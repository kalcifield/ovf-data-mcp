# OVF upstream behaviour — observed limits and data gaps

Live observations of how the public OVF services behave under a real multi-station
workload. Recorded so the same failures are not re-diagnosed from scratch. Companion to
`arcgis-drought-layers.md`, which covers ArcGIS layer contents.

## Verified 2026-07-20

Workload: a soil-moisture sweep over 24 precipitation-network stations in the
Duna–Tisza köze and Dél-Alföld — coverage checks, then daily depth comparisons for
2022 and 2026. Roughly 125 requests, strictly sequential, over about 25 minutes.

### Aggregation cost scales with the raw span, not the response size

`TS/TSListFilterShort` (behind `observations aggregate` and `observations
compare-depths`) times out on long intervals regardless of how few buckets are
requested. Measured on `precip:6994`, six depths, midday:

| span | interval | result |
|------|----------|--------|
| 80 days | tenday | 48 points returned |
| 95 days | tenday | ReadTimeout on all three attempts |
| 105 days | tenday | ReadTimeout on all three attempts |
| 105 days | daily | succeeded earlier the same morning |

Coarser aggregation therefore reduces transfer size and page weight but **not**
upstream work: the server still scans the same raw interval. Chunking by date is the
only lever that helps. Do not assume `--interval tenday` makes a long window safe.

### The service degrades measurably through the day

The same 105-day chunks that succeeded around 08:00 UTC were failing by 10:00 UTC. Of
84 chunk requests, the first ~26 produced 4 failures; the last ~40 produced 21. Light
endpoints stayed responsive throughout — `observations coverage`, `stations nearest`
and the ArcGIS catalogue all returned promptly while aggregation was timing out. The
degradation is specific to the aggregation path.

Total volume here was about one request every 12 seconds with no concurrency, which is
unlikely to be the cause, but the workload cannot be fully excluded as a contributor.
When aggregation starts timing out, stop and retry hours later rather than pushing
through: each retry costs the server a full scan before failing.

### Client-side bounds are ours, not upstream rejections

Two caps in `service.py` raise before any HTTP call:

- aggregation: >1000 buckets
- depth comparison: >1000 points (buckets × depths)

Both estimate from the requested span, so a sparse station trips them exactly like a
dense one. Six depths over 200 days daily = ~1212 points and is refused locally. These
exist to keep queries bounded, not because OVF rejects them.

Separately, raw `observations get` is limited to a 7-day interval.

### Retry policy

`VRAProvider` had no retry until 3f74002; a single `ReadTimeout` dropped a station from
a sweep. Both providers now share `upstream_retry()`: three attempts, exponential
backoff, retrying timeouts and 5xx only. 4xx, auth failures and malformed payloads fail
fast, since repeating a request upstream already refused only adds load. Note that
under the degradation above, chunks still fail all three attempts.

## Data gaps

### Catalogued stations can be long dead

`stations nearest --metric soil-moisture` returns stations by declared metric support,
not by whether data still arrives. `precip:210031` (Pusztamérges, meteorológiai kert)
advertises soil moisture but has coverage only for **2023-02-04 → 2023-02-08** under
both `operatív` (100) and `regisztrált` (2). Inside that window it returns 574 raw
points across six depths; across 2026-05-01 → 07-20 it returns zero days at all six
depths with an explicit warning. A sensor that logged four days three years ago and
never reported again.

Its readings are also suspect on their own: ~6.4–6.8 % at 20 cm while neighbouring
stations in the same window sat at 26–28 %, which reads more like a bad install than
dry soil. Excluded from analysis on both grounds.

**Always check `observations coverage` before including a station in a sweep.** Of the
24 stations returned for that area, 21 had a usable pre-2022 baseline; Gádoros
(from 2022-03-31) and Tótkomlós (from 2022-12-02) start mid-baseline, and Pusztamérges
is the dead one above.

### Aggregated series can start a day before the requested start

Daily aggregation with `--start 2025-07-18T00:00:00Z` returns a first bucket dated
**2025-07-17**. Observed on several stations and metrics, so it is systematic rather than
per-station. The likely cause is the hydrological-day boundary — the requested instant
falls inside the bucket labelled with the previous date — but that mechanism is inferred,
not confirmed upstream.

Consequences worth knowing: a series carries one more row than the requested span
suggests, and any prose quoting the requested window will disagree with the data by a
day. Four example pages shipped with exactly that mismatch. Label periods from the
returned data, not from the request.

Also note the reverse case: the last bucket may be a **partial** day. A row where
min, mean and max are all identical is the signature of a single reading rather than a
full day's aggregate, and should not be presented as a daily mean.

### Coverage is reported for a related data type

Requesting coverage for `operatív összefésült` (101) returns coverage for `operatív`
(100), with a standing warning saying so. This is uniform across stations, so
station-to-station coverage comparisons remain valid, but the reported window is not
strictly the window of the type being queried.

### Raw and aggregated paths disagree on availability

For historical windows, `observations get` can return nothing where
`observations compare-depths` returns a full series for the same station and interval.
The aggregate path is the reliable one for anything older than the operational
retention window. Diagnose "no data" claims on the aggregate path before concluding a
station is empty.

### No normalisation data for cross-station comparison

Wilting point and field capacity are published in the ArcGIS drought layer but are null
for all 127 stations (see `arcgis-drought-layers.md`). Raw soil-moisture percentages
are therefore **not comparable between stations** — soils and calibration differ. Only
within-station comparisons (same station, same depth, across time) are defensible.

The same rule holds for water levels: each gauge reports centimetres above its own local
datum, so absolute levels are not comparable between gauges either. On the Danube in
February 2026, Esztergom peaked at 399.6 cm while Komárom, upstream, peaked at 426.8 cm
— a datum artefact, not a hydrological fact. Any "highest" or "lowest" claim across
stations needs normalising against each station's own range, threshold or record.

### Station coordinates can be wrong

`stations` returns registry coordinates unchecked. Verified 2026-07-20:
`deep-well` **Ódörögdpuszta HgN-62** (municipality Zalahaláp) is published at
**45.5029 N, 17.4689 E**. The longitude is right; the latitude is roughly 1.4° too far
south, putting the well in Croatia, about 155 km from Zalahaláp.

This is upstream data, not a client bug — the same values come back from a plain
`vizugy stations search`. Do not silently correct them: a plausible-looking substituted
coordinate is fabricated data. Plot what upstream publishes and mark it, or exclude it
and say so.

A cheap guard for any map is a bounding-box check against Hungary
(lat 45.7–48.6, lon 16.1–22.9) with anything outside rendered distinctly rather than
dropped. `docs/examples/hungary-deep-groundwater-pulse.html` does this.

### Percentiles: the ranking base is smaller than the series

When ranking a recent value against history for the same calendar month, the evidence is
only the same-month subset, not the full series. In the deep-well example the 30 wells
hold 8,679 monthly values in total, but the percentiles rest on **731** same-month values
— 12 to 41 per well, median 22. At n=12 the resolution is 8.3 percentage points and
"0th percentile" means "below twelve numbers". Publish the per-entity n alongside the
rank, and do not present a percentile from n=12 as equivalent to one from n=41.

## Note on diagnosing empty results

`observations get` returns rows under `items`. A probe script reading a different key
will report zero rows for every station and can look exactly like an upstream outage.
Confirm against a station known to have data before concluding anything is missing.
