"""make_figures.py — Generate every thesis figure from the frozen data.
"""
import textwrap
import csv, json, os, collections
from datetime import date

DATE = date.today().isoformat()
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, PathPatch
from matplotlib.path import Path
from matplotlib.ticker import MultipleLocator, MaxNLocator

OUT = "thesis_latex/figures"
os.makedirs(OUT, exist_ok=True)

# ============================ shared style ==================================
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"          # blue, orange, aqua
SEQ = ["#eaf1fb", "#c3d9f4", "#8fbaea", "#5b9ae0", "#2a78d6", "#1d5497"]  # one hue
INK, INK2, MUTED, FAINT = "#0b0b0b", "#52514e", "#b8b7b2", "#e8e7e3"

W = 5.9                       # the one figure width, in inches
H = {"xs": 2.2, "s": 2.6, "m": 3.0, "l": 3.4, "xl": 3.9}   # the height ladder

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "sans-serif"], "font.size": 8.5,
    "axes.edgecolor": MUTED, "axes.linewidth": 0.6, "axes.labelcolor": INK2,
    "axes.titlesize": 8.5, "axes.titlecolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "xtick.major.size": 0, "ytick.major.size": 0,
    "text.color": INK, "figure.dpi": 200, "savefig.bbox": "tight",
    "legend.frameon": False, "legend.fontsize": 7.8, "legend.handlelength": 1.2,
})

def style(ax, xgrid=False, nogrid=False):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(MUTED); ax.spines["bottom"].set_color(MUTED)
    if not nogrid:
        ax.grid(axis="x" if xgrid else "y", color=MUTED, lw=0.5, alpha=0.5)
    ax.set_axisbelow(True)

def legend_above(ax, ncol=3, **kw):
    ax.legend(ncol=ncol, loc="lower left", bbox_to_anchor=(0, 1.0), **kw)

def new(h="s"):
    return plt.subplots(figsize=(W, H[h]))

# rounded bar marks ------------------------------------------------------------
# Mark spec: "4px rounded data-end, square at the baseline." A bar container's
# Rectangle patches are replaced with a PathPatch that is square where it meets
# the baseline (x=0 for barh, y=0 for bar) and rounded at the tip. Not used for
# stacked bars (bottom=/left= continuations) - those use the surface-gap
# convention (a plain edge between touching segments) instead of rounding an
# internal join.
def _radius_in_data_units(ax, radius_pt):
    fig = ax.figure
    fig.canvas.draw()
    px_per_pt = fig.dpi / 72.0
    r_px = radius_pt * px_per_pt
    p0 = ax.transData.transform((0, 0))
    px1 = ax.transData.transform((1, 0))
    py1 = ax.transData.transform((0, 1))
    return (r_px / abs(px1[0] - p0[0]), r_px / abs(py1[1] - p0[1]))

def _rounded_hbar_path(x0, y0, w, h, rx, ry):
    sign = 1 if w >= 0 else -1
    length = abs(w)
    ry = max(0, min(ry, h / 2)); rx = max(0, min(rx, length))
    x_tip = x0 + w
    y_bot, y_top, y_mid = y0, y0 + h, y0 + h / 2
    if length <= 0:
        return Path([(x0, y0)], [Path.MOVETO])
    verts = [(x0, y_bot), (x_tip - sign * rx, y_bot), (x_tip, y_bot), (x_tip, y_mid),
             (x_tip, y_top), (x_tip - sign * rx, y_top), (x0, y_top), (x0, y_bot)]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3,
             Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY]
    return Path(verts, codes)

def _rounded_vbar_path(x0, y0, w, h, rx, ry):
    sign = 1 if h >= 0 else -1
    length = abs(h)
    rx = max(0, min(rx, w / 2)); ry = max(0, min(ry, length))
    y_tip = y0 + h
    x_l, x_r, x_mid = x0, x0 + w, x0 + w / 2
    if length <= 0:
        return Path([(x0, y0)], [Path.MOVETO])
    verts = [(x_l, y0), (x_l, y_tip - sign * ry), (x_l, y_tip), (x_mid, y_tip),
             (x_r, y_tip), (x_r, y_tip - sign * ry), (x_r, y0), (x_l, y0)]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3,
             Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY]
    return Path(verts, codes)

def _round_bars(ax, bar_container, radius_pt, horiz):
    # The container's label (used by ax.legend()'s auto-handle lookup) lives on
    # the container, not the individual rectangles, but the legend handle for a
    # BarContainer borrows its first patch's visibility -- hiding that patch
    # silently blanks the legend swatch. So: move the label onto the first
    # replacement patch instead of leaving it on the now-hidden rectangle.
    rx, ry = _radius_in_data_units(ax, radius_pt)
    patches = list(bar_container.patches) if hasattr(bar_container, "patches") else list(bar_container)
    label = bar_container.get_label() if hasattr(bar_container, "get_label") else None
    if label and not label.startswith("_"):
        bar_container.set_label("_nolegend_")
    label_used = False
    for rect in patches:
        x0, y0, w, h = rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height()
        if abs(w) < 1e-12 and abs(h) < 1e-12:
            continue  # zero-size legend-proxy bar; leave as is
        fc, ec, lw, zorder = rect.get_facecolor(), rect.get_edgecolor(), rect.get_linewidth(), rect.get_zorder()
        rect.set_visible(False)
        path = (_rounded_hbar_path if horiz else _rounded_vbar_path)(x0, y0, w, h, rx, ry)
        new_label = None
        if label and not label_used:
            new_label, label_used = label, True
        ax.add_patch(PathPatch(path, facecolor=fc, edgecolor=ec if lw else "none", lw=lw,
                                zorder=zorder, label=new_label))
    return bar_container

def round_barh(ax, bar_container, radius_pt=2.2):
    return _round_bars(ax, bar_container, radius_pt, True)

def round_bar(ax, bar_container, radius_pt=2.2):
    return _round_bars(ax, bar_container, radius_pt, False)

def save(fig, name):
    src, sec, what = FIGMETA.get(name, ("--", "?", ""))
    fig.savefig(os.path.join(OUT, name), metadata={
        "Title": what or name,
        "Author": "Sevim Bozkurt",
        "Subject": f"generated by make_figures.py on {DATE} from: {src} | thesis section {sec}",
        "Creator": "make_figures.py (thesis_sparql)",
        "Keywords": "text-to-SPARQL; Wikidata; Instruct-to-SPARQL",
    })
    plt.close(fig)
    MANIFEST.append(dict(figure=name, thesis_section=sec, shows=what, source_data=src))
    print(f"  {name}")

def rows(p): return list(csv.DictReader(open(p)))

