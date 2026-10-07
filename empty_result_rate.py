"""
"""
import csv, json, re

QID = re.compile(r'^Q\d+$')
R = json.load(open("outputs/consensus_results.json"))
GOLD = {k: set(v) for k, v in json.load(open("data/gold_results.json")).items()}
strict = {r["index"] for r in csv.DictReader(open("data/gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}
LABEL = {"zs-gpt": "Zero-shot GPT-5.4", "zs-claude": "Zero-shot Claude",
         "zs-gemini": "Zero-shot Gemini", "zs-deepseek": "Zero-shot DeepSeek",
         "fs-claude": "Few-shot Claude", "e2e-clean": "Pipeline end-to-end",
         "arm-base": "Baseline arm", "arm-idiom": "Idiom arm"}

out = []
print(f"{'run':22s} {'n':>4s} {'executed':>9s} {'empty':>7s} {'error':>7s} "
      f"{'entity Jacc':>12s} {'Jacc | non-empty':>17s}")
for run, lab in LABEL.items():
    rows = {k: v for k, v in R.get(run, {}).items() if k in strict}
    if not rows: continue
    n = len(rows)
    ok = [k for k, v in rows.items() if v["ok"]]
    empty = [k for k in ok if rows[k]["n"] == 0]
    err = n - len(ok)
    def jac(k):
        g = {v for v in GOLD.get(k, set()) if QID.match(v)}
        p = {v for v in rows[k]["values"] if QID.match(v)} if rows[k]["ok"] else set()
        if not g and not p: return None
        if not g or not p: return 0.0
        return len(g & p) / len(g | p)
    allj = [jac(k) for k in rows if jac(k) is not None]
    nonempty = [jac(k) for k in ok if rows[k]["n"] > 0 and jac(k) is not None]
    m = lambda v: sum(v) / len(v) * 100 if v else float("nan")
    print(f"{lab:22s} {n:4d} {len(ok)/n*100:8.1f}% {len(empty)/n*100:6.1f}% {err/n*100:6.1f}% "
          f"{m(allj):11.1f} {m(nonempty):16.1f}")
    out.append(dict(run=lab, n=n, executed_pct=round(len(ok)/n*100, 1),
                    empty_result_pct=round(len(empty)/n*100, 1),
                    error_pct=round(err/n*100, 1),
                    entity_jaccard=round(m(allj), 1),
                    entity_jaccard_nonempty_only=round(m(nonempty), 1)))

with open("results_tables/empty_result_rate.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("written: results_tables/empty_result_rate.csv")
