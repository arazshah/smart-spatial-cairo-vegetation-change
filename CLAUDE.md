# CLAUDE.md — smart-spatial-cairo-vegetation-change

Independent case-study project that **uses** `smart-spatial-system` (s3geo) as a
pinned, third-party dependency to answer one research question and write it up
as a short paper.

## Hard rule: never edit upstream

- `smart-spatial-system==0.3.0` is installed from PyPI and treated as read-only.
  **Never** modify, monkey-patch, vendor, fork or subclass-override anything in
  its installed modules (`plugins/`, `orchestrator/`, `s3geo/`, `config/`,
  `smart_spatial_system/`, `geochat_sdk/`, `geochat_kernel/`), including its
  YAML configs under `config/plugins/`.
- If a plugin misbehaves, **do not work around it silently.** Write a structured
  report in `bugs/NNN-short-slug.md` (template: `bugs/TEMPLATE.md`) with a
  minimal reproduction added to `scripts/verify_bugs.py`, and reference the bug
  ID in `paper/paper.md` where it affects the analysis.
- Allowed: choosing documented parameters (e.g. `all_touched=False`), choosing
  input sizes/resolution, and converting data *into* the documented input
  formats (dict with `data` + `metadata.transform` list). Any such choice made
  *because of* a bug must be stated in the paper and the bug report.

## Layout

```
CLAUDE.md            this file
requirements.txt     pinned deps (smart-spatial-system==0.3.0 + I/O libs)
data/README.md       provenance of every input (URLs, scene IDs, dates, licences)
data/raw/            downloaded clipped COGs + OSM boundaries (git-ignored)
data/processed/      plugin outputs (git-ignored except small tables)
scripts/             01_fetch_*.py → 02_*.py pipeline; verify_bugs.py
bugs/                one markdown file per upstream bug
paper/PLAN.md        research plan
paper/paper.md       the deliverable
paper/figures/       PNG maps/charts referenced from paper.md
```

## Conventions

- Pipeline scripts are numbered and idempotent; every number in `paper.md`
  must be regenerable from `scripts/`.
- All analysis steps named in `paper/PLAN.md` must call the s3geo plugin
  functions (`plugins.<id>.<capability>`); numpy/rasterio are for I/O,
  clipping/resampling and plotting only.
- Rasters are processed in UTM 36N (EPSG:32636) so pixel areas are metric.
