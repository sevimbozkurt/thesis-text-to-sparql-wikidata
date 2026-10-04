"""rerun_e2e_candidates.py — Stage 1 of the end-to-end re-run (FREE).

Usage:  python3 rerun_e2e_candidates.py        (resume-safe; 1-2 h)
"""

import csv, json, re, time, os, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2
K = 7
OUT = "e2e_candidates_clean.json"
SRC = "qlever/results_e2e_regen.csv"

def search(label, is_prop, limit=K):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": limit,
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

def parse_labels(q):
    ents = re.findall(r'\[entity:([^\]]+)\]', q or "")
    props = re.findall(r'\[property:([^\]]+)\]', q or "")
    def dedupe(xs):
        seen, out = set(), []
        for x in xs:
            x = x.strip()
            if x and x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
        return out
    return dedupe(ents), dedupe(props)

rows = list(csv.DictReader(open(SRC)))
labels = set()
for r in rows:
    e, p = parse_labels(r["labeled_query"])
    labels |= {("entity", x) for x in e} | {("property", x) for x in p}
print(f"{len(rows)} rows | {len(labels)} unique generated labels")

pool = json.load(open(OUT)) if os.path.exists(OUT) else {}
todo = [(k, l) for k, l in labels if f"{k}|{l}" not in pool]
print(f"fetching {len(todo)} labels")

for n, (kind, label) in enumerate(todo):
    res = search(label, kind == "property")
    if res is not None:
        pool[f"{kind}|{label}"] = res
    if (n + 1) % 25 == 0:
        json.dump(pool, open(OUT, "w"))
        print(f"  {n+1}/{len(todo)}")
json.dump(pool, open(OUT, "w"))

# second pass over empties (throttling signature)
empties = [(k, l) for k, l in labels if not pool.get(f"{k}|{l}")]
print(f"\nsecond pass over {len(empties)} empty pools")
recovered = 0
for n, (kind, label) in enumerate(empties):
    time.sleep(1.5)
    res = search(label, kind == "property")
    if res:
        pool[f"{kind}|{label}"] = res
        recovered += 1
    if (n + 1) % 25 == 0:
        json.dump(pool, open(OUT, "w"))
        print(f"  {n+1}/{len(empties)} recovered {recovered}")
json.dump(pool, open(OUT, "w"))

still_empty = [(k, l) for k, l in labels if not pool.get(f"{k}|{l}")]
sizes = collections.Counter(len(pool.get(f"{k}|{l}", [])) for k, l in labels)
print(f"\nrecovered {recovered}; still empty {len(still_empty)}")
print(f"pool size distribution: {dict(sorted(sizes.items()))}")
print("examples still empty:", [l[:45] for _, l in still_empty[:10]])
print(f"\nwritten {OUT} — next: python3 rerun_e2e_disamb.py submit")
