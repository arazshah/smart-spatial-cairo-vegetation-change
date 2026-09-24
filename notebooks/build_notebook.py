"""Builds cairo_s3geo_llm.ipynb (run: python notebooks/build_notebook.py)."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []


def md(s):
    C.append(nbf.v4.new_markdown_cell(s.strip()))


def code(s):
    C.append(nbf.v4.new_code_cell(s.strip()))


md(r"""
# Cairo vegetation change 2017→2025, asked in plain language to s3geo

The scripted pipeline (`scripts/04_run_s3geo_pipeline.py`) calls s3geo plugins one by one. This
notebook tests s3geo's real promise instead: **you give it data and a question, and it does the
rest**.

For every question:

1. `s3geo.query(question, layers=...)` sends the question to an LLM, which writes a plan
   (QuerySpec).
2. s3geo validates the plan (and asks the LLM to repair it if needed), turns it into a DAG and
   executes it with its plugins.
3. The notebook compares the result, cell by cell, with the reference numbers from the scripted
   pipeline that the paper is based on.

**Modes**

| `MODE` | What happens | Needs |
|---|---|---|
| `live` | The LLM writes every plan. Plans and all repair attempts are saved to `notebooks/plans/`. | `LLM_API_KEY` (+ optional `LLM_BASE_URL`, `LLM_MODEL`) |
| `replay` | The plans saved by the last live run are executed again. No key needed, and the results are bit-for-bit reproducible. | `notebooks/plans/*.json` |

Questions are asked in **Persian** by default, the language s3geo is built for. Set
`LANG = "en"` to ask the same questions in English.
""")

code(r"""
import os, sys, json, time, subprocess
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd, rasterio
import matplotlib.pyplot as plt

ROOT = Path.cwd().resolve()
if ROOT.name == "notebooks":
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "notebooks"))
import s3geo
from importlib.metadata import version
import s3geo_llm as L

LANG = os.getenv("S3GEO_LANG", "fa")            # "fa" or "en"
cfg = L.llm_config()
MODE = os.getenv("S3GEO_MODE") or ("live" if cfg["api_key_set"] else "replay")
print("smart-spatial-system", version("smart-spatial-system"))
print("MODE =", MODE, "| LANG =", LANG, "| LLM:", {k: v for k, v in cfg.items()})
""")

md(r"""
## 1 Data

Data acquisition happens outside s3geo, because s3geo has no STAC/Overpass loader. This step
uses the project scripts:

- `01`: Sentinel-2 L2A B04/B08 for 2017-08-27 and 2025-09-01 from Earth Search.
- `02`: district boundaries (geoBoundaries ADM2; OSM has no qism level for Cairo).
- `03`: reflectance on a 60 m UTM 36N grid.

The scripts run only if their outputs are missing. The notebook then builds one extra input: a
**4-band stack** (red and NIR for 2017, then red and NIR for 2025). s3geo's `band_math` works on
one raster at a time, so a two-date question needs both dates in one raster.
""")

code(r"""
P = ROOT / "data" / "processed"
need = [P / "refl_early.tif", P / "refl_late.tif", P / "districts_utm.geojson"]
if not all(p.exists() for p in need):
    for s in ["01_fetch_sentinel2.py", "02_fetch_districts.py --source geoboundaries", "03_prepare_inputs.py"]:
        print(">>", s); subprocess.run([sys.executable, *s.split()], cwd=ROOT / "scripts", check=True)

stack = P / "refl_stack_2017_2025.tif"
with rasterio.open(P / "refl_early.tif") as a, rasterio.open(P / "refl_late.tif") as b:
    prof = a.profile | {"count": 4}
    with rasterio.open(stack, "w", **prof) as dst:
        dst.write(np.concatenate([a.read(), b.read()]))
        for i, d in enumerate(["red_2017", "nir_2017", "red_2025", "nir_2025"], 1):
            dst.set_band_description(i, d)

from plugins.local_raster_loader import load_local_raster   # s3geo's own loader
layers_all = {
    "s2_2017": load_local_raster(str(P / "refl_early.tif")),
    "s2_2025": load_local_raster(str(P / "refl_late.tif")),
    "s2_stack": load_local_raster(str(stack)),
    "districts": gpd.read_file(P / "districts_utm.geojson")[["district_id", "name_en", "geometry"]],
}
for k, v in layers_all.items():
    print(f"{k:10s}", type(v).__name__, getattr(v, "metadata", {}).get("band_count", len(v) if hasattr(v, "__len__") else ""))
