"""1. split-half: choose the run order on one half of the strict rows (by
overall score there), evaluate the cascade on the other half, both ways 2.
how often does the cascade actually fall back, and why (empty / error) 3.
per-complexity gain of cascade over best single run 4. paired bootstrap 95%
CI and permutation p for cascade - best single Reads outputs/consensus_results.json;
offline.
"""
import csv, json, re, random, collections
random.seed(42)
QID = re.compile(r'^Q\d+$')
R = json.load(open("outputs/consensus_results.json"))
GOLD = {k: {v for v in vals if QID.match(v)} for k, vals in json.load(open("data/gold_results.json")).items()}
cx = {r["index"]: r["complexity"] for r in csv.DictReader(open("data/gold_status_qlever.csv"))}
strict = {r["index"] for r in csv.DictReader(open("data/gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}
RUNS = ["arm-idiom", "e2e-clean", "arm-base", "fs-claude", "zs-claude", "zs-gpt", "zs-deepseek", "zs-gemini"]

def eset(run, k):
    rec = R[run].get(k); return ({v for v in rec["values"] if QID.match(v)} if rec and rec["ok"] else None)
def jac(a, b):
    if not a and not b: return None
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)
def sc(run, k): return jac(eset(run, k) or set(), GOLD[k])
ids = sorted(k for k in strict if all(k in R[r] for r in RUNS) and all(sc(r, k) is not None for r in RUNS))
def cascade(order, k):
    for r in order:
        s = eset(r, k)
        if s: return r
    return order[0]
def mean(v): return sum(v) / len(v) * 100

# 1. split-half
halves = [[k for k in ids if int(k) % 2 == 0], [k for k in ids if int(k) % 2 == 1]]
print(f"n = {len(ids)}; split-half evaluation of the cascade (order chosen on the other half)")
gains = []
for a, b in [(0, 1), (1, 0)]:
    order = sorted(RUNS, key=lambda r: -mean([sc(r, k) for k in halves[a]]))
    best_single_on_b = max(RUNS, key=lambda r: mean([sc(r, k) for k in halves[a]]))  # chosen on a, evaluated on b
    cas = mean([sc(cascade(order, k), k) for k in halves[b]]); sing = mean([sc(best_single_on_b, k) for k in halves[b]])
    gains.append(cas - sing)
    print(f"  order from half {a}: {order[:3]}...  eval on half {b} (n={len(halves[b])}): best-single {sing:.1f}  cascade {cas:.1f}  gain {cas-sing:+.1f}")
print(f"  mean out-of-sample gain {sum(gains)/2:+.1f}pp")

# 2. fallback triggers
order = RUNS
chosen = collections.Counter(cascade(order, k) for k in ids)
first = R["arm-idiom"]
reasons = collections.Counter()
for k in ids:
    rec = first.get(k)
    if rec and rec["ok"] and rec["n"] > 0: reasons["idiom arm non-empty (kept)"] += 1
    elif rec and rec["ok"]: reasons["idiom arm empty result -> fallback"] += 1
    else: reasons["idiom arm error/unlinked -> fallback"] += 1
print("\nfallback triggers:", dict(reasons)); print("run finally selected:", dict(chosen))
# what happens on fallback rows?
fb = [k for k in ids if not (first.get(k) and first[k]["ok"] and first[k]["n"] > 0)]
print(f"on the {len(fb)} fallback rows: idiom-arm score {mean([sc('arm-idiom',k) for k in fb]):.1f} -> cascade {mean([sc(cascade(order,k),k) for k in fb]):.1f}")

# 3. per complexity
print("\nper complexity (entity Jaccard): best single (arm-idiom) vs cascade")
for c in ["simple", "medium", "complex"]:
    sub = [k for k in ids if cx[k] == c]
    print(f"  {c:8s} n={len(sub):3d}  {mean([sc('arm-idiom',k) for k in sub]):5.1f} -> {mean([sc(cascade(order,k),k) for k in sub]):5.1f}")

# 4. bootstrap + permutation
d = [sc(cascade(order, k), k) - sc("arm-idiom", k) for k in ids]
boots = sorted(sum(random.choice(d) for _ in d) / len(d) * 100 for _ in range(5000))
obs = sum(d) / len(d) * 100
perm = sum(1 for _ in range(5000) if abs(sum(x * random.choice((-1, 1)) for x in d) / len(d) * 100) >= abs(obs)) / 5000
print(f"\ncascade - best single: mean {obs:+.2f}pp, bootstrap 95% CI [{boots[125]:+.2f}, {boots[4875]:+.2f}], permutation p = {perm:.4f}")
print(f"rows changed: {sum(1 for x in d if x != 0)} (improved {sum(1 for x in d if x > 0)}, worsened {sum(1 for x in d if x < 0)})")
