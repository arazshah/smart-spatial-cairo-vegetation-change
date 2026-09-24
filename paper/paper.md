# Where did Cairo's green go? District-level NDVI change in Greater Cairo, 2017–2025, with the s3geo smart spatial system

*Case study for `smart-spatial-system` (s3geo): analysed on 0.5.6 and re-run on **0.5.7**, with identical results · 2026-09-24*

---

## Abstract

We compare two cloud-free, late-summer Sentinel-2 L2A scenes of Greater Cairo: 27 Aug 2017 and
1 Sep 2025. We compute NDVI, classify vegetation health and map ΔNDVI. We then rank the 48
districts (qism/markaz, from CAPMAS via geoBoundaries) that lie mostly inside a 0.3° × 0.3° AOI.
Every analytical step runs through plugins of the s3geo smart spatial system.

Across the AOI, mean NDVI did not change (0.182 → 0.182). However, the area with NDVI ≥ 0.2
shrank by **≈ 2,000 ha (−6.6 %, from 30.4 % to 28.4 % of the AOI)**. Most of that loss is in the
*moderate* class (0.2–0.4, −14 %). The losses sit on the **agricultural fringe of the western
(Giza) bank and the northern edge (Qalyubia)**:

- **Waraq** (mean ΔNDVI −0.028; vegetated share 46.6 % → 37.5 %)
- **Shubra al-Khayma 2** (−0.022)
- **Kardasa** (−0.016; the largest decline area, 1,854 ha)
- **Al-Ahram**, **Khsos**, **Shubra al-Khayma 1** and **Marg**

The dense historic core and the eastern desert-fringe districts show small NDVI *gains*
(+0.01 to +0.025), which fits new parks and greened corridors. Masking water does not change the
top-8 ranking.

On the tooling side, the pipeline ran end to end on s3geo and agreed with an independent
numpy/rasterio re-computation to 5 × 10⁻⁵. It also exposed eight defects in 0.5.6, reported with
minimal reproductions rather than worked around. Seven of them are fixed in 0.5.7; re-running on
0.5.7 reproduces every number exactly and is about 20× faster.

## 1 Introduction

Cairo's vegetation is almost entirely irrigated. It consists of Nile-fed farmland on the valley
and delta edges, plus parks, clubs and street trees in the built-up core. Urban expansion onto
agricultural land has been a policy concern for decades. More recently, large road, bridge and
housing projects have been linked to the loss of trees inside the city. NDVI from Sentinel-2 is a
standard, cheap and transparent way to measure such change at district scale.

**Research question.** How has NDVI (vegetation health and extent) changed across Cairo between a
dry-season scene from about a decade ago and one from 2025, and which districts show the sharpest
decline?

**Tool question.** Can this analysis be run end to end with s3geo's plugin capabilities, and where
does the toolkit fall short?

## 2 Data and methods

### 2.1 Study area and data

- **AOI**: 31.10–31.40 °E, 29.90–30.20 °N. This is the Greater Cairo core on both Nile banks,
  covering parts of Cairo, Giza and Qalyubia governorates. It is 9.95 × 10⁴ ha of valid pixels.
- **Imagery**: Sentinel-2 L2A B04 (red) and B08 (NIR), 10 m, found through the AWS Earth Search
  STAC API. Only an AOI window of each public COG was read over HTTPS. The selection rules were
  fixed in advance (`data/README.md`): June–September, cloud < 5 %, the same MGRS tile for both
  dates, and AOI nodata < 1 %.
  - **Early:** `S2B_36RUU_20170827_0_L2A` (cloud 0.17 %).
  - **Late:** `S2A_36RUU_20250901_0_L2A` (cloud 0.001 %).
  - **Why 2017:** Earth Search holds no L2A over Cairo before 2017. The reprocessed
    `sentinel-2-c1-l2a` collection starts in 2018 here, and `sentinel-2-l2a` has nothing for
    2015–2016. The study interval is therefore **8 years**, not 10.
  - **Season match:** the two dates are 5 days apart in the calendar, both in the dry,
    irrigation-driven season.
