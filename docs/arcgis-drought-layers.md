# ArcGIS drought layers — findings

Live probe of the public ArcGIS catalogue, asking whether the ArcGIS path holds
drought capability the VRAQuery path lacks. Recorded so the negative results are not
rediscovered.

## Verified 2026-07-20

Catalogue: 224 datasets across 20 public folders; 5 folders (`DDVIZIG`, `FETIVIZIG`,
`KDVVIZIG`, `NYUDUVIZIG`, `TIVIZIG`) return code 499 and are skipped with warnings.
Most content is cartographic (flood, ice, inland water, raster imagery). Two drought
folders matter.

### `Aszalymon/Aszaly_fokozatok` — useful, not yet exposed

Layer 0 `vizhiany_korzetek_elrendelt_fokozatban`, polygons, 85 water-shortage
districts, `maxRecordCount` 2000, `supportsPagination: false`.

- Every district carries a declared emergency grade (`Fokozat`/`FokozatKod`), the
  declaring act (`fvNev`, e.g. `ELRENDELÉS`), and a timestamp (`Idopont`).
- Live on probe day: 28 districts at `III. fok`, 34 at `II. fok`, 9 at `I. fok`,
  13 at `-`. `Idopont` range 2024-09-12 → 2026-07-19, i.e. actively maintained.
- This is the official administrative response to drought — which authority declared
  what level, where, when. VRAQuery exposes measurements only and has no equivalent.
- Being polygons, it is also the only route to a real map in an example page.

### `Aszalymon/Aszaly_monitoring_allomasok` — mostly empty

Layer 0 `vObjHidrometAllomas`, points, 127 stations, `supportsPagination: true`.

- Declares `HmWP10…HmWP75` (wilting point) and `HmFC10…HmFC75` (field capacity) at
  exactly the six depths the soil-moisture workflows use. These would turn a raw
  sensor percentage into plant-available water.
- **All twelve fields are null for all 127 stations.** `HidrometTalajnedvesseg` is
  likewise 0/127. Schema only, no data. Do not build on them without re-probing.
- Station metadata is uneven: `HidrometTerepmag` 127/127, `AllomasUzemeltetoVOANev`
  120/127, `Magassag` 29/127, `HidrometVizgyVOANev` 10/127, `HmOntozorendszerNev`
  0/127.
- `HidrometTorzsszam` matches the VRAQuery registry number (Városföld → 6994), so the
  two providers join on station identity without fuzzy matching.

## Implemented 2026-07-20

`ArcGISProvider.query_features()` now performs bounded attribute reads: the caller
passes an explicit `where` and field list, geometry is never requested, and rows are
capped client-side because the layer reports `supportsPagination: false`. It stays an
internal adapter, so the public interface still exposes no arbitrary SQL.

`VizugyService.water_shortage_districts()` reads the declaration fields only and is
exposed as `vizugy datasets water-shortage` and the `water_shortage_districts` MCP
tool. The stale `L0Készültségi_szint.*` index block is excluded by field list, and the
result carries a standing warning that grades are declarations rather than
measurements.

Live check on implementation day reproduced the probe: 85 districts, 28 at `III. fok`,
34 at `II. fok`, 9 at `I. fok`, latest declaration 2026-07-19.

The wilting-point and field-capacity gap remains: with `HmWP*`/`HmFC*` null
everywhere, sensor percentages cannot be converted to plant-available water, so soil
moisture stays comparable only within a station across time, never between stations.
