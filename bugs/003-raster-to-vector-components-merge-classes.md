# 003 — `raster_to_vector(mode="components")` merges adjacent pixels of different classes

| Field | Value |
|---|---|
| Package | smart-spatial-system==0.5.6 (pinned); also present in 0.3.0 |
| Component | `plugins/raster_to_vector.py` → `_connected_components` / component branch of `raster_to_vector` |
| Severity | high (wrong class labels and areas) |
| Kind | wrong result |
| Found while | step 5 — trying to vectorise change-class patches |
| Repro | `python scripts/verify_bugs.py` → check `B3` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |

## Summary
Connected components are grown over a boolean "selected" grid, not over equal values. When
`include_values` holds more than one class, neighbouring pixels of *different* classes fuse into
one feature, and the feature's `value`/`class_value` is simply the value of its first cell.
Additionally each component's geometry is its bounding box (documented), so component polygons
overlap and their areas are not the pixel areas.

## Minimal reproduction
```python
cls = {"data": [[1, 1, 2, 2], [1, 1, 2, 2]], "metadata": {"transform": [1,0,0,0,-1,2]}}
raster_to_vector(cls, include_values=[1, 2], mode="components", connectivity=4)
```

## Expected
Two features: class 1 (4 px) and class 2 (4 px).

## Actual
One feature `{"value": 1, "pixel_count": 8}` — class 2 disappears.

## Root cause
`_selected_grid` collapses values to `True/False`; `_connected_components` only checks
`selected[n_row][n_col]`, never `value(n) == value(seed)`.

## Impact on this case study
Components mode is not used. Change pixels are vectorised with `mode="cells"` (exact per-pixel
squares) and aggregated by `attribute_statistics`, which is correct but produces many features —
one reason the analysis runs at 60 m (see bug 006).

## Suggested fix (not applied here)
Grow components only across neighbours with equal value (per-class labelling), and optionally
dissolve cells into true outlines (e.g. `rasterio.features.shapes`) instead of bounding boxes.
