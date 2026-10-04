"""recompute_common_subset.py — Remove the differing-denominator caveat.

Usage:  python3 recompute_common_subset.py
"""

import csv, os

DIR = "qlever_v2"
RUNS = [
    ("Zero-shot GPT-5.4",     "results_gpt-5.4.csv"),
    ("Zero-shot Claude",      "results_claude.csv"),
    ("Zero-shot Gemini",      "results_gemini.csv"),
    ("Zero-shot DeepSeek",    "results_deepseek.csv"),
    ("Few-shot GPT-5.4",      "results_fewshot_gpt-5.4.csv"),
    ("Few-shot Claude",       "results_fewshot_claude.csv"),
    ("Few-shot Gemini",       "results_fewshot_gemini.csv"),
    ("Few-shot DeepSeek",     "results_fewshot_deepseek.csv"),
    ("Linking (gold labels, clean)", "results_linking_clean.csv"),
    ("End-to-end (clean pools)", "results_e2e_clean.csv"),
]

strict, complexity = set(), {}
with open("gold_status_qlever.csv") as f:
    for r in csv.DictReader(f):
        i = int(r["index"]); complexity[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

data, defined_sets = {}, []
for name, fname in RUNS:
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        print(f"missing: {path}"); continue
    rows = {int(r["index"]): r for r in csv.DictReader(open(path))}
    data[name] = rows
    defined_sets.append({i for i, r in rows.items()
                         if i in strict and r["jaccard_entity"] not in ("na", "")})

common = set.intersection(*defined_sets) if defined_sets else set()
print(f"STRICT rows: {len(strict)}   common entity-defined subset: {len(common)}")
cx = {c: sum(1 for i in common if complexity[i] == c)
      for c in ["simple", "medium", "complex"]}
print(f"complexity breakdown of common subset: {cx}\n")

def mean(rows, col, subset, comp=None):
    vals = [float(rows[i][col]) for i in subset
            if rows[i][col] not in ("na", "") and (comp is None or complexity[i] == comp)]
    return sum(vals) / len(vals) * 100 if vals else None

print(f"{'Run':<24} {'pooled':>8} {'entity':>8} | {'ent simple':>11} {'ent medium':>11} {'ent complex':>12}")
print("-" * 82)
table = []
for name, _ in RUNS:
    if name not in data: continue
    rows = data[name]
    p = mean(rows, "jaccard_pooled", common)
    e = mean(rows, "jaccard_entity", common)
    s = mean(rows, "jaccard_entity", common, "simple")
    m = mean(rows, "jaccard_entity", common, "medium")
    c = mean(rows, "jaccard_entity", common, "complex")
    f = lambda x, w=8: f"{x:{w-1}.1f}%" if x is not None else f"{'—':>{w}}"
    print(f"{name:<24} {f(p)} {f(e)} | {f(s,11)} {f(m,11)} {f(c,12)}")
    table.append([name, round(p,1) if p else None, round(e,1) if e else None,
                  round(s,1) if s else None, round(m,1) if m else None,
                  round(c,1) if c else None])

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/common_subset_metrics.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Approach", "Pooled (%)", "Entity-level (%)",
                "Entity simple", "Entity medium", "Entity complex"])
    w.writerows(table)
print(f"\nExported results_tables/common_subset_metrics.csv  (n = {len(common)})")
print("Report this table where strict comparability matters; the full-set")
print("table (robustness_metrics.csv) keeps the larger denominators.")
