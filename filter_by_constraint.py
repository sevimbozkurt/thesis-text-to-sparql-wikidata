"""

Usage:
  python3 filter_by_constraint.py fetch     # populate the cache (network)
  python3 filter_by_constraint.py measure   # the result (offline)
"""
import json, os, sys, time
import requests

import endpoint as EP

CACHE = "constraint_cache.json"
POOL  = "pool_constrained_seed.json"
GOLD  = "gold_links.json"

MAX_CLOSURE_DEPTH = 6      # P279* hops from an instance's class


# ---------------------------------------------------------------- SPARQL ---
def query_pairs(q, retries=3):
    """Run a query and keep the binding structure, which EP.run_sparql discards.
    Retries on empty results: an empty list from this endpoint is indistinguishable
    from throttling."""
    last = None
    for attempt in range(retries):
        time.sleep(EP.DELAY * (1 + attempt))
        try:
            r = requests.get(EP.ENDPOINT,
                             params={"query": EP.PREFIXES + q},
                             headers=EP.HEADERS, timeout=EP.TIMEOUT)
            if r.status_code != 200:
                last = f"http_{r.status_code}"
                continue
            b = r.json().get("results", {}).get("bindings", [])
            return b
        except Exception as e:                      # noqa: BLE001
            last = type(e).__name__
    print(f"    ! query failed after {retries} attempts ({last})", file=sys.stderr)
    return []


def short(uri):
    return uri.rsplit("/", 1)[-1] if "wikidata.org" in uri else uri


def load_cache():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {
        "domain": {}, "types": {}, "super": {}}


def save_cache(c):
    json.dump(c, open(CACHE, "w"), indent=0)


