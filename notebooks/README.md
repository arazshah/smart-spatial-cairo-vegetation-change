# LLM-driven run: give s3geo the data and a question

`cairo_s3geo_llm.ipynb` asks s3geo 9 plain-language questions (in Persian by default). They
cover the whole case study: NDVI, per-district statistics, the ΔNDVI map, change classes,
decline polygons and the "which districts lost the most?" ranking.

For each question, `s3geo.query()` takes these steps:
1. The LLM writes the plan.
2. s3geo validates it, repairs it if needed, and executes it.
3. The notebook checks the answer against the paper's reference numbers.

## Run it (live, with the LLM)

```bash
pip install -r requirements.txt jupyter
export LLM_API_KEY=...                        # required
export LLM_BASE_URL=https://api.avalai.ir/v1  # optional; this is s3geo's default
export LLM_MODEL=gpt-4o-mini                  # optional; this is s3geo's default
jupyter lab notebooks/cairo_s3geo_llm.ipynb   # MODE switches to "live" automatically when a key is set
```

A live run writes the following:

| Path | Contents |
|---|---|
| `plans/Q*.json` | The LLM's accepted plan for each question, with every rejected or repaired attempt and the model name. This is the evidence of what the LLM did. |
| `results/llm_runs_live.csv` | One row per question: executed or not, number of attempts, operations, runtime. |
| `results/llm_checks_live.csv` | One row per check: pass or fail against the reference numbers. |
| `results/llm_summary_live.json` | The totals. |
| `results/llm_maps_live.png` | ΔNDVI map and district means, drawn only from s3geo's answers. |

Commit `plans/` and `results/` after a live run.

## Replay (no key)

```bash
S3GEO_MODE=replay jupyter nbconvert --to notebook --execute notebooks/cairo_s3geo_llm.ipynb
```

Replay re-executes the saved LLM plans through the same public s3geo pipeline. The plans are
still the LLM's, but no model is called.

## `reference_plans/`: expressibility check, not LLM output

These are hand-written plans. They exist only to show that every question can be expressed with
s3geo's operation catalog, and that a correct plan reproduces the paper.

```bash
S3GEO_MODE=replay S3GEO_PLANS_DIR=notebooks/reference_plans S3GEO_RESULTS_DIR=/tmp/ref \
  jupyter nbconvert --to notebook --execute notebooks/cairo_s3geo_llm.ipynb
```

Result on s3geo 0.5.7 (2026-09-24): 9/9 questions executed, 10/10 checks passed.

So if a live run fails a check, the cause is the plan the LLM produced or s3geo's
prompt/planner. It is not a missing operation.

## Edit the notebook

The notebook is generated. Edit `build_notebook.py`, then run `python notebooks/build_notebook.py`.
