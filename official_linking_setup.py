"""official_linking_setup.py — Stage 1 (FREE): build the linking ground truth
and candidate pools for the OFFICIAL test split.

Usage:  python3 official_linking_setup.py          (resume-safe; 1-2 h)
"""

import json, re, os, time, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2
K = 7

OFFICIAL = "data/official_test.json"
GOLD_OUT = "data/gold_links_official.json"
CAND_OUT = "data/candidates_official.json"

BRACKET = re.compile(r'\[(entity|property):([^\]]+)\]')
GOLDID  = re.compile(r'\b([QP]\d+)\b')

def align(annotated, gold):
    brackets = [(m.group(1), m.group(2).strip()) for m in BRACKET.finditer(annotated or "")]
    ids = GOLDID.findall(gold or "")
    if not brackets or len(brackets) != len(ids):
        return None
    pairs = []
    for (kind, label), gid in zip(brackets, ids):
        if not gid.startswith("Q" if kind == "entity" else "P"):
            return None
        pairs.append([kind, label, gid])
    return pairs

def search(label, is_prop):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": K,
              "type": "property" if is_prop else "item"}
    for a in range(5):
        time.sleep(DELAY * (a + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h.get("id", ""), "label": h.get("label", ""),
                         "description": h.get("description", "")}
                        for h in r.json().get("search", [])]
            print(f"  HTTP {r.status_code}: {label!r}")
        except Exception as e:
            print(f"  {type(e).__name__}: {label!r}")
    return None

def main():
    rows = json.load(open(OFFICIAL))
    print(f"official test split: {len(rows)} rows")

    # ── 1. alignment ──────────────────────────────────────────
    gold_map, skipped = {}, []
    for r in rows:
        pairs = align(r.get("annotated", ""), r.get("query", ""))
        if pairs is None:
            skipped.append(r["id"])
        else:
            gold_map[str(r["id"])] = pairs
    json.dump(gold_map, open(GOLD_OUT, "w"), indent=1)

    n_ent = sum(1 for ps in gold_map.values() for p in ps if p[0] == "entity")
    n_prop = sum(1 for ps in gold_map.values() for p in ps if p[0] == "property")
    cxc = collections.Counter(r["complexity"] for r in rows if str(r["id"]) in gold_map)
    print(f"aligned {len(gold_map)}/{len(rows)} rows "
          f"({len(gold_map)/len(rows)*100:.1f}%) — {dict(cxc)}")
    print(f"mentions: {n_ent} entity, {n_prop} property")
    print(f"skipped {len(skipped)} rows (bracket/ID count or kind mismatch)")
    print(f"wrote {GOLD_OUT}\n")

    # ── 2. candidates ─────────────────────────────────────────
    labels = {(k, l) for ps in gold_map.values() for k, l, g in ps}
    pool = json.load(open(CAND_OUT)) if os.path.exists(CAND_OUT) else {}

    # reuse anything already fetched for the working split (same label text)
    reused = 0
    for f in ["data/candidates_expanded.json", "data/properties_clean.json",
              "e2e_candidates_clean.json", "candidates.json"]:
        if not os.path.exists(f):
            continue
        prev = json.load(open(f))
        for kind, l in labels:
            key = f"{kind}|{l}"
            if key not in pool and prev.get(key):
                pool[key] = prev[key][:K]
                reused += 1
    json.dump(pool, open(CAND_OUT, "w"))
    todo = [(k, l) for k, l in labels if f"{k}|{l}" not in pool]
    print(f"{len(labels)} unique labels | reused from earlier fetches {reused} "
          f"| to fetch {len(todo)}")

    for n, (kind, label) in enumerate(todo):
        res = search(label, kind == "property")
        if res is not None:
            pool[f"{kind}|{label}"] = res
        if (n + 1) % 25 == 0:
            json.dump(pool, open(CAND_OUT, "w"))
            print(f"  {n+1}/{len(todo)}")
    json.dump(pool, open(CAND_OUT, "w"))

    # repair pass over empties
    empt = [(k, l) for k, l in labels if not pool.get(f"{k}|{l}")]
    print(f"\nrepair pass over {len(empt)} empty pools")
    fixed = 0
    for n, (kind, label) in enumerate(empt):
        time.sleep(2.0)
        res = search(label, kind == "property")
        if res:
            pool[f"{kind}|{label}"] = res
            fixed += 1
        if (n + 1) % 20 == 0:
            json.dump(pool, open(CAND_OUT, "w"))
            print(f"  {n+1}/{len(empt)} recovered {fixed}")
    json.dump(pool, open(CAND_OUT, "w"))
    print(f"recovered {fixed}")

    # ── 3. ceiling ────────────────────────────────────────────
    def ceiling(kind):
        tot = hit = 0
        for ps in gold_map.values():
            for k, l, g in ps:
                if k != kind:
                    continue
                tot += 1
                if g in {c["id"] for c in pool.get(f"{k}|{l}", [])}:
                    hit += 1
        return hit, tot

    print("\ncandidate ceiling (gold identifier present in the top-7 pool):")
    for kind in ["entity", "property"]:
        h, t = ceiling(kind)
        if t:
            print(f"  {kind:9s} {h}/{t} = {h/t*100:.1f}%")
    still = [(k, l) for k, l in labels if not pool.get(f"{k}|{l}")]
    print(f"\nlabels without candidates after repair: {len(still)}")
    print("examples:", [l[:40] for _, l in still[:8]])
    print(f"\nwrote {CAND_OUT}")
    print("If the ceilings are ~99%, the pools are healthy and the linker")
    print("comparison can be re-run on this split.")

if __name__ == "__main__":
    main()