# ------------------------------------------------------------------ fetch ---
def fetch():
    pool = json.load(open(POOL))
    gold = json.load(open(GOLD))
    cache = load_cache()

    props = {c["id"] for k, v in pool.items() if k.startswith("property|")
             for c in v if c.get("id", "").startswith("P")}
    props |= {i for links in gold.values() for kind, _, i in links
              if kind == "property"}
    ents = {i for links in gold.values() for kind, _, i in links
            if kind == "entity"}

    print(f"{len(props)} distinct candidate properties, {len(ents)} gold entities")

    # --- 1. domain (type) constraints, in batches -------------------------
    todo = sorted(p for p in props
                  if p not in cache.get("domain_mandatory", {}))
    print(f"domain constraints to fetch: {len(todo)}")
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        vals = " ".join(f"wd:{p}" for p in chunk)
        rows = query_pairs(f"""
SELECT ?p ?class ?status WHERE {{
  VALUES ?p {{ {vals} }}
  ?p p:P2302 ?st .
  ?st ps:P2302 wd:Q21503250 ;
      pq:P2308 ?class .
  OPTIONAL {{ ?st pq:P2316 ?status }}
}}""")
        got, mand = {}, {}
        for r in rows:
            p = short(r["p"]["value"])
            cl = short(r["class"]["value"])
            got.setdefault(p, []).append(cl)
            # Q21502408 = "mandatory constraint". Wikidata marks most type
            # constraints with no status at all, which means a violation is
            # merely reported, not forbidden. Whether a filter should act on an
            # advisory constraint is the design question this run measures.
            if short(r.get("status", {}).get("value", "")) == "Q21502408":
                mand.setdefault(p, []).append(cl)
        for p in chunk:
            cache["domain"][p] = sorted(set(got.get(p, [])))
            cache.setdefault("domain_mandatory", {})[p] = sorted(set(mand.get(p, [])))
        print(f"  {i + len(chunk):5d}/{len(todo)}  "
              f"{sum(1 for p in chunk if cache['domain'][p])} of {len(chunk)} constrained")
        save_cache(cache)

    # --- 2. types of the gold entities ------------------------------------
    todo = sorted(e for e in ents if e not in cache["types"])
    print(f"entity types to fetch: {len(todo)}")
    for i in range(0, len(todo), 60):
        chunk = todo[i:i + 60]
        vals = " ".join(f"wd:{e}" for e in chunk)
        rows = query_pairs(f"""
SELECT ?e ?c WHERE {{ VALUES ?e {{ {vals} }} ?e wdt:P31 ?c . }}""")
        got = {}
        for r in rows:
            got.setdefault(short(r["e"]["value"]), []).append(short(r["c"]["value"]))
        for e in chunk:
            cache["types"][e] = sorted(set(got.get(e, [])))
        print(f"  {i + len(chunk):5d}/{len(todo)}")
        save_cache(cache)

    # --- 3. upward P279 closure, by bounded breadth-first search ----------
    # A single `wdt:P279*` query is prohibitively slow on this endpoint (a
    # one-class closure did not return inside 90 s), so the transitive closure is
    # built here from DIRECT P279 edges, which are cheap and batchable, expanded
    # to MAX_CLOSURE_DEPTH. Bounding the depth is a real approximation and is
    # reported as such: it can only make the filter look SAFER than it is, since
    # a missing ancestor can only cause a candidate to be dropped, never kept.
    seeds = {c for v in cache["types"].values() for c in v} | set(ents)
    edges = cache.setdefault("p279", {})
    frontier = {c for c in seeds if c not in edges}
    depth = 0
    while frontier and depth < MAX_CLOSURE_DEPTH:
        depth += 1
        todo = sorted(frontier)
        print(f"  P279 depth {depth}: {len(todo)} classes")
        found = set()
        for i in range(0, len(todo), 60):
            chunk = todo[i:i + 60]
            vals = " ".join(f"wd:{c}" for c in chunk)
            rows = query_pairs(
                f"SELECT ?c ?s WHERE {{ VALUES ?c {{ {vals} }} ?c wdt:P279 ?s . }}")
            got = {}
            for r in rows:
                got.setdefault(short(r["c"]["value"]), []).append(short(r["s"]["value"]))
            for c in chunk:
                edges[c] = sorted(set(got.get(c, [])))
                found |= set(edges[c])
            save_cache(cache)
        frontier = {c for c in found if c not in edges}

    # materialise the closures the measurement needs
    def closure(c):
        seen, stack = {c}, [c]
        while stack:
            x = stack.pop()
            for y in edges.get(x, []):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return sorted(seen)

    cache["super"] = {c: closure(c) for c in seeds}
    save_cache(cache)
    print(f"closures materialised for {len(cache['super'])} classes "
          f"(mean {sum(len(v) for v in cache['super'].values())/max(len(cache['super']),1):.1f} ancestors)")

    print("cache complete")