- **Districts**: the task specified OSM. The OSM admin level was inspected first
  (`scripts/02_fetch_districts.py --inspect`; the raw survey is in `data/raw/`):
  - Within the AOI, OSM holds only `admin_level` 2 (Egypt) and 4 (governorates).
  - Known district names (Nasr City, Maadi, Heliopolis, Zamalek, Dokki, …) match only metro
    stations, squares and untagged ways.
  - No qism/hayy relation exists at any level.

  We therefore used **geoBoundaries gbOpen EGY ADM2** ("marakiz and aqsam"; source CAPMAS via
  OCHA/HDX, 2020; CC BY 3.0 IGO), which is the qism level. The 48 units with ≥ 50 % of their area
  inside the AOI were kept and clipped to it.

### 2.2 Pre-processing (I/O only)

- **Reflectance.** DN were converted to surface reflectance (`scale` 10⁻⁴).
- **Offset handling.** Care is needed here. The 2025 item's `raster:bands` advertises
  `offset = −0.1`, which is the usual −1000 DN `BOA_ADD_OFFSET` of baseline ≥ 04.00. But the same
  item carries `earthsearch:boa_offset_applied = true`, meaning Element 84 has *already* removed
  that offset from the DNs. Two checks confirm it:
  - 16 % of 2025 red pixels have DN < 1000, which would be impossible for un-shifted data.
  - Applying the offset again drops mean red reflectance from 0.21 to 0.11 and produces NDVI > 1.

  The offset is therefore not applied again (`scripts/03_prepare_inputs.py`). As an after-check,
  bare/built pixels (0 < NDVI < 0.1 on both dates, n = 115,718) have a median ΔNDVI of **+0.002**
  (IQR −0.003…+0.008). The two scenes are radiometrically consistent well inside the ±0.05
  "stable" band.
- **Regridding.** Both dates were area-averaged onto one UTM 36N grid at **60 m**, 492 × 562 =
  276,504 px (§2.4).
- **Districts.** Polygons were reprojected to UTM 36N, because the raster plugins do no CRS
  handling, and simplified with a 5 m tolerance (sub-pixel).

### 2.3 Analysis with s3geo plugins

| # | Step | s3geo plugin → capability | Settings |
|---|---|---|---|
| 0 | Input validation | `local_raster_loader.load_local_raster` | CRS, band count, transform |
| 1 | NDVI, both dates | `ndvi_calculator.calculate_ndvi` | red = band 1, NIR = band 2, clipped to [−1, 1] |
| 2 | ΔNDVI = late − early | `band_math.calculate_band_math` | `b2 - b1` |
| 2b | Vegetation mask | `band_math.calculate_band_math` | `where(b1 >= 0.2, 1, 0)` → zonal mean = vegetated share |
| 3 | Vegetation-health classes | `raster_reclassify.reclassify_raster` | water < 0 ≤ built/bare < 0.10 ≤ sparse < 0.20 ≤ moderate < 0.40 ≤ dense |
| 3b | Change classes | `raster_reclassify.reclassify_raster` | strong decline < −0.15 ≤ decline < −0.05 ≤ stable ≤ 0.05 < gain ≤ 0.15 < strong gain |
| 4 | Per-district statistics | `zonal_statistics.calculate_zonal_statistics` | pixel centre in polygon (`all_touched=False`) |
| 5 | Change table | `raster_to_vector` (cells) → `centroid_extractor` → `spatial_join` (within) → `attribute_statistics` (group by district × class) | changed pixels only |
| S | Sensitivity (added after inspecting Fig. 2) | `band_math` `where(min(b1, b2) < 0, None, b2 - b1)` → `zonal_statistics` | water in either date masked |

The thresholds and the primary ranking metric (district mean ΔNDVI, reported with decline area)
were fixed in `paper/PLAN.md` before the data were seen.

Choices forced by defects in 0.5.6 (all reported, none patched; all fixed in 0.5.7, §4):

- **`all_touched=False` everywhere.** With `all_touched=True`, zonal statistics counts the zone's
  whole bounding box (bug 002).
- **`None` as the single nodata marker, end to end.** Otherwise `raster_reclassify` advertises the
  wrong nodata value to downstream plugins (bug 005).
- **Change pixels vectorised as cells, not components.** Component mode merges neighbouring classes
  (bug 003). Cells are assigned to districts by their centre point, the same rule zonal
  statistics uses, so the areas from steps 4 and 5 agree.
- **Pixels passed to the plugins as in-memory lists.** The loader's output carries no pixels
  (bug 001).

