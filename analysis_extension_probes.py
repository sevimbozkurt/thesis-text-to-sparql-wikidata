"""analysis_extension_probes.py — offline feasibility probes for thesis
extensions. No API calls; reads frozen splits and cached run CSVs only.

Usage:  python3 analysis_extension_probes.py
"""
import csv, json, re, warnings
import numpy as np
warnings.filterwarnings("ignore")

PAT = {"closure P279*":  r'P279\s*\*|subclass of\]\s*\*',
       "statement p:":   r'\bp:P\d+|\bp:\[',
       "qualifier pq:":  r'\bpq:P\d+|\bpq:\[',
       "value node psv:": r'\bpsv:P\d+|\bpsv:\[',
       "aggregation":    r'(?i)\bgroup by\b',
       "alternation":    r'(?i)\bvalues\b|\bunion\b'}
IDIOM_ANY = r'P279\s*\*|\bp:P\d+|\bpq:P\d+|\bpsv:P\d+'

tr = json.load(open("train.json")); te = json.load(open("test.json"))
gold = {str(i): r["query"] for i, r in enumerate(te)}
strict = {r["index"] for r in csv.DictReader(open("gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}

def val(r, col="jaccard_entity"):
    v = r.get(col); return None if v in (None, "", "na") else float(v)

# ── P1 ────────────────────────────────────────────────────────────────
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score, precision_score, recall_score
print("P1 — predict idiom NEED from question text (train 2131 -> test 567)")
X = [r["instruction"] for r in tr] + [r["instruction"] for r in te]
vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True); Xv = vec.fit_transform(X); n = len(tr)
print(f"{'construct':17s} {'base%':>6s} {'AUC':>5s} {'P':>6s} {'R':>6s} {'F1':>6s}")
for name, p in PAT.items():
    ytr = np.array([bool(re.search(p, r["query"])) for r in tr]).astype(int)
    yte = np.array([bool(re.search(p, r["query"])) for r in te]).astype(int)
    clf = LogisticRegression(C=4, max_iter=2000, class_weight="balanced").fit(Xv[:n], ytr)
    pr = clf.predict_proba(Xv[n:])[:, 1]; yp = (pr >= .5).astype(int)
    print(f"{name:17s} {yte.mean()*100:5.1f}% {roc_auc_score(yte, pr):5.2f} "
          f"{precision_score(yte, yp)*100:5.1f} {recall_score(yte, yp)*100:5.1f} {f1_score(yte, yp)*100:5.1f}")

# ── P2 ────────────────────────────────────────────────────────────────
def rows(f): return {r["row_id"]: r for r in csv.DictReader(open(f))}
base, idi = rows("linked_base-qwen.csv"), rows("linked_idiom-qwen.csv")
common = [k for k in base if k in idi and k in strict and val(base[k]) is not None and val(idi[k]) is not None]
d = {k: (val(idi[k]) - val(base[k])) * 100 for k in common}
print(f"\nP2 — idiom prompt vs baseline, paired entity Jaccard, n={len(common)}")
print(f"mean delta {np.mean(list(d.values())):+.2f}pp; improved {sum(v>0 for v in d.values())}, "
      f"worsened {sum(v<0 for v in d.values())}, unchanged {sum(v==0 for v in d.values())}")
print(f"{'gold uses':17s} {'n':>4s} {'delta need':>10s} {'n':>4s} {'delta no-need':>13s}")
for name, p in PAT.items():
    need = [k for k in common if re.search(p, gold[k])]; no = [k for k in common if not re.search(p, gold[k])]
    print(f"{name:17s} {len(need):4d} {np.mean([d[k] for k in need]):+10.2f} {len(no):4d} {np.mean([d[k] for k in no]):+13.2f}")
need = [k for k in common if re.search(IDIOM_ANY, gold[k])]
orc = np.mean([val(idi[k]) if k in need else val(base[k]) for k in common]) * 100
print(f"oracle gate (idiom only where gold needs reification/hierarchy idiom, n_need={len(need)}): "
      f"baseline {np.mean([val(base[k]) for k in common])*100:.1f} | idiom-always "
      f"{np.mean([val(idi[k]) for k in common])*100:.1f} | oracle-gated {orc:.1f}")

# ── P3 ────────────────────────────────────────────────────────────────
print("\nP3 — oracle-selection ceiling over existing runs (entity Jaccard, strict, all runs defined)")
RUNS = {"zs-claude": "qlever_v2/results_claude.csv", "zs-gpt": "qlever_v2/results_gpt-5.4.csv",
        "zs-gemini": "qlever_v2/results_gemini.csv", "zs-deepseek": "qlever_v2/results_deepseek.csv",
        "fs-claude": "qlever_v2/results_fewshot_claude.csv", "e2e-clean": "qlever_v2/results_e2e_clean.csv"}
R = {}
for k, f in RUNS.items():
    try: R[k] = {r["index"]: r for r in csv.DictReader(open(f))}
    except FileNotFoundError: pass
R["arm-base"] = base; R["arm-idiom"] = idi
ids = [i for i in strict if all(i in r and val(r[i]) is not None for r in R.values())]
def mean_of(names): return np.mean([max(val(R[n][i]) for n in names) for i in ids]) * 100
single = {k: np.mean([val(R[k][i]) for i in ids]) * 100 for k in R}
best = max(single, key=single.get)
print(f"n={len(ids)}; best single run: {best} {single[best]:.1f}")
print(f"oracle over 4 zero-shot models        : {mean_of(['zs-claude','zs-gpt','zs-gemini','zs-deepseek']):.1f}")
print(f"oracle over baseline+idiom arms       : {mean_of(['arm-base','arm-idiom']):.1f}")
print(f"oracle over e2e-clean + idiom arm     : {mean_of(['e2e-clean','arm-idiom']):.1f}")
print(f"oracle over ALL {len(R)} runs             : {mean_of(list(R)):.1f}")
solved_any = sum(1 for i in ids if max(val(R[n][i]) for n in R) >= 0.999)
print(f"questions with an exact-match answer in at least one run: {solved_any}/{len(ids)} = {solved_any/len(ids)*100:.1f}%")
