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
            await service.provider.close()

    @mcp.tool()
    async def describe_dataset(dataset_id: str, layer_id: int | None = None) -> dict:
        """Inspect one dataset or layer, including schema, CRS, limits, and provenance."""
        service = create_service()
        try:
            return (await service.describe_dataset(dataset_id, layer_id)).model_dump(mode="json")
        finally:
            await service.provider.close()

    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
