"""rekey_to_default.py — Re-key cached batch artifacts to the `default` config.

Usage:  python3 rekey_to_default.py
"""

import json, os, re, shutil

def n(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()

old_rows = json.load(open("official_test_with_limit.json.bak"))
new_rows = json.load(open("official_test.json"))

old_id2instr = {str(r["id"]): n(r["instruction"]) for r in old_rows}
instr2new_id = {n(r["instruction"]): str(r["id"]) for r in new_rows}

print(f"old config rows: {len(old_rows)} | new config rows: {len(new_rows)}")
overlap = sum(1 for i in old_id2instr.values() if i in instr2new_id)
print(f"questions present in both configs: {overlap}")

for fname in ["batch_generated.json", "batch_candidates.json",
              "batch_disambiguated.json"]:
    if not os.path.exists(fname):
        print(f"  skip {fname} (not found)")
        continue
    data = json.load(open(fname))
    shutil.copy(fname, fname.replace(".json", ".with_limit.bak"))
    out, lost = {}, 0
    for old_id, payload in data.items():
        instr = old_id2instr.get(str(old_id))
        new_id = instr2new_id.get(instr) if instr else None
        if new_id:
            out[new_id] = payload
        else:
            lost += 1
    json.dump(out, open(fname, "w"), indent=1)
    print(f"  {fname}: {len(out)} re-keyed, {lost} dropped "
          f"(question not in new config)")

# how many new rows still need generation?
gen = json.load(open("batch_generated.json"))
missing = [r for r in new_rows if str(r["id"]) not in gen or not gen[str(r["id"])]]
print(f"\nrows still needing generation: {len(missing)} of {len(new_rows)}")
if missing:
    print("run:  python3 run_official_batch.py submit-gen")
    print("      (it will only submit the missing rows)")
else:
    print("nothing to regenerate — go straight to:")
    print("  rm -f official_gold_results.json results_official_e2e.csv")
    print("  python3 run_official_batch.py finalize")
