"""expand_candidates.py — Experiment B, stage 1 (FREE: no LLM calls).

Usage:  python3 expand_candidates.py          (~30-40 min, rate-limited)
"""

import json, time, os, collections
import requests

API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.0
TOP_K = 20
FT_K  = 10
OUT   = "candidates_expanded.json"

def wbsearch(label, limit=TOP_K):
    params = {"action": "wbsearchentities", "search": label, "language": "en",
              "format": "json", "limit": limit, "type": "item"}
    for attempt in range(4):
        time.sleep(DELAY * (attempt + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return [{"id": h.get("id",""), "label": h.get("label",""),
                         "description": h.get("description",""), "src": "wbsearch"}
                        for h in r.json().get("search", [])]
            print(f"  HTTP {r.status_code}: {label!r}")
        except Exception as e:
            print(f"  {type(e).__name__}: {label!r}")
    return []

def fulltext(label, limit=FT_K):
    params = {"action": "query", "list": "search", "srsearch": label,
              "srnamespace": 0, "srlimit": limit, "format": "json"}
    for attempt in range(4):
        time.sleep(DELAY * (attempt + 1))
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                out = []
                for h in r.json().get("query", {}).get("search", []):
                    qid = h.get("title", "")
                    if qid.startswith("Q"):
                        out.append({"id": qid, "label": h.get("title", ""),
                                    "description": "", "src": "fulltext"})
                return out
            print(f"  HTTP {r.status_code} (ft): {label!r}")
        except Exception as e:
            print(f"  {type(e).__name__} (ft): {label!r}")
    return []

def main():
    gold = {int(k): v for k, v in json.load(open("gold_links.json")).items()}
    test = json.load(open("test.json"))
    cx = {i: test[i]["complexity"] for i in gold}

    # unique entity labels + the gold ids they must cover
    label_gold = collections.defaultdict(set)   # label -> {gold ids}
    mentions = []                               # (row, label, gid)
    for i, pairs in gold.items():
        for kind, label, gid in pairs:
            if kind != "entity":
                continue
            label_gold[label].add(gid)
            mentions.append((i, label, gid))
    print(f"{len(mentions)} entity mentions, {len(label_gold)} unique labels")

    base = json.load(open("candidates.json"))   # existing top-7 pools
    pool = json.load(open(OUT)) if os.path.exists(OUT) else {}

    todo = [l for l in label_gold if f"entity|{l}" not in pool]
    print(f"expanding {len(todo)} labels (resume-safe)")
    for n, label in enumerate(todo):
        cands = wbsearch(label)
        have = {c["id"] for c in cands}
        # full-text fallback only when gold still missing (cheap + targeted)
        if not (label_gold[label] & have):
            for c in fulltext(label):
                if c["id"] not in have:
                    cands.append(c); have.add(c["id"])
        pool[f"entity|{label}"] = cands
        if (n + 1) % 25 == 0:
            json.dump(pool, open(OUT, "w"))
            print(f"  {n+1}/{len(todo)}")
    json.dump(pool, open(OUT, "w"))

    # ── ceilings ──────────────────────────────────────────────
    def ceiling(get_pool):
        tot = hit = 0
        per = collections.defaultdict(lambda: [0, 0])
        for i, label, gid in mentions:
            tot += 1; per[cx[i]][1] += 1
            if gid in get_pool(label):
                hit += 1; per[cx[i]][0] += 1
        return hit, tot, per

    p7  = lambda l: {c["id"] for c in base.get(f"entity|{l}", [])}
    p20 = lambda l: {c["id"] for c in pool.get(f"entity|{l}", []) if c["src"] == "wbsearch"}
    pall= lambda l: {c["id"] for c in pool.get(f"entity|{l}", [])}

    lines = [f"CEILING REPORT — {len(mentions)} entity mentions", ""]
    for name, fn in [("top-7 (baseline)", p7), ("top-20 (E1)", p20),
                     ("top-20 + fulltext (E1+E2)", pall)]:
        hit, tot, per = ceiling(fn)
        row = " | ".join(f"{c} {per[c][0]}/{per[c][1]}"
                         for c in ["simple", "medium", "complex"])
        lines.append(f"{name:28s} {hit}/{tot} = {hit/tot*100:5.1f}%   ({row})")
    lines.append("")
    sizes = [len(v) for v in pool.values()]
    lines.append(f"mean pool size: {sum(sizes)/len(sizes):.1f} candidates "
                 f"(baseline was <=7)")
    report = "\n".join(lines)
    print("\n" + report)
    open("ceiling_report.txt", "w").write(report + "\n")
    print("\nwritten ceiling_report.txt — paste the report before running stage 2")

if __name__ == "__main__":
    main()