# ============================ provenance ====================================
# Every figure records where its numbers came from, so a reader (or an examiner)
# can trace any picture in the thesis back to a file on disk. This table is the
# single source of truth; save() stamps it into the PDF metadata and emits
# results_tables/figure_manifest.csv at the end of the run.
FIGMETA = {
 # diagrams -- schematic, no data source
 "fig_pipeline.pdf":            ("--", "4.2", "pipeline architecture and the two evaluation conditions"),
 "fig_method.pdf":              ("--", "4.1", "the four moves of stage-wise diagnostic evaluation"),
 "fig_cascade_mechanism.pdf":   ("--", "4.5", "the execution-guided cascade"),
 "fig_wikidata_model.pdf":      ("--", "2.2", "the Wikidata statement model"),
 "fig_example_kg.pdf":          ("--", "1.1", "a fragment of Wikidata around the question who directed Inception"),

 "fig_empty_rate.pdf":          ("results_tables/empty_result_rate.csv", "6.2",
                                 "how often each system returns nothing, against its accuracy"),
 "fig_label_failures.pdf":      ("results_tables/label_failure_taxonomy.csv", "6.5",
                                 "labels the Wikidata search index cannot find, by category and backbone"),
 "fig_linker_ci.pdf":           ("results_tables/linker_confidence.csv", "6.4",
                                 "linking F1 with bootstrap confidence intervals (B = 2,000)"),
 "fig_splits.pdf":              ("data/test.json; data/official_test.json", "5.1", "the two-split design"),
 "fig_groundtruth.pdf":         ("--", "5.4", "deriving linking ground truth from the benchmark"),
 # data figures
 "fig_main_comparison.pdf":     ("results_tables/common_subset_metrics.csv", "6.2", "frozen models with and without the pipeline"),
 "fig_stage_funnel.pdf":        ("outputs/results_e2e_clean.csv", "6.3", "stage-wise outcomes by complexity"),
 "fig_gap_decomposition.pdf":   ("results_tables/gap_decomposition.csv", "6.3", "failure types in the annotated sample of 30 failing rows"),
 "fig_linker_comparison.pdf":   ("results_tables/linker_comparison.csv", "6.4", "entity linking F1, four paradigms, both splits"),
 "fig_linker_pr.pdf":           ("results_tables/linker_comparison.csv", "6.4", "precision-recall signature per paradigm"),
 "fig_linker_complexity.pdf":   ("results_tables/linker_comparison.csv", "6.4", "linking F1 by query complexity"),
 "fig_backbone.pdf":            ("results_tables/linker_comparison.csv; official_comparison.csv", "6.5", "backbone dependence differs by stage"),
 "fig_error_taxonomy.pdf":      ("annotations/annotation_clean.csv", "6.6", "error taxonomy, overall and by complexity"),
 "fig_constructs.pdf":          ("results_tables/construct_analysis.csv", "6.6", "construct usage, gold against all runs"),
 "fig_construct_agreement.pdf": ("results_tables/construct_analysis.csv", "6.6", "agreement with gold on construct use"),
 "fig_structural_predictors.pdf": ("results_tables/complexity_features.csv", "6.6", "gold-query features against achieved accuracy"),
 "fig_cross_model_agreement.pdf": ("results_tables/agreement_analysis.csv", "6.6", "cross-model agreement and hard-set features"),
 "fig_prompt_arms.pdf":         ("results_tables/significance_jaccard_entity.csv", "6.7", "prompt arms: accuracy and effect with CIs"),
 "fig_idiom_behaviour.pdf":     ("results_tables/construct_analysis.csv", "6.7", "what the idiom prompt changes in generated queries"),
 "fig_cascade.pdf":             ("results_tables/consensus_selection.csv", "6.8", "selection strategies over diverse generations"),
 "fig_cascade_fallback.pdf":    ("results_tables/consensus_robustness.txt", "6.8", "where the fallback fires and what it recovers"),
 "fig_frozen_vs_finetuned.pdf": ("official_comparison.py; results_tables/official_comparison.csv", "6.9", "frozen and fine-tuned systems, official split"),
 "fig_memorisation.pdf":        ("results_tables/memorisation_frontier.csv", "6.10", "structural similarity of generated queries"),
 "fig_wdql.pdf":                ("results_tables/wdql_construct_prevalence.csv", "6.10", "construct prevalence vs real query logs"),
 "fig_wdql_bysize.pdf":         ("results_tables/wdql_construct_prevalence.csv", "6.10", "construct prevalence at matched query size"),
 "fig_candidate_ceiling.pdf":   ("candidates.json; data/candidates_expanded.json; data/gold_links.json", "7.6", "candidate ceiling before and after pool repair"),
 "fig_label_failures.pdf":      ("results_tables/label_failure_taxonomy.csv", "6.5", "what the open model gets wrong when naming things"),
 "fig_empty_rate.pdf":          ("results_tables/empty_result_rate.csv", "6.2", "empty-result rate against accuracy"),
 "fig_linker_ci.pdf":           ("results_tables/linker_confidence.csv", "6.4", "linker F1 with bootstrap confidence intervals"),
}
MANIFEST = []


# diagram helpers -------------------------------------------------------------
def canvas(h="s"):
    fig, ax = plt.subplots(figsize=(W, H[h]))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")
    return fig, ax

def box(ax, x, y, w, h, text, fc="white", ec=MUTED, tc=INK, fs=7.6, lw=0.8, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=2",
                                fc=fc, ec=ec, lw=lw, zorder=3))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=tc, zorder=4, linespacing=1.35,
                fontweight="bold" if bold else "normal")

def arrow(ax, p1, p2, color=INK2, lw=0.9, astyle="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=astyle, mutation_scale=8,
                                 color=color, lw=lw, linestyle=ls,
                                 shrinkA=1, shrinkB=1, zorder=2))

print("writing figures:")
print(" diagrams:")

# ============================ D1 pipeline ===================================
fig, ax = canvas("m")
stages = ["Question", "Generate\nlabelled query", "Parse\nlabels", "Retrieve\ncandidates",
          "Disambiguate", "Substitute", "Execute\n& score"]
n = len(stages); bw, gap = 12.5, 1.3
x0 = (100 - (n * bw + (n - 1) * gap)) / 2
ys, bh = 52, 20
for i, s_ in enumerate(stages):
    x = x0 + i * (bw + gap)
    box(ax, x, ys, bw, bh, s_, fc=FAINT if i in (0, n - 1) else "white", fs=6.5)
    if i:
        arrow(ax, (x - gap, ys + bh / 2), (x, ys + bh / 2))
gx = x0 + 1 * (bw + gap); dx = x0 + 4 * (bw + gap)
ax.add_patch(Rectangle((gx - 1.0, ys - 1.6), (dx - gx) + bw + 2.0, bh + 3.2,
                       fc="none", ec=S2, lw=0.9, ls=(0, (3, 2)), zorder=1))
ax.text(gx - 1.0, ys + bh + 3.0, "varied stage — every other stage held fixed",
        fontsize=6.8, color=S2, va="bottom")
by, bhh = 20, 15
box(ax, gx, by, (dx - gx) + bw, bhh,
    "gold-label condition\nthe benchmark's annotated query supplies the labels,\n"
    "so only disambiguation is exercised", fc="#fdf1ea", ec=S2, fs=6.6)
arrow(ax, (gx + ((dx - gx) + bw) / 2, by + bhh), (gx + ((dx - gx) + bw) / 2, ys), color=S2, ls=(0, (3, 2)))
ax.text(50, 92, "End-to-end condition", ha="center", fontsize=8.4, color=INK, fontweight="bold")
ax.text(50, 85, "the model generates the labelled query itself; the same linking stages run on top",
        ha="center", fontsize=6.9, color=INK2)
ax.set_ylim(14, 100)
save(fig, "fig_pipeline.pdf")

