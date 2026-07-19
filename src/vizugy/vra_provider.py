from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar, cast

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ._generated.vra_models import (
    AdatFajta,
    AdatMinosites,
    AdatTipus,
    DataCatalogMinMax,
    InternetVMO,
    MezoMinosites,
    TSLongResponse,
    TSShortItemDTResponseTSListFilter,
    TSShortResponse,
)
from .errors import UpstreamError
from .models import Coverage, Observation, Provenance, Station


# VRAQuery VMO type code and station-ID namespace per network.
NETWORKS = {
    "surface": (11, "surface"),
    "wells": (12, "well"),
    # Verified live 2026-07: vmo 13 stations all carry Rétegvízszint (70) series,
    # vmo 14 stations all carry Csapadékösszeg (71) series.
    "deep-wells": (13, "deep-well"),
    "precipitation": (14, "precip"),
}

T = TypeVar("T")


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: str


@dataclass(frozen=True)
class WireResponse(Generic[T]):
    value: T
    raw: object


TOKEN_RESPONSE = TypeAdapter(TokenResponse)
METRICS_RESPONSE = TypeAdapter(list[AdatFajta])
DATA_TYPES_RESPONSE = TypeAdapter(list[AdatTipus])
STATIONS_RESPONSE = TypeAdapter(list[InternetVMO])
OBSERVATIONS_RESPONSE = TypeAdapter(list[TSShortResponse])
LONG_OBSERVATIONS_RESPONSE = TypeAdapter(list[TSLongResponse])
DATA_QUALITY_RESPONSE = TypeAdapter(list[AdatMinosites])
FIELD_QUALITY_RESPONSE = TypeAdapter(list[MezoMinosites])
COVERAGE_RESPONSE = TypeAdapter(list[DataCatalogMinMax])
AGGREGATES_RESPONSE = TypeAdapter(list[TSShortItemDTResponseTSListFilter])


