from datetime import datetime

from .factory import create_service


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("vizugy", instructions="Read-only discovery of public Hungarian water datasets.")

    @mcp.tool()
    async def discover_datasets(query: str | None = None, limit: int = 50) -> dict:
        """Find public water datasets by catalogue identifier; results are bounded."""
        service = create_service()
        try:
            return (await service.list_datasets(query, limit)).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def describe_dataset(dataset_id: str, layer_id: int | None = None) -> dict:
        """Inspect one dataset or layer, including schema, CRS, limits, and provenance."""
        service = create_service()
        try:
            return (await service.describe_dataset(dataset_id, layer_id)).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def list_measurement_types() -> dict:
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
    ) -> dict:
        """Find surface-water gauges by registry ID, name, watercourse, or municipality."""
        service = create_service()
        try:
            return (
                await service.find_stations(query, limit, watercourse, municipality)
            ).model_dump(mode="json")
        finally:
            await service.close()

    @mcp.tool()
    async def nearest_stations(latitude: float, longitude: float, limit: int = 5) -> dict:
        """Find public gauges nearest a WGS84 latitude/longitude."""
        service = create_service()
        try:
            return (await service.nearest_stations(latitude, longitude, limit)).model_dump(
                mode="json"
            )
        finally:
            await service.close()

    @mcp.tool()
    async def get_observations(
        station: str,
        metric: str = "water-level",
        data_type: str = "operational",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> dict:
        """Get typed observations for a station and UTC interval."""
        service = create_service()
        try:
            selected, items = await service.get_observations(
                station, metric, data_type, start, end, limit
            )
            return {
                "station": selected.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in items],
            }
        finally:
            await service.close()

    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
