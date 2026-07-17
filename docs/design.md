# Design and review

## Recommendation

Proceed CLI-first with a shared typed application layer and thin CLI/MCP adapters.
Keep observations out of the stable API until OVF documents their semantics and reuse
terms. Do not expose arbitrary ArcGIS SQL.

## Verified 2026-07-17

- `https://geoportal.vizugy.hu/arcgis/rest/services?f=pjson` is public ArcGIS 10.61.
- The root advertised 35 folders and seven services. Relevant folders include `OVSZ`,
  `VIR`, and `Honlap`.
- `VIR/Vizmercek_vizugyhu_orszagos_adatsoros` supports Data/Map/Query and GeoJSON.
- Its layer 6 returned 273 station feature IDs, Web Mercator source geometry, and a 1,000-row
  service limit. ArcGIS reports `supportsPagination: false`; a request using
  `resultRecordCount=2` returned `Pagination is not supported`. `returnIdsOnly=true`
  returned all 273 IDs; bounded retrieval therefore needs ID chunking, not offsets.
- Querying object IDs 7 and 21 with `outSR=4326` returned valid GeoJSON point features.
- Service/layer descriptions and `copyrightText` were empty. Public accessibility is
  not evidence of an open-data licence.
- `data.vizugy.hu` responds, but no documented stable API or reuse terms were verified.
- Official MCP Python SDK stable line is v1; v2 is pre-release. Pin `<2` for this slice.

## Inferences

- ArcGIS is suitable for discovery, schema inspection, station search, and bounded
  feature reads, provided each dataset has an explicit mapping and contract fixture.
- Station IDs should prefer the published VOR/AllomasVOR code; upstream object IDs are
  provider cursors, not domain identity.
- Observation tables are operational views, not yet a trustworthy public contract.

## Unresolved

- OVF reuse/licensing, attribution wording, acceptable request rate, and support policy.
- Authoritative update timestamps; catalogue metadata does not consistently expose them.
- Exact timezone, units, quality flags, and retention guarantees for observations.
- Whether EOV coordinates are consistently EPSG:23700 when exposed as EOVx/EOVy.

## Architecture

`models` defines stable domain envelopes and provenance. `providers` owns ArcGIS wire
format, retries, caching, schema drift, and later ID-chunk pagination. `service` owns
intent operations and bounds. CLI and MCP call only `service`.

Errors: retry transport failures and 429/5xx twice with short exponential backoff;
never retry validation/not-found; emit no partial success without explicit truncation.
Cache metadata for five minutes in-process. Later use conditional requests and an
optional XDG disk cache; never cache observations by the same policy as catalogue data.

Every normalized record should eventually carry: stable ID, label, WGS84 geometry,
source CRS, `observed_at`, `published_at` when known, value/unit, quality flag,
provider-specific `raw`, and provenance (`provider`, URL, retrieval time, upstream
version). Unknown values remain null, never guessed.

## Public interfaces

CLI first slice:

- `vizugy datasets list [--query TEXT] [--limit N] [--format json|jsonl]`
- `vizugy datasets describe ID [--layer N]`

JSON is one envelope. JSONL is one item per line followed by a tagged `_meta` line.
Stdout contains data only; stderr diagnostics only. Exit codes: 0 success, 2 usage,
3 upstream, 4 absent. Default limit 50; hard maximum 1,000.

MCP first slice: `discover_datasets`, `describe_dataset`. Resources later: static
dataset schemas and provider status. Tools perform parameterized/current reads. No
prompts in v1: they add little stable capability.

Next user journeys, in order: station text search; nearest station; bbox feature query;
experimental recent observations from an explicitly mapped provider; observation range.
Proposed MCP tools: `find_stations`, `nearest_stations`, `query_features`, and only after
verification `get_observations`.

## Roadmap

1. Current slice: catalogue discovery/description; deterministic provider tests.
2. Explicit station adapter for one nationwide layer; ID-chunk pagination, field
   selection, bbox and nearest search; fixtures and CLI/MCP equivalence tests.
3. Clarify OVF terms and document attribution/rate policy; add schema-drift canary.
4. Experimental observation adapter with timestamps, units, quality semantics.
5. Optional HTTP MCP deployment only if real clients require it.
