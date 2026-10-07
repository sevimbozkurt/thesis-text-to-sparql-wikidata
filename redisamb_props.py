"""redisamb_props.py — Re-run reasoning disambiguation for PROPERTY mentions
against repaired candidate pools. Companion to redisamb_clean.py (entities).
"""

import json, os, re, sys, collections

MODEL = "claude-opus-4-8"
POOL  = "data/properties_clean.json"
STATE = "redisamb_props_state.json"
MAPF  = "redisamb_props_map.json"
OUTF  = "outputs/preds_props_clean.jsonl"
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

def client():
    import anthropic
    k = api_key() or sys.exit("ANTHROPIC_API_KEY missing")
    return anthropic.Anthropic(api_key=k)


def build():
    """Union the two property fetches, cap at K, repaired-fetch order first."""
    old = json.load(open("candidates.json"))
    new = json.load(open("data/properties_expanded.json"))
    gold = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    labels = {l for ps in gold.values() for k, l, g in ps if k == "property"}

    pool = {}
    for l in labels:
        seen, merged = set(), []
        for c in new.get(f"property|{l}", []) + old.get(f"property|{l}", []):
            if c["id"] and c["id"] not in seen:
                seen.add(c["id"]); merged.append(c)
        pool[f"property|{l}"] = merged[:K]
    save(POOL, pool)

    mentions = [(i, l, g) for i, ps in gold.items() for k, l, g in ps if k == "property"]
    hit = sum(1 for i, l, g in mentions
              if g in {c["id"] for c in pool[f"property|{l}"]})
    sizes = collections.Counter(len(v) for v in pool.values())
    print(f"{len(labels)} labels | capped ceiling at k={K}: "
          f"{hit}/{len(mentions)} = {hit/len(mentions)*100:.1f}%")
    print(f"pool sizes: {dict(sorted(sizes.items()))}")
    print(f"wrote {POOL} — next: python3 redisamb_props.py submit")


def mentions_with_pools():
    gold = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    test = json.load(open("data/test.json"))
    pool = json.load(open(POOL))
    out = []
    for i, pairs in gold.items():
        q = test[i]["instruction"]
        for kind, label, gid in pairs:
            if kind != "property":
                continue
            out.append((i, q, label, pool.get(f"property|{label}", [])))
    return out


def prompt(question, label, cands):
    ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                      for c in cands)
    return (f'Question: "{question}"\n\nFind the correct Wikidata property ID for: '
            f'"{label}"\n\nCandidates:\n{ctext}\n\nThink step by step about which '
            f'candidate best fits the property "{label}" in the context of the '
            f'question. Output ONLY the chosen ID (e.g. P57) on the last line, '
            f'prefixed with "ANSWER: ".\n')


def submit():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    ms = mentions_with_pools()
    reqs, mapping, local = [], {}, {}
    for n, (i, q, label, cands) in enumerate(ms):
        key = f"{i}|{label}"
        if len(cands) == 0:
            local[key] = ""
        elif len(cands) == 1:
            local[key] = cands[0]["id"]
        else:
            cid = f"rp-{n}"
            mapping[cid] = [i, label]
            reqs.append(Request(custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=MODEL, max_tokens=400,
                    messages=[{"role": "user", "content": prompt(q, label, cands)}])))
    save(MAPF, {"map": mapping, "local": local})
    print(f"mentions {len(ms)} | local {len(local)} | to submit {len(reqs)}")
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
    url = meta.get("results_url") or sys.exit(
        f"not finished: {meta.get('processing_status')}")
    fn = f"redisamb_props_{bid}.jsonl"
    if not os.path.exists(fn):
        with rq.get(url, headers=H, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(fn, "wb") as f:
                for ch in r.iter_content(1 << 16):
                    f.write(ch)
    st["results_file"] = fn; save(STATE, st)
    print(f"downloaded {fn}")


def score():
    st = load(STATE, {}); mp = load(MAPF, {})
    mapping, local = mp["map"], mp["local"]
    gold = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    pool = json.load(open(POOL))

    chosen, ok = dict(local), 0
    for line in open(st["results_file"]):
        e = json.loads(line)
        i, label = mapping[e["custom_id"]]
        cands = pool.get(f"property|{label}", [])
        pick = cands[0]["id"] if cands else ""
        if e.get("result", {}).get("type") == "succeeded":
            t = "".join(b.get("text", "") for b in e["result"]["message"]["content"]
                        if b.get("type") == "text")
            m = re.search(r'ANSWER:\s*(P\d+)', t) or re.search(r'\b(P\d+)\b', t)
            if m:
                pick = m.group(1)
            ok += 1
        chosen[f"{i}|{label}"] = pick
    print(f"parsed {ok} results")

    with open(OUTF, "w") as f:
        for i, pairs in gold.items():
            for kind, label, gid in pairs:
                if kind != "property":
                    continue
                f.write(json.dumps({"index": i, "kind": "property", "label": label,
                                    "pred_id": chosen.get(f"{i}|{label}", "")}) + "\n")
    print(f"wrote {OUTF}")
    print("combine and evaluate:")
    print("  cat outputs/preds_reasoning_clean.jsonl outputs/preds_props_clean.jsonl > outputs/preds_reasoning_full.jsonl")
    print("  python3 eval_linker.py outputs/preds_reasoning_full.jsonl")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"build": build, "submit": submit, "status": status,
     "fetch": fetch, "score": score}.get(
        cmd, lambda: sys.exit("usage: redisamb_props.py build|submit|status|fetch|score"))()
