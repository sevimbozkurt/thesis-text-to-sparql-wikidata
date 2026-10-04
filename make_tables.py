"""make_tables.py — Generate booktabs LaTeX tables from the frozen result CSVs
so the results chapter includes them instead of retyping numbers by hand.
"""
import csv, os, re
from datetime import date

OUT = "thesis_latex/tables"
os.makedirs(OUT, exist_ok=True)
DATE = date.today().isoformat()
MANIFEST = []

def esc(s):
    s = str(s)
    for a, b in [("\\", r"\textbackslash "), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"),
                 ("#", r"\#"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde ")]:
        s = s.replace(a, b)
    return s

def table(src, out, caption, label, note, cols=None, rows_filter=None, align=None, landscape=False, size="\\small", relabel=None, tabcolsep=None, headers=None, group_col=None):
    if not os.path.exists(src):
        print(f"  SKIP (missing) {src}"); return
    rows = list(csv.DictReader(open(src)))
    if rows_filter: rows = [r for r in rows if rows_filter(r)]
    if relabel: rows = [relabel(dict(r)) for r in rows]
    if not rows:
        print(f"  SKIP (empty after filter) {src}"); return
    cols = cols or list(rows[0].keys())
    align = align or ("l" + "r" * (len(cols) - 1))
    env = "sidewaystable" if landscape else "table"
    L = [f"\\begin{{{env}}}[htbp]", "  \\centering", f"  \\caption{{{caption}}}",
         f"  \\label{{{label}}}", f"  {size}"]
    if tabcolsep:
        # a narrow table set at a tighter column gap fits the text width
        # without scaling, so it keeps the body font size
        L += [f"  \\setlength{{\\tabcolsep}}{{{tabcolsep}}}", f"  \\begin{{tabular}}{{{align}}}"]
    else:
        # scale down only if the table would run past the text width; a
        # tabular wider than \textwidth overflows into the margins silently,
        # with no overfull warning to catch it
        L += ["  \\resizebox{\\ifdim\\width>\\textwidth\\textwidth\\else\\width\\fi}{!}{%",
              f"  \\begin{{tabular}}{{{align}}}"]
    L += ["    \\toprule",
         "    " + " & ".join((headers or {}).get(c, esc(c)) for c in cols) + " \\\\", "    \\midrule"]
    prev = None
    for r in rows:
        cells = [esc(r.get(c, "")) for c in cols]
        if group_col:
            # name each group once and separate the groups with a rule
            g = r.get(group_col, "")
            if prev is not None and g != prev:
                L.append("    \\midrule")
            if g == prev:
                cells[cols.index(group_col)] = ""
            prev = g
        L.append("    " + " & ".join(cells) + " \\\\")
    L += ["    \\bottomrule", "  \\end{tabular}" + ("" if tabcolsep else "}"), f"  \\tabnote{{{note}}}",
          f"\\end{{{env}}}", ""]
    open(os.path.join(OUT, out), "w").write("\n".join(L))
    MANIFEST.append(dict(table=out, label=label, source_data=src, rows=len(rows)))
    print(f"  {out:34s} <- {src} ({len(rows)} rows)")

print("writing tables:")

table("linker_comparison.csv", "linker_comparison.tex",
      "Entity and property linking across four paradigms, both splits.",
      "tab:linkers",
      "Identical rows, identical ground truth and identical candidate pools within each split. "
      "P/R/F1 are mention-level; a prediction counts as correct only on exact identifier match. "
      "ELQ and ReFinED detect their own mentions, so their set-based figures are reported in the text "
      "instead. GLiNKER chooses among the same seven candidates per label as the reasoning linker. "
      "\\emph{First search result} takes the first Wikidata search hit among those candidates, without "
      "any model, as a reference. Per-complexity F1 is plotted in Figure~\\ref{fig:linker-cx} rather than repeated here.",
      # Portrait rather than landscape: a sideways table takes a whole page of
      # its own. The Paradigm column restated the Linker name, so dropping it
      # buys the width needed to set the rest upright.
      cols=["Split", "Linker", "Backbone", "Mentions", "P (%)", "R (%)", "F1 (%)"],
      align="lllrrrr", landscape=False, size="\\small", tabcolsep="3pt")

table("results_tables/consensus_selection.csv", "consensus_selection.tex",
      "Selection strategies over diverse generations, entity-level Jaccard.",
      "tab:cascade",
      "Each selector uses only the candidates' own result sets, never the gold answer. "
      "\\emph{oracle} is the best candidate per question and is an upper bound, not a system. "
      "Figures come from a re-execution of the cached queries and sit 0.8--1.4 points below the "
      "scores elsewhere in the results; they are internally consistent and should not be mixed "
      "with those tables.",
      cols=["pool", "strategy", "n", "entity_jaccard", "exact_match_pct"],
      headers={"pool": "Candidate pool", "strategy": "Selection", "n": "n",
               "entity_jaccard": "Entity-level Jaccard", "exact_match_pct": "Exact match (\\%)"},
      group_col="pool", align="llrrr",
      relabel=lambda r: {**r,
          "pool": {"all 8 runs": "all eight runs", "4 zero-shot models": "four zero-shot models"}.get(
              r["pool"], "one generator, three prompts" if r["pool"].startswith("same generator") else r["pool"]),
          "strategy": {"single:arm-base": "baseline arm", "single:arm-idiom": "idiom arm",
                       "single:e2e-clean": "end-to-end run", "single:fs-claude": "few-shot Claude",
                       "single:zs-claude": "zero-shot Claude", "single:zs-gpt": "zero-shot GPT-5.4",
                       "single:zs-gemini": "zero-shot Gemini", "single:zs-deepseek": "zero-shot DeepSeek",
                       "centroid+prior": "centroid with fallback", "oracle": "oracle"}.get(r["strategy"], r["strategy"])})

table("results_tables/memorisation_frontier.csv", "memorisation_frontier.tex",
      "Structural similarity of generated queries to the benchmark.",
      "tab:memorisation",
      "Skeletons compare query shape only: identifiers, literals, variable names, numbers and "
      "prefixes are removed. \\emph{Identical} is the memorisation test; "
      "\\emph{Other} measures resemblance to any other dataset query and reflects genericness "
      "rather than recall. For reference, 56\\,\\% of the benchmark authors' fine-tuned model's outputs "
      "are character-identical to the reference query. \\emph{Identical}, $\\geq$0.95 and $\\geq$0.90 give the "
      "share of outputs (\\%) whose skeleton is identical or that similar to its own reference; "
      "\\emph{Other} is the best similarity to any other dataset query (mean, and share $\\geq$0.90 in \\%); "
      "\\emph{Acc.} is entity-level Jaccard on rows whose structure is close ($\\geq$0.90) to another "
      "dataset query and on the other rows.",
      headers={"run": "Run", "n": "n", "identical_to_gold_pct": "Identical",
               "sim_own_ge95_pct": "$\\geq$0.95", "sim_own_ge90_pct": "$\\geq$0.90",
               "best_other_mean": "Other, mean", "best_other_ge90_pct": "Other $\\geq$0.90",
               "acc_near_structure": "Acc.\\ close", "acc_far_structure": "Acc.\\ other",
               "n_near": "n close", "n_far": "n other"},
      relabel=lambda r: {**r, "run": r["run"].replace("Pipeline e2e (Claude gen, clean)", "End-to-end pipeline")
                                          .replace("Idiom arm (Claude gen, Qwen link)", "Idiom arm")})

table("results_tables/significance_jaccard_entity.csv", "significance.tex",
      "Prompt interventions against the baseline arm: paired tests.",
      "tab:significance",
      "Paired over questions scored in both arms. Confidence intervals are bootstrap percentile "
      "intervals; the permutation test is two-sided. Only the generation prompt differs between arms.",
      headers={"comparison": "Comparison", "n": "n", "mean difference (pp)": "Mean difference (pp)",
               "CI low": "CI low", "CI high": "CI high", "permutation p": "Permutation $p$",
               "wilcoxon p": "Wilcoxon $p$"},
      relabel=lambda r: {**r,
          "comparison": {"construct profile (X10)": "construct profile", "constrained vocab (X14)": "constrained vocabulary",
                         "both oracles (X15)": "both oracles", "idiom rules": "idiom guidance"}.get(r["comparison"], r["comparison"]),
          **{k: ("<0.001" if float(v) < 0.001 else v) for k, v in r.items() if k in ("permutation p", "wilcoxon p")}})

table("results_tables/error_taxonomy_clean.csv", "error_taxonomy.tex",
      "Error taxonomy of a stratified sample of 30 failing questions.",
      "tab:errors",
      "Complexity-stratified random sample (seed 42) drawn from the reported clean-pool run and "
      "categorised by dominant error type. Each case was categorised by the author; "
      "an independent second annotator agreed on 21 of 30 cases. Proportions are "
      "indicative rather than population estimates.",
      headers={"category": "Category", "n": "n", "percent": "Share (\\%)"},
      relabel=lambda r: {**r, "category": {"near_miss": "near miss (projection)", "wrong_property": "wrong property",
                                           "triple_flip": "triple flip", "benchmark_noise": "reference noise",
                                           "wrong_entity": "wrong entity", "unresolved": "unresolved label",
                                           "execution": "execution error"}.get(r["category"], r["category"])})

table("results_tables/wdql_construct_prevalence.csv", "wdql_prevalence.tex",
      "Construct prevalence: benchmark gold queries versus real query logs.",
      "tab:wdql",
      "WDQL is the Wikidata Query Logs dataset (one-per-cluster release, 226{,}376 real queries). "
      "Size bands are predicate-token counts, a formatting-robust proxy for triple patterns.",
      rows_filter=lambda r: r["subset"] in ("ALL queries", "queries with 5+ predicate token(s)")
                            and r["construct"] != "label service",
      cols=["subset", "construct", "benchmark_pct", "wdql_pct", "n_benchmark", "n_wdql"],
      headers={"subset": "Queries", "construct": "Construct", "benchmark_pct": "Benchmark (\\%)",
               "wdql_pct": "WDQL (\\%)", "n_benchmark": "n benchmark", "n_wdql": "n WDQL"},
      group_col="subset", align="llrrrr",
      relabel=lambda r: {**r, "subset": {"ALL queries": "all",
                                         "queries with 5+ predicate token(s)": "5+ predicate tokens"}.get(r["subset"], r["subset"]),
                         "construct": "any reification or hierarchy idiom" if r["construct"].startswith("ANY") else r["construct"]})

table("results_tables/common_subset_metrics.csv", "main_results.tex",
      "Main comparison on the common entity-defined subset.",
      "tab:main",
      "Strict fair set; entity-level Jaccard is restricted to Wikidata identifiers and is reported on "
      "the subset where it is defined for every run. The gold-label condition supplies the benchmark's "
      "annotated query structure and is an error-source isolation, not a performance claim.")

with open("results_tables/table_manifest.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["table", "label", "source_data", "rows"])
    w.writeheader(); w.writerows(MANIFEST)
print("\nwritten: results_tables/table_manifest.csv")
print("done. \\input{tables/<file>} from the results chapter.")
