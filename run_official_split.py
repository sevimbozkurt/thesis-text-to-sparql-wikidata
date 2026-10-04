"""run_official_split.py — Comparability experiment on the OFFICIAL test split.

USAGE
  python3 run_official_split.py --prepare        # step 1 only, then inspect
  python3 run_official_split.py --limit 10       # smoke test (10 rows)
  python3 run_official_split.py                  # full run
  python3 score_official.py                      # scoring (separate script)
"""

import json, os, re, csv, time, argparse
from endpoint import run_sparql, jaccard, ENDPOINT

DATASET  = "PaDaS-Lab/Instruct-to-SPARQL"
CONFIG   = "default"
REVISION = None          # set to a commit hash to pin, e.g. "abc123..."
MODEL    = "anthropic/claude-opus-4.8"

OFFICIAL   = "official_test.json"
OUTFILE    = "results_official_e2e.csv"
LINKLOG    = "official_linking_log.jsonl"
GOLDCACHE  = "official_gold_results.json"

API_DELAY, SEARCH_DELAY, N_CANDIDATES, MAX_TOKENS = 1.0, 0.4, 7, 1024
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}

GEN_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""


# ── step 1: prepare official split ─────────────────────────────
def prepare():
    from datasets import load_dataset
    kw = {"revision": REVISION} if REVISION else {}
    ds = load_dataset(DATASET, CONFIG, **kw)
    rows = []
    for r in ds["test"]:
        instrs = r.get("instructions") or []
        if isinstance(instrs, str):
            instrs = [instrs]
        rows.append({
            "id": str(r["id"]),
            "instruction": instrs[0] if instrs else "",
            "query": r["sparql_query"],          # includes PREFIX declarations
            "annotated": r.get("sparql_annotated", ""),
            "complexity": r.get("complexity", "unknown"),
        })
    json.dump(rows, open(OFFICIAL, "w"), indent=1)
    from collections import Counter
    print(f"wrote {OFFICIAL}: {len(rows)} rows, "
          f"complexity {dict(Counter(x['complexity'] for x in rows))}")
    print("NOTE: record the dataset revision in the thesis; set REVISION in "
          "this file to pin it.")


# ── reuse: map dataset id -> cached e2e result from the working split ──
def cached_by_id():
    if not (os.path.exists("test.json") and os.path.exists("qlever/results_e2e.csv")):
        return {}
    work = json.load(open("test.json"))
    idx2id = {i: str(r["id"]) for i, r in enumerate(work)}
    out = {}
    for r in csv.DictReader(open("qlever/results_e2e.csv")):
        did = idx2id.get(int(r["index"]))
        if did:
            out[did] = r
    return out


# ── LLM helpers ────────────────────────────────────────────────
def get_client():
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise SystemExit("OPENROUTER_KEY missing from .env")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)

def generate_labeled(client, question):
    time.sleep(API_DELAY)
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0, max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": GEN_SYSTEM},
                      {"role": "user", "content": f"Question: {question}"}])
        text = resp.choices[0].message.content or ""
        if "```" in text:
            text = "\n".join(l for l in text.split("\n")
                             if not l.strip().startswith("```")).strip()
        return text.strip()
    except Exception:
        return ""

def parse_labels(q):
    ents = re.findall(r'\[entity:([^\]]+)\]', q)
    props = re.findall(r'\[property:([^\]]+)\]', q)
    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
        return out
    return dedupe(ents), dedupe(props)

def search_wikidata(label, is_property):
    import requests
    time.sleep(SEARCH_DELAY)
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": N_CANDIDATES,
              "type": "property" if is_property else "item"}
    for _ in range(3):
        try:
            r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return [{"id": it.get("id",""), "label": it.get("label",""),
                         "description": it.get("description","")}
                        for it in r.json().get("search", [])]
        except Exception:
            pass
        time.sleep(1.5)
    return []

