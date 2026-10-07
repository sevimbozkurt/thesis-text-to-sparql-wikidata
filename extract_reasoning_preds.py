"""extract_reasoning_preds.py — Recover the reasoning linker's predictions from
the cached outputs/results_linking.csv (no API calls).
"""

import json, re, csv

BRACKET = re.compile(r'\[(entity|property):([^\]]+)\]')
TOKEN   = re.compile(r'\[(?:entity|property):[^\]]+\]|\b[QP]\d+\b')

gold_map = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
test     = json.load(open("data/test.json"))
linking  = {int(r["index"]): r for r in csv.DictReader(open("outputs/results_linking.csv"))}

written, skipped = 0, 0
with open("preds_reasoning.jsonl", "w") as out:
    for i, pairs in gold_map.items():
        row = linking.get(i)
        if not row:
            skipped += 1
            continue
        tokens = TOKEN.findall(row["linked_query"])
        if len(tokens) != len(pairs):
            # partial/failed linking made positions unrecoverable ->
            # count every mention as unresolved (pred_id = "")
            for kind, label, _ in pairs:
                out.write(json.dumps({"index": i, "kind": kind,
                                      "label": label, "pred_id": ""}) + "\n")
                written += 1
            continue
        for (kind, label, _), tok in zip(pairs, tokens):
            pred = "" if tok.startswith("[") else tok
            out.write(json.dumps({"index": i, "kind": kind,
                                  "label": label, "pred_id": pred}) + "\n")
            written += 1

print(f"Wrote {written} mention predictions to preds_reasoning.jsonl "
      f"({skipped} rows missing from outputs/results_linking.csv)")
