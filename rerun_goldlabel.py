"""rerun_goldlabel.py — Re-run the gold-label linking experiment using the
CORRECTED disambiguation predictions. No LLM calls, no new spend.

Usage:  python3 rerun_goldlabel.py
"""

import csv, json, re, os, collections
from endpoint import run_sparql, jaccard, ENDPOINT

QID = re.compile(r'^Q\d+$')
OUT = "outputs/results_linking_clean.csv"

def split_vals(vals):
    ents = {v for v in vals if QID.match(v)}
    return ents, vals - ents

def jac_or_none(a, b):
    if not a and not b:
        return None
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

gold_links = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
test = json.load(open("data/test.json"))
gold_res = {int(k): set(v) for k, v in json.load(open("data/gold_results.json")).items()}

preds = collections.defaultdict(dict)
for line in open("outputs/preds_reasoning_full.jsonl"):
    r = json.loads(line)
    preds[r["index"]][(r["kind"], r["label"])] = r["pred_id"]

strict, complexity = set(), {}
with open("data/gold_status_qlever.csv") as f:
    for r in csv.DictReader(f):
        i = int(r["index"]); complexity[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

done = set()
rows_out = []
if os.path.exists(OUT):
    rows_out = list(csv.DictReader(open(OUT)))
    done = {int(r["index"]) for r in rows_out}
    print(f"resuming — {len(done)} rows done")

fields = ["index", "complexity", "linked_query", "fully_linked", "all_links_correct",
          "executed", "exec_error", "jaccard_pooled", "jaccard_entity"]

print(f"endpoint: {ENDPOINT}")
for n, (i, pairs) in enumerate(sorted(gold_links.items())):
    if i in done:
        continue
    q = test[i]["annotated"]
    all_correct = True
    for kind, label, gid in pairs:
        pid = preds.get(i, {}).get((kind, label), "")
        if pid != gid:
            all_correct = False
        if pid:
            tag = "entity" if kind == "entity" else "property"
            q = re.sub(r'\[' + tag + ':' + re.escape(label) + r'\]', pid, q, flags=re.I)
    fully = "[entity:" not in q and "[property:" not in q

    executed, vals, err = (False, set(), "not_linked")
    if fully:
        executed, vals, err = run_sparql(q)
    g = gold_res.get(i, set())
    ge, _ = split_vals(g)
    pe, _ = split_vals(vals)
    jp = jaccard(vals, g) if executed else 0.0
    je = jac_or_none(pe, ge) if executed else 0.0

    rows_out.append({"index": i, "complexity": complexity.get(i, "?"),
                     "linked_query": q, "fully_linked": fully,
                     "all_links_correct": all_correct, "executed": executed,
                     "exec_error": err, "jaccard_pooled": round(jp, 4),
                     "jaccard_entity": ("na" if je is None else round(je, 4))})
    if len(rows_out) % 50 == 0:
        with open(OUT, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows_out)
        print(f"  {len(rows_out)}/{len(gold_links)}")

with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows_out)

# ── report ─────────────────────────────────────────────────────
def mean(rows, col, comp=None):
    v = [float(r[col]) for r in rows
         if int(r["index"]) in strict and r[col] not in ("na", "")
         and (comp is None or r["complexity"] == comp)]
    return sum(v)/len(v)*100 if v else None

def pct(rows, col, comp=None):
    sub = [r for r in rows if comp is None or r["complexity"] == comp]
    return sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100 if sub else None

print(f"\nGOLD-LABEL LINKING, CORRECTED POOLS — {len(rows_out)} rows "
      f"({len(strict)} in strict fair set)\n")
print(f"{'metric':<26} {'simple':>8} {'medium':>8} {'complex':>9} {'overall':>9}")
for label, fn, col in [("all links correct (%)", pct, "all_links_correct"),
                       ("fully linked (%)", pct, "fully_linked"),
                       ("executed (%)", pct, "executed"),
                       ("fair Jaccard pooled", mean, "jaccard_pooled"),
                       ("fair Jaccard entity", mean, "jaccard_entity")]:
    line = f"{label:<26}"
    for c in ["simple", "medium", "complex", None]:
        v = fn(rows_out, col, c)
        line += f" {v:7.1f}%" if v is not None else f" {'—':>8}"
    print(line)
print(f"\nwritten {OUT}")
