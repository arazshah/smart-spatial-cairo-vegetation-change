"""Independent numpy/rasterio re-computation of the district figures produced by the
s3geo plugins (verification only - never feeds the paper's numbers)."""
import csv
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import geometry_mask
from common import PROC, ANALYSIS_RES_M, dump

px_ha = ANALYSIS_RES_M ** 2 / 1e4
with rasterio.open(PROC / "refl_early.tif") as s:
    tf = s.transform
    re_, ne = s.read()
with rasterio.open(PROC / "refl_late.tif") as s:
    rl, nl = s.read()
ref_e = (ne - re_) / (ne + re_)
ref_l = (nl - rl) / (nl + rl)
ref_d = ref_l - ref_e
cls = np.full(ref_d.shape, 0)
cls[ref_d < -0.15] = 1
cls[(ref_d >= -0.15) & (ref_d < -0.05)] = 2
tab = {r["district_id"]: r for r in csv.DictReader(open(PROC / "district_change_table.csv", encoding="utf-8"))}
d = gpd.read_file(PROC / "districts_utm.geojson")
rows, worst = [], {"dndvi_mean": 0.0, "ndvi_early_mean": 0.0, "decline_px": 0}
for _, z in d.iterrows():
    m = ~geometry_mask([z.geometry], ref_d.shape, tf, all_touched=False)
    r = tab[z.district_id]
    e = {"district_id": z.district_id,
         "ndvi_early_mean": float(np.nanmean(ref_e[m])) if np.isfinite(ref_e[m]).any() else None,
         "dndvi_mean": float(np.nanmean(ref_d[m])) if np.isfinite(ref_d[m]).any() else None,
         "decline_px": int(((cls == 1) | (cls == 2))[m].sum())}
    got_px = round((float(r["strong_decline_ha"]) + float(r["decline_ha"])) / px_ha)
    for k in ("dndvi_mean", "ndvi_early_mean"):
        if e[k] is not None and r[k] not in ("", None):
            worst[k] = max(worst[k], abs(e[k] - float(r[k])))
    worst["decline_px"] = max(worst["decline_px"], abs(e["decline_px"] - got_px))
    rows.append(e)
dump({"max_abs_diff": worst, "districts": len(rows)}, PROC / "crosscheck.json")
print("max abs difference plugin vs reference:", worst)
