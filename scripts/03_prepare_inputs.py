"""Radiometric harmonisation + regridding (I/O only, no index maths).

* DN -> surface reflectance with each asset's own scale/offset
  (processing baseline >= 04.00 carries BOA_ADD_OFFSET = -1000 DN; ignoring it
  would bias the late NDVI low and fake a "decline").
* Both dates resampled (area-average) onto one common UTM 36N grid at
  ANALYSIS_RES_M so pixels line up 1:1 between dates.
* Districts reprojected to UTM 36N (the raster plugins do no CRS handling) and
  lightly simplified (5 m tolerance) to bound polygon vertex counts.

Outputs (data/processed/): refl_<role>.tif (2 bands: red, nir; float32, NaN nodata),
grid.json, districts_utm.geojson
"""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds

from common import AOI_BBOX, ANALYSIS_RES_M, PROC, RAW, ROOT, WORK_CRS, dump, load

scenes = load(RAW / "scenes.json")
res = ANALYSIS_RES_M

l, b, r, t = transform_bounds("EPSG:4326", WORK_CRS, *AOI_BBOX, densify_pts=21)
l, b = np.floor(l / res) * res, np.floor(b / res) * res
r, t = np.ceil(r / res) * res, np.ceil(t / res) * res
W, H = int(round((r - l) / res)), int(round((t - b) / res))
dst_tf = from_origin(l, t, res, res)
grid = {"crs": WORK_CRS, "res_m": res, "width": W, "height": H, "transform": list(dst_tf)[:6]}
dump(grid, PROC / "grid.json")
print(f"analysis grid {W}x{H} @ {res} m ({W * H:,} px)")


def band_path(entry):
    p = entry["file"]
    return p if p.startswith("/") else str(ROOT / p)


def reflectance(entry, baseline, offset_already_applied):
    scale = entry.get("scale")
    offset = entry.get("offset")
    if scale is None:
        scale = 1e-4
    if offset_already_applied:
        # Earth Search 'sentinel-2-l2a' items with earthsearch:boa_offset_applied=True have DNs
        # already shifted back to the pre-04.00 convention, yet raster:bands still advertises
        # offset=-0.1. Applying it again double-corrects: 16 % of 2025 B04 pixels have DN < 1000,
        # impossible for un-shifted baseline>=04.00 data. Verified 2026-09-24.
        offset = 0.0
    elif offset is None:  # asset metadata missing -> derive from processing baseline
        offset = -0.1 if baseline and float(baseline) >= 4.0 else 0.0
    with rasterio.open(band_path(entry)) as src:
        dn = src.read(1).astype("float32")
        src_tf, src_crs = src.transform, src.crs
    refl = dn * scale + offset
    refl[dn == 0] = np.nan  # 0 = nodata in S2 L2A
    out = np.full((H, W), np.nan, dtype="float32")
    reproject(refl, out, src_transform=src_tf, src_crs=src_crs, dst_transform=dst_tf, dst_crs=WORK_CRS,
              resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
    return out, scale, offset


harmonisation = {}
for role, sc in scenes["scenes"].items():
    baseline = sc.get("s2:processing_baseline")
    applied = sc.get("earthsearch:boa_offset_applied")
    red, s_r, o_r = reflectance(sc["bands"]["B04"], baseline, applied)
    nir, s_n, o_n = reflectance(sc["bands"]["B08"], baseline, applied)
    harmonisation[role] = {"date": sc["datetime"][:10], "baseline": baseline, "boa_offset_applied": applied,
                           "B04": {"scale": s_r, "offset": o_r}, "B08": {"scale": s_n, "offset": o_n},
                           "valid_fraction": float(np.isfinite(red + nir).mean())}
    with rasterio.open(PROC / f"refl_{role}.tif", "w", driver="GTiff", width=W, height=H, count=2,
                       dtype="float32", crs=WORK_CRS, transform=dst_tf, nodata=np.nan,
                       compress="deflate") as dst:
        dst.write(np.stack([red, nir]))
        dst.set_band_description(1, "red_B04_reflectance")
        dst.set_band_description(2, "nir_B08_reflectance")
    print(role, harmonisation[role])
dump(harmonisation, PROC / "harmonisation.json")

d = gpd.read_file(RAW / "districts.geojson").to_crs(WORK_CRS)
n0 = int(d.geometry.apply(lambda g: len(g.exterior.coords) if g.geom_type == "Polygon"
                          else sum(len(p.exterior.coords) for p in g.geoms)).sum())
d["geometry"] = d.geometry.simplify(5.0, preserve_topology=True)
n1 = int(d.geometry.apply(lambda g: len(g.exterior.coords) if g.geom_type == "Polygon"
                          else sum(len(p.exterior.coords) for p in g.geoms)).sum())
d["area_km2"] = d.geometry.area / 1e6
d.to_file(PROC / "districts_utm.geojson", driver="GeoJSON")
print(f"{len(d)} districts, exterior vertices {n0} -> {n1} after 5 m simplification")
