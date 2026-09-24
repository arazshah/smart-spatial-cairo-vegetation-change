# 001 — `local_raster_loader` output cannot be fed to any raster analysis plugin

| Field | Value |
|---|---|
| Package | smart-spatial-system 0.3.0 – 0.5.6 |
| Component | `plugins/local_raster_loader.py` → `load_local_raster`; `plugins/raster_clip_mask.py` → `_extract_raster` (used by ndvi_calculator, spectral_indices, band_math, raster_reclassify, zonal_statistics, raster_to_vector, …) |
| Severity | high |
| Kind | integration break / crash |
| Found while | step 1 — loading the clipped Sentinel-2 reflectance GeoTIFFs for `calculate_ndvi` |
| Repro | `python scripts/verify_bugs.py` → check `B1` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |
| Status | Fixed in 0.5.7 — checked 2026-09-24 with `scripts/verify_bugs.py` |

## Summary
The only raster *source* plugin returns `geochat_sdk.types.raster.RasterOut(path=..., metadata=...)`,
an object with **no pixel data** (`vars(r) == {'path', 'metadata'}`). Every raster *analysis*
plugin reads pixels through `_extract_raster`, which requires either a `.data` attribute or a dict
with `data`/`array`. The natural chain `load_local_raster → calculate_ndvi` therefore raises.

## Minimal reproduction
```python
r = load_local_raster("two_band.tif")          # valid 2-band GeoTIFF
calculate_ndvi(r, red_band=1, nir_band=2)
```

## Expected
NDVI raster (the loader's docstring says it exposes the file "for downstream raster plugins").

## Actual
`ValueError: raster must be RasterOut-like object or dict with data/array.`

## Root cause
`_extract_raster` branch 1 is `hasattr(input_data, "data")`; SDK `RasterOut.__init__` only sets
`path` and `metadata`. No component reads the file behind `path` into memory. (Analysis plugins
attach `.data` to their own outputs via `_make_raster_out`, so plugin→plugin chains work; only
loader→plugin is broken.) Note also that `metadata["transform"]` from the loader *is* in the
list form the analysis plugins expect, so only the pixel payload is missing.

## Impact on this case study
The loader is still called on every input (CRS, band count, transform validation), but the pixels
are materialised with rasterio into the documented `{"data": [[...]], "metadata": {...}}` form
(`scripts/04_run_s3geo_pipeline.py`). This is conversion into a documented input format, not a
change to any computation.

## Suggested fix (not applied here)
Either have `_extract_raster` lazily read `path` with rasterio when `.data` is absent, or give the
loader an `include_data: bool` option that returns `{"data": src.read().tolist(), "metadata": ...}`.
