from typing import Any, Literal

from pydantic import BaseModel, Field as PydanticField


class Provenance(BaseModel):
    provider: Literal["ovf_arcgis"] = "ovf_arcgis"
    source_url: str
    retrieved_at: str
    upstream_version: float | None = None


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