# ============================ D2 Wikidata model =============================
fig, ax = canvas("m")
box(ax, 2, 40, 21, 16, "item\nwd:Q25188", fc=FAINT, fs=7.0)
box(ax, 39, 40, 22, 16, "statement node\np:P57 / ps:P57", fc="white", ec=S1, fs=7.0)
box(ax, 76, 58, 22, 13, "value\nwd:Q25191", fc="white", fs=7.0)
box(ax, 76, 39, 22, 13, "qualifier\npq:", fc="white", ec=S3, fs=7.0)
box(ax, 76, 18, 22, 13, "value node (quantities)\npsv: amount + unit", fc="white", ec=S3, fs=6.2)
arrow(ax, (23, 48), (39, 48), color=S1); ax.text(31, 50, "p:", ha="center", fontsize=7.0, color=S1)
arrow(ax, (61, 50), (76, 62), color=S1); ax.text(66.5, 58.5, "ps:", fontsize=6.8, color=S1)
arrow(ax, (61, 46), (76, 45), color=S3); ax.text(66.5, 46.5, "pq:", fontsize=6.8, color=S3)
arrow(ax, (61, 42), (76, 26), color=S3); ax.text(64, 32, "psv:", fontsize=6.8, color=S3)
arrow(ax, (12, 56), (75.5, 66), color=S2, ls=(0, (4, 2)))
ax.text(49, 78, "wdt:P57  —  the truthy shortcut, bypassing the statement node",
        ha="center", fontsize=7.2, color=S2)
ax.text(2, 6, "The shortcut is always syntactically available. A model that does not know when a richer\n"
              "construct is required produces a valid query that answers a different question.",
        fontsize=6.9, color=INK2, va="bottom", linespacing=1.6)
ax.set_ylim(2, 84)
save(fig, "fig_wikidata_model.pdf")

# ============================ D0 example graph ==============================
fig, ax = canvas("xs")
box(ax, 6, 36, 24, 28, "Inception\nwd:Q25188", fc=FAINT, fs=7.4)
box(ax, 62, 64, 30, 28, "Christopher Nolan\nwd:Q25191", fc="white", ec=S1, lw=1.1, fs=7.4)
box(ax, 62, 8, 30, 28, "film\nwd:Q11424", fc="white", fs=7.4)
arrow(ax, (30, 56), (62, 78), color=S1, lw=1.1)
ax.text(44, 74, "director\nwdt:P57", ha="center", fontsize=7.0, color=S1, linespacing=1.3)
arrow(ax, (30, 44), (62, 22), color=INK2)
ax.text(40, 17, "instance of\nwdt:P31", ha="center", fontsize=7.0, color=INK2, linespacing=1.3)
save(fig, "fig_example_kg.pdf")

# ============================ D3 ground truth ===============================
fig, ax = canvas("m")
box(ax, 1, 63, 46, 27, "gold query\n\nSELECT ?f WHERE {\n  ?f  wdt:P57  wd:Q25191 . }", fc=FAINT, fs=6.8)
box(ax, 53, 63, 46, 27, "annotated query\n\nSELECT ?f WHERE {\n  ?f  wdt:[property:director]\n"
                        "      wd:[entity:Christopher Nolan] . }", fc=FAINT, fs=6.8)
for i, lab in enumerate(["P57  ↔  [property:director]", "Q25191  ↔  [entity:Christopher Nolan]"]):
    box(ax, 16, 42 - i * 11, 68, 8.5, lab, fc="white", ec=S1, fs=7.0)
arrow(ax, (23, 63), (40, 50.5), color=S1); arrow(ax, (77, 63), (60, 50.5), color=S1)
ax.text(50, 20, "The two forms differ only by substitution, so the k-th bracketed label corresponds\n"
                "positionally to the k-th identifier. Walking both in parallel recovers a mention-level\n"
                "ground truth for 547 of 567 rows without any new annotation.",
        ha="center", va="top", fontsize=6.9, color=INK2, linespacing=1.6)
ax.set_ylim(2, 92)
save(fig, "fig_method_groundtruth_tmp.pdf") if False else save(fig, "fig_groundtruth.pdf")

# ============================ D4 the method =================================
fig, ax = canvas("s")
moves = [("1", "Derive", "Obtain ground truth for an intermediate stage from the benchmark data."),
         ("2", "Isolate", "Keep all other stages fixed and vary only the stage being tested. "
                          "Use an upper bound when gold output is available."),
         ("3", "Compare", "Compare the conditions and check the findings against evidence "
                          "outside the sample."),
         ("4", "Intervene", "Change the suspected cause and test whether the outcome changes. "
                            "A failed intervention is evidence against that explanation.")]
bw, gap = 21.5, 4.0
x0 = (100 - (4 * bw + 3 * gap)) / 2
for i, (num, head, body) in enumerate(moves):
    x = x0 + i * (bw + gap)
    box(ax, x, 12, bw, 60, "", fc="white")
    ax.text(x + bw / 2, 63, num, ha="center", fontsize=12, color=SEQ[3], fontweight="bold")
    ax.text(x + bw / 2, 55, head, ha="center", fontsize=8.0, color=INK, fontweight="bold")
    ax.text(x + bw / 2, 31, textwrap.fill(body, 21), ha="center", va="center", fontsize=6.0,
            color=INK2, linespacing=1.45)
    if i:
        arrow(ax, (x - gap, 42), (x, 42))
ax.text(50, 84, "Stage-wise diagnostic evaluation", ha="center", fontsize=9.0, color=INK, fontweight="bold")
ax.set_ylim(8, 94)
save(fig, "fig_method.pdf")

# ============================ D5 the two splits =============================
tr = json.load(open("data/test.json")); off = json.load(open("data/official_test.json"))
cw = collections.Counter(r["complexity"] for r in tr)
co = collections.Counter(r["complexity"] for r in off)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, H["m"]), gridspec_kw={"width_ratios": [1.0, 1.25]})
cats = ["simple", "medium", "complex"]; y = [2, 1, 0]; h = 0.34
round_barh(a1, a1.barh([v + h / 2 for v in y], [cw[c] for c in cats], h, color=S1, label=f"working (n={len(tr)})", zorder=3))
round_barh(a1, a1.barh([v - h / 2 for v in y], [co[c] for c in cats], h, color=S2, label=f"official (n={len(off)})", zorder=3))
for v, c in zip(y, cats):
    a1.text(cw[c] + 8, v + h / 2, str(cw[c]), va="center", fontsize=7, color=INK2)
    a1.text(co[c] + 8, v - h / 2, str(co[c]), va="center", fontsize=7, color=INK2)
style(a1, xgrid=True); a1.set_yticks(y); a1.set_yticklabels(cats, fontsize=7.6)
a1.set_xlim(0, 400); a1.set_xlabel("test rows"); legend_above(a1, ncol=1, fontsize=7)
a2.axis("off"); a2.set_xlim(0, 100); a2.set_ylim(0, 100)
box(a2, 0, 54, 100, 40, "Working split: for detailed analysis\n\n" + textwrap.fill(
    "Stratified by complexity with a fixed seed. Used for the stage-wise analysis, "
    "error taxonomy, prompt experiments, and cascade.", 52), fc="#eaf1fb", ec=S1, fs=6.7)
box(a2, 0, 6, 100, 40, "Official split: for comparison\n\n" + textwrap.fill(
    "The benchmark authors’ original split. Used to compare with their published systems "
    "and to replicate the linking results, checking that the findings are not split-dependent.", 52),
    fc="#fdf1ea", ec=S2, fs=6.7)
fig.tight_layout(w_pad=1.0); save(fig, "fig_splits.pdf")

