# Design and review

## Recommendation

Proceed CLI-first with a shared typed application layer and thin CLI/MCP adapters.
Use the documented VRAQuery API for water observations; use ArcGIS for spatial
catalogue discovery. Do not expose arbitrary ArcGIS SQL or make anomaly judgments.

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
- Correction after broader discovery: the official frontend uses VRAQuery, documented
  by OpenAPI 3.0.1 at
  `https://vmservice.vizugy.hu/vraquery/swagger/v1.0/swagger.json`. It exposes 39
  schemas for station catalogues, metric/data-type catalogues, time-series filters,
  quality classifications, aggregation, and forecasts.
- Its public frontend token flow is available through
  `https://data.vizugy.hu/AuthApi/auth/token` with the official site origin/referrer.
- Live VRAQuery verification returned 1,190 active surface-water stations. The metric
  catalogue explicitly defines units and acceptable ranges; e.g. surface water level
  code 68 uses `cm`, and discharge code 87 uses `m3/s`.
- Official MCP Python SDK stable line is v1; v2 is pre-release. Pin `<2` for this slice.

## Inferences

- ArcGIS is suitable for discovery, schema inspection, station search, and bounded
  feature reads, provided each dataset has an explicit mapping and contract fixture.
- VRAQuery's hydrological registry number (`Tsz`) is the documented station identity;
  public IDs namespace it as `surface:<Tsz>`.
- ArcGIS observation tables are operational views and are no longer the preferred
  observation contract. VRAQuery is the preferred source.

## Unresolved

- OVF reuse/licensing, attribution wording, acceptable request rate, and support policy.
- Authoritative update timestamps; catalogue metadata does not consistently expose them.
- Retention guarantees and the exact validation status of each data-type code.
- Whether EOV coordinates are consistently EPSG:23700 when exposed as EOVx/EOVy.

## Architecture

`models` defines stable domain envelopes and provenance. `providers` owns ArcGIS
catalogue behavior. `vra_provider` follows the published OpenAPI contract for stations,
catalogues, and observations. Its Pydantic wire models are generated from the pinned
OpenAPI schema; `vra_provider` retains transport policy and maps them into curated public
domain DTOs. `service` owns intent operations and bounds. CLI and MCP call only
`service`.

Generated wire models follow the schema's closed-object contracts. Additive upstream
fields therefore fail validation as `UpstreamError`; recovery is an intentional schema
re-pin, model regeneration, and contract-test review. Provider `raw` values retain the
original parsed JSON rather than the normalized Pydantic serialization.

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
- `vizugy catalog measurements`
- `vizugy stations search [QUERY] [--watercourse TEXT] [--municipality TEXT]`
- `vizugy stations nearest LATITUDE LONGITUDE`
- `vizugy observations get STATION --metric NAME_OR_CODE --data-type NAME_OR_CODE`

JSON is one envelope. JSONL is one item per line followed by a tagged `_meta` line.
Stdout contains data only; stderr diagnostics only. Exit codes: 0 success, 2 usage,
3 upstream, 4 absent. Default limit 50; hard maximum 1,000.

MCP tools mirror these intents: `discover_datasets`, `describe_dataset`,
`list_measurement_types`, `find_stations`, `nearest_stations`, and
`get_observations`. Resources later: static dataset schemas and provider status. No
prompts in v1: they add little stable capability.

Implemented user journeys: station search with watercourse/municipality filters,
nearest station, authoritative measurement catalogue, and bounded observation ranges
with explicit metric/data-type selection. The agent receives typed values, UTC times,
units, and provenance; anomaly interpretation remains with the agent.

Phase 2 adds coverage inspection, query explanation, seven-day raw-query safety bounds,
and documented VRAQuery server-side aggregation (`min`, `max`, `avg`, `sum`, `cnt`,
`mean`, `cntday`) over daily, ten-day, monthly, or yearly buckets. Observation points
are compact; station-independent query metadata and provenance appear once per result.

## Roadmap

1. Current slice: catalogue discovery/description; deterministic provider tests.
2. Current slice: VRAQuery station search, nearest lookup, measurement catalogue, and
   bounded time-series retrieval; recorded provider fixtures and MCP parity.
3. Phase 2: coverage, dry-run query plans, safe raw bounds, and server aggregation.
4. Next: bilingual discovery/entity resolution, cache/freshness metadata, and bounded
   spatial feature queries.
5. Clarify OVF terms and document attribution/rate policy; add schema-drift canary.
6. Generate broader VRAQuery wire clients from OpenAPI; expose documented quality and
   aggregation filters without inventing semantics.
7. Optional HTTP MCP deployment only if real clients require it.

## Verified VRA soil dimension 2026-07-19

VRA metric 299 is soil moisture (`%`) and 303 is soil temperature (`C°`). Their
time-series `DataExt` values 10, 20, 30, 45, 60, and 75 correspond to sensor depth in
centimetres. The documented raw and filtered requests accept `DataExtFilter`; filtered
queries retain server-side aggregation. Keep `DataExt` generic in the domain model and
add `depth_cm` only as a verified semantic dimension for these two metrics.

`DataCatalogMinMax` returned soil-moisture coverage for 24 active precipitation-network
stations, but its live rows did not distinguish `DataExt`. Depth availability therefore
comes from bounded observation queries, not inferred coverage. The separate drought API
remains a possible later provider for broader station coverage, HDI, and water-deficit
variables absent from the VRA metric catalogue.
