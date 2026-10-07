"""prompt_idioms.py — Experiment: schema-idiom-aware generation prompting.
"""

import csv, json, os, re, sys, time, collections

MODEL = "claude-opus-4-8"
GEN   = "idiom_generated.json"
POOL  = "idiom_candidates.json"
MAPF  = "idiom_disamb_map.json"
STATE = "idiom_state.json"
OUT   = "results_e2e_idiom.csv"
K     = 7
QIDRE = re.compile(r'^Q\d+$')

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}

BASE_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""

IDIOM_GUIDE = """

Before writing the query, consider which of Wikidata's modelling idioms the
question requires. Use them where appropriate:

1. Class membership is usually hierarchical. A question about a category
   normally means the category and all of its subclasses, so prefer
   ?item wdt:[property:instance of]/wdt:[property:subclass of]* wd:[entity:CLASS]
   over a direct instance-of triple. Use the direct form only when the question
   clearly means the class itself.

2. Values that carry extra information live on statements, not on direct
   claims. When the question asks about a qualifier — a date, a rank, a role, a
   plot, a part something applies to — go through the statement node:
     ?item p:[property:P] ?st .
     ?st ps:[property:P] ?value ; pq:[property:QUALIFIER] ?qvalue .
   Direct wdt: triples cannot see qualifiers.

3. Quantities with units, precision or bounds require the statement value node:
     ?item p:[property:P]/psv:[property:P] ?vn .
     ?vn wikibase:quantityAmount ?amount ; wikibase:quantityUnit ?unit .
   Use this whenever units must be compared or converted.

4. Questions about words, forms, senses or languages concern lexemes, not
   items: use wikibase:lemma, dct:language, ontolex:sense and the lexeme
   namespace rather than item properties.

5. Counting, ranking or "how many / most / per X" questions need explicit
   aggregation: COUNT/SUM with GROUP BY, and ORDER BY ... DESC for ranking.

6. Alternatives in the question ("mathematicians or physicists", several
   platforms) are expressed with VALUES or UNION, not by choosing one.

7. Do not add LIMIT unless the question asks for a specific number of results.

Apply only the idioms the question actually calls for; do not add machinery
that is not needed."""

def load(p, d):
    return json.load(open(p)) if os.path.exists(p) else d

def save(p, o):
    json.dump(o, open(p, "w"), indent=1)

def api_key():
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.strip().split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY", "")

def client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key() or sys.exit("ANTHROPIC_API_KEY missing"))

def strip_fences(t):
    if "```" in t:
        t = "\n".join(l for l in t.split("\n") if not l.strip().startswith("```")).strip()
    return t.strip()

def parse_labels(q):
    ents = re.findall(r'\[entity:([^\]]+)\]', q or "")
    props = re.findall(r'\[property:([^\]]+)\]', q or "")
    def dd(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x and x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
        return out
    return dd(ents), dd(props)

# ── generation ────────────────────────────────────────────────
def submit_gen():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("data/test.json"))
    done = load(GEN, {})
    todo = [(i, r) for i, r in enumerate(test) if str(i) not in done]
    print(f"{len(test)} rows | already generated {len(done)} | to submit {len(todo)}")
    if not todo:
        return
    reqs = [Request(custom_id=f"ig-{i}",
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=1024,
                        system=BASE_SYSTEM + IDIOM_GUIDE,
                        messages=[{"role": "user",
                                   "content": f"Question: {r['instruction']}"}]))
            for i, r in todo]
    b = client().messages.batches.create(requests=reqs)
    st = load(STATE, {}); st["gen"] = b.id; save(STATE, st)
    print(f"batch id: {b.id}")