# ============================ D6 cascade mechanism ==========================
fig, ax = canvas("s")
box(ax, 1, 46, 16, 20, "question", fc=FAINT, fs=7.2)
box(ax, 23, 46, 20, 20, "generate under\nprompt $p_i$", fc="white", fs=7.0)
box(ax, 49, 46, 17, 20, "execute", fc="white", fs=7.2)
box(ax, 80, 62, 19, 16, "accept", fc="#eaf7f1", ec=S3, fs=7.2)
box(ax, 80, 28, 19, 16, "next prompt\n$p_{i+1}$", fc="#fdf1ea", ec=S2, fs=7.0)
arrow(ax, (17, 56), (23, 56)); arrow(ax, (43, 56), (49, 56))
arrow(ax, (66, 60), (80, 69), color=S3); ax.text(67.5, 68, "non-empty", fontsize=6.6, color=S3)
arrow(ax, (66, 52), (80, 39), color=S2); ax.text(66.5, 47.0, "empty / error", fontsize=6.6, color=S2)
arrow(ax, (89.5, 28), (33, 20), color=S2, ls=(0, (3, 2)), astyle="-")
arrow(ax, (33, 20), (33, 46), color=S2, ls=(0, (3, 2)))
ax.text(50, 90, "Execution-guided cascade", ha="center", fontsize=8.8, color=INK, fontweight="bold")
ax.text(50, 8, "Only empty or erroneous results are replaced, so the cascade cannot reduce\n"
                "accuracy on the strict fair set.",
        ha="center", va="top", fontsize=6.9, color=INK2, linespacing=1.6)
ax.set_ylim(-4, 96)
save(fig, "fig_cascade_mechanism.pdf")

print(" data figures:")

# ============================ F1 main comparison ============================
mc = rows("results_tables/common_subset_metrics.csv")
fig, ax = new("l")
names = [r["Approach"] for r in mc]
y = list(range(len(names)))[::-1]; h = 0.36
round_barh(ax, ax.barh([v + h / 2 for v in y], [float(r["Pooled (%)"]) for r in mc], h, color=MUTED, label="pooled", zorder=3))
round_barh(ax, ax.barh([v - h / 2 for v in y], [float(r["Entity-level (%)"]) for r in mc], h, color=S1, label="entity-level", zorder=3))
for v, r in zip(y, mc):
    ax.text(float(r["Entity-level (%)"]) + 1.2, v - h / 2, f'{float(r["Entity-level (%)"]):.1f}',
            va="center", fontsize=6.9, color=INK2)
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels(names, fontsize=7.6)
ax.set_xlabel("strict fair Jaccard (%), common subset n = 316"); ax.set_xlim(0, 112)
legend_above(ax, ncol=2); save(fig, "fig_main_comparison.pdf")

# ============================ F2 stage funnel ===============================
stages = ["Labelled query\ngenerated", "Fully\nlinked", "Executed", "Answer correct\n(entity Jaccard)"]
data = {"simple": [100.0, 94.7, 92.1, 32.7], "medium": [100.0, 93.7, 89.2, 31.1],
        "complex": [100.0, 91.9, 87.0, 21.9]}
fig, ax = new("s")
x = range(len(stages)); w = 0.26
for i, (k, c) in enumerate([("simple", S1), ("medium", S2), ("complex", S3)]):
    round_bar(ax, ax.bar([xi + (i - 1) * w for xi in x], data[k], w * 0.92, color=c, label=k, zorder=3))
for i, k in enumerate(["simple", "medium", "complex"]):
    for xi, val in zip(x, data[k]):
        ax.text(xi + (i - 1) * w, val + 2, f"{val:.0f}" if val == 100 else f"{val:.1f}",
                ha="center", va="bottom", fontsize=6.0, color=INK2)
style(ax); ax.set_xticks(list(x)); ax.set_xticklabels(stages)
ax.set_ylabel("% of rows"); ax.set_ylim(0, 112); ax.yaxis.set_major_locator(MultipleLocator(25))
legend_above(ax); save(fig, "fig_stage_funnel.pdf")

# ============================ linker data ===================================
lk = rows("results_tables/linker_comparison.csv")
LORDER = ["Reasoning over candidates|Claude Opus 4.8", "Reasoning over candidates|Qwen2.5-14B-Instruct",
          "Reasoning over candidates|Qwen2.5-7B-Instruct", "GLiNKER gliner-linker-large-v1.0|-",
          "ELQ elq_wiki_large|-", "ReFinED questions_model|-", "First search result|-"]
LSHORT = ["Reasoning (Opus 4.8)", "Reasoning (Qwen 14B)", "Reasoning (Qwen 7B)",
          "GLiNKER (bi-encoder)", "ELQ (fine-tuned)", "ReFinED (fine-tuned)", "First search result"]
ent = {s: {} for s in ("working", "official")}
for r in lk:
    if r["Mentions"] == "entity":
        ent[r["Split"]][f'{r["Linker"]}|{r["Backbone"]}'] = r

# F3 linker F1, both splits
fig, ax = new("m")
y = range(len(LORDER)); h = 0.36
for i, (sp, c) in enumerate([("working", S1), ("official", S2)]):
    ys = [v + (0.5 - i) * h for v in y]
    xs = [float(ent[sp][k]["F1 (%)"]) if k in ent[sp] else 0 for k in LORDER]
    round_barh(ax, ax.barh(ys, xs, h * 0.9, color=c, label=f"{sp} split", zorder=3))
    for yy, xx in zip(ys, xs):
        if xx: ax.text(xx + 1, yy, f"{xx:.1f}", va="center", fontsize=7, color=INK2)
style(ax, xgrid=True); ax.set_yticks(list(y)); ax.set_yticklabels(LSHORT, fontsize=7.6)
ax.invert_yaxis(); ax.set_xlabel("entity linking F1 (%)"); ax.set_xlim(0, 108)
legend_above(ax, ncol=2); save(fig, "fig_linker_comparison.pdf")

# F4 precision-recall signature
# 6 series: legend rather than direct labels, and a distinct marker per system so
# identity is never carried by colour alone.
MARK = ["o", "s", "D", "^", "v", "P", "X"]
fig, ax = new("m")
for f in (25, 50, 75):
    pts = []
    for x in range(3, 101):
        den = 2 * x - f
        if den > 0:
            v = (f * x) / den
            if 0 < v <= 100: pts.append((x, v))
    ax.plot([q[0] for q in pts], [q[1] for q in pts], color=MUTED, lw=0.5, ls=(0, (2, 2)), zorder=1)
    if pts: ax.text(pts[-1][0] - 2, pts[-1][1] + 2, f"F1 {f}", fontsize=6.4, color=MUTED, ha="right")
for k, lab, mk in zip(LORDER, LSHORT, MARK):
    if k not in ent["working"]: continue
    r = ent["working"][k]
    c = MUTED if "First search" in lab else (S1 if "Reasoning" in lab else (S3 if "GLiNKER" in lab else S2))
    ax.scatter([float(r["R (%)"])], [float(r["P (%)"])], s=34, color=c, marker=mk,
               zorder=4, linewidths=0, label=lab)
style(ax, nogrid=True); ax.grid(color=MUTED, lw=0.4, alpha=0.4)
ax.set_xlabel("recall (%)"); ax.set_ylabel("precision (%)")
ax.set_xlim(0, 108); ax.set_ylim(0, 112)
legend_above(ax, ncol=3, fontsize=7)
save(fig, "fig_linker_pr.pdf")

# F5 linker F1 by complexity — the reversal
fig, ax = new("s")
cxcols = ["F1 simple", "F1 medium", "F1 complex"]
# complexity is ordinal, not continuous: grouped bars on a light-to-dark ramp
cxshade = ["#86b6ef", "#2a78d6", "#104281"]
cxrows = [(lab, [float(ent["working"][k][c]) for c in cxcols])
        for k, lab in zip(LORDER, LSHORT) if k in ent["working"]]
