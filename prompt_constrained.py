"""

Usage:
  python3 prompt_constrained.py dry-run
  python3 prompt_constrained.py submit-gen
  python3 prompt_constrained.py status | fetch-gen | candidates
"""
import json, re, sys

import prompt_idioms as PI

PI.GEN   = "constrained_generated.json"
PI.POOL  = "constrained_candidates.json"
PI.MAPF  = "constrained_disamb_map.json"
PI.STATE = "constrained_state.json"
PI.OUT   = "results_e2e_constrained.csv"

ENT_RE  = re.compile(r"\[entity:([^\]]+)\]")
PROP_RE = re.compile(r"\[property:([^\]]+)\]")


def vocabulary(row):
    """The closed vocabulary: exactly the entities and properties the reference
    query uses, taken from its label-form variant. Order preserved, duplicates
    removed, so the list reads deterministically."""
    ann = row.get("annotated") or ""
    if not ann.strip():
        raise SystemExit(f"row {row.get('id')} has no annotated reference query")
    def uniq(xs):
        seen, out = set(), []
        for x in xs:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    return uniq(ENT_RE.findall(ann)), uniq(PROP_RE.findall(ann))


def constraint_for(row):
    ents, props = vocabulary(row)
    if not ents and not props:
        return ("\nNo entity or property restriction applies to this question.\n")
    lines = ["\nRESTRICTION FOR THIS QUESTION. You may use ONLY the entities and",
             "properties listed below. Any entity or property not on this list is",
             "forbidden. The list is complete: everything the query needs is here.",
             ""]
    if ents:
        lines.append("Permitted entities:")
        lines += [f"  - wd:[entity:{e}]" for e in ents]
    if props:
        lines.append("Permitted properties:")
        lines += [f"  - [property:{p}]  (use with wdt:, or with p:/ps:/pq:/psv: "
                  f"if the question needs the statement, a qualifier or a "
                  f"normalised value)" for p in props]
    lines += ["",
              "Choose from this list only. Do not introduce any other property,",
              "and do not substitute a property you consider more appropriate.",
              ""]
    return "\n".join(lines)


def system_for(row):
    return PI.BASE_SYSTEM + constraint_for(row)


def submit_gen():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("test.json"))
    done = PI.load(PI.GEN, {})
    todo = [(i, r) for i, r in enumerate(test) if str(i) not in done]
    print(f"{len(test)} rows | already generated {len(done)} | to submit {len(todo)}")
    if not todo:
        return
    reqs = [Request(custom_id=f"cn-{i}",
                    params=MessageCreateParamsNonStreaming(
                        model=PI.MODEL, max_tokens=1024,
                        system=system_for(r),
                        messages=[{"role": "user",
                                   "content": f"Question: {r['instruction']}"}]))
            for i, r in todo]
    b = PI.client().messages.batches.create(requests=reqs)
    st = PI.load(PI.STATE, {}); st["gen"] = b.id; PI.save(PI.STATE, st)
    print(f"batch id: {b.id}")


def fetch_gen():
    st = PI.load(PI.STATE, {})
    fn = PI._download(st["gen"], f"constrained_gen_{st['gen']}.jsonl")
    gen = PI.load(PI.GEN, {})
    ok = failed = 0
    for line in open(fn):
        e = json.loads(line)
        cid = e["custom_id"]
        if not cid.startswith("cn-"):
            raise SystemExit(f"unexpected custom_id {cid!r} — wrong batch?")
        i = cid.split("cn-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[i] = PI.strip_fences(PI.text_of(e)); ok += 1
        else:
            gen.setdefault(i, ""); failed += 1
    PI.save(PI.GEN, gen)
    print(f"collected {ok} succeeded, {failed} failed; {PI.GEN} holds {len(gen)} rows")
    print(f"empty generations: {sum(1 for v in gen.values() if not v.strip())}")


IN_PER_MTOK, OUT_PER_MTOK, BATCH = 5.00, 25.00, 0.50


def dry_run():
    test = json.load(open("test.json"))
    n_in = 0
    sizes = []
    for r in test:
        s = system_for(r) + f"Question: {r['instruction']}"
        n_in += len(s) / 4
        e, p = vocabulary(r)
        sizes.append(len(e) + len(p))
    n = len(test)
    out_tok = n * 220
    cost = n_in / 1e6 * IN_PER_MTOK * BATCH + out_tok / 1e6 * OUT_PER_MTOK * BATCH
    print("=" * 70)
    print(f"X14 DRY RUN — constrained vocabulary, {n} rows, no network")
    print("=" * 70)
    print(f"  input tokens  ~{n_in:,.0f}   ({n_in/n:,.0f}/row)")
    print(f"  output tokens ~{out_tok:,.0f}")
    print(f"  generation cost  ${cost:,.2f}  (Batch API, 50% off)")
    print(f"  disambiguation   free, on the GPU via disamb_any.py")
    print(f"\n  vocabulary size: mean {sum(sizes)/len(sizes):.1f} items/question, "
          f"max {max(sizes)}, empty on {sum(1 for s in sizes if s==0)} rows")
    print("\nexample prompt suffix:")
    for r in test:
        e, p = vocabulary(r)
        if len(p) >= 2 and e:
            print(f"\n  Q: {r['instruction'][:88]}")
            for line in constraint_for(r).strip().splitlines():
                print(f"     {line}")
            break
    print("\nContrast being measured, against results already in the thesis:")
    print("  enumerative grounding  -> 38% label overlap with baseline, -14.7pp")
    print("  idiom guidance         -> 73% label overlap with baseline,  +3.9pp")
    print("  THIS ARM               -> overlap and delta are the measurement")


if __name__ == "__main__":
    def _refuse():
        sys.exit("REFUSED. Disambiguate on the GPU:\n"
                 "  python disamb_any.py --gen constrained_generated.json "
                 "--split working --tag constrained\n")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"dry-run": dry_run, "submit-gen": submit_gen, "fetch-gen": fetch_gen,
     "candidates": PI.candidates, "status": PI.status,
     "submit-disamb": _refuse, "fetch-disamb": _refuse}.get(
        cmd, lambda: sys.exit("usage: prompt_constrained.py dry-run|submit-gen|"
                              "status|fetch-gen|candidates"))()
