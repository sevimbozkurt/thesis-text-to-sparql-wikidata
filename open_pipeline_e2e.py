"""open_pipeline_e2e.py — Run the FULL pipeline with an open-weight backbone on
the server: labelled-query generation, then disambiguation over retrieved
candidates. Free; no API.

USAGE (server, conda env with vllm, one GPU)
  export CUDA_VISIBLE_DEVICES=1
  python open_pipeline_e2e.py --model Qwen/Qwen2.5-14B-Instruct --split official
Then scp linked_queries_<tag>_<split>.json back and score with
score_open_pipeline.py on the laptop.
"""

import argparse, json, os, re, sys, time

K = 7
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2

GEN_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""


def load(p, d=None):
    if not os.path.exists(p):
        if d is None:
            sys.exit(f"missing input: {p}")
        return d
    return json.load(open(p))

def save(p, o):
    json.dump(o, open(p, "w"), indent=1)

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

def disamb_prompt(question, label, cands, is_prop):
    kind = "property" if is_prop else "entity"
    ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                      for c in cands)
    ex = "P57" if is_prop else "Q25191"
    return (f'Question: "{question}"\n\nFind the correct Wikidata {kind} ID for: '
            f'"{label}"\n\nCandidates:\n{ctext}\n\nThink step by step about which '
            f'candidate best fits the {kind} "{label}" in the context of the question. '
            f'Output ONLY the chosen ID (e.g. {ex}) on the last line, prefixed with '
            f'"ANSWER: ".\n')

