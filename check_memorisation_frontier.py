"""check_memorisation_frontier.py — Do the FROZEN frontier models reproduce
benchmark queries?
"""
import csv, json, re, collections, difflib
from check_memorisation import skeleton, best_similarity

csv.field_size_limit(10_000_000)
te = json.load(open("data/test.json"))
full = json.load(open("data/train.json")) + json.load(open("data/val.json")) + te
gold_sk = [skeleton(r["query"]) for r in te]
all_sk = [skeleton(r["query"]) for r in full]
test_offset = len(full) - len(te)          # test rows are last in `full`
index = collections.defaultdict(list)
for i, sk in enumerate(all_sk):
    for t in set(sk.split()):
        index[t].append(i)

strict = {r["index"] for r in csv.DictReader(open("data/gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}

RUNS = [("Zero-shot GPT-5.4", "outputs/qlever_v2/results_gpt-5.4.csv", "generated_query", "index"),
        ("Zero-shot Claude", "outputs/qlever_v2/results_claude.csv", "generated_query", "index"),
        ("Zero-shot Gemini", "outputs/qlever_v2/results_gemini.csv", "generated_query", "index"),
        ("Zero-shot DeepSeek", "outputs/qlever_v2/results_deepseek.csv", "generated_query", "index"),
        ("Few-shot Claude", "outputs/qlever_v2/results_fewshot_claude.csv", "generated_query", "index"),
        ("Pipeline e2e (Claude gen, clean)", "outputs/qlever_v2/results_e2e_clean.csv", "linked_query", "index"),
        ("Idiom arm (Claude gen, Qwen link)", "outputs/linked_idiom-qwen.json", None, None)]

def best_other(sk, own_i):
    """Best similarity to any dataset query except the row's own gold.
    Tokens are sorted so the candidate prefilter is deterministic across runs."""
    toks = sorted(set(sk.split())); cands = collections.Counter()
    for t in toks:
        for i in index.get(t, ())[:400]:
            if i != test_offset + own_i:
                cands[i] += 1
    pool = [i for i, _ in cands.most_common(60)]
    best = 0.0
    for i in pool:
        r = difflib.SequenceMatcher(None, sk, all_sk[i]).ratio()
        best = max(best, r)
    return best

cx = {str(i): r["complexity"] for i, r in enumerate(te)}
out = []
ctrl = []
print(f"{'run':34s} {'n':>4s} {'A ident':>8s} {'B>=.95':>7s} {'B>=.90':>7s} {'C mean':>7s} {'C>=.90':>7s} {'acc near':>9s} {'acc far':>8s}")
for name, path, qcol, icol in RUNS:
    if path.endswith(".json"):
        d = json.load(open(path))
        rows = {k: {"q": v.get("linked_query") or v.get("labeled_query", ""), "j": None} for k, v in d.items()}
        arm = {r["row_id"]: r for r in csv.DictReader(open("outputs/linked_idiom-qwen.csv"))}
        for k in rows:
            j = arm.get(k, {}).get("jaccard_entity")
            rows[k]["j"] = None if j in (None, "", "na") else float(j)
    else:
        rows = {}
        for r in csv.DictReader(open(path)):
            j = r.get("jaccard_entity")
            rows[r[icol]] = {"q": r[qcol], "j": None if j in (None, "", "na") else float(j)}
    recs = []
    for k, v in rows.items():
        if k not in strict or not v["q"]:
            continue
        i = int(k); sk = skeleton(v["q"])
        ident = sk == gold_sk[i]
        sim_own = difflib.SequenceMatcher(None, sk, gold_sk[i]).ratio()
        sim_oth = best_other(sk, i)
        recs.append((ident, sim_own, sim_oth, v["j"]))
        ctrl.append((name, cx[k], sim_oth >= .90, v["j"]))
    n = len(recs)
    A = sum(r[0] for r in recs) / n * 100
    B95 = sum(r[1] >= .95 for r in recs) / n * 100
    B90 = sum(r[1] >= .90 for r in recs) / n * 100
    Cm = sum(r[2] for r in recs) / n
    C90 = sum(r[2] >= .90 for r in recs) / n * 100
    near = [r[3] for r in recs if r[2] >= .90 and r[3] is not None]
    far = [r[3] for r in recs if r[2] < .90 and r[3] is not None]
    an = sum(near) / len(near) * 100 if near else float("nan")
    af = sum(far) / len(far) * 100 if far else float("nan")
    print(f"{name:34s} {n:4d} {A:7.1f}% {B95:6.1f}% {B90:6.1f}% {Cm:7.3f} {C90:6.1f}% {an:8.1f}% {af:7.1f}%")
    out.append(dict(run=name, n=n, identical_to_gold_pct=round(A, 1), sim_own_ge95_pct=round(B95, 1),
                    sim_own_ge90_pct=round(B90, 1), best_other_mean=round(Cm, 3), best_other_ge90_pct=round(C90, 1),
                    acc_near_structure=round(an, 1), acc_far_structure=round(af, 1), n_near=len(near), n_far=len(far)))

# control: is 'accuracy higher near a known structure' just simplicity? split by complexity
print("\nControl — accuracy near (>=.90) vs far a dataset structure, WITHIN each complexity class:")
print(f"{'run':34s} " + " ".join(f"{c:>22s}" for c in ["simple", "medium", "complex"]))
for name, *_ in RUNS:
    cells = []
    for c in ["simple", "medium", "complex"]:
        near = [j for n_, cc, nr, j in ctrl if n_ == name and cc == c and nr and j is not None]
        far = [j for n_, cc, nr, j in ctrl if n_ == name and cc == c and not nr and j is not None]
        f = lambda v: f"{sum(v)/len(v)*100:.0f}({len(v)})" if v else "—"
        cells.append(f"{f(near):>10s}/{f(far):<11s}")
    print(f"{name:34s} " + " ".join(cells))
print("  (cell = accuracy% near(n) / far(n))")

# reference rows: benchmark redundancy and the authors' fine-tuned model 
gold_recs = [best_other(gold_sk[i], i) for i in range(len(te)) if str(i) in strict]
print(f"\nReference — gold test queries vs rest of dataset: mean best similarity {sum(gold_recs)/len(gold_recs):.3f}, "
      f">=0.90 on {sum(s >= .90 for s in gold_recs)/len(gold_recs)*100:.1f}% of strict rows")
print("Reference — authors' mistral-7b-sparql (official split): 56% of outputs character-identical to gold.")
with open("results_tables/memorisation_frontier.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("written: results_tables/memorisation_frontier.csv")
