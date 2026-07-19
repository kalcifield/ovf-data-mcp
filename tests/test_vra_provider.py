import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeAlias

import httpx
import pytest

from vizugy.errors import UpstreamError
from vizugy.vra_provider import VRAProvider

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
Route: TypeAlias = JsonValue | Callable[[httpx.Request], httpx.Response]


def station_payload(registry_number: int = 1, **overrides: JsonValue) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "Tsz": registry_number,
        "Nev": "Rajka",
        "Vizig": 1,
        "Uzem": True,
        "Lat": 48.004,
        "Lon": 17.247,
        "MdrNev": "Duna",
        "Telepules": "Rajka",
        "KF1": 500,
        "KF2": 600,
        "KF3": 650,
        "Fkm": 1848.4,
        "LKV": -70,
        "LNV": 891,
    }
    payload.update(overrides)
    return payload


def metric_payload() -> dict[str, JsonValue]:
    return {
        "KodAZ": 68,
        "Nev": "Felszíni vízállás",
        "Mertekegyseg": "cm",
        "Minimum": -1000,
        "Maximum": 13000,
        "KodSorszam": 5,
    }


def data_type_payload() -> dict[str, JsonValue]:
    return {
        "KodAZ": 101,
        "Nev": "operatív összefésült",
        "Ervenyes": True,
        "KodSorszam": 18,
    }


def provider_with(
    routes: dict[str, Route],
) -> tuple[VRAProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "test"})
        route = routes.get(request.url.path)
        if callable(route):
            return route(request)
        if route is not None:
            return httpx.Response(200, json=route)
        return httpx.Response(404)

    provider = VRAProvider("https://api.test", "https://auth.test/token")
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider, requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("network", "vmo_code", "prefix"),
    [
        ("surface", 11, "surface"),
        ("wells", 12, "well"),
        ("deep-wells", 13, "deep-well"),
        ("precipitation", 14, "precip"),
    ],
)
async def test_station_networks_map_vmo_codes_and_namespaces(
    network: str, vmo_code: int, prefix: str
) -> None:
    path = f"/Vra/InternetVmo/{vmo_code}/true"
    payload = station_payload(502)
    provider, requests = provider_with({path: [payload]})
    try:
        stations = await provider.stations(network)
    finally:
        await provider.close()

    assert stations[0].id == f"{prefix}:502"
    assert stations[0].thresholds == {"level_1": 500.0, "level_2": 600.0, "level_3": 650.0}
    assert stations[0].river_km == 1848.4
    assert stations[0].record_low == -70.0
    assert stations[0].record_high == 891.0
    assert stations[0].raw == payload
    assert requests[-1].url.path == path


@pytest.mark.asyncio
async def test_unknown_station_network_is_rejected_before_request() -> None:
    provider, requests = provider_with({})
    try:
        with pytest.raises(ValueError, match="unknown network"):
            await provider.stations("boreholes")
    finally:
        await provider.close()

    assert requests == []


@pytest.mark.asyncio
async def test_observations_send_filter_and_map_compact_values() -> None:
    provider, requests = provider_with(
        {
            "/Vra/InternetVmo/11/true": [station_payload()],
            "/Base/AdatFajta": [metric_payload()],
            "/Base/AdatTipus": [data_type_payload()],
            "/TS/TsShortList": [
                {
                    "ItemId": 0,
                    "TsItemList": [{"UTCTime": "2026-07-17T12:00:00Z", "Adat": 51.0}],
                }
            ],
        }
    )
    try:
        station = (await provider.stations())[0]
        observations, total = await provider.observations(
            station,
            "water-level",
            "operational",
            datetime(2026, 7, 16, tzinfo=UTC),
            datetime(2026, 7, 18, tzinfo=UTC),
            100,
        )
    finally:
        await provider.close()

    request = next(item for item in requests if item.url.path.endswith("/TS/TsShortList"))
    assert json.loads(request.content) == {
        "TorzsszamList": [1],
        "AdatFajtaKod": 68,
        "AdatTipusKod": 101,
        "StartTime": "2026-07-16T00:00:00+00:00",
        "EndTime": "2026-07-18T00:00:00+00:00",
    }
    assert total == 1
    assert observations[0].model_dump(exclude={"provenance", "raw"}) == {
        "station_id": "surface:1",
        "station_registry_number": 1,
        "observed_at": "2026-07-17T12:00:00Z",
        "metric_code": 68,
        "metric": "Felszíni vízállás",
        "data_type_code": 101,
        "data_type": "operatív összefésült",
        "value": 51.0,
        "unit": "cm",
        "quality_code": None,
        "quality": None,
        "field_quality_code": None,
        "field_quality": None,
    }


