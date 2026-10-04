"""
"""
import os, time, re, json as _json, requests

def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

ENDPOINT = os.environ.get("SPARQL_ENDPOINT", "https://query.wikidata.org/sparql")
USER     = os.environ.get("SPARQL_USER", "")
PASS     = os.environ.get("SPARQL_PASS", "")
AUTH     = (USER, PASS) if USER else None
DELAY    = float(os.environ.get("SPARQL_DELAY", "0.2"))
TIMEOUT  = int(os.environ.get("SPARQL_TIMEOUT", "60"))
MAX_BYTES = 50_000_000

HEADERS = {
    "User-Agent": "ThesisKGQA/2.0 (master thesis research)",
    "Accept": "application/sparql-results+json",
}

PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wdtn: <http://www.wikidata.org/prop/direct-normalized/>
PREFIX wds: <http://www.wikidata.org/entity/statement/>
PREFIX wdv: <http://www.wikidata.org/value/>
PREFIX wdref: <http://www.wikidata.org/reference/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX psn: <http://www.wikidata.org/prop/statement/value-normalized/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX pqv: <http://www.wikidata.org/prop/qualifier/value/>
PREFIX pqn: <http://www.wikidata.org/prop/qualifier/value-normalized/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
PREFIX prv: <http://www.wikidata.org/prop/reference/value/>
PREFIX prn: <http://www.wikidata.org/prop/reference/value-normalized/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX ontolex: <http://www.w3.org/ns/lemon/ontolex#>
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX bds: <http://www.bigdata.com/rdf/search#>
PREFIX hint: <http://www.bigdata.com/queryHints#>
PREFIX gas: <http://www.bigdata.com/rdf/gas#>
"""

def strip_label_service(query):
    out = query
    while True:
        m = re.search(r'SERVICE\s+wikibase:label\s*\{', out, re.IGNORECASE)
        if not m:
            return out
        depth, i = 1, m.end()
        while i < len(out) and depth > 0:
            if out[i] == '{':
                depth += 1
            elif out[i] == '}':
                depth -= 1
            i += 1
        out = out[:m.start()] + out[i:]

def run_sparql(query):
    time.sleep(DELAY)
    try:
        r = requests.get(ENDPOINT,
                         params={"query": PREFIXES + strip_label_service(query)},
                         headers=HEADERS, timeout=TIMEOUT, stream=True)
        if r.status_code != 200:
            return False, set(), f"http_{r.status_code}"
        chunks, size = [], 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                r.close()
                return False, set(), "result_too_large"
        bindings = _json.loads(b"".join(chunks)).get("results", {}).get("bindings", [])
        values = set()
        for row in bindings:
            for v in row.values():
                val = v.get("value", "")
                if "wikidata.org/entity/" in val:
                    val = val.split("/")[-1]
                values.add(val)
        return True, values, ""
    except requests.exceptions.Timeout:
        return False, set(), "timeout"
    except requests.exceptions.ConnectionError:
        return False, set(), "connection"
    except Exception:
        return False, set(), "parse"

def jaccard(a, b):
    if not a and not b: return 1.0
    if not a or not b:  return 0.0
    return len(a & b) / len(a | b)

if __name__ == "__main__":
    print(f"Endpoint : {ENDPOINT}")
    ok, vals, err = run_sparql(
        "SELECT ?o WHERE { <http://www.wikidata.org/entity/Q64> "
        "<http://www.wikidata.org/prop/direct/P17> ?o }"
    )
    print(f"Executed : {ok}   error: {err or '-'}   values: {sorted(vals)}")
    print("Expected : Q183")
