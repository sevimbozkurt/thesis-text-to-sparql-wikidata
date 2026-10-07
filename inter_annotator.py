"""inter_annotator.py — INTER-annotator agreement on the error taxonomy.

Usage:
  python3 inter_annotator.py prepare
  # ... hand the worksheet + guide to the second annotator ...
  python3 inter_annotator.py compare
"""
import csv, random, sys, os, collections

SRC   = "annotations/annotation_clean.csv"
SHEET = "annotations/inter_annotator_worksheet.csv"
GUIDE = "inter_annotator_GUIDE.md"
SEED  = 1743          # independent of seed 42 (sample) and seed 7 (intra-check)

CATEGORIES = ["structure", "triple_flip", "wrong_entity", "wrong_property",
              "unresolved", "execution", "near_miss", "benchmark_noise"]

DEFS = [
 ("structure",
  "The generated query is syntactically fine and its identifiers are right, but "
  "it is built the wrong SHAPE: it uses the direct shortcut `wdt:` where the "
  "reference needs a richer construct -- a subclass closure (`wdt:P31/wdt:P279*`), "
  "a qualifier reachable only through `p:`/`pq:`, a normalised value node "
  "(`psv:`) for a quantity with units, an aggregation (COUNT/AVG/GROUP BY), an "
  "alternation over allowed values, or the lexeme/sitelink model.",
  "Gold averages heights through the value node so units are normalised; the "
  "generated query averages the raw numbers."),
 ("wrong_property",
  "The shape is right but a PROPERTY identifier is wrong -- a different Wikidata "
  "property was chosen than the reference uses.",
  "Gold uses `position held` (P39); generated uses `occupation` (P106)."),
 ("wrong_entity",
  "The shape is right but an ENTITY identifier is wrong.",
  "Gold uses the film Q25188; generated uses the soundtrack album."),
 ("near_miss",
  "Both queries answer the question, but they PROJECT different variables, so "
  "the returned sets do not overlap. Typically gold returns the subject of a "
  "relation and the generated query returns its object.",
  "Gold returns the directors; generated returns the films they directed."),
 ("triple_flip",
  "Subject and object of a triple pattern are REVERSED, so the query asks the "
  "relation backwards.",
  "`?x wdt:P57 wd:Q25188` written as `wd:Q25188 wdt:P57 ?x`."),
 ("unresolved",
  "A label was never linked to an identifier at all -- the query still contains "
  "an unresolved placeholder, or the linking stage returned nothing for it.",
  "`wdt:[property:significant achievement]` left in the query."),
 ("execution",
  "The query failed to run, or the endpoint refused it (syntax error, timeout, "
  "result too large). Judge this from the `executed` and `exec_error` columns.",
  "HTTP error because prose was appended after the query."),
 ("benchmark_noise",
  "The REFERENCE query is itself wrong -- it does not answer the question it is "
  "paired with. The generated query may even be better.",
  "Question asks for the heaviest humans; gold returns the classes of things "
  "that have a weight."),
]

ORDER = """DECISION ORDER — apply these tests in order and stop at the first that fits.

  1. Did the query fail to run?                          -> execution
  2. Is there still an unresolved [entity:...] or
     [property:...] placeholder in it?                   -> unresolved
  3. Does the REFERENCE query fail to answer its own
     question?                                           -> benchmark_noise
  4. Is a triple written backwards?                      -> triple_flip
  5. Do both queries answer the question, but return
     different COLUMNS?                                  -> near_miss
  6. Is the query the wrong SHAPE (missing closure,
     qualifier, value node, aggregation)?                -> structure
  7. Is the shape right but an identifier wrong?         -> wrong_property
                                                            or wrong_entity

Step 6 before step 7 is deliberate and is the hardest call in this task. If the
query would still be wrong AFTER swapping in the correct property, the problem
is the shape: choose `structure`. If swapping the property alone would make it
right, choose `wrong_property`. Use the `second_choice` column whenever you
hesitate between two categories -- recording the hesitation is useful data, and
it does not count against agreement."""


