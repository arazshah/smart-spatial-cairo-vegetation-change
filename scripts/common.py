"""Shared constants and small I/O helpers (no analysis logic lives here)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# S3CASE_SYNTHETIC=1 routes every stage to data/synthetic/ - used to dry-run the
# pipeline on generated inputs (scripts/00_make_synthetic.py) without network.
SYNTHETIC = os.environ.get("S3CASE_SYNTHETIC") == "1"
_BASE = ROOT / "data" / ("synthetic" if SYNTHETIC else "")
RAW = _BASE / "raw"
PROC = _BASE / "processed"
FIG = (_BASE / "figures") if SYNTHETIC else ROOT / "paper" / "figures"
for _d in (RAW, PROC, FIG):
    _d.mkdir(parents=True, exist_ok=True)

# Area of interest (lon/lat, EPSG:4326) - Greater Cairo core, both Nile banks
AOI_BBOX = (31.10, 29.90, 31.40, 30.20)
WORK_CRS = "EPSG:32636"  # UTM 36N - metric pixels for area reporting

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
# Collection 1 is the ESA-reprocessed, radiometrically consistent archive (2015->);
# the older 'sentinel-2-l2a' collection is used as a fallback.
STAC_COLLECTIONS = ["sentinel-2-c1-l2a", "sentinel-2-l2a"]
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "smart-spatial-cairo-vegetation-change/0.1 (research case study)"

# Analysis grid resolution (m). Chosen because of bug 006 (O(H^2*W) runtime in the
# pure-python raster plugins) - see bugs/006-*.md and paper section 2.4.
ANALYSIS_RES_M = float(os.environ.get("S3CASE_RES_M", "60"))

# NDVI vegetation-health classes (upper bound inclusive, first match wins)
NDVI_CLASSES = [
    {"min": -1.0, "max": 0.0, "value": 0, "label": "water",            "inclusive_max": False},
    {"min": 0.0,  "max": 0.10, "value": 1, "label": "built_bare",      "inclusive_max": False},
    {"min": 0.10, "max": 0.20, "value": 2, "label": "sparse_veg",      "inclusive_max": False},
    {"min": 0.20, "max": 0.40, "value": 3, "label": "moderate_veg",    "inclusive_max": False},
    {"min": 0.40, "max": 1.0,  "value": 4, "label": "dense_veg"},
]
# dNDVI (late - early) change classes
DNDVI_CLASSES = [
    {"min": -2.0,  "max": -0.15, "value": 1, "label": "strong_decline", "inclusive_max": False},
    {"min": -0.15, "max": -0.05, "value": 2, "label": "decline",        "inclusive_max": False},
    {"min": -0.05, "max": 0.05,  "value": 3, "label": "stable"},
    {"min": 0.05,  "max": 0.15,  "value": 4, "label": "gain",           "inclusive_min": False, "inclusive_max": False},
    {"min": 0.15,  "max": 2.0,   "value": 5, "label": "strong_gain"},
]


def dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