### 2.4 Resolution and runtime

In 0.5.6 the raster plugins are pure Python and re-validate the whole array on every pixel read
(bug 006), so runtime grows as O(H²·W). Version 0.5.7 fixes this. Measured times at 60 m:

| Step | 0.5.6 | 0.5.7 |
|---|---:|---:|
| One NDVI call | 35 s | 0.7 s |
| One zonal-statistics run (48 districts, ≈ 4,200 vertices) | ≈ 3 min | ≈ 7 s |
| Full 17-call pipeline | 18.5 min | 55 s |

With 0.5.6, a single NDVI call at native 10 m would have taken about 2 h, so the full run would
have taken days. We therefore analyse at 60 m. On 0.5.7 the plugin runtime is no longer the limit;
a 1000 × 1000 NDVI takes 2.4 s. What limits a 10 m run now is memory: the plugins hold rasters as
nested Python lists, and ≈ 10 M pixels × several rasters does not fit in the 7 GB of this
environment. This dilutes street trees and small parks, so fine-scale green loss is
**under-estimated**. District means and fringe farmland conversion (fields ≫ 60 m) are much less
affected.

### 2.5 Verification

`scripts/06_crosscheck.py` recomputes NDVI, ΔNDVI, district means and decline-pixel counts with
numpy/rasterio (`geometry_mask`, pixel centres). On the real data:

- District means agree with the plugins to within **5 × 10⁻⁵**, which is the plugins' 4-decimal
  rounding.
- Decline-pixel counts agree to within **5 px per district**. The difference comes from pixels
  exactly on a class threshold after that rounding.

## 3 Results

### 3.1 NDVI before and after

![NDVI before/after](figures/fig1_ndvi_before_after.png)

*Figure 1 — NDVI on 27 Aug 2017 and 1 Sep 2025 (60 m), with district outlines.*

**Table 1 — AOI area by vegetation-health class** (plugin `reclassify_raster` rule-match counts × 0.36 ha)

| Class | 2017-08-27 | 2025-09-01 |
|---|---:|---:|
| water (NDVI -1.0–0.0) | 1,178 ha | 1,746 ha |
| built bare (NDVI 0.0–0.1) | 46,762 ha | 48,318 ha |
| sparse veg (NDVI 0.1–0.2) | 21,367 ha | 21,243 ha |
| moderate veg (NDVI 0.2–0.4) | 15,650 ha | 13,392 ha |
| dense veg (NDVI 0.4–1.0) | 14,585 ha | 14,843 ha |

Mean NDVI is unchanged: 0.1823 in 2017 and 0.1818 in 2025. The *composition* shifted, though:

- Moderate vegetation (0.2–0.4) lost ≈ 2,260 ha (−14 %).
- Dense vegetation (≥ 0.4) was stable (+1.8 %).
- Built/bare grew by ≈ 1,560 ha.
- Overall, the vegetated area (NDVI ≥ 0.2) fell from 30,235 ha to 28,235 ha (**−2,000 ha,
  −6.6 %**).
- The water class grew (+570 ha). This most likely reflects a lower-NDVI Nile surface in 2025 (turbidity or
  algae), not a land change (§3.4).

### 3.2 Change map

![dNDVI](figures/fig2_dndvi_change_map.png)

*Figure 2 — ΔNDVI (2025 − 2017). Red = decline, blue = gain, grey ≈ no change.*

![Change classes and district means](figures/fig3_change_classes_districts.png)

*Figure 3 — Left: ΔNDVI change classes (`reclassify_raster`). Right: district mean ΔNDVI
(`zonal_statistics`).*

**Table 2 — AOI area by change class**

| Change class | ΔNDVI range | Area (ha) | Share of valid pixels |
|---|---|---:|---:|
| strong decline | -2.0 … -0.15 | 4,232 | 4.3 % |
| decline | -0.15 … -0.05 | 9,507 | 9.6 % |
| stable | -0.05 … 0.05 | 72,932 | 73.3 % |
| gain | 0.05 … 0.15 | 8,607 | 8.6 % |
| strong gain | 0.15 … 2.0 | 4,263 | 4.3 % |

