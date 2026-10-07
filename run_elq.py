"""run_elq.py — Run ELQ over the thesis evaluation questions ON THE SERVER, and
emit predictions in the thesis's standard linker format.

USAGE (conda env with ELQ installed, run from the root of a BLINK checkout):
  export CUDA_VISIBLE_DEVICES=1
  python run_elq.py --split working
  python run_elq.py --split official
Then scp the preds_*.jsonl back and score locally with eval_linker.py /
eval_linker_official.py.
"""

import argparse, collections, json, os, re, sys, time

MODELS = "models/"
WIKI2QID = "data/wiki2qid.json"
BATCH = 32          # questions per ELQ batch
QID_BATCH = 50      # titles per Wikidata API call

def load(p, d):
    return json.load(open(p)) if os.path.exists(p) else d

def save(p, o):
    json.dump(o, open(p, "w"))

# ── gold + questions per split ─────────────────────────────────
def load_split(split):
    if split == "working":
        gold_raw = json.load(open("data/gold_links.json"))
        test = json.load(open("data/test.json"))
        gold = {str(k): v for k, v in gold_raw.items()}
        qs = {str(i): r["instruction"] for i, r in enumerate(test)}
        out = "outputs/preds_elq.jsonl"
    else:
        gold = json.load(open("data/gold_links_official.json"))
        rows = json.load(open("data/official_test.json"))
        qs = {str(r["id"]): r["instruction"] for r in rows}
        out = "outputs/preds_elq_official.jsonl"
    return gold, qs, out

# ── wikipedia-id -> title (from ELQ's own catalogue) ───────────
def catalogue_titles(needed_ids):
    """entity.jsonl lines carry idx implicitly by order? No — ELQ pred_triples
    give the row index into the catalogue. We read the catalogue once and keep
    only the rows we need (ids are line indices)."""
    titles = {}
    needed = set(needed_ids)
    if not needed:
        return titles
    with open(MODELS + "entity.jsonl") as f:
        for i, line in enumerate(f):
            if i in needed:
                try:
                    e = json.loads(line)
                    titles[i] = e.get("title") or e.get("entity") or ""
                except Exception:
                    titles[i] = ""
                needed.discard(i)
                if not needed:
                    break
    return titles

