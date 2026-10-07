"""pipeline_e2e.py — TIER 2 FULL: End-to-end KGQA pipeline (generation +
linking).

Usage:
    python3 pipeline_e2e.py --limit 10
    python3 pipeline_e2e.py
"""

import json, time, requests, csv, os, re, argparse
from openai import OpenAI

# ── YOUR API KEY ───────────────────────────────────────────────
OPENROUTER_KEY = "API KEY HERE"
MODEL = "anthropic/claude-opus-4.8"

# ── SETTINGS ───────────────────────────────────────────────────
API_DELAY      = 2.0
WIKIDATA_DELAY = 1.0
SEARCH_DELAY   = 0.5
TIMEOUT        = 30
N_CANDIDATES   = 7
MAX_TOKENS     = 1024
# ──────────────────────────────────────────────────────────────

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_API    = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/1.0 (master thesis research)"}

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)


# ─────────────────────────────────────────────────────────────
# STEP 1: Generate a LABELED SPARQL query
# ─────────────────────────────────────────────────────────────
GEN_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""

def generate_labeled_query(question):
    time.sleep(API_DELAY)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": GEN_SYSTEM},
                {"role": "user",   "content": f"Question: {question}"}
            ],
            max_tokens=MAX_TOKENS,
            temperature=0,
        )
        text = resp.choices[0].message.content or ""
        # strip markdown fences
        if "```" in text:
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return text.strip()
    except Exception as e:
        return ""


# ─────────────────────────────────────────────────────────────
# STEP 2: Parse labels
# ─────────────────────────────────────────────────────────────
def parse_labels(query):
    entity_labels = re.findall(r'\[entity:([^\]]+)\]', query)
    predicate_labels = re.findall(r'\[property:([^\]]+)\]', query)
    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
        return out
    return dedupe(entity_labels), dedupe(predicate_labels)


# ─────────────────────────────────────────────────────────────
# STEP 3: Wikidata Search
# ─────────────────────────────────────────────────────────────
def search_wikidata(label, is_property=False):
    time.sleep(SEARCH_DELAY)
    params = {
        "action": "wbsearchentities", "search": label, "language": "en",
        "format": "json", "limit": N_CANDIDATES,
        "type": "property" if is_property else "item",
    }
    try:
        r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=15)
        return [{"id": it.get("id",""), "label": it.get("label",""),
                 "description": it.get("description","")}
                for it in r.json().get("search", [])]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# STEP 4: CoT disambiguation
# ─────────────────────────────────────────────────────────────
def disambiguate(question, label, candidates, is_property=False):
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]["id"]
    kind = "property" if is_property else "entity"
    cand_text = "\n".join(
        f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
        for c in candidates)
    example_id = "P57" if is_property else "Q25191"
    prompt = f"""Question: "{question}"

Find the correct Wikidata {kind} ID for: "{label}"

Candidates:
{cand_text}

Think step by step about which candidate best fits the {kind} "{label}" in the
context of the question. Output ONLY the chosen ID (e.g. {example_id}) on the last
line, prefixed with "ANSWER: ".
"""
    time.sleep(API_DELAY)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0,
        )
        text = resp.choices[0].message.content or ""
        m = re.search(r'ANSWER:\s*([QP]\d+)', text)
        if m: return m.group(1)
        m2 = re.search(r'\b([QP]\d+)\b', text)
        return m2.group(1) if m2 else candidates[0]["id"]
    except Exception:
        return candidates[0]["id"]


# ─────────────────────────────────────────────────────────────
# STEP 5: Substitute
# ─────────────────────────────────────────────────────────────
def substitute(query, entity_map, predicate_map):
    out = query
    for label, qid in entity_map.items():
        if qid:
            out = re.sub(r'\[entity:' + re.escape(label) + r'\]', qid, out, flags=re.IGNORECASE)
    for label, pid in predicate_map.items():
        if pid:
            out = re.sub(r'\[property:' + re.escape(label) + r'\]', pid, out, flags=re.IGNORECASE)
    return out


