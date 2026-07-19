from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from vizugy.models import Observation, Provenance, Station
from vizugy.service import VizugyService


def station(station_id: str = "surface:2046", name: str = "Szolnok") -> Station:
    return Station(
        id=station_id,
        registry_number=int(station_id.split(":")[1]),
        name=name,
        watercourse="Tisza",
        municipality="Szolnok",
        latitude=47.17,
        longitude=20.19,
        provenance=Provenance(
            provider="ovf_vraquery",
            source_url="https://example.test/stations",
            retrieved_at="2026-07-17T00:00:00Z",
        ),
    )


def service() -> tuple[VizugyService, AsyncMock]:
    arcgis = AsyncMock()
    vra = AsyncMock()
    vra.stations.return_value = [station()]
    vra.resolve_metric.return_value = {
        "KodAZ": 68,
        "Nev": "Felszíni vízállás",
        "Mertekegyseg": "cm",
    }
    vra.resolve_data_type.return_value = {
        "KodAZ": 101,
        "Nev": "operatív összefésült",
    }
    return VizugyService(arcgis, vra), vra


@pytest.mark.asyncio
async def test_explain_resolves_codes_without_fetching_values() -> None:
    app, vra = service()
    plan = await app.explain_observation_query(
        "Szolnok",
        "water-level",
        "operational",
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 6, tzinfo=UTC),
    )
    assert plan.station_id == "surface:2046"
    assert plan.metric_code == 68
    assert plan.will_fetch is False
    vra.observations.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_raw_query_is_rejected_before_fetch() -> None:
    app, vra = service()
    with pytest.raises(ValueError, match="exceeds 7 days"):
        await app.get_observations(
            "surface:2046",
            "water-level",
            "operational",
            datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
        )
    vra.observations.assert_not_called()


@pytest.mark.asyncio
async def test_aggregate_returns_compact_points_and_envelope_provenance() -> None:
    app, vra = service()
    provenance = station().provenance
    vra.aggregate_observations.return_value = [
        Observation(
            station_id="surface:2046",
            station_registry_number=2046,
            observed_at="2026-06-01T22:00:00Z",
            metric_code=68,
            metric="Felszíni vízállás",
            data_type_code=101,
            data_type="operatív összefésült",
            value=-287,
            unit="cm",
            provenance=provenance,
        )
    ]
    result = await app.aggregate_observations(
        "surface:2046",
        "water-level",
        "operational",
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
        "daily",
        "max",
    )
    assert result.items[0].model_dump() == {
        "observed_at": "2026-06-01T22:00:00Z",
        "value": -287.0,
    }
    assert result.provenance == provenance
    assert result.query.will_fetch is True
