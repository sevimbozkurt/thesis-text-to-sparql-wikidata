"""

Usage:
  python3 prompt_construct_profile.py dry-run
  python3 prompt_construct_profile.py submit-gen      # costs money
"""
import json, os, re, sys

import prompt_idioms as PI            # reuse the arm's machinery verbatim
from construct_analysis import PATTERNS, uses

# --- redirect every artefact so this arm cannot overwrite the idiom arm -------
PI.GEN   = "profile_generated.json"
PI.POOL  = "profile_candidates.json"
PI.MAPF  = "profile_disamb_map.json"
PI.STATE = "profile_state.json"
PI.OUT   = "results_e2e_profile.csv"

# Constructs worth naming. LIMIT/OPTIONAL/FILTER are excluded: they are general
# SPARQL, models already use them at near-gold rates, and
# naming them would make the hint a summary of the query rather than of its
# Wikidata-specific shape.
PROFILE_CONSTRUCTS = {
    "subclass closure (P279*)":
        "the answer set includes members of SUBCLASSES, so you need transitive "
        "subclass closure (wdt:[property:instance of]/wdt:[property:subclass of]*), "
        "not a direct instance-of edge",
    "statement node (p:)":
        "you need the STATEMENT NODE form (p:[property:X] then ps:[property:X]), "
        "not the direct wdt: shortcut",
    "qualifier (pq:)":
        "the question depends on a QUALIFIER (a date, role, rank or applies-to "
        "detail) hanging off the statement, reachable only via p:/pq:",
    "value node (psv:)":
        "a quantity must be read through its NORMALISED VALUE NODE (psv:) so that "
        "units are comparable, not as the bare wdt: number",
    "aggregation (GROUP BY)":
        "the answer requires AGGREGATION (COUNT/SUM/AVG with GROUP BY)",
    "alternation (VALUES/UNION)":
        "the question ranges over several alternatives, needing VALUES or UNION",
    "property path (/ or |)":
        "the answer needs a PROPERTY PATH (a chain with / or an alternative with |)",
}

HINT_HEAD = """
For this specific question, the reference query is known to require the
following. Use them. Do not add Wikidata-specific constructs beyond these.
"""
HINT_NONE = """
For this specific question, the reference query needs none of Wikidata's
reification or hierarchy constructs: a direct wdt: formulation is correct.
Do not introduce statement nodes, qualifiers, value nodes or subclass closure.
"""


def profile(gold_query):
    """Which named constructs does this reference query use?"""
    return [n for n in PROFILE_CONSTRUCTS if uses(gold_query, n, labelled=False)]


def hint_for(gold_query):
    names = profile(gold_query)
    if not names:
        return HINT_NONE
    lines = "".join(f"  - {PROFILE_CONSTRUCTS[n]}\n" for n in names)
    return HINT_HEAD + lines


def gold_of(row):
    """The reference query, in identifier form. Fail loudly if absent: an empty
    gold query yields an empty profile, which would look exactly like a valid
    'this question needs no idiom' hint and silently void the experiment."""
    q = row.get("query") or row.get("sparql_query") or ""
    if not q.strip():
        raise SystemExit(f"row {row.get('id')} has no reference query — "
                         f"fields present: {sorted(row)}")
    return q


def system_for(row):
    return PI.BASE_SYSTEM + hint_for(gold_of(row))


