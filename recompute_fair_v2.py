"""recompute_fair_v2.py — Report pooled / entity-level / literal-level fair
Jaccard side by side on the STRICT fair set.

Usage:  python3 recompute_fair_v2.py
"""

import csv, os

DIR = "outputs/qlever_v2"
RUNS = [
    ("Zero-shot GPT-5.4",     "results_gpt-5.4.csv"),
    ("Zero-shot Claude",      "results_claude.csv"),
    ("Zero-shot Gemini",      "results_gemini.csv"),
    ("Zero-shot DeepSeek",    "results_deepseek.csv"),
    ("Few-shot GPT-5.4",      "results_fewshot_gpt-5.4.csv"),
    ("Few-shot Claude",       "results_fewshot_claude.csv"),
    ("Few-shot Gemini",       "results_fewshot_gemini.csv"),
    ("Few-shot DeepSeek",     "results_fewshot_deepseek.csv"),
    ("Linking (gold labels)", "results_linking.csv"),
    ("End-to-end pipeline",   "results_e2e.csv"),
]

strict, complexity = set(), {}
with open("data/gold_status_qlever.csv") as f:
    for r in csv.DictReader(f):
        i = int(r["index"]); complexity[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

def mean(rows, col):
    vals = [float(r[col]) for r in rows
            if int(r["index"]) in strict and r[col] not in ("na", "")]
    return (sum(vals) / len(vals) * 100, len(vals)) if vals else (None, 0)

print(f"STRICT fair set: {len(strict)} rows\n")
print(f"{'Run':<24} {'pooled':>8} {'entity':>8} {'literal':>8}   {'n_ent':>6}")
print("-" * 62)

table = []
for name, fname in RUNS:
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        continue
    rows = list(csv.DictReader(open(path)))
    p, _  = mean(rows, "jaccard_pooled")
    e, ne = mean(rows, "jaccard_entity")
    l, _  = mean(rows, "jaccard_literal")
    fmt = lambda x: f"{x:7.1f}%" if x is not None else f"{'—':>8}"
    print(f"{name:<24} {fmt(p)} {fmt(e)} {fmt(l)}   {ne:>6}")
    table.append([name, round(p,1) if p else None, round(e,1) if e else None,
                  round(l,1) if l else None, ne])

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/robustness_metrics.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Approach", "Fair pooled (%)", "Fair entity-level (%)",
                "Fair literal-level (%)", "n rows with entity values"])
    w.writerows(table)
print("\nExported results_tables/robustness_metrics.csv")
print("Use pooled as the headline (continuity) and entity-level as the")
print("robustness check; report both in the thesis.")
