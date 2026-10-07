"""build_audit_page.py — turn `annotations/gold_audit_worksheet.csv` into something a
person can actually get through.

Usage:
  python3 build_audit_page.py fetch    # execute the 80 queries, cache results
  python3 build_audit_page.py page     # write gold_audit.html
  python3 build_audit_page.py ingest   # merge downloaded answers back into the CSV
"""
import csv, html, json, os, re, sys, time
import requests

import endpoint as EP

WORKSHEET = "annotations/gold_audit_worksheet.csv"
CACHE     = "annotations/gold_audit_results.json"
PAGE      = "gold_audit.html"
LABELS    = "annotations/gold_audit_labels.json"
QID       = __import__("re").compile(r"Q\d+")
PREVIEW_ROWS = 6


def rows():
    """Worksheet rows, with the query text restored from `data/test.json`.

    The worksheet was written through csv and its queries arrived flattened onto
    one line. That is not merely ugly: these queries carry `#` comments, and on
    one line a comment swallows the rest of the query, so 24 of the 80 failed to
    execute with a bare syntax error. The CSV is the record of WHICH rows to
    adjudicate; `data/test.json` is the authority for what the query says."""
    test = json.load(open("data/test.json"))
    out = []
    for r in csv.DictReader(open(WORKSHEET)):
        i = int(r["row"])
        if 0 <= i < len(test):
            r["reference_query"] = test[i]["query"]
        out.append(r)
    return out


def fetch():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [r for r in rows() if r["row"] not in cache]
    print(f"{len(todo)} queries to execute")
    for n, r in enumerate(todo, 1):
        q = r["reference_query"]
        entry = {"cols": [], "rows": [], "n": None, "error": ""}
        try:
            time.sleep(EP.DELAY)
            resp = requests.get(EP.ENDPOINT,
                                params={"query": EP.PREFIXES + EP.strip_label_service(q)},
                                headers=EP.HEADERS, timeout=45)
            if resp.status_code != 200:
                entry["error"] = f"HTTP {resp.status_code}"
            else:
                d = resp.json()
                cols = d.get("head", {}).get("vars", [])
                b = d.get("results", {}).get("bindings", [])
                entry["cols"] = cols
                entry["n"] = len(b)
                def cell(v):
                    # bare Wikidata URIs make the preview unreadable; the point of
                    # the preview is to see the SHAPE of the answer at a glance
                    v = v.replace("http://www.wikidata.org/entity/statement/", "stmt:")
                    v = v.replace("http://www.wikidata.org/entity/", "")
                    v = v.replace("http://www.wikidata.org/prop/direct/", "")
                    return v[:90]
                entry["rows"] = [[cell(bind.get(c, {}).get("value", "")) for c in cols]
                                 for bind in b[:PREVIEW_ROWS]]
        except Exception as e:                          # noqa: BLE001
            entry["error"] = type(e).__name__
        cache[r["row"]] = entry
        json.dump(cache, open(CACHE, "w"), indent=0)
        print(f"  {n:3d}/{len(todo)}  row {r['row']:>5s}  "
              f"{entry['error'] or str(entry['n']) + ' rows'}")
    print(f"cached {len(cache)} results")


def labels():
    """Resolve QIDs in the cached previews to English labels.

    `endpoint.strip_label_service` removes `SERVICE wikibase:label` because this
    endpoint cannot run it. That is fine for scoring, which compares identifiers,
    but it is actively MISLEADING in a preview: a query whose whole output is
    `?itemLabel` shows up with every label blank, and reads as broken when it is
    not. Labels are therefore fetched separately, with rdfs:label, which the
    endpoint does support."""
    cache = json.load(open(CACHE))
    lab = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    ids = {c for v in cache.values() for row in v.get("rows", []) for c in row
           if QID.fullmatch(c)} - set(lab)
    ids = sorted(ids)
    print(f"{len(ids)} identifiers to label")
    for i in range(0, len(ids), 80):
        chunk = ids[i:i + 80]
        vals = " ".join(f"wd:{x}" for x in chunk)
        time.sleep(EP.DELAY)
        try:
            r = requests.get(EP.ENDPOINT, headers=EP.HEADERS, timeout=45, params={"query":
                EP.PREFIXES + f"""SELECT ?e ?l WHERE {{ VALUES ?e {{ {vals} }}
                  ?e rdfs:label ?l . FILTER(LANG(?l) = "en") }}"""})
            for b in r.json().get("results", {}).get("bindings", []):
                lab[b["e"]["value"].rsplit("/", 1)[-1]] = b["l"]["value"][:60]
        except Exception as e:                          # noqa: BLE001
            print(f"    ! {type(e).__name__}")
        for x in chunk:
            lab.setdefault(x, "")
        json.dump(lab, open(LABELS, "w"), indent=0)
        print(f"  {i + len(chunk):5d}/{len(ids)}")
    print(f"{sum(1 for x in lab.values() if x)} of {len(lab)} resolved")


