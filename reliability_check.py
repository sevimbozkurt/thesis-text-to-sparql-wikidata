"""reliability_check.py — Intra-annotator agreement on the error taxonomy.

Usage:
  python3 reliability_check.py prepare
  # ... annotate annotations/reliability_worksheet.csv by hand, save it ...
  python3 reliability_check.py compare
"""

import csv, random, sys, os, collections

SRC     = "annotations/annotation_clean.csv"
SHEET   = "annotations/reliability_worksheet.csv"
N       = 10
SEED    = 7            # deliberately not 42: an independent draw

CATEGORIES = ["structure", "triple_flip", "wrong_entity", "wrong_property",
              "unresolved", "execution", "near_miss", "benchmark_noise"]

# The second pass was annotated in a FINER vocabulary than the eight canonical
# categories -- the annotator spontaneously distinguished, for example, a wrong
# constraint from a missing one, both of which the original scheme calls
# "structure". That is informative in itself (see the note printed by compare())
# but it means the two passes cannot be compared as literal strings.
#
# This map is a JUDGEMENT and is stated here so it can be audited and disputed.
# Every mapping is many-to-one onto the canonical scheme; none of them merges
# two canonical categories, so the map cannot manufacture agreement between
# categories that the original taxonomy treats as distinct.
FINE_TO_CANONICAL = {
    "semantic_wrong_constraint":      "structure",
    "semantic_missing_constraint":    "structure",
    "semantic_missing_aggregation":   "structure",
    "semantic_wrong_property":        "wrong_property",
    "semantic_wrong_result_variable": "near_miss",
    "linking_entity_not_resolved":    "unresolved",
    "linking_property_not_resolved":  "unresolved",
    "execution_result_too_large":     "execution",
    "execution_error":                "execution",
    "gold_query_mismatch":            "benchmark_noise",
}


def canonical(label):
    """Map a second-pass label onto the canonical scheme, or pass it through."""
    l = label.strip().lower().replace("\n", " ").strip()
    return FINE_TO_CANONICAL.get(l, l)


def prepare():
    rows = list(csv.DictReader(open(SRC)))
    annotated = [r for r in rows if r.get("error_category", "").strip()]
    if len(annotated) < N:
        sys.exit(f"only {len(annotated)} annotated rows found in {SRC}")

    rng = random.Random(SEED)
    sample = rng.sample(annotated, N)
    rng.shuffle(sample)

    fields = ["index", "complexity", "question", "gold_query", "linked_query",
              "generated_ok", "fully_linked", "executed", "exec_error",
              "jaccard", "error_category", "notes"]
    with open(SHEET, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sample:
            row = {k: r.get(k, "") for k in fields}
            row["error_category"] = ""      # blank for re-annotation
            row["notes"] = ""
            w.writerow(row)

    print(f"wrote {SHEET}: {N} cases, categories blanked, order shuffled\n")
    print("Annotate it now, WITHOUT consulting the original file.")
    print("Valid categories: " + ", ".join(CATEGORIES))
    print("\nWhen finished:  python3 reliability_check.py compare")


def kappa(a, b, labels):
    """Cohen's kappa for two label sequences."""
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y)
    po = agree / n
    ca = collections.Counter(a)
    cb = collections.Counter(b)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    if pe == 1.0:
        return po, pe, float("nan")
    return po, pe, (po - pe) / (1 - pe)


def compare():
    if not os.path.exists(SHEET):
        sys.exit(f"{SHEET} not found — run 'prepare' first")

    orig = {r["index"]: r.get("error_category", "").strip().lower()
            for r in csv.DictReader(open(SRC))}
    redo = list(csv.DictReader(open(SHEET)))

    missing = [r["index"] for r in redo if not r.get("error_category", "").strip()]
    if missing:
        sys.exit(f"{len(missing)} rows in {SHEET} are still unannotated: {missing}")

    raw_second = [r["error_category"].strip().lower().replace("\n", " ").strip()
                  for r in redo]
    unmapped = sorted({l for l in raw_second
                       if l not in CATEGORIES and l not in FINE_TO_CANONICAL})
    if unmapped:
        print("WARNING: second-pass labels with no mapping to the canonical "
              "scheme, compared as-is: " + ", ".join(unmapped) + "\n")
    fine_used = sorted({l for l in raw_second if l in FINE_TO_CANONICAL})
    pairs = [(orig.get(r["index"], ""), canonical(r["error_category"]))
             for r in redo]
    a = [x for x, _ in pairs]
    b = [y for _, y in pairs]
    labels = sorted(set(a) | set(b))

    po, pe, k = kappa(a, b, labels)
    agree = sum(1 for x, y in zip(a, b) if x == y)

    print(f"intra-annotator check on {len(pairs)} cases\n")
    if fine_used:
        print(f"NOTE: the second pass used a finer vocabulary than the original")
        print(f"      eight categories ({len(fine_used)} distinct fine labels).")
        print(f"      Agreement below is computed after mapping them onto the")
        print(f"      canonical scheme (FINE_TO_CANONICAL in this file); the")
        print(f"      mapping is a judgement and should be quoted with the figure.\n")
    print(f"raw agreement      : {agree}/{len(pairs)} = {po*100:.0f}%")
    print(f"chance agreement   : {pe*100:.0f}%")
    print(f"Cohen's kappa      : {k:.2f}")
    band = ("poor" if k < 0.40 else "moderate" if k < 0.60
            else "substantial" if k < 0.80 else "almost perfect")
    print(f"conventional band  : {band}")

    dis = [(r["index"], x, y) for r, (x, y) in zip(redo, pairs) if x != y]
    if dis:
        print(f"\ndisagreements ({len(dis)}):")
        for idx, x, y in dis:
            print(f"  row {idx:>4}: originally '{x}' → now '{y}'")
        conf = collections.Counter((x, y) for _, x, y in dis)
        top, n_top = conf.most_common(1)[0]
        print(f"\nMost frequent confusion: '{top[0]}' vs '{top[1]}' "
              f"({n_top} of {len(dis)}).")
        print("Systematic confusion between two categories is a more useful "
              "outcome than the kappa value: it says the category definitions "
              "need sharpening in the methodology. Report the specific pair, "
              "not just the number.")
    else:
        print("\nno disagreements")

    with open("results_tables/reliability.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "raw agreement", "chance agreement", "cohens kappa",
                    "second pass used finer scheme", "n disagreements"])
        w.writerow([len(pairs), round(po, 3), round(pe, 3), round(k, 3),
                    bool(fine_used), len(dis)])
        w.writerow([])
        w.writerow(["index", "pass 1", "pass 2 (raw)", "pass 2 (mapped)"])
        for r, (x, y) in zip(redo, pairs):
            w.writerow([r["index"], x, r["error_category"].strip(), y])
    print("\nwritten results_tables/reliability.csv")
    print("Report in the thesis with the caveat that n = 10 makes the estimate "
          "imprecise, and that this measures intra-annotator consistency, not "
          "agreement between independent annotators.")


if __name__ == "__main__":
    os.makedirs("results_tables", exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare()
    elif cmd == "compare":
        compare()
    else:
        sys.exit("usage: reliability_check.py prepare | compare")
