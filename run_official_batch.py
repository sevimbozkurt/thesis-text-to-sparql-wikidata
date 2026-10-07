"""run_official_batch.py — Official-split experiment via the Anthropic Batch
API (50% cheaper than standard: $2.50/M input, $12.50/M output).

USAGE (in order; each command is a separate run)
  python3 run_official_batch.py submit-gen        # then wait (<24h, often ~1h)
  python3 run_official_batch.py status
  python3 run_official_batch.py fetch-gen
  python3 run_official_batch.py candidates
  python3 run_official_batch.py submit-disamb
  python3 run_official_batch.py status
  python3 run_official_batch.py fetch-disamb
  python3 run_official_batch.py finalize
  python3 score_official.py
"""

import json, os, re, csv, sys, time, argparse
from endpoint import run_sparql, jaccard, ENDPOINT

MODEL      = "claude-opus-4-8"     # exact API model string
STATE      = "batch_state.json"
OFFICIAL   = "data/official_test.json"
GEN_OUT    = "outputs/batch_generated.json"        # {row_id: labelled query}
CAND_OUT   = "data/batch_candidates.json"       # {row_id: {kind: {label: [cands]}}}
DISAMB_MAP = "outputs/batch_disamb_map.json"       # {custom_id: [row_id, kind, label]}
DISAMB_OUT = "outputs/batch_disambiguated.json"    # {row_id: {kind: {label: chosen_id}}}
RESULTS    = "outputs/results_official_e2e.csv"
GOLDCACHE  = "data/official_gold_results.json"
LINKLOG    = "official_linking_log.jsonl"

N_CANDIDATES, SEARCH_DELAY = 7, 1.0
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}

GEN_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""


# ── small helpers ──────────────────────────────────────────────
def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

def save(path, obj):
    json.dump(obj, open(path, "w"), indent=1)

def client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY missing from .env")
    return anthropic.Anthropic(api_key=key)

def strip_fences(text):
    if "```" in text:
        text = "\n".join(l for l in text.split("\n")
                         if not l.strip().startswith("```")).strip()
    return text.strip()

def parse_labels(q):
    ents = re.findall(r'\[entity:([^\]]+)\]', q or "")
    props = re.findall(r'\[property:([^\]]+)\]', q or "")
    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x and x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
        return out
    return dedupe(ents), dedupe(props)


# ── stage 1: generation ────────────────────────────────────────
def submit_gen(limit=None):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    rows = load(OFFICIAL, None)
    if rows is None:
        sys.exit(f"{OFFICIAL} missing — run: python3 run_official_split.py --prepare")
    if limit:
        rows = rows[:limit]

    # reuse anything already generated in the working split (free)
    reused = load("reuse_map.json", {})
				
    todo = [r for r in rows if str(r["id"]) not in reused]
    print(f"official rows {len(rows)} | reused {len(reused)} | to generate {len(todo)}")

    save(GEN_OUT, {k: v for k, v in reused.items()
                   if k in {str(r['id']) for r in rows}})

    if not todo:
        print("nothing to submit"); return

    reqs = [Request(custom_id=f"gen-{r['id']}",
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=1024,
                        system=GEN_SYSTEM,
                        messages=[{"role": "user",
                                   "content": f"Question: {r['instruction']}"}]))
            for r in todo]

    batch = client().messages.batches.create(requests=reqs)
    st = load(STATE, {})
    st["gen_batch_id"] = batch.id
    save(STATE, st)
    print(f"submitted {len(reqs)} generation requests\nbatch id: {batch.id}")
    print("check with:  python3 run_official_batch.py status")


def fetch_gen():
    st = load(STATE, {})
    bid = st.get("gen_batch_id")
    if not bid:
        sys.exit("no generation batch submitted")
    gen = load(GEN_OUT, {})
    n = 0
    for entry in client().messages.batches.results(bid):
        rid = entry.custom_id.split("gen-", 1)[1]
        if entry.result.type == "succeeded":
            text = "".join(b.text for b in entry.result.message.content
                           if getattr(b, "type", "") == "text")
            gen[rid] = strip_fences(text)
            n += 1
        else:
            gen.setdefault(rid, "")
    save(GEN_OUT, gen)
    print(f"collected {n} generations; {GEN_OUT} now holds {len(gen)} rows")
    print("next:  python3 run_official_batch.py candidates")