""")

md(r"""
## 2 Reference numbers (scripted pipeline = the paper)

The LLM's answers are compared with these numbers. If they are missing, the scripted pipeline
runs first.
""")

code(r"""
if not (P / "district_change_table.csv").exists():
    subprocess.run([sys.executable, "04_run_s3geo_pipeline.py"], cwd=ROOT / "scripts", check=True)
REF = pd.read_csv(P / "district_change_table.csv", dtype={"district_id": str}).set_index("district_id")
REF_SUM = json.loads((P / "run_summary.json").read_text())
ref_ndvi = {r: rasterio.open(P / f"ndvi_{r}.tif").read(1) for r in ("early", "late")}
ref_dndvi = rasterio.open(P / "dndvi.tif").read(1)
REF[["name_en", "ndvi_early_mean", "ndvi_late_mean", "dndvi_mean", "veg_frac_early", "rank_decline"]].sort_values("rank_decline").head(8)
""")

code(r"""
RUNS, CHECKS = [], []

def show(run):
    print(f"[{run.qid}] ok={run.ok}  {run.seconds:.1f}s  LLM attempts={run.attempts} repaired={run.repaired}")
    print("goal:", run.goal)
    print("operations:", " → ".join(run.operations) if run.operations else "-")
    if run.error: print("ERROR:", run.error[:800])
    if run.query_spec:
        for op in run.query_spec.get("operations", []):
            print(f"  · {op['op']:<18} inputs={op.get('inputs')} params={json.dumps(op.get('params'), ensure_ascii=False)[:220]}")

def check(qid, name, passed, **detail):
    CHECKS.append({"qid": qid, "check": name, "pass": bool(passed), **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in detail.items()}})
    print(("PASS " if passed else "FAIL ") + name, detail)

def zonal_series(run, *needles):
    feats = L.features_of(run.output)
    if not feats: return pd.Series(dtype=float), None
    props = feats[0]["properties"]
    key = L.find_prop(props, *needles)
    idk = "zone_id" if "zone_id" in props else "district_id"
    s = pd.Series({str(f["properties"].get(idk)): f["properties"].get(key) for f in feats}, dtype=float)
    return s, key

def compare_series(qid, s, ref_col, tol=1e-3):
    j = pd.concat([s.rename("llm"), REF[ref_col].rename("ref")], axis=1, join="inner").dropna()
    if j.empty:
        check(qid, f"{ref_col}: values returned", False, matched=0); return
    diff = float((j.llm - j.ref).abs().max())
    rho = float(j.llm.rank().corr(j.ref.rank()))
    check(qid, f"{ref_col} matches reference", diff <= tol and len(j) == len(REF),
          districts=len(j), max_abs_diff=diff, spearman=rho)

def ask(qid, fa, en, **kw):
    q = fa if LANG == "fa" else en
    print("Q:", q)
    run = L.ask(qid, q, LAYERS_FOR[qid], mode=MODE, **kw)
    RUNS.append(run); show(run); return run
""")

QUESTIONS = [
    ("Q1", "NDVI of one scene",
     "برای لایهٔ s2_2017 (باند ۱ قرمز و باند ۲ مادون‌قرمز نزدیک است) شاخص NDVI را محاسبه کن.",
     "Compute NDVI for layer s2_2017 (band 1 is red, band 2 is near-infrared).",
     ["s2_2017"],
     r"""
if run.ok:
    arr, meta = L.raster_of(run.output)
    d = np.nanmax(np.abs(arr - ref_ndvi["early"]))
    check("Q1", "NDVI 2017 raster = reference", arr.shape == ref_ndvi["early"].shape and d < 1e-3, max_abs_diff=float(d))
"""),
    ("Q2", "District mean NDVI, 2017",
     "میانگین NDVI سال ۲۰۱۷ را برای هر محله حساب کن. لایهٔ تصویر s2_2017 است (باند ۱ قرمز، باند ۲ مادون‌قرمز نزدیک) و محله‌ها در لایهٔ districts با شناسهٔ district_id هستند.",
     "Compute the mean 2017 NDVI for every district. The image is layer s2_2017 (band 1 red, band 2 near-infrared); districts are in layer districts with id field district_id.",
     ["s2_2017", "districts"],
     r"""
if run.ok:
    s, key = zonal_series(run, "mean"); print("stat field chosen by the plan:", key)
    compare_series("Q2", s, "ndvi_early_mean")
