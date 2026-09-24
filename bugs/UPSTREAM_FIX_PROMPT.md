# Prompt for an upstream bug-fix session (smart-spatial-system)

Paste everything below the line into a new session that has the **smart-spatial-system source
repository** attached (not this case-study repo). The bug reports it refers to are in
`https://github.com/arazshah/smart-spatial-cairo-vegetation-change/tree/master/bugs`. They are
summarised inline below, so the session does not need that repo.

---

You are working in the source repository of `smart-spatial-system` (PyPI name; import roots
`plugins/`, `orchestrator/`, `s3geo/`, `smart_spatial_system/`, `config/`). The latest release is
**0.5.6**. An independent case study (Cairo NDVI change, repo `arazshah/smart-spatial-cairo-vegetation-change`)
found 8 defects. Each was reproduced on 0.3.0 and 0.5.6, and the affected plugin files are
byte-identical between those versions. Fix them in this repository and prepare release **0.5.7**.

## Ground rules

1. First create a branch `fix/cairo-case-study-bugs` from the default branch. Do not commit to main.
2. **Test first.** For every bug, add a failing regression test under the existing test suite
   (find it first: `tests/`, `pytest.ini`/`pyproject.toml`). Show that it fails, then fix the code
   and show that it passes. Use the minimal reproductions below verbatim as the test bodies.
3. Keep public signatures and default behaviour backward-compatible unless a bug *is* the default
   behaviour (002, 005); call out every behaviour change in `CHANGELOG`.
4. Stay dependency-free where a plugin is documented as "no external dependency". numpy and
   shapely are optional accelerators only, used behind `engine="auto"` with a pure-python
   fallback.
5. Run the **full** existing test suite before and after. Report the pass/fail counts and any
   pre-existing failures you did not cause.
6. One commit per bug (`fix(<plugin>): <summary> (#00N)`), plus one commit for version/changelog.
   Open a PR titled `Fix 8 bugs found by the Cairo NDVI case study (0.5.7)` with a table of
   bug → test → commit. Do not publish to PyPI; stop at the PR.

## The bugs (severity; file; reproduction; expected; fix direction)

**001 (high)**: the `local_raster_loader` output cannot be consumed by any raster analysis plugin.
- Where: `plugins/local_raster_loader.py` and `plugins/raster_clip_mask.py::_extract_raster`.
- Repro:
  ```python
  r = load_local_raster("two_band.tif")
  calculate_ndvi(r, red_band=1, nir_band=2)
  ```
  This raises `ValueError: raster must be RasterOut-like object or dict with data/array`. The
  SDK `RasterOut` only has `path` and `metadata`.
- Fix: in `_extract_raster`, when the input has no `.data` but has a readable `path`, lazily
  read it with rasterio (a clear `SDKDependencyError` if rasterio is missing) into band-first
  lists and fill `transform`/`crs`/`nodata` from the file. Map file nodata to `None`.

**002 (high, wrong results)**: `zonal_statistics(all_touched=True)` uses the zone *bbox*.
- Where: `plugins/zonal_statistics.py::_pixel_matches_zone`.
- Repro: take a 10×10 raster of 1.0 with transform `[1,0,0,0,-1,10]` and the zone
  `Polygon [[0,0],[10,0],[0,10],[0,0]]`.
  - `all_touched=False` gives 45 pixels.
  - `all_touched=True` gives 100 pixels. The correct answer is ≤ 65.
- Fix: select a pixel only when its square actually intersects the polygon, holes included.
  Keep the bbox test as a pre-filter. Update the docstring.

**003 (high, wrong results)**: `raster_to_vector(mode="components")` merges different classes.
- Where: `plugins/raster_to_vector.py::_connected_components`.
- Repro:
  ```python
  raster_to_vector(
      {"data": [[1,1,2,2],[1,1,2,2]], "metadata": {"transform": [1,0,0,0,-1,2]}},
      include_values=[1,2], mode="components")
  ```
  This returns one feature with value 1 and 8 px. It should return two features: class 1 with
  4 px and class 2 with 4 px.
- Fix: grow components only across neighbours with the same value.
- Optional: add `geometry="outline"`, which dissolves the cells of each component into a true
  polygon, as an alternative to the current bbox geometry. Keep `"bbox"` as the default and
  document it.

