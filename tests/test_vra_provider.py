from datetime import UTC, datetime

import httpx
import pytest

from vizugy.vra_provider import VRAProvider


@pytest.mark.asyncio
async def test_openapi_provider_maps_catalog_units_and_observations():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "test"})
        if request.url.path.endswith("/Vra/InternetVmo/11/true"):
            return httpx.Response(
                200,
                json=[
                    {
                        "Tsz": 1,
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
                    }
                ],
            )
        if request.url.path.endswith("/Base/AdatFajta"):
            return httpx.Response(
                200,
                json=[
                    {
                        "KodAZ": 68,
                        "Nev": "Felszíni vízállás",
                        "Mertekegyseg": "cm",
                        "Minimum": -1000,
                        "Maximum": 13000,
                        "KodSorszam": 5,
                    }
                ],
            )
        if request.url.path.endswith("/Base/AdatTipus"):
            return httpx.Response(
                200,
                json=[
                    {
                        "KodAZ": 101,
                        "Nev": "operatív összefésült",
                        "Ervenyes": True,
                        "KodSorszam": 18,
                    }
                ],
            )
        if request.url.path.endswith("/TS/TsShortList"):
            return httpx.Response(
                200,
                json=[
                    {
                        "ItemId": 0,
                        "TsItemList": [{"UTCTime": "2026-07-17T12:00:00Z", "Adat": 51.0}],
                    }
                ],
            )
        return httpx.Response(404)

    provider = VRAProvider("https://api.test", "https://auth.test/token")
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        station = (await provider.stations())[0]
        observations = await provider.observations(
            station,
            "water-level",
            "operational",
            datetime(2026, 7, 16, tzinfo=UTC),
            datetime(2026, 7, 18, tzinfo=UTC),
            100,
        )
        assert station.id == "surface:1"
        assert observations[0].unit == "cm"
        assert observations[0].value == 51
        assert observations[0].data_type_code == 101
    finally:
        await provider.close()
