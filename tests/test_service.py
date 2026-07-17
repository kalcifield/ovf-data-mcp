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
        assert "Token Required" in page.warnings[0]
    finally:
        await provider.close()
