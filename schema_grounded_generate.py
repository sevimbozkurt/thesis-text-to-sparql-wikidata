"""schema_grounded_generate.py — Schema-grounded query generation. STAGE 2:
generation with the retrieved schema evidence (server, vLLM, free).

USAGE (server, vllm env, one GPU)
  export CUDA_VISIBLE_DEVICES=1
  python schema_grounded_generate.py --split working \
         --cards data/schema_cards_working.json --tag grounded
Output: grounded_generated_<tag>.json  — then link it with disamb_any.py and
score with score_open_pipeline.py, exactly as the other arms.
"""

import argparse, json, os, re, sys

BASE_SYSTEM = """You are a SPARQL expert for Wikidata. Generate a SPARQL query that
answers the question, but instead of using opaque Wikidata IDs, use human-readable
labels in this exact bracket format:
  - For entities:   wd:[entity:LABEL]      e.g. wd:[entity:Christopher Nolan]
  - For properties: wdt:[property:LABEL]   e.g. wdt:[property:director]
Use this format for ALL entities and properties. Keep variable names and SPARQL
structure normal. Output ONLY the SPARQL query, no explanation."""

GROUNDING_PREAMBLE = """
The following facts were retrieved from Wikidata for the entities this question
concerns. Use them to decide how to model the query:

{evidence}

Guidance for reading this evidence:
  - if an entity is marked as a class with subclasses, match instances with
    wdt:[property:instance of]/wdt:[property:subclass of]* rather than a direct
    instance-of triple
  - if the value the question asks for is listed as a qualifier, it can only be
    reached through the statement: ?item p:[property:P] ?st . ?st
    ps:[property:P] ?value ; pq:[property:QUALIFIER] ?qvalue
  - if a property is marked quantity-valued, the unit lives on the statement
    value node: ?item p:[property:P]/psv:[property:P] ?vn . ?vn
    wikibase:quantityAmount ?amount ; wikibase:quantityUnit ?unit
  - use only what the question actually requires; do not add machinery that is
    not needed
"""

def load(p, d=None):
    if not os.path.exists(p):
        if d is None:
            sys.exit(f"missing input: {p}")
        return d
    return json.load(open(p))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["working", "official"], default="working")
    ap.add_argument("--cards", required=True)
    ap.add_argument("--tag", default="grounded")
    ap.add_argument("--model", default="Qwen/Qwen2.5-14B-Instruct")
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    a = ap.parse_args()

    cards = load(a.cards)
    if a.split == "working":
        test = load("data/test.json")
        qs = {str(i): r["instruction"] for i, r in enumerate(test)}
    else:
        rows = load("data/official_test.json")
        qs = {str(r["id"]): r["instruction"] for r in rows}

    targets = [rid for rid in qs if rid in cards]
    with_ev = sum(1 for rid in targets if cards[rid].strip())
    print(f"{a.split}: {len(targets)} questions have schema cards "
          f"({with_ev} with non-empty evidence)")

    out_file = f"grounded_generated_{a.tag}.json"
    gen = load(out_file, {})
    todo = [rid for rid in targets if rid not in gen]
    print(f"to generate: {len(todo)}")
    if not todo:
        print("nothing to do"); return

    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, gpu_memory_utilization=a.gpu_mem, trust_remote_code=True)
    tok = llm.get_tokenizer()

    prompts = []
    for rid in todo:
        ev = cards[rid].strip()
        system = BASE_SYSTEM + (GROUNDING_PREAMBLE.format(evidence=ev) if ev else "")
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": f"Question: {qs[rid]}"}]
        try:
            prompts.append(tok.apply_chat_template(msgs, tokenize=False,
                                                   add_generation_prompt=True))
        except Exception:
            prompts.append(system + "\n\nQuestion: " + qs[rid])

    outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=1024))
    for rid, o in zip(todo, outs):
        t = o.outputs[0].text if o.outputs else ""
        if "```" in t:
            t = "\n".join(l for l in t.split("\n")
                          if not l.strip().startswith("```")).strip()
        gen[rid] = t.strip()
    json.dump(gen, open(out_file, "w"), indent=1)

    empty = sum(1 for v in gen.values() if not v)
    print(f"\nwrote {out_file}: {len(gen)} queries ({empty} empty)")

    # quick behavioural readout, same constructs as the idiom experiment
    import collections
    c = collections.Counter()
    for q in gen.values():
        if re.search(r'subclass of\]\s*\*', q or ''): c["P279* closure"] += 1
        if re.search(r'\bp:\[', q or ''): c["statement node p:"] += 1
        if re.search(r'\bpq:\[', q or ''): c["qualifier pq:"] += 1
        if re.search(r'\bpsv:\[', q or ''): c["value node psv:"] += 1
        if re.search(r'(?i)\bgroup by\b', q or ''): c["GROUP BY"] += 1
        if re.search(r'(?i)\blimit\b', q or ''): c["LIMIT"] += 1
    print("\nconstruct usage in the grounded generations:")
    for k, v in sorted(c.items()):
        print(f"  {k:20s} {v:4d}")
    print("\ngold reference (working split): closure 149, p: 130, pq: 85, "
          "psv: 35, GROUP BY 177, LIMIT 64")
    print("baseline / idiom arms: closure 50 / 264, p: 25 / 45, pq: 21 / 29, "
          "psv: 2 / 6")
    print(f"\nNext: link with  python disamb_any.py --gen {out_file} "
          f"--split {a.split} --tag {a.tag}")

if __name__ == "__main__":
    main()