# ---------------------------------------------------------------- measure ---
def measure(policy="all"):
    """policy 'all'       — act on every declared type constraint (naive SAGA-style)
       policy 'mandatory' — act only on constraints Wikidata marks mandatory"""
    pool = json.load(open(POOL))
    gold = json.load(open(GOLD))
    cache = load_cache()
    table = cache["domain"] if policy == "all" else cache.get("domain_mandatory", {})
    if not cache["domain"]:
        raise SystemExit("cache empty — run `python3 filter_by_constraint.py fetch` first")

    def subject_universe(links):
        """Every class the row's gold entities belong to, closed under P279*,
        plus the entities themselves closed the same way."""
        u = set()
        for kind, _, i in links:
            if kind != "entity":
                continue
            u |= set(cache["super"].get(i, [i]))
            for c in cache["types"].get(i, []):
                u |= set(cache["super"].get(c, [c]))
        return u

    n_mentions = kept_tot = cand_tot = 0
    n_fired = n_recall_ok = n_decisive = 0
    lost = []
    no_constraint = 0
    abstained = 0

    for rid, links in gold.items():
        universe = subject_universe(links)
        # A filter must ABSTAIN where it has no type evidence. Rows whose gold
        # links contain no entity at all (the query constrains only by property)
        # give the filter nothing to test a constraint against, and treating
        # that as "no class matches" would destroy every constrained candidate
        # for a reason that has nothing to do with type compatibility. Counted
        # and excluded rather than silently scored.
        if not universe:
            abstained += sum(1 for k, lab, g in set(map(tuple, links))
                             if k == "property"
                             and len([c for c in (pool.get(f"property|{lab}") or [])
                                      if c.get("id", "").startswith("P")]) >= 2)
            continue
        seen_here = set()
        for kind, label, gid in links:
            if (kind, label, gid) in seen_here:
                continue                       # gold_links repeats some mentions
            seen_here.add((kind, label, gid))
            if kind != "property":
                continue
            cands = pool.get(f"property|{label}") or []
            ids = [c["id"] for c in cands if c.get("id", "").startswith("P")]
            if len(ids) < 2 or gid not in ids:
                continue                       # nothing for a filter to decide
            n_mentions += 1
            cand_tot += len(ids)

            survivors = []
            for p in ids:
                allowed = table.get(p) or []
                if not allowed:
                    survivors.append(p)        # unconstrained: always kept
                    continue
                ok = any(a in universe for a in allowed)
                if ok:
                    survivors.append(p)
            kept_tot += len(survivors)
            if len(survivors) < len(ids):
                n_fired += 1
                if gid in survivors:
                    n_recall_ok += 1
                else:
                    lost.append((rid, label, gid, len(ids), len(survivors)))
                if len(survivors) == 1:
                    n_decisive += 1
            else:
                no_constraint += 1

    print("=" * 72)
    print(f"R4 stage 1 — is a domain filter safe enough to build?   policy: {policy}")
    print("=" * 72)
    print(f"  ambiguous property mentions examined     {n_mentions}")
    print(f"  mean candidates before filtering         {cand_tot / max(n_mentions,1):.2f}")
    print(f"  mean candidates after filtering          {kept_tot / max(n_mentions,1):.2f}")
    print(f"  mentions where the filter removed anything {n_fired}"
          f"  ({100*n_fired/max(n_mentions,1):.1f} %)")
    print(f"  mentions the filter left untouched       {no_constraint}")
    print(f"  mentions skipped: no type evidence at all {abstained}"
          f"  (rows with no gold entity; a filter must abstain)")
    print()
    if n_fired:
        rec = n_recall_ok / n_fired
        lo, hi = wilson(n_recall_ok, n_fired)
        print(f"  RECALL when the filter fires             {n_recall_ok}/{n_fired}"
              f" = {100*rec:.1f} %  [{100*lo:.1f}, {100*hi:.1f}]")
        print(f"  filter left exactly one candidate        {n_decisive}"
              f"  ({100*n_decisive/n_fired:.1f} % of firings)")
        print()
        print(f"  gold property DESTROYED on {len(lost)} mentions")
        for rid, label, gid, before, after in lost[:15]:
            print(f"     row {rid:>5s}  {label[:34]:34s} gold {gid:8s}"
                  f"  {before} -> {after}")
        if len(lost) > 15:
            print(f"     ... and {len(lost)-15} more")
    print()
    print("READING")
    if n_fired == 0:
        print("  The filter never fires on this pool: Wikidata's declared type")
        print("  constraints do not discriminate between the candidates a label")
        print("  search returns. Mechanical domain filtering has nothing to remove")
        print("  here.")
    elif n_recall_ok / n_fired >= 0.98:
        print("  The filter is safe at this rate and worth building: it removes")
        print("  candidates while almost never removing the right one.")
    else:
        print("  The filter is NOT safe. It destroys the correct property on a")
        print("  measurable share of the mentions where it acts, and a filter's")
        print("  removals cannot be recovered by later reasoning.")


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "measure"
    if cmd == "fetch":
        fetch()
    elif cmd == "measure":
        for pol in (sys.argv[2:] or ["all", "mandatory"]):
            measure(pol)
            print()
    else:
        raise SystemExit("usage: filter_by_constraint.py fetch | measure [all|mandatory]")
