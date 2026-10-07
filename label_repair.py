"""

Usage: python3 label_repair.py            (~8 minutes for 270 labels)
Writes results_tables/label_repair.csv
"""
import json, re, csv, time, sys, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEAD = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.0          # fast bursts make the API return empty lists silently
POOL = "data/pool_qwen-qwen2-5-14b-instruct_official.json"

def search(label, is_property, k=7):
    time.sleep(DELAY)
    p = {"action": "wbsearchentities", "search": label, "language": "en",
         "format": "json", "limit": k, "type": "property" if is_property else "item"}
    for attempt in (1, 2):                       # one retry: empty may mean throttled
        try:
            r = requests.get(API, params=p, headers=HEAD, timeout=15)
            hits = r.json().get("search", [])
            if hits or attempt == 2:
                return [{"id": h.get("id", ""), "label": h.get("label", "")} for h in hits]
            time.sleep(3.0)
        except Exception:
            time.sleep(3.0)
    return []

# --- the normalisation ladder; first rule that changes the string is applied ---
def split_camel(s):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s).replace("  ", " ").strip().lower()

RULES = [
    ("bare identifier",  lambda s: s if re.fullmatch(r'[PQ]\d+', s) else None),
    ("split camelCase",  lambda s: split_camel(s) if re.search(r'[a-z][A-Z]', s) and ' ' not in s else None),
    ("unsnake",          lambda s: s.replace("_", " ").lower() if "_" in s else None),
    ("drop leading is/has", lambda s: re.sub(r'^(is|has)\s+', '', s) if re.match(r'^(is|has)\s+', s) else None),
    ("strip parenthetical", lambda s: re.sub(r'\s*\([^)]*\)\s*$', '', s).strip() if s.endswith(")") else None),
    ("singularise (s)",  lambda s: s[:-1] if s.endswith("s") and not s.endswith("ss") else None),
]

def classify(label):
    if re.fullmatch(r"[PQ]\d+", label):                       return "bare identifier"
    if re.search(r"[a-z][A-Z]", label) and " " not in label:  return "camelCase / RDF style"
    if "_" in label:                                          return "snake_case"
    if len(label.split()) >= 5:                               return "verbose paraphrase"
    if re.search(r"\b(ID|URL|URI|identifier)\b", label):      return "qualified / suffixed name"
    return "near-miss wording"

pool = json.load(open(POOL))
unfindable = [k for k, v in pool.items() if not v]
print(f"{len(unfindable)} unfindable labels from {POOL}")
print(f"re-querying with a normalisation ladder at {DELAY}s/request "
      f"(~{len(unfindable)*DELAY*1.2/60:.0f} min)\n")

rows, fixed_by = [], collections.Counter()
by_cat = collections.defaultdict(lambda: [0, 0])
for n, key in enumerate(unfindable, 1):
    kind, _, label = key.partition("|")
    cat = classify(label)
    by_cat[cat][1] += 1
    repaired, rule, cands = None, None, []
    for rname, fn in RULES:
        cand = fn(label)
        if not cand or cand == label:
            continue
        if rname == "bare identifier":            # already an ID; no search needed
            repaired, rule, cands = cand, rname, [{"id": cand, "label": "(identifier)"}]
            break
        hits = search(cand, kind == "property")
        if hits:
            repaired, rule, cands = cand, rname, hits
            break
    if repaired:
        by_cat[cat][0] += 1
        fixed_by[rule] += 1
    rows.append(dict(kind=kind, original=label, category=cat,
                     repaired=repaired or "", rule=rule or "",
                     top_candidate=(cands[0]["id"] if cands else ""),
                     top_label=(cands[0]["label"] if cands else "")))
    if n % 30 == 0:
        print(f"  {n}/{len(unfindable)}  repaired so far: {sum(v[0] for v in by_cat.values())}")

tot_fixed = sum(v[0] for v in by_cat.values())
print(f"\n{'category':26s} {'unfindable':>11s} {'repaired':>9s} {'rate':>7s}")
for c, (f, t) in sorted(by_cat.items(), key=lambda kv: -kv[1][1]):
    print(f"{c:26s} {t:11d} {f:9d} {f/t*100:6.1f}%")
print(f"{'TOTAL':26s} {len(unfindable):11d} {tot_fixed:9d} {tot_fixed/len(unfindable)*100:6.1f}%")

print(f"\nrepairs by rule:")
for r, n in fixed_by.most_common():
    print(f"  {r:24s} {n:4d}")

orig_rate = len(unfindable) / len(pool) * 100
new_rate = (len(unfindable) - tot_fixed) / len(pool) * 100
print(f"""
EFFECT ON THE OPEN MODEL'S LABEL FAILURE RATE
  before repair {orig_rate:.1f}%  ->  after repair {new_rate:.1f}%   (frontier: 3.3%)

""")
with open("results_tables/label_repair.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("written: results_tables/label_repair.csv")
