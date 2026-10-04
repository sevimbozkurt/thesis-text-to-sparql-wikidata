"""
"""
import csv, json, re, itertools, collections

QID = re.compile(r'^Q\d+$')
THRESH = 0.5
PRIOR = ["arm-idiom", "e2e-clean", "arm-base", "fs-claude", "zs-claude", "zs-gpt", "zs-deepseek", "zs-gemini"]
POOLS = {"same generator, 3 prompts (arm-base, arm-idiom, e2e-clean)": ["arm-base", "arm-idiom", "e2e-clean"],
         "4 zero-shot models": ["zs-claude", "zs-gpt", "zs-gemini", "zs-deepseek"],
         "all 8 runs": PRIOR}

R = json.load(open("consensus_results.json"))
GOLD = {k: set(v) for k, v in json.load(open("gold_results.json")).items()}
strict = {r["index"] for r in csv.DictReader(open("gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}

def ents(vals): return {v for v in vals if QID.match(v)}
def jac(a, b):
    if not a and not b: return None
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)

def cand_sets(pool, k):
    """entity result set per run for row k; None if not executed / missing."""
    out = {}
    for run in pool:
        rec = R.get(run, {}).get(k)
        out[run] = ents(rec["values"]) if rec and rec["ok"] else None
    return out

def score(sel_set, gold_ents): return jac(sel_set if sel_set is not None else set(), gold_ents)

def select(strategy, pool, sets):
    order = [r for r in PRIOR if r in pool]
    nonempty = [r for r in order if sets[r]]
    if strategy.startswith("single:"):
        return sets[strategy.split(":", 1)[1]]
    if strategy == "cascade":
        return sets[nonempty[0]] if nonempty else sets[order[0]]
    if strategy in ("centroid", "centroid+prior"):
        if len(nonempty) == 1:
            return sets[nonempty[0]]
        if not nonempty:
            return sets[order[0]]
        best, best_run, best_max = -1, None, 0
        for r in nonempty:
            js = [jac(sets[r], sets[o]) or 0 for o in nonempty if o != r]
            m = sum(js) / len(js)
            if m > best + 1e-9:
                best, best_run, best_max = m, r, max(js)
        if strategy == "centroid+prior" and best_max < THRESH:
            return sets[order[0]]
        return sets[best_run]
    raise ValueError(strategy)

rows_out = []
for pool_name, pool in POOLS.items():
    # rows where every run in the pool has a defined entity score (matches P3 convention)
    ids = []
    for k in strict:
        g = ents(GOLD.get(k, set()))
        sets = cand_sets(pool, k)
        if all(k in R.get(r, {}) for r in pool) and all(score(sets[r], g) is not None for r in pool):
            ids.append(k)
    strategies = [f"single:{r}" for r in pool] + ["cascade", "centroid", "centroid+prior", "oracle"]
    print(f"\n=== pool: {pool_name}   n = {len(ids)} ===")
    for st in strategies:
        vals = []
        for k in ids:
            g = ents(GOLD[k]); sets = cand_sets(pool, k)
            if st == "oracle":
                v = max(score(sets[r], g) for r in pool)
            else:
                v = score(select(st, pool, sets), g)
            vals.append(v)
        acc = sum(vals) / len(vals) * 100
        exact = sum(v >= 0.999 for v in vals) / len(vals) * 100
        print(f"  {st:26s} entity Jaccard {acc:5.1f}   exact-match {exact:5.1f}%")
        rows_out.append(dict(pool=pool_name, strategy=st, n=len(ids), entity_jaccard=round(acc, 1), exact_match_pct=round(exact, 1)))

# agreement diagnostics: how often do candidates agree, and is agreement predictive of correctness?
pool = PRIOR
print("\n=== diagnostics (all 8 runs): pairwise agreement vs correctness ===")
buckets = collections.defaultdict(list)
for k in strict:
    g = ents(GOLD.get(k, set()))
    if not g: continue
    sets = cand_sets(pool, k)
    ne = [r for r in pool if sets.get(r)]
    if len(ne) < 2: continue
    for r in ne:
        partners = [jac(sets[r], sets[o]) or 0 for o in ne if o != r]
        agree = max(partners)
        b = "max agreement >= 0.9" if agree >= .9 else ">= 0.5" if agree >= .5 else "< 0.5"
        buckets[b].append(jac(sets[r], g) or 0)
for b in ["max agreement >= 0.9", ">= 0.5", "< 0.5"]:
    v = buckets[b]
    if v: print(f"  candidates with {b:22s}: n={len(v):5d}  mean entity Jaccard vs gold {sum(v)/len(v)*100:5.1f}")

# sanity: recomputed single-run scores vs the cached CSV scores
print("\n=== sanity: re-executed vs cached entity Jaccard (all strict rows defined in both) ===")
CACHED = {"zs-claude": "qlever_v2/results_claude.csv", "e2e-clean": "qlever_v2/results_e2e_clean.csv", "arm-idiom": "linked_idiom-qwen.csv"}
for run, f in CACHED.items():
    idc = "row_id" if run == "arm-idiom" else "index"
    cached = {r[idc]: r["jaccard_entity"] for r in csv.DictReader(open(f))}
    pairs = []
    for k in strict:
        c = cached.get(k); rec = R.get(run, {}).get(k)
        if c in (None, "", "na") or rec is None: continue
        v = score(ents(rec["values"]) if rec["ok"] else set(), ents(GOLD.get(k, set())))
        if v is None: continue
        pairs.append((float(c), v))
    if pairs:
        mc = sum(p[0] for p in pairs) / len(pairs) * 100; mr = sum(p[1] for p in pairs) / len(pairs) * 100
        print(f"  {run:10s} n={len(pairs)}  cached {mc:5.1f}  re-executed {mr:5.1f}  |diff| {abs(mc-mr):.1f}")

with open("results_tables/consensus_selection.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows_out[0])); w.writeheader(); w.writerows(rows_out)
print("\nwritten: results_tables/consensus_selection.csv")
