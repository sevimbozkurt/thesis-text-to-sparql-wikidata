"""score_open_pipeline.py — Execute and score the linked queries produced by
open_pipeline_e2e.py, using the thesis's endpoint, fair sets and metrics.

Usage:
  python3 score_open_pipeline.py linked_queries_qwen-qwen2-5-14b-instruct_official.json --split official
  python3 score_open_pipeline.py linked_queries_qwen-qwen2-5-14b-instruct_working.json  --split working
"""

import argparse, csv, json, os, re, sys
from endpoint import run_sparql, jaccard

QID = re.compile(r'^Q\d+$')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("linked_file")
    ap.add_argument("--split", choices=["working", "official"], default="official")
    a = ap.parse_args()

    linked = json.load(open(a.linked_file))
    out = a.linked_file.replace("linked_queries_", "results_").replace(".json", ".csv")

    # Refuse to run if another scorer is already writing this file. Concurrent
    # writers interleave their rows and fuse two records into one line.
    lock = out + ".lock"
    if os.path.exists(lock):
        sys.exit(f"{lock} exists — another scorer is writing {out}.\n"
                 f"Wait for it, or remove the lock if you are sure it is stale.")
    open(lock, "w").write(str(os.getpid()))
    import atexit
    atexit.register(lambda: os.path.exists(lock) and os.remove(lock))

    if a.split == "official":
        gold_raw = json.load(open("official_gold_results.json"))
        gold = {k: set(v["values"]) for k, v in gold_raw.items()}
        strict = {k for k, v in gold_raw.items() if v["ok"] and v["values"]}
        cx = {str(r["id"]): r["complexity"] for r in json.load(open("official_test.json"))}
    else:
        gold = {str(k): set(v) for k, v in json.load(open("gold_results.json")).items()}
        strict, cx = set(), {}
        for r in csv.DictReader(open("gold_status_qlever.csv")):
            i = r["index"]; cx[i] = r["complexity"]
            if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
                strict.add(i)
    print(f"{a.split} split: {len(linked)} rows | strict fair set {len(strict)}")

    done, rows = set(), []
    if os.path.exists(out):
        rows = list(csv.DictReader(open(out)))
        done = {r["row_id"] for r in rows}
        print(f"resuming — {len(done)} scored")

    fields = ["row_id", "complexity", "fully_linked", "executed", "exec_error",
              "jaccard_pooled", "jaccard_entity"]
    for n, (rid, rec) in enumerate(linked.items()):
        if rid in done:
            continue
        q = rec["linked_query"] if rec.get("fully_linked") else ""
        executed, vals, err = run_sparql(q) if q else (False, set(), "not_linked")
        g = gold.get(rid, set())
        ge = {v for v in g if QID.match(v)}
        pe = {v for v in vals if QID.match(v)}
        jp = jaccard(vals, g) if executed else 0.0
        je = ("na" if (not pe and not ge) else round(jaccard(pe, ge), 4)) if executed else 0.0
        rows.append({"row_id": rid, "complexity": cx.get(rid, "?"),
                     "fully_linked": rec.get("fully_linked"), "executed": executed,
                     "exec_error": err, "jaccard_pooled": round(jp, 4),
                     "jaccard_entity": je})
        if len(rows) % 50 == 0:
            with open(out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
            print(f"  {len(rows)}/{len(linked)}")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

    def pct(col, comp=None):
        sub = [r for r in rows if comp is None or r["complexity"] == comp]
        return sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100 if sub else None
    def mean(col, comp=None):
        v = [float(r[col]) for r in rows if r["row_id"] in strict
             and r[col] not in ("na", "") and (comp is None or r["complexity"] == comp)]
        return sum(v)/len(v)*100 if v else None

    print(f"\nOPEN-WEIGHT PIPELINE — {a.split} split, strict fair set\n")
    print(f"{'metric':<24} {'simple':>8} {'medium':>8} {'complex':>9} {'overall':>9}")
    for label, fn, col in [("fully linked (%)", pct, "fully_linked"),
                           ("executed (%)", pct, "executed"),
                           ("fair Jaccard pooled", mean, "jaccard_pooled"),
                           ("fair Jaccard entity", mean, "jaccard_entity")]:
        line = f"{label:<24}"
        for c in ["simple", "medium", "complex", None]:
            v = fn(col, c)
            line += f" {v:7.1f}%" if v is not None else f" {'—':>8}"
        print(line)
    ref = ("official: frontier backbone 23.4% pooled"
           if a.split == "official" else
           "working: frontier backbone 25.1% pooled / 30.9% entity (clean pools)")
    print(f"\nfor comparison — {ref}")
    print(f"written {out}")

if __name__ == "__main__":
    main()
