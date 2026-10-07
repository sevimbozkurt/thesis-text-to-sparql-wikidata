"""refetch_candidates.py — Repair empty candidate lists in
batch_candidates.json.

Usage:  python3 refetch_candidates.py
"""

import json, time, os, sys
import requests

CAND = "data/batch_candidates.json"
API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
N = 7
DELAY = 1.2           # base delay between requests
MAX_PASSES = 3

def search(label, is_prop):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": N,
              "type": "property" if is_prop else "item"}
    for attempt in range(4):
        time.sleep(DELAY * (attempt + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                hits = r.json().get("search", [])
                return [{"id": h.get("id",""), "label": h.get("label",""),
                         "description": h.get("description","")} for h in hits]
            print(f"    HTTP {r.status_code} for {label!r}")
        except Exception as e:
            print(f"    {type(e).__name__} for {label!r}")
    return []

if not os.path.exists(CAND):
    sys.exit(f"{CAND} not found — run: python3 run_official_batch.py candidates")

for p in range(1, MAX_PASSES + 1):
    cache = json.load(open(CAND))
    empties = [(rid, kind, label)
               for rid, kinds in cache.items()
               for kind, labels in kinds.items()
               for label, v in labels.items() if not v]
    total = sum(len(labels) for kinds in cache.values() for labels in kinds.values())
    print(f"\npass {p}: {len(empties)} empty of {total} labels")
    if not empties:
        break
    fixed = 0
    for n, (rid, kind, label) in enumerate(empties):
        res = search(label, kind == "property")
        if res:
            cache[rid][kind][label] = res
            fixed += 1
        if (n + 1) % 20 == 0:
            json.dump(cache, open(CAND, "w"))
            print(f"  {n+1}/{len(empties)} (recovered {fixed})")
    json.dump(cache, open(CAND, "w"))
    print(f"pass {p} done: recovered {fixed} of {len(empties)}")
    if fixed == 0:
        print("no further recovery — remaining empties look like genuine misses")
        break

cache = json.load(open(CAND))
empties = [(rid, kind, label)
           for rid, kinds in cache.items()
           for kind, labels in kinds.items()
           for label, v in labels.items() if not v]
print(f"\nfinal: {len(empties)} labels still without candidates")
for e in empties[:15]:
    print("  ", e[1], "|", e[2][:70])
