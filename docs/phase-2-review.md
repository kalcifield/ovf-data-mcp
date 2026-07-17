# Phase 2 agent investigation review

## Findings

Already useful: official VRAQuery metric/data-type catalogues, station search, nearest
lookup, explicit units, bounded output, and provenance. Blocking efficient
investigation: no coverage call, implicit time defaults, raw queries that downloaded
before truncating, repeated metadata on every point, and no dry-run interpretation.

Reference patterns retained:

- World Bank Data360 MCP: search results enriched with coverage/dimensions; compact
  result envelopes retain provenance.
- U.S. Census Data API MCP: resolve human entities before structured data queries.
- Japan e-Stat MCP/CLI: matching intent operations, explicit filters, and bounded data
  retrieval across Python and MCP surfaces.

Not adopted: large local metadata databases, general analytics, automatic anomaly
judgment, unrestricted all-page retrieval, or a generic ArcGIS query tool.

## Implemented milestone

- `observations coverage`: documented `DataCatalogMinMax` temporal bounds.
- `observations get`: explicit bounds, maximum seven raw days, compact points,
  truncation metadata.
- `observations aggregate`: documented upstream aggregation and bounded bucket count.
- `--explain`: resolves identifiers/codes and shows upstream operation without values.
- MCP equivalents: `inspect_coverage`, `aggregate_observations`; raw query tightened.

Known upstream inconsistency: coverage returns no row for composed operational data
type 101. If type 100 exists, the tool returns it with an explicit inference warning.
Aggregation bucket labels may precede the requested UTC boundary because the upstream
service uses hydrological/local-day boundaries; values retain its UTC bucket labels.

## Deferred

Bilingual vague dataset discovery, settlements/catchments/VIZIG entity resolution,
sampling-gap estimates, cache age/status, quality-code filters, spatial feature
queries, and multi-series comparison. These need separate coherent slices.
