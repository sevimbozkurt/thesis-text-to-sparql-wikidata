"""run_glinker_restricted.py — GLiNKER choosing among each label's own
candidates.

Usage:
    python3 run_glinker_restricted.py --template desc  [--split official] [--limit N]
    python3 eval_linker.py preds_glinker_restricted_desc.jsonl
    python3 eval_linker_official.py preds_glinker_restricted_desc_official.jsonl
"""

import argparse, json, warnings

MODEL = "knowledgator/gliner-linker-large-v1.0"
POOL  = "candidates_expanded.json"
K     = 7
TEMPLATES = {"desc": "{label}: {description}", "label": "{label}"}

def build_text_and_spans(question, labels):
    text = question.rstrip() + "\nMentions: "
    spans = []
    for lbl in labels:
        start = len(text)
        text += lbl
        spans.append({"text": lbl, "start": start, "end": len(text)})
        text += " ; "
    return text, spans

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", choices=TEMPLATES, default="desc")
    ap.add_argument("--split", choices=["working", "official"], default="working")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    official = a.split == "official"
    out_path = (f"preds_glinker_restricted_{a.template}"
                + ("_official" if official else "") + ".jsonl")

    warnings.filterwarnings("ignore")
    from glinker import ProcessorFactory
    if official:
        pool = json.load(open("candidates_official.json"))
        gold = json.load(open("gold_links_official.json"))
        question = {str(r["id"]): r["instruction"] for r in json.load(open("official_test.json"))}
        def cands_for(label):
            return pool.get(f"entity|{label}", [])[:K]
    else:
        pool = json.load(open(POOL))
        gold = {int(k): v for k, v in json.load(open("gold_links.json")).items()}
        question = dict(enumerate(r["instruction"] for r in json.load(open("test.json"))))
        def cands_for(label):
            return [c for c in pool.get(f"entity|{label}", []) if c.get("src") == "wbsearch"][:K]
    executor = ProcessorFactory.create_simple(
        model_name=MODEL, template=TEMPLATES[a.template], external_entities=True)

    n = hit = 0
    with open(out_path, "w") as out:
        for i, pairs in sorted(gold.items()):
            for kind, label, gid in pairs:
                if kind != "entity":
                    continue
                cands = cands_for(label)
                pred = ""
                if cands:
                    executor.clear_databases()
                    executor.load_entities([{
                        "entity_id": c["id"], "label": c.get("label") or c["id"],
                        "description": c.get("description") or "",
                        "aliases": [label], "entity_type": "entity"} for c in cands])
                    text, spans = build_text_and_spans(question.get(i, ""), [label])
                    res = executor.execute({"texts": [text], "entities": [spans]})
                    l0 = res.get("l0_result")
                    for ent in (l0.entities[0] if l0 and l0.entities else []):
                        le = getattr(ent, "linked_entity", None)
                        if le is not None and ent.mention_text == label:
                            pred = le.entity_id
                    hit += gid in {c["id"] for c in cands}
                out.write(json.dumps({"index": i, "kind": kind, "label": label,
                                      "pred_id": pred, "n_candidates": len(cands)}) + "\n")
                n += 1
                if n % 100 == 0:
                    print(f"  {n} mentions", flush=True)
                if a.limit and n >= a.limit:
                    break
            if a.limit and n >= a.limit:
                break
    print(f"wrote {n} predictions -> {out_path}; gold among candidates for {hit}/{n}")

if __name__ == "__main__":
    main()
