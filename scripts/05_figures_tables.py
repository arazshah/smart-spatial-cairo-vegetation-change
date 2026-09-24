"""Figures + markdown tables for paper/paper.md (plotting only; reads plugin outputs)."""
from __future__ import annotations

import csv

import numpy as np
import geopandas as gpd
import matplotlib
import rasterio
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from common import FIG, NDVI_CLASSES, DNDVI_CLASSES, PROC, dump, load  # noqa: E402

INK, MUTED, SURFACE = "#1a1a19", "#6b6a66", "#fcfcfb"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": SURFACE,
                     "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE})
# single-hue sequential for NDVI magnitude; diverging red<->blue with gray midpoint for dNDVI
SEQ = LinearSegmentedColormap.from_list("seq_green", ["#f3f1e8", "#bfdcae", "#6fb36a", "#2e7d32", "#123f18"])
DIV = LinearSegmentedColormap.from_list("div", ["#7a1c1c", "#e34948", "#f0efec", "#3987e5", "#104281"])
SEQ.set_bad("#ffffff00")
DIV.set_bad("#ffffff00")

harm = load(PROC / "harmonisation.json")
districts = gpd.read_file(PROC / "districts_utm.geojson")
rows = list(csv.DictReader(open(PROC / "district_change_table.csv", encoding="utf-8")))


def read(name):
    with rasterio.open(PROC / name) as s:
        return s.read(1), s.bounds


def base_ax(ax, title):
    ax.set_title(title, loc="left", color=INK, fontsize=10)
    ax.set_xticks([]), ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    districts.boundary.plot(ax=ax, color=INK, linewidth=0.35, alpha=0.6)


# Fig 1: NDVI before / after
fig, axs = plt.subplots(1, 2, figsize=(10, 5.4), constrained_layout=True)
for ax, role in zip(axs, ("early", "late")):
    a, bnd = read(f"ndvi_{role}.tif")
    im = ax.imshow(a, cmap=SEQ, vmin=-0.1, vmax=0.7, extent=(bnd.left, bnd.right, bnd.bottom, bnd.top))
    base_ax(ax, f"NDVI - {harm[role]['date']}")
cb = fig.colorbar(im, ax=axs, shrink=0.7, label="NDVI")
fig.savefig(FIG / "fig1_ndvi_before_after.png", dpi=180)
plt.close(fig)

# Fig 2: dNDVI change map
a, bnd = read("dndvi.tif")
fig, ax = plt.subplots(figsize=(6.4, 6.4), constrained_layout=True)
im = ax.imshow(a, cmap=DIV, vmin=-0.4, vmax=0.4, extent=(bnd.left, bnd.right, bnd.bottom, bnd.top))
base_ax(ax, f"dNDVI  ({harm['late']['date']} minus {harm['early']['date']})")
fig.colorbar(im, ax=ax, shrink=0.75, label="dNDVI  (red = decline, blue = gain)")
fig.savefig(FIG / "fig2_dndvi_change_map.png", dpi=180)
plt.close(fig)

# Fig 3: change classes + district mean dNDVI choropleth
c, bnd = read("dndvi_class.tif")
cls_cmap = ListedColormap(["#7a1c1c", "#e8908f", "#e4e2dc", "#8fb8ef", "#104281"])
fig, axs = plt.subplots(1, 2, figsize=(10.5, 5.4), constrained_layout=True)
im = axs[0].imshow(c, cmap=cls_cmap, norm=BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], 5),
                   extent=(bnd.left, bnd.right, bnd.bottom, bnd.top), interpolation="nearest")
base_ax(axs[0], "Change classes (reclassified dNDVI)")
cb = fig.colorbar(im, ax=axs[0], ticks=[1, 2, 3, 4, 5], shrink=0.7)
cb.ax.set_yticklabels([k["label"].replace("_", " ") for k in DNDVI_CLASSES])
m = districts.merge(gpd.pd.DataFrame(rows)[["district_id", "dndvi_mean"]], on="district_id")
m["dndvi_mean"] = m["dndvi_mean"].replace("", np.nan).astype(float)
lim = float(np.nanmax(np.abs(m["dndvi_mean"]))) or 0.1
m.plot(column="dndvi_mean", ax=axs[1], cmap=DIV, vmin=-lim, vmax=lim, edgecolor=SURFACE, linewidth=0.6,
       legend=True, legend_kwds={"shrink": 0.7, "label": "district mean dNDVI"})