def page():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    lab = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    data = []
    for r in rows():
        c = cache.get(r["row"], {})
        data.append({
            "row": r["row"], "stratum": r["stratum"],
            "question": r["question"], "query": r["reference_query"],
            "screen": r["screen_said"],
            "cols": c.get("cols", []), "res": c.get("rows", []),
            "n": c.get("n"), "err": c.get("error", ""),
            # The first pass stripped SERVICE wikibase:label, so any query whose
            # output is label columns showed up entirely blank and read as
            # broken. Those rows were judged on a misleading preview and are
            # marked for a second look.
            "recheck": bool(
                [i for i, cl in enumerate(c.get("cols", []))
                 if cl.lower().endswith("label")]
                and c.get("rows")
                and all(not c["rows"][j][i].strip()
                        for j in range(len(c["rows"]))
                        for i in [k for k, cl in enumerate(c["cols"])
                                  if cl.lower().endswith("label")])
                and any(lab.get(x) for row in c.get("rows", []) for x in row)),
        })
    open(PAGE, "w", encoding="utf-8").write(
        TEMPLATE.replace("/*DATA*/", json.dumps(data))
                .replace("/*LABELS*/", json.dumps({k: v for k, v in lab.items() if v})))
    print(f"wrote {PAGE} — open it by double-clicking; answers save in the browser")


