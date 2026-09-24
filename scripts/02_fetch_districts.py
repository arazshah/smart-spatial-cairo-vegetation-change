"""Fetch Greater-Cairo district (qism / hayy) boundaries from OSM Overpass.

Step 1 (--inspect): look up a few well-known districts by name and print the
admin_level OSM uses for them in Egypt (it varies by country).
Step 2: download every boundary=administrative relation at that admin_level
intersecting the AOI, build polygons, clip to AOI and save
data/raw/districts.geojson (EPSG:4326) + data/raw/districts_inspect.json.

    python scripts/02_fetch_districts.py --inspect
    python scripts/02_fetch_districts.py --level 8
"""
from __future__ import annotations

import argparse
import collections
import sys
import time

import geopandas as gpd
import requests
from shapely.geometry import LineString, box
from shapely.ops import linemerge, polygonize, unary_union

from common import AOI_BBOX, OVERPASS_URLS, RAW, USER_AGENT, dump

# Well-known Cairo / Giza districts (Arabic OSM names; English in name:en)
PROBES = ["مدينة نصر", "المعادي", "مصر الجديدة", "الزمالك", "حلوان", "شبرا", "الدقي", "العجوزة", "إمبابة"]


def overpass(q: str) -> dict:
    errors = []
    for url in OVERPASS_URLS:
        for attempt in range(3):
            try:
                r = requests.post(url, data={"data": q}, headers={"User-Agent": USER_AGENT}, timeout=240)
            except requests.RequestException as e:
                errors.append(f"{url}: {type(e).__name__}")
                break
            if r.status_code in (429, 504):
                time.sleep(20 * (attempt + 1))
                continue
            if r.ok:
                print(f"  (overpass endpoint: {url})")
                return r.json()
            errors.append(f"{url}: HTTP {r.status_code}")
            break
    raise RuntimeError("all Overpass endpoints failed: " + "; ".join(errors))


def bbox_ql() -> str:
    w, s, e, n = AOI_BBOX
    return f"{s},{w},{n},{e}"


def inspect() -> dict:
    names = "|".join(PROBES)
    q = f'[out:json][timeout:120];relation["boundary"="administrative"]["name"~"^({names})"]({bbox_ql()});out tags;'
    rels = overpass(q)["elements"]
    rows = [{"id": r["id"], "admin_level": r["tags"].get("admin_level"), "name": r["tags"].get("name"),
             "name:en": r["tags"].get("name:en")} for r in rels]
    counts = collections.Counter(r["admin_level"] for r in rows)
    q2 = f'[out:json][timeout:120];relation["boundary"="administrative"]({bbox_ql()});out tags;'
    allrels = overpass(q2)["elements"]
    per_level = collections.Counter(r["tags"].get("admin_level") for r in allrels)
    out = {"probe_matches": rows, "probe_admin_levels": dict(counts), "all_levels_in_aoi": dict(per_level)}
    dump(out, RAW / "districts_inspect.json")
    for r in rows:
        print(f"  level {r['admin_level']:>3}  {r['name']}  ({r['name:en']})  rel {r['id']}")
    print("probe levels:", dict(counts), "| all levels in AOI:", dict(per_level))
    return out


def relation_polygon(rel: dict):
    outers, inners = [], []
    for m in rel.get("members", []):
        if m.get("type") != "way" or "geometry" not in m:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
        (inners if m.get("role") == "inner" else outers).append(line)
    if not outers:
        return None
    outer = unary_union(list(polygonize(linemerge(outers))))
    if inners:
        outer = outer.difference(unary_union(list(polygonize(linemerge(inners)))))
    return outer if not outer.is_empty else None


def fetch(level: str) -> gpd.GeoDataFrame:
    q = f'[out:json][timeout:240];relation["boundary"="administrative"]["admin_level"="{level}"]({bbox_ql()});out geom;'
    rels = overpass(q)["elements"]
    rows = []
    for r in rels:
        geom = relation_polygon(r)
        if geom is None:
            print("  skip (no closed rings):", r["id"], r["tags"].get("name"))
            continue
        t = r["tags"]
        rows.append({"osm_id": r["id"], "name": t.get("name"), "name_en": t.get("name:en") or t.get("name"),
                     "admin_level": t.get("admin_level"), "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    aoi = box(*AOI_BBOX)
    gdf["aoi_share"] = gdf.geometry.intersection(aoi).area / gdf.geometry.area
    gdf = gdf[gdf["aoi_share"] >= 0.5].copy()  # keep districts mostly inside the AOI
    gdf["geometry"] = gdf.geometry.intersection(aoi)
    gdf = gdf.explode(index_parts=False).dissolve(by="osm_id", as_index=False, aggfunc="first")
    gdf["district_id"] = gdf["osm_id"].astype(str)
    return gdf.sort_values("name_en").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--level", default=None, help="admin_level to download (see --inspect)")
    a = ap.parse_args()
    if a.inspect or not a.level:
        info = inspect()
        if not a.level:
            if not info["probe_admin_levels"]:
                print("no probe matched; pass --level explicitly", file=sys.stderr)
                return 1
            a.level = max(info["probe_admin_levels"], key=info["probe_admin_levels"].get)
            print("using most common probe level:", a.level)
    gdf = fetch(a.level)
    out = RAW / "districts.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"wrote {len(gdf)} districts (admin_level={a.level}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
