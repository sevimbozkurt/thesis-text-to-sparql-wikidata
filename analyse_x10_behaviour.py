"""

Usage: python3 analyse_x10_behaviour.py
Writes results_tables/x10_behaviour.csv
"""
import json, csv, os
from construct_analysis import PATTERNS, uses
from prompt_construct_profile import PROFILE_CONSTRUCTS, gold_of

test = json.load(open("data/test.json"))
ARMS = [("baseline", "baseline_generated.json"),
        ("idiom",    "idiom_generated.json"),
        ("profile",  "profile_generated.json")]
gens = {n: json.load(open(f)) for n, f in ARMS if os.path.exists(f)}

rows = []
print("=" * 74)
print("X10 STAGE 1 — does the model produce the construct when told to?")
print("=" * 74)
print(f"{'construct':26s} {'gold':>5s} {'base':>6s} {'idiom':>6s} {'prof':>6s}"
      f"   {'COMPLIANCE on rows where gold uses it':>0s}")
print(f"{'':26s} {'n':>5s} {'n':>6s} {'n':>6s} {'n':>6s}   "
      f"{'base':>6s} {'idiom':>6s} {'prof':>6s}")
print("-" * 74)

for name in PROFILE_CONSTRUCTS:
    gold_rows = [i for i, r in enumerate(test) if uses(gold_of(r), name, False)]
    counts, comply = {}, {}
    for arm in gens:
        g = gens[arm]
        counts[arm] = sum(1 for i in range(len(test))
                          if uses(g.get(str(i), ""), name, True))
        hit = sum(1 for i in gold_rows if uses(g.get(str(i), ""), name, True))
        comply[arm] = 100 * hit / len(gold_rows) if gold_rows else float("nan")
    short = name.split(" (")[0]
    print(f"{short:26s} {len(gold_rows):5d} "
          f"{counts.get('baseline',0):6d} {counts.get('idiom',0):6d} "
          f"{counts.get('profile',0):6d}   "
          f"{comply.get('baseline',0):5.1f}% {comply.get('idiom',0):5.1f}% "
          f"{comply.get('profile',0):5.1f}%")
    rows.append(dict(construct=name, gold_rows=len(gold_rows),
                     **{f"count_{a}": counts.get(a, 0) for a in gens},
                     **{f"compliance_{a}": round(comply.get(a, 0), 1) for a in gens}))

# negative control: rows whose reference needs NO idiom were explicitly told so
none_rows = [i for i, r in enumerate(test)
             if not any(uses(gold_of(r), n, False) for n in PROFILE_CONSTRUCTS)]
print("-" * 74)
print(f"\nNEGATIVE CONTROL — {len(none_rows)} rows whose reference needs no idiom,")
print("and whose prompt said so explicitly. Lower is better:")
for arm in gens:
    g = gens[arm]
    over = sum(1 for i in none_rows
               if any(uses(g.get(str(i), ""), n, True) for n in PROFILE_CONSTRUCTS))
    print(f"  {arm:9s} used an idiom anyway on {over:4d}/{len(none_rows)} "
          f"= {100*over/len(none_rows):.1f}%")

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/x10_behaviour.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("\nwritten: results_tables/x10_behaviour.csv")
print("\nReading: compliance is the 'how' measurement. High compliance with a")
print("flat accuracy result (GPU stage) would mean the model can write the")
print("idioms and still gets the query wrong for other reasons.")