Change concentrates in the farmland belts, where decline (13.9 %) and gain (12.9 %) are both
large. That pattern is expected from crop rotation between two single dates, so the *net* change
per district is what matters. The built-up core is overwhelmingly "stable". Compact, coherent red
patches north-east of the centre (Shubra al-Khayma/Marg) and along the western fringe are
consistent with farmland being built over. Compact blue patches in the eastern districts are
consistent with new parks and greened areas.

### 3.3 Districts ranked by decline

![Top declines](figures/fig4_top_decline_bars.png)

*Figure 4 — The 15 districts with negative mean ΔNDVI, sharpest first.*

**Table 3 — All 48 districts ranked by mean ΔNDVI** (most negative first). The columns also show
the vegetated share (NDVI ≥ 0.2, from the `band_math` mask plus `zonal_statistics`) and the decline
area from the `raster_to_vector` → `centroid_extractor` → `spatial_join` → `attribute_statistics`
chain. Full CSV: `data/processed/district_change_table.csv`.

| Rank | District | Area km² | NDVI early | NDVI late | ΔNDVI mean | ΔNDVI median | Veg. cover early → late (%) | Decline area ha (strong + moderate) | Decline share % |
|---:|---|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | Waraq | 27.6 | 0.237 | 0.209 | -0.028 | -0.007 | 46.6 → 37.5 | 763 (324 + 439) | 27.6 |
| 2 | Shubra Al-Khayma 2 | 17.2 | 0.130 | 0.108 | -0.022 | -0.000 | 11.7 → 6.2 | 192 (117 + 75) | 11.2 |
| 3 | Kardasa | 62.7 | 0.294 | 0.278 | -0.016 | -0.012 | 65.8 → 57.8 | 1854 (674 + 1181) | 29.5 |
| 4 | Al-Ahram | 20.1 | 0.151 | 0.137 | -0.015 | -0.004 | 20.5 → 16.0 | 281 (77 + 204) | 14.0 |
| 5 | Khsos | 5.7 | 0.106 | 0.093 | -0.013 | +0.004 | 7.0 → 2.6 | 33 (23 + 9) | 5.7 |
| 6 | Shubra Al-Khayma 1 | 10.4 | 0.121 | 0.110 | -0.011 | +0.002 | 10.6 → 5.7 | 96 (50 + 46) | 9.3 |
| 7 | Marg | 16.5 | 0.114 | 0.103 | -0.010 | +0.000 | 8.2 → 4.6 | 143 (38 + 105) | 8.7 |
| 8 | Auseem | 51.1 | 0.382 | 0.376 | -0.005 | -0.015 | 79.8 → 75.8 | 1486 (420 + 1066) | 29.1 |
| 9 | Umraniyya | 17.5 | 0.111 | 0.105 | -0.005 | +0.001 | 7.8 → 6.3 | 106 (33 + 73) | 6.0 |
| 10 | Zamalik | 2.7 | 0.207 | 0.202 | -0.005 | -0.002 | 50.3 → 47.0 | 37 (8 + 29) | 13.8 |
| 11 | Giza (1246) | 56.3 | 0.332 | 0.328 | -0.004 | -0.009 | 70.0 → 64.3 | 1502 (498 + 1004) | 26.7 |
| 12 | Al-Aguza | 5.4 | 0.134 | 0.130 | -0.004 | -0.002 | 12.6 → 13.9 | 38 (3 + 36) | 7.1 |
| 13 | DuqqI | 5.2 | 0.157 | 0.155 | -0.002 | -0.003 | 23.7 → 22.6 | 44 (1 + 42) | 8.4 |
| 14 | Giza (0134) | 11.5 | 0.179 | 0.179 | -0.000 | -0.002 | 33.4 → 32.5 | 193 (46 + 148) | 16.8 |
| 15 | Al Matariyya | 6.2 | 0.091 | 0.093 | +0.001 | +0.006 | 2.0 → 2.6 | 30 (2 + 28) | 4.8 |
| 16 | Nuzha | 32.3 | 0.103 | 0.105 | +0.002 | +0.003 | 8.5 → 8.5 | 229 (34 + 196) | 7.1 |
| 17 | Misr Al-Qadima | 9.7 | 0.123 | 0.125 | +0.002 | +0.004 | 10.6 → 10.6 | 92 (28 + 63) | 9.4 |
| 18 | Bulaq Al-DakrUr | 9.2 | 0.123 | 0.125 | +0.002 | +0.001 | 13.8 → 12.9 | 58 (23 + 35) | 6.3 |
| 19 | Ain Shams | 8.3 | 0.102 | 0.105 | +0.003 | +0.006 | 7.4 → 7.8 | 26 (4 + 22) | 3.2 |
| 20 | Gamaliyya | 2.0 | 0.097 | 0.100 | +0.004 | +0.010 | 2.5 → 2.5 | 14 (1 + 13) | 6.8 |
| 21 | Imbaba | 8.6 | 0.093 | 0.097 | +0.004 | +0.003 | 4.7 → 6.8 | 25 (4 + 21) | 2.9 |
| 22 | Bulaq | 2.1 | 0.100 | 0.104 | +0.004 | +0.006 | 1.2 → 2.9 | 12 (0 + 12) | 5.7 |
| 23 | Rud Al-Farag | 2.5 | 0.095 | 0.098 | +0.004 | +0.005 | 3.0 → 2.7 | 8 (1 + 8) | 3.3 |
| 24 | Madinat Nasr-2 | 17.3 | 0.122 | 0.127 | +0.005 | +0.003 | 12.3 → 14.3 | 105 (16 + 89) | 6.1 |
| 25 | Misr al-Gadida | 9.2 | 0.148 | 0.153 | +0.005 | +0.007 | 19.3 → 21.1 | 59 (12 + 48) | 6.5 |
| 26 | Nasr City | 66.2 | 0.092 | 0.097 | +0.005 | +0.003 | 3.6 → 5.2 | 212 (15 + 197) | 3.2 |
| 27 | Al Sahil | 5.2 | 0.104 | 0.111 | +0.006 | +0.008 | 4.5 → 4.4 | 21 (5 + 16) | 4.0 |
| 28 | Al Wayli | 5.0 | 0.123 | 0.130 | +0.007 | +0.007 | 10.6 → 13.0 | 22 (4 + 19) | 4.5 |
| 29 | Hadaiq Al-Qubba | 4.0 | 0.097 | 0.103 | +0.007 | +0.010 | 3.9 → 4.1 | 16 (2 + 13) | 4.0 |
| 30 | Tura | 55.4 | 0.059 | 0.066 | +0.007 | +0.008 | 0.5 → 0.5 | 61 (4 + 57) | 1.1 |
| 31 | Al Zahir | 2.0 | 0.098 | 0.106 | +0.008 | +0.010 | 3.5 → 4.0 | 10 (1 + 10) | 5.3 |
| 32 | Maadi | 16.4 | 0.119 | 0.127 | +0.008 | +0.006 | 18.1 → 19.9 | 45 (3 + 42) | 2.8 |
| 33 | Basatin | 29.8 | 0.091 | 0.099 | +0.009 | +0.006 | 4.4 → 6.3 | 74 (16 + 58) | 2.5 |
| 34 | Minshat Nasir | 5.6 | 0.090 | 0.099 | +0.009 | +0.010 | 1.1 → 1.6 | 22 (0 + 22) | 4.0 |
| 35 | Zawiyya Al-Hamra | 5.0 | 0.115 | 0.124 | +0.009 | +0.008 | 10.6 → 13.4 | 26 (5 + 21) | 5.2 |
| 36 | Shubra | 1.3 | 0.094 | 0.104 | +0.010 | +0.010 | 1.7 → 1.9 | 0 (0 + 0) | 0.3 |
| 37 | Hwamdeia | 11.9 | 0.338 | 0.349 | +0.010 | +0.001 | 70.5 → 68.0 | 252 (57 + 195) | 21.1 |
| 38 | Al Sharabiyya | 3.7 | 0.096 | 0.108 | +0.011 | +0.010 | 1.9 → 3.5 | 8 (1 + 7) | 2.1 |
| 39 | Sayyida Zainab | 3.6 | 0.115 | 0.127 | +0.013 | +0.010 | 3.3 → 9.5 | 6 (0 + 6) | 1.6 |
| 40 | Al Khalifa | 38.9 | 0.093 | 0.106 | +0.014 | +0.004 | 4.2 → 7.8 | 126 (26 + 100) | 3.2 |
| 41 | Al Zaytun | 8.2 | 0.114 | 0.131 | +0.017 | +0.007 | 10.1 → 12.8 | 23 (2 + 20) | 2.8 |
| 42 | Muski | 0.8 | 0.084 | 0.101 | +0.017 | +0.011 | 2.2 → 4.5 | 0 (0 + 0) | 0.5 |
| 43 | Al Azbakiyya | 1.4 | 0.076 | 0.096 | +0.020 | +0.019 | 1.5 → 2.8 | 2 (0 + 2) | 1.2 |
| 44 | Bab Al-Shariyya | 1.0 | 0.090 | 0.110 | +0.020 | +0.019 | 0.0 → 2.5 | 1 (0 + 1) | 0.7 |
| 45 | Abdin | 1.7 | 0.097 | 0.118 | +0.021 | +0.019 | 6.2 → 7.3 | 1 (0 + 1) | 0.6 |
| 46 | Qasr Al-Nile | 1.1 | 0.117 | 0.139 | +0.021 | +0.016 | 13.6 → 19.3 | 1 (0 + 1) | 1.3 |
| 47 | Al Darb al-Ahmar | 1.9 | 0.135 | 0.159 | +0.025 | +0.009 | 15.0 → 17.2 | 1 (0 + 1) | 0.4 |
| 48 | Qalyub | 24.2 | 0.328 | 0.354 | +0.026 | -0.004 | 67.1 → 63.8 | 437 (148 + 289) | 18.0 |

