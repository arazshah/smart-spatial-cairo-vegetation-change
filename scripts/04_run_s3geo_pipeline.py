"""The analysis itself - every analytical step is an s3geo plugin capability.

  1. ndvi_calculator.calculate_ndvi          NDVI, both dates
  2. band_math.calculate_band_math           dNDVI = late - early; vegetation mask (NDVI >= 0.2)
  3. raster_reclassify.reclassify_raster     vegetation-health classes; dNDVI change classes
  4. zonal_statistics.calculate_zonal_statistics   per district, both dates + dNDVI
  5. raster_to_vector.raster_to_vector       changed pixels -> cell polygons
     centroid_extractor.extract_centroids    cell polygons -> centre points
     spatial_join.spatial_join_features      centre points within district
     attribute_statistics.calculate_attribute_statistics   change-class counts per district

Inputs are handed to the plugins in their documented in-memory form
({"data": nested lists, "metadata": {"transform": [a,b,c,d,e,f], ...}}), with
None as the nodata marker, because local_raster_loader output cannot be chained
into the analysis plugins (bug 001).
"""
from __future__ import annotations

import csv
import json
import time

import numpy as np
import geopandas as gpd
import rasterio

from plugins.attribute_statistics import calculate_attribute_statistics
from plugins.band_math import calculate_band_math
from plugins.centroid_extractor import extract_centroids
from plugins.local_raster_loader import load_local_raster
from plugins.ndvi_calculator import calculate_ndvi
from plugins.raster_reclassify import reclassify_raster
from plugins.raster_to_vector import raster_to_vector
from plugins.spatial_join import spatial_join_features
from plugins.zonal_statistics import calculate_zonal_statistics

from common import ANALYSIS_RES_M, DNDVI_CLASSES, NDVI_CLASSES, PROC, WORK_CRS, dump, load

LOG: list[dict] = []


def step(name, fn, **kw):
    t0 = time.time()
    out = fn(**kw)
    dt = time.time() - t0
    LOG.append({"step": name, "plugin_fn": f"{fn.__module__}.{fn.__name__}", "seconds": round(dt, 2)})
    print(f"  {name:<34} {dt:7.1f} s")
    return out


def to_lists(a: np.ndarray) -> list:
    """numpy -> nested python lists with None for NaN (plugins' nodata marker)."""
    obj = a.astype(object)
    obj[~np.isfinite(a.astype(float))] = None
    return obj.tolist()


def to_array(data) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in data], dtype="float32")


def write_tif(arr: np.ndarray, name: str, grid: dict, desc: str):
    with rasterio.open(PROC / name, "w", driver="GTiff", width=grid["width"], height=grid["height"],
                       count=1, dtype="float32", crs=WORK_CRS, transform=rasterio.Affine(*grid["transform"]),
                       nodata=np.nan, compress="deflate") as dst:
        dst.write(arr.astype("float32"), 1)
        dst.set_band_description(1, desc)