# ─────────────────────────────────────────────────────────────
# STEP 6: Execute
# ─────────────────────────────────────────────────────────────
def run_sparql(query):
    time.sleep(WIKIDATA_DELAY)
    try:
        r = requests.get(WIKIDATA_SPARQL, params={"query": query, "format": "json"},
                         headers=HEADERS, timeout=TIMEOUT)
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
# Full pipeline for one question
# ─────────────────────────────────────────────────────────────
def pipeline_one(ex):
    question = ex["instruction"]

    # [1] generate labeled query
    labeled = generate_labeled_query(question)
    if not labeled:
        return {"labeled_query": "", "linked_query": "", "generated_ok": False,
                "fully_linked": False, "syntax": False, "pred_vals": set()}

    # [2] parse
    ent_labels, pred_labels = parse_labels(labeled)

    # [3+4] search + disambiguate
    entity_map, predicate_map = {}, {}
    for lbl in ent_labels:
        entity_map[lbl] = disambiguate(question, lbl,
                                       search_wikidata(lbl, False), False)
    for lbl in pred_labels:
        predicate_map[lbl] = disambiguate(question, lbl,
                                          search_wikidata(lbl, True), True)

    # [5] substitute
    linked = substitute(labeled, entity_map, predicate_map)
    fully_linked = "[entity:" not in linked and "[property:" not in linked

    # [6] execute
    syntax, pred_vals = (False, set())
    if fully_linked:
        syntax, pred_vals = run_sparql(linked)

    return {"labeled_query": labeled, "linked_query": linked, "generated_ok": True,
            "fully_linked": fully_linked, "syntax": syntax, "pred_vals": pred_vals}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    with open("data/test.json") as f:
        test = json.load(f)
    rows_all = test[:args.limit] if args.limit else test

    outfile = "outputs/results_e2e.csv"
    done = set()
    if os.path.exists(outfile):
        with open(outfile) as f:
            done = {int(r["index"]) for r in csv.DictReader(f)}
        print(f"Resuming — {len(done)} rows done")

    fields = ["index", "complexity", "instruction", "labeled_query",
              "linked_query", "generated_ok", "fully_linked", "syntax", "jaccard"]

    with open(outfile, "a" if done else "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not done:
            writer.writeheader()

        for i, ex in enumerate(rows_all):
            if i in done:
                continue
            try:
                res = pipeline_one(ex)
            except Exception as e:
                print(f"  [{i}] error: {str(e)[:80]}")
                continue

            jac = 0.0
            if res["syntax"]:
                _, gold_vals = run_sparql(ex["query"])
                jac = jaccard(res["pred_vals"], gold_vals)

            writer.writerow({
                "index": i, "complexity": ex["complexity"],
                "instruction": ex["instruction"],
                "labeled_query": res["labeled_query"],
                "linked_query": res["linked_query"],
                "generated_ok": res["generated_ok"],
                "fully_linked": res["fully_linked"],
                "syntax": res["syntax"], "jaccard": round(jac, 4),
            })
            f.flush()

            if (i + 1) % 5 == 0:
                print(f"  {i+1}/{len(rows_all)} done")

    # Summary
    rows = list(csv.DictReader(open(outfile)))
    total = len(rows)
    gen   = sum(1 for r in rows if r["generated_ok"] == "True") / total * 100
    link  = sum(1 for r in rows if r["fully_linked"] == "True") / total * 100
    syn   = sum(1 for r in rows if r["syntax"] == "True") / total * 100
    jac   = sum(float(r["jaccard"]) for r in rows) / total * 100

    print(f"\n{'='*52}")
    print(f"END-TO-END PIPELINE — {MODEL}")
    print(f"{'='*52}")
    print(f"Generated labeled query : {gen:.1f}%")
    print(f"Fully linked (IDs found): {link:.1f}%")
    print(f"Syntax (executes)       : {syn:.1f}%")
    print(f"Jaccard (RESULT ACCURACY): {jac:.1f}%")
    print()
    print(f"{'Complexity':<10} {'N':>5} {'Linked':>8} {'Syntax':>8} {'Jaccard':>9}")
    print('-' * 44)
    for c in ["simple", "medium", "complex"]:
        sub = [r for r in rows if r["complexity"] == c]
        if not sub: continue
        l = sum(1 for r in sub if r["fully_linked"] == "True") / len(sub) * 100
        s = sum(1 for r in sub if r["syntax"] == "True") / len(sub) * 100
        j = sum(float(r["jaccard"]) for r in sub) / len(sub) * 100
        print(f"{c:<10} {len(sub):>5} {l:>7.1f}% {s:>7.1f}% {j:>8.1f}%")

    print(f"\n>> Baselines: zero-shot ~18%, few-shot ~18%, gold-label linking 59.3%")
    print(f">> This end-to-end number is your REAL system result.")


if __name__ == "__main__":
    main()