def _download(bid, fn):
    import requests as rq
    H = {"x-api-key": api_key(), "anthropic-version": "2023-06-01"}
    meta = rq.get(f"https://api.anthropic.com/v1/messages/batches/{bid}",
                  headers=H, timeout=60).json()
    url = meta.get("results_url") or sys.exit(f"not finished: {meta.get('processing_status')}")
    if not os.path.exists(fn):
        with rq.get(url, headers=H, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(fn, "wb") as f:
                for ch in r.iter_content(1 << 16):
                    f.write(ch)
    return fn

def text_of(e):
    return "".join(b.get("text", "") for b in
                   e.get("result", {}).get("message", {}).get("content", [])
                   if b.get("type") == "text")

def fetch_gen():
    st = load(STATE, {})
    fn = _download(st["gen"], f"idiom_gen_{st['gen']}.jsonl")
    gen = load(GEN, {})
    ok = 0
    for line in open(fn):
        e = json.loads(line)
        i = e["custom_id"].split("ig-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[i] = strip_fences(text_of(e)); ok += 1
        else:
            gen.setdefault(i, "")
    save(GEN, gen)
    print(f"collected {ok}; {GEN} holds {len(gen)} rows")

# ── candidates ────────────────────────────────────────────────
def candidates():
    import requests
    gen = load(GEN, {})
    pool = load(POOL, {})
    existing = {}
    for f in ["e2e_candidates_clean.json", "data/candidates_expanded.json", "data/properties_clean.json"]:
        existing.update(load(f, {}))
    labels = set()
    for q in gen.values():
        e, p = parse_labels(q)
        labels |= {("entity", x) for x in e} | {("property", x) for x in p}
    reused = 0
    for kind, l in labels:
        key = f"{kind}|{l}"
        if key in pool:
            continue
        if key in existing and existing[key]:
            pool[key] = existing[key][:K]; reused += 1
    save(POOL, pool)
    todo = [(k, l) for k, l in labels if f"{k}|{l}" not in pool]
    print(f"{len(labels)} labels | reused from earlier fetches {reused} | to fetch {len(todo)}")

    def search(label, is_prop):
        params = {"action": "wbsearchentities", "search": label, "language": "en",
                  "format": "json", "limit": K,
                  "type": "property" if is_prop else "item"}
        for a in range(5):
            time.sleep(1.2 * (a + 1))
            try:
                r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=25)
                if r.status_code == 200:
                    return [{"id": h.get("id",""), "label": h.get("label",""),
                             "description": h.get("description","")}
                            for h in r.json().get("search", [])]
                print(f"  HTTP {r.status_code}: {label!r}")
            except Exception as ex:
                print(f"  {type(ex).__name__}: {label!r}")
        return None

    for n, (kind, label) in enumerate(todo):
        res = search(label, kind == "property")
        if res is not None:
            pool[f"{kind}|{label}"] = res
        if (n + 1) % 25 == 0:
            save(POOL, pool); print(f"  {n+1}/{len(todo)}")
    save(POOL, pool)
    empt = [k for k, v in pool.items() if not v]
    print(f"empty pools: {len(empt)} (rerun this command once to retry them)")

# ── disambiguation ────────────────────────────────────────────
def prompt(question, label, cands, is_prop):
    kind = "property" if is_prop else "entity"
    ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                      for c in cands)
    ex = "P57" if is_prop else "Q25191"
    return (f'Question: "{question}"\n\nFind the correct Wikidata {kind} ID for: '
            f'"{label}"\n\nCandidates:\n{ctext}\n\nThink step by step about which '
            f'candidate best fits the {kind} "{label}" in the context of the question. '
            f'Output ONLY the chosen ID (e.g. {ex}) on the last line, prefixed with '
            f'"ANSWER: ".\n')

def submit_disamb():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("data/test.json"))
    gen, pool = load(GEN, {}), load(POOL, {})
    reqs, mapping, local = [], {}, {}
    n = 0
    for idx, q in gen.items():
        ents, props = parse_labels(q)
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                cands = pool.get(f"{kind}|{l}", [])[:K]
                key = f"{idx}|{kind}|{l}"
                if len(cands) == 0:
                    local[key] = ""
                elif len(cands) == 1:
                    local[key] = cands[0]["id"]
                else:
                    cid = f"id-{n}"; n += 1
                    mapping[cid] = [idx, kind, l]
                    reqs.append(Request(custom_id=cid,
                        params=MessageCreateParamsNonStreaming(
                            model=MODEL, max_tokens=400,
                            messages=[{"role": "user", "content": prompt(
                                test[int(idx)]["instruction"], l, cands,
                                kind == "property")}])))
    save(MAPF, {"map": mapping, "local": local})
    print(f"local {len(local)} | to submit {len(reqs)}")
    if not reqs:
        return
    b = client().messages.batches.create(requests=reqs)
    st = load(STATE, {}); st["disamb"] = b.id; save(STATE, st)
    print(f"batch id: {b.id}")

def fetch_disamb():
    st = load(STATE, {})
    fn = _download(st["disamb"], f"idiom_disamb_{st['disamb']}.jsonl")
    st["disamb_file"] = fn; save(STATE, st)
    print(f"downloaded {fn}")

def status():
    st = load(STATE, {}); c = client()
    for k in ["gen", "disamb"]:
        if k in st:
            b = c.messages.batches.retrieve(st[k])
            print(f"{k:8s}: {b.processing_status} {getattr(b,'request_counts','')}")
        else:
            print(f"{k:8s}: not submitted")

