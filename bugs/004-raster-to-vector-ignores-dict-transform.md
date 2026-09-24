# 004 — `raster_to_vector` silently ignores a dict transform and emits pixel coordinates

| Field | Value |
|---|---|
| Package | smart-spatial-system==0.3.0 |
| Component | `plugins/raster_to_vector.py` → `_extract_transform` |
| Severity | medium (silent wrong georeferencing) |
| Kind | wrong result / API inconsistency |
| Found while | reviewing transform handling before step 5 |
| Repro | `python scripts/verify_bugs.py` → check `B4` |

## Summary
`zonal_statistics` and `raster_clip_mask` accept `metadata["transform"]` as a list **or a dict**
(`_normalize_transform`). `raster_to_vector` accepts only a list/tuple; anything else falls through
*without warning* to a default transform `[1, 0, 0, 0, -1, 0]`, so polygons come out in pixel units
at the origin. It also does not look at `metadata["affine_transform"]`, which the shared helper
does.

## Minimal reproduction
```python
tf = {"a": 10, "b": 0, "c": 300000, "d": 0, "e": -10, "f": 3330000}
raster_to_vector({"data": [[1]], "metadata": {"transform": tf}}, include_values=[1])
```

## Expected
Cell polygon starting at (300000, 3330000), or a clear error.

## Actual
First vertex `[0.0, 0.0]`; only hint is `metadata["transform_source"] == "default_transform"`.

## Root cause
`_extract_transform` handles `isinstance(transform, (list, tuple))` only, then silently builds a
default from config (`default_origin_x/y = 0`, `default_x/y_resolution = 1`).

## Impact on this case study
Rasters always carry the list form, and the pipeline asserts
`transform_source != "default_transform"` implicitly by cross-checking cell counts per district
(`scripts/06_crosscheck.py`). No effect on results.

## Suggested fix (not applied here)
Reuse `raster_clip_mask._get_transform_from_metadata` (after fixing bug 007) and raise when a
transform is present but unparseable.
