"""full_set_results.py — Full strict-set results for every working-split run,
from the current scoring (outputs/qlever_v2/), with per-run denominators.

Usage:  python3 full_set_results.py
"""

import csv, os

RUNS = [("Zero-shot GPT-5.4", "results_gpt-5.4.csv"),
        ("Zero-shot Claude Opus 4.8", "results_claude.csv"),
        ("Zero-shot Gemini 3.1 Flash Lite", "results_gemini.csv"),
        ("Zero-shot DeepSeek V4 Flash", "results_deepseek.csv"),
        ("Few-shot GPT-5.4", "results_fewshot_gpt-5.4.csv"),
        ("Few-shot Claude Opus 4.8", "results_fewshot_claude.csv"),
        ("Few-shot Gemini 3.1 Flash Lite", "results_fewshot_gemini.csv"),
        ("Few-shot DeepSeek V4 Flash", "results_fewshot_deepseek.csv"),
        ("Gold-label condition", "results_linking_clean.csv"),
        ("End-to-end pipeline", "results_e2e_clean.csv")]

strict, cx = set(), {}
for r in csv.DictReader(open("data/gold_status_qlever.csv")):
    i = int(r["index"])
    cx[i] = r["complexity"]
    if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
        strict.add(i)

def defined(v):
    return v not in (None, "", "na")

table = []
for name, f in RUNS:
    rows = {int(r["index"]): r for r in csv.DictReader(open(os.path.join("outputs/qlever_v2", f)))}
    def pooled(comp=None):
        ids = [i for i in strict if comp is None or cx[i] == comp]
        v = [float(rows[i]["jaccard_pooled"]) if i in rows and defined(rows[i]["jaccard_pooled"])
             else 0.0 for i in ids]
        return round(sum(v) / len(v) * 100, 1)
    scored = sum(1 for i in strict if i in rows and defined(rows[i]["jaccard_pooled"]))
    ent = [float(rows[i]["jaccard_entity"]) for i in strict
           if i in rows and defined(rows[i]["jaccard_entity"])]
    table.append([name, scored, pooled(), pooled("simple"), pooled("medium"),
                  pooled("complex"), round(sum(ent) / len(ent) * 100, 1), len(ent)])
    print(table[-1])

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/master_results_v2.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Approach", "Questions scored", "Pooled (%)", "Simple", "Medium", "Complex",
                "Entity-level (%)", "Entity rows"])
    w.writerows(table)
print("Exported results_tables/master_results_v2.csv")
