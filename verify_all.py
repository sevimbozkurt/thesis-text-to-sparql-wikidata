"""verify_all.py — Recompute every headline number in the thesis from the
frozen inputs, in one pass, and write a dated report with file hashes.

Usage:   python3 verify_all.py
"""

import csv, json, os, hashlib, collections
from datetime import date

OUT = []
def say(s=""):
    print(s)
    OUT.append(s)

def sha(path, n=12):
    if not os.path.exists(path):
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]

def exists(p):
    return os.path.exists(p)

say(f"# Verification Report — {date.today().isoformat()}")
say()

# ── provenance ────────────────────────────────────────────────
say("## Input files (sha256, first 12 hex chars)")
say()
for p in ["data/test.json", "data/train.json", "data/val.json",
          "data/gold_status_qlever.csv", "data/gold_results.json", "data/gold_links.json",
          "data/candidates_expanded.json", "data/properties_clean.json",
          "data/official_test.json", "data/official_gold_results.json",
          "data/gold_links_official.json", "data/candidates_official.json",
          "data/schema_cards_working.json", "data/schema_cards_targeted_working.json",
          "data/all_results.csv", "annotations/annotation_clean.csv", "annotations/my_annotation.csv",
          "results_tables/construct_analysis.csv", "results_tables/complexity_features.csv",
          "results_tables/agreement_analysis.csv",
          "outputs/consensus_results.json", "results_tables/consensus_selection.csv",
          "results_tables/memorisation_frontier.csv",
          "results_tables/wdql_construct_prevalence.csv"]:
    say(f"- `{p}` — {sha(p)}")
say()

# ── fair sets ─────────────────────────────────────────────────
say("## 1. Fair sets (working split, QLever)")
say()
if exists("data/gold_status_qlever.csv"):
    strict, lenient, cx = set(), set(), {}
    for r in csv.DictReader(open("data/gold_status_qlever.csv")):
        i = int(r["index"]); cx[i] = r["complexity"]
        if r["gold_executed"] == "True":
            lenient.add(i)
            if r["gold_result_count"] != "0":
                strict.add(i)
    say(f"- rows: {len(cx)}  |  LENIENT: {len(lenient)}  |  STRICT: {len(strict)}"
        f"  |  gold-empty: {len(lenient)-len(strict)}")
    per = collections.Counter(cx[i] for i in strict)
    say(f"- strict by complexity: {dict(per)}")
    strict_s = {str(i) for i in strict}
else:
    strict, lenient, cx = set(), set(), {}
    strict_s = set()
    say("- MISSING data/gold_status_qlever.csv")
say()

# ── metric tables ─────────────────────────────────────────────
RUNS = [("Zero-shot GPT-5.4", "results_gpt-5.4.csv"),
        ("Zero-shot Claude", "results_claude.csv"),
        ("Zero-shot Gemini", "results_gemini.csv"),
        ("Zero-shot DeepSeek", "results_deepseek.csv"),
        ("Few-shot GPT-5.4", "results_fewshot_gpt-5.4.csv"),
        ("Few-shot Claude", "results_fewshot_claude.csv"),
        ("Few-shot Gemini", "results_fewshot_gemini.csv"),
        ("Few-shot DeepSeek", "results_fewshot_deepseek.csv"),
        ("Linking (gold labels, clean)", "results_linking_clean.csv"),
        ("End-to-end (clean pools)", "results_e2e_clean.csv")]

say("## 2. Fair Jaccard, pooled and entity-level (outputs/qlever_v2/)")
say()
data, defined = {}, []
for name, f in RUNS:
    p = os.path.join("outputs/qlever_v2", f)
    if not exists(p):
        say(f"- MISSING {p}")
        continue
    rows = {int(r["index"]): r for r in csv.DictReader(open(p))}
    data[name] = rows
    defined.append({i for i, r in rows.items()
                    if i in strict and r.get("jaccard_entity") not in ("na", "", None)})

common = set.intersection(*defined) if defined else set()
say(f"- common entity-defined subset: n = {len(common)}"
    f"  ({dict(collections.Counter(cx[i] for i in common))})")
