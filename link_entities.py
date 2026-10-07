"""link_entities.py — TIER 2, Step (b): Entity & Predicate Linking on GOLD
labels.

Usage:
    python3 link_entities.py --limit 10        # quick test
    python3 link_entities.py                   # full test set
"""

import json, time, requests, csv, os, re, argparse
from openai import OpenAI

# ── API KEY ───────────────────────────────────────────────
OPENROUTER_KEY = "API KEY HERE"
MODEL = "anthropic/claude-opus-4.8"

# ── SETTINGS ───────────────────────────────────────────────────
API_DELAY      = 2.0
WIKIDATA_DELAY = 1.0
SEARCH_DELAY   = 0.5
TIMEOUT        = 30
N_CANDIDATES   = 7      # candidates to fetch per label
# ──────────────────────────────────────────────────────────────

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_API    = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/1.0 (master thesis research)"}

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)


# ─────────────────────────────────────────────────────────────
# STEP 1: Parse labels out of the annotated query
# ─────────────────────────────────────────────────────────────
def parse_labels(annotated):
    """
    Find all  wd:[entity:LABEL]  and  wdt:[property:LABEL]  (and p:, ps:, etc).
    Returns two lists: entity_labels, predicate_labels (deduplicated, order-preserved).
    """
    # entity labels:  wd:[entity:...]
    entity_labels = re.findall(r'\[entity:([^\]]+)\]', annotated)
    # predicate labels: [property:...]
    predicate_labels = re.findall(r'\[property:([^\]]+)\]', annotated)

    # dedupe, preserve order
    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x.lower() not in seen:
                seen.add(x.lower())
                out.append(x)
        return out

    return dedupe(entity_labels), dedupe(predicate_labels)


# ─────────────────────────────────────────────────────────────
# STEP 2: Wikidata Search API → candidates
# ─────────────────────────────────────────────────────────────
def search_wikidata(label, is_property=False):
    """
    Query Wikidata search API for a label.
    Returns list of {id, label, description}.
    """
    time.sleep(SEARCH_DELAY)
    params = {
        "action": "wbsearchentities",
        "search": label,
        "language": "en",
        "format": "json",
        "limit": N_CANDIDATES,
        "type": "property" if is_property else "item",
    }
    try:
        r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        out = []
        for item in data.get("search", []):
            out.append({
                "id":          item.get("id", ""),
                "label":       item.get("label", ""),
                "description": item.get("description", ""),
            })
        return out
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# STEP 3: CoT disambiguation with Claude
# ─────────────────────────────────────────────────────────────
def disambiguate(question, label, candidates, is_property=False):
    """
    Ask Claude to pick the best candidate ID using chain-of-thought reasoning.
    Returns the chosen ID (e.g. 'Q25191' or 'P57'), or '' if none fit.
    """
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]["id"]

    kind = "property" if is_property else "entity"
    cand_text = "\n".join(
        f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
        for c in candidates
    )
    prompt = f"""Question: "{question}"

I need to find the correct Wikidata {kind} ID for the {kind} mention: "{label}"

Candidates:
{cand_text}

Think step by step about which candidate best matches the {kind} "{label}" in the
context of the question. Then output ONLY the chosen ID (e.g. {"P57" if is_property else "Q25191"})
on the last line, prefixed with "ANSWER: ".
"""
    time.sleep(API_DELAY)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
        )
        text = resp.choices[0].message.content or ""
        # Extract the ID after "ANSWER:"
        m = re.search(r'ANSWER:\s*([QP]\d+)', text)
        if m:
            return m.group(1)
        # fallback: first valid ID mentioned
        m2 = re.search(r'\b([QP]\d+)\b', text)
        return m2.group(1) if m2 else candidates[0]["id"]
    except Exception:
        return candidates[0]["id"]   # fallback to top search hit


# ─────────────────────────────────────────────────────────────
# STEP 4: Substitute IDs back into the query
# ─────────────────────────────────────────────────────────────
def substitute(annotated, entity_map, predicate_map):
    """Replace [entity:X] → Qid and [property:Y] → Pid in the query."""
    out = annotated
    for label, qid in entity_map.items():
        out = re.sub(r'\[entity:' + re.escape(label) + r'\]', qid, out, flags=re.IGNORECASE)
    for label, pid in predicate_map.items():
        out = re.sub(r'\[property:' + re.escape(label) + r'\]', pid, out, flags=re.IGNORECASE)
    return out


# ─────────────────────────────────────────────────────────────
# STEP 5: Execute on Wikidata
# ─────────────────────────────────────────────────────────────
def run_sparql(query):
    time.sleep(WIKIDATA_DELAY)
    try:
        r = requests.get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code != 200:
            return False, set()
        bindings = r.json().get("results", {}).get("bindings", [])
        values = set()
        for row in bindings:
            for v in row.values():
                val = v.get("value", "")
                if "wikidata.org/entity/" in val:
                    val = val.split("/")[-1]
                values.add(val)
        return True, values
    except Exception:
        return False, set()


