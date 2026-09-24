"""Sensitivity run (added after inspecting Fig. 2): the Nile channel shows a strong water-NDVI
drop between the dates (turbidity/algae, not vegetation). Districts that include river
surface (e.g. Waraq with its Nile islands) could therefore be ranked as "declining" because of
water. This re-computes the district mean dNDVI with water masked in either date, using only
s3geo plugins:

  band_math   where(min(b1, b2) < 0, None, b2 - b1)     (NDVI < 0 = water in either date)
  zonal_statistics  mean / valid_count per district (all_touched=False)

The pre-registered ranking (all pixels) stays the primary result; this is reported alongside.
"""
from __future__ import annotations

import csv
import json

import numpy as np
import rasterio

from plugins.band_math import calculate_band_math
from plugins.zonal_statistics import calculate_zonal_statistics

from common import PROC, WORK_CRS, dump, load

grid = load(PROC / "grid.json")
meta = {"transform": grid["transform"], "crs": WORK_CRS}


def lists(path):
    a = rasterio.open(path).read(1).astype(object)
    a[~np.isfinite(rasterio.open(path).read(1))] = None
    return a.tolist()


pair = {"data": [lists(PROC / "ndvi_early.tif"), lists(PROC / "ndvi_late.tif")], "metadata": meta}
land = calculate_band_math(raster=pair, expression="where(min(b1, b2) < 0, None, b2 - b1)", precision=4)
zones = json.loads((PROC / "districts_utm.geojson").read_text())
vo = calculate_zonal_statistics(raster=land, zones=zones, stats=["valid_count", "mean", "median"],
                                zone_id_field="district_id", all_touched=False,
                                include_zone_geometry=False, stat_prefix="land_", precision=4)
by_id = {f["properties"]["zone_id"]: f["properties"] for f in vo.features}

rows = list(csv.DictReader(open(PROC / "district_change_table.csv", encoding="utf-8")))
for r in rows:
    p = by_id[r["district_id"]]
    r["dndvi_mean_land"] = p["land_mean"]
    r["dndvi_median_land"] = p["land_median"]
    r["water_px_masked"] = int(r["valid_px"]) - (p["land_valid_count"] or 0)
rows_land = sorted(rows, key=lambda r: (r["dndvi_mean_land"] is None, r["dndvi_mean_land"] or 0))
for i, r in enumerate(rows_land, 1):
    r["rank_land"] = i
rows_veg = sorted(rows, key=lambda r: float(r["veg_frac_change_pp"]))
for i, r in enumerate(rows_veg, 1):
    r["rank_veg_share"] = i
with open(PROC / "district_change_table_sensitivity.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: int(r["rank_decline"])))

top = sorted(rows, key=lambda r: int(r["rank_decline"]))[:15]
md = ("| District | Rank: mean ΔNDVI (all px) | Rank: mean ΔNDVI (land only) | ΔNDVI land | "
      "Rank: Δ vegetated share | Δ vegetated share (pp) | Water px masked |\n"
      "|---|---:|---:|---:|---:|---:|---:|\n")
for r in sorted(rows, key=lambda r: min(int(r["rank_decline"]), r["rank_land"], r["rank_veg_share"]))[:15]:
    md += (f"| {r['name_en']} | {r['rank_decline']} | {r['rank_land']} | {float(r['dndvi_mean_land']):+.3f} | "
           f"{r['rank_veg_share']} | {float(r['veg_frac_change_pp']):+.1f} | {r['water_px_masked']} |\n")
(PROC / "table_sensitivity.md").write_text(md, encoding="utf-8")
dump({"land_nodata_pixels": sum(1 for row in land.data for v in row if v is None)}, PROC / "sensitivity_meta.json")
print(md)
