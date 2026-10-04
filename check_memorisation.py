"""check_memorisation.py — Are the fine-tuned baselines generalising or
recalling?

Usage:  python3 check_memorisation.py
"""

import csv, json, re, collections, difflib

csv.field_size_limit(10_000_000)
SRC = "all_results.csv"
MODELS = ["mistral-7b-sparql", "llama3-8b-sparql"]

def norm_text(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()

def skeleton(q):
    """Reduce a query to its structural skeleton: drop prefixes, comments,
    identifiers, literals and variable names; keep keywords and shape."""
    if not q:
        return ""
    q = re.sub(r'#[^\n]*', ' ', q)
    q = re.sub(r'(?i)prefix\s+\S+\s*:\s*<[^>]*>', ' ', q)
    q = re.sub(r'"[^"]*"', '"L"', q)
    q = re.sub(r"'[^']*'", '"L"', q)
    q = re.sub(r'\bwd:Q\d+', 'wd:E', q)
    q = re.sub(r'\bwdt:P\d+', 'wdt:P', q)
    q = re.sub(r'\b[pP]s?v?:P\d+', 'p:P', q)
    q = re.sub(r'\bpq:P\d+', 'pq:P', q)
    q = re.sub(r'\[entity:[^\]]*\]', 'E', q)
    q = re.sub(r'\[property:[^\]]*\]', 'P', q)
    q = re.sub(r'\?\w+', '?v', q)
    q = re.sub(r'\d+', 'N', q)
    q = re.sub(r'\s+', ' ', q)
    return q.strip().lower()

def extract_query(text):
    if not text:
        return ""
    m = re.search(r'\[QUERY\](.*?)\[/QUERY\]', text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r'((?:PREFIX|SELECT|ASK|CONSTRUCT|DESCRIBE)\b.*)', text, re.S | re.I)
    return m.group(1).strip() if m else text.strip()

def best_similarity(sk, train_sks, train_index):
    """Highest difflib ratio against training skeletons, with a cheap
    token-overlap prefilter so this stays tractable."""
    if not sk:
        return 0.0, ""
    toks = sorted(set(sk.split()))   # sorted: keep the candidate prefilter deterministic
    cands = collections.Counter()
    for t in toks:
        for i in train_index.get(t, ())[:400]:
            cands[i] += 1
    pool = [i for i, _ in cands.most_common(60)] or range(min(200, len(train_sks)))
    best, bi = 0.0, ""
    for i in pool:
        r = difflib.SequenceMatcher(None, sk, train_sks[i]).ratio()
        if r > best:
            best, bi = r, train_sks[i]
    return best, bi

def main():
    from datasets import load_dataset
    ds = load_dataset("PaDaS-Lab/Instruct-to-SPARQL", "default")
    train_q = [r["sparql_query"] for r in ds["train"]]
    train_sks = [skeleton(q) for q in train_q]
    print(f"training queries: {len(train_sks)}")

    index = collections.defaultdict(list)
    for i, sk in enumerate(train_sks):
        for t in set(sk.split()):
            index[t].append(i)

    official = json.load(open("official_test.json"))
    by_instr = {norm_text(r["instruction"]): str(r["id"]) for r in official}
    gold_q = {str(r["id"]): r["query"] for r in official}

    scored = collections.defaultdict(dict)
    for r in csv.DictReader(open("results_authors_baselines.csv")):
        scored[r["model"]][r["row_id"]] = r

    # ── baseline: how redundant is the benchmark itself? ──────
    print("\n1. GOLD test queries vs training queries (benchmark redundancy)")
    sims = []
    for r in official:
        s, _ = best_similarity(skeleton(r["query"]), train_sks, index)
        sims.append(s)
    def band(v):
        return (">=0.95" if v >= .95 else ">=0.90" if v >= .90 else
                ">=0.80" if v >= .80 else "<0.80")
    c = collections.Counter(band(s) for s in sims)
    for k in [">=0.95", ">=0.90", ">=0.80", "<0.80"]:
        print(f"   {k:8s} {c[k]:4d}  ({c[k]/len(sims)*100:.1f}%)")
    print(f"   mean best similarity: {sum(sims)/len(sims):.3f}")

    # ── per fine-tuned model ──────────────────────────────────
    rows = list(csv.DictReader(open(SRC)))
    for model in MODELS:
        sel = [r for r in rows if r["model"] == model and r["annotated"] == "False"]
        if not sel:
            print(f"\n{model}: not found in {SRC}")
            continue
        print(f"\n2. {model}: generated queries vs training queries")
        recs = []
        for r in sel:
            rid = by_instr.get(norm_text(r["user_instruction"]))
            if rid is None:
                continue
            sk = skeleton(extract_query(r["generated_query"]))
            s, _ = best_similarity(sk, train_sks, index)
            sc = scored.get(model, {}).get(rid)
            j = float(sc["jaccard_pooled"]) if sc and sc["jaccard_pooled"] not in ("", "na") else None
            recs.append((rid, s, j))
        c = collections.Counter(band(s) for _, s, _ in recs)
        for k in [">=0.95", ">=0.90", ">=0.80", "<0.80"]:
            print(f"   {k:8s} {c[k]:4d}  ({c[k]/len(recs)*100:.1f}%)")
        print(f"   mean best similarity: {sum(s for _, s, _ in recs)/len(recs):.3f}")

        hi = [j for _, s, j in recs if s >= 0.90 and j is not None]
        lo = [j for _, s, j in recs if s < 0.90 and j is not None]
        f = lambda v: f"{sum(v)/len(v)*100:.1f}% (n={len(v)})" if v else "—"
        print(f"   accuracy where a near-identical training structure exists: {f(hi)}")
        print(f"   accuracy where it does not:                                {f(lo)}")

    print("\nReading: if accuracy is far higher on rows whose structure already")
    print("appears in training, the fine-tuned advantage rests substantially on")
    print("structural recall. Compare against the gold-query redundancy in (1):")
    print("that is the ceiling any model could exploit.")

if __name__ == "__main__":
    main()
