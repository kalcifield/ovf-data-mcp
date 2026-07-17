# vizugy-mcp

Agent-friendly, read-only access to public Hungarian water-management data from the
Országos Vízügyi Főigazgatóság (OVF).

`vizugy` supports the investigation workflow agents actually need:

```text
discover → resolve stations → inspect coverage → explain query → retrieve or aggregate → cite
```

The same application logic is exposed through a composable CLI and a local MCP server.
The CLI is the primary interface; MCP tools are thin adapters over identical operations.

## What it can do

- Discover and inspect public OVF ArcGIS datasets.
- Search surface-water stations by name, municipality, or watercourse.
- Find the nearest stations to WGS84 coordinates.
- List authoritative measurement codes, units, accepted ranges, and data types.
- Inspect temporal coverage before requesting observations.
- Retrieve compact, bounded operational or historical time series.
- Aggregate observations upstream by day, ten-day period, month, or year.
- Explain resolved identifiers and query semantics without fetching values.
- Return structured provenance and explicit upstream caveats.

It deliberately does not interpret hydrology, detect anomalies, expose arbitrary SQL,
or provide unrestricted bulk access. The agent remains responsible for analysis.

## Data sources

| Source | Purpose | Status |
|---|---|---|
| [VRAQuery OpenAPI](https://vmservice.vizugy.hu/vraquery/swagger/index.html) | Stations, measurement catalogues, coverage, observations, aggregation | Officially documented |
| [OVF ArcGIS REST](https://geoportal.vizugy.hu/arcgis/rest/services) | Spatial dataset discovery and layer metadata | Public; metadata quality varies |
| [data.vizugy.hu](https://data.vizugy.hu/) | Official public-data frontend and anonymous access flow | Public frontend |

Operational observations may be preliminary or unchecked. For official proceedings or
guaranteed checked data, follow OVF's formal data-request process.

## Installation

Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
git clone <repository-url> vizugy-mcp
cd vizugy-mcp
uv sync --extra mcp --extra test
```

Run commands from the checkout:

```bash
uv run vizugy --help
uv run vizugy-mcp
```

After packaging or installation, use `vizugy` and `vizugy-mcp` directly.

## Quick investigation

### 1. Resolve a station

```bash
uv run vizugy stations search Budapest --watercourse Duna --limit 10
```

Results use stable namespaced IDs such as `surface:1026`.

Find stations by coordinates:

```bash
uv run vizugy stations nearest 47.4979 19.0402 --limit 5
```

### 2. Inspect available measurements and coverage

```bash
uv run vizugy catalog measurements

uv run vizugy observations coverage surface:1026 \
  --metric water-level \
  --data-type operational
```

Useful metric aliases:

- `water-level`
- `discharge`
- `water-temperature`

Useful data-type aliases:

- `raw`
- `observed`
- `checked`
- `processed`
- `hydrological`
- `operational`

Numeric VRA codes and exact catalogue names are also accepted.

### 3. Explain before fetching

```bash
uv run vizugy observations get surface:1026 \
  --metric water-level \
  --data-type operational \
  --start 2026-07-16T00:00:00Z \
  --end 2026-07-17T00:00:00Z \
  --explain
```

The explanation shows the resolved station, metric and data-type codes, UTC bounds,
upstream operation, expected mode, and safety warnings. It performs no value query.

### 4. Retrieve a bounded raw series

```bash
uv run vizugy observations get surface:1026 \
  --metric water-level \
  --data-type operational \
  --start 2026-07-16T00:00:00Z \
  --end 2026-07-17T00:00:00Z \
  --limit 1000 \
  --format jsonl
```

Raw observation queries require explicit bounds and may span at most seven days.
JSONL emits one compact timestamp/value record per line followed by a `_meta` record.

### 5. Aggregate longer periods upstream

```bash
uv run vizugy observations aggregate surface:2046 \
  --metric water-level \
  --data-type operational \
  --start 2026-06-01T00:00:00Z \
  --end 2026-07-01T00:00:00Z \
  --interval daily \
  --operation max
```

Intervals: `daily`, `tenday`, `monthly`, `yearly`.

Operations supported by VRAQuery:
`min`, `max`, `avg`, `sum`, `cnt`, `mean`, `cntday`.

Aggregation buckets follow upstream hydrological/local-day boundaries. Returned bucket
labels remain UTC timestamps and can precede the requested UTC boundary by an offset.

## Dataset discovery

Search the OVF ArcGIS catalogue without knowing folder or layer identifiers:

```bash
uv run vizugy datasets list --query Vizmercek --limit 20 --format json
```

Inspect one service or layer:

```bash
uv run vizugy datasets describe \
  VIR/Vizmercek_vizugyhu_orszagos_adatsoros \
  --layer 6
```

Some advertised ArcGIS folders require authentication. Public discovery skips them and
returns explicit warnings rather than failing the entire catalogue request.

## CLI reference

```text
vizugy datasets list
vizugy datasets describe
vizugy catalog measurements
vizugy stations search
vizugy stations nearest
vizugy observations coverage
vizugy observations get
vizugy observations aggregate
```

Machine-readable output goes to stdout; diagnostics go to stderr.

| Exit code | Meaning |
|---:|---|
| `0` | Success |
| `2` | Invalid or unsafe query |
| `3` | Upstream unavailable or invalid response |
| `4` | Requested entity not found |

## MCP server

Start the local stdio server:

```bash
uv run vizugy-mcp
```

Example client configuration:

```json
{
  "mcpServers": {
    "vizugy": {
      "command": "uv",
      "args": ["--directory", "/path/to/vizugy-mcp", "run", "vizugy-mcp"]
    }
  }
}
```

Available tools:

| Tool | Intent |
|---|---|
| `discover_datasets` | Search public spatial datasets |
| `describe_dataset` | Inspect a service or layer schema |
| `list_measurement_types` | Resolve metrics, units, ranges, and data types |
| `find_stations` | Resolve station names, rivers, and municipalities |
| `nearest_stations` | Resolve coordinates to nearby stations |
| `inspect_coverage` | Check temporal availability before querying |
| `get_observations` | Retrieve a bounded raw series |
| `aggregate_observations` | Aggregate a longer series upstream |

## Output semantics

Observation results distinguish:

- station identity and location;
- observation or aggregation-bucket timestamp;
- metric and unit;
- VRA data type;
- requested UTC interval;
- retrieval timestamp;
- provider and source operation;
- truncation and upstream warnings.

The coverage endpoint currently omits composed operational type `101`. When related
type `100` coverage exists, `vizugy` returns it with an explicit inference warning; it
does not silently claim equivalence.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VIZUGY_ARCGIS_URL` | `https://geoportal.vizugy.hu/arcgis/rest` | ArcGIS catalogue root |
| `VIZUGY_VRA_URL` | `https://vmservice.vizugy.hu/vraquery` | VRAQuery API root |
| `VIZUGY_TOKEN_URL` | `https://data.vizugy.hu/AuthApi/auth/token` | Public frontend token endpoint |
| `VIZUGY_TIMEOUT_SECONDS` | `15` | Upstream request timeout |
| `VIZUGY_CACHE_TTL_SECONDS` | `300` | ArcGIS metadata cache lifetime |

## Development

```bash
uv sync --extra mcp --extra test
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
uv run pytest -q
```

Design decisions, verified upstream behavior, and unresolved questions are documented
in [`docs/design.md`](docs/design.md) and [`docs/phase-2-review.md`](docs/phase-2-review.md).

## Licence and data attribution

The software licence has not yet been finalized in this repository. Public endpoint
access alone does not establish unrestricted reuse rights for every upstream dataset.
Preserve OVF provenance and verify the applicable terms before redistribution or
production use.
