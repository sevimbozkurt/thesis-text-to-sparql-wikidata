"""rerun_e2e_disamb.py — Stage 2 of the end-to-end re-run. Final experiment.
"""

import csv, json, os, re, sys, collections

MODEL = "claude-opus-4-8"
SRC   = "qlever/results_e2e_regen.csv"
POOL  = "e2e_candidates_clean.json"
STATE = "e2e_disamb_state.json"
MAPF  = "e2e_disamb_map.json"
OUT   = "results_e2e_clean.csv"
QID   = re.compile(r'^Q\d+$')

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

def jobs():
    rows = list(csv.DictReader(open(SRC)))
    pool = json.load(open(POOL))
    out = []
    for r in rows:
        ents, props = parse_labels(r["labeled_query"])
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                out.append((r["index"], r["instruction"], kind, l,
                            pool.get(f"{kind}|{l}", [])))
    return rows, out

def submit():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    _, js = jobs()
    reqs, mapping, local = [], {}, {}
    for n, (idx, q, kind, label, cands) in enumerate(js):
        key = f"{idx}|{kind}|{label}"
        if len(cands) == 0:
            local[key] = ""
        elif len(cands) == 1:
            local[key] = cands[0]["id"]
        else:
            cid = f"e2-{n}"
            mapping[cid] = [idx, kind, label]
            reqs.append(Request(custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=MODEL, max_tokens=400,
                    messages=[{"role": "user",
                               "content": prompt(q, label, cands, kind == "property")}])))
    save(MAPF, {"map": mapping, "local": local})
    print(f"label instances {len(js)} | local {len(local)} | to submit {len(reqs)}")
    if not reqs:
        print("nothing to submit"); return
    b = client().messages.batches.create(requests=reqs)
    st = load(STATE, {}); st["batch_id"] = b.id; save(STATE, st)
    print(f"batch id: {b.id}")

def status():
    st = load(STATE, {})
    b = client().messages.batches.retrieve(st["batch_id"])
    print(b.processing_status, getattr(b, "request_counts", ""))

def fetch():
    import requests as rq
    st = load(STATE, {}); bid = st["batch_id"]
    H = {"x-api-key": api_key(), "anthropic-version": "2023-06-01"}
    meta = rq.get(f"https://api.anthropic.com/v1/messages/batches/{bid}",
                  headers=H, timeout=60).json()
    url = meta.get("results_url") or sys.exit(f"not finished: {meta.get('processing_status')}")
    fn = f"e2e_disamb_{bid}.jsonl"
    if not os.path.exists(fn):
        with rq.get(url, headers=H, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(fn, "wb") as f:
                for ch in r.iter_content(1 << 16):
                    f.write(ch)
    st["results_file"] = fn; save(STATE, st)
    print(f"downloaded {fn}")

def score():
    from endpoint import run_sparql, jaccard
    st, mp = load(STATE, {}), load(MAPF, {})
    mapping, local = mp["map"], mp["local"]
    pool = json.load(open(POOL))
    rows = list(csv.DictReader(open(SRC)))
    gold = {int(k): set(v) for k, v in json.load(open("gold_results.json")).items()}

    chosen, ok = dict(local), 0
    for line in open(st["results_file"]):
        e = json.loads(line)
        idx, kind, label = mapping[e["custom_id"]]
        cands = pool.get(f"{kind}|{label}", [])
        pick = cands[0]["id"] if cands else ""
        if e.get("result", {}).get("type") == "succeeded":
            t = "".join(b.get("text", "") for b in e["result"]["message"]["content"]
                        if b.get("type") == "text")
            pat = r'ANSWER:\s*(P\d+)' if kind == "property" else r'ANSWER:\s*(Q\d+)'
            alt = r'\b(P\d+)\b' if kind == "property" else r'\b(Q\d+)\b'
            m = re.search(pat, t) or re.search(alt, t)
            if m:
                pick = m.group(1)
            ok += 1
        chosen[f"{idx}|{kind}|{label}"] = pick
    print(f"parsed {ok} disambiguations")

    strict, cx = set(), {}
    for r in csv.DictReader(open("gold_status_qlever.csv")):
        i = int(r["index"]); cx[i] = r["complexity"]
        if r["gold_executed"] == "True" and r["gold_result_count"] != "0":
            strict.add(i)

    done, outrows = set(), []
    if os.path.exists(OUT):
        outrows = list(csv.DictReader(open(OUT)))
        done = {int(r["index"]) for r in outrows}
        print(f"resuming — {len(done)} rows scored")

    fields = ["index", "complexity", "linked_query", "fully_linked", "executed",
              "exec_error", "jaccard_pooled", "jaccard_entity"]
    for n, r in enumerate(rows):
        i = int(r["index"])
        if i in done:
            continue
        q = r["labeled_query"]
        ents, props = parse_labels(q)
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                pid = chosen.get(f"{r['index']}|{kind}|{l}", "")
                if pid:
                    q = re.sub(r'\[' + kind + ':' + re.escape(l) + r'\]', pid, q, flags=re.I)
        fully = bool(q) and "[entity:" not in q and "[property:" not in q
        executed, vals, err = (False, set(), "not_linked")
        if fully:
            executed, vals, err = run_sparql(q)
        g = gold.get(i, set())
        ge = {v for v in g if QID.match(v)}
        pe = {v for v in vals if QID.match(v)}
        jp = jaccard(vals, g) if executed else 0.0
        je = ("na" if (not pe and not ge) else
              round(jaccard(pe, ge), 4)) if executed else 0.0
        outrows.append({"index": i, "complexity": r["complexity"], "linked_query": q,
                        "fully_linked": fully, "executed": executed, "exec_error": err,
                        "jaccard_pooled": round(jp, 4), "jaccard_entity": je})
        if len(outrows) % 50 == 0:
            with open(OUT, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(outrows)
            print(f"  {len(outrows)}/{len(rows)}")

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(outrows)

    def pct(col, comp=None):
        sub = [r for r in outrows if comp is None or r["complexity"] == comp]
        return sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100 if sub else None
    def mean(col, comp=None):
        v = [float(r[col]) for r in outrows if int(r["index"]) in strict
             and r[col] not in ("na", "") and (comp is None or r["complexity"] == comp)]
        return sum(v)/len(v)*100 if v else None

    print(f"\nEND-TO-END, CLEAN POOLS — {len(outrows)} rows ({len(strict)} strict)\n")
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
    print(f"written {OUT}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"submit": submit, "status": status, "fetch": fetch, "score": score}.get(
        cmd, lambda: sys.exit("usage: rerun_e2e_disamb.py submit|status|fetch|score"))()
