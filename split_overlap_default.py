"""split_overlap_default.py — Where the 567 working-split test questions fall
in the official split of the release configuration that the official-split
experiments use ("default", 495 test rows, as in the benchmark paper).

Usage:  python3 split_overlap_default.py      (needs the cached HF dataset)
"""

import csv, json, re, collections, os
from datasets import load_dataset

REVISION = "f04ffa1063a1f406c19c00b461e595a07221fa52"

def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()

ds = load_dataset("PaDaS-Lab/Instruct-to-SPARQL", "default", revision=REVISION)
where = collections.defaultdict(set)
for split in ["train", "validation", "test"]:
    col = [c for c in ds[split].column_names if "instruction" in c.lower()][0]
    for x in ds[split][col]:
        for y in (x if isinstance(x, list) else [x]):
            where[norm(y)].add(split)

ours = [norm(r["instruction"]) for r in json.load(open("test.json"))]
def bucket(x):
    s = where.get(x)
    if not s:
        return "no counterpart"
    return next(iter(s)) if len(s) == 1 else "more than one split"

c = collections.Counter(bucket(x) for x in ours)
os.makedirs("results_tables", exist_ok=True)
with open("results_tables/split_overlap_default.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["official split (default configuration)", "working test rows", "percent"])
    for k in ["train", "test", "validation", "more than one split", "no counterpart"]:
        w.writerow([k, c[k], round(c[k] / len(ours) * 100, 1)])
        print(f"{k:22s} {c[k]:4d} {c[k] / len(ours) * 100:5.1f}%")
print({k: len(v) for k, v in ds.items()})