bh = 0.24
for j, (cxname, shade) in enumerate(zip(["simple", "medium", "complex"], cxshade)):
    ys = [i + (j - 1) * (bh + 0.03) for i in range(len(cxrows))]
    round_barh(ax, ax.barh(ys, [v[j] for _, v in cxrows], height=bh, color=shade, label=cxname, zorder=3))
style(ax); ax.set_yticks(range(len(cxrows))); ax.set_yticklabels([lab for lab, _ in cxrows])
ax.invert_yaxis()
ax.set_xlabel("entity linking F1 (%)"); ax.set_xlim(0, 108)
legend_above(ax, ncol=3, fontsize=7)
save(fig, "fig_linker_complexity.pdf")

# F6 backbone dependence
fig, ax = new("s")
pairs = [("Disambiguation\n(entity F1)", 97.7, 94.9), ("Full pipeline\n(fully linked, %)", 92.1, 49.7),
         ("Full pipeline\n(pooled Jaccard)", 23.4, 4.8)]
x = range(len(pairs)); w = 0.3
round_bar(ax, ax.bar([v - w / 2 for v in x], [p[1] for p in pairs], w * 0.92, color=S1, label="frontier model", zorder=3))
round_bar(ax, ax.bar([v + w / 2 for v in x], [p[2] for p in pairs], w * 0.92, color=S2, label="open 14B", zorder=3))
for xi, (_, a, b) in zip(x, pairs):
    if a - b > 8:
        arrow(ax, (xi + w / 2, a), (xi + w / 2, b), astyle="<|-|>", lw=0.7)
    ax.text(xi + w / 2 + 0.08, (a + b) / 2 if a - b > 10 else a + 6, f"{a - b:.1f} pt",
            fontsize=7.2, color=INK2, va="center", ha="left")
style(ax); ax.set_xticks(list(x)); ax.set_xticklabels([p[0] for p in pairs])
ax.set_ylabel("score"); ax.set_ylim(0, 118); legend_above(ax, ncol=2)
save(fig, "fig_backbone.pdf")

# ============================ construct data ================================
txt = open("results_tables/construct_analysis.csv").read()
use_rows = list(csv.DictReader(txt.split("AGREEMENT WITH GOLD")[0].strip().splitlines()[1:]))
agr_rows = list(csv.DictReader(txt.split("AGREEMENT WITH GOLD")[1].strip().splitlines()[1:]))
CONS = [r["construct"] for r in use_rows]
MODELS = [c for c in use_rows[0] if c not in ("construct", "GOLD", None)]

# F7 construct usage
fig, ax = new("l")
y = list(range(len(CONS)))[::-1]
for yi, r in zip(y, use_rows):
    v = [int(r[m]) for m in MODELS]
    ax.plot([min(v), max(v)], [yi, yi], color=MUTED, lw=3, solid_capstyle="round", zorder=2)
    ax.scatter(v, [yi] * len(v), s=9, color=S1, zorder=3, linewidths=0)
ax.scatter([int(r["GOLD"]) for r in use_rows], y, marker="|", s=170, color=INK,
           zorder=4, linewidths=1.6, label="gold queries")
ax.scatter([], [], s=9, color=S1, label="generated (11 runs)")
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels(CONS, fontsize=7.6)
ax.set_xlabel("number of queries using the construct (of 567)")
legend_above(ax, ncol=2); save(fig, "fig_constructs.pdf")

# F8 construct agreement heatmap (sequential, one hue)
AM = [c for c in agr_rows[0] if c not in ("construct", None)]
fig, ax = new("l")
vals = [[float(r[m]) for m in AM] for r in agr_rows]
im = ax.imshow(vals, cmap=matplotlib.colors.LinearSegmentedColormap.from_list("seq", SEQ),
               aspect="auto", vmin=0, vmax=65)
ax.set_xticks(range(len(AM)))
ax.set_xticklabels([m.replace("zero-shot ", "zs ").replace("few-shot ", "fs ").replace(" (labelled)", "")
                    for m in AM], rotation=35, ha="right", fontsize=6.7)
ax.set_yticks(range(len(agr_rows))); ax.set_yticklabels([r["construct"] for r in agr_rows], fontsize=7.2)
for i, row in enumerate(vals):
    for j, v in enumerate(row):
        ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=5.9,
                color="white" if v > 40 else INK2)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
cb = fig.colorbar(im, ax=ax, fraction=0.022, pad=0.015)
cb.set_label("agreement with gold, F1", fontsize=7.2); cb.ax.tick_params(labelsize=6.8, length=0)
cb.outline.set_visible(False)
save(fig, "fig_construct_agreement.pdf")

# F9 idiom behavioural effect
fig, ax = new("m")
sel = [r for r in use_rows if r["construct"] in
       ["subclass closure (P279*)", "statement node (p:)", "qualifier (pq:)",
        "value node (psv:)", "aggregation (GROUP BY)", "LIMIT"]]
y = list(range(len(sel)))[::-1]
for yi, r in zip(y, sel):
    b, idm, g = int(r["pipeline (labelled)"]), int(r["idiom prompt (labelled)"]), int(r["GOLD"])
    ax.plot([b, idm], [yi, yi], color=MUTED, lw=1.2, zorder=2)
    ax.scatter([b], [yi], s=26, color=MUTED, zorder=3, linewidths=0)
    ax.scatter([idm], [yi], s=26, color=S1, zorder=4, linewidths=0)
    ax.scatter([g], [yi], marker="|", s=150, color=INK, zorder=5, linewidths=1.5)
ax.scatter([], [], s=26, color=MUTED, label="baseline prompt")
ax.scatter([], [], s=26, color=S1, label="+ idiom rules")
ax.scatter([], [], marker="|", s=150, color=INK, linewidths=1.5, label="gold")
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["construct"] for r in sel], fontsize=7.6)
ax.set_xlabel("number of queries using the construct (of 567)")
legend_above(ax, ncol=3); save(fig, "fig_idiom_behaviour.pdf")

# ============================ F10 error taxonomy ============================
ann = [r for r in rows("annotations/annotation_clean.csv") if r.get("error_category", "").strip()]
cats2 = collections.Counter(r["error_category"].strip() for r in ann)
order = [c for c, _ in cats2.most_common()]
bycx = {c: collections.Counter(r["error_category"].strip() for r in ann if r["complexity"] == c)
        for c in ["simple", "medium", "complex"]}
def catcol(c):
    if c in ("structure", "triple_flip"): return S1
    if c in ("wrong_property", "wrong_entity", "unresolved"): return S2
    return MUTED
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, H["s"]), gridspec_kw={"width_ratios": [1, 1.1]})
y = list(range(len(order)))[::-1]
round_barh(a1, a1.barh(y, [cats2[c] for c in order], 0.62, color=[catcol(c) for c in order], zorder=3))
for yi, c in zip(y, order):
    a1.text(cats2[c] + 0.25, yi, f"{cats2[c]}", va="center", fontsize=7.2, color=INK2)
style(a1, xgrid=True); a1.set_yticks(y); a1.set_yticklabels([c.replace("_", " ") for c in order], fontsize=7.2)
a1.set_xlabel("cases (n = 30)"); a1.set_xlim(0, 16); a1.set_title("All complexities", pad=6)
bot = [0, 0, 0]
for c in order:
    v = [bycx[k][c] for k in ["simple", "medium", "complex"]]
    a2.bar(range(3), v, 0.55, bottom=bot, color=catcol(c), edgecolor="white", lw=0.8, zorder=3)
    bot = [b + x for b, x in zip(bot, v)]