say()
say("| Run | pooled | entity | ent simple | ent medium | ent complex |")
say("|---|---|---|---|---|---|")

def mean(rows, col, subset, comp=None):
    v = [float(rows[i][col]) for i in subset
         if rows[i].get(col) not in ("na", "", None)
         and (comp is None or cx.get(i) == comp)]
    return sum(v)/len(v)*100 if v else None

for name, _ in RUNS:
    if name not in data:
        continue
    r = data[name]
    vals = [mean(r, "jaccard_pooled", common), mean(r, "jaccard_entity", common),
            mean(r, "jaccard_entity", common, "simple"),
            mean(r, "jaccard_entity", common, "medium"),
            mean(r, "jaccard_entity", common, "complex")]
    say("| " + name + " | " + " | ".join(f"{v:.1f}%" if v is not None else "—"
                                          for v in vals) + " |")
say()

# ── stage table ───────────────────────────────────────────────
say("## 3. Stage table (end-to-end, clean pools)")
say()
p = "outputs/results_e2e_clean.csv" if exists("outputs/results_e2e_clean.csv") else "outputs/qlever/results_e2e_regen.csv"
if exists(p):
    rows = list(csv.DictReader(open(p)))
    say("| Stage | simple | medium | complex | overall |")
    say("|---|---|---|---|---|")
    def pct(sub, col):
        return sum(1 for r in sub if str(r[col]) == "True")/len(sub)*100 if sub else None
    cols = [c for c in ["generated_ok", "fully_linked", "executed"]
            if rows and c in rows[0]]
    names = {"generated_ok": "Generated labelled query",
             "fully_linked": "Fully linked", "executed": "Executed"}
    for col in cols:
        label = names[col]
        vals = [pct([r for r in rows if c is None or r["complexity"] == c], col)
                for c in ["simple", "medium", "complex", None]]
        say(f"| {label} | " + " | ".join(f"{v:.1f}%" for v in vals) + " |")
    jcol = "jaccard_entity" if rows and "jaccard_entity" in rows[0] else "jaccard_new"
    vals = []
    for c in ["simple", "medium", "complex", None]:
        sub = [r for r in rows if str(r["index"]) in strict_s
               and r.get(jcol) not in ("na", "", None)
               and (c is None or r["complexity"] == c)]
        vals.append(sum(float(r[jcol]) for r in sub)/len(sub)*100 if sub else 0)
    say(f"| Strict fair Jaccard ({jcol}) | " + " | ".join(f"{v:.1f}%" for v in vals) + " |")
else:
    say(f"- MISSING {p}")
say()