# ── title -> QID via Wikidata sitelinks ────────────────────────
def titles_to_qids(titles):
    import requests
    cache = load(WIKI2QID, {})
    todo = sorted({t for t in titles if t and t not in cache})
    print(f"resolving {len(todo)} titles to QIDs (cached: {len(cache)})")
    H = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
    for i in range(0, len(todo), QID_BATCH):
        chunk = todo[i:i + QID_BATCH]
        params = {"action": "wbgetentities", "sites": "enwiki",
                  "titles": "|".join(chunk), "props": "info",
                  "format": "json", "redirects": "yes"}
        for attempt in range(5):
            time.sleep(1.0 * (attempt + 1))
            try:
                r = requests.get("https://www.wikidata.org/w/api.php",
                                 params=params, headers=H, timeout=30)
                if r.status_code == 200:
                    ents = r.json().get("entities", {})
                    # map back: each entity has a 'title'? wbgetentities keyed by QID;
                    # use the 'sitelinks' absence — instead match via normalised title
                    got = {}
                    for qid, e in ents.items():
                        if qid.startswith("Q"):
                            # 'title' of the request isn't echoed; fetch sitelink title
                            pass
                    # simpler: re-request with props=sitelinks to recover mapping
                    params2 = dict(params); params2["props"] = "sitelinks"
                    r2 = requests.get("https://www.wikidata.org/w/api.php",
                                      params=params2, headers=H, timeout=30)
                    ents2 = r2.json().get("entities", {}) if r2.status_code == 200 else {}
                    for qid, e in ents2.items():
                        if not qid.startswith("Q"):
                            continue
                        t = e.get("sitelinks", {}).get("enwiki", {}).get("title", "")
                        if t:
                            got[t] = qid
                    for t in chunk:
                        cache[t] = got.get(t) or got.get(t.replace("_", " ")) or ""
                    break
                print(f"  HTTP {r.status_code} on chunk {i}")
            except Exception as e:
                print(f"  {type(e).__name__} on chunk {i}")
        if (i // QID_BATCH) % 5 == 4:
            save(WIKI2QID, cache)
            print(f"  {i + len(chunk)}/{len(todo)}")
    save(WIKI2QID, cache)
    return cache

# ── mention matching (same protocol as ReFinED) ────────────────
def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()

def score_match(label, mention):
    L, M = norm(label), norm(mention)
    if not L or not M:
        return 0.0
    if L == M:
        return 1.0
    if L in M or M in L:
        return 0.8
    lt, mt = set(L.split()), set(M.split())
    inter = len(lt & mt)
    return 0.6 * inter / max(len(lt), len(mt)) if inter else 0.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["working", "official"], default="working")
    ap.add_argument("--threshold", type=float, default=-4.5)
    a = ap.parse_args()

    gold, qs, outfile = load_split(a.split)
    rows = [(rid, qs[rid]) for rid in gold if rid in qs]
    print(f"{a.split} split: {len(rows)} rows with ground truth")

    # ── ELQ ───────────────────────────────────────────────────
    import elq.main_dense as main_dense
    config = {"interactive": False,
              "biencoder_model": MODELS + "elq_wiki_large.bin",
              "biencoder_config": MODELS + "elq_large_params.txt",
              "cand_token_ids_path": MODELS + "entity_token_ids_128.t7",
              "entity_catalogue": MODELS + "entity.jsonl",
              "entity_encoding": MODELS + "all_entities_large.t7",
              "output_path": "output/",
              "faiss_index": "hnsw", "index_path": MODELS + "faiss_hnsw_index.pkl",
              "num_cand_mentions": 10, "num_cand_entities": 10,
              "threshold_type": "joint", "threshold": a.threshold}
    args = argparse.Namespace(**config)
    print("loading ELQ models (several minutes)...")
    models = main_dense.load_models(args, logger=None)
    print("models loaded; running inference")

    predictions = {}     # rid -> list[(mention_text, wiki_row_id)]
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        data = [{"id": n, "text": q} for n, (_, q) in enumerate(chunk)]
        out = main_dense.run(args, None, *models, test_data=data)
        for n, res in enumerate(out):
            rid = chunk[n][0]
            ments = []
            triples = res.get("pred_triples", [])
            strings = res.get("pred_tuples_string", [])
            for k, trip in enumerate(triples):
                wiki_id = int(trip[0])
                mention = strings[k][1] if k < len(strings) else ""
                ments.append((mention, wiki_id))
            predictions[rid] = ments
        print(f"  {min(i + BATCH, len(rows))}/{len(rows)}")

    # ── map wiki ids -> titles -> QIDs ────────────────────────
    all_ids = {wid for ms in predictions.values() for _, wid in ms}
    print(f"{len(all_ids)} distinct predicted wiki entities; reading catalogue")
    titles = catalogue_titles(all_ids)
    t2q = titles_to_qids(set(titles.values()))
    wid2qid = {wid: t2q.get(t, "") for wid, t in titles.items()}
    resolved = sum(1 for v in wid2qid.values() if v)
    print(f"wiki->QID resolved for {resolved}/{len(wid2qid)} entities")

    # ── 2019-snapshot coverage of gold entities ───────────────
    qid_set = set(v for v in t2q.values() if v)
    gold_ents = {g for ps in gold.values() for k, l, g in ps if k == "entity"}
    # coverage against the full catalogue would need all 5.9M titles resolved;
    # approximate instead: how many gold QIDs were EVER predicted is not
    # coverage. Proper coverage = does the gold entity exist in the 2019 lib.
    # We measure it directly: resolve gold QIDs' enwiki titles and check
    # membership in the catalogue title set (built lazily).
    print("measuring 2019-library coverage of gold entities...")
    import requests
    H = {"User-Agent": "ThesisKGQA/2.0 (master thesis research)"}
    q2title = {}
    gl = sorted(gold_ents)
    for i in range(0, len(gl), QID_BATCH):
        chunk = gl[i:i + QID_BATCH]
        try:
            time.sleep(1.0)
            r = requests.get("https://www.wikidata.org/w/api.php",
                             params={"action": "wbgetentities", "ids": "|".join(chunk),
                                     "props": "sitelinks", "format": "json"},
                             headers=H, timeout=30)
            for qid, e in r.json().get("entities", {}).items():
                q2title[qid] = e.get("sitelinks", {}).get("enwiki", {}).get("title", "")
        except Exception:
            pass
    cat_titles = set()
    with open(MODELS + "entity.jsonl") as f:
        for line in f:
            try:
                e = json.loads(line)
                cat_titles.add(e.get("title") or e.get("entity") or "")
            except Exception:
                pass
    covered = sum(1 for q in gold_ents if q2title.get(q) and q2title[q] in cat_titles)
    no_sitelink = sum(1 for q in gold_ents if not q2title.get(q))
    print(f"gold entities: {len(gold_ents)} | in ELQ 2019 library: {covered} "
          f"({covered/len(gold_ents)*100:.1f}%) | without enwiki sitelink: "
          f"{no_sitelink} ({no_sitelink/len(gold_ents)*100:.1f}%)")

    # ── write predictions in standard format ──────────────────
    written = 0
    set_c = set_p = set_g = 0
    with open(outfile, "w") as fh:
        for rid, pairs in gold.items():
            ent = [(k, l, g) for k, l, g in pairs if k == "entity"]
            if not ent:
                continue
            preds = [(m, wid2qid.get(wid, "")) for m, wid in predictions.get(rid, [])]
            used = set()
            for kind, label, gid in ent:
                best, bs, bj = "", 0.0, None
                for j, (mt, qid) in enumerate(preds):
                    if j in used or not qid:
                        continue
                    v = score_match(label, mt)
                    if v > bs:
                        best, bs, bj = qid, v, j
                if bs >= 0.5 and bj is not None:
                    used.add(bj)
                else:
                    best = ""
                fh.write(json.dumps({"index": rid, "kind": kind, "label": label,
                                     "pred_id": best}) + "\n")
                written += 1
            g = {x for _, _, x in ent}
            p = {q for _, q in preds if q}
            set_g += len(g); set_p += len(p); set_c += len(g & p)
    P = set_c/set_p*100 if set_p else 0
    R = set_c/set_g*100 if set_g else 0
    F = 2*P*R/(P+R) if P+R else 0
    print(f"\nwrote {written} predictions -> {outfile}")
    print(f"SET-BASED (secondary): P {P:.1f} R {R:.1f} F1 {F:.1f}")
    print(f"scp {outfile} (and {WIKI2QID}) back to the laptop and score with "
          f"eval_linker{'_official' if a.split=='official' else ''}.py")

if __name__ == "__main__":
    main()
