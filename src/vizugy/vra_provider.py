from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .errors import UpstreamError
from .models import Observation, Provenance, Station


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
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._token: str | None = None
        self._metrics: list[dict[str, Any]] | None = None
        self._data_types: list[dict[str, Any]] | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def _headers(self) -> dict[str, str]:
        if self._token is None:
            response = await self.client.get(
                self.token_url,
                headers={"Origin": "https://data.vizugy.hu", "Referer": "https://data.vizugy.hu/"},
            )
            response.raise_for_status()
            self._token = response.json()["access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
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
            return response.json()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise UpstreamError(f"VRAQuery request failed: {exc}") from exc

    async def catalogs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self._metrics is None:
            self._metrics = await self._request("GET", "Base/AdatFajta")
        if self._data_types is None:
            self._data_types = await self._request("GET", "Base/AdatTipus")
        return self._metrics, self._data_types

    async def stations(self) -> list[Station]:
        data = await self._request("GET", "Vra/InternetVmo/11/true")
        source = f"{self.base_url}/Vra/InternetVmo/11/true"
        retrieved = datetime.now(UTC).isoformat()
        return [
            Station(
                id=f"surface:{item['Tsz']}",
                registry_number=item["Tsz"],
                name=item["Nev"],
                watercourse=item.get("MdrNev"),
                municipality=item.get("Telepules"),
                latitude=item["Lat"],
                longitude=item["Lon"],
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
        aliases = {"water-level": 68, "discharge": 87, "water-temperature": 85}
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
    ) -> list[Observation]:
        metric = await self.resolve_metric(metric_name)
        data_type = await self.resolve_data_type(data_type_name)
        body = {
            "TorzsszamList": [station.registry_number],
            "AdatFajtaKod": metric["KodAZ"],
            "AdatTipusKod": data_type["KodAZ"],
            "StartTime": start.astimezone(UTC).isoformat(),
            "EndTime": end.astimezone(UTC).isoformat(),
        }
        data = await self._request("POST", "TS/TsShortList", json=body)
        items = data[0].get("TsItemList") or [] if data else []
        if len(items) > limit:
            items = items[-limit:]
        source = f"{self.base_url}/TS/TsShortList"
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
                provenance=Provenance(
                    provider="ovf_vraquery", source_url=source, retrieved_at=retrieved
                ),
                raw=item,
            )
            for item in items
        ]