"""),
    ("Q3", "District mean NDVI, 2025",
     "میانگین NDVI سال ۲۰۲۵ را برای هر محله حساب کن. لایهٔ تصویر s2_2025 است (باند ۱ قرمز، باند ۲ مادون‌قرمز نزدیک) و محله‌ها در لایهٔ districts با شناسهٔ district_id هستند.",
     "Compute the mean 2025 NDVI for every district. The image is layer s2_2025 (band 1 red, band 2 near-infrared); districts are in layer districts with id field district_id.",
     ["s2_2025", "districts"],
     r"""
if run.ok:
    s, key = zonal_series(run, "mean"); print("stat field chosen by the plan:", key)
    compare_series("Q3", s, "ndvi_late_mean")
"""),
    ("Q4", "ΔNDVI map from a 4-band stack",
     "لایهٔ s2_stack چهار باند دارد: باند ۱ قرمز ۲۰۱۷، باند ۲ مادون‌قرمز نزدیک ۲۰۱۷، باند ۳ قرمز ۲۰۲۵، باند ۴ مادون‌قرمز نزدیک ۲۰۲۵. نقشهٔ تغییر NDVI یعنی NDVI سال ۲۰۲۵ منهای NDVI سال ۲۰۱۷ را بساز.",
     "Layer s2_stack has four bands: 1 = red 2017, 2 = NIR 2017, 3 = red 2025, 4 = NIR 2025. Build the NDVI change map, i.e. NDVI 2025 minus NDVI 2017.",
     ["s2_stack"],
     r"""
if run.ok:
    arr, meta = L.raster_of(run.output)
    d = np.nanmax(np.abs(arr - ref_dndvi))
    check("Q4", "ΔNDVI raster = reference", arr.shape == ref_dndvi.shape and d < 1e-3, max_abs_diff=float(d))
    Q4_DNDVI = arr
"""),
    ("Q5", "District ΔNDVI and ranking",
     "لایهٔ s2_stack چهار باند دارد: باند ۱ قرمز ۲۰۱۷، باند ۲ مادون‌قرمز نزدیک ۲۰۱۷، باند ۳ قرمز ۲۰۲۵، باند ۴ مادون‌قرمز نزدیک ۲۰۲۵. میانگین تغییر NDVI (۲۰۲۵ منهای ۲۰۱۷) را برای هر محلهٔ لایهٔ districts (شناسه district_id) حساب کن.",
     "Layer s2_stack has four bands: 1 = red 2017, 2 = NIR 2017, 3 = red 2025, 4 = NIR 2025. Compute the mean NDVI change (2025 minus 2017) for every district in layer districts (id field district_id).",
     ["s2_stack", "districts"],
     r"""
if run.ok:
    s, key = zonal_series(run, "mean"); print("stat field chosen by the plan:", key)
    compare_series("Q5", s, "dndvi_mean")
    if len(s):
        # districts 8-10 differ by < 0.001 in mean ΔNDVI, so the check is the top 7 in order + overall rank agreement
        llm_top = list(s.sort_values().index[:7]); ref_top = list(REF.sort_values("rank_decline").index[:7])
        rho = float(pd.concat([s, REF.dndvi_mean], axis=1, join="inner").rank().corr().iloc[0, 1])
        check("Q5", "same top-7 declining districts, same order; Spearman ≥ 0.99", llm_top == ref_top and rho >= 0.99,
              spearman=rho, llm_top7=", ".join(REF.loc[llm_top, "name_en"]))
        Q5_SERIES = s
"""),
    ("Q6", "Change classes",
     "لایهٔ s2_stack چهار باند دارد: باند ۱ قرمز ۲۰۱۷، باند ۲ مادون‌قرمز نزدیک ۲۰۱۷، باند ۳ قرمز ۲۰۲۵، باند ۴ مادون‌قرمز نزدیک ۲۰۲۵. تغییر NDVI (۲۰۲۵ منهای ۲۰۱۷) را حساب کن و به پنج کلاس طبقه‌بندی کن: ۱ کاهش شدید (کمتر از ‎-0.15)، ۲ کاهش (از ‎-0.15 تا ‎-0.05)، ۳ پایدار (از ‎-0.05 تا 0.05)، ۴ افزایش (از 0.05 تا 0.15)، ۵ افزایش شدید (بیشتر از 0.15).",
     "Layer s2_stack has four bands: 1 = red 2017, 2 = NIR 2017, 3 = red 2025, 4 = NIR 2025. Compute the NDVI change (2025 minus 2017) and classify it into five classes: 1 strong decline (< -0.15), 2 decline (-0.15 to -0.05), 3 stable (-0.05 to 0.05), 4 gain (0.05 to 0.15), 5 strong gain (> 0.15).",
     ["s2_stack"],
     r"""