def disambiguate(client, question, label, cands, is_property, log, row_id):
    if not cands:
        chosen = ""
    elif len(cands) == 1:
        chosen = cands[0]["id"]
    else:
        kind = "property" if is_property else "entity"
        ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                          for c in cands)
        example = "P57" if is_property else "Q25191"
        prompt = (f'Question: "{question}"\n\nFind the correct Wikidata {kind} ID for: '
                  f'"{label}"\n\nCandidates:\n{ctext}\n\nThink step by step about which '
                  f'candidate best fits the {kind} "{label}" in the context of the question. '
                  f'Output ONLY the chosen ID (e.g. {example}) on the last line, prefixed '
                  f'with "ANSWER: ".\n')
        time.sleep(API_DELAY)
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=400,
                messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content or ""
            m = re.search(r'ANSWER:\s*([QP]\d+)', text) or re.search(r'\b([QP]\d+)\b', text)
            chosen = m.group(1) if m else cands[0]["id"]
        except Exception:
            chosen = cands[0]["id"]
    log.write(json.dumps({"id": row_id, "kind": "property" if is_property else "entity",
                          "label": label, "candidates": [c["id"] for c in cands],
                          "chosen": chosen}) + "\n")
    log.flush()
    return chosen

def substitute(q, emap, pmap):
    out = q
    for lbl, qid in emap.items():
        if qid: out = re.sub(r'\[entity:' + re.escape(lbl) + r'\]', qid, out, flags=re.I)
    for lbl, pid in pmap.items():
        if pid: out = re.sub(r'\[property:' + re.escape(lbl) + r'\]', pid, out, flags=re.I)
    return out


# ── main ───────────────────────────────────────────────────────
def main(limit=None):
    if not os.path.exists(OFFICIAL):
        raise SystemExit(f"{OFFICIAL} missing — run with --prepare first")
    rows = json.load(open(OFFICIAL))
    if limit: rows = rows[:limit]

    gold_cache = json.load(open(GOLDCACHE)) if os.path.exists(GOLDCACHE) else {}
    reuse = cached_by_id()
    print(f"official rows: {len(rows)} | reusable from working split: "
          f"{sum(1 for r in rows if r['id'] in reuse)}")

    done = set()
    if os.path.exists(OUTFILE):
        done = {r["id"] for r in csv.DictReader(open(OUTFILE))}
        print(f"resuming — {len(done)} rows done")

    client = get_client()
    fields = ["id", "complexity", "instruction", "labeled_query", "linked_query",
              "generated_ok", "fully_linked", "executed", "exec_error",
              "jaccard", "source"]

    with open(OUTFILE, "a" if done else "w", newline="") as fh, \
         open(LINKLOG, "a") as log:
        w = csv.DictWriter(fh, fieldnames=fields)
        if not done: w.writeheader()

        for n, row in enumerate(rows):
            rid = row["id"]
            if rid in done: continue

            # gold result (cached once per row)
            if rid not in gold_cache:
                ok, gvals, gerr = run_sparql(row["query"])
                gold_cache[rid] = {"ok": ok, "values": sorted(gvals), "err": gerr}
                if len(gold_cache) % 25 == 0:
                    json.dump(gold_cache, open(GOLDCACHE, "w"))
            gold = set(gold_cache[rid]["values"])

            cached = reuse.get(rid)
            if cached and cached.get("labeled_query"):
                labeled  = cached["labeled_query"]
                linked   = cached["linked_query"]
                source   = "reused"
            else:
                labeled = generate_labeled(client, row["instruction"])
                if labeled:
                    ents, props = parse_labels(labeled)
                    emap = {l: disambiguate(client, row["instruction"], l,
                                            search_wikidata(l, False), False, log, rid)
                            for l in ents}
                    pmap = {l: disambiguate(client, row["instruction"], l,
                                            search_wikidata(l, True), True, log, rid)
                            for l in props}
                    linked = substitute(labeled, emap, pmap)
                else:
                    linked = ""
                source = "generated"

            generated_ok = bool(labeled)
            fully_linked = bool(linked) and "[entity:" not in linked and "[property:" not in linked
            executed, pvals, err = (False, set(), "no_query")
            if fully_linked:
                executed, pvals, err = run_sparql(linked)
            jac = jaccard(pvals, gold) if executed else 0.0

            w.writerow({"id": rid, "complexity": row["complexity"],
                        "instruction": row["instruction"], "labeled_query": labeled,
                        "linked_query": linked, "generated_ok": generated_ok,
                        "fully_linked": fully_linked, "executed": executed,
                        "exec_error": err, "jaccard": round(jac, 4), "source": source})
            fh.flush()
            if (n + 1) % 10 == 0:
                print(f"  {n+1}/{len(rows)}")

    json.dump(gold_cache, open(GOLDCACHE, "w"))
    print(f"\nDone -> {OUTFILE}. Next: python3 score_official.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.prepare:
        prepare()
    else:
        main(a.limit)
