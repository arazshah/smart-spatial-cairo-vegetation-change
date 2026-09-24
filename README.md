# smart-spatial-cairo-vegetation-change

Case study: **ten-year NDVI change across Greater Cairo districts (≈2015 → ≈2025)**, computed with the
[`smart-spatial-system`](https://pypi.org/project/smart-spatial-system/) (s3geo) plugins, pinned at `0.5.7`.

- Research question, method, status → [`paper/PLAN.md`](paper/PLAN.md)
- Paper (draft) → [`paper/paper.md`](paper/paper.md)
- Data provenance → [`data/README.md`](data/README.md)
- Upstream bugs found (never patched here) → [`bugs/`](bugs/)
- Project rules → [`CLAUDE.md`](CLAUDE.md)

```bash
pip install -r requirements.txt
python scripts/verify_bugs.py                              # reproduce upstream bugs
S3CASE_SYNTHETIC=1 python scripts/00_make_synthetic.py      # offline dry-run inputs
S3CASE_SYNTHETIC=1 python scripts/03_prepare_inputs.py && S3CASE_SYNTHETIC=1 python scripts/04_run_s3geo_pipeline.py
```
