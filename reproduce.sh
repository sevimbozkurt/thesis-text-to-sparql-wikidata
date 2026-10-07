#!/usr/bin/env bash
# =============================================================================
# reproduce.sh — regenerate every reported number, table and figure in the
# thesis from the frozen data in this directory.
#
#   bash reproduce.sh            # stages 1 and 3 (offline; ~3 minutes)
#   bash reproduce.sh --with-endpoint   # also stage 2 (QLever; ~80 minutes)
#
# WHAT THIS DOES AND DOES NOT DO
#   It does     : recompute every figure, table and reported statistic from the
#                 cached experiment outputs stored here.
#   It does not : re-run the experiments themselves. Generation, disambiguation
#                 and the linker runs required paid API calls, a GPU server and
#                 many hours; their outputs are cached in this directory
#                 (results_*.csv, preds_*.jsonl, linked_*.json, batch_*.json) and
#                 everything downstream is derived from those caches.
#                 The scripts that produced them are listed in "ORIGINAL RUNS"
#                 at the bottom of this file.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"
WITH_ENDPOINT=${1:-}

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "Stage 0 — prerequisites"
python3 - <<'PY'
import sys, importlib.util
need = ["csv", "json", "sklearn", "numpy", "matplotlib"]
miss = [m for m in need if not importlib.util.find_spec(m)]
print(f"  python {sys.version.split()[0]}")
print("  missing packages:", ", ".join(miss) if miss else "none")
if miss:
    sys.exit("  install them before continuing (scikit-learn, numpy, matplotlib)")
PY
if [ ! -d external/wdql/wdql-one-per-cluster ]; then
  echo "  NOTE: external/wdql not present — X3 (query-log comparison) will be skipped."
  echo "        Download: https://wdql.cs.uni-freiburg.de/data/latest/wdql-one-per-cluster.tar.gz"
fi

# -----------------------------------------------------------------------------
say "Stage 1 — offline analysis (no network, no API)"

echo "-- X6 gap decomposition"
python3 gap_decomposition.py > /dev/null
echo "   -> results_tables/gap_decomposition.csv"

echo "-- X4 frontier memorisation check"
python3 check_memorisation_frontier.py > /dev/null
echo "   -> results_tables/memorisation_frontier.csv"

if [ -d external/wdql/wdql-one-per-cluster ]; then
  echo "-- X3 construct prevalence against the Wikidata query logs"
  python3 wdql_construct_prevalence.py > /dev/null
  echo "   -> results_tables/wdql_construct_prevalence.csv"
fi

if [ -f outputs/consensus_results.json ]; then
  echo "-- X5 selection strategies"
  python3 consensus_select.py > results_tables/consensus_selection_full.txt
  echo "   -> results_tables/consensus_selection.csv"
  echo "-- X8 empty-result rate"
  python3 empty_result_rate.py > results_tables/empty_result_rate.txt
  echo "   -> results_tables/empty_result_rate.csv"
  echo "-- X5 robustness (split-half, bootstrap, permutation)"
  python3 consensus_robustness.py > results_tables/consensus_robustness.txt
  echo "   -> results_tables/consensus_robustness.txt"
else
  echo "-- X5 skipped: outputs/consensus_results.json missing (run with --with-endpoint)"
fi

echo "-- X7 label-failure taxonomy"
python3 label_failure_taxonomy.py > results_tables/label_failure_taxonomy.txt
echo "   -> results_tables/label_failure_taxonomy.csv"

echo "-- X12 prompt-arm provenance check"
python3 arm_provenance_check.py > results_tables/arm_provenance_check.txt
echo "   -> results_tables/arm_provenance_check.txt"

echo "-- linker comparison table from the prediction files"
python3 build_linker_comparison.py > /dev/null
echo "   -> results_tables/linker_comparison.csv"

echo "-- X9 linker confidence intervals (bootstrap, ~1 min)"
python3 linker_confidence.py > results_tables/linker_confidence.txt
echo "   -> results_tables/linker_confidence.csv"