**004 (medium, silent wrong georeferencing)**: `raster_to_vector` ignores a dict transform or
`affine_transform`, and silently falls back to `[1,0,0,0,-1,0]`.
- Where: `plugins/raster_to_vector.py::_extract_transform`.
- Repro: `metadata.transform = {"a":10,"b":0,"c":300000,"d":0,"e":-10,"f":3330000}` gives a
  first vertex of `[0,0]`.
- Fix: reuse `raster_clip_mask._get_transform_from_metadata` (after fixing 007).
  - If a transform is present but can't be parsed, raise an error.
  - Use the config default only when no transform exists at all, and add a `warning` to the
    metadata when that happens.

**005 (high, wrong downstream results)**: `raster_reclassify` output metadata carries the *input*
nodata value.
- Where: `plugins/raster_reclassify.py::reclassify_raster`.
- Repro:
  ```python
  rc = reclassify_raster(
      {"data": [[-9999.0,0.5],[0.1,0.9]],
       "metadata": {"nodata": -9999.0, "transform": [1,0,0,0,-1,2]}},
      rules=[{"min": -1, "max": 1, "value": 1}], output_nodata=0)
  ```
  - `rc.metadata["nodata"]` is -9999.0; it should be 0.
  - A downstream `zonal_statistics` over all 4 px reports `valid_count` 4 and `mean` 0.75; it
    should report 3 and 1.0.
- Fix: set `"nodata": final_output_nodata` and add `"input_nodata": final_nodata`.
- Audit the other raster plugins (`band_math`, `ndvi_calculator`, `spectral_indices`,
  `raster_threshold`, `raster_clip_mask`) for the same pattern.

**006 (high, performance)**: runtime grows as O(H²·W).
- Where: `_band_value` / `_pixel_value` in `ndvi_calculator`, `raster_reclassify`, `band_math`,
  `zonal_statistics`, `raster_to_vector` and `spectral_indices`. Each calls
  `_array_shape(data)`, which walks every row, on **every pixel**.
- Measured with `calculate_ndvi`:

  | Raster | Time |
  |---|---:|
  | 100² | 0.22 s |
  | 200² | 1.67 s |
  | 400² | 13.3 s |
  | 492×562 | 32 s |

  4× the pixels takes ≈ 8× the time. A 3000×3400 Sentinel-2 AOI is therefore infeasible
  (≈ 2 h per call).
- `zonal_statistics._collect_zone_values` also runs point-in-polygon on every raster pixel for
  every zone, with no bbox pre-filter.
- Fix:
  - Compute the shape once per call and index the data directly.
  - In zonal statistics, loop only over the row/column window of each zone's bbox.
  - Optionally add a numpy fast path under `engine="auto"` for NDVI, band_math and reclassify.
    It must produce identical results.
- Add a benchmark test:
  - Doubling H and W must scale time by ≤ 5×.
  - A 1000×1000 NDVI must run in under 10 s in the pure-python path.

**007 (medium, crash)**: `_normalize_transform` rejects a complete `{a..f}` dict.
- Where: `plugins/raster_clip_mask.py`.
- Cause: `float(transform.get("e", -abs(float(transform.get("pixel_height")))))` evaluates the
  default eagerly, so `float(None)` raises even when `"e"` is present.
- Fix: branch explicitly on `"e" in transform`. Do the same for `a`, `c` and `f`, and add the
  missing-key error messages.

**008 (low–medium, packaging)**: the wheel installs generic top-level packages.
- `top_level.txt` lists `api`, `config`, `orchestrator`, `plugins` and `templates` next to
  `smart_spatial_system` and `s3geo`. These collide with any user project that has a local
  `config/` or `plugins/` package.
- Scope for 0.5.7: document the issue and add a test that imports plugins from a working
  directory containing a dummy `config/__init__.py`.
- If the move under `smart_spatial_system.*` with deprecated shim re-exports is small, do it.
  Otherwise open a tracking issue with a migration plan instead of doing it.

## Definition of done

- 7 new regression tests (001–007) fail on `main` and pass on the branch, plus the packaging
  test or issue for 008.
- The full suite is green, apart from pre-existing failures, which must be listed.
- On the branch, NDVI → reclassify → zonal on a 1000×1000 synthetic raster with 30 polygons
  finishes in under 60 s. Report the time.
- `CHANGELOG.md` has a 0.5.7 entry, the version is bumped in `pyproject.toml` (or wherever it
  is defined), and a PR is open.
- Your final message lists every behaviour change (002, 004, 005) that could change numbers for
  existing users.
