import math
from datetime import UTC, datetime

from .errors import NotFoundError
from .models import (
    Coverage,
    DatasetDescription,
    ObservationResult,
    ObservationPoint,
    Page,
    QueryPlan,
    Station,
    StationPage,
)
from .providers import ArcGISProvider
from .vra_provider import VRAProvider


class VizugyService:
    def __init__(self, provider: ArcGISProvider, vra_provider: VRAProvider | None = None) -> None:
        self.provider = provider
        self.vra_provider = vra_provider

    def _vra(self) -> VRAProvider:
        if self.vra_provider is None:
            raise RuntimeError("VRAQuery provider is not configured")
        return self.vra_provider

    async def close(self) -> None:
        await self.provider.close()
        if self.vra_provider is not None:
            await self.vra_provider.close()

    async def list_datasets(self, query: str | None = None, limit: int = 50) -> Page:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        items = await self.provider.list_datasets()
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in item.id.casefold()]
        selected = items[:limit]
        return Page(
            items=selected,
            returned=len(selected),
            total=len(items),
            limit=limit,
            truncated=len(items) > limit,
            warnings=self.provider.warnings,
        )

    async def describe_dataset(
        self, dataset_id: str, layer_id: int | None = None
    ) -> DatasetDescription:
        return await self.provider.describe(dataset_id, layer_id)

    async def find_stations(
        self,
        query: str | None = None,
        limit: int = 50,
        watercourse: str | None = None,
        municipality: str | None = None,
    ) -> StationPage:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        items = await self._vra().stations()
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    filter(None, [item.id, item.name, item.watercourse, item.municipality])
                ).casefold()
            ]
        if watercourse:
            needle = watercourse.casefold()
            items = [
                item for item in items if item.watercourse and needle in item.watercourse.casefold()
            ]
        if municipality:
            needle = municipality.casefold()
            items = [
                item
                for item in items
                if item.municipality and needle in item.municipality.casefold()
            ]
        items.sort(key=lambda item: (item.name.casefold(), item.id))
        return StationPage(
            items=items[:limit],
            returned=min(len(items), limit),
            total=len(items),
            limit=limit,
            truncated=len(items) > limit,
            warnings=[],
        )

    async def nearest_stations(
        self, latitude: float, longitude: float, limit: int = 5
    ) -> StationPage:
        items = await self._vra().stations()

        def distance(item: Station) -> float:
            lat1, lat2 = math.radians(latitude), math.radians(item.latitude)
            dlat = lat2 - lat1
            dlon = math.radians(item.longitude - longitude)
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        for item in items:
            item.distance_km = distance(item)
        items.sort(key=lambda item: item.distance_km or 0)
        return StationPage(
            items=items[:limit],
            returned=min(len(items), limit),
            total=len(items),
            limit=limit,
            truncated=len(items) > limit,
        )

    async def measurement_catalog(self) -> dict:
        vra = self._vra()
        metrics, data_types = await vra.catalogs()
        return {
            "metrics": metrics,
            "data_types": [item for item in data_types if item.get("Ervenyes")],
            "provenance": {
                "provider": "ovf_vraquery",
                "source_url": f"{vra.base_url}/Base",
                "retrieved_at": datetime.now(UTC).isoformat(),
                "upstream_version": "OpenAPI v1.0.0",
            },
        }

    async def resolve_station(self, station_query: str) -> Station:
        items = await self._vra().stations()
        exact = [item for item in items if item.id.casefold() == station_query.casefold()]
        if exact:
            return exact[0]
        needle = station_query.casefold()
        matches = [
            item
            for item in items
            if needle
            in " ".join(filter(None, [item.name, item.watercourse, item.municipality])).casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise NotFoundError(station_query)
        options = ", ".join(f"{item.id} ({item.name})" for item in matches[:5])
        raise ValueError(f"ambiguous station; use its station ID. Matches: {options}")

    @staticmethod
    def _bounds(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        if start is None or end is None:
            raise ValueError("explicit start and end timestamps are required")
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if start >= end:
            raise ValueError("start must be before end")
        return start, end

    async def explain_observation_query(
        self,
        station_query: str,
        metric: str,
        data_type: str,
        start: datetime | None,
        end: datetime | None,
        *,
        interval: str | None = None,
        operation: str | None = None,
    ) -> QueryPlan:
        start, end = self._bounds(start, end)
        station = await self.resolve_station(station_query)
        metric_item = await self._vra().resolve_metric(metric)
        data_type_item = await self._vra().resolve_data_type(data_type)
        duration = (end - start).total_seconds() / 86400
        warnings = []
        mode = "aggregate" if interval and operation else "raw"
        if mode == "raw" and duration > 7:
            warnings.append("Raw intervals over 7 days are rejected; use aggregation.")
        if mode == "raw" and duration > 3:
            warnings.append("Consider daily aggregation to reduce transfer size.")
        return QueryPlan(
            station=station,
            station_id=station.id,
            station_name=station.name,
            metric_code=metric_item["KodAZ"],
            metric=metric_item["Nev"],
            unit=metric_item.get("Mertekegyseg"),
            data_type_code=data_type_item["KodAZ"],
            data_type=data_type_item["Nev"],
            start=start.astimezone(UTC).isoformat(),
            end=end.astimezone(UTC).isoformat(),
            duration_days=duration,
            mode=mode,
            aggregation=(
                {"interval": interval, "operation": operation} if interval and operation else None
            ),
            source_operation=("TS/TSListFilterShort" if mode == "aggregate" else "TS/TsShortList"),
            warnings=warnings,
        )

    async def inspect_coverage(self, station_query: str, metric: str, data_type: str) -> Coverage:
        station = await self.resolve_station(station_query)
        return await self._vra().coverage(station, metric, data_type)

    async def get_observations(
        self,
        station_query: str,
        metric: str = "water-level",
        data_type: str = "operational",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> ObservationResult:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        plan = await self.explain_observation_query(station_query, metric, data_type, start, end)
        if plan.duration_days > 7:
            raise ValueError("raw interval exceeds 7 days; use observations aggregate")
        start_dt = datetime.fromisoformat(plan.start)
        end_dt = datetime.fromisoformat(plan.end)
        items, total = await self._vra().observations(
            plan.station, metric, data_type, start_dt, end_dt, limit
        )
        plan.will_fetch = True
        provenance = items[0].provenance if items else plan.station.provenance
        return ObservationResult(
            station=plan.station,
            query=plan,
            items=[
                ObservationPoint(observed_at=item.observed_at, value=item.value) for item in items
            ],
            returned=len(items),
            truncated=total > len(items),
            provenance=provenance,
            warnings=plan.warnings,
        )

    async def aggregate_observations(
        self,
        station_query: str,
        metric: str,
        data_type: str,
        start: datetime | None,
        end: datetime | None,
        interval: str,
        operation: str,
    ) -> ObservationResult:
        intervals = {"daily", "tenday", "monthly", "yearly"}
        operations = {"min", "max", "avg", "sum", "cnt", "mean", "cntday"}
        if interval not in intervals:
            raise ValueError(f"interval must be one of: {', '.join(sorted(intervals))}")
        if operation not in operations:
            raise ValueError(f"operation must be one of: {', '.join(sorted(operations))}")
        plan = await self.explain_observation_query(
            station_query,
            metric,
            data_type,
            start,
            end,
            interval=interval,
            operation=operation,
        )
        max_buckets = {
            "daily": plan.duration_days + 2,
            "tenday": plan.duration_days / 10 + 2,
            "monthly": plan.duration_days / 28 + 2,
            "yearly": plan.duration_days / 365 + 2,
        }[interval]
        if max_buckets > 1000:
            raise ValueError("aggregation may exceed 1000 buckets; narrow the interval")
        items = await self._vra().aggregate_observations(
            plan.station,
            metric,
            data_type,
            datetime.fromisoformat(plan.start),
            datetime.fromisoformat(plan.end),
            interval,
            operation,
        )
        plan.will_fetch = True
        warnings = [
            "VRAQuery aggregation buckets follow upstream hydrological/local-day boundaries; "
            "returned timestamps are UTC bucket labels."
        ]
        provenance = items[0].provenance if items else plan.station.provenance
        return ObservationResult(
            station=plan.station,
            query=plan,
            items=[
                ObservationPoint(observed_at=item.observed_at, value=item.value) for item in items
            ],
            returned=len(items),
            provenance=provenance,
            warnings=warnings,
        )
