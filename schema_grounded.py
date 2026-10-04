"""schema_grounded.py — Schema-grounded query generation. STAGE 1: build the
schema evidence (runs on the laptop, against QLever; free).

Usage:
  python3 schema_grounded.py --split working   [--limit N]
  python3 schema_grounded.py --split official
Then scp schema_cards.json to the server and run stage 2 (generation).
"""

import argparse, json, os, re, sys, time
# endpoint.py exposes run_sparql(query) -> (ok, values:set, err)
from endpoint import run_sparql

MAX_PROPS = 12          # properties listed per question
MAX_ENTS  = 4           # entities probed per question

def load(p, d=None):
    if not os.path.exists(p):
        if d is None:
            sys.exit(f"missing input: {p}")
        return d
    return json.load(open(p))

def save(p, o):
    json.dump(o, open(p, "w"), indent=1)


# ── SPARQL probes ──────────────────────────────────────────────
def probe_properties(qid):
    """Which properties does this entity carry, as direct claims?"""
    q = f"""SELECT ?p (COUNT(*) AS ?n) WHERE {{
  wd:{qid} ?pd ?v .
  ?p wikibase:directClaim ?pd .
}} GROUP BY ?p ORDER BY DESC(?n) LIMIT {MAX_PROPS}"""
    ok, vals, err = run_sparql(q)
    return sorted({v for v in vals if re.match(r'^P\d+$', v)}) if ok else []

def probe_qualifiers(qid):
    """Which of this entity's statements actually carry qualifiers?"""
    q = f"""SELECT DISTINCT ?p ?q WHERE {{
  wd:{qid} ?ps ?st .
  ?p wikibase:claim ?ps .
  ?st ?pq ?qv .
  ?q wikibase:qualifier ?pq .
}} LIMIT 25"""
    ok, vals, err = run_sparql(q)
    return sorted({v for v in vals if re.match(r'^P\d+$', v)}) if ok else []

def probe_is_class(qid):
    """Does anything declare this entity as its superclass? If so, a query
    about the class probably needs P31/P279* rather than a direct P31."""
    q = f"""SELECT ?sub WHERE {{ ?sub wdt:P279 wd:{qid} }} LIMIT 1"""
    ok, vals, err = run_sparql(q)
    return ok and bool(vals)

def probe_quantity(pid):
    """Are this property's values quantities with units? If so the query may
    need the statement value node (psv:) rather than a direct claim."""
    q = f"""SELECT ?u WHERE {{ ?s p:{pid}/psv:{pid} ?vn . ?vn wikibase:quantityUnit ?u }} LIMIT 1"""
    ok, vals, err = run_sparql(q)
    return ok and bool(vals)

def probe_prop_qualifiers(pid):
    """Which qualifiers are actually used on statements of this property?
    Property-level evidence, so that questions mentioning only properties
    (about half of this benchmark) also receive grounding."""
    q = f"""SELECT DISTINCT ?q WHERE {{
  ?s p:{pid} ?st .
  ?st ?pq ?v .
  ?q wikibase:qualifier ?pq .
}} LIMIT 8"""
    ok, vals, err = run_sparql(q)
    return sorted({v for v in vals if re.match(r'^P\d+$', v)}) if ok else []

def probe_prop_class_range(pid):
    """Do this property's values tend to be classes with subclasses? If so, a
    question filtering on such a value usually needs P279* closure."""
    q = f"""SELECT ?sub WHERE {{
  ?s wdt:{pid} ?v .
  ?sub wdt:P279 ?v .
}} LIMIT 1"""
    ok, vals, err = run_sparql(q)
    return ok and bool(vals)

def label_of(qid):
    q = f"""SELECT ?l WHERE {{ wd:{qid} rdfs:label ?l . FILTER(LANG(?l)="en") }} LIMIT 1"""
    ok, vals, err = run_sparql(q)
    return sorted(vals)[0] if ok and vals else qid


def build_card_targeted(entities, properties, prop_cache, ent_cache):
    """Targeted variant: evidence ONLY for the properties/entities the
    question actually links to (gold mentions), no enumeration of everything
    an entity happens to carry. Tests whether the full-listing version failed
    from information overload/distraction rather than from the concept of
    grounding itself."""
    lines = []
    for qid in entities[:MAX_ENTS]:
        info = ent_cache.get(qid)
        if info and info.get("is_class"):
            lines.append(f"{qid} ({info['label']}) is a class with subclasses: "
                         f"a question about it usually means the class and "
                         f"everything below it (wdt:[property:instance of]/"
                         f"wdt:[property:subclass of]*).")
    seen = set()
    for pid in properties[:MAX_PROPS]:
        info = prop_cache.get(pid)
        if not info or pid in seen:
            continue
        seen.add(pid)
        label = info.get("label", pid)
        bits = []
        if info.get("qualifiers"):
            bits.append("if the question asks for something beyond the plain "
                        "value (e.g. a date, role or extra detail attached to "
                        "this fact), it is recorded as a QUALIFIER and needs "
                        "p:[property:" + label + "] / pq:[property:...], not "
                        "wdt:[property:" + label + "] alone")
        if info.get("quantity"):
            bits.append("its value is a QUANTITY with a unit; if the unit or "
                        "precision matters, use p:/psv: to reach the value node")
        if info.get("class_range"):
            bits.append("its value is itself a class; if the question means "
                        "the value or anything below it, add "
                        "wdt:[property:subclass of]* on the value")
        if bits:
            lines.append(f"{pid} ({label}): " + "; ".join(bits) + ".")
    return "\n".join(lines)


