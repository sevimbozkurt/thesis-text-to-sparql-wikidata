"""repair_expanded.py — Repair throttled pools in candidates_expanded.json
(flat format: {"entity|<label>": [candidates]}).

Usage:  python3 repair_expanded.py
"""

import json, time, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 2.5
OUT = "candidates_expanded.json"

def wbsearch(label):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": 20, "type": "item"}
    for a in range(5):
        time.sleep(DELAY * (a + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h.get("id",""), "label": h.get("label",""),
                         "description": h.get("description",""), "src": "wbsearch"}
                        for h in r.json().get("search", [])]
            print(f"  HTTP {r.status_code}: {label!r}")
        except Exception as e:
            print(f"  {type(e).__name__}: {label!r}")
    return None   # signal: failed, keep old

def fulltext(label):
    params = {"action": "query", "list": "search", "srsearch": label,
              "srnamespace": 0, "srlimit": 10, "format": "json"}
    for a in range(5):
        time.sleep(DELAY * (a + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h["title"], "label": h["title"], "description": "",
                         "src": "fulltext"}
                        for h in r.json().get("query", {}).get("search", [])
                        if h.get("title", "").startswith("Q")]
            print(f"  HTTP {r.status_code} (ft): {label!r}")
        except Exception as e:
            print(f"  {type(e).__name__} (ft): {label!r}")
    return None

gold = {int(k): v for k, v in json.load(open("gold_links.json")).items()}
lab_gold = collections.defaultdict(set)
for ps in gold.values():
    for k, l, g in ps:
        if k == "entity":
            lab_gold[l].add(g)

pool = json.load(open(OUT))

# pass 1: refetch empty or short wbsearch portions
todo = [l for l in lab_gold
        if len([c for c in pool.get(f"entity|{l}", []) if c["src"] == "wbsearch"]) < 7]
print(f"pools to repair (wbsearch < 7): {len(todo)}")
fixed = 0
for n, label in enumerate(todo):
    res = wbsearch(label)
    if res:   # keep old on failure or genuinely-empty return handled below
        ft = [c for c in pool.get(f"entity|{label}", []) if c["src"] == "fulltext"]
        have = {c["id"] for c in res}
        pool[f"entity|{label}"] = res + [c for c in ft if c["id"] not in have]
        fixed += 1
    if (n + 1) % 20 == 0:
        json.dump(pool, open(OUT, "w"))
        print(f"  {n+1}/{len(todo)} (repaired {fixed})")
json.dump(pool, open(OUT, "w"))
print(f"pass 1 done: repaired {fixed}/{len(todo)}")

# pass 2: fulltext fallback where gold still absent
todo2 = [l for l, g in lab_gold.items()
         if not (g & {c["id"] for c in pool.get(f"entity|{l}", [])})
         and not any(c["src"] == "fulltext" for c in pool.get(f"entity|{l}", []))]
print(f"labels needing fulltext fallback: {len(todo2)}")
added = 0
for n, label in enumerate(todo2):
    res = fulltext(label)
    if res:
        have = {c["id"] for c in pool.get(f"entity|{label}", [])}
        pool[f"entity|{label}"] = pool.get(f"entity|{label}", []) + \
                                  [c for c in res if c["id"] not in have]
        added += 1
    if (n + 1) % 20 == 0:
        json.dump(pool, open(OUT, "w"))
json.dump(pool, open(OUT, "w"))
print(f"pass 2 done: fulltext added for {added}/{len(todo2)}")

# summary
empty = sum(1 for l in lab_gold if not pool.get(f"entity|{l}"))
short = sum(1 for l in lab_gold
            if 0 < len([c for c in pool.get(f'entity|{l}', []) if c['src']=='wbsearch']) < 7)
print(f"\nremaining: empty pools {empty}, short wbsearch pools {short}")
print("if both are near zero:  python3 expand_candidates.py   (recomputes the ceiling, no refetch)")