style(a2); a2.set_xticks(range(3))
a2.set_xticklabels(["simple\n(n=5)", "medium\n(n=10)", "complex\n(n=15)"], fontsize=7.4)
a2.set_ylabel("cases"); a2.set_title("By complexity", pad=6)
a2.yaxis.set_major_locator(MaxNLocator(integer=True))
for c, lab in [(S1, "structural"), (S2, "identifier"), (MUTED, "other")]:
    a2.bar(0, 0, color=c, label=lab)
a2.legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.08), fontsize=7)
fig.tight_layout(w_pad=1.8); save(fig, "fig_error_taxonomy.pdf")

# ============================ F11 gap decomposition =========================
gd = [r for r in rows("results_tables/gap_decomposition.csv") if r["run"].startswith("reported")]
fig, ax = new("xs")
y = list(range(len(gd)))[::-1]
for yi, r in zip(y, gd):
    lo, hi, p = float(r["ci_low_pct"]), float(r["ci_high_pct"]), float(r["share_pct"])
    c = S1 if r["group"] == "structural" else (S2 if r["group"] == "identifier" else MUTED)
    ax.plot([lo, hi], [yi, yi], color=c, lw=1.8, solid_capstyle="round", zorder=3)
    ax.scatter([p], [yi], s=26, color=c, zorder=4, linewidths=0)
    ax.text(hi + 1.5, yi, f"{p:.1f}\u202f%", va="center", fontsize=7.2, color=INK2)
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["group"] for r in gd], fontsize=7.6)
ax.set_xlabel("share of the 30 annotated failing rows (%), with 95\u202f% Wilson interval")
ax.set_xlim(0, 80); save(fig, "fig_gap_decomposition.pdf")

# ============================ F12 structural predictors =====================
cf = sorted(rows("results_tables/complexity_features.csv"), key=lambda r: float(r["gap (pp)"]))
fig, ax = new("m")
y = list(range(len(cf)))[::-1]
g = [float(r["gap (pp)"]) for r in cf]
round_barh(ax, ax.barh(y, g, 0.6, color=[S1 if v > 0 else S2 for v in g], zorder=3))
for yi, r, v in zip(y, cf, g):
    ax.text(v + (0.4 if v > 0 else -0.4), yi, f'n={r["n questions with feature"]}',
            va="center", ha="left" if v > 0 else "right", fontsize=6.4, color=INK2)
ax.axvline(0, color=INK2, lw=0.7, zorder=4)
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["feature"] for r in cf], fontsize=7.2)
ax.set_xlabel("accuracy when the gold query has the feature, minus when it does not (pp)")
ax.set_xlim(-18, 16); save(fig, "fig_structural_predictors.pdf")

# ============================ F13 cross-model agreement =====================
blocks = open("results_tables/agreement_analysis.csv").read().strip().split("\n\n")
solved = list(csv.DictReader(blocks[0].splitlines()))
feats = list(csv.DictReader(blocks[1].splitlines()))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, H["m"]), gridspec_kw={"width_ratios": [1, 1.25]})
kk = [int(r["questions solved by k models"]) for r in solved]
cnt = [int(r["count"]) for r in solved]
round_bar(a1, a1.bar(kk, cnt, 0.6, color=[S2] + [SEQ[3]] * (len(kk) - 2) + [S1], zorder=3))
for a, b in zip(kk, cnt):
    a1.text(a, b + 6, str(b), ha="center", fontsize=7.2, color=INK2)
style(a1); a1.set_xlabel("models solving the question"); a1.set_ylabel("questions")
a1.set_ylim(0, 355); a1.set_title("Of 400 strict-set questions", pad=30)
fs = [r for r in feats if r["feature"] in
      ["statement node (p:)", "qualifier (pq:)", "aggregation", "transitive star (*)",
       "alternation (VALUES/UNION)", "OPTIONAL", "FILTER"]]
y = list(range(len(fs)))[::-1]
for yi, r in zip(y, fs):
    hard, easy = float(r["mean in hard set"]), float(r["mean in easy set"])
    a2.plot([easy, hard], [yi, yi], color=MUTED, lw=1.2, zorder=2)
    a2.scatter([easy], [yi], s=24, color=S1, zorder=3, linewidths=0)
    a2.scatter([hard], [yi], s=24, color=S2, zorder=3, linewidths=0)
a2.scatter([], [], s=24, color=S1, label="solved by all four")
a2.scatter([], [], s=24, color=S2, label="solved by none")
style(a2, xgrid=True); a2.set_yticks(y); a2.set_yticklabels([r["feature"] for r in fs], fontsize=7)
a2.set_xlabel("mean occurrences per gold query")
a2.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.01), fontsize=7)
a2.set_title("Query features by difficulty", pad=30)
fig.tight_layout(w_pad=1.6); save(fig, "fig_cross_model_agreement.pdf")

# ============================ F14 prompt arms ===============================
# Rewritten 9 Sep 2026. The previous version hardcoded four arms and three
# comparisons; when X10, X14 and X15 were added the figure silently kept showing
# the old four while the text and the significance table showed six. Everything
# below is now derived from the data, so the figure cannot go stale again.
import statistics as _stats
_strict = {r["index"] for r in rows("data/gold_status_qlever.csv")
           if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}

def _arm(fn):
    out = {}
    for r in rows(fn):
        v = r.get("jaccard_entity", "")
        if v in ("na", "", None) or r.get("row_id") not in _strict:
            continue
        out[r["row_id"]] = float(v)
    return out

ARMS = [("baseline", "outputs/linked_base-qwen.csv"), ("idiom", "outputs/linked_idiom-qwen.csv"),
        ("verbose", "outputs/linked_grounded.csv"),
        ("targeted", "outputs/linked_grounded-targeted.csv"),
        ("profile", "outputs/linked_profile.csv"),
        ("vocabulary", "outputs/linked_constrained.csv"),
        ("both", "outputs/linked_both.csv")]
_d = {n: _arm(f) for n, f in ARMS}
_common = sorted(set.intersection(*[set(v) for v in _d.values()]))
arms = [(n, 100 * _stats.mean(_d[n][k] for k in _common)) for n, _ in ARMS]

sig = {r["comparison"]: r for r in rows("results_tables/significance_jaccard_entity.csv")}
key = {"idiom rules": "idiom rules",
       "schema evidence (verbose)": "schema evidence, verbose",
       "schema evidence (targeted)": "schema evidence, targeted",
       "construct profile": "construct profile (X10)",
       "constrained vocabulary": "constrained vocab (X14)",
       "both oracles": "both oracles (X15)"}
key = {k: v for k, v in key.items() if v in sig}

fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, H["m"]),
                             gridspec_kw={"width_ratios": [1, 1.15]})
_cols = [MUTED] + [S1 if v > arms[0][1] else S2 for _, v in arms[1:]]
round_bar(a1, a1.bar(range(len(arms)), [v for _, v in arms], 0.62, color=_cols, zorder=3))
for i, (_, v) in enumerate(arms):
    a1.text(i, v + 0.9, f"{v:.1f}", ha="center", fontsize=7.0, color=INK2)