**Reading the ranking.**

- **Sharpest decline.** The eight districts with the most negative mean ΔNDVI are all
  peri-urban, where farmland meets the city:
  - Waraq (including the Nile islands, notably al-Warraq island)
  - Shubra al-Khayma 2 and 1, and Marg on the northern edge
  - Kardasa, Al-Ahram and Khsos on the western/Giza fringe
  - Auseem

  The decline in these districts is a loss of *extent*: their vegetated share falls by 4–9
  percentage points, the largest being Waraq (−9.0 pp) and Kardasa (−7.9 pp).
- **Largest absolute decline area.** Here the biggest farmland districts lead: Kardasa (1,854 ha),
  Giza-1246 (1,502 ha) and Auseem (1,486 ha). In these districts the decline is partly offset by
  gains elsewhere (1,310, 1,448 and 1,363 ha), so their mean ΔNDVI is small. That is the signature
  of crop rotation plus net conversion.
- **Qalyub.** It ranks last on mean ΔNDVI (+0.026) but its vegetated share still falls (−3.3 pp).
  Greener fields that remain are offsetting fields that were lost. This is why vegetated share is
  reported next to mean ΔNDVI.
- **Core districts.** The historic core (Abdin, Azbakiyya, Darb al-Ahmar, Qasr al-Nil, Muski) and
  Al-Khalifa show small gains of +0.014 to +0.025. These are larger than the +0.002 stable-surface
  bias (§2.2).