# ── entity linking ────────────────────────────────────────────
say("## 4. Entity linking (same rows, same ground truth)")
say()
if exists("data/gold_links.json"):
    gold = {int(k): v for k, v in json.load(open("data/gold_links.json")).items()}
    n_ent = sum(1 for ps in gold.values() for p in ps if p[0] == "entity")
    n_prop = sum(1 for ps in gold.values() for p in ps if p[0] == "property")
    say(f"- ground truth: {len(gold)} rows, {n_ent} entity mentions, "
        f"{n_prop} property mentions")

    for cfile, cname in [("data/candidates_expanded.json", "clean union pools")]:
        if not exists(cfile):
            continue
        cand = json.load(open(cfile))
        tot = hit = 0
        for ps in gold.values():
            for kind, label, gid in ps:
                if kind != "entity":
                    continue
                tot += 1
                if gid in {c["id"] for c in cand.get(f"entity|{label}", [])}:
                    hit += 1
        say(f"- entity candidate ceiling, {cname}: {hit}/{tot} = {hit/tot*100:.1f}%")

    if exists("data/properties_clean.json"):
        pc = json.load(open("data/properties_clean.json"))
        tot = hit = 0
        for ps in gold.values():
            for kind, label, gid in ps:
                if kind != "property":
                    continue
                tot += 1
                if gid in {c["id"] for c in pc.get(f"property|{label}", [])}:
                    hit += 1
        say(f"- property candidate ceiling, clean union pools (k=7): "
            f"{hit}/{tot} = {hit/tot*100:.1f}%")

    say()
    cx_test = ({i: ex["complexity"] for i, ex in enumerate(json.load(open("data/test.json")))}
               if exists("data/test.json") else {})
    say("| Linker | mentions | P | R | F1 | F1 simple | F1 medium | F1 complex |")
    say("|---|---|---|---|---|---|---|---|")
    for pred_file, label in [("outputs/preds_reasoning_full.jsonl", "Reasoning (Opus 4.8, clean)"),
                             ("outputs/preds_qwen_full.jsonl", "Reasoning (Qwen2.5-14B)"),
                             ("outputs/preds_qwen7b_entity.jsonl", "Reasoning (Qwen2.5-7B, entity only)"),
                             ("outputs/preds_glinker_restricted_desc.jsonl", "GLiNKER large v1.0 (same candidates, descriptions)"),
                             ("outputs/preds_glinker_restricted_label.jsonl", "GLiNKER large v1.0 (same candidates, labels only)"),
                             ("outputs/preds_first_search_result.jsonl", "First search result (no model)"),
                             ("outputs/preds_elq.jsonl", "ELQ (elq_wiki_large)"),
                             ("outputs/preds_refined.jsonl", "ReFinED questions_model")]:
        if not exists(pred_file):
            say(f"| {label} | MISSING | | | |")
            continue
        preds = collections.defaultdict(dict)
        for line in open(pred_file):
            r = json.loads(line)
            preds[r["index"]][(r["kind"], r["label"])] = r["pred_id"]
        for kind in ["entity", "property"]:
            cnt = {c: [0, 0, 0] for c in ["simple", "medium", "complex", None]}
            for i, ps in gold.items():
                if i not in preds:
                    continue
                for k, lab, gid in ps:
                    if k != kind:
                        continue
                    pid = preds[i].get((k, lab), "")
                    for key in (None, cx_test.get(i)):
                        if key not in cnt:
                            continue
                        cnt[key][2] += 1
                        if pid:
                            cnt[key][1] += 1
                        if pid == gid:
                            cnt[key][0] += 1
            c, pr, g = cnt[None]
            if g == 0 or pr == 0:
                continue
            def f1(c, pr, g):
                if not pr or not g:
                    return None
                P, R = c/pr*100, c/g*100
                return 2*P*R/(P+R) if P+R else 0
            P, R = c/pr*100, c/g*100
            F = f1(c, pr, g)
            per = [f1(*cnt[k]) for k in ["simple", "medium", "complex"]]
            say(f"| {label} | {kind} | {P:.1f}% | {R:.1f}% | {F:.1f}% | "
                + " | ".join(f"{v:.1f}%" if v is not None else "—" for v in per) + " |")
else:
    say("- MISSING data/gold_links.json")
say()

# ── official split ────────────────────────────────────────────
say("## 5. Official test split (comparability experiment)")
say()
if exists("results_tables/official_comparison.csv"):
    say("- source: `official_comparison.py` (clean pools; all 370 strict-set questions "
        "count, a question without a generated query scores zero)")
    say()
    say("| Metric | simple | medium | complex | overall |")
    say("|---|---|---|---|---|")
    for r in csv.DictReader(open("results_tables/official_split_results.csv")):
        say(f"| {r['Metric']} | {r['simple']} | {r['medium']} | {r['complex']} | {r['overall']} |")
    say()
    say("| System | questions with output | pooled fair Jaccard | executed % |")
    say("|---|---|---|---|")
    for r in csv.DictReader(open("results_tables/official_comparison.csv")):
        say(f"| {r['system']} | {r['questions with output']} | {r['pooled']} | {r['executed_pct']} |")
else:
    say("- MISSING results_tables/official_comparison.csv (run official_comparison.py)")
say()

