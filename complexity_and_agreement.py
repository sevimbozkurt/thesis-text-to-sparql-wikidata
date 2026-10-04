"""complexity_and_agreement.py — Two free analyses (no API, no endpoint calls).

Usage:  python3 complexity_and_agreement.py
"""

import csv, json, re, os, math, collections

STRICT_FILE = "gold_status_qlever.csv"
E2E = "results_e2e_clean.csv"          # falls back to the regenerated file
JCOL = "jaccard_entity"

FEATURES = {
    "path operator (/ or |)":   lambda q: len(re.findall(r'wdt:P\d+\s*[/|]|\)\s*[/|]', q)),
    "transitive star (*)":      lambda q: len(re.findall(r'P\d+\s*\*', q)),
    "statement node (p:)":      lambda q: len(re.findall(r'\bp:P\d+', q)),
    "qualifier (pq:)":          lambda q: len(re.findall(r'\bpq:P\d+', q)),
    "value node (psv:)":        lambda q: len(re.findall(r'\bpsv:P\d+', q)),
    "aggregation":              lambda q: len(re.findall(r'(?i)\b(count|sum|avg|min|max)\s*\(', q)),
    "GROUP BY":                 lambda q: len(re.findall(r'(?i)\bgroup by\b', q)),
    "alternation (VALUES/UNION)": lambda q: len(re.findall(r'(?i)\b(values|union)\b', q)),
    "subquery":                 lambda q: q.count("{") > 3 and len(re.findall(r'(?i)\bselect\b', q)) > 1,
    "OPTIONAL":                 lambda q: len(re.findall(r'(?i)\boptional\b', q)),
    "FILTER":                   lambda q: len(re.findall(r'(?i)\bfilter\b', q)),
    "triples (approx)":         lambda q: len(re.findall(r'\?\w+\s+(?:wdt:|p:|ps:|pq:|rdfs:)', q)),
    "projected vars":           lambda q: len(set(re.findall(r'\?(\w+)',
                                    re.search(r'(?i)select(.*?)where', q, re.S).group(1)))) 
                                    if re.search(r'(?i)select(.*?)where', q, re.S) else 0,
}

def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a-mx)**2 for a in rx) * sum((b-my)**2 for b in ry))
    return num/den if den else None

def main():
    test = json.load(open("test.json"))
    strict, cx = set(), {}
    for r in csv.DictReader(open(STRICT_FILE)):
        i = int(r["index"]); cx[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

    path = E2E if os.path.exists(E2E) else "qlever/results_e2e_regen.csv"
    col = JCOL if path == E2E else "jaccard_new"
    acc = {}
    for r in csv.DictReader(open(path)):
        i = int(r["index"])
        v = r.get(col, "")
        if i in strict and v not in ("na", "", None):
            acc[i] = float(v)
    print(f"accuracy source: {path} ({col}), {len(acc)} scored strict rows\n")

    feats = {}
    for i in acc:
        q = test[i]["query"]
        feats[i] = {name: (1 if isinstance(fn(q), bool) and fn(q) else
                           (0 if isinstance(fn(q), bool) else fn(q)))
                    for name, fn in FEATURES.items()}

    # ── PART 1 ────────────────────────────────────────────────
    print("PART 1 — structural features of the GOLD query vs achieved accuracy\n")
    print(f"{'feature':28s} {'n present':>9} {'acc present':>12} {'acc absent':>11} "
          f"{'gap':>7} {'rho':>7}")
    print("-" * 78)
    rows = []
    for name in FEATURES:
        pres = [acc[i] for i in acc if feats[i][name] > 0]
        absn = [acc[i] for i in acc if feats[i][name] == 0]
        if not pres or not absn:
            continue
        mp, ma = sum(pres)/len(pres)*100, sum(absn)/len(absn)*100
        xs = [feats[i][name] for i in acc]
        ys = [acc[i] for i in acc]
        rho = spearman(xs, ys)
        print(f"{name:28s} {len(pres):9d} {mp:11.1f}% {ma:10.1f}% "
              f"{mp-ma:+6.1f} {('%.2f' % rho) if rho is not None else '—':>7}")
        rows.append([name, len(pres), round(mp,1), round(ma,1), round(mp-ma,1),
                     round(rho,3) if rho is not None else ""])
    with open("complexity_features.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["feature", "n questions with feature", "mean acc present (%)",
                    "mean acc absent (%)", "gap (pp)", "spearman rho"])
        w.writerows(rows)

    # ── PART 2 ────────────────────────────────────────────────
    runs = {}
    for name, p in [("GPT-5.4", "qlever_v2/results_gpt-5.4.csv"),
                    ("Claude", "qlever_v2/results_claude.csv"),
                    ("Gemini", "qlever_v2/results_gemini.csv"),
                    ("DeepSeek", "qlever_v2/results_deepseek.csv")]:
        if os.path.exists(p):
            runs[name] = {int(r["index"]): r for r in csv.DictReader(open(p))}
    if len(runs) < 2:
        print("\n(skipping Part 2 — baseline files not found in qlever_v2/)")
        return

    common = set.intersection(*[set(r) for r in runs.values()]) & strict
    def solved(r):
        v = r.get("jaccard_entity", r.get("jaccard_pooled", "0"))
        try:
            return float(v) >= 0.5
        except ValueError:
            return False

    tally = collections.Counter()
    per_q = {}
    for i in common:
        k = sum(1 for rn in runs if solved(runs[rn][i]))
        tally[k] += 1
        per_q[i] = k

    print(f"\n\nPART 2 — how many of the {len(runs)} zero-shot models solve each "
          f"question (Jaccard >= 0.5), n = {len(common)}\n")
    for k in range(len(runs) + 1):
        n = tally[k]
        print(f"  solved by {k}/{len(runs)} models: {n:4d} ({n/len(common)*100:5.1f}%)")
    hard = [i for i, k in per_q.items() if k == 0]
    easy = [i for i, k in per_q.items() if k == len(runs)]
    print(f"\nintrinsically hard (no model): {len(hard)}  |  solved by all: {len(easy)}")
    print(f"complexity of the hard set: "
          f"{dict(collections.Counter(cx[i] for i in hard))}")
    print(f"complexity of the easy set: "
          f"{dict(collections.Counter(cx[i] for i in easy))}")

    print(f"\nstructural features: hard set vs easy set (mean count per query)")
    print(f"{'feature':28s} {'hard':>8} {'easy':>8}")
    arows = []
    for name, fn in FEATURES.items():
        def m(ids):
            vals = []
            for i in ids:
                v = fn(test[i]["query"])
                vals.append(1 if v is True else (0 if v is False else v))
            return sum(vals)/len(vals) if vals else 0
        h, e = m(hard), m(easy)
        print(f"{name:28s} {h:8.2f} {e:8.2f}")
        arows.append([name, round(h,2), round(e,2)])
    with open("agreement_analysis.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["questions solved by k models", "count"])
        for k in range(len(runs)+1):
            w.writerow([k, tally[k]])
        w.writerow([])
        w.writerow(["feature", "mean in hard set", "mean in easy set"])
        w.writerows(arows)
    print("\nwritten complexity_features.csv, agreement_analysis.csv")

if __name__ == "__main__":
    main()
