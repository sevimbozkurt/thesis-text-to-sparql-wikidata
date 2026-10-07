"""elq_library_coverage.py — How many reference entities exist in ELQ's entity
catalogue at all.
"""

import json, sys, time
import requests

gold_off = json.load(open("data/gold_links_official.json"))
gold_w = json.load(open("data/gold_links.json"))
E_off = {g for ps in gold_off.values() for k, l, g in ps if k == "entity"}
E_w = {g for ps in gold_w.values() for k, l, g in ps if k == "entity"}

H = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
q2t, failed = {}, 0
ents = sorted(E_off)
for i in range(0, len(ents), 50):
    chunk = ents[i:i + 50]
    for attempt in range(4):
        try:
            time.sleep(1.0 + attempt * 2)
            r = requests.get("https://www.wikidata.org/w/api.php",
                             params={"action": "wbgetentities", "ids": "|".join(chunk),
                                     "props": "sitelinks", "sitefilter": "enwiki", "format": "json"},
                             headers=H, timeout=30)
            r.raise_for_status()
            for q, e in r.json()["entities"].items():
                q2t[q] = e.get("sitelinks", {}).get("enwiki", {}).get("title", "")
            break
        except Exception:
            if attempt == 3:
                failed += len(chunk)
titles = {t for t in q2t.values() if t}

want = E_off | E_w
seen_q, seen_t, n, noid = set(), set(), 0, 0
for line in sys.stdin.buffer:
    n += 1
    i = line.rfind(b'"title": ')
    if i < 0:
        continue
    try:
        d = json.loads(b"{" + line[i:])
    except Exception:
        continue
    q = d.get("kb_idx")
    if not q:
        noid += 1
    elif q in want:
        seen_q.add(q)
    if d.get("title") in titles:
        seen_t.add(d.get("title"))

out = [f"ELQ entity catalogue (entity.jsonl): {n} entries, {noid} without a Wikidata ID", ""]
for name, E in [("official split", E_off), ("working split", E_w)]:
    c = len(E & seen_q)
    out.append(f"{name}: {c} of {len(E)} distinct reference entities in the catalogue by ID = {c / len(E) * 100:.1f}%")
ct = sum(1 for q in E_off if q2t.get(q) in seen_t)
nosl = sum(1 for q in E_off if q2t.get(q) == "")
out += ["",
        f"official split, cross-check by current English Wikipedia title: {ct} = {ct / len(E_off) * 100:.1f}%",
        f"official split, without an English Wikipedia page: {nosl} = {nosl / len(E_off) * 100:.1f}%",
        f"sitelink lookups that failed after retries: {failed}"]
open("results_tables/RESULT_elq_coverage.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
