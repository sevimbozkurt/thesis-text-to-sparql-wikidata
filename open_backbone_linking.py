"""open_backbone_linking.py — Run the reasoning-based linker with an
OPEN-WEIGHT backbone, on the server, with vLLM.

USAGE (server, conda env with vllm, one GPU):
  export CUDA_VISIBLE_DEVICES=1
  python open_backbone_linking.py --model Qwen/Qwen3-32B --split working
  python open_backbone_linking.py --model Qwen/Qwen3-32B --split working --kind property
"""

import argparse, json, os, re, sys

K = 7

def load(p, d=None):
    if not os.path.exists(p):
        sys.exit(f"missing input: {p}")
    return json.load(open(p))

def build_jobs(split, kind):
    if split == "working":
        gold = {str(k): v for k, v in load("data/gold_links.json").items()}
        test = load("data/test.json")
        qs = {str(i): r["instruction"] for i, r in enumerate(test)}
        ent_pool = load("data/candidates_expanded.json")
        prop_pool = load("data/properties_clean.json") if os.path.exists("data/properties_clean.json") else {}
    else:
        gold = load("data/gold_links_official.json")
        rows = load("data/official_test.json")
        qs = {str(r["id"]): r["instruction"] for r in rows}
        ent_pool = prop_pool = load("data/candidates_official.json")

    jobs = []
    for rid, pairs in gold.items():
        q = qs.get(rid, "")
        for k, label, gid in pairs:
            if k != kind:
                continue
            pool = ent_pool if k == "entity" else prop_pool
            cands = [c for c in pool.get(f"{k}|{label}", [])
                     if c.get("src", "wbsearch") == "wbsearch"][:K]
            jobs.append({"rid": rid, "kind": k, "label": label,
                         "question": q, "cands": cands})
    return jobs

def prompt_text(job):
    kind = job["kind"]
    ctext = "\n".join(f"  {c['id']}: {c['label']} — {c['description'] or '(no description)'}"
                      for c in job["cands"])
    ex = "P57" if kind == "property" else "Q25191"
    return (f'Question: "{job["question"]}"\n\nFind the correct Wikidata {kind} ID for: '
            f'"{job["label"]}"\n\nCandidates:\n{ctext}\n\nThink step by step about which '
            f'candidate best fits the {kind} "{job["label"]}" in the context of the '
            f'question. Output ONLY the chosen ID (e.g. {ex}) on the last line, prefixed '
            f'with "ANSWER: ".\n')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True,
                    help="e.g. Qwen/Qwen3-32B, meta-llama/Llama-3.3-70B-Instruct")
    ap.add_argument("--split", choices=["working", "official"], default="working")
    ap.add_argument("--kind", choices=["entity", "property"], default="entity")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--tp", type=int, default=1, help="tensor parallel size")
    a = ap.parse_args()

    jobs = build_jobs(a.split, a.kind)
    print(f"{a.split} split, {a.kind} mentions: {len(jobs)}")

    # trivial cases need no model call, exactly as in the API pipeline
    trivial = {}
    to_run = []
    for j in jobs:
        if len(j["cands"]) == 0:
            trivial[f'{j["rid"]}|{j["label"]}'] = ""
        elif len(j["cands"]) == 1:
            trivial[f'{j["rid"]}|{j["label"]}'] = j["cands"][0]["id"]
        else:
            to_run.append(j)
    print(f"resolved without the model: {len(trivial)} | to generate: {len(to_run)}")

    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, gpu_memory_utilization=a.gpu_mem,
              tensor_parallel_size=a.tp, trust_remote_code=True)
    tok = llm.get_tokenizer()

    prompts = []
    for j in to_run:
        msgs = [{"role": "user", "content": prompt_text(j)}]
        try:
            prompts.append(tok.apply_chat_template(msgs, tokenize=False,
                                                   add_generation_prompt=True))
        except Exception:
            prompts.append(prompt_text(j))

    params = SamplingParams(temperature=0.0, max_tokens=a.max_tokens)
    print("generating...")
    outs = llm.generate(prompts, params)

    pat = r'ANSWER:\s*(P\d+)' if a.kind == "property" else r'ANSWER:\s*(Q\d+)'
    alt = r'\b(P\d+)\b' if a.kind == "property" else r'\b(Q\d+)\b'
    chosen = dict(trivial)
    parsed = fallback = 0
    for j, o in zip(to_run, outs):
        text = o.outputs[0].text if o.outputs else ""
        m = re.search(pat, text) or re.search(alt, text)
        if m:
            chosen[f'{j["rid"]}|{j["label"]}'] = m.group(1); parsed += 1
        else:
            chosen[f'{j["rid"]}|{j["label"]}'] = j["cands"][0]["id"]; fallback += 1
    print(f"parsed an ID from {parsed} responses; fell back to top candidate "
          f"for {fallback}")

    tag = re.sub(r'[^A-Za-z0-9]+', '-', a.model).strip('-').lower()
    out = f"outputs/preds_{tag}_{a.split}_{a.kind}.jsonl"
    with open(out, "w") as f:
        for j in jobs:
            f.write(json.dumps({"index": j["rid"], "kind": j["kind"],
                                "label": j["label"],
                                "pred_id": chosen.get(f'{j["rid"]}|{j["label"]}', "")}) + "\n")
    print(f"wrote {len(jobs)} predictions -> {out}")
    print("scp back and score with eval_linker.py (working) or "
          "eval_linker_official.py (official)")
    print("For the working split, remember the evaluator expects integer row "
          "indices: convert with json before scoring if needed.")

if __name__ == "__main__":
    main()