def ingest():
    """Merge the page's downloaded answers into the worksheet.

    The browser writes to ~/Downloads and renames repeats to
    `gold_audit_answers (1).csv`, so a second round of judgements silently does
    not reach here if only the original filename is checked -- which is exactly
    what happened once. The NEWEST matching file anywhere plausible is used, its
    timestamp is printed, and every verdict that actually CHANGED is listed, so
    "nothing moved" is visible rather than inferred."""
    import glob, time as _t
    cands = (glob.glob("annotations/gold_audit_answers*.csv")
             + glob.glob(os.path.expanduser("~/Downloads/gold_audit_answers*.csv")))
    if not cands:
        sys.exit("no gold_audit_answers*.csv found — click 'Download answers' "
                 "on the page first")
    src = max(cands, key=os.path.getmtime)
    age = (_t.time() - os.path.getmtime(src)) / 60
    print(f"using {src}")
    print(f"  saved {_t.strftime('%d %b %H:%M', _t.localtime(os.path.getmtime(src)))}"
          f"  ({age:.0f} minutes ago)")
    if age > 120:
        print("  WARNING: that file is over two hours old. If you have just "
              "re-judged rows,\n           click 'Download answers' again — this "
              "is a stale export.")

    ans = {r["row"]: r for r in csv.DictReader(open(src))}
    out, n, changed = [], 0, []
    for r in rows():
        a = ans.get(r["row"])
        if a and a.get("verdict", "").strip():
            before = r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower()
            after = a["verdict"].strip().lower()
            if before and before != after:
                changed.append((r["row"], before, after))
            r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"] = a["verdict"].strip()
            r["your_note"] = a.get("note", "").strip()
            n += 1
        out.append(r)
    with open(WORKSHEET, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    notes = sum(1 for r in out if r["your_note"].strip())
    print(f"\nmerged {n} judgements, {notes} with a written reason")
    if changed:
        print(f"{len(changed)} verdict(s) CHANGED since the last merge:")
        for rid, b, a2 in changed:
            print(f"   row {rid:>5s}  {b} -> {a2}")
    else:
        print("NO verdict changed. If you just re-judged rows in the browser, the "
              "export\nabove is the old one — click 'Download answers' again and "
              "re-run this.")
    print("\nnow run:  python3 gold_query_screen.py estimate")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Gold-query adjudication</title>
<style>
 :root{--bg:#fbfaf8;--fg:#1c1a17;--mut:#6b6560;--line:#e0dcd6;--card:#fff;
       --yes:#2f6b3d;--no:#8c3320;--flag:#8a6d1f}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
 header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
        padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;z-index:5}
 h1{font-size:15px;margin:0;font-weight:600}
 .prog{color:var(--mut);font-size:13px}
 button{font:inherit;padding:6px 12px;border:1px solid var(--line);background:var(--card);
        border-radius:6px;cursor:pointer}
 button:hover{border-color:var(--mut)}
 main{max-width:900px;margin:0 auto;padding:20px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
       padding:18px 20px;margin-bottom:18px}
 .card.done{opacity:.5}
 .meta{font-size:12px;color:var(--mut);display:flex;gap:12px;margin-bottom:8px}
 .flag{color:var(--flag);font-weight:600}
 .rc{color:#7a2f8a;font-weight:600}
 .q{font-size:17px;font-weight:600;margin:0 0 12px}
 .screen{font-size:13px;color:var(--flag);margin:-6px 0 12px}
 table{border-collapse:collapse;font-size:12px;width:100%;display:block;overflow-x:auto}
 th,td{border:1px solid var(--line);padding:3px 7px;text-align:left;
       white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}
 th{background:#f4f1ec}
 .n{font-size:12px;color:var(--mut);margin:8px 0 4px}
 .warn{color:var(--flag);background:#fdf8e8;border:1px solid #ece0bd;border-radius:6px;padding:8px 10px;line-height:1.5}
 pre{background:#f4f1ec;border:1px solid var(--line);border-radius:6px;padding:10px;
     font-size:11.5px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;margin:10px 0 0}
 details summary{cursor:pointer;font-size:13px;color:var(--mut);margin-top:10px}
 .ans{margin-top:14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .ans button{padding:7px 18px;font-weight:600}
 .ans button.yes.on{background:var(--yes);color:#fff;border-color:var(--yes)}
 .ans button.no.on{background:var(--no);color:#fff;border-color:var(--no)}
 .ans input{flex:1;min-width:220px;padding:6px 9px;border:1px solid var(--line);
            border-radius:6px;font:inherit}
</style></head><body>
<header>
  <h1>Does the reference query answer its question?</h1>
  <span class="prog" id="prog"></span>
  <button id="hide">Hide answered</button>
  <button id="only">Only second-look rows</button>
  <button id="dl">Download answers</button>
</header>
<main id="main"></main>
<script>
const DATA = /*DATA*/;
const LAB = /*LABELS*/;
const KEY = "gold_audit_v1";
let ans = {}; try{ ans = JSON.parse(localStorage.getItem(KEY)||"{}"); }catch(e){}
const save = () => { try{ localStorage.setItem(KEY, JSON.stringify(ans)); }catch(e){} };
// A blank-label preview could only have pushed a judgement towards "no", so a
// "yes" needs no revisiting: only the rejections are contaminated.
const recheck = d => d.recheck && (ans[d.row]||{}).verdict === "no";
const esc = s => (s||"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function prog(){
  const n = Object.values(ans).filter(a=>a && a.verdict).length;
  const r = DATA.filter(recheck).length;
  document.getElementById("prog").textContent =
    n + " of " + DATA.length + " judged" + (r ? " · " + r + " need a second look" : "");
}
function render(){
  document.getElementById("main").innerHTML = DATA.map(d => {
    const a = ans[d.row] || {};
    const tbl = d.err ? '<div class="n warn">Did not execute on this endpoint ('+esc(d.err)
        + ') &mdash; judge it from the SPARQL below. <b>Failing to run is not the same as '
        + 'failing to answer the question</b>: some of these use Blazegraph-only syntax '
        + 'or entities missing from this snapshot, which says nothing about whether the '
        + 'query is a fair answer.</div>'
      : (d.cols.length ? '<div class="n">returns ' + d.n + ' row' + (d.n===1?'':'s')
          + ' · columns: ' + d.cols.map(esc).join(", ") + '</div><table><tr>'
          + d.cols.map(c=>"<th>"+esc(c)+"</th>").join("") + "</tr>"
          + d.res.map(r=>"<tr>"+r.map(v=>"<td>"+esc(LAB[v]?v+" · "+LAB[v]:v)+"</td>").join("")+"</tr>").join("")
          + "</table>" : '<div class="n">returns nothing</div>');
    return '<div class="card'+(a.verdict?' done':'')+'" data-row="'+d.row+'">'
      + '<div class="meta"><span>row '+d.row+'</span><span class="'
      + (d.stratum==="flagged"?"flag":"")+'">'+d.stratum+'</span>'
      + (recheck(d)?'<span class="rc">needs a second look</span>':'')+'</div>'
      + '<p class="q">'+esc(d.question)+'</p>'
      + (d.screen ? '<div class="screen">screen: '+esc(d.screen)+'</div>' : '')
      + (recheck(d)?'<div class="n warn">The first version of this page stripped the '
         + 'label service, so every label below was blank and this query looked '
         + 'broken. The labels are filled in now &mdash; please judge it again.</div>':'')
      + tbl
      + '<details><summary>show the SPARQL</summary><pre>'+esc(d.query)+'</pre></details>'
      + '<div class="ans">'
      +   '<button class="yes'+(a.verdict==="yes"?" on":"")+'" data-v="yes">Yes, it answers it</button>'
      +   '<button class="no'+(a.verdict==="no"?" on":"")+'" data-v="no">No, it does not</button>'
      +   '<input placeholder="note (optional)" value="'+esc(a.note||"")+'">'
      + '</div></div>';
  }).join("");
  prog();
}
document.getElementById("main").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]"); if(!b) return;
  const card = b.closest(".card"), row = card.dataset.row;
  const cur = ans[row] || {};
  cur.verdict = (cur.verdict === b.dataset.v) ? "" : b.dataset.v;
  ans[row] = cur; save();
  // Update only this card. A full re-render of all 80 would reset the scroll
  // position on every single judgement, which over 80 judgements is the
  // difference between a usable tool and an unusable one.
  card.querySelectorAll("button[data-v]").forEach(x =>
    x.classList.toggle("on", cur.verdict === x.dataset.v));
  card.classList.toggle("done", !!cur.verdict);
  if (document.getElementById("hide").dataset.on === "1") card.hidden = !!cur.verdict;
  prog();
});
document.getElementById("main").addEventListener("input", e => {
  if(e.target.tagName !== "INPUT") return;
  const row = e.target.closest(".card").dataset.row;
  ans[row] = ans[row] || {}; ans[row].note = e.target.value; save(); prog();
});
document.getElementById("hide").addEventListener("click", e => {
  const on = e.target.dataset.on === "1";
  e.target.dataset.on = on ? "0" : "1";
  e.target.textContent = on ? "Hide answered" : "Show all";
  document.querySelectorAll(".card.done").forEach(c => c.hidden = !on);
});
document.getElementById("only").addEventListener("click", e => {
  const on = e.target.dataset.on === "1";
  e.target.dataset.on = on ? "0" : "1";
  e.target.textContent = on ? "Only second-look rows" : "Show all rows";
  document.querySelectorAll(".card").forEach(c => {
    const d = DATA.find(x => x.row === c.dataset.row);
    c.hidden = on ? false : !recheck(d);
  });
});
document.getElementById("dl").addEventListener("click", () => {
  const q = s => '"' + String(s||"").replace(/"/g,'""') + '"';
  const csv = "row,verdict,note\n" + DATA.map(d =>
      [d.row, (ans[d.row]||{}).verdict||"", q((ans[d.row]||{}).note||"")].join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
  a.download = "annotations/gold_audit_answers.csv"; a.click();
});
render();
</script></body></html>
"""

# ---------------------------------------------------------------- re-judge ---
# The reference-noise bound rests on a single pass. One way to strengthen it
# without a second person is to measure how stably that person
# applies their own criterion: draw a subset of the rows already judged, present
# them again with the earlier verdicts HIDDEN, and report agreement. This is the
# same intra-annotator check the error taxonomy already reports (kappa 0.62), and
# it is a weaker claim than inter-annotator agreement -- it bounds noise in the
# adjudication, it does not show the criterion means the same to anyone else.
REJUDGE_PAGE = "gold_audit_rejudge.html"
REJUDGE_N = 30
REJUDGE_SEED = 20260914


def _scorable():
    return {rid for rid, vals in json.load(open("data/gold_results.json")).items() if vals}


def _blind_page(pick, key, outfile, heading):
    """Render a blind judging page: no prior verdict, no stratum, no screen flag.

    Every hidden field is hidden for a reason. The prior verdict would anchor a
    second pass; the stratum and the screen's flag would tell the judge what a
    heuristic already suspected, and an agreement figure obtained that way
    measures the heuristic, not the judge."""
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    lab = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    data = []
    for r in pick:
        c = cache.get(r["row"], {})
        data.append({"row": r["row"], "stratum": "",
                     "question": r["question"], "query": r["reference_query"],
                     "screen": "",
                     "cols": c.get("cols", []), "res": c.get("rows", []),
                     "n": c.get("n"), "err": c.get("error", "")})
    out = (TEMPLATE.replace("/*DATA*/", json.dumps(data))
           .replace("/*LABELS*/", json.dumps({k: v for k, v in lab.items() if v}))
           .replace("gold_audit_v1", key)
           .replace("annotations/gold_audit_answers.csv", outfile.replace(".html", "_answers.csv"))
           .replace("Does the reference query answer its question?", heading))
    open(outfile, "w", encoding="utf-8").write(out)
    return len(data)


def _judged_scorable():
    return [r for r in rows()
            if r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower() in ("yes", "no")
            and r["row"] in _scorable()]


def annotator2():
    """The package for a SECOND PERSON. Unlike `rejudge`, this is a genuine
    inter-annotator study: it yields both an agreement figure and an independent
    estimate of the noise rate from someone with no stake in the answer."""
    import random
    pool = _judged_scorable()
    if len(pool) < 10:
        raise SystemExit(f"only {len(pool)} scorable rows judged -- adjudicate first")
    rnd = random.Random(REJUDGE_SEED + 1)
    # Interleave the strata so that stopping early still leaves a balanced set:
    # a partial return is usable, an all-flagged prefix would not be.
    F = [r for r in pool if r["stratum"] == "flagged"]
    U = [r for r in pool if r["stratum"] == "unflagged"]
    rnd.shuffle(F); rnd.shuffle(U)
    pick, i, j = [], 0, 0
    while i < len(F) or j < len(U):
        if j * len(F) <= i * len(U) and j < len(U):
            pick.append(U[j]); j += 1
        elif i < len(F):
            pick.append(F[i]); i += 1
    n = _blind_page(pick, "gold_audit_annot2_v1", "gold_audit_annotator2.html",
                    "Does the reference query answer its question?")
    print(f"wrote gold_audit_annotator2.html -- {n} rows, strata interleaved so")
    print("     stopping early still leaves a balanced sample.")
    print("Send the second judge that file and the instruction sheet. When they send the")
    print("CSV back, put it in this folder and run:")
    print("  python3 build_audit_page.py compare2")


def compare2():
    _agreement("gold_audit_annotator2_answers*.csv",
               "INTER-ANNOTATOR AGREEMENT ON THE ADJUDICATION",
               independent=True)


def rejudge():
    import random
    judged = [r for r in rows()
              if r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower()
              in ("yes", "no")]
    pool = [r for r in judged if r["row"] in _scorable()]
    if len(pool) < 10:
        raise SystemExit(f"only {len(pool)} scorable rows judged -- adjudicate first")
    rnd = random.Random(REJUDGE_SEED)
    F = [r for r in pool if r["stratum"] == "flagged"]
    U = [r for r in pool if r["stratum"] == "unflagged"]
    nf = round(REJUDGE_N * len(F) / len(pool))
    pick = rnd.sample(F, min(nf, len(F))) + rnd.sample(U, min(REJUDGE_N - nf, len(U)))
    rnd.shuffle(pick)

    n = _blind_page(pick, "gold_audit_rejudge_v1", REJUDGE_PAGE,
                    "Second pass &mdash; judge these fresh")
    print(f"wrote {REJUDGE_PAGE} -- {n} rows, your earlier verdicts hidden,")
    print("     and the screen's flag hidden so it cannot anchor you.")
    print("Leave a few days between passes if you can, then:")
    print("  python3 build_audit_page.py compare")


def compare():
    _agreement("gold_audit_rejudge_answers*.csv",
               "INTRA-ANNOTATOR AGREEMENT ON THE ADJUDICATION",
               independent=False)


def _agreement(pattern, title, independent):
    import glob
    cands = glob.glob(pattern) + glob.glob(os.path.expanduser("~/Downloads/" + pattern))
    if not cands:
        sys.exit(f"no {pattern} found -- download the second pass first")
    src2 = max(cands, key=os.path.getmtime)
    second = {r["row"]: r["verdict"].strip().lower()
              for r in csv.DictReader(open(src2)) if r["verdict"].strip()}
    wrows = rows()
    # Agreement must be measured on the verdicts the two judges reached
    # INDEPENDENTLY. Once `settle` has written reconciled verdicts back into the
    # worksheet, reading them here would report the agreement the discussion
    # produced (trivially high) as though it were the agreement that preceded it.
    if os.path.exists(PRERECON):
        first = {r["row"]: r["verdict"].strip().lower()
                 for r in csv.DictReader(open(PRERECON))}
        print(f"  (first judge's verdicts read from {PRERECON}, "
              f"i.e. before reconciliation)")
    else:
        first = {r["row"]: r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower()
                 for r in wrows}
    strat = {r["row"]: r["stratum"] for r in wrows}
    both = [(k, first[k], second[k]) for k in second if first.get(k) in ("yes", "no")]
    if not both:
        sys.exit("no overlapping rows judged in both passes")

    n = len(both)
    agree = sum(1 for _, a, b in both if a == b)
    po = agree / n
    pa1 = sum(1 for _, a, _ in both if a == "no") / n
    pa2 = sum(1 for _, _, b in both if b == "no") / n
    pe = pa1 * pa2 + (1 - pa1) * (1 - pa2)
    k = (po - pe) / (1 - pe) if pe < 1 else 1.0
    print("=" * 70); print(title); print("=" * 70)
    print(f"  using {src2}")
    print(f"  rows judged twice        : {n}")
    print(f"  raw agreement            : {agree}/{n} = {100*po:.1f}%")
    print(f"  Cohen's kappa            : {k:.3f}")
    print(f"  'no' rate, first  judge  : {100*pa1:.1f}%")
    print(f"  'no' rate, second judge  : {100*pa2:.1f}%")
    flips = [(r, a, b) for r, a, b in both if a != b]
    if flips:
        print(f"\n  {len(flips)} disagreement(s):")
        for r, a, b in flips:
            print(f"     row {r:>5s}  first {a:3s} -> second {b}")

    if independent:
        # The second judge's own verdicts give a second, independent estimate of
        # the noise rate by the same stratified formula -- which is the point of
        # asking a second person rather than merely checking consistency.
        F = [(r, b) for r, _, b in both if strat.get(r) == "flagged"]
        U = [(r, b) for r, _, b in both if strat.get(r) == "unflagged"]
        if F and U:
            flags = {str(f["row"]) for f in
                     json.load(open("results_tables/gold_screen_flags.json"))}
            sc = _scorable()
            N, nf = len(sc), len(flags & sc)
            p = sum(1 for _, v in F if v == "no") / len(F)
            q = sum(1 for _, v in U if v == "no") / len(U)
            est = (nf * p + (N - nf) * q) / N

            def wilson(kk, nn, z=1.96):
                if not nn: return (0.0, 0.0)
                ph = kk / nn; d = 1 + z*z/nn
                c = (ph + z*z/(2*nn)) / d
                h = z*((ph*(1-ph)/nn + z*z/(4*nn*nn))**0.5)/d
                return (max(0.0, c-h), min(1.0, c+h))
            pl, phi = wilson(sum(1 for _, v in F if v == "no"), len(F))
            ql, qhi = wilson(sum(1 for _, v in U if v == "no"), len(U))
            lo = (nf*pl + (N-nf)*ql)/N
            hi = (nf*phi + (N-nf)*qhi)/N
            print(f"\n  SECOND JUDGE'S INDEPENDENT NOISE ESTIMATE : {100*est:.1f}%"
                  f"  [{100*lo:.1f}, {100*hi:.1f}]"
                  f"   ({len(F)} flagged, {len(U)} unflagged)")
            print("  Compare with the headline in RESULT_gold_noise.txt. Two")
            print("  independent estimates that land close together is the")
            print("  strongest claim this design can make.")
        else:
            print("\n  (not enough of both strata returned for an independent estimate)")
    else:
        print("\n  This bounds NOISE in one person's adjudication. It is not")
        print("  inter-annotator agreement and must not be reported as it.")


# ------------------------------------------------------------- reconcile ---
# After two independent passes, the honest way to a single rate is a
# reconciliation round: both judges look at the rows they differ on, TOGETHER,
# with the query text open. Reporting convention -- publish the pre-reconciliation
# agreement (kappa) AND the post-reconciliation rate. Reporting only the second
# would hide how hard the judgement was, which on this benchmark is the finding.
RECONCILE_PAGE = "gold_audit_reconcile.html"
PRERECON = "annotations/gold_audit_prereconcile.csv"
ANNOT2 = "gold_audit_annotator2_answers*.csv"

# Faults that a result preview cannot show. Detected mechanically and shown as
# THINGS TO CHECK, never as verdicts -- the point of the round is the two
# readers' judgement, not a heuristic's.
MARKERS = [
    ("a commented-out line inside the query",
     lambda q: bool(re.search(r"^\s*#\s*(FILTER|VALUES|BIND|\?)", q, re.M))),
    ("an OPTIONAL holding more than one required triple (binds all or none)",
     lambda q: bool(re.search(r"OPTIONAL\s*\{[^}]*;[^}]*;", q, re.S))),
    ("an OPTIONAL never tested with BOUND",
     lambda q: "OPTIONAL" in q and "BOUND" not in q.upper()),
    ("a renamed or derived variable in the projection",
     lambda q: bool(re.search(r"\(\s*\?\w+\s+as\s+\?\w+\s*\)", q, re.I))),
    ("no P31/P279 class restriction anywhere",
     lambda q: "P31" not in q and "P279" not in q),
]


def _second_verdicts():
    import glob
    cands = glob.glob(ANNOT2) + glob.glob(os.path.expanduser("~/Downloads/" + ANNOT2))
    if not cands:
        sys.exit(f"no {ANNOT2} found -- the second adjudicator's file is needed")
    path = max(cands, key=os.path.getmtime)
    return path, {r["row"]: (r["verdict"].strip().lower(), r.get("note", "").strip())
                  for r in csv.DictReader(open(path)) if r["verdict"].strip()}


def _disagreements():
    path, second = _second_verdicts()
    out = []
    for r in rows():
        a = r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower()
        if r["row"] in second and a in ("yes", "no") and second[r["row"]][0] != a:
            b, note = second[r["row"]]
            out.append((r, a, b, note))
    return path, out


def reconcile():
    path, dis = _disagreements()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    lab = json.load(open(LABELS)) if os.path.exists(LABELS) else {}
    data = []
    for r, a, b, note in dis:
        c = cache.get(r["row"], {})
        q = r["reference_query"]
        data.append({"row": r["row"], "question": r["question"], "query": q,
                     "you": a, "them": b, "note": note,
                     "markers": [name for name, f in MARKERS if f(q)],
                     "cols": c.get("cols", []), "res": c.get("rows", []),
                     "n": c.get("n"), "err": c.get("error", "")})
    out = (RECON_TEMPLATE.replace("/*DATA*/", json.dumps(data))
           .replace("/*LABELS*/", json.dumps({k: v for k, v in lab.items() if v})))
    open(RECONCILE_PAGE, "w", encoding="utf-8").write(out)

    # a printable copy, for reading away from a screen
    with open("RECONCILE_SHEET.md", "w", encoding="utf-8") as f:
        f.write("# Reconciliation sheet — the 15 rows you disagree on\n\n")
        f.write(f"Second adjudicator's file: `{path}`\n\n")
        f.write("For each row, decide together: **is this reference query a fair "
                "answer to its question?** Read the SPARQL, not the results — the "
                "faults that caused this disagreement do not show in the output.\n\n")
        for d in data:
            f.write(f"---\n\n## Row {d['row']}\n\n")
            f.write(f"**Question.** {d['question']}\n\n")
            f.write(f"- author: **{d['you']}**, second judge: **{d['them']}**\n")
            if d["note"]:
                f.write(f"- second judge's reason: *{d['note']}*\n")
            if d["markers"]:
                f.write("- mechanically detected, worth checking: "
                        + "; ".join(d["markers"]) + "\n")
            f.write(f"\n```sparql\n{d['query'].strip()}\n```\n\n")
            f.write("**Agreed verdict:** ______   **because:** "
                    "________________________________\n\n")
    print(f"wrote {RECONCILE_PAGE} and RECONCILE_SHEET.md -- {len(data)} rows")
    print("Work through them together, then click 'Download agreed' and run:")
    print("  python3 build_audit_page.py settle")


def settle():
    import glob
    cands = (glob.glob("annotations/gold_audit_reconciled*.csv")
             + glob.glob(os.path.expanduser("~/Downloads/gold_audit_reconciled*.csv")))
    if not cands:
        sys.exit("no gold_audit_reconciled*.csv found -- download from the "
                 "reconciliation page first")
    path = max(cands, key=os.path.getmtime)
    agreed = {r["row"]: (r["verdict"].strip().lower(), r.get("note", "").strip())
              for r in csv.DictReader(open(path)) if r["verdict"].strip() in ("yes", "no")}
    _, dis = _disagreements()
    unresolved = [r["row"] for r, _, _, _ in dis if r["row"] not in agreed]

    if not os.path.exists(PRERECON):
        with open(PRERECON, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["row", "verdict"])
            for r in rows():
                w.writerow([r["row"],
                            r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower()])
        print(f"saved the pre-reconciliation verdicts to {PRERECON} so the "
              f"independent kappa stays recoverable")

    out, applied = [], 0
    for r in rows():
        if r["row"] in agreed:
            v, note = agreed[r["row"]]
            r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"] = v
            r["your_note"] = (note or r["your_note"]) + "  [reconciled]"
            applied += 1
        out.append(r)
    with open(WORKSHEET, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"applied {applied} agreed verdicts to {WORKSHEET}")
    if unresolved:
        print(f"STILL UNRESOLVED ({len(unresolved)}): {', '.join(unresolved)}")
        print("  Leave these as they are and say so in the thesis -- a residual")
        print("  disagreement after discussion is a stronger statement about the")
        print("  benchmark than a forced agreement would be.")
    print("\nnow run:  python3 gold_query_screen.py estimate")
    print("and report the PRE-reconciliation kappa (0.426) alongside the new rate.")


RECON_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Reconciliation</title>
<style>
 :root{--bg:#fbfaf8;--fg:#1c1a17;--mut:#6b6560;--line:#e0dcd6;--card:#fff;
       --yes:#2f6b3d;--no:#8c3320;--open:#7a6a2a;--accent:#8a6d1f}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
 header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
        padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;z-index:5}
 h1{font-size:15px;margin:0;font-weight:600}
 .prog{color:var(--mut);font-size:13px}
 button{font:inherit;padding:6px 12px;border:1px solid var(--line);background:var(--card);
        border-radius:6px;cursor:pointer}
 button:hover{border-color:var(--mut)}
 main{max-width:900px;margin:0 auto;padding:20px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
       padding:18px 20px;margin-bottom:18px}
 .card.done{opacity:.55}
 .rownum{font-size:12px;color:var(--mut);margin-bottom:6px}
 .q{font-size:17px;font-weight:600;margin:0 0 12px}
 .split{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
 .v{flex:1;min-width:210px;border:1px solid var(--line);border-radius:8px;padding:9px 11px;
    font-size:13px;background:#faf8f5}
 .v b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
      color:var(--mut);margin-bottom:3px}
 .v .verd{font-weight:700}
 .v .verd.yes{color:var(--yes)} .v .verd.no{color:var(--no)}
 .mk{background:#fdf8e8;border:1px solid #ece0bd;border-radius:8px;padding:9px 12px;
     font-size:13px;margin-bottom:10px;line-height:1.5}
 .mk b{color:var(--accent)}
 pre{background:#f4f1ec;border:1px solid var(--line);border-radius:6px;padding:11px;
     font-size:11.5px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;margin:0 0 10px}
 .n{font-size:12px;color:var(--mut);margin:0 0 6px}
 table{border-collapse:collapse;font-size:12px;width:100%;display:block;overflow-x:auto;
       margin-bottom:10px}
 th,td{border:1px solid var(--line);padding:3px 7px;text-align:left;white-space:nowrap;
       max-width:250px;overflow:hidden;text-overflow:ellipsis}
 th{background:#f4f1ec}
 details summary{cursor:pointer;font-size:13px;color:var(--mut);margin-bottom:8px}
 .ans{margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .ans button{padding:7px 14px;font-weight:600}
 .ans button.yes.on{background:var(--yes);color:#fff;border-color:var(--yes)}
 .ans button.no.on{background:var(--no);color:#fff;border-color:var(--no)}
 .ans button.split.on{background:var(--open);color:#fff;border-color:var(--open)}
 .ans input{flex:1;min-width:240px;padding:6px 9px;border:1px solid var(--line);
            border-radius:6px;font:inherit}
</style></head><body>
<header>
  <h1>Reconciliation &mdash; the rows you disagree on</h1>
  <span class="prog" id="prog"></span>
  <button id="dl">Download agreed</button>
</header>
<main id="main"></main>
<script>
const DATA = /*DATA*/;
const LAB = /*LABELS*/;
const KEY = "gold_audit_reconcile_v1";
let ans = {}; try{ ans = JSON.parse(localStorage.getItem(KEY)||"{}"); }catch(e){}
const save = () => { try{ localStorage.setItem(KEY, JSON.stringify(ans)); }catch(e){} };
const esc = s => (s||"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const nice = v => { const m=String(v||"").match(/^Q\d+$/); return m&&LAB[v] ? v+" · "+LAB[v] : v; };

function prog(){
  const n = Object.values(ans).filter(a=>a&&a.verdict).length;
  document.getElementById("prog").textContent = n + " of " + DATA.length + " settled";
}
function render(){
  document.getElementById("main").innerHTML = DATA.map(d => {
    const a = ans[d.row] || {};
    const tbl = d.err
      ? '<div class="n">Did not execute here &mdash; judge from the query.</div>'
      : (d.cols.length ? '<div class="n">returns ' + d.n + ' row' + (d.n===1?'':'s') + '</div>'
          + '<table><tr>' + d.cols.map(c=>"<th>"+esc(c)+"</th>").join("") + "</tr>"
          + d.res.map(r=>"<tr>"+r.map(v=>"<td>"+esc(nice(v))+"</td>").join("")+"</tr>").join("")
          + "</table>" : '<div class="n">returns nothing</div>');
    return '<div class="card'+(a.verdict?' done':'')+'" data-row="'+d.row+'">'
      + '<div class="rownum">row '+d.row+'</div>'
      + '<p class="q">'+esc(d.question)+'</p>'
      + '<div class="split">'
      +   '<div class="v"><b>author</b><span class="verd '+d.you+'">'+d.you+'</span></div>'
      +   '<div class="v"><b>second judge</b><span class="verd '+d.them+'">'+d.them+'</span>'
      +     (d.note ? '<div style="margin-top:5px">'+esc(d.note)+'</div>' : '')
      +   '</div></div>'
      + (d.markers.length ? '<div class="mk"><b>Worth checking in the query text.</b> '
          + 'Detected mechanically, not a verdict: ' + d.markers.map(esc).join("; ") + '.</div>' : '')
      + '<pre>'+esc(d.query.trim())+'</pre>'
      + '<details><summary>show what it returns</summary>'+tbl+'</details>'
      + '<div class="ans">'
      +   '<button class="yes'+(a.verdict==="yes"?" on":"")+'" data-v="yes">Agreed: it answers it</button>'
      +   '<button class="no'+(a.verdict==="no"?" on":"")+'" data-v="no">Agreed: it does not</button>'
      +   '<button class="split'+(a.verdict==="split"?" on":"")+'" data-v="split">Still disagree</button>'
      +   '<input placeholder="why (worth writing down)" value="'+esc(a.note||"")+'">'
      + '</div></div>';
  }).join("");
  prog();
}
document.getElementById("main").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]"); if(!b) return;
  const card = b.closest(".card"), row = card.dataset.row;
  const cur = ans[row] || {};
  cur.verdict = (cur.verdict === b.dataset.v) ? "" : b.dataset.v;
  ans[row] = cur; save();
  card.querySelectorAll("button[data-v]").forEach(x =>
    x.classList.toggle("on", cur.verdict === x.dataset.v));
  card.classList.toggle("done", !!cur.verdict);
  prog();
});
document.getElementById("main").addEventListener("input", e => {
  if(e.target.tagName !== "INPUT") return;
  const row = e.target.closest(".card").dataset.row;
  ans[row] = ans[row] || {}; ans[row].note = e.target.value; save(); prog();
});
document.getElementById("dl").addEventListener("click", () => {
  const q = s => '"' + String(s||"").replace(/"/g,'""') + '"';
  const csv = "row,verdict,note\n" + DATA.map(d =>
      [d.row, (ans[d.row]||{}).verdict||"", q((ans[d.row]||{}).note||"")].join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
  a.download = "gold_audit_reconciled.csv"; a.click();
});
render();
</script></body></html>
"""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "page"
    {"fetch": fetch, "labels": labels, "page": page, "ingest": ingest,
     "rejudge": rejudge, "compare": compare,
     "annotator2": annotator2, "compare2": compare2,
     "reconcile": reconcile, "settle": settle}.get(
        cmd, lambda: sys.exit(
            "usage: build_audit_page.py fetch | labels | page | ingest | "
            "rejudge | compare | annotator2 | compare2"))()
