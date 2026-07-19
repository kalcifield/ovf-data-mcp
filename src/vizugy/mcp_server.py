from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from .factory import create_service


def build_server() -> FastMCP:
    mcp = FastMCP("vizugy", instructions="Read-only discovery of public Hungarian water datasets.")

    @mcp.tool()
    async def discover_datasets(query: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Find public water datasets by catalogue identifier; results are bounded."""
        service = create_service()
        try:
            return (await service.list_datasets(query, limit)).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def describe_dataset(dataset_id: str, layer_id: int | None = None) -> dict[str, Any]:
        """Inspect one dataset or layer, including schema, CRS, limits, and provenance."""
        service = create_service()
        try:
            return (await service.describe_dataset(dataset_id, layer_id)).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def list_measurement_types() -> dict[str, Any]:
        """List authoritative metric codes, units, valid ranges, and data-type codes."""
        service = create_service()
        try:
            return await service.measurement_catalog()
        finally:
            await service.close()

    @mcp.tool()
    async def find_stations(
        query: str | None = None,
        limit: int = 50,
        watercourse: str | None = None,
        municipality: str | None = None,
        network: str = "surface",
    ) -> dict[str, Any]:
        """Find gauges by registry ID, name, watercourse, or municipality.

        network: "surface" (rivers and lakes), "wells" (shallow groundwater),
        "deep-wells" (confined/layer aquifer), or "precipitation".
        """
        service = create_service()
        try:
            return (
                await service.find_stations(query, limit, watercourse, municipality, network)
            ).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def nearest_stations(
        latitude: float, longitude: float, limit: int = 5, network: str = "surface"
    ) -> dict[str, Any]:
        """Find public gauges nearest a WGS84 latitude/longitude.

        network: "surface" (rivers and lakes), "wells" (shallow groundwater),
        "deep-wells" (confined/layer aquifer), or "precipitation".
        """
        service = create_service()
        try:
            return (await service.nearest_stations(latitude, longitude, limit, network)).model_dump(
                mode="json"
            )
        finally:
            await service.close()

    @mcp.tool()
    async def get_observations(
        station: str,
        start: datetime,
        end: datetime,
        metric: str = "water-level",
        data_type: str = "operational",
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Get raw observations for an explicit interval of at most 7 days."""
        service = create_service()
        try:
            result = await service.get_observations(station, metric, data_type, start, end, limit)
            return result.model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def inspect_coverage(
        station: str,
        metric: str = "water-level",
        data_type: str = "operational",
    ) -> dict[str, Any]:
        """Resolve a station and report documented temporal coverage before querying."""
        service = create_service()
        try:
            return (await service.inspect_coverage(station, metric, data_type)).model_dump(
                mode="json"
            )
        finally:
            await service.close()

    @mcp.tool()
    async def aggregate_observations(
        station: str,
        start: datetime,
        end: datetime,
        metric: str = "water-level",
        data_type: str = "operational",
        interval: str = "daily",
        operation: str = "max",
    ) -> dict[str, Any]:
        """Aggregate observations server-side over daily, ten-day, monthly, or yearly buckets."""
        service = create_service()
        try:
            result = await service.aggregate_observations(
                station, metric, data_type, start, end, interval, operation
            )
            return result.model_dump(mode="json")
        finally:
            await service.close()

    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