# ── local: candidate generation (free) ─────────────────────────
def candidates():
    import requests
    gen = load(GEN_OUT, {})
    cache = load(CAND_OUT, {})
    todo = [(rid, q) for rid, q in gen.items() if rid not in cache and q]
    print(f"fetching candidates for {len(todo)} rows")

    def search(label, is_prop):
        params = {"action": "wbsearchentities", "search": label, "language": "en",
                  "format": "json", "limit": N_CANDIDATES,
                  "type": "property" if is_prop else "item"}
        for _ in range(3):
            time.sleep(SEARCH_DELAY)
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

    for n, (rid, q) in enumerate(todo):
        ents, props = parse_labels(q)
        cache[rid] = {"entity":   {l: search(l, False) for l in ents},
                      "property": {l: search(l, True)  for l in props}}
        if (n + 1) % 20 == 0:
            save(CAND_OUT, cache); print(f"  {n+1}/{len(todo)}")
    save(CAND_OUT, cache)
    tot = sum(len(v["entity"]) + len(v["property"]) for v in cache.values())
    print(f"done — {len(cache)} rows, {tot} labels total")
    print("next:  python3 run_official_batch.py submit-disamb")


# ── stage 2: disambiguation ────────────────────────────────────
def disamb_prompt(question, label, cands, is_prop):
    kind = "property" if is_prop else "entity"
    ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                      for c in cands)
    ex = "P57" if is_prop else "Q25191"
    return (f'Question: "{question}"\n\nFind the correct Wikidata {kind} ID for: "{label}"\n\n'
            f'Candidates:\n{ctext}\n\nThink step by step about which candidate best fits the '
            f'{kind} "{label}" in the context of the question. Output ONLY the chosen ID '
            f'(e.g. {ex}) on the last line, prefixed with "ANSWER: ".\n')


def submit_disamb():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    rows = {str(r["id"]): r for r in load(OFFICIAL, [])}
    cache = load(CAND_OUT, {})
    resolved = load(DISAMB_OUT, {})

    reqs, mapping = [], {}
    for rid, kinds in cache.items():
        q = rows.get(rid, {}).get("instruction", "")
        for kind, labels in kinds.items():
            for i, (label, cands) in enumerate(labels.items()):
                # skip trivial cases — no API call needed
                if len(cands) <= 1:
                    resolved.setdefault(rid, {}).setdefault(kind, {})[label] = (
                        cands[0]["id"] if cands else "")
                    continue
                if resolved.get(rid, {}).get(kind, {}).get(label):
                    continue
                cid = f"d-{rid}-{kind[0]}-{i}"
                mapping[cid] = [rid, kind, label]
                reqs.append(Request(custom_id=cid,
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=400,
                        messages=[{"role": "user",
                                   "content": disamb_prompt(q, label, cands,
                                                            kind == "property")}])))
    save(DISAMB_OUT, resolved)
    save(DISAMB_MAP, mapping)
    print(f"trivial labels resolved locally; {len(reqs)} disambiguation requests to submit")
    if not reqs:
        print("nothing to submit"); return

    batch = client().messages.batches.create(requests=reqs)
    st = load(STATE, {}); st["disamb_batch_id"] = batch.id; save(STATE, st)
    print(f"batch id: {batch.id}\ncheck with:  python3 run_official_batch.py status")