if run.ok:
    arr, meta = L.raster_of(run.output)
    llm_counts = {int(v): int((arr == v).sum()) for v in (1, 2, 3, 4, 5)}
    labels = {1: "strong_decline", 2: "decline", 3: "stable", 4: "gain", 5: "strong_gain"}
    ref_counts = {v: REF_SUM["dndvi_class_counts"].get(labels[v], 0) for v in labels}
    worst = max(abs(llm_counts[v] - ref_counts[v]) / max(ref_counts[v], 1) for v in labels)
    print(pd.DataFrame({"llm_px": llm_counts, "reference_px": ref_counts}).rename(index=labels))
    check("Q6", "class areas within 1 % of reference", worst <= 0.01, worst_rel_diff=float(worst))
"""),
    ("Q7", "Vegetated share per district",
     "برای هر محلهٔ لایهٔ districts (شناسه district_id) سهم پیکسل‌هایی را که NDVI آن‌ها در سال ۲۰۱۷ دست‌کم ۰٫۲ است حساب کن. تصویر ۲۰۱۷ لایهٔ s2_2017 است (باند ۱ قرمز، باند ۲ مادون‌قرمز نزدیک). خروجی باید برای هر محله عددی بین ۰ و ۱ باشد.",
     "For every district in layer districts (id district_id), compute the share of pixels whose 2017 NDVI is at least 0.2. The 2017 image is layer s2_2017 (band 1 red, band 2 NIR). The result should be a number between 0 and 1 per district.",
     ["s2_2017", "districts"],
     r"""
if run.ok:
    s, key = zonal_series(run, "mean"); print("stat field chosen by the plan:", key)
    compare_series("Q7", s, "veg_frac_early", tol=5e-3)  # ≤ ~1 pixel per district at the 0.2 threshold
"""),
    ("Q8", "Decline areas as polygons",
     "لایهٔ s2_stack چهار باند دارد: باند ۱ قرمز ۲۰۱۷، باند ۲ مادون‌قرمز نزدیک ۲۰۱۷، باند ۳ قرمز ۲۰۲۵، باند ۴ مادون‌قرمز نزدیک ۲۰۲۵. پیکسل‌هایی را که NDVI آن‌ها از ۲۰۱۷ تا ۲۰۲۵ بیش از 0.05 کاهش یافته پیدا کن و به پلیگون تبدیل کن.",
     "Layer s2_stack has four bands: 1 = red 2017, 2 = NIR 2017, 3 = red 2025, 4 = NIR 2025. Find the pixels whose NDVI dropped by more than 0.05 from 2017 to 2025 and convert them to polygons.",
     ["s2_stack"],
     r"""
if run.ok:
    feats = L.features_of(run.output)
    px = sum(int(f["properties"].get("pixel_count", 1)) for f in feats)
    ref_px = REF_SUM["dndvi_class_counts"].get("strong_decline", 0) + REF_SUM["dndvi_class_counts"].get("decline", 0)
    print(f"{len(feats)} polygons covering {px} pixels (reference decline pixels: {ref_px})")
    check("Q8", "decline pixel count within 1 % of reference", abs(px - ref_px) / ref_px <= 0.01, llm_px=px, ref_px=ref_px)
    Q8_FEATS = feats
"""),
    ("Q9", "The open research question",
     "لایهٔ s2_stack چهار باند دارد: باند ۱ قرمز ۲۰۱۷، باند ۲ مادون‌قرمز نزدیک ۲۰۱۷، باند ۳ قرمز ۲۰۲۵، باند ۴ مادون‌قرمز نزدیک ۲۰۲۵؛ محله‌ها در لایهٔ districts هستند. کدام ۱۰ محلهٔ قاهره بین ۲۰۱۷ و ۲۰۲۵ بیشترین کاهش پوشش گیاهی (میانگین تغییر NDVI) را داشته‌اند؟",
     "Layer s2_stack has four bands: 1 = red 2017, 2 = NIR 2017, 3 = red 2025, 4 = NIR 2025; districts are in layer districts. Which 10 Cairo districts had the largest vegetation decline (mean NDVI change) between 2017 and 2025?",
     ["s2_stack", "districts"],
     r"""
