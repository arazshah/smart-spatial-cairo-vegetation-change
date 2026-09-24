# 002 — `zonal_statistics(all_touched=True)` selects the zone's whole bounding box

| Field | Value |
|---|---|
| Package | smart-spatial-system==0.3.0 |
| Component | `plugins/zonal_statistics.py` → `_pixel_matches_zone` |
| Severity | high (silently wrong statistics) |
| Kind | wrong result |
| Found while | step 4 — choosing the pixel-selection rule for district zonal statistics |
| Repro | `python scripts/verify_bugs.py` → check `B2` |

## Summary
With `all_touched=True`, a pixel is assigned to a zone when the **pixel's bbox intersects the
zone's bbox** — the polygon geometry is never consulted. For any non-rectangular zone this adds
every pixel in the bounding box, including pixels belonging to neighbouring zones. The name
follows the rasterio/GDAL convention ("every pixel the geometry touches"), so users will
reasonably expect geometric behaviour.

## Minimal reproduction
10×10 raster of 1.0, unit pixels; zone = right triangle covering the lower-left half.
```python
calculate_zonal_statistics(ras, [tri], stats=["count"], all_touched=False)  # count = 45
calculate_zonal_statistics(ras, [tri], stats=["count"], all_touched=True)   # count = 100
```

## Expected
At most 55 + the boundary pixels crossed by the hypotenuse (< 70), never 100.

## Actual
100 — every pixel in the triangle's bbox.

## Root cause
```python
if all_touched:
    return _bboxes_intersect(_pixel_bbox(row, col, transform), geometry_bbox)
```
The docstring even says "pixel bbox intersection with zone bbox is used", so this is documented,
but it contradicts the parameter's established meaning and makes every statistic wrong for
irregular polygons (Cairo districts are elongated along the Nile — their bboxes overlap heavily).

## Impact on this case study
All zonal runs use `all_touched=False` (pixel-centre-in-polygon, which *is* geometric). Stated
in paper §2.3.

## Suggested fix (not applied here)
Test real pixel-polygon intersection (e.g. shapely `box(...).intersects(geom)`, with the bbox test
kept only as a cheap pre-filter), or rename the option to `bbox_mode`.