def wikidata_search(label, is_prop):
    import requests
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": K,
              "type": "property" if is_prop else "item"}
    for a in range(5):
        time.sleep(DELAY * (a + 1))
        try:
            r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h.get("id",""), "label": h.get("label",""),
                         "description": h.get("description","")}
                        for h in r.json().get("search", [])]
            print(f"    HTTP {r.status_code}: {label!r}")
        except Exception as e:
            print(f"    {type(e).__name__}: {label!r}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--split", choices=["working", "official"], default="official")
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--tp", type=int, default=1)
    a = ap.parse_args()

    tag = re.sub(r'[^A-Za-z0-9]+', '-', a.model).strip('-').lower()
    gen_file  = f"gen_{tag}_{a.split}.json"
    pool_file = f"pool_{tag}_{a.split}.json"
    out_file  = f"linked_queries_{tag}_{a.split}.json"

    if a.split == "official":
        rows = load("official_test.json")
        qs = {str(r["id"]): r["instruction"] for r in rows}
        base_pool = load("candidates_official.json", {})
    else:
        test = load("test.json")
        qs = {str(i): r["instruction"] for i, r in enumerate(test)}
        base_pool = {}
        for f in ["candidates_expanded.json", "properties_clean.json",
                  "e2e_candidates_clean.json"]:
            base_pool.update(load(f, {}))
    print(f"{a.split} split: {len(qs)} questions")

    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, gpu_memory_utilization=a.gpu_mem,
              tensor_parallel_size=a.tp, trust_remote_code=True)
    tok = llm.get_tokenizer()

    def chat(msgs):
        try:
            return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        except Exception:
            return msgs[-1]["content"]

    # ── stage 1: generation ───────────────────────────────────
    gen = load(gen_file, {})
    todo = [(rid, q) for rid, q in qs.items() if rid not in gen]
    if todo:
        print(f"generating {len(todo)} labelled queries")
        prompts = [chat([{"role": "system", "content": GEN_SYSTEM},
                         {"role": "user", "content": f"Question: {q}"}])
                   for _, q in todo]
        outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=1024))
        for (rid, _), o in zip(todo, outs):
            t = o.outputs[0].text if o.outputs else ""
            if "```" in t:
                t = "\n".join(l for l in t.split("\n")
                              if not l.strip().startswith("```")).strip()
            gen[rid] = t.strip()
        save(gen_file, gen)
    empty = sum(1 for v in gen.values() if not v)
    print(f"generated: {len(gen)} ({empty} empty)")

    # ── candidates for the generated labels ───────────────────
    pool = load(pool_file, dict(base_pool))
    needed = set()
    for q in gen.values():
        e, p = parse_labels(q)
        needed |= {("entity", x) for x in e} | {("property", x) for x in p}
    missing = [(k, l) for k, l in needed if f"{k}|{l}" not in pool]
    print(f"{len(needed)} distinct labels | fetching {len(missing)}")
    for n, (kind, label) in enumerate(missing):
        res = wikidata_search(label, kind == "property")
        if res is not None:
            pool[f"{kind}|{label}"] = res
        if (n + 1) % 25 == 0:
            save(pool_file, pool); print(f"  {n+1}/{len(missing)}")
    save(pool_file, pool)
    empt = [(k, l) for k, l in needed if not pool.get(f"{k}|{l}")]
    print(f"repair pass over {len(empt)} empty pools")
    for kind, label in empt:
        time.sleep(2.0)
        res = wikidata_search(label, kind == "property")
        if res:
            pool[f"{kind}|{label}"] = res
    save(pool_file, pool)
    still = sum(1 for k, l in needed if not pool.get(f"{k}|{l}"))
    print(f"labels still without candidates: {still}")

    # ── stage 2: disambiguation ───────────────────────────────
    jobs, chosen = [], {}
    for rid, q in gen.items():
        ents, props = parse_labels(q)
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                cands = pool.get(f"{kind}|{l}", [])[:K]
                key = f"{rid}|{kind}|{l}"
                if len(cands) == 0:
                    chosen[key] = ""
                elif len(cands) == 1:
                    chosen[key] = cands[0]["id"]
                else:
                    jobs.append((rid, kind, l, cands))
    print(f"disambiguating {len(jobs)} labels ({len(chosen)} resolved trivially)")
    if jobs:
        prompts = [chat([{"role": "user",
                          "content": disamb_prompt(qs.get(rid, ""), l, c,
                                                   kind == "property")}])
                   for rid, kind, l, c in jobs]
        outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=400))
        parsed = fallback = 0
        for (rid, kind, l, cands), o in zip(jobs, outs):
            t = o.outputs[0].text if o.outputs else ""
            pat = r'ANSWER:\s*(P\d+)' if kind == "property" else r'ANSWER:\s*(Q\d+)'
            alt = r'\b(P\d+)\b' if kind == "property" else r'\b(Q\d+)\b'
            m = re.search(pat, t) or re.search(alt, t)
            if m:
                chosen[f"{rid}|{kind}|{l}"] = m.group(1); parsed += 1
            else:
                chosen[f"{rid}|{kind}|{l}"] = cands[0]["id"]; fallback += 1
        print(f"parsed {parsed}, fell back {fallback}")

    # ── substitute ────────────────────────────────────────────
    linked = {}
    for rid, q in gen.items():
        s = q
        ents, props = parse_labels(q)
        for kind, labs in [("entity", ents), ("property", props)]:
            for l in labs:
                pid = chosen.get(f"{rid}|{kind}|{l}", "")
                if pid:
                    s = re.sub(r'\[' + kind + ':' + re.escape(l) + r'\]', pid, s, flags=re.I)
        linked[rid] = {"labeled_query": q, "linked_query": s,
                       "fully_linked": bool(s) and "[entity:" not in s
                                       and "[property:" not in s}
    save(out_file, linked)
    fl = sum(1 for v in linked.values() if v["fully_linked"])
    print(f"\nwrote {out_file}: {len(linked)} rows, {fl} fully linked "
          f"({fl/len(linked)*100:.1f}%)")
    print("scp back to the laptop and run: python3 score_open_pipeline.py "
          f"{out_file} --split {a.split}")

if __name__ == "__main__":
    main()
