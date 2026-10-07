"""fetch_candidates.py — Build the candidate pool for the linker comparison.
"""

import json, time, requests, os

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
N_CANDIDATES = 7
DELAY = 0.4

def search(label, is_property):
    time.sleep(DELAY)
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": N_CANDIDATES,
              "type": "property" if is_property else "item"}
    try:
        r = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=15)
        return [{"id": it.get("id", ""), "label": it.get("label", ""),
                 "description": it.get("description", "")}
                for it in r.json().get("search", [])]
    except Exception:
        return []

gold_map = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
labels = {}   # (kind, label_lower) -> label
for pairs in gold_map.values():
    for kind, label, _ in pairs:
        labels[(kind, label.lower())] = label

cache = {}
if os.path.exists("candidates.json"):
    cache = json.load(open("candidates.json"))
    print(f"Resuming — {len(cache)} labels cached")

todo = [(k, l) for (k, ll), l in labels.items() if f"{k}|{l}" not in cache]
print(f"Fetching candidates for {len(todo)} of {len(labels)} unique labels")

for n, (kind, label) in enumerate(todo):
    cache[f"{kind}|{label}"] = search(label, kind == "property")
    if (n + 1) % 50 == 0:
        json.dump(cache, open("candidates.json", "w"))
        print(f"  {n+1}/{len(todo)}")

json.dump(cache, open("candidates.json", "w"))

# GLiNKER entity dictionary: union of all ENTITY candidates, deduplicated
seen, count = set(), 0
with open("entities.jsonl", "w") as f:
    for key, cands in cache.items():
        if not key.startswith("entity|"):
            continue
        for c in cands:
            if c["id"] and c["id"] not in seen:
                seen.add(c["id"])
                f.write(json.dumps({
                    "entity_id": c["id"],
                    "label": c["label"],
                    "description": c["description"] or c["label"],
                    "entity_type": "entity",
                }) + "\n")
                count += 1

print(f"Done. candidates.json: {len(cache)} labels; entities.jsonl: {count} unique entities")
