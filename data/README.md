# Data

All inputs are fetched by scripts; nothing is hand-edited. `raw/` and `processed/` are
git-ignored (regenerate with the commands below); small result tables are copied into
`paper/` when the paper is written.

| File | Produced by | Source | Licence |
|---|---|---|---|
| `raw/s2_<date>_B04.tif`, `raw/s2_<date>_B08.tif` | `scripts/01_fetch_sentinel2.py` | Sentinel-2 L2A COGs on AWS (`sentinel-cogs`), found via Earth Search STAC `https://earth-search.aws.element84.com/v1/search`; collection `sentinel-2-c1-l2a` (fallback `sentinel-2-l2a`) | Copernicus Sentinel data, free & open (Copernicus licence) |
| `raw/scenes.json` | same | STAC item IDs, datetimes, MGRS tile, cloud cover, processing baseline, asset hrefs, per-band `scale`/`offset` | — |
| `raw/districts_inspect.json`, `raw/osm_boundary_survey_raw.json` | `scripts/02_fetch_districts.py --inspect` | OpenStreetMap via Overpass (`overpass-api.de`, mirror `overpass.kumi.systems`); used to check whether OSM has qism relations | © OpenStreetMap contributors, ODbL 1.0 |
| `raw/districts.geojson`, `raw/geoBoundaries-EGY-ADM2*.json` | `scripts/02_fetch_districts.py --source geoboundaries` | geoBoundaries gbOpen EGY ADM2 (CAPMAS / OCHA ROMENA, 2020) | CC BY 3.0 IGO |
| `processed/*` | `scripts/03`–`06` | derived | — |
| `synthetic/*` | `scripts/00_make_synthetic.py` | generated test data for offline dry-runs; **never reported** | — |

## Selection rules (recorded, not tuned after seeing results)

- **AOI**: lon 31.10–31.40 E, lat 29.90–30.20 N (Greater Cairo core, both Nile banks).
- **Season**: 1 June – 30 September (dry season, no rain; vegetation is irrigation-driven, which
  keeps the two dates phenologically comparable).
- **Years**: early = first of 2015, 2016, 2017 with a usable scene; late = 2025, else 2024.
  *Outcome (2026-09-24):* Earth Search has **no L2A over Cairo before 2017** (`sentinel-2-c1-l2a`
  starts in 2018 here; `sentinel-2-l2a` has nothing in 2015–2016), so the pair is
  **S2B_36RUU_20170827_0_L2A** (cloud 0.17 %) and **S2A_36RUU_20250901_0_L2A** (cloud 0.001 %), an
  8-year interval. Both are from `sentinel-2-l2a`, tile 36RUU, and dated 5 days apart in the
  calendar. The 2025 scene carries offset −0.1 (baseline 05.11); the 2017 scene has offset 0.
- **Scene**: `eo:cloud_cover < 5 %`, item bbox covers the whole AOI, AOI nodata < 1 % (checked
  on a decimated read), ranked by cloud cover then nodata; the late scene must be on the **same
  MGRS tile** as the early one so both share one pixel grid.
- **Bands**: B04 (red, 10 m) and B08 (NIR, 10 m). Only an AOI window of each COG is read over
  HTTPS via GDAL `/vsicurl/`; no credentials needed.
- **Radiometry**: DN → reflectance with each asset's `raster:bands` `scale`/`offset`. Scenes with
  processing baseline ≥ 04.00 (from 25 Jan 2022) carry `BOA_ADD_OFFSET = -1000`; without the
  offset, late-date NDVI would be biased low and fake a decline.
- **Districts**: the `admin_level` is not assumed. `02_fetch_districts.py --inspect` first looks
  up known district names (مدينة نصر Nasr City, المعادي Maadi, مصر الجديدة Heliopolis,
  الزمالك Zamalek, حلوان Helwan, شبرا Shubra, الدقي Dokki, العجوزة Agouza, إمبابة Imbaba) and
  reports which `admin_level` they carry; that level is then downloaded. Districts with ≥ 50 % of
  their area inside the AOI are kept and clipped to it (Cairo and Giza governorates both appear,
  since the Nile splits the city).

## Reproduce

```bash
pip install -r requirements.txt
python scripts/01_fetch_sentinel2.py
python scripts/02_fetch_districts.py --inspect      # read the level, then:
python scripts/02_fetch_districts.py --source geoboundaries   # OSM has no qism level for Cairo
python scripts/03_prepare_inputs.py
python scripts/04_run_s3geo_pipeline.py
python scripts/05_figures_tables.py
python scripts/06_crosscheck.py
python scripts/verify_bugs.py
```

## Status (2026-09-24)

- **Sentinel-2:** downloaded. The 2025 item has `earthsearch:boa_offset_applied=true`, so its
  advertised `offset=-0.1` is **not** applied again (see `scripts/03_prepare_inputs.py`).
- **OSM:** `overpass-api.de` rejects the cloud egress with 406; the `overpass.kumi.systems`
  mirror works. The inspection found only `admin_level` 2 and 4 in the AOI and no qism/hayy
  relations. The survey is saved in `raw/districts_inspect.json` and
  `raw/osm_boundary_survey_raw.json`.
- **Districts:** taken from **geoBoundaries gbOpen EGY ADM2** (CAPMAS via OCHA/HDX, 2020,
  CC BY 3.0 IGO): `02_fetch_districts.py --source geoboundaries`. 48 units have ≥ 50 % of their
  area inside the AOI.