# ── 6. official-split linking ──────────────────────────────────
say("## 6. Entity linking on the official test split")
say()
if exists("data/gold_links_official.json"):
    goldo = json.load(open("data/gold_links_official.json"))
    rowso = {str(r["id"]): r for r in json.load(open("data/official_test.json"))} \
            if exists("data/official_test.json") else {}
    n_e = sum(1 for ps in goldo.values() for p in ps if p[0] == "entity")
    n_p = sum(1 for ps in goldo.values() for p in ps if p[0] == "property")
    say(f"- ground truth: {len(goldo)} rows aligned, {n_e} entity, {n_p} property mentions")
    say()
    say("| Linker | kind | P | R | F1 | F1 simple | F1 medium | F1 complex |")
    say("|---|---|---|---|---|---|---|---|")
    for pf, lab in [("outputs/preds_qwen_official.jsonl", "Reasoning (Qwen2.5-14B)"),
                    ("outputs/preds_glinker_restricted_desc_official.jsonl", "GLiNKER large v1.0 (same candidates, descriptions)"),
                    ("outputs/preds_first_search_result_official.jsonl", "First search result (no model)"),
                    ("outputs/preds_elq_official.jsonl", "ELQ (elq_wiki_large)"),
                    ("outputs/preds_refined_official.jsonl", "ReFinED questions_model")]:
        if not exists(pf):
            say(f"| {lab} | MISSING | | | |")
            continue
        pr = collections.defaultdict(dict)
        for line in open(pf):
            r = json.loads(line)
            pr[str(r["index"])][(r["kind"], r["label"])] = r["pred_id"]
        for kind in ["entity", "property"]:
            cnt = {c: [0, 0, 0] for c in ["simple", "medium", "complex", None]}
            for rid, pairs in goldo.items():
                if rid not in pr:
                    continue
                cxr = rowso.get(rid, {}).get("complexity")
                for k, lbl, gid in pairs:
                    if k != kind:
                        continue
                    pid = pr[rid].get((k, lbl), "")
                    for key in (None, cxr):
                        if key not in cnt:
                            continue
                        cnt[key][2] += 1
                        if pid:
                            cnt[key][1] += 1
                        if pid == gid:
                            cnt[key][0] += 1
            c, p_, g_ = cnt[None]
            if g_ == 0 or p_ == 0:
                continue
            def f1(c, pr_, g):
                if not pr_ or not g:
                    return None
                P, R = c/pr_*100, c/g*100
                return 2*P*R/(P+R) if P+R else 0
            P, R = c/p_*100, c/g_*100
            F = f1(c, p_, g_)
            per = [f1(*cnt[k]) for k in ["simple", "medium", "complex"]]
            say(f"| {lab} | {kind} | {P:.1f}% | {R:.1f}% | {F:.1f}% | "
                + " | ".join(f"{v:.1f}%" if v is not None else "—" for v in per) + " |")
else:
    say("- MISSING data/gold_links_official.json")
say()

# ── 7. prompt intervention arms ────────────────────────────────
say("## 7. Prompt intervention arms (open-weight disambiguation)")
say()
ARMS = [("baseline", "outputs/linked_base-qwen.csv"),
        ("idiom rules", "outputs/linked_idiom-qwen.csv"),
        ("schema evidence, verbose", "outputs/linked_grounded.csv"),
        ("schema evidence, targeted", "outputs/linked_grounded-targeted.csv")]
# arm result files are written by score_open_pipeline.py and key rows on
# "row_id"; the strict set is keyed on the same string ids.
found = False
say("| arm | pooled | entity | n |")
say("|---|---|---|---|")
for lab, f in ARMS:
    if not exists(f):
        say(f"| {lab} | MISSING | | |")
        continue
    found = True
    rws = list(csv.DictReader(open(f)))
    def m(col):
        v = [float(r[col]) for r in rws
             if str(r.get("row_id") or r.get("index") or "") in strict_s
             and r.get(col) not in ("na", "", None)]
        return sum(v)/len(v)*100 if v else None
    p_, e_ = m("jaccard_pooled"), m("jaccard_entity")
    fm = lambda x: f"{x:.1f}%" if x is not None else "—"
    say(f"| {lab} | {fm(p_)} | {fm(e_)} | {len(rws)} |")
if not found:
    say()
    say("(arm result files not present in this directory)")
say()

