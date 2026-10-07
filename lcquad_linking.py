"""

Usage:
  python3 lcquad_linking.py sample      # draw N and extract gold identifiers
  python3 lcquad_linking.py labels      # resolve identifiers -> labels (Wikidata API)
  python3 lcquad_linking.py candidates  # retrieve top-7 per label (Wikidata API)
  python3 lcquad_linking.py package     # write the file the GPU stage consumes
  python3 lcquad_linking.py score       # after disambiguation returns
"""
import json, re, sys, time, random, os, collections
import requests

SRC   = "external/lcquad2/test.json"
N     = 150
SEED  = 23
K     = 7
API   = "https://www.wikidata.org/w/api.php"
HEAD  = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
DELAY = 1.2

SAMPLE = "data/lcquad_sample.json"
LABELS = "data/lcquad_labels.json"
POOL   = "data/lcquad_pool.json"
GENF   = "outputs/lcquad_generated.json"

QID = re.compile(r"\bwd:(Q\d+)\b")
PID = re.compile(r"\b(?:wdt|p|ps|pq|psv|pqv|ps):(P\d+)\b")


def question_of(r):
    """LC-QuAD 2.0's `question` is sometimes a slot template; prefer a natural one."""
    q = (r.get("question") or "").strip()
    if q and "{" not in q and len(q) > 8:
        return q
    p = (r.get("paraphrased_question") or "").strip()
    return p if p and "{" not in p else ""


def sample():
    rows = json.load(open(SRC))
    ok = []
    for r in rows:
        q, s = question_of(r), (r.get("sparql_wikidata") or "")
        if not q or not s.strip():
            continue
        ents, props = sorted(set(QID.findall(s))), sorted(set(PID.findall(s)))
        if not ents and not props:
            continue
        ok.append({"uid": r.get("uid"), "question": q, "sparql": " ".join(s.split()),
                   "gold_entities": ents, "gold_properties": props})
    rng = random.Random(SEED)
    sel = rng.sample(ok, min(N, len(ok)))
    json.dump(sel, open(SAMPLE, "w"), indent=1)
    ne = sum(len(r["gold_entities"]) for r in sel)
    np_ = sum(len(r["gold_properties"]) for r in sel)
    print(f"{len(ok)} usable rows in LC-QuAD 2.0 test; sampled {len(sel)} (seed {SEED})")
    print(f"gold mentions: {ne} entities, {np_} properties")
    print(f"written: {SAMPLE}")


def _get(params):
    for attempt in (1, 2, 3):
        try:
            time.sleep(DELAY)
            r = requests.get(API, params=params, headers=HEAD, timeout=25)
            if r.status_code == 429:
                time.sleep(5); continue
            return r.json()
        except Exception:
            time.sleep(3)
    return {}


def labels():
    sel = json.load(open(SAMPLE))
    have = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    ids = sorted({i for r in sel for i in r["gold_entities"] + r["gold_properties"]}
                 - set(have))
    print(f"{len(ids)} identifiers to resolve")
    for n in range(0, len(ids), 50):
        chunk = ids[n:n + 50]
        d = _get({"action": "wbgetentities", "ids": "|".join(chunk),
                  "props": "labels", "languages": "en", "format": "json"})
        for k, v in (d.get("entities") or {}).items():
            lab = (v.get("labels") or {}).get("en", {}).get("value")
            if lab:
                have[k] = lab
        json.dump(have, open(LABELS, "w"), indent=1)
        print(f"  {min(n+50,len(ids))}/{len(ids)} resolved {len(have)}")
    miss = [i for i in ids if i not in have]
    print(f"resolved {len(have)} | unresolved {len(miss)} {miss[:6]}")


def candidates():
    sel = json.load(open(SAMPLE)); lab = json.load(open(LABELS))
    pool = json.load(open(POOL)) if os.path.exists(POOL) else {}
    need = []
    for r in sel:
        for i in r["gold_entities"]:
            if i in lab: need.append(("entity", lab[i]))
        for i in r["gold_properties"]:
            if i in lab: need.append(("property", lab[i]))
    need = sorted({f"{k}|{l}" for k, l in need} - set(pool))
    print(f"{len(need)} distinct labels to look up (~{len(need)*DELAY/60:.0f} min)")
    for n, key in enumerate(need, 1):
        kind, _, label = key.partition("|")
        d = _get({"action": "wbsearchentities", "search": label, "language": "en",
                  "format": "json", "limit": K,
                  "type": "property" if kind == "property" else "item"})
        pool[key] = [{"id": h.get("id", ""), "label": h.get("label", ""),
                      "description": h.get("description", "")}
                     for h in d.get("search", [])]
        if n % 25 == 0:
            json.dump(pool, open(POOL, "w"), indent=1)
            print(f"  {n}/{len(need)}")
    json.dump(pool, open(POOL, "w"), indent=1)
    empty = sum(1 for v in pool.values() if not v)
    print(f"pool: {len(pool)} labels | empty: {empty}")


def package():
    """Write a labelled-query file in the shape disamb_any.py already consumes,
    so the GPU stage is the same code the thesis used rather than a new one."""
    sel = json.load(open(SAMPLE)); lab = json.load(open(LABELS))
    out, qs = {}, {}
    for i, r in enumerate(sel):
        parts = []
        for e in r["gold_entities"]:
            if e in lab: parts.append(f"wd:[entity:{lab[e]}]")
        for p in r["gold_properties"]:
            if p in lab: parts.append(f"wdt:[property:{lab[p]}]")
        if parts:
            out[str(i)] = "SELECT ?x WHERE { " + " ".join(parts) + " }"
            qs[str(i)] = r["question"]
    json.dump(out, open(GENF, "w"), indent=1)
    json.dump(qs, open("data/lcquad_questions.json", "w"), indent=1)
    print(f"written: {GENF} ({len(out)} rows) and data/lcquad_questions.json")


def score():
    linked = json.load(open("outputs/linked_lcquad.json"))
    sel = json.load(open(SAMPLE)); lab = json.load(open(LABELS))
    inv = {v: k for k, v in lab.items()}
    te = tp = ce = cp = 0
    for i, r in enumerate(sel):
        row = linked.get(str(i))
        if not row: continue
        got = set(re.findall(r"\b(Q\d+|P\d+)\b", row.get("linked_query", "")))
        for e in r["gold_entities"]:
            if e in lab:
                te += 1; ce += (e in got)
        for p in r["gold_properties"]:
            if p in lab:
                tp += 1; cp += (p in got)
    print("=" * 66)
    print("R3 — LINKING REPLICATION ON LC-QuAD 2.0 (gold-label condition)")
    print("=" * 66)
    print(f"  entity   {ce}/{te} = {100*ce/max(te,1):.1f} %")
    print(f"  property {cp}/{tp} = {100*cp/max(tp,1):.1f} %")
    print(f"\n  Instruct-to-SPARQL, same backbone: 94.9 entity F1")
    print(f"  Read as an upper bound: labels here come from Wikidata rather than")
    print(f"  from a human-written mention, so they are by construction findable.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"sample": sample, "labels": labels, "candidates": candidates,
     "package": package, "score": score}.get(
        cmd, lambda: sys.exit("usage: lcquad_linking.py sample|labels|candidates|"
                              "package|score"))()
