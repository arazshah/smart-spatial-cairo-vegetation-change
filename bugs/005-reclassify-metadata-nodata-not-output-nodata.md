# 005 — `raster_reclassify` output advertises the *input* nodata, not `output_nodata`

| Field | Value |
|---|---|
| Package | smart-spatial-system 0.3.0 – 0.5.6 |
| Component | `plugins/raster_reclassify.py` → `reclassify_raster` (output metadata) |
| Severity | high when `output_nodata` differs from the input nodata (silently wrong downstream stats) |
| Kind | wrong result (metadata contract) |
| Found while | step 3 — choosing nodata handling for the class rasters |
| Repro | `python scripts/verify_bugs.py` → check `B5` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |
| Status | Fixed in 0.5.7 — checked 2026-09-24 with `scripts/verify_bugs.py` |

## Summary
Nodata pixels are written as `output_nodata`, but the output metadata keeps `"nodata": <input nodata>`
(and adds a separate `"output_nodata"` key that no downstream plugin reads). Every consumer
(`zonal_statistics`, `raster_to_vector`, `band_math`, …) resolves nodata from `metadata["nodata"]`,
so the reclassified nodata value is counted as real data.

## Minimal reproduction
```python
ras = {"data": [[-9999.0, 0.5], [0.1, 0.9]], "metadata": {"nodata": -9999.0, "transform": [1,0,0,0,-1,2]}}
rc = reclassify_raster(ras, rules=[{"min": -1, "max": 1, "value": 1}], output_nodata=0)
calculate_zonal_statistics(rc, [square_over_all_4_px], stats=["valid_count", "mean"])
```

## Expected
`rc.metadata["nodata"] == 0`; zonal `valid_count == 3`, `mean == 1.0`.

## Actual
`rc.metadata["nodata"] == -9999.0`; zonal `valid_count == 4`, `mean == 0.75`.

## Root cause
`output_metadata = {..., "nodata": final_nodata, "output_nodata": final_output_nodata, ...}` —
the key downstream plugins read describes the input, not the array being returned.

## Impact on this case study
The pipeline uses `None` as the only nodata marker end-to-end (input nodata = output nodata =
`None`), for which the bug has no effect. Stated in paper §2.3.

## Suggested fix (not applied here)
Set `"nodata": final_output_nodata` (keep the input value under `"input_nodata"`).