style(a1); a1.set_xticks(range(len(arms)))
a1.set_xticklabels([a for a, _ in arms], rotation=30, ha="right", fontsize=7.0)
a1.set_ylabel("entity-level Jaccard (%)")
a1.set_ylim(0, max(v for _, v in arms) * 1.18)
a1.set_title(f"Accuracy by arm (n = {len(_common)})", pad=6)

ys = list(range(len(key)))[::-1]
_lo = min(float(sig[v]["CI low"]) for v in key.values())
_hi = max(float(sig[v]["CI high"]) for v in key.values())
for yi, name in zip(ys, list(key)):
    r = sig[key[name]]
    d, lo, hi = (float(r["mean difference (pp)"]), float(r["CI low"]), float(r["CI high"]))
    c = S1 if d > 0 else S2
    a2.plot([lo, hi], [yi, yi], color=c, lw=1.6, solid_capstyle="round", zorder=3)
    a2.scatter([d], [yi], s=22, color=c, zorder=4, linewidths=0)
    pad = (_hi - _lo) * 0.025
    if d > 0:
        a2.text(hi + pad, yi, f"{d:+.1f}", va="center", ha="left",
                fontsize=7.0, color=INK2)
    else:
        a2.text(lo - pad, yi, f"{d:+.1f}", va="center", ha="right",
                fontsize=7.0, color=INK2)
a2.axvline(0, color=INK2, lw=0.7, zorder=2)
style(a2, xgrid=True); a2.set_yticks(ys)
a2.set_yticklabels(list(key), fontsize=7.0)
a2.set_xlabel("change vs baseline (pp)")
a2.set_xlim(_lo - (_hi - _lo) * 0.20, _hi + (_hi - _lo) * 0.16)
a2.set_title("Effect against baseline, 95\u202f% CI", pad=6)
fig.tight_layout(w_pad=2.0); save(fig, "fig_prompt_arms.pdf")

# ============================ F15 cascade ===================================
cs = rows("results_tables/consensus_selection.csv")
pools = ["same generator, 3 prompts (arm-base, arm-idiom, e2e-clean)", "4 zero-shot models", "all 8 runs"]
plabel = ["same generator,\n3 prompts", "4 zero-shot\nmodels", "all 8 runs"]
def gv(pool, strat):
    if strat == "best single":
        return max(float(r["entity_jaccard"]) for r in cs if r["pool"] == pool and r["strategy"].startswith("single:"))
    return next(float(r["entity_jaccard"]) for r in cs if r["pool"] == pool and r["strategy"] == strat)
fig, ax = new("s")
x = range(3); w = 0.26
for i, (st, c, lab) in enumerate([("best single", MUTED, "best single run"),
                                  ("centroid", S2, "centroid (agreement)"),
                                  ("cascade", S1, "cascade (empty-result fallback)")]):
    v = [gv(p, st) for p in pools]
    round_bar(ax, ax.bar([xi + (i - 1) * w for xi in x], v, w * 0.92, color=c, label=lab, zorder=3))
    if st == "cascade":
        for xi, vv in zip(x, v):
            ax.text(xi + (i - 1) * w, vv - 1.0, f"{vv:.1f}", ha="center", va="top",
                    fontsize=7.2, color="white", zorder=5)
for xi, p in zip(x, pools):
    o = gv(p, "oracle")
    ax.plot([xi - 1.6 * w, xi + 1.6 * w], [o, o], color=INK, lw=1.0, ls=(0, (3, 2)), zorder=4)
    ax.text(xi + 1.6 * w, o + 0.7, f"oracle {o:.1f}", fontsize=7, color=INK2, va="bottom", ha="right")
style(ax); ax.set_xticks(list(x)); ax.set_xticklabels(plabel)
ax.set_ylabel("entity-level Jaccard (%)"); ax.set_ylim(0, 58)
legend_above(ax, ncol=3, fontsize=7.2); save(fig, "fig_cascade.pdf")

# F16 where the fallback fires
fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, H["xs"]), gridspec_kw={"width_ratios": [1.25, 1]})
round_barh(a1, a1.barh([1], [235], 0.5, color=MUTED, zorder=3))
a1.barh([0], [64], 0.5, color=S1, zorder=3)
a1.barh([0], [28], 0.5, left=64, color=S3, zorder=3)
a1.text(239, 1, "235", va="center", fontsize=7.2, color=INK2)
a1.text(96, 0, "92", va="center", fontsize=7.2, color=INK2)
style(a1, xgrid=True); a1.set_yticks([1, 0])
a1.set_yticklabels(["first prompt\naccepted", "fallback\nfires"], fontsize=7.2)
a1.set_xlim(0, 300); a1.set_xlabel("questions (n = 327)")
for c, lab in [(S1, "empty result (64)"), (S3, "error / unlinked (28)")]:
    a1.bar(0, 0, color=c, label=lab)
a1.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=6.8)
round_bar(a2, a2.bar([0, 1], [0.0, 16.3], 0.45, color=[MUTED, S1], zorder=3))
for xi, v in zip([0, 1], [0.0, 16.3]):
    a2.text(xi, v + 0.6, f"{v:.1f}", ha="center", fontsize=7.2, color=INK2)
style(a2); a2.set_xticks([0, 1]); a2.set_xticklabels(["first prompt", "after cascade"], fontsize=7.2)
a2.set_ylabel("entity Jaccard (%)"); a2.set_ylim(0, 22)
a2.set_title("On the 92 fallback rows", pad=14, fontsize=8)
fig.tight_layout(w_pad=2.0); save(fig, "fig_cascade_fallback.pdf")

# ============================ F17 frozen vs fine-tuned ======================
offc = {r["system"]: float(r["pooled"]) for r in rows("results_tables/official_comparison.csv")}
sysd = [("mistral-7b-sparql (fine-tuned)", offc["mistral-7b-sparql"], S2),
        ("llama3-8b-sparql (fine-tuned)", offc["llama3-8b-sparql"], S2),
        ("this pipeline (frozen)", offc["this pipeline (frozen)"], S1),
        ("gpt4 (their baseline)", offc["gpt4"], MUTED),
        ("gpt3.5 (their baseline)", offc["gpt3.5"], MUTED),
        ("llama3-70b (base)", offc["llama3-70b"], MUTED),
        ("mistral-7b / llama3-8b (base)", max(offc["mistral-7b"], offc["llama3-8b"]), MUTED)]
fig, ax = new("s")
y = list(range(len(sysd)))[::-1]
round_barh(ax, ax.barh(y, [s[1] for s in sysd], 0.6, color=[s[2] for s in sysd], zorder=3))
for yi, s in zip(y, sysd):
    ax.text(s[1] + 1, yi, f"{s[1]:.1f}", va="center", fontsize=7.2, color=INK2)
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([s[0] for s in sysd], fontsize=7.6)
ax.set_xlabel("pooled fair Jaccard (%), official split, identical dump and metric")
ax.set_xlim(0, 72); save(fig, "fig_frozen_vs_finetuned.pdf")

# ============================ F18 memorisation ==============================
mf = rows("results_tables/memorisation_frontier.csv")
fig, ax = new("s")
y = list(range(len(mf)))[::-1]; h = 0.36
round_barh(ax, ax.barh([v + h / 2 for v in y], [float(r["sim_own_ge95_pct"]) for r in mf], h,
        color=S1, label="$\\geq$0.95 similar to its own gold", zorder=3))
round_barh(ax, ax.barh([v - h / 2 for v in y], [float(r["best_other_ge90_pct"]) for r in mf], h,
        color=MUTED, label="$\\geq$0.90 similar to any dataset query", zorder=3))
