"""Find two low-cloud, dry-season Sentinel-2 L2A scenes over Cairo ~10 years apart
(AWS Earth Search STAC, no login) and download B04/B08 clipped to the AOI.

Only a window of each public COG is read over HTTPS (GDAL /vsicurl/), so full
tiles are never downloaded. Output: data/raw/s2_<date>_{B04,B08}.tif (native
10 m, UTM 36N, uint16 DN) + data/raw/scenes.json (full provenance incl. offsets).

    python scripts/01_fetch_sentinel2.py [--early 2015,2016] [--late 2025,2024] [--max-cloud 5]
"""
from __future__ import annotations

import argparse
import sys

import rasterio
import requests
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from common import AOI_BBOX, RAW, STAC_COLLECTIONS, STAC_URL, USER_AGENT, dump

DRY_SEASON = ("06-01", "09-30")  # Cairo summer: no rain, stable crop/park irrigation regime
BAND_KEYS = {"B04": ("red", "B04"), "B08": ("nir", "B08")}


def search(collection: str, year: int, max_cloud: float) -> list[dict]:
    body = {
        "collections": [collection],
        "bbox": list(AOI_BBOX),
        "datetime": f"{year}-{DRY_SEASON[0]}T00:00:00Z/{year}-{DRY_SEASON[1]}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "limit": 200,
    }
    r = requests.post(STAC_URL, json=body, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    return r.json().get("features", [])


def mgrs(item: dict) -> str | None:
    p = item["properties"]
    return p.get("grid:code") or p.get("s2:mgrs_tile") or (
        f"{p.get('mgrs:utm_zone')}{p.get('mgrs:latitude_band')}{p.get('mgrs:grid_square')}"
        if p.get("mgrs:utm_zone") else None)


def aoi_cover(item: dict) -> float:
    """Fraction of AOI bbox covered by the item bbox (coarse, pre-download)."""
    a = AOI_BBOX
    b = item.get("bbox") or [0, 0, 0, 0]
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / ((a[2] - a[0]) * (a[3] - a[1]))


def asset(item: dict, band: str) -> dict:
    for key in BAND_KEYS[band]:
        if key in item["assets"]:
            return item["assets"][key]
    raise KeyError(f"{item['id']}: no asset for {band}; have {sorted(item['assets'])}")


def ranked(items: list[dict], tile: str | None) -> list[dict]:
    cands = [i for i in items if (tile is None or mgrs(i) == tile) and aoi_cover(i) > 0.99]
    cands.sort(key=lambda i: (i["properties"].get("eo:cloud_cover", 100),
                              i["properties"].get("s2:nodata_pixel_percentage", 100)))
    return cands


def aoi_nodata_fraction(item: dict) -> float:
    """Read a decimated overview of B04 over the AOI; fraction of 0 (=nodata) pixels."""
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(asset(item, "B04")["href"]) as src:
            l, b, r, t = transform_bounds("EPSG:4326", src.crs, *AOI_BBOX, densify_pts=21)
            win = from_bounds(l, b, r, t, src.transform)
            arr = src.read(1, window=win, boundless=True, fill_value=0, out_shape=(200, 200))
    return float((arr == 0).mean())


def pick(items: list[dict], tile: str | None) -> dict | None:
    for it in ranked(items, tile)[:8]:
        frac = aoi_nodata_fraction(it)
        print(f"    {it['id']} cloud={it['properties'].get('eo:cloud_cover')} aoi_nodata={frac:.3f}")
        if frac < 0.01:
            return it
    return None


def clip_band(href: str, out_path) -> dict:
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(href) as src:
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *AOI_BBOX, densify_pts=21)
            win = from_bounds(left, bottom, right, top, src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win, boundless=True, fill_value=0)
            prof = src.profile.copy()
            prof.update(driver="GTiff", width=data.shape[1], height=data.shape[0],
                        transform=src.window_transform(win), compress="deflate", tiled=True,
                        blockxsize=256, blockysize=256, nodata=0)
            with rasterio.open(out_path, "w", **prof) as dst:
                dst.write(data, 1)
            return {"crs": src.crs.to_string(), "shape": list(data.shape), "res": list(src.res)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--early", default="2015,2016,2017")
    ap.add_argument("--late", default="2025,2024")
    ap.add_argument("--max-cloud", type=float, default=5.0)
    a = ap.parse_args()

    chosen: dict[str, dict] = {}
    for collection in STAC_COLLECTIONS:
        try:
            early_items = [(y, search(collection, int(y), a.max_cloud)) for y in a.early.split(",")]
        except requests.HTTPError as e:
            print(f"{collection}: {e}", file=sys.stderr)
            continue
        for y, items in early_items:
            print(f"{collection} {y}: {len(items)} candidate scenes")
            e = pick(items, None)
            if not e:
                continue
            tile = mgrs(e)
            for ly in a.late.split(","):
                late_items = search(collection, int(ly), a.max_cloud)
                print(f"{collection} {ly}: {len(late_items)} candidate scenes (tile {tile})")
                l = pick(late_items, tile)  # same MGRS tile -> identical pixel grid
                if l:
                    chosen = {"early": e, "late": l, "collection": collection}
                    break
            if chosen:
                break
        if chosen:
            break
    if not chosen:
        print("No suitable scene pair found - relax --max-cloud or years.", file=sys.stderr)
        return 1

    record = {"collection": chosen["collection"], "aoi_bbox_wgs84": AOI_BBOX, "scenes": {}}
    for role in ("early", "late"):
        it = chosen[role]
        p = it["properties"]
        date = p["datetime"][:10]
        entry = {
            "id": it["id"], "datetime": p["datetime"], "mgrs_tile": mgrs(it),
            "eo:cloud_cover": p.get("eo:cloud_cover"),
            "s2:processing_baseline": p.get("s2:processing_baseline"),
            # True = Element84 already removed BOA_ADD_OFFSET from the DNs (see 03_prepare_inputs)
            "earthsearch:boa_offset_applied": p.get("earthsearch:boa_offset_applied"),
            "platform": p.get("platform"), "stac_self": next(
                (l["href"] for l in it.get("links", []) if l.get("rel") == "self"), None),
            "bands": {},
        }
        for band in ("B04", "B08"):
            ast = asset(it, band)
            out = RAW / f"s2_{date}_{band}.tif"
            print(f"  {role} {date} {band} <- {ast['href']}")
            info = clip_band(ast["href"], out)
            rb = (ast.get("raster:bands") or [{}])[0]
            entry["bands"][band] = {"href": ast["href"], "file": str(out.relative_to(RAW.parents[1])),
                                    "scale": rb.get("scale"), "offset": rb.get("offset"), **info}
        record["scenes"][role] = entry
    dump(record, RAW / "scenes.json")
    print("wrote", RAW / "scenes.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
