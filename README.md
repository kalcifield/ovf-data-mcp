# vizugy-mcp

Experimental, read-only agent interface to public Hungarian water-management data.

Uses the public VRAQuery OpenAPI service for stations, measurement catalogues, and
time series; ArcGIS remains the spatial dataset catalogue. Data may be operational
and unverified, so it must not be presented as validated official evidence.

```sh
uv sync --extra test --extra mcp
uv run vizugy datasets list --format json
uv run vizugy catalog measurements
uv run vizugy stations search Budapest --watercourse Duna
uv run vizugy stations nearest 47.4979 19.0402 --limit 5
uv run vizugy observations get surface:1026 --metric water-level \
  --data-type operational --start 2026-07-16T00:00:00Z --format jsonl
uv run vizugy-mcp
```

Machine output goes to stdout; diagnostics go to stderr. Exit codes: `0` success,
`2` invalid usage, `3` upstream unavailable/invalid, `4` requested item absent.

Configuration: `VIZUGY_ARCGIS_URL` (default public OVF ArcGIS root),
`VIZUGY_TIMEOUT_SECONDS` (default `15`), `VIZUGY_CACHE_TTL_SECONDS` (default `300`).
Advanced overrides: `VIZUGY_VRA_URL`, `VIZUGY_TOKEN_URL`.

See `docs/design.md` for verified findings, architecture, interfaces, and roadmap.