# ── 8. authors' baselines ──────────────────────────────────────
say("## 8. Benchmark authors' systems, rescored on this dump")
say()
if exists("outputs/results_authors_baselines.csv"):
    ab = list(csv.DictReader(open("outputs/results_authors_baselines.csv")))
    go = json.load(open("data/official_gold_results.json")) if exists("data/official_gold_results.json") else {}
    st = {rid for rid, v in go.items() if v.get("ok") and v.get("values")}
    say("| model | n | exec % | pooled | entity |")
    say("|---|---|---|---|---|")
    for mdl in sorted({r["model"] for r in ab}):
        sub = [r for r in ab if r["model"] == mdl and r["row_id"] in st]
        if not sub:
            continue
        ex = sum(1 for r in sub if str(r["executed"]) == "True")/len(sub)*100
        def mm(col):
            v = [float(r[col]) for r in sub if r[col] not in ("na", "")]
            return sum(v)/len(v)*100 if v else None
        fm = lambda x: f"{x:.1f}%" if x is not None else "—"
        say(f"| {mdl} | {len(sub)} | {ex:.1f}% | {fm(mm('jaccard_pooled'))} "
            f"| {fm(mm('jaccard_entity'))} |")
else:
    say("- MISSING outputs/results_authors_baselines.csv")
say()

# ── 9. construct usage and agreement ───────────────────────────
say("## 9. Wikidata construct usage and agreement with gold")
say()
if exists("results_tables/construct_analysis.csv"):
    blocks, cur = [], []
    for row in csv.reader(open("results_tables/construct_analysis.csv")):
        if not row or not any(row):
            if cur: blocks.append(cur); cur = []
            continue
        cur.append(row)
    if cur: blocks.append(cur)
    for b in blocks:
        title = b[0][0] if len(b[0]) == 1 else "table"
        say(f"**{title}**")
        say()
        hdr = b[1] if len(b[0]) == 1 else b[0]
        body = b[2:] if len(b[0]) == 1 else b[1:]
        say("| " + " | ".join(hdr) + " |")
        say("|" + "---|" * len(hdr))
        for r in body:
            say("| " + " | ".join(str(x) for x in r) + " |")
        say()
else:
    say("- MISSING results_tables/construct_analysis.csv")
say()

# ── 10. structural predictors of failure ───────────────────────
say("## 10. Structural features of the gold query vs achieved accuracy")
say()
if exists("results_tables/complexity_features.csv"):
    rs = list(csv.DictReader(open("results_tables/complexity_features.csv")))
    if rs:
        hdr = list(rs[0].keys())
        say("| " + " | ".join(hdr) + " |")
        say("|" + "---|" * len(hdr))
        for r in rs:
            say("| " + " | ".join(str(r[h]) for h in hdr) + " |")
else:
    say("- MISSING results_tables/complexity_features.csv")
say()

# ── 11. cross-model agreement ──────────────────────────────────
say("## 11. Cross-model agreement")
say()
if exists("results_tables/agreement_analysis.csv"):
    for row in csv.reader(open("results_tables/agreement_analysis.csv")):
        if row and any(row):
            say("- " + " | ".join(str(x) for x in row))
else:
    say("- MISSING results_tables/agreement_analysis.csv")
say()

# ── 12. significance of the prompt interventions ───────────────
say("## 12. Significance of the prompt interventions (paired, vs baseline)")
say()
sig = [f for f in ["results_tables/significance_jaccard_entity.csv",
                   "results_tables/significance_jaccard_pooled.csv"] if exists(f)]
if sig:
    for f in sig:
        say(f"**{f}**")
        say()
        rs = list(csv.DictReader(open(f)))
        if rs:
            hdr = list(rs[0].keys())
            say("| " + " | ".join(hdr) + " |")
            say("|" + "---|" * len(hdr))
            for r in rs:
                say("| " + " | ".join(str(r[h]) for h in hdr) + " |")
        say()
else:
    say("- MISSING significance tables (run significance_idiom.py)")
say()

