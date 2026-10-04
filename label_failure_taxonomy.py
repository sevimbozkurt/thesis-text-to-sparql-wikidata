"""
"""
import json, re, csv, collections

def flat_pool(path):
    """Return {kind|label: candidates}. Handles both pool layouts in this repo."""
    d = json.load(open(path))
    first = next(iter(d.values()))
    if isinstance(first, list):                      # already kind|label keyed
        return d
    out = {}                                         # per-row: {row: {kind: {label: cands}}}
    for row in d.values():
        for kind, labels in row.items():
            if isinstance(labels, dict):
                for lab, cands in labels.items():
                    out[f"{kind}|{lab}"] = cands
    return out

POOLS = [("Qwen2.5-14B (open)", "pool_qwen-qwen2-5-14b-instruct_official.json"),
         ("frontier model",     "batch_candidates.json")]

def classify(label):
    if re.fullmatch(r"[PQ]\d+", label):                       return "bare identifier"
    if re.search(r"[a-z][A-Z]", label) and " " not in label:  return "camelCase / RDF style"
    if "_" in label:                                          return "snake_case"
    if len(label.split()) >= 5:                               return "verbose paraphrase"
    if re.search(r"\b(ID|URL|URI|identifier)\b", label):      return "qualified / suffixed name"
    return "near-miss wording"

out, summary = [], {}
for name, path in POOLS:
    pool = flat_pool(path)
    unfindable = [k for k, v in pool.items() if not v]
    cats, ex = collections.Counter(), collections.defaultdict(list)
    for key in unfindable:
        kind, _, label = key.partition("|")
        c = classify(label); cats[c] += 1
        if len(ex[c]) < 4: ex[c].append(label)
    summary[name] = (len(pool), len(unfindable), cats, ex)

print("Official split, both backbones, deduplicated unique labels:\n")
print(f"{'backbone':22s} {'unique labels':>14s} {'unfindable':>11s} {'rate':>7s}")
for name, (tot, un, _, _) in summary.items():
    print(f"{name:22s} {tot:14d} {un:11d} {un/tot*100:6.1f}%")
qt, qu = summary["Qwen2.5-14B (open)"][0], summary["Qwen2.5-14B (open)"][1]
ft, fu = summary["frontier model"][0], summary["frontier model"][1]
print(f"\nratio of unfindable rates: {(qu/qt)/(fu/ft):.1f}x")
print(f"distinct labels generated for the same questions: {qt/ft:.1f}x more for the open model")

for name, (tot, un, cats, ex) in summary.items():
    print(f"\n{name} — {un} unfindable labels")
    print(f"  {'category':26s} {'n':>4s} {'%':>6s}  examples")
    for c, n in cats.most_common():
        print(f"  {c:26s} {n:4d} {n/un*100:5.1f}%  {'; '.join(ex[c][:2])[:52]}")
        out.append(dict(backbone=name, category=c, n=n, pct_of_unfindable=round(n / un * 100, 1),
                        unique_labels=tot, total_unfindable=un,
                        unfindable_rate_pct=round(un / tot * 100, 1),
                        examples="; ".join(ex[c])))

with open("results_tables/label_failure_taxonomy.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("written: results_tables/label_failure_taxonomy.csv")