def rows():
    with open(SRC, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def prepare():
    data = rows()
    random.Random(SEED).shuffle(data)
    cols = ["case", "orig_index", "complexity", "question", "reference_query",
            "generated_query", "fully_linked", "executed", "exec_error",
            "jaccard", "YOUR_CATEGORY", "second_choice", "your_note"]
    with open(SHEET, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        for i, r in enumerate(data, 1):
            wr.writerow({
                "case": i,
                "orig_index": r["index"],
                "complexity": r["complexity"],
                "question": r["question"],
                "reference_query": r["gold_query"],
                "generated_query": r["linked_query"],
                "fully_linked": r["fully_linked"],
                "executed": r["executed"],
                "exec_error": r["exec_error"],
                "jaccard": r["jaccard"],
                "YOUR_CATEGORY": "", "second_choice": "", "your_note": "",
            })
    with open(GUIDE, "w", encoding="utf-8") as f:
        f.write("# Second-annotator guide — error taxonomy\n\n")
        f.write("Thank you for doing this. It should take 45–75 minutes.\n\n")
        f.write("## What you are doing\n\n"
                "A system translated natural-language questions into SPARQL queries "
                "against Wikidata. All thirty cases in the worksheet are **failures** "
                "— the generated query did not return the reference answer. Your job "
                "is to decide, for each one, **what went wrong**, choosing exactly "
                "one of eight categories.\n\n"
                "Please **do not** read the thesis or any results file before you "
                "finish. The point of this exercise is that your judgement is "
                "independent of the author's.\n\n")
        f.write("## How to fill it in\n\n"
                f"Open `{SHEET}` in Excel, Numbers or a text editor. For each row "
                "put one category name in **YOUR_CATEGORY**. Use exactly these "
                "spellings:\n\n```\n" + "\n".join(CATEGORIES) + "\n```\n\n"
                "If you hesitated between two, put the runner-up in "
                "**second_choice**. Add anything you noticed in **your_note**. "
                "Leave nothing blank in YOUR_CATEGORY — if you truly cannot tell, "
                "pick the closest and say so in the note.\n\n")
        f.write("## Reading a row\n\n"
                "- `question` — what was asked.\n"
                "- `reference_query` — the benchmark's correct query.\n"
                "- `generated_query` — what the system produced. Identifiers appear "
                "as readable labels in brackets, e.g. `wdt:[property:director]`.\n"
                "- `fully_linked` / `executed` / `exec_error` — whether every label "
                "resolved, and whether the query ran.\n"
                "- `jaccard` — overlap with the reference answer; 0 means no overlap.\n\n")
        f.write("## A 60-second primer on Wikidata's query shapes\n\n"
                "You need this only for the `structure` category.\n\n"
                "- `wdt:P57` — the **shortcut**: goes straight from item to value.\n"
                "- `p:P39` + `ps:P39` — goes via a **statement node** instead. Same "
                "answer, but the statement node can carry extra detail.\n"
                "- `pq:P580` — a **qualifier** (a date, a role) hanging off a "
                "statement node. Reachable *only* through `p:`.\n"
                "- `psv:` — a **normalised value**, carrying the unit a quantity was "
                "recorded in. Needed when comparing quantities.\n"
                "- `wdt:P31/wdt:P279*` — **subclass closure**: all members of a class "
                "*including* members of its subclasses. Plain `wdt:P31` misses those.\n\n"
                "The shortcut is always allowed by the syntax, so a query that uses "
                "it where a richer form was needed still runs — it just answers a "
                "different question.\n\n")
        f.write("## The categories\n\n")
        for name, d, ex in DEFS:
            f.write(f"### `{name}`\n\n{d}\n\n*Example:* {ex}\n\n")
        f.write("## " + ORDER.replace("\n", "\n") + "\n")
    print(f"wrote {SHEET} ({len(data)} cases, shuffled with seed {SEED})")
    print(f"wrote {GUIDE}")
    print("\nGive the second annotator BOTH files and nothing else.")
    print("Then: python3 inter_annotator.py compare")


def kappa(a, b, cats):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return po, (po - pe) / (1 - pe) if pe < 1 else float("nan")


def compare():
    if not os.path.exists(SHEET):
        sys.exit(f"{SHEET} not found — run 'prepare' first")
    orig = {r["index"]: r["error_category"].strip() for r in rows()}
    A, B, pairs, blank = [], [], [], 0
    with open(SHEET, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = r["YOUR_CATEGORY"].strip().lower()
            if not g:
                blank += 1
                continue
            if g not in CATEGORIES:
                sys.exit(f"case {r['case']}: '{g}' is not one of {CATEGORIES}")
            a, b = orig[r["orig_index"]], g
            A.append(a); B.append(b)
            pairs.append((r["case"], r["orig_index"], r["complexity"], a, b,
                          r.get("second_choice", "").strip(),
                          r.get("your_note", "").strip()))
    if blank:
        print(f"WARNING: {blank} rows have no category and were skipped\n")
    if not A:
        sys.exit("nothing annotated yet")

    cats = sorted(set(A) | set(B))
    po, k = kappa(A, B, cats)
    band = ("poor" if k < .40 else "moderate" if k < .60 else
            "substantial" if k < .80 else "almost perfect")
    print("=" * 66)
    print(f"INTER-ANNOTATOR AGREEMENT  (n = {len(A)} of 30)")
    print("=" * 66)
    print(f"  raw agreement   {sum(x==y for x,y in zip(A,B))}/{len(A)} = {po*100:.1f}%")
    print(f"  Cohen's kappa   {k:.3f}   ({band})")

    print("\nconfusion (rows = author, cols = second annotator)")
    m = collections.Counter(zip(A, B))
    w = max(len(c) for c in cats) + 1
    print(" " * (w + 1) + " ".join(f"{c[:6]:>6s}" for c in cats))
    for a in cats:
        print(f"{a:>{w}s} " + " ".join(f"{m[(a,b)]:6d}" for b in cats))

    print("\ndisagreements")
    for case, idx, cx, a, b, sc, note in pairs:
        if a != b:
            extra = f"  (their 2nd choice: {sc})" if sc else ""
            print(f"  case {case:>2s} [{cx:>7s}]  author={a:<16s} other={b:<16s}{extra}")
            if note:
                print(f"      note: {note[:100]}")

    # the boundary the central claim depends on
    pair = {"structure", "wrong_property"}
    on = [(a, b) for a, b in zip(A, B) if {a, b} & pair]
    cross = sum(1 for a, b in on if a != b and {a, b} <= pair)
    print(f"\nSTRUCTURE / WRONG_PROPERTY BOUNDARY")
    print(f"  cases touching either category: {len(on)}")
    print(f"  swapped across just that boundary: {cross}")
    sa = sum(1 for x in A if x == "structure")
    sb = sum(1 for x in B if x == "structure")
    print(f"  'structure' share — author {sa}/{len(A)} = {sa/len(A)*100:.1f}%, "
          f"second annotator {sb}/{len(B)} = {sb/len(B)*100:.1f}%")
    print("\nBoth shares are reported; the decomposition is quoted as a range across annotators.")

    with open("results_tables/inter_annotator.csv", "w", newline="",
              encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["case", "orig_index", "complexity", "author",
                     "second_annotator", "second_choice", "note", "agree"])
        for case, idx, cx, a, b, sc, note in pairs:
            wr.writerow([case, idx, cx, a, b, sc, note, int(a == b)])
    print("\nwritten: results_tables/inter_annotator.csv")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prepare":   prepare()
    elif mode == "compare": compare()
    else: sys.exit(__doc__)
