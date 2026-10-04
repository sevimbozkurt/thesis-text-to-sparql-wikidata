"""construct_analysis.py — Corpus-wide analysis of Wikidata modelling
constructs.

Usage:  python3 construct_analysis.py
"""

import csv, json, re, os, collections

# Construct detectors. Two variants: identifier form (gold, executed queries)
# and label form (the pipeline's labelled queries, before substitution).
PATTERNS = {
    "subclass closure (P279*)":   (r'P279\s*\*',              r'subclass of\]\s*\*'),
    "statement node (p:)":        (r'\bp:P\d+',               r'\bp:\['),
    "qualifier (pq:)":            (r'\bpq:P\d+',              r'\bpq:\['),
    "value node (psv:)":          (r'\bpsv:P\d+',             r'\bpsv:\['),
    "aggregation (GROUP BY)":     (r'(?i)\bgroup by\b',       r'(?i)\bgroup by\b'),
    "alternation (VALUES/UNION)": (r'(?i)\bvalues\b|\bunion\b', r'(?i)\bvalues\b|\bunion\b'),
    "property path (/ or |)":     (r'wdt:P\d+\s*[/|]',        r'\]\s*[/|]'),
    "LIMIT":                      (r'(?i)\blimit\b',          r'(?i)\blimit\b'),
    "OPTIONAL":                   (r'(?i)\boptional\b',       r'(?i)\boptional\b'),
    "FILTER":                     (r'(?i)\bfilter\b',         r'(?i)\bfilter\b'),
}

def uses(query, name, labelled):
    if not query:
        return False
    pat = PATTERNS[name][1 if labelled else 0]
    return bool(re.search(pat, query))

def load_runs():
    """Return {run_name: {index: (query, is_labelled)}}"""
    test = json.load(open("test.json"))
    runs = collections.OrderedDict()
    runs["GOLD"] = {i: (r["query"], False) for i, r in enumerate(test)}

    for name, path in [("zero-shot GPT-5.4", "results_gpt-5.4.csv"),
                       ("zero-shot Claude", "results_claude.csv"),
                       ("zero-shot Gemini", "results_gemini.csv"),
                       ("zero-shot DeepSeek", "results_deepseek.csv"),
                       ("few-shot GPT-5.4", "results_fewshot_gpt-5.4.csv"),
                       ("few-shot Claude", "results_fewshot_claude.csv"),
                       ("few-shot Gemini", "results_fewshot_gemini.csv"),
                       ("few-shot DeepSeek", "results_fewshot_deepseek.csv")]:
        if os.path.exists(path):
            runs[name] = {int(r["index"]): (r["generated_query"], False)
                          for r in csv.DictReader(open(path))}

    p = "qlever/results_e2e_regen.csv"
    if os.path.exists(p):
        runs["pipeline (labelled)"] = {int(r["index"]): (r["labeled_query"], True)
                                       for r in csv.DictReader(open(p))}
    if os.path.exists("idiom_generated.json"):
        g = json.load(open("idiom_generated.json"))
        runs["idiom prompt (labelled)"] = {int(k): (v, True) for k, v in g.items()}
    return runs

def main():
    runs = load_runs()
    names = list(PATTERNS)
    gold = runs["GOLD"]
    n_rows = len(gold)

    # ── A. usage counts ───────────────────────────────────────
    print(f"A. CONSTRUCT USAGE — counts over {n_rows} questions\n")
    header = f"{'construct':28s}" + "".join(f"{r[:11]:>12s}" for r in runs)
    print(header)
    print("-" * len(header))
    table = []
    for c in names:
        row = [c]
        line = f"{c:28s}"
        for rn, rows in runs.items():
            k = sum(1 for i, (q, lab) in rows.items() if uses(q, c, lab))
            row.append(k)
            line += f"{k:12d}"
        print(line)
        table.append(row)

    # ── B. agreement with gold ────────────────────────────────
    print(f"\n\nB. AGREEMENT WITH GOLD — does the system use a construct")
    print("   exactly when the gold query does? (per-query P / R / F1)\n")
    print(f"{'construct':28s}" + "".join(f"{r[:11]:>12s}" for r in runs if r != "GOLD"))
    print("-" * (28 + 12 * (len(runs) - 1)))
    agree = []
    for c in names:
        line = f"{c:28s}"
        row = [c]
        for rn, rows in runs.items():
            if rn == "GOLD":
                continue
            tp = fp = fn = 0
            for i, (gq, _) in gold.items():
                if i not in rows:
                    continue
                q, lab = rows[i]
                g_use, m_use = uses(gq, c, False), uses(q, c, lab)
                if g_use and m_use: tp += 1
                elif m_use and not g_use: fp += 1
                elif g_use and not m_use: fn += 1
            P = tp / (tp + fp) * 100 if tp + fp else 0
            R = tp / (tp + fn) * 100 if tp + fn else 0
            F = 2 * P * R / (P + R) if P + R else 0
            line += f"{F:11.0f}%"
            row.append(round(F, 1))
        print(line)
        agree.append(row)

    with open("construct_analysis.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["USAGE COUNTS"])
        w.writerow(["construct"] + list(runs))
        w.writerows(table)
        w.writerow([])
        w.writerow(["AGREEMENT WITH GOLD (F1 of construct use)"])
        w.writerow(["construct"] + [r for r in runs if r != "GOLD"])
        w.writerows(agree)
    print("\nwritten construct_analysis.csv")
    print("\nReading: low usage vs GOLD = under-use of the idiom; usage above")
    print("GOLD with low agreement F1 = the construct is applied, but not where")
    print("the question requires it (mis-calibration rather than ignorance).")

if __name__ == "__main__":
    main()
