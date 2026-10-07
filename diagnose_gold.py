"""diagnose_gold.py — Re-verify all gold queries on the configured endpoint AND
cache their result sets, in one pass.

Usage:
    python3 diagnose_gold.py
"""

import json, csv, os
from endpoint import run_sparql, ENDPOINT

STATUS_FILE  = "data/gold_status_qlever.csv"
RESULTS_FILE = "data/gold_results.json"

with open("data/test.json") as f:
    test = json.load(f)

# Resume support
done, gold_results = set(), {}
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE) as f:
        gold_results = {int(k): v for k, v in json.load(f).items()}
    done = set(gold_results.keys())
    print(f"Resuming — {len(done)} gold queries already cached")

status_rows = []
if os.path.exists(STATUS_FILE):
    status_rows = list(csv.DictReader(open(STATUS_FILE)))
    status_rows = [r for r in status_rows if int(r["index"]) in done]

print(f"Endpoint: {ENDPOINT}")

for i, ex in enumerate(test):
    if i in done:
        continue
    executed, vals, err = run_sparql(ex["query"])
    gold_results[i] = sorted(vals)
    status_rows.append({
        "index": i, "complexity": ex["complexity"],
        "gold_executed": executed, "gold_error": err,
        "gold_result_count": len(vals),
    })
    # checkpoint every 25
    if (i + 1) % 25 == 0:
        with open(RESULTS_FILE, "w") as f:
            json.dump({str(k): v for k, v in gold_results.items()}, f)
        print(f"  {i+1}/{len(test)} checked")

with open(RESULTS_FILE, "w") as f:
    json.dump({str(k): v for k, v in gold_results.items()}, f)

with open(STATUS_FILE, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["index", "complexity", "gold_executed",
                                      "gold_error", "gold_result_count"])
    w.writeheader()
    for r in sorted(status_rows, key=lambda r: int(r["index"])):
        w.writerow(r)

# ── Summary ────────────────────────────────────────────────────
rows = list(csv.DictReader(open(STATUS_FILE)))
total    = len(rows)
executed = [r for r in rows if r["gold_executed"] == "True"]
strict   = [r for r in executed if r["gold_result_count"] != "0"]
timeouts = sum(1 for r in rows if r["gold_error"] in ("timeout", "connection"))
http_err = sum(1 for r in rows if r["gold_error"].startswith("http"))

print(f"\n{'='*52}")
print(f"GOLD DIAGNOSTIC — {ENDPOINT}")
print(f"{'='*52}")
print(f"Total gold queries              : {total}")
print(f"Executed (LENIENT fair set)     : {len(executed)}")
print(f"Executed & non-empty (STRICT)   : {len(strict)}")
print(f"Gold-empty rows (the 1.0 trap)  : {len(executed) - len(strict)}")
print(f"Failed — HTTP errors            : {http_err}")
print(f"Failed — timeout/connection     : {timeouts}")
print()
print(f"{'Complexity':<10} {'Total':>6} {'Lenient':>8} {'Strict':>7}")
print("-" * 36)
for c in ["simple", "medium", "complex"]:
    sub = [r for r in rows if r["complexity"] == c]
    le  = sum(1 for r in sub if r["gold_executed"] == "True")
    st  = sum(1 for r in sub if r["gold_executed"] == "True"
              and r["gold_result_count"] != "0")
    print(f"{c:<10} {len(sub):>6} {le:>8} {st:>7}")
print(f"\nRecord these counts WITH today's date — they define the fair sets")
print(f"for every number in the thesis. Gold results cached to {RESULTS_FILE}.")
