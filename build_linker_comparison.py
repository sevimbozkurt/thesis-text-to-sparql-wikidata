"""build_linker_comparison.py — Rebuild linker_comparison.csv from the
prediction files, so every row of the linker table is computed by one scorer
instead of being copied from separate evaluator printouts.

Usage:  python3 build_linker_comparison.py
"""

import csv, json, collections

SPLITS = {
    "working": dict(gold="gold_links.json",
                    complexity={str(i): r["complexity"]
                                for i, r in enumerate(json.load(open("test.json")))}),
    "official": dict(gold="gold_links_official.json",
                     complexity={str(r["id"]): r["complexity"]
                                 for r in json.load(open("official_test.json"))}),
}

ROWS = [
    ("working", "Reasoning over candidates", "Claude Opus 4.8", "LLM reasoning", "entity", "preds_reasoning_clean.jsonl"),
    ("working", "Reasoning over candidates", "Claude Opus 4.8", "LLM reasoning", "property", "preds_props_clean.jsonl"),
    ("working", "Reasoning over candidates", "Qwen2.5-14B-Instruct", "LLM reasoning", "entity", "preds_qwen_full.jsonl"),
    ("working", "Reasoning over candidates", "Qwen2.5-14B-Instruct", "LLM reasoning", "property", "preds_qwen_full.jsonl"),
    ("working", "Reasoning over candidates", "Qwen2.5-7B-Instruct", "LLM reasoning", "entity", "preds_qwen7b_entity.jsonl"),
    ("working", "GLiNKER gliner-linker-large-v1.0", "-", "zero-shot bi-encoder", "entity", "preds_glinker_restricted_desc.jsonl"),
    ("working", "ELQ elq_wiki_large", "-", "fine-tuned end-to-end", "entity", "preds_elq.jsonl"),
    ("working", "ReFinED questions_model", "-", "fine-tuned end-to-end", "entity", "preds_refined.jsonl"),
    ("working", "First search result", "-", "reference, no model", "entity", "preds_first_search_result.jsonl"),
    ("official", "Reasoning over candidates", "Qwen2.5-14B-Instruct", "LLM reasoning", "entity", "preds_qwen-qwen2-5-14b-instruct_official_entity.jsonl"),
    ("official", "Reasoning over candidates", "Qwen2.5-14B-Instruct", "LLM reasoning", "property", "preds_qwen-qwen2-5-14b-instruct_official_property.jsonl"),
    ("official", "GLiNKER gliner-linker-large-v1.0", "-", "zero-shot bi-encoder", "entity", "preds_glinker_restricted_desc_official.jsonl"),
    ("official", "ELQ elq_wiki_large", "-", "fine-tuned end-to-end", "entity", "preds_elq_official.jsonl"),
    ("official", "ReFinED questions_model", "-", "fine-tuned end-to-end", "entity", "preds_refined_official.jsonl"),
    ("official", "First search result", "-", "reference, no model", "entity", "preds_first_search_result_official.jsonl"),
]

def f1(c, p, g):
    P = c / p * 100 if p else 0.0
    R = c / g * 100 if g else 0.0
    return P, R, (2 * P * R / (P + R) if P + R else 0.0)

out = []
for split, linker, backbone, paradigm, kind, path in ROWS:
    gold = json.load(open(SPLITS[split]["gold"]))
    cx = SPLITS[split]["complexity"]
    preds = collections.defaultdict(dict)
    for line in open(path):
        r = json.loads(line)
        preds[str(r["index"])][(r["kind"], r["label"])] = r["pred_id"]
    cnt = {c: [0, 0, 0] for c in ["simple", "medium", "complex", None]}
    for i, pairs in gold.items():
        if str(i) not in preds:
            continue
        for k, label, gid in pairs:
            if k != kind:
                continue
            pid = preds[str(i)].get((k, label), "")
            for key in (None, cx.get(str(i))):
                if key not in cnt:
                    continue
                cnt[key][2] += 1
                cnt[key][1] += bool(pid)
                cnt[key][0] += pid == gid
    c, p, g = cnt[None]
    P, R, F = f1(c, p, g)
    per = [f1(*cnt[k])[2] for k in ["simple", "medium", "complex"]]
    out.append([split, linker, backbone, paradigm, kind, f"{P:.1f}", f"{R:.1f}", f"{F:.1f}"]
               + [f"{v:.1f}" for v in per] + [f"{c}/{p}/{g}", path])
    print(f"{split:9s} {linker[:30]:30s} {backbone[:20]:20s} {kind:9s} F1 {F:5.1f}")

with open("linker_comparison.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Split", "Linker", "Backbone", "Paradigm", "Mentions", "P (%)", "R (%)", "F1 (%)",
                "F1 simple", "F1 medium", "F1 complex", "Correct/Predicted/Gold", "Source file"])
    w.writerows(out)
print("wrote linker_comparison.csv")
