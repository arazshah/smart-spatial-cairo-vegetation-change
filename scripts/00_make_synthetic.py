"""Generate synthetic stand-ins for the outputs of 01_fetch_sentinel2.py and
02_fetch_districts.py so the whole s3geo pipeline can be dry-run offline.

    S3CASE_SYNTHETIC=1 python scripts/00_make_synthetic.py
    S3CASE_SYNTHETIC=1 python scripts/03_prepare_inputs.py  ... etc.

Synthetic numbers are NEVER reported in the paper.
"""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import box

from common import AOI_BBOX, RAW, SYNTHETIC, WORK_CRS, dump

assert SYNTHETIC, "run with S3CASE_SYNTHETIC=1"
rng = np.random.default_rng(42)

l, b, r, t = transform_bounds("EPSG:4326", WORK_CRS, *AOI_BBOX)
l, t = np.floor(l / 10) * 10, np.ceil(t / 10) * 10
W, H = int(np.ceil((r - l) / 10)), int(np.ceil((t - b) / 10))
tf = from_origin(l, t, 10, 10)
yy, xx = np.mgrid[0:H, 0:W]

# vegetation "blobs" (fields/parks); some disappear in the late scene (urbanisation)
centers = rng.uniform([0, 0], [H, W], size=(60, 2))
radii = rng.uniform(60, 250, size=60)
lost = rng.random(60) < 0.35
veg_e = np.zeros((H, W), np.float32)
veg_l = np.zeros((H, W), np.float32)
for (cy, cx), rad, gone in zip(centers, radii, lost):
    m = np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * rad ** 2))).astype(np.float32)
    veg_e = np.maximum(veg_e, m)
    if not gone:
        veg_l = np.maximum(veg_l, m * 0.95)
river = (np.abs(xx - W * 0.45 - 0.1 * yy) < 40)


def bands(veg, offset_dn):
    red = 2200 - 1600 * veg + rng.normal(0, 60, veg.shape)
    nir = 2600 + 1800 * veg + rng.normal(0, 60, veg.shape)
    red[river], nir[river] = 400, 250
    return (np.clip(red, 1, None) + offset_dn).astype("uint16"), (np.clip(nir, 1, None) + offset_dn).astype("uint16")


scenes = {"collection": "SYNTHETIC", "aoi_bbox_wgs84": AOI_BBOX, "scenes": {}}
for role, date, veg, off, baseline in (("early", "2015-08-01", veg_e, 0, "02.00"),
                                       ("late", "2025-08-01", veg_l, 1000, "05.11")):
    rb, nb = bands(veg, off)
    entry = {"id": f"SYNTH_{date}", "datetime": date + "T08:40:00Z", "mgrs_tile": "36RUU",
             "s2:processing_baseline": baseline, "bands": {}}
    for band, arr in (("B04", rb), ("B08", nb)):
        p = RAW / f"s2_{date}_{band}.tif"
        with rasterio.open(p, "w", driver="GTiff", width=W, height=H, count=1, dtype="uint16",
                           crs=WORK_CRS, transform=tf, nodata=0, compress="deflate") as dst:
            dst.write(arr, 1)
        entry["bands"][band] = {"file": str(p), "scale": 0.0001, "offset": -0.1 if off else 0.0}
    scenes["scenes"][role] = entry
dump(scenes, RAW / "scenes.json")

# districts: irregular 6x6 grid of polygons in lon/lat
w, s, e, n = AOI_BBOX
xs, ys = np.linspace(w, e, 7), np.linspace(s, n, 7)
rows = []
for i in range(6):
    for j in range(6):
        g = box(xs[i], ys[j], xs[i + 1], ys[j + 1]).segmentize(0.0005)  # ~100 vertices, like real OSM rings
        rows.append({"osm_id": 1000 + i * 6 + j, "name": f"D{i}{j}", "name_en": f"District {i}{j}",
                     "admin_level": "8", "district_id": str(1000 + i * 6 + j), "geometry": g})
gpd.GeoDataFrame(rows, crs="EPSG:4326").to_file(RAW / "districts.geojson", driver="GeoJSON")
print("synthetic inputs written to", RAW)
