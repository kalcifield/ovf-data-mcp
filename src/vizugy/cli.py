import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

import typer

from .errors import NotFoundError, UpstreamError
from .factory import create_service
from .models import (
    ObservationResult,
    Page,
    QueryPlan,
    StationPage,
)
from .service import VizugyService

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


async def use_service(operation: Callable[[VizugyService], Awaitable[T]]) -> T:
    async with create_service() as service:
        return await operation(service)


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
    page = run(use_service(lambda service: service.list_datasets(query, limit)))
    if format == Output.jsonl:
        for item in page.items:
            print(item.model_dump_json())
        print(json.dumps({"_meta": page.model_dump(exclude={"items"})}, ensure_ascii=False))
    else:
        print(page.model_dump_json(indent=2))


@datasets.command("describe")
def describe_dataset(dataset_id: str, layer: int | None = typer.Option(None)) -> None:
    result = run(use_service(lambda service: service.describe_dataset(dataset_id, layer)))
    print(result.model_dump_json(indent=2))


@datasets.command("water-shortage")
def water_shortage(
    grade_code: int | None = typer.Option(None, help="720 (none), 721, 722, or 723."),
    directorate: str | None = typer.Option(
        None, help="Filter by water directorate, e.g. ADUVIZIG."
    ),
    limit: int = typer.Option(100, min=1, max=200),
) -> None:
    """Officially declared water-shortage grades per district."""
    result = run(
        use_service(
            lambda service: service.water_shortage_districts(grade_code, directorate, limit)
        )
    )
    print(result.model_dump_json(indent=2))


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
    result = run(use_service(lambda service: service.measurement_catalog()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


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
    result = run(
        use_service(
            lambda service: service.find_stations(
                query, limit, watercourse, municipality, network, metric
            )
        )
    )
    emit_page(result, format)


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
    result = run(
        use_service(
            lambda service: service.nearest_stations(latitude, longitude, limit, network, metric)
        )
    )
    emit_page(result, format)


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
    async def operation(service: VizugyService) -> QueryPlan | ObservationResult:
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

    result = run(use_service(operation))
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
    result = run(use_service(lambda service: service.inspect_coverage(station, metric, data_type)))
    print(result.model_dump_json(indent=2))


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

    async def execute(service: VizugyService) -> QueryPlan | ObservationResult:
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

    result = run(use_service(execute))
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
    result = run(
        use_service(
            lambda service: service.compare_soil_depths(
                station,
                parse_time(start),
                parse_time(end),
                depths_cm,
                metric,
                data_type,
                interval,
                operation,
            )
        )
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
