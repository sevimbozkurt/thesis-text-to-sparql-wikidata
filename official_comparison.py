"""official_comparison.py — Every official-split figure under one rule: all 370
strict-set questions count for every system, and a question for which a
system produced no scored query counts as zero (and as not executed).

Usage:  python3 official_comparison.py
"""

import csv, json, collections, os

gold = json.load(open("data/official_gold_results.json"))
strict = {k for k, v in gold.items() if v["ok"] and v["values"]}
gen = {r["id"]: r for r in csv.DictReader(open("outputs/results_official_e2e.csv"))}
cx = {k: r["complexity"] for k, r in gen.items()}
assert len(gen) == 495 and len(strict) == 370
COMPS = ["simple", "medium", "complex", None]

def ids(pool, comp):
    return [i for i in pool if comp is None or cx[i] == comp]

def pct(n, d):
    return round(n / d * 100, 1)

# ── this pipeline, stage table ─────────────────────────────────
clean = {r["row_id"]: r for r in csv.DictReader(open("outputs/linked_official-clean.csv"))}
stage = []
for label, test in [("Generated labelled query (%)", lambda i: gen[i]["generated_ok"] == "True"),
                    ("Fully linked (%)", lambda i: clean.get(i, {}).get("fully_linked") == "True"),
                    ("Executed (%)", lambda i: clean.get(i, {}).get("executed") == "True")]:
    stage.append([label] + [pct(sum(test(i) for i in ids(gen, c)), len(ids(gen, c))) for c in COMPS])

def pooled(scores, comp=None):
    q = ids(strict, comp)
    return pct(sum(scores.get(i, 0.0) for i in q), len(q))

pipe = {i: float(r["jaccard_pooled"]) for i, r in clean.items()}
stage.append(["Strict fair Jaccard (%)"] + [pooled(pipe, c) for c in COMPS])

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/official_split_results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Metric", "simple", "medium", "complex", "overall"])
    w.writerows(stage)
for row in stage:
    print(row)

# ── every system, pooled Jaccard and execution rate ────────────
systems = [("this pipeline (frozen)", pipe,
            {i for i, r in clean.items() if r["executed"] == "True"})]
open_rows = {r["row_id"]: r for r in csv.DictReader(
    open("outputs/results_qwen-qwen2-5-14b-instruct_official.csv"))}
systems.append(("open 14B for both stages",
                {i: float(r["jaccard_pooled"]) for i, r in open_rows.items()},
                {i for i, r in open_rows.items() if r["executed"] == "True"}))

auth = collections.defaultdict(lambda: collections.defaultdict(list))
for r in csv.DictReader(open("outputs/results_authors_baselines.csv")):
    if r["annotated"] == "False":
        auth[r["model"]][r["row_id"]].append(r)
for m in ["mistral-7b-sparql", "llama3-8b-sparql", "gpt4", "gpt3.5",
          "llama3-70b", "llama3-8b", "mistral-7b"]:
    d = auth[m]
    sc = {i: sum(float(x["jaccard_pooled"]) for x in v) / len(v) for i, v in d.items()}
    ex = {i: sum(x["executed"] == "True" for x in v) / len(v) for i, v in d.items()}
    systems.append((m, sc, ex))

out = []
for name, sc, ex in systems:
    exec_rate = (pct(sum(ex.get(i, 0) for i in strict), len(strict)) if isinstance(ex, dict)
                 else pct(sum(1 for i in strict if i in ex), len(strict)))
    raw = sum(sc.get(i, 0.0) for i in strict) / len(strict) * 100
    out.append([name, sum(1 for i in strict if i in sc), round(raw, 2), pooled(sc), exec_rate])
    print(out[-1])
with open("results_tables/official_comparison.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["system", "questions with output", "pooled_exact", "pooled", "executed_pct"])
    w.writerows(out)
print("Exported results_tables/official_split_results.csv and official_comparison.csv")
