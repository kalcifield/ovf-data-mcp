import asyncio
import math
from datetime import UTC, datetime
from typing import Any, Literal

from zoneinfo import ZoneInfo

from .errors import NotFoundError, UpstreamError
from .models import (
    Coverage,
    DatasetDescription,
    DepthSeries,
    Observation,
    ObservationResult,
    ObservationPoint,
    Page,
    QueryPlan,
    SoilDepthComparison,
    Station,
    StationPage,
)
from .providers import ArcGISProvider
from .vra_provider import NETWORKS, VRAProvider


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
        network: str = "surface",
        metric: str | None = None,
    ) -> StationPage:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        items = (
            await self._vra().stations_with_metric(network, metric)
            if metric
            else await self._vra().stations(network)
        )
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
        self,
        latitude: float,
        longitude: float,
        limit: int = 5,
        network: str = "surface",
        metric: str | None = None,
    ) -> StationPage:
        items = (
            await self._vra().stations_with_metric(network, metric)
            if metric
            else await self._vra().stations(network)
        )

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

    async def measurement_catalog(self) -> dict[str, Any]:
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
        needle = station_query.casefold()
        matched = next(
            (name for name, (_, prefix) in NETWORKS.items() if needle.startswith(f"{prefix}:")),
            None,
        )
        networks = [matched] if matched else list(NETWORKS)
        for network in networks:
            items = await self._vra().stations(network)
            exact = [item for item in items if item.id.casefold() == needle]
            if exact:
                return exact[0]
            matches = [
                item
                for item in items
                if needle
                in " ".join(
                    filter(None, [item.name, item.watercourse, item.municipality])
                ).casefold()
            ]
            if len(matches) == 1:
                return matches[0]
            if matches:
                options = ", ".join(f"{item.id} ({item.name})" for item in matches[:5])
                raise ValueError(f"ambiguous station; use its station ID. Matches: {options}")
        raise NotFoundError(station_query)

    @staticmethod
    def _network_metric(station: Station, metric: str) -> str:
        # Network-specific stations do not carry surface water level (68); map the
        # generic default to their primary metric instead of returning an empty series.
        if metric.casefold() == "water-level":
            if station.id.startswith("well:"):
                return "groundwater-level"
            if station.id.startswith("deep-well:"):
                return "layer-water-level"
            if station.id.startswith("precip:"):
                return "precipitation"
        return metric

    @staticmethod
    def _bucket_floor(moment: datetime, interval: str) -> datetime:
        # Upstream buckets start at Europe/Budapest local boundaries; splitting anywhere
        # else would compute the straddling bucket twice from partial ranges.
        local = moment.astimezone(ZoneInfo("Europe/Budapest"))
        if interval == "yearly":
            local = local.replace(month=1)
        if interval in {"yearly", "monthly", "tenday"}:
            local = local.replace(day=1)
        local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return local.astimezone(UTC)

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
        data_ext: int | None = None,
        depth_cm: int | None = None,
        *,
        interval: str | None = None,
        operation: str | None = None,
    ) -> QueryPlan:
        start, end = self._bounds(start, end)
        station = await self.resolve_station(station_query)
        metric = self._network_metric(station, metric)
        metric_item = await self._vra().resolve_metric(metric)
        data_ext, dimensions = self._resolve_dimension(metric_item, data_ext, depth_cm)
        data_type_item = await self._vra().resolve_data_type(data_type)
        duration = (end - start).total_seconds() / 86400
        warnings: list[str] = []
        mode: Literal["raw", "aggregate"] = "aggregate" if interval and operation else "raw"
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
            data_ext=data_ext,
            dimensions=dimensions,
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
        return await self._vra().coverage(station, self._network_metric(station, metric), data_type)

    async def get_observations(
        self,
        station_query: str,
        metric: str = "water-level",
        data_type: str = "operational",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
        include_quality: bool = False,
        data_ext: int | None = None,
        depth_cm: int | None = None,
    ) -> ObservationResult:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        plan = await self.explain_observation_query(
            station_query, metric, data_type, start, end, data_ext, depth_cm
        )
        if plan.duration_days > 7:
            raise ValueError("raw interval exceeds 7 days; use observations aggregate")
        start_dt = datetime.fromisoformat(plan.start)
        end_dt = datetime.fromisoformat(plan.end)
        items, total = await self._vra().observations(
            plan.station,
            self._network_metric(plan.station, metric),
            data_type,
            start_dt,
            end_dt,
            limit,
            include_quality=include_quality,
            data_ext=plan.data_ext,
        )
        plan.will_fetch = True
        provenance = items[0].provenance if items else plan.station.provenance
        warnings = list(plan.warnings)
        if not items:
            warnings.append(await self._empty_observation_warning(plan))
        return ObservationResult(
            station=plan.station,
            query=plan,
            items=[
                ObservationPoint(
                    observed_at=item.observed_at,
                    value=item.value,
                    quality_code=item.quality_code,
                    quality=item.quality,
                    field_quality_code=item.field_quality_code,
                    field_quality=item.field_quality,
                    data_ext=item.data_ext,
                    dimensions=item.dimensions,
                )
                for item in items
            ],
            returned=len(items),
            truncated=total > len(items),
            provenance=provenance,
            warnings=warnings,
        )

    async def _empty_observation_warning(self, plan: QueryPlan) -> str:
        try:
            coverage = await self._vra().available_data_types(plan.station, str(plan.metric_code))
        except UpstreamError:
            # A secondary diagnostic failure must not hide the valid empty query response.
            return (
                f"No observations returned for {plan.data_type} ({plan.data_type_code}); "
                "coverage diagnostics were temporarily unavailable."
            )
        requested = next((item for item in coverage if item["code"] == plan.data_type_code), None)
        if requested:
            detail = (
                f"documented coverage is {requested['available_from']} to "
                f"{requested['available_until']}"
            )
        else:
            detail = "no documented coverage exists for this station and metric"
        alternatives = [item for item in coverage if item["code"] != plan.data_type_code]
        if not alternatives:
            return (
                f"No observations returned for {plan.data_type} ({plan.data_type_code}); {detail}."
            )
        choices = ", ".join(
            f"{item['name']} ({item['code']}, {item['available_from']} to "
            f"{item['available_until']})"
            for item in alternatives
        )
        return (
            f"No observations returned for {plan.data_type} ({plan.data_type_code}); {detail}. "
            f"Other data types with documented coverage: {choices}. Specify data_type explicitly "
            f"(CLI: --data-type NAME)."
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
        data_ext: int | None = None,
        depth_cm: int | None = None,
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
            data_ext=data_ext,
            depth_cm=depth_cm,
        )
        max_buckets = {
            "daily": plan.duration_days + 2,
            "tenday": plan.duration_days / 10 + 2,
            "monthly": plan.duration_days / 28 + 2,
            "yearly": plan.duration_days / 365 + 2,
        }[interval]
        if max_buckets > 1000:
            raise ValueError("aggregation may exceed 1000 buckets; narrow the interval")
        chunks = 0

        async def fetch(
            chunk_start: datetime, chunk_end: datetime, depth: int
        ) -> list[Observation]:
            nonlocal chunks
            try:
                result = await self._vra().aggregate_observations(
                    plan.station,
                    self._network_metric(plan.station, metric),
                    data_type,
                    chunk_start,
                    chunk_end,
                    interval,
                    operation,
                    plan.data_ext,
                )
                chunks += 1
                return result
            except UpstreamError:
                # Multi-decade windows can exceed the upstream timeout; bisect at a bucket
                # boundary and retry. Short windows fail fast so outages don't fan out.
                if depth >= 3 or (chunk_end - chunk_start).days <= 730:
                    raise
                mid = self._bucket_floor(chunk_start + (chunk_end - chunk_start) / 2, interval)
                if not chunk_start < mid < chunk_end:
                    raise
                # A timed-out query still costs the server; pause before asking again.
                await asyncio.sleep(2 * (depth + 1))
                return await fetch(chunk_start, mid, depth + 1) + await fetch(
                    mid, chunk_end, depth + 1
                )

        items = await fetch(datetime.fromisoformat(plan.start), datetime.fromisoformat(plan.end), 0)
        plan.will_fetch = True
        warnings = [
            "VRAQuery aggregation buckets follow upstream hydrological/local-day boundaries; "
            "returned timestamps are UTC bucket labels."
        ]
        if not items:
            warnings.append(await self._empty_observation_warning(plan))
        if chunks > 1:
            warnings.append(
                f"window exceeded an upstream limit and was fetched in {chunks} chunked requests"
            )
        provenance = items[0].provenance if items else plan.station.provenance
        return ObservationResult(
            station=plan.station,
            query=plan,
            items=[
                ObservationPoint(
                    observed_at=item.observed_at,
                    value=item.value,
                    data_ext=item.data_ext,
                    dimensions=item.dimensions,
                )
                for item in items
            ],
            returned=len(items),
            provenance=provenance,
            warnings=warnings,
        )

    @staticmethod
    def _resolve_dimension(
        metric: dict[str, Any], data_ext: int | None, depth_cm: int | None
    ) -> tuple[int | None, dict[str, int]]:
        if data_ext is not None and depth_cm is not None:
            raise ValueError("specify either data_ext or depth_cm, not both")
        if depth_cm is not None:
            if metric["KodAZ"] not in {299, 303}:
                raise ValueError("depth_cm is only defined for soil moisture and soil temperature")
            if depth_cm not in {10, 20, 30, 45, 60, 75}:
                raise ValueError("depth_cm must be one of: 10, 20, 30, 45, 60, 75")
            return depth_cm, {"depth_cm": depth_cm}
        return data_ext, {}

    async def compare_soil_depths(
        self,
        station_query: str,
        start: datetime | None,
        end: datetime | None,
        depths_cm: list[int] | None = None,
        metric: str = "soil-moisture",
        data_type: str = "operational",
        interval: str = "daily",
        operation: str = "avg",
    ) -> SoilDepthComparison:
        start, end = self._bounds(start, end)
        depths = depths_cm or [10, 20, 30, 45, 60, 75]
        if not depths or len(depths) != len(set(depths)):
            raise ValueError("depths_cm must contain unique depths")
        invalid = sorted(set(depths) - {10, 20, 30, 45, 60, 75})
        if invalid:
            raise ValueError("depths_cm must use: 10, 20, 30, 45, 60, 75")
        if interval not in {"daily", "tenday", "monthly", "yearly"}:
            raise ValueError("invalid aggregation interval")
        if operation not in {"min", "max", "avg", "sum", "cnt", "mean", "cntday"}:
            raise ValueError("invalid aggregation operation")
        duration_days = (end - start).total_seconds() / 86400
        max_buckets = {
            "daily": duration_days + 2,
            "tenday": duration_days / 10 + 2,
            "monthly": duration_days / 28 + 2,
            "yearly": duration_days / 365 + 2,
        }[interval]
        if max_buckets * len(depths) > 1000:
            raise ValueError(
                "depth comparison may exceed 1000 total points; narrow the interval or depths"
            )
        station = await self.resolve_station(station_query)
        by_depth, metric_item = await self._vra().aggregate_depths(
            station, metric, data_type, start, end, depths, interval, operation
        )
        all_items = [item for items in by_depth.values() for item in items]
        provenance = all_items[0].provenance if all_items else station.provenance
        missing = [str(depth) for depth in depths if not by_depth[depth]]
        warnings = []
        if missing:
            warnings.append(
                "No observations in the requested interval at depths (cm): " + ", ".join(missing)
            )
        return SoilDepthComparison(
            station=station,
            metric_code=metric_item["KodAZ"],
            metric=metric_item["Nev"],
            unit=metric_item.get("Mertekegyseg"),
            depths_cm=depths,
            series=[
                DepthSeries(
                    depth_cm=depth,
                    items=[
                        ObservationPoint(
                            observed_at=item.observed_at,
                            value=item.value,
                            data_ext=item.data_ext,
                            dimensions=item.dimensions,
                        )
                        for item in by_depth[depth]
                    ],
                    returned=len(by_depth[depth]),
                )
                for depth in depths
            ],
            start=start.astimezone(UTC).isoformat(),
            end=end.astimezone(UTC).isoformat(),
            aggregation={
                "period": interval,
                "operation": operation,
                "performed_by": "upstream",
            },
            dimension={
                "source_field": "DataExt",
                "interpretation": "depth_cm",
                "basis": "verified VRA soil-metric behavior",
            },
            provenance=provenance,
            warnings=warnings,
        )