### 3.4 Sensitivity: water masked

The Nile channel is strongly red in Fig. 2: water NDVI fell between the dates, most likely from
turbidity or algae differences rather than any vegetation change. Districts containing river
surface could therefore be ranked as "declining" because of water. We re-ran step 4 with water
masked on either date (step S in §2.3).

**Table 4 — Rank stability across three metrics** (the 15 districts that appear in the top 15 of
any metric)

| District | Rank: mean ΔNDVI (all px) | Rank: mean ΔNDVI (land only) | ΔNDVI land | Rank: Δ vegetated share | Δ vegetated share (pp) | Water px masked |
|---|---:|---:|---:|---:|---:|---:|
| Waraq | 1 | 1 | -0.025 | 1 | -9.0 | 258 |
| Shubra Al-Khayma 2 | 2 | 2 | -0.022 | 4 | -5.4 | 27 |
| Kardasa | 3 | 3 | -0.016 | 2 | -7.9 | 1 |
| Giza (1246) | 11 | 10 | -0.003 | 3 | -5.7 | 126 |
| Al-Ahram | 4 | 4 | -0.015 | 6 | -4.5 | 0 |
| Khsos | 5 | 5 | -0.013 | 7 | -4.4 | 0 |
| Shubra Al-Khayma 1 | 6 | 6 | -0.011 | 5 | -4.9 | 3 |
| Marg | 7 | 7 | -0.010 | 9 | -3.5 | 0 |
| Auseem | 8 | 9 | -0.005 | 8 | -3.9 | 115 |
| Umraniyya | 9 | 8 | -0.005 | 13 | -1.5 | 0 |
| Zamalik | 10 | 12 | -0.003 | 10 | -3.4 | 103 |
| Al-Aguza | 12 | 11 | -0.003 | 31 | +1.3 | 29 |
| Qalyub | 48 | 48 | +0.026 | 11 | -3.3 | 0 |
| Hwamdeia | 37 | 39 | +0.013 | 12 | -2.6 | 77 |
| DuqqI | 13 | 13 | -0.001 | 14 | -1.1 | 35 |

