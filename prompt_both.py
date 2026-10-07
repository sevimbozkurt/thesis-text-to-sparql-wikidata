"""Gold identifiers AND gold constructs, so their contributions can be
separated instead of confounded with oracle strength.

Usage:
  python3 prompt_both.py dry-run
  python3 prompt_both.py submit-gen | status | fetch-gen
"""
import json, sys

import prompt_idioms as PI
from prompt_constrained import constraint_for, vocabulary
from prompt_construct_profile import hint_for, gold_of

PI.GEN   = "both_generated.json"
PI.POOL  = "both_candidates.json"
PI.MAPF  = "both_disamb_map.json"
PI.STATE = "both_state.json"
PI.OUT   = "results_e2e_both.csv"


def system_for(row):
    """Base prompt + the SAME two blocks the single-factor arms used, verbatim.

    Reusing the exact functions matters: if either block were reworded here the
    2x2 would no longer be a clean factorial, and the interaction term would mix
    a wording change with the factor it is meant to isolate.
    """
    return PI.BASE_SYSTEM + constraint_for(row) + hint_for(gold_of(row))


def submit_gen():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("data/test.json"))
    done = PI.load(PI.GEN, {})
    todo = [(i, r) for i, r in enumerate(test) if str(i) not in done]
    print(f"{len(test)} rows | already generated {len(done)} | to submit {len(todo)}")
    if not todo:
        return
    reqs = [Request(custom_id=f"bo-{i}",
                    params=MessageCreateParamsNonStreaming(
                        model=PI.MODEL, max_tokens=1024, system=system_for(r),
                        messages=[{"role": "user",
                                   "content": f"Question: {r['instruction']}"}]))
            for i, r in todo]
    b = PI.client().messages.batches.create(requests=reqs)
    st = PI.load(PI.STATE, {}); st["gen"] = b.id; PI.save(PI.STATE, st)
    print(f"batch id: {b.id}")


def fetch_gen():
    st = PI.load(PI.STATE, {})
    fn = PI._download(st["gen"], f"both_gen_{st['gen']}.jsonl")
    gen = PI.load(PI.GEN, {}); ok = failed = 0
    for line in open(fn):
        e = json.loads(line); cid = e["custom_id"]
        if not cid.startswith("bo-"):
            raise SystemExit(f"unexpected custom_id {cid!r} — wrong batch?")
        i = cid.split("bo-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[i] = PI.strip_fences(PI.text_of(e)); ok += 1
        else:
            gen.setdefault(i, ""); failed += 1
    PI.save(PI.GEN, gen)
    print(f"collected {ok} succeeded, {failed} failed; {PI.GEN} holds {len(gen)} rows")
    print(f"empty generations: {sum(1 for v in gen.values() if not v.strip())}")


def dry_run():
    test = json.load(open("data/test.json"))
    n_in = sum(len(system_for(r) + f"Question: {r['instruction']}") / 4 for r in test)
    n = len(test); out_tok = n * 220
    cost = n_in / 1e6 * 5.00 * 0.5 + out_tok / 1e6 * 25.00 * 0.5
    print("=" * 66)
    print(f"X15 DRY RUN — both oracles, {n} rows, no network")
    print("=" * 66)
    print(f"  input tokens ~{n_in:,.0f} ({n_in/n:,.0f}/row)")
    print(f"  generation cost  ${cost:,.2f}   disambiguation free (GPU)")
    r = next(x for x in test if len(vocabulary(x)[1]) >= 2)
    print(f"\nexample prompt suffix for: {r['instruction'][:80]}")
    for line in (constraint_for(r) + hint_for(gold_of(r))).strip().splitlines():
        print("   " + line)


if __name__ == "__main__":
    def _refuse():
        sys.exit("REFUSED. Disambiguate on the GPU:\n"
                 "  python disamb_any.py --gen both_generated.json "
                 "--split working --tag both\n")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"dry-run": dry_run, "submit-gen": submit_gen, "fetch-gen": fetch_gen,
     "candidates": PI.candidates, "status": PI.status,
     "submit-disamb": _refuse, "fetch-disamb": _refuse}.get(
        cmd, lambda: sys.exit("usage: prompt_both.py dry-run|submit-gen|status|"
                              "fetch-gen|candidates"))()
