"""significance_idiom.py — Is the idiom-prompting gain distinguishable from
noise?

Usage:
  python3 significance_idiom.py
  python3 significance_idiom.py --metric jaccard_pooled
"""

import argparse, csv, os, random, statistics

ARMS = [
    ("baseline",                    "outputs/linked_base-qwen.csv"),
    ("idiom rules",                 "outputs/linked_idiom-qwen.csv"),
    ("schema evidence, verbose",    "outputs/linked_grounded.csv"),
    ("schema evidence, targeted",   "outputs/linked_grounded-targeted.csv"),
    # Added 9 Sep 2026. Same pipeline, same disambiguation backbone
    # (Qwen2.5-14B), same scoring — only the generation prompt differs, exactly
    # as for the four arms above. load_scores() returns None for a missing file,
    # so these are skipped silently until they have been scored.
    ("construct profile (X10)",     "outputs/linked_profile.csv"),
    ("constrained vocab (X14)",     "outputs/linked_constrained.csv"),
    # X15: the fourth cell of the 2x2 — gold vocabulary AND gold constructs.
    # The quantity of interest is X15 - X14, i.e. what structural knowledge adds
    # once the identifiers are already correct.
    ("both oracles (X15)",          "outputs/linked_both.csv"),
]

def load_scores(path, metric, strict):
    """row_id -> score, restricted to the strict fair set."""
    if not os.path.exists(path):
        return None
    out = {}
    for r in csv.DictReader(open(path)):
        rid = r.get("row_id") or r.get("index")
        if rid is None or rid not in strict:
            continue
        v = r.get(metric, "")
        if v in ("na", "", None):
            continue
        x = float(v)
        # Jaccard is bounded in [0,1]. A value outside that range means the CSV
        # is damaged, not that a system did unusually well, and it will silently
        # dominate a mean difference. This fired once: two background jobs scored
        # the same file concurrently, their writes interleaved, and one row read
        # jaccard_entity = 374, turning a +23pp result into +128.88pp with a CI
        # to +343. Caught only because the number was impossible.
        if not (0.0 <= x <= 1.0):
            raise SystemExit(
                f"{path}: row {rid} has {metric} = {v}, outside [0,1].\n"
                f"The file is corrupt — most likely two scorers wrote to it at "
                f"once. Delete it and re-score with a single writer.")
        out[rid] = x
    return out

def paired_bootstrap(diffs, n=10000, seed=42):
    rng = random.Random(seed)
    k = len(diffs)
    means = []
    for _ in range(n):
        s = sum(diffs[rng.randrange(k)] for _ in range(k))
        means.append(s / k)
    means.sort()
    lo = means[int(0.025 * n)]
    hi = means[int(0.975 * n)]
    p_neg = sum(1 for m in means if m <= 0) / n
    return lo, hi, p_neg

def permutation_test(diffs, n=10000, seed=42):
    """Null: the sign of each per-question difference is arbitrary."""
    rng = random.Random(seed)
    obs = abs(sum(diffs) / len(diffs))
    hits = 0
    for _ in range(n):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(s / len(diffs)) >= obs:
            hits += 1
    return (hits + 1) / (n + 1)          # add-one correction

def wilcoxon(diffs):
    try:
        from scipy.stats import wilcoxon as w
    except Exception:
        return None
    nz = [d for d in diffs if d != 0]
    if len(nz) < 10:
        return None
    try:
        return float(w(nz).pvalue)
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", default="jaccard_entity",
                    choices=["jaccard_entity", "jaccard_pooled"])
    a = ap.parse_args()

    strict = set()
    with open("data/gold_status_qlever.csv") as f:
        for r in csv.DictReader(f):
            if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
                strict.add(r["index"])
    print(f"strict fair set: {len(strict)} questions | metric: {a.metric}\n")

    scores = {}
    for label, path in ARMS:
        s = load_scores(path, a.metric, strict)
        if s is None:
            print(f"  MISSING {path} — arm '{label}' skipped")
        else:
            scores[label] = s

    if "baseline" not in scores:
        raise SystemExit("baseline arm missing; cannot run paired tests")

    base = scores["baseline"]
    print(f"{'comparison':<32} {'n':>5} {'mean Δ':>9} {'95% CI':>18} "
          f"{'perm p':>9} {'wilcoxon':>10}")
    print("-" * 88)

    rows_out = []
    for label in [l for l, _ in ARMS if l != "baseline" and l in scores]:
        arm = scores[label]
        common = sorted(set(base) & set(arm))
        diffs = [arm[r] - base[r] for r in common]
        if not diffs:
            continue
        mean_d = sum(diffs) / len(diffs) * 100
        lo, hi, p_neg = paired_bootstrap(diffs)
        p_perm = permutation_test(diffs)
        p_wil = wilcoxon(diffs)
        wil_s = f"{p_wil:.4f}" if p_wil is not None else "—"
        print(f"{label:<32} {len(common):5d} {mean_d:+8.2f}pp "
              f"[{lo*100:+6.2f},{hi*100:+6.2f}] {p_perm:9.4f} {wil_s:>10}")
        rows_out.append([label, len(common), round(mean_d, 2),
                         round(lo * 100, 2), round(hi * 100, 2),
                         round(p_perm, 4), wil_s])

        nz = sum(1 for d in diffs if d != 0)
        better = sum(1 for d in diffs if d > 0)
        worse = sum(1 for d in diffs if d < 0)
        print(f"{'':<32} questions changed: {nz} "
              f"(better {better}, worse {worse}, unchanged {len(diffs)-nz})")

    os.makedirs("results_tables", exist_ok=True)
    with open(f"results_tables/significance_{a.metric}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["comparison", "n", "mean difference (pp)", "CI low",
                    "CI high", "permutation p", "wilcoxon p"])
        w.writerows(rows_out)
    print(f"\nwritten results_tables/significance_{a.metric}.csv")
    print("\nReporting note: the confidence interval is the informative "
          "quantity; a p-value alone says nothing about the size of the effect.")

if __name__ == "__main__":
    main()
