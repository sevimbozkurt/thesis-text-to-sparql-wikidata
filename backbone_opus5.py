"""

Usage:
  python3 backbone_opus5.py dry-run | submit-gen | status | fetch-gen | candidates
"""
import json, sys

import prompt_idioms as PI

MODEL = "claude-opus-5"          # the only thing that differs from the baseline arm
PI.GEN   = "opus5_generated.json"
PI.POOL  = "opus5_candidates.json"
PI.MAPF  = "opus5_disamb_map.json"
PI.STATE = "opus5_state.json"
PI.OUT   = "results_e2e_opus5.csv"


def submit_gen():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("test.json"))
    done = PI.load(PI.GEN, {})
    todo = [(i, r) for i, r in enumerate(test) if str(i) not in done]
    print(f"model: {MODEL}  (baseline arm used {PI.MODEL})")
    print(f"{len(test)} rows | already generated {len(done)} | to submit {len(todo)}")
    if not todo:
        return
    reqs = [Request(custom_id=f"o5-{i}",
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=1024,
                        system=PI.BASE_SYSTEM,          # identical to the baseline arm
                        messages=[{"role": "user",
                                   "content": f"Question: {r['instruction']}"}]))
            for i, r in todo]
    b = PI.client().messages.batches.create(requests=reqs)
    st = PI.load(PI.STATE, {}); st["gen"] = b.id; PI.save(PI.STATE, st)
    print(f"batch id: {b.id}")


def fetch_gen():
    st = PI.load(PI.STATE, {})
    fn = PI._download(st["gen"], f"opus5_gen_{st['gen']}.jsonl")
    gen = PI.load(PI.GEN, {}); ok = failed = 0
    for line in open(fn):
        e = json.loads(line); cid = e["custom_id"]
        if not cid.startswith("o5-"):
            raise SystemExit(f"unexpected custom_id {cid!r} — wrong batch?")
        i = cid.split("o5-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[i] = PI.strip_fences(PI.text_of(e)); ok += 1
        else:
            gen.setdefault(i, ""); failed += 1
    PI.save(PI.GEN, gen)
    print(f"collected {ok} succeeded, {failed} failed; {PI.GEN} holds {len(gen)} rows")
    print(f"empty generations: {sum(1 for v in gen.values() if not v.strip())}")


def dry_run():
    test = json.load(open("test.json"))
    n = len(test)
    inp = sum(len(PI.BASE_SYSTEM + f"Question: {r['instruction']}") / 4 for r in test)
    cost = inp / 1e6 * 5.00 * 0.5 + n * 220 / 1e6 * 25.00 * 0.5
    print(f"X16 dry run — {MODEL}, {n} rows, ~${cost:.2f} (Batch API)")
    print(f"prompt is PI.BASE_SYSTEM verbatim, no thinking, max_tokens 1024")
    print(f"disambiguation: Qwen2.5-14B on the GPU, as every other arm")


if __name__ == "__main__":
    def _refuse():
        sys.exit("REFUSED. Disambiguate on the GPU:\n"
                 "  python disamb_any.py --gen opus5_generated.json "
                 "--split working --tag opus5\n")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"dry-run": dry_run, "submit-gen": submit_gen, "fetch-gen": fetch_gen,
     "candidates": PI.candidates, "status": PI.status,
     "submit-disamb": _refuse, "fetch-disamb": _refuse}.get(
        cmd, lambda: sys.exit("usage: backbone_opus5.py dry-run|submit-gen|status|"
                              "fetch-gen|candidates"))()