if run.ok:
    feats = L.features_of(run.output)
    ids = [str(f["properties"].get("zone_id", f["properties"].get("district_id"))) for f in feats]
    print("returned", len(feats), "districts:", ", ".join(REF.loc[[i for i in ids if i in REF.index], "name_en"]))
    ref10 = list(REF.sort_values("rank_decline").index[:10])
    # the top 7 are separated clearly; places 8-10 are within 0.001 of each other, so only set membership is checked there
    check("Q9", "10 districts returned = reference top 10 (top 7 in order)",
          len(ids) == 10 and set(ids) == set(ref10) and ids[:7] == ref10[:7],
          overlap_with_reference_top10=len(set(ids) & set(ref10)))
"""),
]

code("LAYERS_FOR = {" + ", ".join(f'"{q[0]}": {{k: layers_all[k] for k in {q[4]!r}}}' for q in QUESTIONS) + "}")

for qid, title, fa, en, _lay, chk in QUESTIONS:
    md(f"## {qid}: {title}\n\n> **fa:** {fa}\n>\n> **en:** {en}")
    code(f'run = ask("{qid}", {fa!r},\n          {en!r})\n' + chk.strip())

md(r"""
## Figures made from s3geo's own outputs

These maps are drawn only from what s3geo returned to the questions above: the ΔNDVI raster from
Q4, and the district means from Q5.
""")

code(r"""
fig, axs = plt.subplots(1, 2, figsize=(12, 6), constrained_layout=True)
d = gpd.read_file(P / "districts_utm.geojson")
if "Q4_DNDVI" in globals():
    with rasterio.open(P / "refl_early.tif") as src: b = src.bounds
    im = axs[0].imshow(Q4_DNDVI, cmap="RdBu", vmin=-0.4, vmax=0.4, extent=(b.left, b.right, b.bottom, b.top))
    d.boundary.plot(ax=axs[0], color="k", lw=0.3); fig.colorbar(im, ax=axs[0], shrink=0.7, label="ΔNDVI (Q4, s3geo)")
if "Q5_SERIES" in globals():
    m = d.merge(Q5_SERIES.rename("dndvi").rename_axis("district_id").reset_index(), on="district_id")
    lim = float(np.nanmax(np.abs(m.dndvi)))
    m.plot(column="dndvi", cmap="RdBu", vmin=-lim, vmax=lim, ax=axs[1], legend=True, legend_kwds={"shrink": 0.7, "label": "mean ΔNDVI (Q5, s3geo)"}, edgecolor="w", lw=0.4)
for a in axs: a.set_axis_off()
out = L.RESULTS / f"llm_maps_{MODE}.png"; fig.savefig(out, dpi=150); print("saved", out)
""")

md("## Evaluation: how far does plain language get you?")

code(r"""
runs = pd.DataFrame([r.summary() for r in RUNS])
checks = pd.DataFrame(CHECKS)
res = L.RESULTS
runs.to_csv(res / f"llm_runs_{MODE}.csv", index=False); checks.to_csv(res / f"llm_checks_{MODE}.csv", index=False)
n_q, n_ok = len(runs), int(runs.ok.sum())
n_first = int(((runs.ok) & (runs.llm_attempts <= 1)).sum())
n_pass = int(checks["pass"].sum()) if len(checks) else 0
summary = {"mode": MODE, "lang": LANG, "model": runs.model.dropna().iloc[0] if runs.model.notna().any() else None,
           "questions": n_q, "executed": n_ok, "plan_accepted_first_try": n_first,
           "checks": len(checks), "checks_passed": n_pass}
(res / f"llm_summary_{MODE}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
print(json.dumps(summary, indent=2, ensure_ascii=False))
display(runs[["qid", "ok", "llm_attempts", "repaired", "seconds", "operations", "error"]])
display(checks)
""")

md(r"""
### Reading the result

- **executed**: s3geo turned the question into a valid plan and ran it.
- **checks_passed**: the answer matches the paper's reference numbers. District means must agree
  to 10⁻³ and class areas to 1 %.
- A **FAIL** is a result too, not an error in the notebook. The saved plan (`plans/Qn.json`) shows
  what the LLM understood, and the gap tells us what s3geo's planner or catalog is missing.
  Typical gaps are an operation it has no way to express (e.g. two rasters in one expression) or
  a parameter the LLM guessed wrong.
""")

nb["cells"] = C
nb["metadata"] = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                  "language_info": {"name": "python"}}
nbf.write(nb, "notebooks/cairo_s3geo_llm.ipynb")
print("wrote notebooks/cairo_s3geo_llm.ipynb with", len(C), "cells")
