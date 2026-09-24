# 008 — wheel installs generic top-level packages (`config`, `plugins`, `api`, `templates`, `orchestrator`)

| Field | Value |
|---|---|
| Package | smart-spatial-system 0.3.0 – 0.5.6 |
| Component | packaging (`top_level.txt`) |
| Severity | low–medium |
| Kind | packaging |
| Found while | Phase 0 — installing the pinned dependency |
| Repro | `cat $(python -c "import site;print(site.getsitepackages()[0])")/smart_spatial_system-0.5.6.dist-info/top_level.txt` |
| Verified | 2026-09-24: reproduces on 0.3.0 and 0.5.6; the plugin source is byte-identical between them |
| Status | **Open** in 0.5.7 (top_level.txt unchanged) — checked 2026-09-24 with `scripts/verify_bugs.py` |

## Summary
Besides `smart_spatial_system` and `s3geo`, the wheel installs `api`, `config`, `orchestrator`,
`plugins` and `templates` directly into `site-packages`. Any user project (or other dependency)
with a local `config/`, `plugins/` or `api/` package will shadow or be shadowed by them depending
on `sys.path` order — e.g. running a script from a repo that has a `config/__init__.py` breaks
every plugin's `from plugins._shared.plugin_config import ...` / YAML config lookup.

## Expected
Everything namespaced under `smart_spatial_system.*` (the `smart_spatial_system/plugins/` and
`.../interfaces/api/` stubs suggest this migration is under way).

## Impact on this case study
The repo deliberately has no top-level `config/`, `plugins/` or `api/` directories, and scripts
live in `scripts/` (which is what lands on `sys.path[0]`).

## Suggested fix (not applied here)
Finish the move under `smart_spatial_system.` and keep thin deprecated re-export shims.