def jaccard(a, b):
    if not a and not b: return 1.0
    if not a or not b:  return 0.0
    return len(a & b) / len(a | b)


# ─────────────────────────────────────────────────────────────
# Main pipeline per query
# ─────────────────────────────────────────────────────────────
def link_one(ex):
    annotated = ex["annotated"]
    question  = ex["instruction"]

    entity_labels, predicate_labels = parse_labels(annotated)

    entity_map, predicate_map = {}, {}
    for lbl in entity_labels:
        cands = search_wikidata(lbl, is_property=False)
        entity_map[lbl] = disambiguate(question, lbl, cands, is_property=False)
    for lbl in predicate_labels:
        cands = search_wikidata(lbl, is_property=True)
        predicate_map[lbl] = disambiguate(question, lbl, cands, is_property=True)

    linked_query = substitute(annotated, entity_map, predicate_map)

    # Did we resolve everything? (no leftover [ ] brackets)
    fully_linked = "[entity:" not in linked_query and "[property:" not in linked_query

    syntax, pred_vals = (False, set())
    if fully_linked:
        syntax, pred_vals = run_sparql(linked_query)

    return {
        "linked_query": linked_query,
        "fully_linked": fully_linked,
        "syntax":       syntax,
        "pred_vals":    pred_vals,
        "n_entities":   len(entity_labels),
        "n_predicates": len(predicate_labels),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    with open("data/test.json") as f:
        test = json.load(f)
    rows_all = test[:args.limit] if args.limit else test

    outfile = "outputs/results_linking.csv"
    done = set()
    if os.path.exists(outfile):
        with open(outfile) as f:
            done = {int(r["index"]) for r in csv.DictReader(f)}
        print(f"Resuming — {len(done)} rows done")

    fields = ["index", "complexity", "instruction", "linked_query",
              "fully_linked", "syntax", "jaccard", "n_entities", "n_predicates"]

    with open(outfile, "a" if done else "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not done:
            writer.writeheader()

        for i, ex in enumerate(rows_all):
            if i in done:
                continue
            try:
                res = link_one(ex)
            except Exception as e:
                print(f"  [{i}] error: {str(e)[:80]}")
                continue

            # Jaccard vs gold results
            jac = 0.0
            if res["syntax"]:
                _, gold_vals = run_sparql(ex["query"])
                jac = jaccard(res["pred_vals"], gold_vals)

            writer.writerow({
                "index":        i,
                "complexity":   ex["complexity"],
                "instruction":  ex["instruction"],
                "linked_query": res["linked_query"],
                "fully_linked": res["fully_linked"],
                "syntax":       res["syntax"],
                "jaccard":      round(jac, 4),
                "n_entities":   res["n_entities"],
                "n_predicates": res["n_predicates"],
            })
            f.flush()

            if (i + 1) % 5 == 0:
                print(f"  {i+1}/{len(rows_all)} done")

    # Summary
    rows = list(csv.DictReader(open(outfile)))
    total       = len(rows)
    linked      = sum(1 for r in rows if r["fully_linked"] == "True") / total * 100
    syntax_pct  = sum(1 for r in rows if r["syntax"] == "True") / total * 100
    jaccard_pct = sum(float(r["jaccard"]) for r in rows) / total * 100

    print(f"\n{'='*50}")
    print(f"ENTITY LINKING ON GOLD LABELS — {MODEL}")
    print(f"{'='*50}")
    print(f"Fully linked (all IDs resolved): {linked:.1f}%")
    print(f"Syntax (executes on Wikidata)  : {syntax_pct:.1f}%")
    print(f"Jaccard                        : {jaccard_pct:.1f}%")
    print()
    print(f"{'Complexity':<10} {'N':>5} {'Linked':>8} {'Syntax':>8} {'Jaccard':>9}")
    print('-' * 44)
    for c in ["simple", "medium", "complex"]:
        sub = [r for r in rows if r["complexity"] == c]
        if not sub:
            continue
        l = sum(1 for r in sub if r["fully_linked"] == "True") / len(sub) * 100
        s = sum(1 for r in sub if r["syntax"] == "True") / len(sub) * 100
        j = sum(float(r["jaccard"]) for r in sub) / len(sub) * 100
        print(f"{c:<10} {len(sub):>5} {l:>7.1f}% {s:>7.1f}% {j:>8.1f}%")

    print(f"\n>> Compare this Jaccard to the zero-shot baseline (~18%).")
    print(f">> If higher, the linking approach works and is worth scaling up.")


if __name__ == "__main__":
    main()
