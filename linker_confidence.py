"""
"""
import json, csv, random, collections
random.seed(42)
B = 2000

gold = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
RUNS = [("Reasoning (Opus 4.8)", "outputs/preds_reasoning_clean.jsonl"),
        ("Reasoning (Qwen 14B)", "outputs/preds_qwen_full.jsonl"),
        ("Reasoning (Qwen 7B)", "outputs/preds_qwen7b_entity.jsonl"),
        ("GLiNKER (bi-encoder)", "outputs/preds_glinker_restricted_desc.jsonl"),
        ("ELQ (fine-tuned)", "outputs/preds_elq.jsonl"),
        ("ReFinED (fine-tuned)", "outputs/preds_refined.jsonl"),
        ("First search result", "outputs/preds_first_search_result.jsonl")]

preds = {}
for name, f in RUNS:
    p = collections.defaultdict(dict)
    for line in open(f):
        r = json.loads(line)
        p[int(r["index"])][(r["kind"], r["label"])] = r["pred_id"]
    preds[name] = p

# the shared mention list: every gold entity mention on rows all linkers scored
common = set.intersection(*[set(p) for p in preds.values()])
mentions = [(i, lab, gid) for i, ps in gold.items() if i in common
            for k, lab, gid in ps if k == "entity"]
print(f"{len(mentions)} entity mentions on {len(common)} rows scored by every linker\n")

def f1_on(idx, name):
    p = preds[name]; c = pr = g = 0
    for j in idx:
        i, lab, gid = mentions[j]
        pid = p[i].get(("entity", lab), "")
        g += 1
        if pid: pr += 1
        if pid == gid: c += 1
    if not pr or not g: return 0.0
    P, R = c / pr, c / g
    return 2 * P * R / (P + R) * 100 if P + R else 0.0

base = {n: f1_on(range(len(mentions)), n) for n, _ in RUNS}
draws = {n: [] for n, _ in RUNS}
N = len(mentions)
for _ in range(B):
    idx = [random.randrange(N) for _ in range(N)]      # one resample, all linkers
    for n, _ in RUNS:
        draws[n].append(f1_on(idx, n))

def pct(v, q): 
    s = sorted(v); return s[int(q * (len(s) - 1))]

out = []
print(f"{'linker':24s} {'F1':>6s} {'95% CI':>16s}")
for n, _ in RUNS:
    lo, hi = pct(draws[n], .025), pct(draws[n], .975)
    print(f"{n:24s} {base[n]:6.1f} [{lo:6.1f}, {hi:6.1f}]")
    out.append(dict(comparison=n, kind="F1", estimate=round(base[n], 1),
                    ci_low=round(lo, 1), ci_high=round(hi, 1), n_mentions=N, bootstrap_B=B))

print(f"\nPaired differences against the best specialised linker (GLiNKER):")
print(f"{'comparison':44s} {'diff':>7s} {'95% CI':>16s}")
def paired(ref, others):
    for n in others:
        d = [a - b for a, b in zip(draws[n], draws[ref])]
        lo, hi = pct(d, .025), pct(d, .975)
        est = base[n] - base[ref]
        print(f"{n + ' - ' + ref:44s} {est:+7.1f} [{lo:+6.1f}, {hi:+6.1f}]")
        out.append(dict(comparison=f"{n} - {ref}", kind="paired difference",
                        estimate=round(est, 1), ci_low=round(lo, 1), ci_high=round(hi, 1),
                        n_mentions=N, bootstrap_B=B))

reasoning = [n for n, _ in RUNS if n.startswith("Reasoning")]
paired("GLiNKER (bi-encoder)", reasoning)
print(f"\nPaired differences against the first search result:")
paired("First search result", reasoning)

with open("results_tables/linker_confidence.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("written: results_tables/linker_confidence.csv")
