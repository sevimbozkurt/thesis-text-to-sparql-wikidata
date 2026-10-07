"""official_linkers.py — Re-run the linker comparison on the OFFICIAL test
split.

Usage:  python3 official_linkers.py <subcommand>
"""

import json, os, re, sys, collections

MODEL = "claude-opus-4-8"
GOLD  = "data/gold_links_official.json"
POOL  = "data/candidates_official.json"
ROWS  = "data/official_test.json"
STATE = "official_linker_state.json"
MAPF  = "official_linker_map.json"
K     = 7

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

def questions():
    return {str(r["id"]): r["instruction"] for r in json.load(open(ROWS))}


# ── reasoning linker (batch) ───────────────────────────────────
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

def submit():
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    gold, pool, qs = load(GOLD, {}), load(POOL, {}), questions()
    reqs, mapping, local = [], {}, {}
    n = 0
    for rid, pairs in gold.items():
        q = qs.get(rid, "")
        for kind, label, gid in pairs:
            cands = pool.get(f"{kind}|{label}", [])[:K]
            key = f"{rid}|{kind}|{label}"
            if len(cands) == 0:
                local[key] = ""
            elif len(cands) == 1:
                local[key] = cands[0]["id"]
            else:
                cid = f"ol-{n}"; n += 1
                mapping[cid] = [rid, kind, label]
                reqs.append(Request(custom_id=cid,
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=400,
                        messages=[{"role": "user",
                                   "content": prompt(q, label, cands, kind == "property")}])))
    save(MAPF, {"map": mapping, "local": local})
    print(f"mentions {sum(len(v) for v in gold.values())} | local {len(local)} | "
          f"to submit {len(reqs)}")
    if not reqs:
        return
    c = anthropic.Anthropic(api_key=api_key())
    b = c.messages.batches.create(requests=reqs)
    st = load(STATE, {}); st["batch_id"] = b.id; save(STATE, st)
    print(f"batch id: {b.id}")

def status():
    import anthropic
    st = load(STATE, {})
    b = anthropic.Anthropic(api_key=api_key()).messages.batches.retrieve(st["batch_id"])
    print(b.processing_status, getattr(b, "request_counts", ""))