# ── scoring ───────────────────────────────────────────────────
def score():
    from endpoint import run_sparql, jaccard
    st, mp = load(STATE, {}), load(MAPF, {})
    mapping, local = mp["map"], mp["local"]
    gen, pool = load(GEN, {}), load(POOL, {})
    test = json.load(open("data/test.json"))
    gold = {int(k): set(v) for k, v in json.load(open("data/gold_results.json")).items()}

    chosen = dict(local)
    for line in open(st["disamb_file"]):
        e = json.loads(line)
        idx, kind, label = mapping[e["custom_id"]]
        cands = pool.get(f"{kind}|{label}", [])
        pick = cands[0]["id"] if cands else ""
        if e.get("result", {}).get("type") == "succeeded":
            t = text_of(e)
            pat = r'ANSWER:\s*(P\d+)' if kind == "property" else r'ANSWER:\s*(Q\d+)'
            alt = r'\b(P\d+)\b' if kind == "property" else r'\b(Q\d+)\b'
            m = re.search(pat, t) or re.search(alt, t)
            if m:
                pick = m.group(1)
        chosen[f"{idx}|{kind}|{label}"] = pick

    strict, cx = set(), {}
    for r in csv.DictReader(open("data/gold_status_qlever.csv")):
        i = int(r["index"]); cx[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

    done, outrows = set(), []
    if os.path.exists(OUT):
        outrows = list(csv.DictReader(open(OUT)))
        done = {int(r["index"]) for r in outrows}
        print(f"resuming — {len(done)} scored")

    fields = ["index", "complexity", "labeled_query", "linked_query", "fully_linked",
              "executed", "exec_error", "jaccard_pooled", "jaccard_entity"]
    for idx, q in sorted(gen.items(), key=lambda kv: int(kv[0])):
        i = int(idx)
        if i in done:
            continue
        linked = q
        ents, props = parse_labels(q)
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                pid = chosen.get(f"{idx}|{kind}|{l}", "")
                if pid:
                    linked = re.sub(r'\[' + kind + ':' + re.escape(l) + r'\]',
                                    pid, linked, flags=re.I)
        fully = bool(linked) and "[entity:" not in linked and "[property:" not in linked
        executed, vals, err = (False, set(), "not_linked")
        if fully:
            executed, vals, err = run_sparql(linked)
        g = gold.get(i, set())
        ge = {v for v in g if QIDRE.match(v)}
        pe = {v for v in vals if QIDRE.match(v)}
        jp = jaccard(vals, g) if executed else 0.0
        je = ("na" if (not pe and not ge) else round(jaccard(pe, ge), 4)) if executed else 0.0
        outrows.append({"index": i, "complexity": cx.get(i, test[i]["complexity"]),
                        "labeled_query": q, "linked_query": linked,
                        "fully_linked": fully, "executed": executed, "exec_error": err,
                        "jaccard_pooled": round(jp, 4), "jaccard_entity": je})
        if len(outrows) % 50 == 0:
            with open(OUT, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(outrows)
            print(f"  {len(outrows)}/{len(gen)}")
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(outrows)

    def pct(col, comp=None):
        sub = [r for r in outrows if comp is None or r["complexity"] == comp]
        return sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100 if sub else None
    def mean(col, comp=None):
        v = [float(r[col]) for r in outrows if int(r["index"]) in strict
             and r[col] not in ("na","") and (comp is None or r["complexity"] == comp)]
        return sum(v)/len(v)*100 if v else None

    print(f"\nIDIOM-AWARE PROMPTING — {len(outrows)} rows ({len(strict)} strict)\n")
    print(f"{'metric':<24} {'simple':>8} {'medium':>8} {'complex':>9} {'overall':>9}")
    for label, fn, col in [("fully linked (%)", pct, "fully_linked"),
                           ("executed (%)", pct, "executed"),
                           ("fair Jaccard pooled", mean, "jaccard_pooled"),
                           ("fair Jaccard entity", mean, "jaccard_entity")]:
        line = f"{label:<24}"
        for c in ["simple", "medium", "complex", None]:
            v = fn(col, c)
            line += f" {v:7.1f}%" if v is not None else f" {'—':>8}"
        print(line)

    # idiom usage counts: did the intervention change what was generated?
    def counts(qs):
        c = collections.Counter()
        for q in qs:
            if re.search(r'subclass of\]\*', q): c["P279* closure"] += 1
            if re.search(r'\bp:\[', q): c["statement node p:"] += 1
            if re.search(r'\bpq:\[', q): c["qualifier pq:"] += 1
            if re.search(r'\bpsv:\[', q): c["value node psv:"] += 1
            if re.search(r'(?i)\bgroup by\b', q): c["GROUP BY"] += 1
            if re.search(r'(?i)\bvalues\b|\bunion\b', q): c["VALUES/UNION"] += 1
            if re.search(r'(?i)\blimit\b', q): c["LIMIT"] += 1
        return c
    new_c = counts(gen.values())
    old = {r["index"]: r["labeled_query"] for r in
           csv.DictReader(open("outputs/qlever/results_e2e_regen.csv"))}
    old_c = counts(old.values())
    print("\nidiom usage in generated queries (baseline -> idiom prompt):")
    for k in sorted(set(new_c) | set(old_c)):
        print(f"  {k:18s} {old_c.get(k,0):4d} -> {new_c.get(k,0):4d}")
    print("\nBaseline for comparison: pooled 22.4 / entity 27.5 (strict, n=400)")
    print(f"written {OUT}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"submit-gen": submit_gen, "fetch-gen": fetch_gen, "candidates": candidates,
     "submit-disamb": submit_disamb, "fetch-disamb": fetch_disamb,
     "status": status, "score": score}.get(
        cmd, lambda: sys.exit("usage: prompt_idioms.py submit-gen|status|fetch-gen|"
                              "candidates|submit-disamb|fetch-disamb|score"))()
