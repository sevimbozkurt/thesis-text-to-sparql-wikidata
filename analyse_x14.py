"""
"""
import json, re, csv, os

LAB = re.compile(r'\[(entity|property):([^\]]*)\]')

def from_linked(f):
    d = json.load(open(f))
    return {m.group(2) for v in d.values()
            for m in LAB.finditer(v.get("labeled_query") or "")}

def from_gen(f):
    d = json.load(open(f))
    return {m.group(2) for v in d.values() for m in LAB.finditer(v or "")}

def J(a, b):
    return len(a & b) / len(a | b) if (a | b) else float("nan")

base = from_gen("baseline_generated.json")
ARMS = [
    ("idiom guidance",            from_gen("idiom_generated.json"),      "+3.9",  "informative"),
    ("schema evidence, verbose",  from_linked("linked_grounded.json"),   "-14.7", "enumerative"),
    ("schema evidence, targeted", from_linked("linked_grounded-targeted.json"), "-12.7", "enumerative"),
    ("construct profile (X10)",   from_gen("profile_generated.json"),    "?",     "informative, targeted"),
    ("constrained vocab (X14)",   from_gen("constrained_generated.json"),"?",     "RESTRICTIVE"),
]

print("=" * 78)
print("X14 — label-vocabulary overlap with the baseline arm (Jaccard)")
print("=" * 78)
print(f"{'arm':28s} {'labels':>7s} {'overlap':>8s}  {'accuracy':>8s}  framing")
print("-" * 78)
print(f"{'baseline':28s} {len(base):7d} {1.0:8.3f}  {'--':>8s}  none")
rows = []
for name, s, acc, framing in ARMS:
    j = J(base, s)
    print(f"{name:28s} {len(s):7d} {j:8.3f}  {acc:>8s}  {framing}")
    rows.append(dict(arm=name, unique_labels=len(s), overlap_with_baseline=round(j, 3),
                     accuracy_delta_pp=acc, framing=framing))

con = from_gen("constrained_generated.json")
idi = from_gen("idiom_generated.json")
gv  = from_linked("linked_grounded.json")
print("-" * 78)
print(f"\nPREDICTION was: constrained lands near the idiom arm's 0.727, not 0.383.")
print(f"OBSERVED:       constrained = {J(base, con):.3f}")
verdict = ("CONSISTENT with the principle" if J(base, con) > 0.60 else
           "AGAINST the principle" if J(base, con) < 0.45 else
           "AMBIGUOUS -- between the two regimes")
print(f"VERDICT:        {verdict}")

# how much of the drift is the arm obeying its own restriction?
test = json.load(open("test.json"))
ANN = re.compile(r'\[(?:entity|property):([^\]]*)\]')
obey = viol = 0
for i, r in enumerate(test):
    allowed = set(ANN.findall(r.get("annotated") or ""))
    used = set(ANN.findall(json.load(open("constrained_generated.json")).get(str(i), "")
                           if False else ""))
gen = json.load(open("constrained_generated.json"))
tot_used = tot_out = 0
for i, r in enumerate(test):
    allowed = set(ANN.findall(r.get("annotated") or ""))
    used = set(ANN.findall(gen.get(str(i), "") or ""))
    if not used:
        continue
    tot_used += len(used)
    tot_out += len(used - allowed)
print(f"\nOBEDIENCE: of {tot_used} label uses in the constrained arm, "
      f"{tot_out} ({100*tot_out/max(tot_used,1):.1f}%) are outside the permitted list.")
print("A prompt-level restriction can be ignored; this measures whether it was.")

os.makedirs("results_tables", exist_ok=True)
with open("results_tables/x14_overlap.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("\nwritten: results_tables/x14_overlap.csv")
print("\nOverlap is a MECHANISM measurement, not accuracy. The accuracy half needs")
print("the GPU disambiguation stage (disamb_any.py --tag constrained).")
