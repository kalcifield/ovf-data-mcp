import asyncio
import json
from datetime import datetime
from enum import Enum

import typer

from .errors import NotFoundError, UpstreamError
from .factory import create_service


class Output(str, Enum):
    json = "json"
    jsonl = "jsonl"


app = typer.Typer(no_args_is_help=True)
datasets = typer.Typer(no_args_is_help=True)
app.add_typer(datasets, name="datasets")


def run(coro):
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

    async def operation():
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

    async def operation():
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


def emit_page(page, format: Output) -> None:
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

    async def operation():
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
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation():
        try:
            return await service.find_stations(query, limit, watercourse, municipality)
        finally:
            await service.close()

    emit_page(run(operation()), format)


@stations.command("nearest")
def nearest_stations(
    latitude: float,
    longitude: float,
    limit: int = typer.Option(5, min=1, max=100),
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation():
        try:
            return await service.nearest_stations(latitude, longitude, limit)
        finally:
            await service.close()

    emit_page(run(operation()), format)


@observations.command("get")
def get_observations(
    station: str,
    metric: str = typer.Option("water-level", help="Metric name, alias, or VRA code."),
    data_type: str = typer.Option("operational", help="Data-type name, alias, or VRA code."),
    start: str | None = typer.Option(
        None, help="UTC/offset ISO-8601 start; default five days ago."
    ),
    end: str | None = typer.Option(None, help="UTC/offset ISO-8601 end; default now."),
    limit: int = typer.Option(1000, min=1, max=1000),
    format: Output = typer.Option(Output.json),
) -> None:
    service = create_service()

    async def operation():
        try:
            return await service.get_observations(
                station, metric, data_type, parse_time(start), parse_time(end), limit
            )
        finally:
            await service.close()

    selected, items = run(operation())
    if format == Output.jsonl:
        for item in items:
            print(item.model_dump_json())
        print(
            json.dumps(
                {"_meta": {"station": selected.model_dump(mode="json"), "returned": len(items)}},
                ensure_ascii=False,
            )
        )
    else:
        print(
            json.dumps(
                {
                    "station": selected.model_dump(mode="json"),
                    "items": [item.model_dump(mode="json") for item in items],
                    "returned": len(items),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    app()
