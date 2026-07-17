# vizugy-mcp

Experimental, read-only agent interface to public Hungarian water-management data.

The first slice deliberately supports only ArcGIS catalogue discovery and layer
description. Upstream metadata contains no useful copyright statement; verify reuse
terms with OVF before redistribution or production use.

```sh
uv sync --extra test --extra mcp
uv run vizugy datasets list --format json
uv run vizugy datasets list --format jsonl --limit 10
uv run vizugy datasets describe VIR/Vizmercek_vizugyhu_orszagos_adatsoros --layer 6
uv run vizugy-mcp
```

Machine output goes to stdout; diagnostics go to stderr. Exit codes: `0` success,
`2` invalid usage, `3` upstream unavailable/invalid, `4` requested item absent.

Configuration: `VIZUGY_ARCGIS_URL` (default public OVF ArcGIS root),
`VIZUGY_TIMEOUT_SECONDS` (default `15`), `VIZUGY_CACHE_TTL_SECONDS` (default `300`).

See `docs/design.md` for verified findings, architecture, interfaces, and roadmap.

