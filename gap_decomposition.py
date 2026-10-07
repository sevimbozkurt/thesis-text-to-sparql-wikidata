"""gap_decomposition.py — Bound the claim that "the 66-point gap is structure".
"""
import csv, collections, math

GOLD_LABEL, END_TO_END = 97.4, 30.9          # entity-level, n = 316 (main results table)
GAP = GOLD_LABEL - END_TO_END

GROUP = {"structure": "structural", "triple_flip": "structural",
         "wrong_property": "identifier", "wrong_entity": "identifier", "unresolved": "identifier",
         "near_miss": "projection",
         "execution": "other", "benchmark_noise": "other"}

def load(path):
    rows = [r for r in csv.DictReader(open(path)) if r.get("error_category", "").strip()]
    return rows

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0.0, c-h), min(1.0, c+h))

out = []
for path, label in [("annotations/annotation_clean.csv", "reported (clean-pool) run"),
                    ("annotations/my_annotation.csv", "pre-repair run (supporting)")]:
    rows = load(path)
    n = len(rows)
    g = collections.Counter(GROUP.get(r["error_category"].strip(), "other") for r in rows)
    print(f"\n=== {label} — n = {n} ===")
    print(f"{'group':12s} {'n':>3s} {'share':>7s} {'95% CI':>16s} {'points of the 66.5':>19s}")
    for k in ["structural", "projection", "identifier", "other"]:
        share = g[k] / n
        lo, hi = wilson(g[k], n)
        print(f"{k:12s} {g[k]:3d} {share*100:6.1f}% [{lo*100:5.1f}, {hi*100:5.1f}] "
              f"{share*GAP:9.1f}  [{lo*GAP:.1f}, {hi*GAP:.1f}]")
        out.append(dict(run=label, group=k, n=g[k], sample_n=n, share_pct=round(share*100, 1),
                        ci_low_pct=round(lo*100, 1), ci_high_pct=round(hi*100, 1),
                        points_of_gap=round(share*GAP, 1),
                        points_ci_low=round(lo*GAP, 1), points_ci_high=round(hi*GAP, 1)))
    # complex only
    cx = [r for r in rows if r.get("complexity") == "complex"]
    gc = collections.Counter(GROUP.get(r["error_category"].strip(), "other") for r in cx)
    print(f"  complex only (n={len(cx)}): " + ", ".join(f"{k} {gc[k]}" for k in
          ["structural", "projection", "identifier", "other"]))

with open("results_tables/gap_decomposition.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("written: results_tables/gap_decomposition.csv")
