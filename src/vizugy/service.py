import math
from datetime import UTC, datetime, timedelta

from .errors import NotFoundError
from .models import DatasetDescription, Observation, Page, Station, StationPage
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

    async def get_observations(
        self,
        station_query: str,
        metric: str = "water-level",
        data_type: str = "operational",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> tuple[Station, list[Observation]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        page = await self.find_stations(station_query, limit=1000)
        exact = [item for item in page.items if item.id.casefold() == station_query.casefold()]
        if exact:
            station = exact[0]
        elif page.total == 1:
            station = page.items[0]
        elif page.total == 0:
            raise NotFoundError(station_query)
        else:
            matches = ", ".join(f"{item.id} ({item.name})" for item in page.items[:5])
            raise ValueError(f"ambiguous station; use its station ID. Matches: {matches}")
        end = end or datetime.now(UTC)
        start = start or end - timedelta(days=5)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if start >= end:
            raise ValueError("start must be before end")
        return station, await self._vra().observations(
            station, metric, data_type, start, end, limit
        )
