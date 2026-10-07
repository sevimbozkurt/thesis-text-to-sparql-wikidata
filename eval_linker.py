"""eval_linker.py — Score ANY linker's predictions against gold_links.json.

Usage:
    python3 eval_linker.py outputs/preds_reasoning_clean.jsonl
    python3 eval_linker.py outputs/preds_glinker_restricted_desc.jsonl
"""

import json, sys, collections

def prf(correct, predicted, gold):
    P = correct / predicted * 100 if predicted else 0.0
    R = correct / gold * 100 if gold else 0.0
    F = 2 * P * R / (P + R) if P + R else 0.0
    return P, R, F

def main(pred_file):
    gold_map = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    test = json.load(open("data/test.json"))
    complexity = {i: ex["complexity"] for i, ex in enumerate(test)}

    preds = collections.defaultdict(dict)   # index -> {(kind,label): pred_id}
    with open(pred_file) as f:
        for line in f:
            r = json.loads(line)
            preds[r["index"]][(r["kind"], r["label"])] = r["pred_id"]

    stats = {"entity": [0, 0, 0], "property": [0, 0, 0]}   # correct, predicted, gold
    by_cx = collections.defaultdict(lambda: {"entity": [0, 0, 0], "property": [0, 0, 0]})
    rows_all_ok, rows_total = 0, 0

    for i, pairs in gold_map.items():
        if i not in preds:
            continue
        rows_total += 1
        cx, all_ok = complexity[i], True
        for kind, label, gid in pairs:
            pid = preds[i].get((kind, label), "")
            for S in (stats, by_cx[cx]):
                S[kind][2] += 1
                if pid:
                    S[kind][1] += 1
                if pid == gid:
                    S[kind][0] += 1
            if pid != gid:
                all_ok = False
        if all_ok:
            rows_all_ok += 1

    print(f"\n=== {pred_file} ===  ({rows_total} rows evaluated)\n")
    print(f"{'':10s} {'P':>7s} {'R':>7s} {'F1':>7s}   (correct/predicted/gold)")
    for kind in ["entity", "property"]:
        c, p, g = stats[kind]
        if g == 0:
            print(f"{kind:10s} {'—':>7s}  (no gold mentions of this kind in predictions)")
            continue
        P, R, F = prf(c, p, g)
        print(f"{kind:10s} {P:6.1f}% {R:6.1f}% {F:6.1f}%   ({c}/{p}/{g})")

    print(f"\nRow-level: ALL links correct on {rows_all_ok}/{rows_total} rows "
          f"= {rows_all_ok/rows_total*100:.1f}%")

    print(f"\n{'Complexity':<10} {'entity F1':>10} {'property F1':>12}")
    for cx in ["simple", "medium", "complex"]:
        if cx not in by_cx:
            continue
        line = f"{cx:<10}"
        for kind in ["entity", "property"]:
            c, p, g = by_cx[cx][kind]
            line += f" {prf(c,p,g)[2]:9.1f}%" if g else f" {'—':>10}"
        print(line)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "outputs/preds_reasoning_clean.jsonl")
