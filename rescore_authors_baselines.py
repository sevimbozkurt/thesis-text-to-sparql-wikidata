"""rescore_authors_baselines.py — Level-playing-field comparison against the
benchmark authors' own systems.

Usage:
  python3 rescore_authors_baselines.py --list          # what is in the file
  python3 rescore_authors_baselines.py --model gpt4    # one model
  python3 rescore_authors_baselines.py                 # all models (slow)
"""

import csv, json, re, os, sys, argparse, collections
from endpoint import run_sparql, jaccard

SRC = "data/all_results.csv"
OUT = "outputs/results_authors_baselines.csv"
QID = re.compile(r'^Q\d+$')
csv.field_size_limit(10_000_000)

def norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()

def extract_query(text):
    """Their models wrap the query in [QUERY] ... [/QUERY]; fall back to the
    first PREFIX/SELECT block if the tags are absent."""
    if not text:
        return ""
    m = re.search(r'\[QUERY\](.*?)\[/QUERY\]', text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r'((?:PREFIX|SELECT|ASK|CONSTRUCT|DESCRIBE)\b.*)', text, re.S | re.I)
    return m.group(1).strip() if m else text.strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--annotated", default="False",
                    help="'False' (executable) or 'True' (bracket placeholders)")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(SRC)))
    if a.list:
        c = collections.Counter((r["model"], r["annotated"]) for r in rows)
        for (m, an), n in c.most_common():
            print(f"{m:22s} annotated={an:5s} {n:5d} rows")
        return

    official = json.load(open("data/official_test.json"))
    by_instr = {norm(r["instruction"]): str(r["id"]) for r in official}
    cx = {str(r["id"]): r["complexity"] for r in official}

    gold = json.load(open("data/official_gold_results.json"))
    strict = {rid for rid, g in gold.items() if g["ok"] and g["values"]}
    print(f"official split {len(official)} rows | strict fair set {len(strict)}")

    sel = [r for r in rows if r["annotated"] == a.annotated
           and (a.model is None or r["model"] == a.model)]
    models = sorted({r["model"] for r in sel})
    print(f"scoring {len(sel)} rows across {len(models)} model(s): {models}\n")

    done = set()
    out_rows = []
    if os.path.exists(OUT):
        out_rows = list(csv.DictReader(open(OUT)))
        done = {(r["model"], r["row_id"]) for r in out_rows}
        print(f"resuming — {len(done)} already scored")

    fields = ["model", "annotated", "row_id", "complexity", "executed",
              "exec_error", "jaccard_pooled", "jaccard_entity"]
    unmatched = 0
    for n, r in enumerate(sel):
        rid = by_instr.get(norm(r["user_instruction"]))
        if rid is None:
            unmatched += 1
            continue
        key = (r["model"], rid)
        if key in done:
            continue
        q = extract_query(r["generated_query"])
        executed, vals, err = run_sparql(q) if q else (False, set(), "no_query")
        g = set(gold.get(rid, {}).get("values", []))
        ge = {v for v in g if QID.match(v)}
        pe = {v for v in vals if QID.match(v)}
        jp = jaccard(vals, g) if executed else 0.0
        je = ("na" if (not pe and not ge) else round(jaccard(pe, ge), 4)) if executed else 0.0
        out_rows.append({"model": r["model"], "annotated": r["annotated"],
                         "row_id": rid, "complexity": cx.get(rid, "?"),
                         "executed": executed, "exec_error": err,
                         "jaccard_pooled": round(jp, 4), "jaccard_entity": je})
        if len(out_rows) % 50 == 0:
            with open(OUT, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(out_rows)
            print(f"  {len(out_rows)} scored")

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(out_rows)
    if unmatched:
        print(f"note: {unmatched} rows had no instruction match in data/official_test.json")

    # ── report ────────────────────────────────────────────────
    print(f"\nAUTHORS' MODELS, RESCORED ON OUR DUMP (14.03.2026), "
          f"strict fair set, annotated={a.annotated}\n")
    print(f"{'model':22s} {'n':>5} {'exec%':>7} {'pooled':>8} {'entity':>8} "
          f"{'simple':>8} {'medium':>8} {'complex':>9}")
    print("-" * 82)
    for m in models:
        sub = [r for r in out_rows if r["model"] == m and r["row_id"] in strict]
        if not sub:
            continue
        ex = sum(1 for r in sub if str(r["executed"]) == "True") / len(sub) * 100
        def mean(col, comp=None):
            v = [float(r[col]) for r in sub if r[col] not in ("na", "")
                 and (comp is None or r["complexity"] == comp)]
            return sum(v)/len(v)*100 if v else None
        p, e = mean("jaccard_pooled"), mean("jaccard_entity")
        s, md, c = (mean("jaccard_entity", x) for x in ["simple", "medium", "complex"])
        f = lambda x: f"{x:7.1f}%" if x is not None else f"{'—':>8}"
        print(f"{m:22s} {len(sub):5d} {ex:6.1f}% {f(p)} {f(e)} {f(s)} {f(md)} {f(c)}")

    print("\nFor the thesis comparison (every question counted, duplicates averaged) "
          "run official_comparison.py")
    print(f"written {OUT}")

if __name__ == "__main__":
    main()