base_ax(axs[1], "District mean dNDVI (zonal_statistics)")
fig.savefig(FIG / "fig3_change_classes_districts.png", dpi=180)
plt.close(fig)

# Fig 4: ranked bars - sharpest declines (one measure, one axis)
top = [r for r in rows if r["dndvi_mean"] not in ("", None)][:15]
fig, ax = plt.subplots(figsize=(7.5, 0.32 * len(top) + 1.2), constrained_layout=True)
vals = [float(r["dndvi_mean"]) for r in top]
names = [r["name_en"] or r["name"] for r in top]
ax.barh(range(len(top)), vals, color="#e34948", height=0.72)
ax.set_yticks(range(len(top)), names)
ax.invert_yaxis()
ax.axvline(0, color=MUTED, linewidth=0.8)
ax.set_xlim(min(vals) * 1.15, max(0.0, max(vals)) + 0.01)
ax.grid(axis="x", color="#e4e2dc", linewidth=0.6)
ax.set_axisbelow(True)
for i, v in enumerate(vals):
    ax.text(v - 0.002, i, f"{v:+.3f}", va="center", ha="right", color=INK, fontsize=8)
ax.set_xlabel("mean dNDVI per district")
ax.set_title("Districts with the sharpest NDVI decline", loc="left", color=INK, fontsize=10)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
fig.savefig(FIG / "fig4_top_decline_bars.png", dpi=180)
plt.close(fig)

# Markdown tables
def fmt(v, nd=3):
    try:
        return f"{float(v):+.{nd}f}" if nd else f"{float(v):.0f}"
    except (TypeError, ValueError):
        return "n/a"


hdr = ("| Rank | District | Area km² | NDVI early | NDVI late | ΔNDVI mean | ΔNDVI median | "
       "Veg. cover early → late (%) | Decline area ha (strong + moderate) | Decline share % |\n"
       "|---:|---|---:|---:|---:|---:|---:|---|---:|---:|\n")
lines = []
for r in rows:
    if r["dndvi_mean"] in ("", None):
        continue
    ve = float(r["veg_frac_early"]) * 100 if r["veg_frac_early"] else float("nan")
    vl = float(r["veg_frac_late"]) * 100 if r["veg_frac_late"] else float("nan")
    lines.append(f"| {r['rank_decline']} | {r['name_en'] or r['name']} ({r['name']}) | {float(r['area_km2']):.1f} | "
                 f"{float(r['ndvi_early_mean']):.3f} | {float(r['ndvi_late_mean']):.3f} | {fmt(r['dndvi_mean'])} | "
                 f"{fmt(r['dndvi_median'])} | {ve:.1f} → {vl:.1f} | "
                 f"{float(r['strong_decline_ha']) + float(r['decline_ha']):.0f} "
                 f"({float(r['strong_decline_ha']):.0f} + {float(r['decline_ha']):.0f}) | {float(r['decline_share_pct']):.1f} |")
(PROC / "table_districts.md").write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8")

s = load(PROC / "run_summary.json")
px = s["grid"]["res_m"] ** 2 / 1e4
aoi = "| Class | " + " | ".join(harm[r]["date"] for r in ("early", "late")) + " |\n|---|---:|---:|\n"
for k in NDVI_CLASSES:
    aoi += f"| {k['label'].replace('_', ' ')} (NDVI {k['min']}–{k['max']}) | " + " | ".join(
        f"{s['class_counts'][r].get(k['label'], 0) * px:,.0f} ha" for r in ("early", "late")) + " |\n"
(PROC / "table_aoi_classes.md").write_text(aoi, encoding="utf-8")
chg = "| Change class | ΔNDVI range | Area (ha) | Share of valid pixels |\n|---|---|---:|---:|\n"
tot = sum(s["dndvi_class_counts"].values())
for k in DNDVI_CLASSES:
    n = s["dndvi_class_counts"].get(k["label"], 0)
    chg += f"| {k['label'].replace('_', ' ')} | {k['min']} … {k['max']} | {n * px:,.0f} | {100 * n / tot:.1f} % |\n"
(PROC / "table_aoi_change.md").write_text(chg, encoding="utf-8")
dump({"figures": sorted(p.name for p in FIG.glob("*.png"))}, PROC / "figures_index.json")
print("figures + tables written")
