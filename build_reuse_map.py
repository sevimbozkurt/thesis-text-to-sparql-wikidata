"""

Usage:  python3 build_reuse_map.py
"""

import json, csv, re, collections
from datasets import load_dataset

def n(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()

ours = json.load(open("data/test.json"))
official = json.load(open("data/official_test.json"))
ds = load_dataset("PaDaS-Lab/Instruct-to-SPARQL", "with_limit")

# instruction -> official split name (every instruction variant of every row)
instr2split = {}
for split in ["train", "validation", "test"]:
    for r in ds[split]:
        ins = r.get("instructions") or []
        if isinstance(ins, str):
            ins = [ins]
        for i in ins:
            instr2split[n(i)] = split

counts = collections.Counter()
report = []
for idx, r in enumerate(ours):
    sp = instr2split.get(n(r["instruction"]), "not_found")
    counts[sp] += 1
    report.append([idx, r["complexity"], sp])

print(f"our 567 working-test rows map to official splits as:")
for k, v in counts.most_common():
    print(f"  {k:12s} {v:4d}  ({v/len(ours)*100:.1f}%)")

with open("overlap_report.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["our_index", "complexity", "official_split"])
    w.writerows(report)

# ── reuse map: official row -> our cached labelled query ───────
cached = {}
try:
    for r in csv.DictReader(open("outputs/qlever/results_e2e.csv")):
        i = int(r["index"])
        if r.get("labeled_query"):
            cached[n(ours[i]["instruction"])] = r["labeled_query"]
except FileNotFoundError:
    print("\nqlever/results_e2e.csv not found — no reuse possible")

reuse = {}
for row in official:
    q = cached.get(n(row["instruction"]))
    if q:
        reuse[str(row["id"])] = q

json.dump(reuse, open("reuse_map.json", "w"), indent=1)
print(f"\nreuse_map.json: {len(reuse)} of {len(official)} official rows can reuse "
      f"an already-generated query (verified by instruction text)")
print("overlap_report.csv written — use these numbers in the Limitations section")