# ── 13. error taxonomy ─────────────────────────────────────────
say("## 13. Error taxonomy")
say()
for f, lab in [("annotations/annotation_clean.csv", "clean-pool run (reported)"),
               ("annotations/my_annotation.csv", "pre-repair run (supporting)")]:
    if not exists(f):
        say(f"- MISSING {f}")
        continue
    rs = [r for r in csv.DictReader(open(f)) if r.get("error_category", "").strip()]
    if not rs:
        say(f"- {f}: no categories filled in")
        continue
    t = collections.Counter(r["error_category"] for r in rs)
    say(f"**{lab}** — {f}, n = {len(rs)}")
    say()
    say("| category | n | % |")
    say("|---|---|---|")
    for c, n in t.most_common():
        say(f"| {c} | {n} | {n/len(rs)*100:.1f} |")
    bycx = collections.defaultdict(collections.Counter)
    for r in rs:
        bycx[r["complexity"]][r["error_category"]] += 1
    comp = bycx.get("complex", collections.Counter())
    link = comp["wrong_entity"] + comp["wrong_property"] + comp["unresolved"]
    say(f"\ncomplex failures attributable to linking: {link} of {sum(comp.values())}")
    say()

# ── 14. annotation reliability ─────────────────────────────────
say("## 14. Annotation reliability")
say()
if exists("results_tables/reliability.csv"):
    for row in csv.reader(open("results_tables/reliability.csv")):
        if row and any(row):
            say("- " + " | ".join(str(x) for x in row))
else:
    say("- not run: no results_tables/reliability.csv "
        "(either complete reliability_check.py or remove the claim "
        "from the limitations section)")
say()

# ── 15. extensions ─────────────────────────
say("## 15. Extensions (tables copied verbatim from results_tables/)")
say()
for title, f in [("X5 selection strategies", "results_tables/consensus_selection.csv"),
                 ("X4 frontier memorisation", "results_tables/memorisation_frontier.csv"),
                 ("X3 WDQL construct prevalence", "results_tables/wdql_construct_prevalence.csv")]:
    say(f"**{title}** — `{f}`")
    say()
    if exists(f):
        rows = list(csv.DictReader(open(f)))
        say("| " + " | ".join(rows[0].keys()) + " |")
        say("|" + "---|" * len(rows[0]))
        for r in rows:
            say("| " + " | ".join(str(v) for v in r.values()) + " |")
    else:
        say(f"- MISSING {f}")
    say()
say("X1/X2 (idiom gating, oracle ceiling) are printed by `analysis_extension_probes.py`; "
    "X5 robustness by `consensus_robustness.py` (results_tables/consensus_robustness.txt).")
say()

# ── 16. artefact inventory ─────────────────────────────────────────────
say("## 16. Artefacts derived from these inputs (figures and tables)")
say()
say("Regenerate all three stages with `bash reproduce.sh`. Each figure also")
say("carries its source and thesis section in its PDF metadata.")
say()
for man, kind in [("results_tables/figure_manifest.csv", "figure"),
                  ("results_tables/table_manifest.csv", "table")]:
    if not exists(man):
        say(f"- MISSING {man} (run make_figures.py / make_tables.py)")
        continue
    rs = list(csv.DictReader(open(man)))
    say(f"**{len(rs)} {kind}s** — `{man}`")
    say()
    if kind == "figure":
        say("| figure | §  | sha256 | built from |")
        say("|---|---|---|---|")
        for r in rs:
            say(f"| `{r['figure']}` | {r['thesis_section']} | "
                f"{sha('thesis_latex/figures/' + r['figure'], 8)} | {r['source_data']} |")
    else:
        say("| table | label | sha256 | built from |")
        say("|---|---|---|---|")
        for r in rs:
            say(f"| `{r['table']}` | `{r['label']}` | "
                f"{sha('thesis_latex/tables/' + r['table'], 8)} | {r['source_data']} |")
    say()

say("---")
say("Regenerate with: `python3 verify_all.py`.")

open("VERIFICATION_REPORT.md", "w").write("\n".join(OUT) + "\n")
dated = f"VERIFICATION_REPORT_{date.today().isoformat()}.md"
open(dated, "w").write("\n".join(OUT) + "\n")
print(f"\nwritten: VERIFICATION_REPORT.md and {dated}")
