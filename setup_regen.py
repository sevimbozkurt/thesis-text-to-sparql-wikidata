"""setup_regen.py — Rebuild the 102 working-split rows whose labelled-query
generation returned an empty string.

Usage:  python3 setup_regen.py
"""

import json, csv, os, shutil

SRC_ROWS   = "test.json"
SRC_RESULT = "qlever/results_e2e.csv"
GOLD       = "gold_results.json"
REGEN      = "regen"

rows = json.load(open(SRC_ROWS))
res  = list(csv.DictReader(open(SRC_RESULT)))

failed = [int(r["index"]) for r in res if r["generated_ok"] != "True"]
print(f"rows to regenerate: {len(failed)}")

os.makedirs(REGEN, exist_ok=True)

# rows in the shape run_official_batch.py expects, id = working-split index
out = [{"id": str(i), "instruction": rows[i]["instruction"],
        "query": rows[i]["query"], "annotated": rows[i].get("annotated", ""),
        "complexity": rows[i]["complexity"]} for i in failed]
json.dump(out, open(f"{REGEN}/official_test.json", "w"), indent=1)

# prefill the gold cache from the existing working-split gold results (free)
gold_src = json.load(open(GOLD))
gold = {str(i): {"ok": True, "values": gold_src.get(str(i), []), "err": ""}
        for i in failed if str(i) in gold_src}
json.dump(gold, open(f"{REGEN}/official_gold_results.json", "w"))
print(f"prefilled gold results for {len(gold)} of {len(failed)} rows")

for f in ["endpoint.py", "run_official_batch.py", "fetch_results.py",
          "refetch_candidates.py", ".env"]:
    if os.path.exists(f):
        shutil.copy(f, f"{REGEN}/{f}")
    else:
        print(f"  WARNING: {f} not found — copy it into {REGEN}/ manually")

merge = '''"""
merge_regen.py — Merge regenerated rows back into the working-split results.

Writes qlever/results_e2e_regen.csv (the original file is left untouched) and
prints the corrected stage table so the effect of the fix is visible.
"""
import csv, json

base = list(csv.DictReader(open("qlever/results_e2e.csv")))
new  = {r["id"]: r for r in csv.DictReader(open("regen/results_official_e2e.csv"))}

fixed = 0
for r in base:
    n = new.get(r["index"])
    if not n or not n["labeled_query"]:
        continue
    r["labeled_query"] = n["labeled_query"]
    r["linked_query"]  = n["linked_query"]
    r["generated_ok"]  = n["generated_ok"]
    r["fully_linked"]  = n["fully_linked"]
    r["executed"]      = n["executed"]
    r["exec_error"]    = n["exec_error"]
    r["jaccard_new"]   = n["jaccard"]
    fixed += 1

with open("qlever/results_e2e_regen.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=base[0].keys()); w.writeheader(); w.writerows(base)
print(f"merged {fixed} regenerated rows -> qlever/results_e2e_regen.csv")

strict, cx = set(), {}
for r in csv.DictReader(open("gold_status_qlever.csv")):
    i = r["index"]; cx[i] = r["complexity"]
    if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
        strict.add(i)

def pct(sub, col):
    return round(sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100, 1) if sub else None

print(f"\\n{'Stage':<30} {'simple':>8} {'medium':>8} {'complex':>9} {'overall':>9}")
for label, col in [("1. Generated labelled query","generated_ok"),
                   ("2. Fully linked","fully_linked"),
                   ("3. Executed","executed")]:
    line = f"{label:<30}"
    for c in ["simple","medium","complex",None]:
        sub = [r for r in base if c is None or r["complexity"] == c]
        line += f" {pct(sub,col):7.1f}%"
    print(line)
line = f"{'4. Strict fair Jaccard':<30}"
for c in ["simple","medium","complex",None]:
    sub = [r for r in base if r["index"] in strict and (c is None or r["complexity"] == c)]
    v = sum(float(r["jaccard_new"]) for r in sub)/len(sub)*100 if sub else 0
    line += f" {v:7.1f}%"
print(line)
'''
open("merge_regen.py", "w").write(merge)
print("\\nwrote merge_regen.py")
print(f"next:  cd {REGEN}  and run the batch commands listed in this file's docstring")