def fetch_disamb():
    st = load(STATE, {})
    bid = st.get("disamb_batch_id")
    if not bid:
        sys.exit("no disambiguation batch submitted")
    mapping = load(DISAMB_MAP, {})
    cache   = load(CAND_OUT, {})
    resolved = load(DISAMB_OUT, {})
    n = 0
    with open(LINKLOG, "a") as log:
        for entry in client().messages.batches.results(bid):
            rid, kind, label = mapping.get(entry.custom_id, [None, None, None])
            if rid is None:
                continue
            cands = cache.get(rid, {}).get(kind, {}).get(label, [])
            chosen = cands[0]["id"] if cands else ""
            if entry.result.type == "succeeded":
                text = "".join(b.text for b in entry.result.message.content
                               if getattr(b, "type", "") == "text")
                m = re.search(r'ANSWER:\s*([QP]\d+)', text) or re.search(r'\b([QP]\d+)\b', text)
                if m:
                    chosen = m.group(1)
                n += 1
            resolved.setdefault(rid, {}).setdefault(kind, {})[label] = chosen
            log.write(json.dumps({"id": rid, "kind": kind, "label": label,
                                  "candidates": [c["id"] for c in cands],
                                  "chosen": chosen}) + "\n")
    save(DISAMB_OUT, resolved)
    print(f"collected {n} disambiguations")
    print("next:  python3 run_official_batch.py finalize")


# ── local: substitute, execute, score ──────────────────────────
def finalize():
    rows = load(OFFICIAL, [])
    gen  = load(GEN_OUT, {})
    res  = load(DISAMB_OUT, {})
    gold = load(GOLDCACHE, {})

    done = set()
    if os.path.exists(RESULTS):
        done = {r["id"] for r in csv.DictReader(open(RESULTS))}
        print(f"resuming — {len(done)} rows already finalized")

    fields = ["id", "complexity", "instruction", "labeled_query", "linked_query",
              "generated_ok", "fully_linked", "executed", "exec_error", "jaccard"]
    with open(RESULTS, "a" if done else "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if not done:
            w.writeheader()
        for n, row in enumerate(rows):
            rid = str(row["id"])
            if rid in done:
                continue
            if rid not in gold:
                ok, gvals, gerr = run_sparql(row["query"])
                gold[rid] = {"ok": ok, "values": sorted(gvals), "err": gerr}
                if len(gold) % 25 == 0:
                    save(GOLDCACHE, gold)
            gvals = set(gold[rid]["values"])

            labeled = gen.get(rid, "")
            linked = labeled
            for kind, tag in [("entity", "entity"), ("property", "property")]:
                for label, cid in res.get(rid, {}).get(kind, {}).items():
                    if cid:
                        linked = re.sub(r'\[' + tag + ':' + re.escape(label) + r'\]',
                                        cid, linked, flags=re.I)
            fully = bool(linked) and "[entity:" not in linked and "[property:" not in linked
            executed, pvals, err = (False, set(), "no_query")
            if fully:
                executed, pvals, err = run_sparql(linked)
            jac = jaccard(pvals, gvals) if executed else 0.0

            w.writerow({"id": rid, "complexity": row["complexity"],
                        "instruction": row["instruction"], "labeled_query": labeled,
                        "linked_query": linked, "generated_ok": bool(labeled),
                        "fully_linked": fully, "executed": executed,
                        "exec_error": err, "jaccard": round(jac, 4)})
            fh.flush()
            if (n + 1) % 25 == 0:
                print(f"  {n+1}/{len(rows)}")
    save(GOLDCACHE, gold)
    print(f"\nwrote {RESULTS} — next: python3 score_official.py")


def status():
    st = load(STATE, {})
    c = client()
    for name, key in [("generation", "gen_batch_id"), ("disambiguation", "disamb_batch_id")]:
        bid = st.get(key)
        if not bid:
            print(f"{name:15s}: not submitted"); continue
        b = c.messages.batches.retrieve(bid)
        counts = getattr(b, "request_counts", None)
        print(f"{name:15s}: {b.processing_status}   {counts}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["submit-gen", "fetch-gen", "candidates",
                                        "submit-disamb", "fetch-disamb",
                                        "finalize", "status"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    {"submit-gen": lambda: submit_gen(a.limit), "fetch-gen": fetch_gen,
     "candidates": candidates, "submit-disamb": submit_disamb,
     "fetch-disamb": fetch_disamb, "finalize": finalize, "status": status}[a.command]()