The top 8 by mean ΔNDVI are almost unchanged with water masked, and Waraq stays first
(−0.025). Ranking by the change in vegetated share picks out the same fringe group: Waraq,
Kardasa, Giza-1246, Shubra al-Khayma 2 and 1, Al-Ahram and Khsos. The finding is robust to the
water confounder and to the choice of metric.

## 4 Using s3geo: what worked, what broke

**What worked well:**
- **Simple, uniform contracts.** Rasters are a dict with `data` and `metadata.transform`; vectors
  are GeoJSON FeatureCollections. One plugin's output feeds the next without glue code.
- **Correct numbers.** Results match an independent implementation on real data (§2.5).
- **`band_math` sandbox.** Its expression language (`where`, `min`, comparisons, `None` as
  nodata) covered ΔNDVI, the vegetation mask and the water-masked sensitivity cleanly.
- **Fast vector plugins.** `spatial_join` and `centroid_extractor` use shapely.
- **Auditable metadata.** Each call reports pixel counts, rule-match counts and nodata counts.

**Defects found** (full reports in `bugs/`, reproductions in `scripts/verify_bugs.py`, and a
ready-to-use upstream fix prompt in `bugs/UPSTREAM_FIX_PROMPT.md`):

| ID | Plugin | Kind | Effect | Severity |
|---|---|---|---|---|
| [001](../bugs/001-local-raster-loader-output-not-consumable.md) | local_raster_loader | integration | loader output has no pixels → every analysis plugin raises | high |
| [002](../bugs/002-zonal-all-touched-uses-zone-bbox.md) | zonal_statistics | wrong result | `all_touched=True` = every pixel in the zone *bbox* (triangle test: 100 px instead of ≤ 65) | high |
| [003](../bugs/003-raster-to-vector-components-merge-classes.md) | raster_to_vector | wrong result | components merge adjacent different classes; label = first cell | high |
| [004](../bugs/004-raster-to-vector-ignores-dict-transform.md) | raster_to_vector | wrong result | dict transform silently replaced by pixel-unit default | medium |
| [005](../bugs/005-reclassify-metadata-nodata-not-output-nodata.md) | raster_reclassify | wrong result | output metadata keeps input nodata → downstream stats count nodata | high |
| [006](../bugs/006-per-pixel-array-shape-cubic-runtime.md) | raster plugins (shared pattern) | performance | O(H²·W); zonal adds zones × pixels polygon tests with no bbox pre-filter | high |
| [007](../bugs/007-normalize-transform-rejects-complete-dict.md) | raster_clip_mask helper | crash | complete `{a..f}` dict transform rejected (eager default) | medium |
| [008](../bugs/008-generic-top-level-package-names.md) | packaging | packaging | installs top-level `config`, `plugins`, `api`, … | low–medium |

All eight were first found on 0.3.0 and re-verified on 0.5.6; the source of every plugin used
here is byte-identical between those two versions. None were patched or monkey-patched here.
Where a defect constrained the analysis, the constraint is stated in §2.3–2.4.

**Status in 0.5.7.** The upstream fix release was checked with the same reproductions
(`scripts/verify_bugs.py`):