def fetch():
    import requests as rq
    st = load(STATE, {}); bid = st["batch_id"]
    H = {"x-api-key": api_key(), "anthropic-version": "2023-06-01"}
    meta = rq.get(f"https://api.anthropic.com/v1/messages/batches/{bid}",
                  headers=H, timeout=60).json()
    url = meta.get("results_url") or sys.exit(f"not finished: {meta.get('processing_status')}")
    fn = f"official_linker_{bid}.jsonl"
    if not os.path.exists(fn):
        with rq.get(url, headers=H, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(fn, "wb") as f:
                for ch in r.iter_content(1 << 16):
                    f.write(ch)
    st["results_file"] = fn; save(STATE, st)
    print(f"downloaded {fn}")

def score():
    st, mp = load(STATE, {}), load(MAPF, {})
    mapping, local = mp["map"], mp["local"]
    gold, pool = load(GOLD, {}), load(POOL, {})
    chosen, ok = dict(local), 0
    for line in open(st["results_file"]):
        e = json.loads(line)
        rid, kind, label = mapping[e["custom_id"]]
        cands = pool.get(f"{kind}|{label}", [])[:K]
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
        chosen[f"{rid}|{kind}|{label}"] = pick
    out = "preds_reasoning_official.jsonl"
    with open(out, "w") as f:
        for rid, pairs in gold.items():
            for kind, label, gid in pairs:
                f.write(json.dumps({"index": rid, "kind": kind, "label": label,
                                    "pred_id": chosen.get(f"{rid}|{kind}|{label}", "")}) + "\n")
    print(f"parsed {ok}; wrote {out}")


# ── GLiNKER ────────────────────────────────────────────────────
def glinker():
    from glinker import ProcessorFactory
    gold, pool, qs = load(GOLD, {}), load(POOL, {}), questions()
    dict_file = "entities_official.jsonl"
    seen = set()
    with open(dict_file, "w") as f:
        for key, cands in pool.items():
            if not key.startswith("entity|"):
                continue
            for c in cands:
                if c["id"] and c["id"] not in seen:
                    seen.add(c["id"])
                    f.write(json.dumps({"entity_id": c["id"],
                                        "label": c.get("label") or c["id"],
                                        "description": c.get("description")
                                                       or c.get("label") or c["id"],
                                        "entity_type": "entity"}) + "\n")
    print(f"{dict_file}: {len(seen)} entities")

    ex = ProcessorFactory.create_simple(
        model_name="knowledgator/gliner-linker-large-v1.0",
        entities=dict_file, external_entities=True)

    out, written = "preds_glinker_official.jsonl", 0
    with open(out, "w") as fh:
        for rid, pairs in gold.items():
            ent = [(k, l, g) for k, l, g in pairs if k == "entity"]
            if not ent:
                continue
            labels = [l for _, l, _ in ent]
            text = qs.get(rid, "").rstrip() + "\nMentions: "
            spans = []
            for lbl in labels:
                s = len(text); text += lbl
                spans.append({"text": lbl, "start": s, "end": len(text)})
                text += " ; "
            res = ex.execute({"texts": [text], "entities": [spans]})
            l0 = res.get("l0_result")
            pred = {}
            for e in (l0.entities[0] if l0 and l0.entities else []):
                le = getattr(e, "linked_entity", None)
                if le is not None:
                    pred[e.mention_text] = le.entity_id
            for kind, label, _ in ent:
                fh.write(json.dumps({"index": rid, "kind": kind, "label": label,
                                     "pred_id": pred.get(label, "")}) + "\n")
                written += 1
    print(f"wrote {written} predictions -> {out}")


# ── ReFinED ────────────────────────────────────────────────────
def refined():
    from refined.inference.processor import Refined
    gold, qs = load(GOLD, {}), questions()

    def norm(s):
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    def score_match(label, mention):
        L, M = norm(label), norm(mention)
        if not L or not M:
            return 0.0
        if L == M:
            return 1.0
        if L in M or M in L:
            return 0.8
        lt, mt = set(L.split()), set(M.split())
        inter = len(lt & mt)
        return 0.6 * inter / max(len(lt), len(mt)) if inter else 0.0

    r = Refined.from_pretrained(model_name="questions_model", entity_set="wikidata",
                                use_precomputed_descriptions=False)
    out, written = "outputs/preds_refined_official.jsonl", 0
    sc = sp = sg = 0
    with open(out, "w") as fh:
        for rid, pairs in gold.items():
            ent = [(k, l, g) for k, l, g in pairs if k == "entity"]
            if not ent:
                continue
            spans = r.process_text(qs.get(rid, ""))
            predicted = []
            for s in spans:
                pe = getattr(s, "predicted_entity", None)
                qid = getattr(pe, "wikidata_entity_id", None) if pe else None
                if qid:
                    predicted.append((s.text, qid))
            used = set()
            for kind, label, gid in ent:
                best, bs, bj = "", 0.0, None
                for j, (mt, qid) in enumerate(predicted):
                    if j in used:
                        continue
                    v = score_match(label, mt)
                    if v > bs:
                        best, bs, bj = qid, v, j
                if bs >= 0.5 and bj is not None:
                    used.add(bj)
                else:
                    best = ""
                fh.write(json.dumps({"index": rid, "kind": kind, "label": label,
                                     "pred_id": best}) + "\n")
                written += 1
            g = {x for _, _, x in ent}; p = {q for _, q in predicted}
            sg += len(g); sp += len(p); sc += len(g & p)
    P = sc/sp*100 if sp else 0
    R = sc/sg*100 if sg else 0
    F = 2*P*R/(P+R) if P+R else 0
    print(f"wrote {written} -> {out}")
    print(f"SET-BASED (secondary): P {P:.1f} R {R:.1f} F1 {F:.1f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"submit": submit, "status": status, "fetch": fetch, "score": score,
     "glinker": glinker, "refined": refined}.get(
        cmd, lambda: sys.exit("usage: official_linkers.py "
                              "glinker|refined|submit|status|fetch|score"))()