@pytest.mark.asyncio
async def test_quality_observations_use_long_format_and_decode_codes() -> None:
    provider, requests = provider_with(
        {
            "/Vra/InternetVmo/11/true": [station_payload()],
            "/Base/AdatFajta": [metric_payload()],
            "/Base/AdatTipus": [data_type_payload()],
            "/Base/AdatMinosites": [{"KodAZ": 3, "Nev": "gyanús", "KodSorszam": 3}],
            "/Base/MezoMinosites": [{"KodAZ": 8, "Nev": "mért adat", "KodSorszam": 8}],
            "/TS/TsLongList": [
                {
                    "ItemId": 0,
                    "TsItemList": [
                        {
                            "UTCTime": "2026-07-17T12:00:00Z",
                            "Adat": 51.0,
                            "AMKod": 3,
                            "MMKod": 8,
                        }
                    ],
                }
            ],
        }
    )
    try:
        station = (await provider.stations())[0]
        observations, _ = await provider.observations(
            station,
            "water-level",
            "operational",
            datetime(2026, 7, 16, tzinfo=UTC),
            datetime(2026, 7, 18, tzinfo=UTC),
            100,
            include_quality=True,
        )
    finally:
        await provider.close()

    assert not any(item.url.path.endswith("/TS/TsShortList") for item in requests)
    first = observations[0]
    assert (first.quality_code, first.quality) == (3, "gyanús")
    assert (first.field_quality_code, first.field_quality) == (8, "mért adat")


@pytest.mark.asyncio
async def test_coverage_falls_back_from_composed_operational_type() -> None:
    def coverage_response(request: httpx.Request) -> httpx.Response:
        if request.url.params["atKod"] == "101":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "HAFKod": 68,
                    "ATKod": 100,
                    "Torzsszam": 1,
                    "UTCTimeMin": "1950-01-01T07:00:00Z",
                    "UTCTimeMax": "2026-07-17T02:00:00Z",
                }
            ],
        )

    provider, requests = provider_with(
        {
            "/Vra/InternetVmo/11/true": [station_payload()],
            "/Base/AdatFajta": [metric_payload()],
            "/Base/AdatTipus": [data_type_payload()],
            "/Base/DataCatalogMinMax": coverage_response,
        }
    )
    try:
        station = (await provider.stations())[0]
        coverage = await provider.coverage(station, "water-level", "operational")
    finally:
        await provider.close()

    coverage_requests = [
        item for item in requests if item.url.path.endswith("/Base/DataCatalogMinMax")
    ]
    assert [item.url.params["atKod"] for item in coverage_requests] == ["101", "0"]
    assert all(json.loads(item.content) == [1] for item in coverage_requests)
    assert coverage.coverage_data_type_code == 100
    assert coverage.available_from == "1950-01-01T07:00:00Z"
    assert coverage.warnings


@pytest.mark.asyncio
async def test_aggregation_sends_bucket_operation_and_maps_response() -> None:
    provider, requests = provider_with(
        {
            "/Vra/InternetVmo/11/true": [station_payload()],
            "/Base/AdatFajta": [metric_payload()],
            "/Base/AdatTipus": [data_type_payload()],
            "/TS/TSListFilterShort": [
                {
                    "FilterID": 1,
                    "FilteredResponse": [
                        {
                            "Torzsszam": 1,
                            "TsItemList": [{"UTCTime": "2026-07-16T22:00:00Z", "Adat": 52.0}],
                        }
                    ],
                }
            ],
        }
    )
    try:
        station = (await provider.stations())[0]
        aggregates = await provider.aggregate_observations(
            station,
            "water-level",
            "operational",
            datetime(2026, 7, 16, tzinfo=UTC),
            datetime(2026, 7, 18, tzinfo=UTC),
            "daily",
            "max",
        )
    finally:
        await provider.close()

    request = next(item for item in requests if item.url.path.endswith("/TS/TSListFilterShort"))
    body = json.loads(request.content)
    assert body["Filters"][0]["AggregateFilters"] == {
        "RangeType": "daily",
        "AggregateType": "max",
        "AggregateRangePosition": "none",
    }
    assert aggregates[0].observed_at == "2026-07-16T22:00:00Z"
    assert aggregates[0].value == 52


@pytest.mark.asyncio
async def test_catalogs_are_cached() -> None:
    provider, requests = provider_with(
        {"/Base/AdatFajta": [metric_payload()], "/Base/AdatTipus": [data_type_payload()]}
    )
    try:
        first = await provider.catalogs()
        second = await provider.catalogs()
    finally:
        await provider.close()

    catalog_paths = [item.url.path for item in requests if item.url.path.startswith("/Base/")]
    assert catalog_paths == ["/Base/AdatFajta", "/Base/AdatTipus"]
    assert first == second == ([metric_payload()], [data_type_payload()])


@pytest.mark.asyncio
async def test_unauthorized_response_refreshes_token_once() -> None:
    token_count = 0
    api_count = 0
    authorizations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_count, token_count
        if request.url.path == "/token":
            token_count += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{token_count}", "expires_in": 3600},
            )
        api_count += 1
        authorizations.append(request.headers["Authorization"])
        if api_count == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=[station_payload()])

    provider = VRAProvider("https://api.test", "https://auth.test/token")
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        stations = await provider.stations()
    finally:
        await provider.close()

    assert stations[0].id == "surface:1"
    assert token_count == 2
    assert authorizations == ["Bearer token-1", "Bearer token-2"]


@pytest.mark.asyncio
async def test_invalid_wire_response_becomes_upstream_error() -> None:
    provider, _ = provider_with({"/Vra/InternetVmo/11/true": [{"Tsz": "not-an-integer"}]})
    try:
        with pytest.raises(UpstreamError, match="VRAQuery request failed"):
            await provider.stations()
    finally:
        await provider.close()
