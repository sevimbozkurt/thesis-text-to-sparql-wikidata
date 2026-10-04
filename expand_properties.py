"""expand_properties.py — Step 1a: clean property candidate pools.

Usage:  python3 expand_properties.py        (resume-safe; ~40-60 min)
"""

import json, time, os, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2
TOP_K = 20
OUT = "properties_expanded.json"

def wbsearch_prop(label, limit=TOP_K):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": limit, "type": "property"}
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
    return None          # None = failed; keep whatever we had

def main():
    gold = {int(k): v for k, v in json.load(open("gold_links.json")).items()}
    test = json.load(open("test.json"))
    cx = {i: test[i]["complexity"] for i in gold}

    mentions, lab_gold = [], collections.defaultdict(set)
    for i, pairs in gold.items():
        for kind, label, gid in pairs:
            if kind != "property":
                continue
            mentions.append((i, label, gid))
            lab_gold[label].add(gid)
    print(f"{len(mentions)} property mentions, {len(lab_gold)} unique labels")

    pool = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [l for l in lab_gold if f"property|{l}" not in pool]
    print(f"fetching {len(todo)} labels (resume-safe)")
    for n, label in enumerate(todo):
        res = wbsearch_prop(label)
        if res is not None:
            pool[f"property|{label}"] = res
        if (n + 1) % 25 == 0:
            json.dump(pool, open(OUT, "w"))
            print(f"  {n+1}/{len(todo)}")
    json.dump(pool, open(OUT, "w"))

    # sanity: short pools that nevertheless contain gold are fine
    short = [l for l in lab_gold if 0 < len(pool.get(f"property|{l}", [])) < 7]
    short_ok = sum(1 for l in short
                   if lab_gold[l] & {c["id"] for c in pool.get(f"property|{l}", [])})
    empty = [l for l in lab_gold if not pool.get(f"property|{l}")]
    print(f"\npools: empty {len(empty)} | short(<7) {len(short)} "
          f"of which gold present {short_ok}")

    base = json.load(open("candidates.json"))
    old7  = lambda l: {c["id"] for c in base.get(f"property|{l}", [])}
    new7  = lambda l: {c["id"] for c in pool.get(f"property|{l}", [])[:7]}
    new20 = lambda l: {c["id"] for c in pool.get(f"property|{l}", [])}

    def ceiling(fn):
        hit = 0
        per = collections.defaultdict(lambda: [0, 0])
        for i, label, gid in mentions:
            per[cx[i]][1] += 1
            if gid in fn(label):
                hit += 1
                per[cx[i]][0] += 1
        return hit, per

    lines = [f"PROPERTY CEILING REPORT — {len(mentions)} property mentions", ""]
    for name, fn in [("old top-7 (as used)", old7),
                     ("clean top-7", new7),
                     ("clean top-20", new20)]:
        hit, per = ceiling(fn)
        detail = " | ".join(f"{c} {per[c][0]}/{per[c][1]}"
                            for c in ["simple", "medium", "complex"])
        lines.append(f"{name:22s} {hit}/{len(mentions)} = "
                     f"{hit/len(mentions)*100:5.1f}%   ({detail})")

    # rank audit: where do previously-missing golds sit now?
    ranks = collections.Counter()
    for i, label, gid in mentions:
        if gid in old7(label):
            continue
        ids = [c["id"] for c in pool.get(f"property|{label}", [])]
        if gid in ids:
            ranks["rank 1-7" if ids.index(gid) < 7 else "rank 8-20"] += 1
        else:
            ranks["still missing"] += 1
    lines += ["", "golds missing from OLD top-7 are now at:"]
    for k, v in ranks.most_common():
        lines.append(f"  {k:14s} {v}")
    lines += ["",
              "Reading: many at rank 1-7 => the earlier property pools were affected by",
              "throttling, as the entity pools were, and property",
              "linking is re-run on the rate-limited pools. Many at rank 8-20 => a genuine depth effect.",
              "Mostly still missing => a real retrieval limit for properties."]

    report = "\n".join(lines)
    print("\n" + report)
    open("property_ceiling_report.txt", "w").write(report + "\n")

if __name__ == "__main__":
    main()
