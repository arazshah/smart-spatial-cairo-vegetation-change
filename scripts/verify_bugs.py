"""Minimal, self-contained reproductions for smart-spatial-system bugs found in 0.3.0/0.5.6 (all but 008 fixed in 0.5.7; PASS = fixed).
Each check prints PASS (behaves as expected) or BUG (reproduces). No upstream code is modified."""
import json, tempfile, time, os, random
import numpy as np, rasterio
from rasterio.transform import from_origin

from plugins.local_raster_loader import load_local_raster
from plugins.ndvi_calculator import calculate_ndvi
from plugins.raster_reclassify import reclassify_raster
from plugins.zonal_statistics import calculate_zonal_statistics
from plugins.raster_to_vector import raster_to_vector

def report(name, ok, detail):
    print(f"[{'PASS' if ok else 'BUG '}] {name}: {detail}")

# B1 loader -> ndvi
tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "two_band.tif")
with rasterio.open(p, "w", driver="GTiff", width=4, height=4, count=2, dtype="uint16",
                   crs="EPSG:32636", transform=from_origin(300000, 3330000, 10, 10)) as dst:
    dst.write(np.full((2, 4, 4), 1000, dtype="uint16"))
r = load_local_raster(p)
try:
    calculate_ndvi(r, red_band=1, nir_band=2)
    report("B1 loader->ndvi", True, "chained OK")
except Exception as e:
    report("B1 loader->ndvi", False, f"{type(e).__name__}: {e}  (loader returns {type(r).__name__} with attrs {sorted(vars(r))})")

# B2 zonal all_touched uses zone bbox, not geometry
# 10x10 raster of 1s, unit pixels, origin (0,10). Zone = right triangle covering lower-left half.
ras = {"data": [[1.0]*10 for _ in range(10)], "metadata": {"transform": [1, 0, 0, 0, -1, 10]}}
tri = {"type": "Feature", "properties": {"id": "tri"},
       "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [0, 10], [0, 0]]]}}
c_center = calculate_zonal_statistics(ras, [tri], stats=["count"], all_touched=False).features[0]["properties"]["zonal_count"]
c_touch = calculate_zonal_statistics(ras, [tri], stats=["count"], all_touched=True).features[0]["properties"]["zonal_count"]
# geometrically, pixels touching the triangle = 55 + 10 boundary-diagonal cells = at most 65, never 100
report("B2 zonal all_touched", c_touch < 100,
       f"center-mode count={c_center}, all_touched count={c_touch} (100 = every pixel of the zone's bounding box)")

# B3 raster_to_vector components merge adjacent different classes
cls = {"data": [[1, 1, 2, 2], [1, 1, 2, 2]], "metadata": {"transform": [1, 0, 0, 0, -1, 2]}}
fc = raster_to_vector(cls, include_values=[1, 2], mode="components", connectivity=4)
vals = [(f["properties"]["value"], f["properties"]["pixel_count"]) for f in fc["features"]]
report("B3 r2v components mix classes", len(fc["features"]) == 2,
       f"{len(fc['features'])} component(s) (value, pixel_count)={vals}; expected 2 (class 1 x4, class 2 x4)")

# B4 raster_to_vector ignores dict transform (accepted by zonal_statistics / clip) -> silent pixel coords
dict_tf = {"a": 10, "b": 0, "c": 300000, "d": 0, "e": -10, "f": 3330000}
fc = raster_to_vector({"data": [[1]], "metadata": {"transform": dict_tf}}, include_values=[1])
ring = fc["features"][0]["geometry"]["coordinates"][0]
report("B4 r2v dict transform", abs(ring[0][0] - 300000) < 1,
       f"first vertex={ring[0]}, transform_source={fc['metadata']['transform_source']} (expected ~[300000, 3330000])")
unit_sq = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[300000, 3329990], [300010, 3329990], [300010, 3330000], [300000, 3330000], [300000, 3329990]]]}}

# B7 shared _normalize_transform rejects a complete a..f dict (eager default evaluation of pixel_height)
try:
    zs = calculate_zonal_statistics({"data": [[5.0]], "metadata": {"transform": dict_tf}}, [unit_sq], stats=["count"])
    report("B7 dict transform a..f", True, f"count={zs.features[0]['properties']['zonal_count']}")
except Exception as e:
    cause = e.__cause__
    report("B7 dict transform a..f", False, f"{type(e).__name__}: {e} <- {type(cause).__name__}: {cause}")
zs = calculate_zonal_statistics({"data": [[5.0]], "metadata": {"transform": {**dict_tf, "pixel_height": 10}}}, [unit_sq], stats=["count"])
print("      (adding a redundant pixel_height key makes it work: count =", zs.features[0]["properties"]["zonal_count"], ")")

# B5 reclassify output metadata keeps INPUT nodata, not output_nodata
ras = {"data": [[-9999.0, 0.5], [0.1, 0.9]], "metadata": {"nodata": -9999.0, "transform": [1, 0, 0, 0, -1, 2]}}
rc = reclassify_raster(ras, rules=[{"min": -1, "max": 1, "value": 1}], output_nodata=0)
zs = calculate_zonal_statistics(rc, [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}], stats=["valid_count", "mean"])
pr = zs.features[0]["properties"]
report("B5 reclassify nodata metadata", rc.metadata["nodata"] == 0,
       f"output data={rc.data}, metadata.nodata={rc.metadata['nodata']}, output_nodata={rc.metadata['output_nodata']}; "
       f"downstream zonal valid_count={pr['zonal_valid_count']} mean={pr['zonal_mean']} (expected 3 and 1.0)")

# B6 per-pixel _array_shape() -> O(H^2 W) runtime
times = {}
for n in (100, 200, 400):
    d = [[[random.randint(1, 3000) for _ in range(n)] for _ in range(n)] for _ in range(2)]
    t = time.time(); calculate_ndvi({"data": d, "metadata": {}}); times[n] = time.time() - t
ratio = times[400] / times[200]
report("B6 quadratic-per-row runtime", ratio < 5,
       f"ndvi times {{n: s}} = { {k: round(v, 2) for k, v in times.items()} }; 4x pixels -> x{ratio:.1f} time (linear would be ~x4)")