# --- generation: same call shape as PI.submit_gen, different system prompt ----
def submit_gen():
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    test = json.load(open("data/test.json"))
    done = PI.load(PI.GEN, {})
    todo = [(i, r) for i, r in enumerate(test) if str(i) not in done]
    print(f"{len(test)} rows | already generated {len(done)} | to submit {len(todo)}")
    if not todo:
        return
    reqs = [Request(custom_id=f"cp-{i}",
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
    """Mirror of PI.fetch_gen, but parsing this arm's custom_id prefix.

    PI.fetch_gen hardcodes the idiom arm's "ig-" prefix; this arm submits "cp-".
    Reusing it raised IndexError on every row. Kept as a thin local override so
    the rest of the machinery still comes from prompt_idioms.py unchanged.
    """
    st = PI.load(PI.STATE, {})
    fn = PI._download(st["gen"], f"profile_gen_{st['gen']}.jsonl")
    gen = PI.load(PI.GEN, {})
    ok = failed = 0
    for line in open(fn):
        e = json.loads(line)
        cid = e["custom_id"]
        if not cid.startswith("cp-"):
            raise SystemExit(f"unexpected custom_id {cid!r} — wrong batch?")
        i = cid.split("cp-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[i] = PI.strip_fences(PI.text_of(e)); ok += 1
        else:
            gen.setdefault(i, ""); failed += 1
    PI.save(PI.GEN, gen)
    print(f"collected {ok} succeeded, {failed} failed; "
          f"{PI.GEN} holds {len(gen)} rows")
    empty = sum(1 for v in gen.values() if not v.strip())
    print(f"empty generations: {empty}")


# --- dry run: exact cost, no network -----------------------------------------
# Opus 4.8 list price, halved for the Batch API.
IN_PER_MTOK, OUT_PER_MTOK, BATCH = 5.00, 25.00, 0.50


def dry_run():
    test = json.load(open("data/test.json"))
    try:
        from anthropic import Anthropic
        enc = None
    except ImportError:
        enc = None

    n_sys = n_usr = 0
    dist = {}
    examples = []
    for i, r in enumerate(test):
        gold = gold_of(r)
        names = tuple(sorted(profile(gold)))
        dist[names] = dist.get(names, 0) + 1
        s, u = system_for(r), f"Question: {r['instruction']}"
        # ~4 chars per token is the standard rough estimate; good enough to
        # decide whether to spend, and deliberately rounded UP below.
        n_sys += len(s) / 4
        n_usr += len(u) / 4
        if len(examples) < 3 and names:
            examples.append((r["instruction"][:90], hint_for(gold).strip()))

    n = len(test)
    in_tok = n_sys + n_usr
    out_tok = n * 220           # observed mean generated-query length in this repo
    cost_in = in_tok / 1e6 * IN_PER_MTOK * BATCH
    cost_out = out_tok / 1e6 * OUT_PER_MTOK * BATCH

    print("=" * 68)
    print(f"X10 DRY RUN — construct-profile hint, {n} rows, no network used")
    print("=" * 68)
    print(f"  input tokens  ~{in_tok:,.0f}   ({n_sys/n:,.0f} system + "
          f"{n_usr/n:,.0f} user per row)")
    print(f"  output tokens ~{out_tok:,.0f}   (220/row, observed mean)")
    print(f"\n  generation cost   ${cost_in + cost_out:,.2f}   (Batch API, 50% off)")
    print(f"  disambiguation    free — disamb_any.py on the GPU server, which is")
    print(f"                    how the four reported arms were linked (Qwen).")
    print(f"                    Do NOT use prompt_idioms.submit_disamb: that API")
    print(f"                    path was never run for the reported arms, and")
    print(f"                    using it would change the disambiguation backbone.")
    print(f"  execution/scoring free (QLever)")
    print(f"\n  TOTAL to answer the 'when vs how' question: "
          f"${cost_in + cost_out:,.2f}  (generation only; "
          f"disambiguation is free on the GPU)")

    print("\nprofile distribution across the split:")
    for names, c in sorted(dist.items(), key=lambda kv: -kv[1]):
        label = ", ".join(n_.split(" (")[0] for n_ in names) if names else \
                "(no idiom — negative control)"
        print(f"  {c:4d}  {label}")

    print("\nexample prompts (system suffix only):")
    for q, h in examples:
        print(f"\n  Q: {q}")
        for line in h.splitlines():
            print(f"     {line}")

    print("\nSanity checks before spending:")
    print("  - the hint must never contain the reference query, only its shape")
    print("  - rows with no idiom get an explicit negative instruction, so the")
    print("    arm cannot win merely by using idioms more often everywhere")
    print("  - compare against the BASELINE arm (outputs/results_e2e.csv), not the idiom arm")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    def _refuse_disamb():
        sys.exit(
            "REFUSED. Do not disambiguate this arm through the Batch API.\n\n"
            "The reported prompt arms were disambiguated by\n"
            "disamb_any.py on the GPU server with an open-weight backbone --\n"
            "'Claude gen, Qwen link'. prompt_idioms.py:submit_disamb exists but\n"
            "was never run for them (idiom_state.json has no 'disamb' id).\n\n"
            "Linking this arm with claude-opus-4-8 would give it a different\n"
            "disambiguation backbone from the arms it is compared against, which\n"
            "is the confound X12 was run to exclude. It would also cost ~$7 to\n"
            "make the result worse.\n\n"
            "Instead, on the GPU server:\n"
            "  python disamb_any.py --gen profile_generated.json "
            "--split working --tag profile\n")

    {"dry-run": dry_run, "submit-gen": submit_gen,
     "fetch-gen": fetch_gen, "candidates": PI.candidates,
     "submit-disamb": _refuse_disamb, "fetch-disamb": _refuse_disamb,
     "status": PI.status, "score": PI.score}.get(
        cmd, lambda: sys.exit("usage: prompt_construct_profile.py dry-run|submit-gen|"
                              "status|fetch-gen|candidates|score\n"
                              "  (disambiguation runs on the GPU via disamb_any.py)"))()