# X11 needs the Wikidata API (~9 min); skipped by default, results are cached
if [ ! -f results_tables/label_repair.csv ]; then
  echo "-- X11 label repair (Wikidata API, ~9 min)"
  python3 label_repair.py > results_tables/label_repair.txt
else
  echo "-- X11 label repair: cached (delete results_tables/label_repair.csv to re-run)"
fi

echo "-- official split, every question counted (Table A.4, Figure 4.12)"
python3 official_comparison.py > /dev/null
echo "   -> results_tables/official_split_results.csv, official_comparison.csv"

echo "-- full strict-set results, working split (Table A.1)"
python3 full_set_results.py > /dev/null
echo "   -> results_tables/master_results_v2.csv"

echo "-- cross-model agreement (hard and easy questions)"
python3 complexity_and_agreement.py > results_tables/RESULT_cross_model_agreement.txt
echo "   -> results_tables/RESULT_cross_model_agreement.txt"

echo "-- X1/X2 extension probes (printed, not written)"
python3 analysis_extension_probes.py > results_tables/extension_probes.txt
echo "   -> results_tables/extension_probes.txt"

# -----------------------------------------------------------------------------
if [ "$WITH_ENDPOINT" = "--with-endpoint" ]; then
  say "Stage 2 — QLever endpoint (~80 minutes, needs .env credentials)"
  echo "-- re-executing 3,197 cached queries to collect result sets"
  python3 consensus_execute.py
  echo "-- re-running stage 1 selection steps on the fresh result sets"
  python3 consensus_select.py > results_tables/consensus_selection_full.txt
  python3 consensus_robustness.py > results_tables/consensus_robustness.txt
else
  say "Stage 2 — skipped (pass --with-endpoint to re-execute queries on QLever)"
fi

# -----------------------------------------------------------------------------
say "Stage 3 — verification report, tables, figures"

echo "-- verification report (every reported number, from hashed inputs)"
python3 verify_all.py > /dev/null
echo "   -> VERIFICATION_REPORT.md and VERIFICATION_REPORT_<today>.md"

echo "-- LaTeX tables"
python3 make_tables.py | sed 's/^/   /'

echo "-- figures"
python3 make_figures.py | sed 's/^/   /'

echo "-- appendix (prompts verbatim from source, annotations, full tables)"
python3 make_appendix.py | sed 's/^/   /'

say "Done"
cat <<'EOF'
  Outputs:
    VERIFICATION_REPORT_<today>.md   — the reported numbers, recomputed
    results_tables/figure_manifest.csv / table_manifest.csv — what each figure
       and table was built from
    thesis_latex/  — LaTeX sources with the regenerated tables and figures
EOF

# =============================================================================
# ORIGINAL RUNS — not re-executed here (paid API / GPU / many hours).
# The scripts that produced the cached outputs.
#
#   prepare_dataset.py        build the stratified split from the released data
#   evaluate_all.py           zero-shot baselines, four frontier models
#   evaluate_fewshot.py       few-shot baselines
#   link_entities.py          gold-label linking condition
#   pipeline_e2e.py           end-to-end pipeline
#   fetch_candidates.py       candidate retrieval
#   refetch_candidates.py     rate-limited candidate retrieval
#   run_glinker_restricted.py GLiNKER on each label's own candidates
#   run_refined.py / run_elq.py   fine-tuned end-to-end linkers (GPU server)
#   elq_library_coverage.py   ELQ catalogue coverage (streams the 3.5 GB catalogue)
#   open_backbone_linking.py  Qwen2.5-14B / 7B disambiguation via vLLM (GPU)
#   prompt_idioms.py          idiom-guidance arm (Anthropic Batch API)
#   schema_grounded.py        schema-evidence arms (verbose and targeted)
#   run_official_batch.py     official-split run (Batch API)
#   rescore_v2.py             re-scoring of all cached runs on QLever
#   eval_linker.py / eval_linker_official.py   linking P/R/F1 per split
#   construct_analysis.py     corpus-wide construct usage and agreement
#   complexity_and_agreement.py  structural predictors, cross-model agreement
#   check_memorisation.py     memorisation check for the authors' fine-tuned models
# =============================================================================
