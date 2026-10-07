"""gold_query_screen.py — bound the benchmark's reference-noise rate.

Usage:
  python3 gold_query_screen.py screen          # flag rate over the split
  python3 gold_query_screen.py validate        # check rules against the 30 known cases
  python3 gold_query_screen.py prepare-audit   # stratified worksheet for a human
  python3 gold_query_screen.py estimate        # bounded rate from the adjudicated sample
"""
import json, re, csv, sys, random, os, collections

SPLIT = "data/test.json"
AUDIT = "annotations/gold_audit_worksheet.csv"

AGG = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX|SAMPLE|GROUP_CONCAT)\s*\(", re.I)
LIST_Q = re.compile(r"^\s*(list|which|who|what|name|show|find|give)\b", re.I)
SUPERLATIVE = re.compile(r"\b(top|highest|lowest|largest|smallest|most|least|"
                         r"oldest|newest|longest|shortest|biggest)\b", re.I)
TOPN = re.compile(r"\btop\s+\d+|\bfirst\s+\d+\b", re.I)
COUNT_Q = re.compile(r"^\s*(how many|count\b|number of)", re.I)
COUNTRYISH = re.compile(r"P17\b|P27\b|P495\b|P1532\b|P1001\b", re.I)
DEMONYM = re.compile(r"\b(czech|german|french|british|spanish|italian|polish|dutch|"
                     r"swedish|danish|norwegian|finnish|russian|american|canadian|"
                     r"australian|japanese|chinese|indian|brazilian|mexican|turkish|"
                     r"greek|portuguese|austrian|swiss|belgian|irish|scottish|welsh|"
                     r"hungarian|romanian|bulgarian|croatian|serbian|ukrainian)\b", re.I)
COUNTRY_WORD = re.compile(r"\bin (the )?[A-Z][a-z]+\b|\bfrom (the )?[A-Z][a-z]+\b")


def projected(q):
    m = re.search(r"SELECT\s+(DISTINCT\s+)?(.*?)\s+WHERE", q, re.I | re.S)
    return m.group(2) if m else ""


def rules(question, gold):
    g = " ".join(gold.split())
    proj = projected(g)
    hits = []
    # H1 asks for items, returns only aggregates
    if LIST_Q.match(question) and not COUNT_Q.match(question) and proj:
        # BUGFIX (validation, 10 Sep): variables INSIDE an aggregate --- the
        # ?thing in (COUNT(?thing) AS ?count) --- were being counted as plain
        # projections, so a query that returns nothing but a count looked as if
        # it projected an item. Strip aggregate expressions first.
        bare = re.sub(r"\((?:[^()]|\([^()]*\))*\)", " ", proj)
        plain = [v for v in re.findall(r"\?(\w+)", bare)
                 if not v.lower().endswith("label")]
        if AGG.search(proj) and not plain:
            hits.append("H1 asks for items, gold returns only a count")
    # H2 superlative / top-N without ordering
    if SUPERLATIVE.search(question):
        if not re.search(r"ORDER\s+BY", g, re.I):
            hits.append("H2 superlative question, gold has no ORDER BY")
        elif TOPN.search(question) and not re.search(r"\bLIMIT\b", g, re.I):
            hits.append("H2 top-N question, gold has no LIMIT")
    # H3 nationality named, no country property
    # H3 needs care: a demonym is often a LANGUAGE or part of a named entity
    # ("the Swedish alphabet", "labels in Spanish"), where no country property
    # is expected. Inspecting the first screen showed those dominated the H3
    # flags, so language and named-entity contexts are excluded.
    m3 = DEMONYM.search(question)
    if m3 and not COUNTRYISH.search(g):
        before = question[max(0, m3.start() - 30):m3.start()].lower()
        after = question[m3.end():m3.end() + 20].lower()
        LANG_CUE = ("written in", "language", "labels", "label", "description",
                    "translat", "spelled", "names in", "named in", " in ")
        ENT_CUE = ("alphabet", "language", "word", "letter", "name", "script")
        if not any(c in before for c in LANG_CUE) and \
           not any(after.lstrip().startswith(c) for c in ENT_CUE):
            hits.append("H3 question names a nationality, gold has no country property")
    # H4 flag bound but never filtered
    # BUGFIX (validation, 10 Sep): the statues case computes its flags with
    # IF(?female, ...) in the SELECT clause rather than BIND(... AS ?v), so
    # looking only for BIND missed it. Treat both, and treat a variable that is
    # only ever an IF *condition* as unfiltered: the query decorates rows with
    # the flag instead of restricting to them.
    bound = re.findall(r"BIND\s*\([^)]*\bAS\s+\?(\w+)\s*\)", g, re.I)
    for v in bound:
        if not re.search(rf"FILTER[^)]*\?{v}\b", g, re.I) and not re.search(rf"\?{v}\b", proj):
            hits.append(f"H4 binds ?{v} but never filters or projects it")
            break
    else:
        for v in set(re.findall(r"\bIF\s*\(\s*\?(\w+)", g, re.I)):
            if not re.search(rf"FILTER[^)]*\?{v}\b", g, re.I):
                hits.append(f"H4 computes ?{v} as a flag but never filters on it")
                break
    # H5 asks for two things, projects one
    if re.search(r"\band their\b|\bwith their\b|\band its\b", question, re.I):
        vars_ = [v for v in re.findall(r"\?(\w+)", proj) if not v.lower().endswith("label")]
        if len(set(vars_)) < 2:
            hits.append("H5 question asks for two things, gold projects one")
    return hits


def load():
    return json.load(open(SPLIT))


def screen():
    rows = load()
    flagged = []
    by_rule = collections.Counter()
    for i, r in enumerate(rows):
        h = rules(r["instruction"], r.get("query") or "")
        if h:
            flagged.append((i, r["instruction"], h))
            for x in h:
                by_rule[x.split()[0]] += 1
    n = len(rows)
    print("=" * 70)
    print(f"GOLD-QUERY SCREEN — {n} reference queries, working split")
    print("=" * 70)
    print(f"  flagged: {len(flagged)} / {n} = {100*len(flagged)/n:.1f}%\n")
    print("  by rule (a query may trip several):")
    for k, v in by_rule.most_common():
        print(f"    {k}  {v:4d}")
    print("\n  first 8 flagged:")
    for i, q, h in flagged[:8]:
        print(f"    row {i:3d}  {q[:66]}")
        print(f"             {h[0]}")
    print(f"\nA FLAG IS NOT A VERDICT. Run 'prepare-audit', adjudicate, then "
          f"'estimate'.")
    json.dump([{"row": i, "question": q, "rules": h} for i, q, h in flagged],
              open("results_tables/gold_screen_flags.json", "w"), indent=1)
    print("written: results_tables/gold_screen_flags.json")


def validate():
    """Do the rules recover the cases the human annotators actually found?"""
    rows = load()
    ia = {r["orig_index"]: r for r in csv.DictReader(open("results_tables/inter_annotator.csv"))}
    known_bad = {k for k, v in ia.items() if v["second_annotator"] == "benchmark_noise"}
    known_ok = {k for k, v in ia.items() if v["second_annotator"] != "benchmark_noise"}
    tp = sum(1 for k in known_bad if rules(rows[int(k)]["instruction"], rows[int(k)].get("query") or ""))
    fp = sum(1 for k in known_ok if rules(rows[int(k)]["instruction"], rows[int(k)].get("query") or ""))
    print("=" * 70)
    print("RULE VALIDATION against the 30 independently annotated cases")
    print("=" * 70)
    print(f"  annotator called 'benchmark_noise' : {len(known_bad)}")
    print(f"  of those, screen flags             : {tp}  (recall {100*tp/max(len(known_bad),1):.0f}%)")
    print(f"  annotator called something else    : {len(known_ok)}")
    print(f"  of those, screen also flags        : {fp}  (these are either false")
    print(f"                                        positives or noise the")
    print(f"                                        annotator missed)")
    print("\n  per-case detail:")
    for k in sorted(known_bad, key=int):
        h = rules(rows[int(k)]["instruction"], rows[int(k)].get("query") or "")
        print(f"    row {k:>3s}  {'FLAGGED' if h else 'MISSED '}  {h[0] if h else ''}")


def prepare_audit(n_flagged=40, n_clean=40, seed=11):
    """Stratified worksheet: a flag rate alone cannot give a noise rate, because
    the rules have unknown precision and recall. Adjudicating a sample of BOTH
    strata gives both, and 'estimate' then combines them."""
    rows = load()
    flags = {f["row"] for f in json.load(open("results_tables/gold_screen_flags.json"))}
    rng = random.Random(seed)
    fl = rng.sample(sorted(flags), min(n_flagged, len(flags)))
    cl = rng.sample(sorted(set(range(len(rows))) - flags), n_clean)
    out = []
    for i in fl + cl:
        r = rows[i]
        h = rules(r["instruction"], r.get("query") or "")
        out.append({"row": i, "stratum": "flagged" if i in flags else "unflagged",
                    "question": r["instruction"],
                    "reference_query": " ".join((r.get("query") or "").split()),
                    "screen_said": "; ".join(h),
                    "DOES_THE_REFERENCE_ANSWER_THE_QUESTION": "", "your_note": ""})
    rng.shuffle(out)
    with open(AUDIT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f"wrote {AUDIT}: {len(fl)} flagged + {len(cl)} unflagged, shuffled.")
    print("Answer yes / no in DOES_THE_REFERENCE_ANSWER_THE_QUESTION.")
    print("The 'screen_said' column is shown for flagged rows only after you")
    print("decide -- ignore it while judging, or delete it first.")


def estimate(include_all=False):
    """include_all=True keeps rows whose reference query does not execute or
    returns nothing. They are excluded by default (see the comment below); the
    flag exists so the sensitivity of the headline number to that choice can be
    shown rather than asserted."""
    if not os.path.exists(AUDIT):
        sys.exit(f"{AUDIT} not found -- run prepare-audit first")
    rows = load()
    flags = {str(f["row"]) for f in json.load(open("results_tables/gold_screen_flags.json"))}
    a = [r for r in csv.DictReader(open(AUDIT))
         if r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower() in ("yes", "no")]

    # A reference query that does not EXECUTE, or that executes and returns
    # nothing, cannot be judged on whether it answers its question: both are
    # properties of the engine and the dump date. The first run of this estimate
    # counted them anyway and every one of them was marked "no" (9 of 9 empty,
    # 10 of 14 non-executing), which put the rate at 35.0% against the second
    # annotator's 16.7%. Restricting to rows that execute and return results --
    # which is also exactly the strict fair set Chapter 6 scores on -- is the
    # population the judgement actually fits.
    scorable = {rid for rid, vals in json.load(open("data/gold_results.json")).items() if vals}
    dropped = [] if include_all else [r for r in a if r["row"] not in scorable]
    if dropped:
        nbad = sum(1 for r in dropped
                   if r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower() == "no")
        print(f"NOTE: {len(dropped)} adjudicated rows do not execute or return nothing "
              f"on this snapshot\n      ({nbad} of them judged 'no'). They are excluded: "
              f"neither condition is evidence\n      about whether the query answers its "
              f"question. Use `estimate all` to include them.\n")
        a = [r for r in a if r["row"] in scorable]
    if not a:
        sys.exit("nothing adjudicated yet")
    bad = lambda r: r["DOES_THE_REFERENCE_ANSWER_THE_QUESTION"].strip().lower() == "no"
    F = [r for r in a if r["stratum"] == "flagged"]
    U = [r for r in a if r["stratum"] == "unflagged"]
    p = sum(1 for r in F if bad(r)) / len(F) if F else 0.0   # precision
    q = sum(1 for r in U if bad(r)) / len(U) if U else 0.0   # miss rate
    if include_all:
        N = len(rows)
        nf = len(flags)
        pop = "all rows"
    else:
        N = len(scorable)
        nf = len(flags & scorable)
        pop = "scorable rows"
    est = (nf * p + (N - nf) * q) / N
    def wilson(k, n, z=1.96):
        if not n: return (0.0, 0.0)
        ph = k / n; d = 1 + z*z/n
        c = (ph + z*z/(2*n)) / d
        h = z*((ph*(1-ph)/n + z*z/(4*n*n))**0.5)/d
        return (max(0, c-h), min(1, c+h))
    pl, ph = wilson(sum(1 for r in F if bad(r)), len(F))
    ql, qh = wilson(sum(1 for r in U if bad(r)), len(U))
    lo = (nf*pl + (N-nf)*ql)/N; hi = (nf*ph + (N-nf)*qh)/N
    print("=" * 70)
    print("BOUNDED REFERENCE-NOISE RATE")
    print("=" * 70)
    print(f"  adjudicated: {len(F)} flagged, {len(U)} unflagged")
    print(f"  precision of the screen : {100*p:.1f}%  [{100*pl:.1f}, {100*ph:.1f}]")
    print(f"  noise among unflagged   : {100*q:.1f}%  [{100*ql:.1f}, {100*qh:.1f}]")
    print(f"  flag rate               : {100*nf/N:.1f}%  ({nf}/{N} {pop})")
    print(f"\n  ESTIMATED NOISE RATE    : {100*est:.1f}%  [{100*lo:.1f}, {100*hi:.1f}]")
    print(f"\n  for comparison: author 3.3%, second annotator 16.7% (n = 30 each)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "estimate":
        estimate(include_all=(len(sys.argv) > 2 and sys.argv[2] == "all"))
    else:
        {"screen": screen, "validate": validate,
         "prepare-audit": prepare_audit}.get(
            cmd, lambda: sys.exit("usage: gold_query_screen.py "
                                  "screen|validate|prepare-audit|estimate [all]"))()
