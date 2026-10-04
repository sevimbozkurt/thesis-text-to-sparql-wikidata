"""build_gold_links.py — Build the entity-linking ground truth.
"""

import json, re

BRACKET = re.compile(r'\[(entity|property):([^\]]+)\]')
GOLDID  = re.compile(r'\b([QP]\d+)\b')

def align(annotated, gold):
    brackets = [(m.group(1), m.group(2).strip()) for m in BRACKET.finditer(annotated)]
    ids = GOLDID.findall(gold)
    if len(brackets) != len(ids):
        return None
    pairs = []
    for (kind, label), gid in zip(brackets, ids):
        if not gid.startswith('Q' if kind == 'entity' else 'P'):
            return None
        pairs.append([kind, label, gid])
    return pairs

if __name__ == "__main__":
    test = json.load(open("test.json"))
    gold_map, mismatched = {}, []
    for i, ex in enumerate(test):
        pairs = align(ex["annotated"], ex["query"])
        if pairs is None:
            mismatched.append(i)
        else:
            gold_map[i] = pairs

    with open("gold_links.json", "w") as f:
        json.dump({str(k): v for k, v in gold_map.items()}, f, indent=1)

    n_ent  = sum(1 for ps in gold_map.values() for p in ps if p[0] == "entity")
    n_prop = sum(1 for ps in gold_map.values() for p in ps if p[0] == "property")
    print(f"Aligned {len(gold_map)}/{len(test)} rows "
          f"({n_ent} entity mentions, {n_prop} property mentions)")
    print(f"Skipped {len(mismatched)} rows (bracket/ID count mismatch): "
          f"{mismatched[:10]}{'...' if len(mismatched) > 10 else ''}")
