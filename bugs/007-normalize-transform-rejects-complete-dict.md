# 007 — `_normalize_transform` rejects a complete `{a..f}` dict transform

| Field | Value |
|---|---|
| Package | smart-spatial-system 0.3.0 – 0.5.6 |
| Component | `plugins/raster_clip_mask.py` → `_normalize_transform` (shared by zonal_statistics, raster_clip_mask) |
| Severity | medium |
| Kind | crash / API inconsistency |
| Found while | writing the repro for bug 004 |
| Repro | `python scripts/verify_bugs.py` → check `B7` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |
| Status | Fixed in 0.5.7 — checked 2026-09-24 with `scripts/verify_bugs.py` |

## Summary
A dict transform with all six affine keys `a, b, c, d, e, f` raises
`ValueError: Invalid transform dict.` unless a redundant `pixel_height` key is also present.

## Minimal reproduction
```python
tf = {"a": 10, "b": 0, "c": 300000, "d": 0, "e": -10, "f": 3330000}
calculate_zonal_statistics({"data": [[5.0]], "metadata": {"transform": tf}}, [unit_square], stats=["count"])
```

## Expected
count = 1.

## Actual
`ValueError: Invalid transform dict.` ← `TypeError: float() argument must be ... not 'NoneType'`.
Adding `"pixel_height": 10` makes it work.

## Root cause
```python
float(transform.get("e", -abs(float(transform.get("pixel_height")))))
```
Python evaluates the default argument eagerly, so `float(None)` runs even when `"e"` exists.

## Impact on this case study
None — list transforms are used throughout.

## Suggested fix (not applied here)
`e = transform["e"] if "e" in transform else -abs(float(transform["pixel_height"]))`.
