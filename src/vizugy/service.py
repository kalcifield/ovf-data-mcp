from .models import DatasetDescription, Page
from .providers import ArcGISProvider


class VizugyService:
    def __init__(self, provider: ArcGISProvider) -> None:
        self.provider = provider

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

    async def describe_dataset(self, dataset_id: str, layer_id: int | None = None) -> DatasetDescription:
        return await self.provider.describe(dataset_id, layer_id)
