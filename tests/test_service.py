import json
from pathlib import Path

import httpx
import pytest

from vizugy.errors import NotFoundError, UpstreamError
from vizugy.providers import ArcGISProvider
from vizugy.service import VizugyService


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def provider_with(routes: dict[str, tuple[int, dict]]) -> ArcGISProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(
            request.url.path, (404, {"error": {"code": 404, "message": "missing"}})
        )
        return httpx.Response(status, json=body)

    provider = ArcGISProvider("https://example.test/arcgis/rest", cache_ttl=300)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_discovery_normalizes_and_bounds_results():
    provider = provider_with(
        {
            "/arcgis/rest/services": (200, fixture("services.json")),
            "/arcgis/rest/services/VIR": (200, fixture("vir.json")),
        }
    )
    try:
        page = await VizugyService(provider).list_datasets(limit=1)
        assert page.total == 2
        assert page.returned == 1
        assert page.truncated is True
        assert page.items[0].provenance.provider == "ovf_arcgis"
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_layer_mapping_preserves_raw_schema():
    provider = provider_with(
        {
            "/arcgis/rest/services": (200, fixture("services.json")),
            "/arcgis/rest/services/VIR": (200, fixture("vir.json")),
            "/arcgis/rest/services/VIR/Stations/MapServer/6": (200, fixture("layer.json")),
        }
    )
    try:
        result = await VizugyService(provider).describe_dataset("VIR/Stations", 6)
        assert result.crs_wkid == 3857
        assert result.supports_pagination is False
        assert result.fields[0].alias == "Név"
        assert result.fields[0].raw["length"] == 200
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_not_found_is_domain_error():
    provider = provider_with(
        {
            "/arcgis/rest/services": (200, fixture("services.json")),
            "/arcgis/rest/services/VIR": (200, fixture("vir.json")),
        }
    )
    try:
        with pytest.raises(NotFoundError):
            await VizugyService(provider).describe_dataset("nope", None)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_upstream_error_after_retries():
    provider = provider_with({"/arcgis/rest/services": (503, {"message": "down"})})
    try:
        with pytest.raises(UpstreamError):
            await provider.list_datasets()
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_protected_folder_becomes_explicit_warning():
    provider = provider_with(
        {
            "/arcgis/rest/services": (200, fixture("services.json")),
            "/arcgis/rest/services/VIR": (
                200,
                {"error": {"code": 499, "message": "Token Required"}},
            ),
        }
    )
    try:
        page = await VizugyService(provider).list_datasets()
        assert page.total == 1
        assert "requires ArcGIS authentication" in page.warnings[0]
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_long_aggregate_windows_bisect_on_upstream_failure():
    import json as jsonlib
    from datetime import datetime, timedelta

    from vizugy.vra_provider import VRAProvider

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path.endswith("/Vra/InternetVmo/11/true"):
            return httpx.Response(
                200,
                json=[{"Tsz": 1, "Nev": "Rajka", "Lat": 48.0, "Lon": 17.2, "Telepules": "Rajka"}],
            )
        if path.endswith("/Base/AdatFajta"):
            return httpx.Response(
                200, json=[{"KodAZ": 68, "Nev": "Felszíni vízállás", "Mertekegyseg": "cm"}]
            )
        if path.endswith("/Base/AdatTipus"):
            return httpx.Response(
                200, json=[{"KodAZ": 101, "Nev": "operatív összefésült", "Ervenyes": True}]
            )
        if path.endswith("/TS/TSListFilterShort"):
            body = jsonlib.loads(request.content)
            f = body["Filters"][0]
            start = datetime.fromisoformat(f["StartTime"])
            end = datetime.fromisoformat(f["EndTime"])
            calls.append((start, end))
            if end - start > timedelta(days=15 * 365):
                return httpx.Response(500)  # upstream chokes on long windows
            years = []
            y = start.year
            while y < end.year:
                years.append({"UTCTime": f"{y}-12-31T23:00:00Z", "Adat": float(y)})
                y += 1
            return httpx.Response(
                200, json=[{"FilteredResponse": [{"Torzsszam": 1, "TsItemList": years}]}]
            )
        return httpx.Response(404)

    arcgis = provider_with({})
    vra = VRAProvider("https://api.test", "https://auth.test/token")
    vra.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = VizugyService(arcgis, vra)
    try:
        result = await service.aggregate_observations(
            "surface:1",
            "water-level",
            "operational",
            datetime(1990, 1, 1, tzinfo=__import__("datetime").UTC),
            datetime(2020, 1, 1, tzinfo=__import__("datetime").UTC),
            "yearly",
            "avg",
        )
        assert len(result.items) == 30
        observed = [item.observed_at for item in result.items]
        assert len(observed) == len(set(observed))  # no duplicated buckets at the split
        assert any("chunked" in w for w in result.warnings)
        assert len(calls) >= 3  # one failed full-window attempt plus the halves
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_protected_arcgis_folder_fails_fast_without_retries():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if request.url.path.endswith("/services"):
            return httpx.Response(
                200, json={"currentVersion": 10.61, "folders": ["TIVIZIG"], "services": []}
            )
        return httpx.Response(200, json={"error": {"code": 499, "message": "Token Required"}})

    provider = ArcGISProvider("https://example.test/arcgis/rest", cache_ttl=300)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        page = await VizugyService(provider).list_datasets()
        assert page.total == 0
        assert any("requires ArcGIS authentication" in w for w in page.warnings)
        folder_attempts = [p for p in attempts if p.endswith("/TIVIZIG")]
        assert len(folder_attempts) == 1  # deterministic auth error: no retries
    finally:
        await provider.close()
