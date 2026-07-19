import asyncio
import json
from collections.abc import Coroutine
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

import typer

from .errors import NotFoundError, UpstreamError
from .factory import create_service
from .models import (
    Coverage,
    DatasetDescription,
    ObservationResult,
    Page,
    QueryPlan,
    SoilDepthComparison,
    StationPage,
)

T = TypeVar("T")


class Output(str, Enum):
    json = "json"
    jsonl = "jsonl"


app = typer.Typer(no_args_is_help=True)
datasets = typer.Typer(no_args_is_help=True)
app.add_typer(datasets, name="datasets")


def run(coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except NotFoundError as exc:
        typer.echo(f"not found: {exc}", err=True)
        raise typer.Exit(4) from exc
    except UpstreamError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("expected ISO-8601, for example 2026-07-16T00:00:00Z") from exc


@datasets.command("list")
def list_datasets(
    query: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1, max=1000),
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation() -> Page:
        try:
            return await service.list_datasets(query, limit)
        finally:
            await service.close()

    page = run(operation())
    if format == Output.jsonl:
        for item in page.items:
            print(item.model_dump_json())
        print(json.dumps({"_meta": page.model_dump(exclude={"items"})}, ensure_ascii=False))
    else:
        print(page.model_dump_json(indent=2))


@datasets.command("describe")
def describe_dataset(dataset_id: str, layer: int | None = typer.Option(None)) -> None:
    service = create_service()

    async def operation() -> DatasetDescription:
        try:
            return await service.describe_dataset(dataset_id, layer)
        finally:
            await service.close()

    print(run(operation()).model_dump_json(indent=2))


stations = typer.Typer(no_args_is_help=True)
observations = typer.Typer(no_args_is_help=True)
catalog = typer.Typer(no_args_is_help=True)
app.add_typer(stations, name="stations")
app.add_typer(observations, name="observations")
app.add_typer(catalog, name="catalog")


def emit_page(page: Page | StationPage, format: Output) -> None:
    if format == Output.jsonl:
        for item in page.items:
            print(item.model_dump_json())
        print(json.dumps({"_meta": page.model_dump(exclude={"items"})}, ensure_ascii=False))
    else:
        print(page.model_dump_json(indent=2))


@catalog.command("measurements")
def measurement_catalog() -> None:
    """List authoritative metric codes, units, ranges, and data types."""
    service = create_service()

    async def operation() -> dict[str, Any]:
        try:
            return await service.measurement_catalog()
        finally:
            await service.close()

    print(json.dumps(run(operation()), ensure_ascii=False, indent=2))


@stations.command("search")
def search_stations(
    query: str | None = typer.Argument(None),
    limit: int = typer.Option(50, min=1, max=1000),
    watercourse: str | None = typer.Option(None, help="Case-insensitive watercourse filter."),
    municipality: str | None = typer.Option(None, help="Case-insensitive municipality filter."),
    network: str = typer.Option(
        "surface",
        help='Station network: "surface", "wells" (shallow groundwater), "deep-wells" (confined/layer aquifer), or "precipitation".',
    ),
    metric: str | None = typer.Option(None, help="Only stations with documented metric coverage."),
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation() -> StationPage:
        try:
            return await service.find_stations(
                query, limit, watercourse, municipality, network, metric
            )
        finally:
            await service.close()

    emit_page(run(operation()), format)


@stations.command("nearest")
def nearest_stations(
    latitude: float,
    longitude: float,
    limit: int = typer.Option(5, min=1, max=100),
    network: str = typer.Option(
        "surface",
        help='Station network: "surface", "wells" (shallow groundwater), "deep-wells" (confined/layer aquifer), or "precipitation".',
    ),
    metric: str | None = typer.Option(None, help="Only stations with documented metric coverage."),
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation() -> StationPage:
        try:
            return await service.nearest_stations(latitude, longitude, limit, network, metric)
        finally:
            await service.close()

    emit_page(run(operation()), format)


@observations.command("get")
def get_observations(
    station: str,
    metric: str = typer.Option("water-level", help="Metric name, alias, or VRA code."),
    data_type: str = typer.Option("operational", help="Data-type name, alias, or VRA code."),
    start: str = typer.Option(..., help="UTC/offset ISO-8601 start."),
    end: str = typer.Option(..., help="UTC/offset ISO-8601 end."),
    limit: int = typer.Option(1000, min=1, max=1000),
    format: Output = typer.Option(Output.json),
    explain: bool = typer.Option(False, help="Resolve and validate without fetching data."),
    quality: bool = typer.Option(
        False, help="Include upstream quality codes and labels per observation."
    ),
    data_ext: int | None = typer.Option(None, help="Generic upstream DataExt filter."),
    depth_cm: int | None = typer.Option(
        None, help="Soil depth alias; valid only for soil metrics."
    ),
) -> None:
    service = create_service()

    async def operation() -> QueryPlan | ObservationResult:
        try:
            if explain:
                return await service.explain_observation_query(
                    station,
                    metric,
                    data_type,
                    parse_time(start),
                    parse_time(end),
                    data_ext,
                    depth_cm,
                )
            return await service.get_observations(
                station,
                metric,
                data_type,
                parse_time(start),
                parse_time(end),
                limit,
                include_quality=quality,
                data_ext=data_ext,
                depth_cm=depth_cm,
            )
        finally:
            await service.close()

    result = run(operation())
    if explain:
        assert isinstance(result, QueryPlan)
        print(result.model_dump_json(indent=2))
        return
    assert isinstance(result, ObservationResult)
    if format == Output.jsonl:
        for item in result.items:
            print(item.model_dump_json())
        print(
            json.dumps(
                {"_meta": result.model_dump(mode="json", exclude={"items"})},
                ensure_ascii=False,
            )
        )
    else:
        print(result.model_dump_json(indent=2))


@observations.command("coverage")
def observation_coverage(
    station: str,
    metric: str = typer.Option("water-level"),
    data_type: str = typer.Option("operational"),
) -> None:
    """Inspect temporal coverage before querying values."""
    service = create_service()

    async def operation() -> Coverage:
        try:
            return await service.inspect_coverage(station, metric, data_type)
        finally:
            await service.close()

    print(run(operation()).model_dump_json(indent=2))


@observations.command("aggregate")
def aggregate_observations(
    station: str,
    start: str = typer.Option(..., help="UTC/offset ISO-8601 start."),
    end: str = typer.Option(..., help="UTC/offset ISO-8601 end."),
    metric: str = typer.Option("water-level"),
    data_type: str = typer.Option("operational"),
    interval: str = typer.Option("daily", help="daily, tenday, monthly, or yearly."),
    operation: str = typer.Option("max", help="min, max, avg, sum, cnt, mean, or cntday."),
    format: Output = typer.Option(Output.json),
    explain: bool = typer.Option(False, help="Resolve and validate without fetching data."),
    data_ext: int | None = typer.Option(None, help="Generic upstream DataExt filter."),
    depth_cm: int | None = typer.Option(
        None, help="Soil depth alias; valid only for soil metrics."
    ),
) -> None:
    """Run documented server-side aggregation over a bounded interval."""
    service = create_service()

    async def execute() -> QueryPlan | ObservationResult:
        try:
            if explain:
                return await service.explain_observation_query(
                    station,
                    metric,
                    data_type,
                    parse_time(start),
                    parse_time(end),
                    interval=interval,
                    operation=operation,
                    data_ext=data_ext,
                    depth_cm=depth_cm,
                )
            return await service.aggregate_observations(
                station,
                metric,
                data_type,
                parse_time(start),
                parse_time(end),
                interval,
                operation,
                data_ext,
                depth_cm,
            )
        finally:
            await service.close()

    result = run(execute())
    if explain:
        assert isinstance(result, QueryPlan)
        print(result.model_dump_json(indent=2))
        return
    assert isinstance(result, ObservationResult)
    if format == Output.jsonl:
        for item in result.items:
            print(item.model_dump_json())
        print(json.dumps({"_meta": result.model_dump(mode="json", exclude={"items"})}))
    else:
        print(result.model_dump_json(indent=2))


@observations.command("compare-depths")
def compare_soil_depths(
    station: str,
    start: str = typer.Option(..., help="UTC/offset ISO-8601 start."),
    end: str = typer.Option(..., help="UTC/offset ISO-8601 end."),
    depths_cm: list[int] | None = typer.Option(
        None, "--depth-cm", help="Repeat for selected depths; defaults to all six."
    ),
    metric: str = typer.Option("soil-moisture", help="soil-moisture or soil-temperature."),
    data_type: str = typer.Option("operational"),
    interval: str = typer.Option("daily"),
    operation: str = typer.Option("avg"),
) -> None:
    """Compare aligned, upstream-aggregated soil series by sensor depth."""
    service = create_service()

    async def execute() -> SoilDepthComparison:
        try:
            return await service.compare_soil_depths(
                station,
                parse_time(start),
                parse_time(end),
                depths_cm,
                metric,
                data_type,
                interval,
                operation,
            )
        finally:
            await service.close()

    print(run(execute()).model_dump_json(indent=2))


if __name__ == "__main__":
    app()
