"""run_refined.py — ReFinED experiment (fine-tuned end-to-end paradigm).
"""

import json, re

from refined.inference.processor import Refined

MODEL      = "questions_model"
ENTITY_SET = "wikidata"

def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def match_score(label, mention):
    """Crude surface similarity: exact > containment > token overlap."""
    L, M = norm(label), norm(mention)
    if not L or not M:
        return 0.0
    if L == M:
        return 1.0
    if L in M or M in L:
        return 0.8
    lt, mt = set(L.split()), set(M.split())
    inter = len(lt & mt)
    return 0.6 * inter / max(len(lt), len(mt)) if inter else 0.0

def main():
    gold_map = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    test = json.load(open("data/test.json"))

    print(f"Loading ReFinED ({MODEL}, entity_set={ENTITY_SET}) — "
          f"first run downloads several GB...")
    refined = Refined.from_pretrained(model_name=MODEL, entity_set=ENTITY_SET,
                                      use_precomputed_descriptions=False)

    set_correct, set_predicted, set_gold = 0, 0, 0
    written = 0

    with open("outputs/preds_refined.jsonl", "w") as out:
        for i, pairs in sorted(gold_map.items()):
            ent_pairs = [(k, l, g) for k, l, g in pairs if k == "entity"]
            if not ent_pairs:
                continue
            question = test[i]["instruction"]

            spans = refined.process_text(question)
            predicted = []   # (mention_text, qid)
            for sp in spans:
                pe = getattr(sp, "predicted_entity", None)
                qid = getattr(pe, "wikidata_entity_id", None) if pe else None
                if qid:
                    predicted.append((sp.text, qid))

            # --- 1) mention-matched predictions (for eval_linker.py) ---
            used = set()
            for kind, label, gid in ent_pairs:
                best, best_s = "", 0.0
                for j, (mtext, qid) in enumerate(predicted):
                    if j in used:
                        continue
                    s = match_score(label, mtext)
                    if s > best_s:
                        best, best_s, best_j = qid, s, j
                if best_s >= 0.5:
                    used.add(best_j)
                else:
                    best = ""
                out.write(json.dumps({"index": i, "kind": kind,
                                      "label": label, "pred_id": best}) + "\n")
                written += 1

            # --- 2) set-based tally (secondary metric) ---
            gold_qids = {g for _, _, g in ent_pairs}
            pred_qids = {q for _, q in predicted}
            set_gold      += len(gold_qids)
            set_predicted += len(pred_qids)
            set_correct   += len(gold_qids & pred_qids)

            if written % 200 < len(ent_pairs):
                print(f"  row {i}, {written} mentions done")

    P = set_correct / set_predicted * 100 if set_predicted else 0
    R = set_correct / set_gold * 100 if set_gold else 0
    F = 2 * P * R / (P + R) if P + R else 0
    print(f"\nWrote {written} predictions -> outputs/preds_refined.jsonl")
    print(f"SET-BASED (secondary): P {P:.1f}%  R {R:.1f}%  F1 {F:.1f}%   "
          f"({set_correct}/{set_predicted}/{set_gold})")
    print("Mention-matched (comparable):  python3 eval_linker.py outputs/preds_refined.jsonl")

if __name__ == "__main__":
    main()
