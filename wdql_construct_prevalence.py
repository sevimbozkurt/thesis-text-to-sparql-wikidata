"""wdql_construct_prevalence.py — Extension C: is Instruct-to-SPARQL's heavy
use of Wikidata's reification/hierarchy idioms representative of real
Wikidata querying? Compare construct prevalence in the benchmark's gold
queries (all splits) with the Wikidata Query Logs dataset (WDQL, Walter &
Bast 2026; one-per-cluster release, 226k real queries from the query service
logs).
"""
import json, re, csv, glob, collections

PAT = {"subclass closure (P279*)": r'P279\s*\*|P279\s*\+',
       "statement node (p:)":      r'\bp:P\d+',
       "qualifier (pq:)":          r'\bpq:P\d+',
       "value node (psv:/psn:)":   r'\bpsv:P\d+|\bpsn:P\d+',
       "aggregation (GROUP BY)":   r'(?i)\bgroup by\b',
       "alternation (VALUES/UNION)": r'(?i)\bvalues\b|\bunion\b',
       "property path (/ | * +)":  r'\b(?:wdt|p|ps|pq):P\d+\s*[/|*+]|[/|]\s*(?:wdt|p|ps|pq):P\d+',
       "OPTIONAL":                 r'(?i)\boptional\b',
       "FILTER":                   r'(?i)\bfilter\b',
       "LIMIT":                    r'(?i)\blimit\b',
       "label service":            r'wikibase:label'}
ANY_IDIOM = r'P279\s*[*+]|\bp:P\d+|\bpq:P\d+|\bpsv:P\d+|\bpsn:P\d+'

def expand(q):
    """WDQL `sparql` uses prefixes; benchmark gold too. Normalise full URIs just in case."""
    q = re.sub(r'<http://www\.wikidata\.org/prop/direct/(P\d+)>', r'wdt:\1', q)
    q = re.sub(r'<http://www\.wikidata\.org/prop/qualifier/(P\d+)>', r'pq:\1', q)
    q = re.sub(r'<http://www\.wikidata\.org/prop/statement/value/(P\d+)>', r'psv:\1', q)
    q = re.sub(r'<http://www\.wikidata\.org/prop/statement/(P\d+)>', r'ps:\1', q)
    q = re.sub(r'<http://www\.wikidata\.org/prop/(P\d+)>', r'p:\1', q)
    return q

def ntriples(q):
    """Size proxy robust to formatting: number of predicate tokens outside PREFIX
    declarations (wdt:/p:/ps:/pq:/psv:/psn:/rdfs:/schema:/skos:/wikibase: terms,
    excluding wikibase:label service boilerplate)."""
    body = re.sub(r'(?i)prefix\s+\S+\s*:\s*<[^>]*>', ' ', q)
    body = re.sub(r'SERVICE\s+wikibase:label\s*\{[^}]*\}', ' ', body, flags=re.I)
    return max(1, len(re.findall(r'\b(?:wdt|p|ps|pq|psv|psn|wdtn|rdfs|schema|skos|dct|ontolex|wikibase):\w+', body)))

def size_band(n): return "1" if n == 1 else "2" if n == 2 else "3-4" if n <= 4 else "5+"

bench = json.load(open("train.json")) + json.load(open("val.json")) + json.load(open("test.json"))
bench_q = [expand(r["query"]) for r in bench]
wdql_q = []
for f in glob.glob("external/wdql/wdql-one-per-cluster/*.jsonl"):
    for line in open(f):
        wdql_q.append(expand(json.loads(line)["sparql"]))
print(f"benchmark gold queries: {len(bench_q)}   WDQL queries: {len(wdql_q)}")

def prevalence(qs):
    return {name: sum(bool(re.search(p, q)) for q in qs) / len(qs) * 100 for name, p in PAT.items()} | \
           {"ANY reification/hierarchy idiom": sum(bool(re.search(ANY_IDIOM, q)) for q in qs) / len(qs) * 100}

rows = []
def report(label, bq, wq):
    pb, pw = prevalence(bq), prevalence(wq)
    print(f"\n{label}:  benchmark n={len(bq)}  WDQL n={len(wq)}")
    print(f"{'construct':34s} {'benchmark':>10s} {'WDQL':>8s} {'ratio':>6s}")
    for k in pb:
        r = pb[k] / pw[k] if pw[k] else float('inf')
        print(f"{k:34s} {pb[k]:9.1f}% {pw[k]:7.1f}% {r:6.2f}")
        rows.append(dict(subset=label, construct=k, benchmark_pct=round(pb[k], 1), wdql_pct=round(pw[k], 1),
                         n_benchmark=len(bq), n_wdql=len(wq)))

report("ALL queries", bench_q, wdql_q)
bb = collections.defaultdict(list); wb = collections.defaultdict(list)
for q in bench_q: bb[size_band(ntriples(q))].append(q)
for q in wdql_q: wb[size_band(ntriples(q))].append(q)
print("\nsize distribution (triple patterns): benchmark", {k: len(v) for k, v in sorted(bb.items())},
      " WDQL", {k: len(v) for k, v in sorted(wb.items())})
for band in ["1", "2", "3-4", "5+"]:
    if bb.get(band) and wb.get(band):
        report(f"queries with {band} predicate token(s)", bb[band], wb[band])
with open("results_tables/wdql_construct_prevalence.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("\nwritten: results_tables/wdql_construct_prevalence.csv")