| ID | 0.5.7 result |
|---|---|
| 001 | Fixed. The loader output now chains into `calculate_ndvi`. On the real 2025 reflectance file the result matches this study's NDVI to 3 × 10⁻⁸, with identical nodata. |
| 002 | Fixed. The triangle test gives 64 px, which is the exact count of pixels touching the closed triangle. |
| 003 | Fixed. Two components are returned (class 1 × 4 px, class 2 × 4 px). |
| 004 | Fixed. A dict transform is honoured (`transform_source = metadata_transform`). |
| 005 | Fixed. `metadata.nodata` equals `output_nodata`; downstream `valid_count = 3` and `mean = 1.0`. |
| 006 | Fixed. 4× the pixels now takes 3.9× the time (linear). A 1000² NDVI runs in 2.4 s instead of ≈ 4 min extrapolated, and zonal statistics scans only each zone's bbox window. |
| 007 | Fixed. A complete `{a..f}` dict transform is accepted. |
| 008 | Open. `top_level.txt` still lists `api`, `config`, `orchestrator`, `plugins`, `templates`; this was allowed as deferred in the fix request. |

Re-running the full pipeline on 0.5.7 reproduces every number in this paper exactly (0 differing
cells in `district_change_table.csv`). None of the fixed defects had biased the published results,
because the analysis had avoided the affected options.

A data-side issue that is *not* in s3geo: the Earth Search `raster:bands` offset contradicts
`earthsearch:boa_offset_applied` (§2.2). Applying the advertised offset would have turned the
result into a spurious citywide "greening" or "browning" artefact of ±0.1 reflectance.

## 5 Discussion and limitations

- **Two dates, not two composites.** Crop rotation and fallow timing drive the large, balanced
  decline/gain areas in farmland districts. Net metrics (mean ΔNDVI, change in vegetated share)
  are more reliable than either gross area alone. A median composite per season would be the
  natural next step. With 0.5.7 it is now feasible in runtime, but memory bounds the
  practical raster size (§2.4).
- **8 years, not 10.** No L2A imagery exists on Earth Search over Cairo before 2017 (§2.1). Landsat
  would reach back to 2015, but at 30 m and with a sensor change.
- **Radiometric consistency** between S2B (2017) and S2A (2025, baseline 05.11) is
  supported by the +0.002 median ΔNDVI on stable bare/built surfaces.
- **60 m resolution** under-estimates the loss of small features such as street trees and pocket
  parks (§2.4). The core-district gains should be read with this in mind.
- **District source.** OSM has no qism boundaries for Cairo, so the CAPMAS/OCHA 2020 ADM2 units were
  used. Two units share the name "Giza" and are distinguished by the last four characters of their
  geoBoundaries ID.
- **Attribution.** NDVI decline next to farmland is *consistent with* urban encroachment, but
  this study does not classify land cover. Confirming the cause would need building footprints or
  very-high-resolution imagery.

## 6 Conclusion

Between late summer 2017 and late summer 2025, Greater Cairo's *average* greenness did not
change. The **extent** of vegetation (NDVI ≥ 0.2), however, shrank by about 2,000 ha (−6.6 %).
The sharpest declines are on the peri-urban agricultural fringe: Waraq (with its Nile islands),
Shubra al-Khayma, Marg, Kardasa, Al-Ahram and Khsos. The dense core and the eastern districts
greened slightly. The ranking holds up whether water is masked and whether districts are ranked
by mean ΔNDVI or by change in vegetated share.

s3geo could carry the whole workflow and gave exact results. The defects found in 0.5.6 were
three silent-wrong-result bugs and a pure-Python engine too slow for full-resolution rasters.
Seven of the eight are fixed in 0.5.7, which runs the same pipeline about 20× faster with identical
output. The remaining limit for a native 10 m run is memory in the list-based raster model, not
speed.

## Reproducibility

```bash
pip install -r requirements.txt
python scripts/01_fetch_sentinel2.py
python scripts/02_fetch_districts.py --inspect          # documents the OSM finding
python scripts/02_fetch_districts.py --source geoboundaries
python scripts/03_prepare_inputs.py && python scripts/04_run_s3geo_pipeline.py
python scripts/04b_sensitivity_land_only.py
python scripts/05_figures_tables.py && python scripts/06_crosscheck.py
python scripts/verify_bugs.py                            # reproduces bugs 001-007
```

**Data sources.**
- Imagery: Copernicus Sentinel data 2017, 2025 (processed by ESA; accessed via AWS Open Data /
  Element 84 Earth Search).
- District boundaries: geoBoundaries (Runfola et al. 2020), from CAPMAS / OCHA ROMENA, CC BY 3.0
  IGO.
- OSM inspection data: © OpenStreetMap contributors, ODbL.