class VRAProvider:
    """Client for the public VRAQuery OpenAPI 3.0.1 service."""

    def __init__(
        self,
        base_url: str = "https://vmservice.vizugy.hu/vraquery",
        token_url: str = "https://data.vizugy.hu/AuthApi/auth/token",
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        # Identify ourselves so OVF can attribute and contact this traffic.
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "ovf-data-mcp (+https://github.com/kalcifield/ovf-data-mcp)"},
        )
        self._token: str | None = None
        self._metrics: list[dict[str, Any]] | None = None
        self._data_types: list[dict[str, Any]] | None = None
        self._quality_names: dict[str, dict[int, str]] | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def _headers(self) -> dict[str, str]:
        if self._token is None:
            response = await self.client.get(
                self.token_url,
                headers={"Origin": "https://data.vizugy.hu", "Referer": "https://data.vizugy.hu/"},
            )
            response.raise_for_status()
            self._token = TOKEN_RESPONSE.validate_python(response.json()).access_token
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self, method: str, path: str, adapter: TypeAdapter[T], **kwargs: Any
    ) -> WireResponse[T]:
        try:
            response = await self.client.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                headers=await self._headers(),
                **kwargs,
            )
            if response.status_code == 401:
                self._token = None
                response = await self.client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=await self._headers(),
                    **kwargs,
                )
            response.raise_for_status()
            raw: object = response.json()
            return WireResponse(value=adapter.validate_python(raw), raw=raw)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # str() of httpx timeout exceptions is often empty; fall back to the class name.
            detail = str(exc) or type(exc).__name__
            raise UpstreamError(f"VRAQuery request failed: {detail}") from exc

    async def catalogs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self._metrics is None:
            metrics_response = await self._request("GET", "Base/AdatFajta", METRICS_RESPONSE)
            self._metrics = cast(list[dict[str, Any]], metrics_response.raw)
        if self._data_types is None:
            data_types_response = await self._request("GET", "Base/AdatTipus", DATA_TYPES_RESPONSE)
            self._data_types = cast(list[dict[str, Any]], data_types_response.raw)
        return self._metrics, self._data_types

    async def quality_names(self) -> dict[str, dict[int, str]]:
        if self._quality_names is None:
            data = await self._request("GET", "Base/AdatMinosites", DATA_QUALITY_RESPONSE)
            field = await self._request("GET", "Base/MezoMinosites", FIELD_QUALITY_RESPONSE)
            self._quality_names = {
                "data": {item.KodAZ: item.Nev for item in data.value if item.KodAZ and item.Nev},
                "field": {item.KodAZ: item.Nev for item in field.value if item.KodAZ and item.Nev},
            }
        return self._quality_names

    async def stations(self, network: str = "surface") -> list[Station]:
        if network not in NETWORKS:
            raise ValueError(f"unknown network: {network}; expected one of: {', '.join(NETWORKS)}")
        vmo_type, prefix = NETWORKS[network]
        response = await self._request("GET", f"Vra/InternetVmo/{vmo_type}/true", STATIONS_RESPONSE)
        data = cast(list[dict[str, Any]], response.raw)
        source = f"{self.base_url}/Vra/InternetVmo/{vmo_type}/true"
        retrieved = datetime.now(UTC).isoformat()
        return [
            Station(
                id=f"{prefix}:{item['Tsz']}",
                registry_number=item["Tsz"],
                name=item["Nev"],
                watercourse=item.get("MdrNev"),
                municipality=item.get("Telepules"),
                latitude=item["Lat"],
                longitude=item["Lon"],
                river_km=item.get("Fkm"),
                record_low=item.get("LKV"),
                record_high=item.get("LNV"),
                thresholds={
                    "level_1": item.get("KF1"),
                    "level_2": item.get("KF2"),
                    "level_3": item.get("KF3"),
                },
                provenance=Provenance(
                    provider="ovf_vraquery", source_url=source, retrieved_at=retrieved
                ),
                raw=item,
            )
            for item in data
            if item.get("Lat") is not None and item.get("Lon") is not None
        ]

    async def resolve_metric(self, value: str) -> dict[str, Any]:
        metrics, _ = await self.catalogs()
        aliases = {
            "water-level": 68,
            "discharge": 87,
            "water-temperature": 85,
            "groundwater-level": 69,
            "layer-water-level": 70,
            "precipitation": 71,
            "soil-moisture": 299,
            "soil-temperature": 303,
        }
        code = aliases.get(value.casefold())
        if code is None and value.isdigit():
            code = int(value)
        matches = [
            item
            for item in metrics
            if item["KodAZ"] == code or item.get("Nev", "").casefold() == value.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(f"unknown or ambiguous metric: {value}")
        return matches[0]

    async def resolve_data_type(self, value: str) -> dict[str, Any]:
        _, types = await self.catalogs()
        aliases = {
            "raw": 1,
            "observed": 4,
            "checked": 3,
            "processed": 7,
            "hydrological": 9,
            "operational": 101,
        }
        code = aliases.get(value.casefold())
        if code is None and value.isdigit():
            code = int(value)
        matches = [
            item
            for item in types
            if item["KodAZ"] == code or item.get("Nev", "").casefold() == value.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(f"unknown or ambiguous data type: {value}")
        return matches[0]

    async def observations(
        self,
        station: Station,
        metric_name: str,
        data_type_name: str,
        start: datetime,
        end: datetime,
        limit: int,
        include_quality: bool = False,
        data_ext: int | None = None,
    ) -> tuple[list[Observation], int]:
        metric = await self.resolve_metric(metric_name)
        data_type = await self.resolve_data_type(data_type_name)
        body = {
            "TorzsszamList": [station.registry_number],
            "AdatFajtaKod": metric["KodAZ"],
            "AdatTipusKod": data_type["KodAZ"],
            "StartTime": start.astimezone(UTC).isoformat(),
            "EndTime": end.astimezone(UTC).isoformat(),
        }
        if data_ext is not None:
            body["DataExtFilter"] = data_ext
        if include_quality:
            path = "TS/TsLongList"
            quality = await self.quality_names()
            long_response = await self._request("POST", path, LONG_OBSERVATIONS_RESPONSE, json=body)
            raw_response = long_response.raw
        else:
            path = "TS/TsShortList"
            quality = {"data": {}, "field": {}}
            short_response = await self._request("POST", path, OBSERVATIONS_RESPONSE, json=body)
            raw_response = short_response.raw
        data = cast(list[dict[str, Any]], raw_response)
        items = data[0].get("TsItemList") or [] if data else []
        total = len(items)
        if total > limit:
            items = items[-limit:]
        source = f"{self.base_url}/{path}"
        retrieved = datetime.now(UTC).isoformat()
        observations = [
            Observation(
                station_id=station.id,
                station_registry_number=station.registry_number,
                observed_at=item["UTCTime"],
                metric_code=metric["KodAZ"],
                metric=metric["Nev"],
                data_type_code=data_type["KodAZ"],
                data_type=data_type["Nev"],
                value=item.get("Adat"),
                unit=metric.get("Mertekegyseg"),
                quality_code=item.get("AMKod"),
                quality=quality["data"].get(item.get("AMKod")),
                field_quality_code=item.get("MMKod"),
                field_quality=quality["field"].get(item.get("MMKod")),
                data_ext=item.get("DataExt"),
                dimensions=self._dimensions(metric["KodAZ"], item.get("DataExt")),
                provenance=Provenance(
                    provider="ovf_vraquery", source_url=source, retrieved_at=retrieved
                ),
                raw=item,
            )
            for item in items
        ]
        return observations, total

    @staticmethod
    def _dimensions(metric_code: int, data_ext: int | None) -> dict[str, int]:
        if metric_code in {299, 303} and data_ext is not None:
            return {"depth_cm": data_ext}
        return {}

    async def stations_with_metric(self, network: str, metric_name: str) -> list[Station]:
        """Return catalogue stations carrying any documented data type for a metric."""
        stations = await self.stations(network)
        metric = await self.resolve_metric(metric_name)
        rows = await self._coverage_rows_for_ids(
            [station.registry_number for station in stations], metric["KodAZ"], 0
        )
        available = {row["Torzsszam"] for row in rows}
        return [station for station in stations if station.registry_number in available]

    async def coverage(self, station: Station, metric_name: str, data_type_name: str) -> Coverage:
        metric = await self.resolve_metric(metric_name)
        data_type = await self.resolve_data_type(data_type_name)

        rows = await self._coverage_rows(station, metric["KodAZ"], data_type["KodAZ"])
        warnings: list[str] = []
        if not rows and data_type["KodAZ"] == 101:
            all_rows = await self._coverage_rows(station, metric["KodAZ"], 0)
            rows = [row for row in all_rows if row.get("ATKod") == 100]
            if rows:
                warnings.append(
                    "VRAQuery coverage omits composed operational type 101; showing related "
                    "operational type 100 coverage. This relationship is inferred from the "
                    "official catalog and live behavior."
                )
        row = rows[0] if rows else {}
        return Coverage(
            station=station,
            metric_code=metric["KodAZ"],
            metric=metric["Nev"],
            unit=metric.get("Mertekegyseg"),
            requested_data_type_code=data_type["KodAZ"],
            requested_data_type=data_type["Nev"],
            available_from=row.get("UTCTimeMin"),
            available_until=row.get("UTCTimeMax"),
            coverage_data_type_code=row.get("ATKod"),
            provenance=Provenance(
                provider="ovf_vraquery",
                source_url=f"{self.base_url}/Base/DataCatalogMinMax",
                retrieved_at=datetime.now(UTC).isoformat(),
                upstream_version="OpenAPI v1.0.0",
            ),
            warnings=warnings,
        )

    async def available_data_types(
        self, station: Station, metric_name: str
    ) -> list[dict[str, Any]]:
        """Return documented coverage for every data type carried by a station metric."""
        metric = await self.resolve_metric(metric_name)
        _, data_types = await self.catalogs()
        names = {item["KodAZ"]: item["Nev"] for item in data_types}
        rows = await self._coverage_rows(station, metric["KodAZ"], 0)
        return [
            {
                "code": row["ATKod"],
                "name": names.get(row["ATKod"], f"code {row['ATKod']}"),
                "available_from": row.get("UTCTimeMin"),
                "available_until": row.get("UTCTimeMax"),
            }
            for row in rows
        ]

    async def _coverage_rows(
        self, station: Station, metric_code: int, data_type_code: int
    ) -> list[dict[str, Any]]:
        return await self._coverage_rows_for_ids(
            [station.registry_number], metric_code, data_type_code
        )

    async def _coverage_rows_for_ids(
        self, station_ids: list[int], metric_code: int, data_type_code: int
    ) -> list[dict[str, Any]]:
        response = await self._request(
            "POST",
            "Base/DataCatalogMinMax",
            COVERAGE_RESPONSE,
            params={"hafKod": metric_code, "atKod": data_type_code},
            json=station_ids,
        )
        return cast(list[dict[str, Any]], response.raw)

    async def aggregate_observations(
        self,
        station: Station,
        metric_name: str,
        data_type_name: str,
        start: datetime,
        end: datetime,
        interval: str,
        operation: str,
        data_ext: int | None = None,
    ) -> list[Observation]:
        metric = await self.resolve_metric(metric_name)
        data_type = await self.resolve_data_type(data_type_name)
        query_filter: dict[str, Any] = {
            "FilterID": 1,
            "AdatFajtaKod": metric["KodAZ"],
            "AdatTipusKod": data_type["KodAZ"],
            "StartTime": start.astimezone(UTC).isoformat(),
            "EndTime": end.astimezone(UTC).isoformat(),
            "AggregateFilters": {
                "RangeType": interval,
                "AggregateType": operation,
                "AggregateRangePosition": "none",
            },
        }
        if data_ext is not None:
            query_filter["DataExtFilter"] = data_ext
        body = {
            "TorzsszamList": [station.registry_number],
            "Filters": [query_filter],
        }
        response = await self._request(
            "POST", "TS/TSListFilterShort", AGGREGATES_RESPONSE, json=body
        )
        data = cast(list[dict[str, Any]], response.raw)
        responses = data[0].get("FilteredResponse") or [] if data else []
        items = responses[0].get("TsItemList") or [] if responses else []
        source = f"{self.base_url}/TS/TSListFilterShort"
        retrieved = datetime.now(UTC).isoformat()
        return [
            Observation(
                station_id=station.id,
                station_registry_number=station.registry_number,
                observed_at=item["UTCTime"],
                metric_code=metric["KodAZ"],
                metric=metric["Nev"],
                data_type_code=data_type["KodAZ"],
                data_type=data_type["Nev"],
                value=item.get("Adat"),
                unit=metric.get("Mertekegyseg"),
                data_ext=item.get("DataExt"),
                dimensions=self._dimensions(metric["KodAZ"], item.get("DataExt")),
                provenance=Provenance(
                    provider="ovf_vraquery",
                    source_url=source,
                    retrieved_at=retrieved,
                    upstream_version="OpenAPI v1.0.0",
                ),
                raw=item,
            )
            for item in items
        ]

    async def aggregate_depths(
        self,
        station: Station,
        metric_name: str,
        data_type_name: str,
        start: datetime,
        end: datetime,
        depths_cm: list[int],
        interval: str,
        operation: str,
    ) -> tuple[dict[int, list[Observation]], dict[str, Any]]:
        metric = await self.resolve_metric(metric_name)
        if metric["KodAZ"] not in {299, 303}:
            raise ValueError("depth_cm is only defined for soil moisture and soil temperature")
        data_type = await self.resolve_data_type(data_type_name)
        filters = [
            {
                "FilterID": index,
                "AdatFajtaKod": metric["KodAZ"],
                "AdatTipusKod": data_type["KodAZ"],
                "StartTime": start.astimezone(UTC).isoformat(),
                "EndTime": end.astimezone(UTC).isoformat(),
                "DataExtFilter": depth,
                "AggregateFilters": {
                    "RangeType": interval,
                    "AggregateType": operation,
                    "AggregateRangePosition": "none",
                },
            }
            for index, depth in enumerate(depths_cm, start=1)
        ]
        response = await self._request(
            "POST",
            "TS/TSListFilterShort",
            AGGREGATES_RESPONSE,
            json={"TorzsszamList": [station.registry_number], "Filters": filters},
        )
        raw = cast(list[dict[str, Any]], response.raw)
        source = f"{self.base_url}/TS/TSListFilterShort"
        retrieved = datetime.now(UTC).isoformat()
        by_depth: dict[int, list[Observation]] = {depth: [] for depth in depths_cm}
        filter_depths = {index: depth for index, depth in enumerate(depths_cm, start=1)}
        for filtered in raw:
            filter_id = filtered.get("FilterID")
            depth = filter_depths.get(filter_id) if isinstance(filter_id, int) else None
            if depth is None:
                continue
            station_responses = filtered.get("FilteredResponse") or []
            items = station_responses[0].get("TsItemList") or [] if station_responses else []
            by_depth[depth] = [
                Observation(
                    station_id=station.id,
                    station_registry_number=station.registry_number,
                    observed_at=item["UTCTime"],
                    metric_code=metric["KodAZ"],
                    metric=metric["Nev"],
                    data_type_code=data_type["KodAZ"],
                    data_type=data_type["Nev"],
                    value=item.get("Adat"),
                    unit=metric.get("Mertekegyseg"),
                    data_ext=item.get("DataExt", depth),
                    dimensions={"depth_cm": depth},
                    provenance=Provenance(
                        provider="ovf_vraquery",
                        source_url=source,
                        retrieved_at=retrieved,
                        upstream_version="OpenAPI v1.0.0",
                    ),
                    raw=item,
                )
                for item in items
            ]
        return by_depth, metric
