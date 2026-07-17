import asyncio
import json
import sys
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
            await service.provider.close()

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
            await service.provider.close()

    print(run(operation()).model_dump_json(indent=2))


if __name__ == "__main__":
    app()

