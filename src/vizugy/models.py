from typing import Any, Literal

from pydantic import BaseModel, Field as PydanticField


class Provenance(BaseModel):
    provider: Literal["ovf_arcgis", "ovf_vraquery"] = "ovf_arcgis"
    source_url: str
    retrieved_at: str
    upstream_version: float | str | None = None


class Dataset(BaseModel):
    id: str
    name: str
    kind: str
    folder: str | None = None
    provenance: Provenance


class Field(BaseModel):
    name: str
    alias: str | None = None
    type: str
    raw: dict[str, Any] = PydanticField(default_factory=dict)


class DatasetDescription(BaseModel):
    dataset: Dataset
    layer_id: int | None = None
    layer_name: str | None = None
    geometry_type: str | None = None
    crs_wkid: int | None = None
    max_record_count: int | None = None
    supports_pagination: bool | None = None
    fields: list[Field] = PydanticField(default_factory=list)
    raw: dict[str, Any] = PydanticField(default_factory=dict)


class Page(BaseModel):
    items: list[Dataset]
    returned: int
    total: int
    limit: int
    truncated: bool
    warnings: list[str] = PydanticField(default_factory=list)


class Station(BaseModel):
    id: str
    registry_number: int
    name: str
    watercourse: str | None = None
    municipality: str | None = None
    latitude: float
    longitude: float
    distance_km: float | None = None
    thresholds: dict[str, float | None] = PydanticField(default_factory=dict)
    provenance: Provenance
    raw: dict[str, Any] = PydanticField(default_factory=dict, exclude=True)


class StationPage(BaseModel):
    items: list[Station]
    returned: int
    total: int
    limit: int
    truncated: bool
    warnings: list[str] = PydanticField(default_factory=list)


class Observation(BaseModel):
    station_id: str
    station_registry_number: int
    observed_at: str
    metric_code: int
    metric: str
    data_type_code: int
    data_type: str
    value: float | None = None
    unit: str | None = None
    provenance: Provenance
    raw: dict[str, Any] = PydanticField(default_factory=dict, exclude=True)


class ObservationPoint(BaseModel):
    observed_at: str
    value: float | None = None


class QueryPlan(BaseModel):
    station: Station = PydanticField(exclude=True)
    station_id: str
    station_name: str
    metric_code: int
    metric: str
    unit: str | None = None
    data_type_code: int
    data_type: str
    start: str
    end: str
    duration_days: float
    mode: Literal["raw", "aggregate"]
    aggregation: dict[str, str] | None = None
    source_operation: str
    will_fetch: bool = False
    warnings: list[str] = PydanticField(default_factory=list)


class Coverage(BaseModel):
    station: Station
    metric_code: int
    metric: str
    unit: str | None = None
    requested_data_type_code: int
    requested_data_type: str
    available_from: str | None = None
    available_until: str | None = None
    coverage_data_type_code: int | None = None
    provenance: Provenance
    warnings: list[str] = PydanticField(default_factory=list)


class ObservationResult(BaseModel):
    station: Station
    query: QueryPlan
    items: list[ObservationPoint]
    returned: int
    truncated: bool = False
    provenance: Provenance
    warnings: list[str] = PydanticField(default_factory=list)