def main():
    grid = load(PROC / "grid.json")
    harm = load(PROC / "harmonisation.json")
    meta = {"transform": grid["transform"], "crs": WORK_CRS}
    zones = json.loads((PROC / "districts_utm.geojson").read_text())
    zone_props = {f["properties"]["district_id"]: f["properties"] for f in zones["features"]}

    rasters = {}
    for role in ("early", "late"):
        # loader used for validation/metadata only - its RasterOut carries no pixels (bug 001)
        ref = load_local_raster(str(PROC / f"refl_{role}.tif"))
        assert ref.metadata["crs"] == WORK_CRS and ref.metadata["band_count"] == 2
        with rasterio.open(PROC / f"refl_{role}.tif") as src:
            stack = src.read()
        rasters[role] = {"data": [to_lists(stack[0]), to_lists(stack[1])], "metadata": dict(meta)}

    print(f"grid {grid['width']}x{grid['height']} @ {grid['res_m']} m")
    ndvi, cls = {}, {}
    for role in ("early", "late"):
        ndvi[role] = step(f"ndvi[{role}]", calculate_ndvi, raster=rasters[role], red_band=1, nir_band=2,
                          precision=4, metadata={"date": harm[role]["date"]})
        cls[role] = step(f"reclassify ndvi[{role}]", reclassify_raster, raster=ndvi[role],
                         rules=NDVI_CLASSES, keep_unmatched=False, unmatched_value=None)
        write_tif(to_array(ndvi[role].data), f"ndvi_{role}.tif", grid, f"NDVI {harm[role]['date']}")
        write_tif(to_array(cls[role].data), f"ndvi_class_{role}.tif", grid, "vegetation class 0-4")

    pair = {"data": [ndvi["early"].data, ndvi["late"].data], "metadata": dict(meta)}
    dndvi = step("band_math dNDVI", calculate_band_math, raster=pair, expression="b2 - b1", precision=4)
    write_tif(to_array(dndvi.data), "dndvi.tif", grid, "dNDVI late-early")
    dcls = step("reclassify dNDVI", reclassify_raster, raster=dndvi, rules=DNDVI_CLASSES,
                keep_unmatched=False, unmatched_value=None)
    write_tif(to_array(dcls.data), "dndvi_class.tif", grid, "change class 1-5")

    vegmask = {}
    for role in ("early", "late"):
        vegmask[role] = step(f"band_math vegmask[{role}]", calculate_band_math,
                             raster={"data": ndvi[role].data, "metadata": dict(meta)},
                             expression="where(b1 >= 0.2, 1, 0)")

    # ---- zonal statistics per district (all_touched=False: see bug 002) -------------
    zonal_runs = {
        "ndvi_early": ndvi["early"], "ndvi_late": ndvi["late"], "dndvi": dndvi,
        "veg_early": vegmask["early"], "veg_late": vegmask["late"],
    }
    zonal = {}
    for key, ras in zonal_runs.items():
        vo = step(f"zonal[{key}]", calculate_zonal_statistics, raster=ras, zones=zones,
                  stats=["count", "valid_count", "mean", "median", "population_stdev"],
                  zone_id_field="district_id", all_touched=False, include_zone_geometry=False,
                  stat_prefix=f"{key}_", precision=4)
        zonal[key] = {f["properties"]["zone_id"]: f["properties"] for f in vo.features}
        dump({"metadata": vo.metadata, "features": vo.features}, PROC / f"zonal_{key}.json")

    # ---- changed pixels -> vectors -> district -> counts ------------------------------
    changed = [1, 2, 4, 5]  # everything except 'stable'
    cells = step("raster_to_vector changed", raster_to_vector, raster=dcls, include_values=changed,
                 mode="cells", include_pixel_properties=False, precision=1)
    # cell -> centre point, so a pixel belongs to the district containing its centre -
    # the same rule zonal_statistics uses with all_touched=False (areas stay consistent)
    points = step("centroid_extractor cells", extract_centroids, features=cells, precision=2)
    joined = step("spatial_join cells->district", spatial_join_features, source_features=points,
                  target_features=zones, predicate="within", join_type="inner", cardinality="first",
                  flatten_target_properties=True, include_target_properties=False,
                  target_property_prefix="d_")
    per_d = step("attribute_statistics by district", calculate_attribute_statistics, features=joined,
                 fields=["class_value"], group_by=["d_district_id", "class_value"], max_top_values=0)
    aoi_cls = step("attribute_statistics AOI classes", calculate_attribute_statistics,
                   features={"type": "FeatureCollection", "features": [
                       {"type": "Feature", "geometry": None, "properties": {"class_value": v}}
                       for row in dcls.data for v in row if v is not None]},
                   fields=["class_value"], group_by=["class_value"], max_top_values=0)
    dump({"per_district": [f["properties"] for f in per_d.features],
          "aoi": [f["properties"] for f in aoi_cls.features],
          "cells_meta": {k: v for k, v in cells["metadata"].items() if k in (
              "selected_pixel_count", "feature_count", "truncated", "transform_source")}},
         PROC / "change_class_counts.json")

    # ---- assemble the change table ----------------------------------------------------
    px_ha = ANALYSIS_RES_M ** 2 / 1e4
    label = {c["value"]: c["label"] for c in DNDVI_CLASSES}
    counts: dict[str, dict[str, int]] = {}
    for f in per_d.features:
        did, cv = f["properties"]["_group_value"]
        counts.setdefault(str(did), {})[label[int(cv)]] = f["properties"]["_count"]

    rows = []
    for did, p in zone_props.items():
        e, l, d = zonal["ndvi_early"][did], zonal["ndvi_late"][did], zonal["dndvi"][did]
        ve, vl = zonal["veg_early"][did], zonal["veg_late"][did]
        c = counts.get(did, {})
        valid = d["dndvi_valid_count"] or 0
        rows.append({
            "district_id": did, "name": p.get("name"), "name_en": p.get("name_en"),
            "area_km2": round(p.get("area_km2", 0), 2), "valid_px": valid,
            "ndvi_early_mean": e["ndvi_early_mean"], "ndvi_late_mean": l["ndvi_late_mean"],
            "dndvi_mean": d["dndvi_mean"], "dndvi_median": d["dndvi_median"],
            "veg_frac_early": ve["veg_early_mean"], "veg_frac_late": vl["veg_late_mean"],
            "veg_frac_change_pp": (round(100 * (vl["veg_late_mean"] - ve["veg_early_mean"]), 2)
                                   if ve["veg_early_mean"] is not None and vl["veg_late_mean"] is not None else None),
            "strong_decline_ha": round(c.get("strong_decline", 0) * px_ha, 1),
            "decline_ha": round(c.get("decline", 0) * px_ha, 1),
            "gain_ha": round(c.get("gain", 0) * px_ha, 1),
            "strong_gain_ha": round(c.get("strong_gain", 0) * px_ha, 1),
            "decline_share_pct": round(100 * (c.get("strong_decline", 0) + c.get("decline", 0)) / valid, 2) if valid else None,
        })
    rows.sort(key=lambda r: (r["dndvi_mean"] is None, r["dndvi_mean"] if r["dndvi_mean"] is not None else 0))
    for i, r in enumerate(rows, 1):
        r["rank_decline"] = i
    with open(PROC / "district_change_table.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "grid": grid, "harmonisation": harm, "timings": LOG,
        "ndvi_meta": {r: {k: ndvi[r].metadata.get(k) for k in (
            "output_mean_value", "valid_pixel_count", "nodata_pixel_count")} for r in ndvi},
        "class_counts": {r: cls[r].metadata["rule_match_counts"] for r in cls},
        "dndvi_class_counts": dcls.metadata["rule_match_counts"],
        "cells_vectorised": cells["metadata"]["feature_count"],
        "cells_joined": len(joined.features),
    }
    dump(summary, PROC / "run_summary.json")
    print("done ->", PROC / "district_change_table.csv")


if __name__ == "__main__":
    main()
