"""rescore_v2.py — Add robustness metrics to every run. Zero LLM calls.

Usage:
    python3 rescore_v2.py                      # all runs
    python3 rescore_v2.py --run results_e2e.csv
"""

import json, csv, os, gzip, argparse, re
from endpoint import run_sparql, ENDPOINT

OUTDIR   = "qlever_v2"
VALCACHE = "preds_values.jsonl.gz"
MAXVALS  = 3000

os.makedirs(OUTDIR, exist_ok=True)

QID = re.compile(r'^Q\d+$')

QUERY_COLUMN = {"results_linking.csv": "linked_query",
                "results_e2e.csv": "linked_query",
                "results_e2e_regen.csv": "linked_query"}

ALL_RUNS = ([f"results_{m}.csv" for m in ["gpt-5.4","claude","gemini","deepseek"]] +
            [f"results_fewshot_{m}.csv" for m in ["gpt-5.4","claude","gemini","deepseek"]] +
            ["results_linking.csv", "results_e2e.csv"])

GOLD = {int(k): set(v) for k, v in json.load(open("gold_results.json")).items()}

def split_vals(vals):
    ents = {v for v in vals if QID.match(v)}
    lits = vals - ents
    return ents, lits

def jac(a, b):
    if not a and not b: return None      # undefined, not 1.0
    if not a or not b:  return 0.0
    return len(a & b) / len(a | b)

def rescore(path, valcache):
    if not os.path.exists(path):
        print(f"  SKIP {path}"); return
    qcol = QUERY_COLUMN.get(path, "generated_query")
    rows = list(csv.DictReader(open(path)))
    outfile = os.path.join(OUTDIR, path)

    done, out_rows = set(), []
    if os.path.exists(outfile):
        out_rows = list(csv.DictReader(open(outfile)))
        done = {int(r["index"]) for r in out_rows}
        print(f"  resuming — {len(done)} done")

    fields = [c for c in rows[0].keys() if c != "jaccard"] + [
        "executed", "exec_error", "jaccard_pooled",
        "jaccard_entity", "jaccard_literal", "n_pred_values"]

    for r in rows:
        idx = int(r["index"])
        if idx in done: continue
        q = (r.get(qcol) or "").strip()
        if "fully_linked" in r and r["fully_linked"] != "True":
            q = ""

        executed, vals, err = (False, set(), "no_query")
        if q:
            executed, vals, err = run_sparql(q)

        g = GOLD.get(idx, set())
        ge, gl = split_vals(g)
        pe, pl = split_vals(vals)

        new = {k: v for k, v in r.items() if k != "jaccard"}
        new["executed"]        = executed
        new["exec_error"]      = err
        new["jaccard_pooled"]  = round(jac(vals, g) or 0.0, 4) if executed else 0.0
        je = jac(pe, ge)
        jl = jac(pl, gl)
        new["jaccard_entity"]  = ("na" if (je is None) else round(je, 4)) if executed else 0.0
        new["jaccard_literal"] = ("na" if (jl is None) else round(jl, 4)) if executed else 0.0
        new["n_pred_values"]   = len(vals)
        out_rows.append(new)

        valcache.write((json.dumps({"run": path, "index": idx,
                                    "values": sorted(vals)[:MAXVALS]}) + "\n").encode())

        if len(out_rows) % 50 == 0:
            _write(outfile, fields, out_rows)
            print(f"    {len(out_rows)}/{len(rows)}")

    _write(outfile, fields, out_rows)
    print(f"  {path} -> {outfile}")

def _write(outfile, fields, out_rows):
    with open(outfile, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(out_rows, key=lambda r: int(r["index"])):
            w.writerow(r)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    a = ap.parse_args()
    print(f"Endpoint: {ENDPOINT}\n")
    with gzip.open(VALCACHE, "ab") as vc:
        for p in ([a.run] if a.run else ALL_RUNS):
            print(f"Rescoring {p}")
            rescore(p, vc)
    print("\nDone. Then: python3 recompute_fair_v2.py")
