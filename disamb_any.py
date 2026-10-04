"""disamb_any.py — Generic disambiguation stage for ANY set of labelled
queries, run on the server with an open-weight backbone. Free.

USAGE (server)
  export CUDA_VISIBLE_DEVICES=1
  python disamb_any.py --gen idiom_generated.json --split working  --tag idiom
  python disamb_any.py --gen batch_generated.json --split official --tag officialclean
  # control arm for the idiom experiment (same backbone, baseline generations):
  python disamb_any.py --gen baseline_generated.json --split working --tag baseline
"""

import argparse, json, os, re, sys, time

K = 7
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2

def load(p, d=None):
    if not os.path.exists(p):
        if d is None:
            sys.exit(f"missing: {p}")
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

def search(label, is_prop, delay=DELAY):
    import requests
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": K,
              "type": "property" if is_prop else "item"}
    for a in range(5):
        time.sleep(delay * (a + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h.get("id",""), "label": h.get("label",""),
                         "description": h.get("description","")}
                        for h in r.json().get("search", [])]
            print(f"    HTTP {r.status_code}: {label[:40]!r}")
        except Exception as e:
            print(f"    {type(e).__name__}: {label[:40]!r}")
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True, help="JSON: row_id -> labelled query")
    ap.add_argument("--split", choices=["working", "official"], required=True)
    # R3: the LC-QuAD 2.0 replication supplies its own questions rather than
    # coming from one of this thesis's two splits. Everything downstream --
    # pooling, prompting, the model, the scoring shape -- is unchanged, so the
    # replication runs the same code path the thesis ran.
    ap.add_argument("--questions", default=None,
                    help="JSON {row_id: question}; overrides --split for questions")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--model", default="Qwen/Qwen2.5-14B-Instruct")
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--skip-fetch", action="store_true",
                    help="use only cached pools; do not query Wikidata")
    a = ap.parse_args()

    gen_raw = load(a.gen)
    gen = {str(k): (v if isinstance(v, str) else v.get("labeled_query", ""))
           for k, v in gen_raw.items()}
    gen = {k: v for k, v in gen.items() if v}
    print(f"{len(gen)} labelled queries from {a.gen}")

    if a.questions:
        qs = {str(k): v for k, v in load(a.questions).items()}
    elif a.split == "official":
        rows = load("official_test.json")
        qs = {str(r["id"]): r["instruction"] for r in rows}
    else:
        test = load("test.json")
        qs = {str(i): r["instruction"] for i, r in enumerate(test)}

    pool_file = f"pool_{a.tag}.json"
    pool = load(pool_file, {})
    if not pool:
        for f in ["candidates_expanded.json", "properties_clean.json",
                  "e2e_candidates_clean.json", "candidates_official.json",
                  "pool_qwen-qwen2-5-14b-instruct_official.json"]:
            pool.update(load(f, {}))
        save(pool_file, pool)
    print(f"candidate pool seeded with {len(pool)} labels")

    needed = set()
    for q in gen.values():
        e, p = parse_labels(q)
        needed |= {("entity", x) for x in e} | {("property", x) for x in p}
    missing = [(k, l) for k, l in needed if f"{k}|{l}" not in pool]
    print(f"{len(needed)} distinct labels | {len(missing)} to fetch")

    if missing and not a.skip_fetch:
        for n, (kind, label) in enumerate(missing):
            res = search(label, kind == "property")
            if res is not None:
                pool[f"{kind}|{label}"] = res
            if (n + 1) % 25 == 0:
                save(pool_file, pool); print(f"  {n+1}/{len(missing)}")
        save(pool_file, pool)
        empt = [(k, l) for k, l in needed if not pool.get(f"{k}|{l}")]
        print(f"repair pass over {len(empt)} empty pools")
        for kind, label in empt:
            res = search(label, kind == "property", delay=2.5)
            if res:
                pool[f"{kind}|{label}"] = res
        save(pool_file, pool)
    still = sum(1 for k, l in needed if not pool.get(f"{k}|{l}"))
    print(f"labels without candidates: {still}/{len(needed)}")

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
    print(f"{len(jobs)} to disambiguate ({len(chosen)} trivial)")

    if jobs:
        from vllm import LLM, SamplingParams
        llm = LLM(model=a.model, gpu_memory_utilization=a.gpu_mem,
                  trust_remote_code=True)
        tok = llm.get_tokenizer()
        def chat(text):
            try:
                return tok.apply_chat_template([{"role": "user", "content": text}],
                                               tokenize=False, add_generation_prompt=True)
            except Exception:
                return text
        prompts = [chat(prompt(qs.get(rid, ""), l, c, kind == "property"))
                   for rid, kind, l, c in jobs]
        outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=400))
        parsed = fb = 0
        for (rid, kind, l, cands), o in zip(jobs, outs):
            t = o.outputs[0].text if o.outputs else ""
            pat = r'ANSWER:\s*(P\d+)' if kind == "property" else r'ANSWER:\s*(Q\d+)'
            alt = r'\b(P\d+)\b' if kind == "property" else r'\b(Q\d+)\b'
            m = re.search(pat, t) or re.search(alt, t)
            if m:
                chosen[f"{rid}|{kind}|{l}"] = m.group(1); parsed += 1
            else:
                chosen[f"{rid}|{kind}|{l}"] = cands[0]["id"]; fb += 1
        print(f"parsed {parsed}, fell back {fb}")

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
    out = f"linked_{a.tag}.json"
    save(out, linked)
    fl = sum(1 for v in linked.values() if v["fully_linked"])
    print(f"\nwrote {out}: {len(linked)} rows, {fl} fully linked "
          f"({fl/len(linked)*100:.1f}%)")
    print(f"score on the laptop: python3 score_open_pipeline.py {out} --split {a.split}")

if __name__ == "__main__":
    main()