ax.axvline(36.5, color=INK, lw=0.9, ls=(0, (3, 2)), zorder=4)
ax.plot([], [], color=INK, lw=0.9, ls=(0, (3, 2)),
        label="gold queries vs the rest of the dataset (36.5)")
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["run"] for r in mf], fontsize=7.2)
ax.set_xlabel("% of generated queries (structural skeletons)"); ax.set_xlim(0, 88)
legend_above(ax, ncol=1, fontsize=7.2); save(fig, "fig_memorisation.pdf")

# ============================ F19-F20 WDQL ==================================
wd = rows("results_tables/wdql_construct_prevalence.csv")
KEEP = ["subclass closure (P279*)", "statement node (p:)", "qualifier (pq:)", "value node (psv:/psn:)",
        "aggregation (GROUP BY)", "alternation (VALUES/UNION)", "ANY reification/hierarchy idiom"]
def wdfig(subset, fname, xlabel):
    sel = [r for r in wd if r["subset"] == subset and r["construct"] in KEEP]
    sel.sort(key=lambda r: KEEP.index(r["construct"]))
    fig, ax = new("s")
    y = list(range(len(sel)))[::-1]
    for yi, r in zip(y, sel):
        b, w_ = float(r["benchmark_pct"]), float(r["wdql_pct"])
        ax.plot([w_, b], [yi, yi], color=MUTED, lw=1.2, zorder=2)
        ax.scatter([w_], [yi], s=26, color=S2, zorder=3, linewidths=0)
        ax.scatter([b], [yi], s=26, color=S1, zorder=3, linewidths=0)
    ax.scatter([], [], s=26, color=S1, label="Instruct-to-SPARQL gold")
    ax.scatter([], [], s=26, color=S2, label="real query logs (WDQL)")
    style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["construct"] for r in sel], fontsize=7.4)
    ax.set_xlabel(xlabel); ax.set_xlim(0, 68); legend_above(ax, ncol=2)
    save(fig, fname)
wdfig("ALL queries", "fig_wdql.pdf", "% of queries using the construct (all queries)")
wdfig("queries with 5+ predicate token(s)", "fig_wdql_bysize.pdf",
      "% of queries using the construct (queries with $\\geq$5 predicate tokens)")

# ============================ F21 candidate ceiling =========================
# Candidate ceiling under unthrottled and rate-limited retrieval.
fig, ax = new("xs")
round_barh(ax, ax.barh([1], [80.4], 0.45, color=S2, zorder=3))
round_barh(ax, ax.barh([0], [99.4], 0.45, color=S1, zorder=3))
for yi, v in [(1, 80.4), (0, 99.4)]:
    ax.text(v + 1, yi, f"{v:.1f}\u202f%", va="center", fontsize=7.4, color=INK2)
style(ax, xgrid=True); ax.set_yticks([1, 0])
ax.set_yticklabels(["original pools\n(throttled retrieval)", "clean union pools\n(rate-limited, repaired)"],
                   fontsize=7.2)
ax.set_xlim(0, 112); ax.set_xlabel("% of gold entity mentions present in the top-7 candidate pool")
save(fig, "fig_candidate_ceiling.pdf")

# ============================ F22 label failure taxonomy ====================
lf = rows("results_tables/label_failure_taxonomy.csv")
cats = ["near-miss wording", "camelCase / RDF style", "verbose paraphrase",
        "snake_case", "qualified / suffixed name", "bare identifier"]
back = ["Qwen2.5-14B (open)", "frontier model"]
val = {b: {c: 0 for c in cats} for b in back}
rate = {}
for r in lf:
    val[r["backbone"]][r["category"]] = int(r["n"])
    rate[r["backbone"]] = float(r["unfindable_rate_pct"])
fig, ax = new("m")
y = list(range(len(cats)))[::-1]; h = 0.36
for i, (b, c) in enumerate([("Qwen2.5-14B (open)", S2), ("frontier model", S1)]):
    ys = [v + (0.5 - i) * h for v in y]
    xs = [val[b][k] for k in cats]
    round_barh(ax, ax.barh(ys, xs, h * 0.9, color=c, label=f"{b} ({rate[b]:.1f}\u202f% of labels)", zorder=3))
    for yy, xx in zip(ys, xs):
        ax.text(xx + 2, yy, str(xx), va="center", fontsize=7, color=INK2)
style(ax, xgrid=True); ax.set_yticks(list(y)); ax.set_yticklabels(cats, fontsize=7.6)
ax.set_xlabel("labels Wikidata's search index cannot find (official split)")
ax.set_xlim(0, 165); legend_above(ax, ncol=1, fontsize=7.2)
save(fig, "fig_label_failures.pdf")

# ============================ F23 empty-result rate =========================
er = rows("results_tables/empty_result_rate.csv")
er = sorted(er, key=lambda r: -float(r["empty_result_pct"]))
fig, ax = new("m")
y = list(range(len(er)))[::-1]; h = 0.36
round_barh(ax, ax.barh([v + h / 2 for v in y], [float(r["empty_result_pct"]) for r in er], h,
        color=S2, label="returns nothing", zorder=3))
round_barh(ax, ax.barh([v - h / 2 for v in y], [float(r["entity_jaccard"]) for r in er], h,
        color=S1, label="entity Jaccard", zorder=3))
for v, r in zip(y, er):
    ax.text(float(r["empty_result_pct"]) + 1, v + h / 2, r["empty_result_pct"],
            va="center", fontsize=6.9, color=INK2)
    ax.text(float(r["entity_jaccard"]) + 1, v - h / 2, r["entity_jaccard"],
            va="center", fontsize=6.9, color=INK2)
style(ax, xgrid=True); ax.set_yticks(y); ax.set_yticklabels([r["run"] for r in er], fontsize=7.6)
ax.set_xlabel("% of strict-set questions"); ax.set_xlim(0, 68)
legend_above(ax, ncol=2); save(fig, "fig_empty_rate.pdf")

# ============================ F24 linker CIs ================================
lc = [r for r in rows("results_tables/linker_confidence.csv") if r["kind"] == "F1"]
fig, ax = new("s")
y = list(range(len(lc)))[::-1]
for yi, r in zip(y, lc):
    lo, hi, e = float(r["ci_low"]), float(r["ci_high"]), float(r["estimate"])
    c = (MUTED if "First search" in r["comparison"] else
         S1 if "Reasoning" in r["comparison"] else (S3 if "GLiNKER" in r["comparison"] else S2))
    ax.plot([lo, hi], [yi, yi], color=c, lw=2.0, solid_capstyle="round", zorder=3)
    ax.scatter([e], [yi], s=26, color=c, zorder=4, linewidths=0)
    ax.text(hi + 1.5, yi, f"{e:.1f}", va="center", fontsize=7.2, color=INK2)
style(ax, xgrid=True); ax.set_yticks(y)
ax.set_yticklabels([r["comparison"] for r in lc], fontsize=7.6)
ax.set_xlabel("entity linking F1 (%) with 95\u202f% bootstrap CI, 1,086 mentions")
ax.set_xlim(0, 108); save(fig, "fig_linker_ci.pdf")

with open("results_tables/figure_manifest.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["figure", "thesis_section", "shows", "source_data"])
    w.writeheader(); w.writerows(sorted(MANIFEST, key=lambda r: r["thesis_section"]))

print(f"\n{len(MANIFEST)} figures in {OUT}/ — one width, one palette, one style.")
print("written: results_tables/figure_manifest.csv (provenance also stamped into each PDF)")
