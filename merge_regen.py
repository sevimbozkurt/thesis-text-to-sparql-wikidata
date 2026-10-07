"""merge_regen.py — Merge regenerated rows back into the working-split results.
"""
import csv, json

base = list(csv.DictReader(open("outputs/qlever/results_e2e.csv")))
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

with open("outputs/qlever/results_e2e_regen.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=base[0].keys()); w.writeheader(); w.writerows(base)
print(f"merged {fixed} regenerated rows -> outputs/qlever/results_e2e_regen.csv")

strict, cx = set(), {}
for r in csv.DictReader(open("data/gold_status_qlever.csv")):
    i = r["index"]; cx[i] = r["complexity"]
    if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
        strict.add(i)

def pct(sub, col):
    return round(sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100, 1) if sub else None

print(f"\n{'Stage':<30} {'simple':>8} {'medium':>8} {'complex':>9} {'overall':>9}")
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
