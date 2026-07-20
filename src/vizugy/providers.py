from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from .errors import AccessDeniedError, NotFoundError, UpstreamError
from .models import Dataset, DatasetDescription, Field, Provenance
from .retry import upstream_retry


class ArcGISProvider:
    def __init__(self, base_url: str, timeout: float = 15, cache_ttl: float = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.warnings: list[str] = []

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            return await self._fetch(url, path)
        except (NotFoundError, AccessDeniedError):
            raise
        except (httpx.HTTPError, ValueError, UpstreamError) as exc:
            raise UpstreamError(f"ArcGIS request failed: {exc}") from exc

    @upstream_retry(attempts=3, first_delay=0.2)
    async def _fetch(self, url: str, path: str) -> dict[str, Any]:
        response = await self.client.get(url, params={"f": "pjson"})
        response.raise_for_status()
        data = cast(dict[str, Any], response.json())
        if "error" in data:
            code = data["error"].get("code")
            if code == 404:
                raise NotFoundError(path)
            if code in (403, 498, 499):
                raise AccessDeniedError(f"requires ArcGIS authentication (code {code})")
            raise UpstreamError(data["error"].get("message", "ArcGIS error"))
        self._cache[url] = (time.monotonic() + self.cache_ttl, data)
        return data

    def _dataset(self, item: dict[str, Any], version: float | None, source: str) -> Dataset:
        identifier = item["name"]
        return Dataset(
            id=identifier,
            name=identifier.rsplit("/", 1)[-1],
            folder=identifier.rsplit("/", 1)[0] if "/" in identifier else None,
            kind=item["type"],
            provenance=Provenance(
                source_url=source,
                retrieved_at=datetime.now(UTC).isoformat(),
                upstream_version=version,
            ),
        )

    async def list_datasets(self) -> list[Dataset]:
        root = await self._get("services")
        self.warnings = []

        async def public_folder(folder: str) -> dict[str, Any]:
            try:
                return await self._get(f"services/{folder}")
            except (NotFoundError, UpstreamError) as exc:
                self.warnings.append(f"skipped folder {folder}: {exc}")
                return {}

        groups = await asyncio.gather(*(public_folder(folder) for folder in root["folders"]))
        self.warnings.sort()
        items = list(root.get("services", []))
        for group in groups:
            items.extend(group.get("services", []))
        source = f"{self.base_url}/services"
        return sorted(
            (self._dataset(item, root.get("currentVersion"), source) for item in items),
            key=lambda item: item.id.casefold(),
        )

    async def describe(self, dataset_id: str, layer_id: int | None) -> DatasetDescription:
        datasets = await self.list_datasets()
        try:
            dataset = next(item for item in datasets if item.id == dataset_id)
        except StopIteration as exc:
            raise NotFoundError(dataset_id) from exc
        suffix = f"/{layer_id}" if layer_id is not None else ""
        path = f"services/{dataset.id}/{dataset.kind}{suffix}"
        raw = await self._get(path)
        spatial = raw.get("extent", {}).get("spatialReference") or raw.get("spatialReference", {})
        advanced = raw.get("advancedQueryCapabilities", {})
        return DatasetDescription(
            dataset=dataset,
            layer_id=raw.get("id"),
            layer_name=raw.get("name"),
            geometry_type=raw.get("geometryType"),
            crs_wkid=spatial.get("latestWkid") or spatial.get("wkid"),
            max_record_count=raw.get("maxRecordCount"),
            supports_pagination=advanced.get("supportsPagination"),
            fields=[
                Field(name=f["name"], alias=f.get("alias"), type=f["type"], raw=f)
                for f in raw.get("fields", [])
            ],
            raw=raw,
        )
