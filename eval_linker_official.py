"""eval_linker_official.py — Score linker predictions against the
OFFICIAL-split ground truth (gold_links_official.json, string row ids).

Usage:
  python3 eval_linker_official.py preds_reasoning_official.jsonl
  python3 eval_linker_official.py preds_glinker_official.jsonl
  python3 eval_linker_official.py preds_refined_official.jsonl
"""

import json, sys, collections

def main(pred_file):
    gold = json.load(open("gold_links_official.json"))
    rows = {str(r["id"]): r for r in json.load(open("official_test.json"))}

    preds = collections.defaultdict(dict)
    with open(pred_file) as f:
        for line in f:
            r = json.loads(line)
            preds[str(r["index"])][(r["kind"], r["label"])] = r["pred_id"]

    stats = {k: {"c": 0, "p": 0, "g": 0} for k in ["entity", "property"]}
    bycx  = {c: {k: {"c": 0, "p": 0, "g": 0} for k in ["entity", "property"]}
             for c in ["simple", "medium", "complex"]}
    rows_all = rows_ok = 0
    evaluated = 0

    for rid, pairs in gold.items():
        if rid not in preds:
            continue
        evaluated += 1
        cx = rows.get(rid, {}).get("complexity", "medium")
        all_ok = True
        for kind, label, gid in pairs:
            pid = preds[rid].get((kind, label), "")
            stats[kind]["g"] += 1
            bycx[cx][kind]["g"] += 1
            if pid:
                stats[kind]["p"] += 1
                bycx[cx][kind]["p"] += 1
            if pid == gid:
                stats[kind]["c"] += 1
                bycx[cx][kind]["c"] += 1
            else:
                all_ok = False
        rows_all += 1
        rows_ok += all_ok

    def prf(d):
        P = d["c"] / d["p"] * 100 if d["p"] else 0.0
        R = d["c"] / d["g"] * 100 if d["g"] else 0.0
        F = 2 * P * R / (P + R) if P + R else 0.0
        return P, R, F

    print(f"=== {pred_file} ===  ({evaluated} rows evaluated, official split)\n")
    print(f"{'':12s} {'P':>7} {'R':>7} {'F1':>7}   (correct/predicted/gold)")
    for k in ["entity", "property"]:
        if stats[k]["g"] == 0:
            continue
        P, R, F = prf(stats[k])
        print(f"{k:12s} {P:6.1f}% {R:6.1f}% {F:6.1f}%   "
              f"({stats[k]['c']}/{stats[k]['p']}/{stats[k]['g']})")
    print(f"\nRow-level: ALL links correct on {rows_ok}/{rows_all} rows "
          f"= {rows_ok/rows_all*100:.1f}%" if rows_all else "no rows")
    print(f"\n{'Complexity':10s} {'entity F1':>10} {'property F1':>12}")
    for c in ["simple", "medium", "complex"]:
        fe = prf(bycx[c]["entity"])[2]
        fp = prf(bycx[c]["property"])[2]
        print(f"{c:10s} {fe:9.1f}% {fp:11.1f}%")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "preds_reasoning_official.jsonl")