def build_card(entities, properties, prop_cache, ent_cache):
    """Compose the compact evidence text placed in the generation prompt.
    Entity evidence is included when the question mentions entities; property
    evidence is always included, so property-only questions are covered too."""
    lines = []
    for qid in entities[:MAX_ENTS]:
        info = ent_cache.get(qid)
        if not info:
            continue
        head = f"{qid} ({info['label']})"
        if info["is_class"]:
            head += " — this is a class with subclasses; a question about it " \
                    "usually means the class and everything below it"
        lines.append(head)
        if info["properties"]:
            named = ", ".join(f"{p} ({prop_cache.get(p, {}).get('label', p)})"
                              for p in info["properties"][:MAX_PROPS])
            lines.append(f"  properties in use: {named}")
        if info["qualified"]:
            named = ", ".join(f"{p} ({prop_cache.get(p, {}).get('label', p)})"
                              for p in info["qualified"][:8])
            lines.append(f"  statements with qualifiers (need p:/pq: to read "
                         f"the qualifier): {named}")
        quants = [p for p in info["properties"]
                  if prop_cache.get(p, {}).get("quantity")]
        if quants:
            lines.append(f"  quantity-valued (unit lives on the value node, "
                         f"need p:/psv:): {', '.join(quants[:6])}")

    prop_lines = []
    for pid in properties[:MAX_PROPS]:
        info = prop_cache.get(pid)
        if not info:
            continue
        bits = []
        if info.get("qualifiers"):
            named = ", ".join(f"{q} ({prop_cache.get(q, {}).get('label', q)})"
                              for q in info["qualifiers"][:5])
            bits.append(f"used with qualifiers {named}, reachable only through "
                        f"p:/pq:")
        if info.get("quantity"):
            bits.append("quantity-valued; the unit sits on the statement value "
                        "node, reachable through p:/psv:")
        if info.get("class_range"):
            bits.append("its values are classes with subclasses, so filtering "
                        "on one usually needs P279* closure")
        if bits:
            prop_lines.append(f"{pid} ({info.get('label', pid)}): " + "; ".join(bits))
    if prop_lines:
        lines.append("properties this question refers to:")
        lines += ["  " + l for l in prop_lines]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["working", "official"], default="working")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    if a.split == "working":
        gold = {str(k): v for k, v in load("gold_links.json").items()}
    else:
        gold = load("gold_links_official.json")

    out_file = f"schema_cards_{a.split}.json"
    cards = load(out_file, {})
    out_file_t = f"schema_cards_targeted_{a.split}.json"
    cards_targeted = load(out_file_t, {})
    ent_cache = load(f"schema_entities_{a.split}.json", {})
    prop_cache = load("schema_properties.json", {})

    rows = [r for r in gold if r not in cards or r not in cards_targeted]
    if a.limit:
        rows = rows[:a.limit]
    print(f"{a.split}: {len(gold)} rows with ground truth, {len(rows)} to build")

    for n, rid in enumerate(rows):
        ents = [g for k, l, g in gold[rid] if k == "entity"][:MAX_ENTS]
        props = [g for k, l, g in gold[rid] if k == "property"]

        for qid in ents:
            if qid in ent_cache:
                continue
            ent_cache[qid] = {
                "label": label_of(qid),
                "properties": probe_properties(qid),
                "qualified": probe_qualifiers(qid),
                "is_class": probe_is_class(qid),
            }
        for pid in set(props) | {p for q in ents
                                 for p in ent_cache.get(q, {}).get("properties", [])}:
            if pid in prop_cache:
                continue
            prop_cache[pid] = {"label": label_of(pid),
                               "quantity": probe_quantity(pid),
                               "qualifiers": probe_prop_qualifiers(pid),
                               "class_range": probe_prop_class_range(pid)}

        cards[rid] = build_card(ents, props, prop_cache, ent_cache)
        cards_targeted[rid] = build_card_targeted(ents, props, prop_cache, ent_cache)
        if (n + 1) % 10 == 0:
            save(out_file, cards)
            save(out_file_t, cards_targeted)
            save(f"schema_entities_{a.split}.json", ent_cache)
            save("schema_properties.json", prop_cache)
            print(f"  {n+1}/{len(rows)}")

    save(out_file, cards)
    save(out_file_t, cards_targeted)
    save(f"schema_entities_{a.split}.json", ent_cache)
    save("schema_properties.json", prop_cache)

    nonempty = sum(1 for v in cards.values() if v.strip())
    avg = sum(len(v.split()) for v in cards.values()) / max(len(cards), 1)
    print(f"\nwrote {out_file}: {len(cards)} cards, {nonempty} non-empty, "
          f"mean {avg:.0f} words")
    ex = next((v for v in cards.values() if v.strip()), "")
    print("\n--- example card ---\n" + ex[:600])
    print("\nNext: scp this file to the server and run stage 2 "
          "(schema_grounded_generate.py)")

if __name__ == "__main__":
    main()
