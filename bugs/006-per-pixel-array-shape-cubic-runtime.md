# 006 — Raster plugins revalidate the whole array for every pixel: O(H²·W) runtime

| Field | Value |
|---|---|
| Package | smart-spatial-system==0.5.6 (pinned); also present in 0.3.0 |
| Component | `_band_value` / `_pixel_value` in `ndvi_calculator`, `raster_reclassify`, `band_math`, `zonal_statistics`, `raster_to_vector` (and the equivalent in `spectral_indices`); `zonal_statistics._collect_zone_values` |
| Severity | high (full-resolution Sentinel-2 analysis is not feasible) |
| Kind | performance |
| Found while | sizing the analysis grid for step 1 |
| Repro | `python scripts/verify_bugs.py` → check `B6` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |

## Summary
Every per-pixel read calls `_array_shape(data)`, which loops over **all rows** (and, for 3-D input,
all bands) to check that widths agree. A read is O(H) instead of O(1), so one pass over an H×W
raster costs O(H²·W): 4× the pixels → ~8× the time.

## Measurements (this machine, `calculate_ndvi`, 2-band input)

| Raster | Pixels | Time |
|---|---:|---:|
| 100×100 | 10 k | 0.25 s |
| 200×200 | 40 k | 1.8 s |
| 400×400 | 160 k | 15.4 s |
| 492×562 (Cairo AOI @ 60 m) | 277 k | 32 s |
| ≈2950×3370 (Cairo AOI @ 10 m) | 9.9 M | ≈ 2 h *(extrapolated, per plugin call)* |

The full 60 m pipeline (16 plugin calls) takes about 6 minutes. At native 10 m it would take more
than a day, and the nested-list representation (plus `deepcopy` in `_extract_raster`) would need
several GB of RAM.

`zonal_statistics` adds a second factor: `_collect_zone_values` runs a full point-in-polygon test
for **every pixel of the raster for every zone**, with no bbox pre-filter (the bbox is computed but
only used in `all_touched` mode). Cost is O(zones × H × W × vertices).

## Root cause
```python
def _band_value(data, *, band_index, row, col):
    bands, _height, _width = _array_shape(data)   # O(H) validation, every pixel
```

## Impact on this case study
The analysis runs on a 60 m grid (area-average of 10 m reflectance) instead of the native 10 m.
This is a stated limitation (paper §2.4, §5): small parks and street trees are diluted, so
fine-scale loss is underestimated. The plugins' logic is not bypassed. District polygons are
simplified with a 5 m tolerance, which is sub-pixel at 60 m, to bound the zonal cost.

## Suggested fix (not applied here)
Call `_array_shape` once per plugin call and pass `(bands, height, width)` down (or index
directly); in zonal statistics, skip pixels outside the zone bbox before the polygon test (or
rasterise each zone once). A numpy engine (`engine="numpy"`; the `auto` engine already exists in
the validators) would give a 100–1000× speed-up.
