"""consensus_execute.py — Extension B, stage 1: re-execute the cached queries
of every existing run on QLever and store their RESULT SETS (not just
Jaccard), so that selection strategies over multiple generations can be
evaluated offline without any new LLM call.

Usage: python3 consensus_execute.py            (~1 h at the default delay)
"""
import csv, json, os, sys, time
from endpoint import run_sparql

CAP = 20000
OUT = "consensus_results.json"
RUNS = {"zs-gpt":     ("qlever_v2/results_gpt-5.4.csv", "generated_query", "index"),
        "zs-claude":  ("qlever_v2/results_claude.csv", "generated_query", "index"),
        "zs-gemini":  ("qlever_v2/results_gemini.csv", "generated_query", "index"),
        "zs-deepseek": ("qlever_v2/results_deepseek.csv", "generated_query", "index"),
        "fs-claude":  ("qlever_v2/results_fewshot_claude.csv", "generated_query", "index"),
        "e2e-clean":  ("qlever_v2/results_e2e_clean.csv", "linked_query", "index"),
        "arm-base":   ("linked_base-qwen.json", "linked_query", None),
        "arm-idiom":  ("linked_idiom-qwen.json", "linked_query", None)}

strict = {r["index"] for r in csv.DictReader(open("gold_status_qlever.csv"))
          if r["gold_executed"] == "True" and r["gold_result_count"] != "0"}

def load_queries(path, qcol, icol):
    if path.endswith(".json"):
        return {k: v.get(qcol, "") for k, v in json.load(open(path)).items()}
    return {r[icol]: r[qcol] for r in csv.DictReader(open(path))}

res = json.load(open(OUT)) if os.path.exists(OUT) else {}
todo = []
for run, (path, qcol, icol) in RUNS.items():
    res.setdefault(run, {})
    for k, q in load_queries(path, qcol, icol).items():
        if k in strict and k not in res[run]:
            todo.append((run, k, q))
print(f"{len(todo)} queries to execute; {sum(len(v) for v in res.values())} already cached", flush=True)

t0 = time.time()
for n, (run, k, q) in enumerate(todo, 1):
    if not q or "[entity:" in q or "[property:" in q:
        res[run][k] = {"ok": False, "values": [], "err": "unlinked_or_empty", "n": 0}
    else:
        ok, vals, err = run_sparql(q)
        vals = sorted(vals) if vals else []
        rec = {"ok": bool(ok), "n": len(vals), "err": (err or "")[:200]}
        rec["values"] = vals[:CAP]
        rec["truncated"] = len(vals) > CAP
        res[run][k] = rec
    if n % 25 == 0 or n == len(todo):
        json.dump(res, open(OUT, "w"))
        el = time.time() - t0
        print(f"{n}/{len(todo)}  {el/60:.1f} min elapsed, ~{el/n*(len(todo)-n)/60:.0f} min left", flush=True)
print("done:", OUT)
