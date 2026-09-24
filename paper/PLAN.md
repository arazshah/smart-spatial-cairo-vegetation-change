# Paper plan — Cairo vegetation change 2015 → 2025 with s3geo

## Purpose (two audiences)

1. **Urban-environment question**: how has vegetation health and extent (NDVI) changed across
   Cairo over ~10 years, and which districts lost the most?
2. **Tool demonstration**: show a reproducible remote-sensing workflow built from
   `smart-spatial-system==0.5.7` (s3geo) plugins, including an honest account of what worked and
   what did not (bug reports in `bugs/`).

## Outcome vs plan (added after the analysis)

This plan was written before the data were seen and is kept as written. The deviations were:

- **Period:** 2017 → 2025 instead of ~2015 → 2025, because Earth Search has no L2A over Cairo before 2017.
- **District layer:** geoBoundaries ADM2 instead of OSM, because OSM has no qism relations in Cairo.
- **Extra step:** a water-masked sensitivity run was added after the change map was inspected.

All three are explained in `paper/paper.md` §2.1 and §3.4.

## Research question

How has NDVI changed across Cairo between a dry-season scene from ~2015 and one from ~2025,
and which districts show the sharpest decline?

Sub-questions
- RQ1: What share of the AOI changed vegetation class, and in which direction?
- RQ2: Ranking of districts by mean ΔNDVI and by area of decline (both reported: a small district
  can have a large mean drop, a large one a big absolute loss).
- RQ3 (context): does decline sit at the desert/agricultural fringe (urban expansion onto farmland)
  or inside the core (loss of parks and street trees)?

## Data  → `data/README.md`

Sentinel-2 L2A B04/B08 (Earth Search STAC, public COGs), 2 dates, same MGRS tile, dry season,
< 5 % cloud; OSM admin boundaries at the qism/hayy level found by inspection.

## Method (every analytical step is an s3geo plugin)

| # | Step | Plugin → capability | Key parameters |
|---|---|---|---|
| 0 | Validate inputs | `local_raster_loader.load_local_raster` | CRS / band count check |
| 1 | NDVI per date | `ndvi_calculator.calculate_ndvi` | red=1, nir=2, clip [-1, 1] |
| 2 | ΔNDVI; vegetation mask | `band_math.calculate_band_math` | `b2 - b1`; `where(b1 >= 0.2, 1, 0)` |
| 3 | Vegetation-health classes; change classes | `raster_reclassify.reclassify_raster` | NDVI: water < 0 ≤ built/bare < 0.1 ≤ sparse < 0.2 ≤ moderate < 0.4 ≤ dense; ΔNDVI: strong decline < −0.15 ≤ decline < −0.05 ≤ stable ≤ 0.05 < gain ≤ 0.15 < strong gain |
| 4 | Per-district statistics, both dates + Δ | `zonal_statistics.calculate_zonal_statistics` | `all_touched=False` (bug 002), mean/median/std/valid_count |
| 5 | Change table | `raster_to_vector.raster_to_vector` (cells) → `centroid_extractor.extract_centroids` → `spatial_join.spatial_join_features` (within) → `attribute_statistics.calculate_attribute_statistics` (group by district × class) | changed classes only |
| V | Verification | `scripts/06_crosscheck.py` (numpy/rasterio re-computation) | must agree within rounding |

Analysis grid: UTM 36N, 60 m (area-average of 10 m reflectance) — forced by bug 006; the
effect of coarsening is discussed as a limitation. Fixed thresholds were set before seeing results.

## Outputs → `paper/paper.md`

- Fig 1 NDVI before/after maps · Fig 2 ΔNDVI change map · Fig 3 change classes + district
  choropleth · Fig 4 ranked bar chart of declines
- Table 1 AOI class areas per date · Table 2 AOI change-class areas · Table 3 ranked districts
- Section "Using s3geo: what worked, what broke" referencing bugs 001–008

## Threats to validity (to address in the paper)

- Two single dates: inter-annual irrigation / fallow timing can mimic change → dry-season window,
  same tile & similar DOY; state as limitation (a multi-date composite would be the fix).
- Sensor change S2A (2015) vs S2A/B/C (2025) and processing baseline change → reflectance offset
  handling + C1 reprocessed collection.
- Nile water level/turbidity alters water-pixel NDVI → water class excluded from vegetation
  metrics via `NDVI >= 0.2` mask.
- 60 m averaging dilutes street trees and small parks → report as underestimate of fine-scale loss.
- OSM boundary completeness varies → list districts dropped (< 50 % inside AOI).

## Status

- [x] Phase 0: CLAUDE.md, requirements.txt, data/README.md, this plan
- [x] Plugin source review + bug reproductions (`scripts/verify_bugs.py`, `bugs/001–008`)
- [x] Pin moved to 0.5.6 (latest); all 8 bugs re-verified, plugin sources unchanged since 0.3.0
- [x] Pipeline dry-run on synthetic data; plugin output == independent reference
- [x] Real data: S2 2017-08-27 / 2025-09-01 (no L2A before 2017 on Earth Search); districts from
      geoBoundaries ADM2 because OSM has no qism relations in Cairo (only admin_level 2 and 4)
- [x] Real run (18.5 min on 0.5.6), crosscheck ≤ 5e-5, water-masked sensitivity, figures, paper.md final

- [x] 0.5.7 upstream fix release verified: bugs 001–007 fixed, 008 open; re-run gives identical numbers (55 s)
- [ ] Optional: re-run at 20 m / 10 m (runtime fine on 0.5.7; memory-bound at 10 m on 7 GB)
