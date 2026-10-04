"""evaluate_all.py — Benchmark 4 frontier LLMs on the Instruct-to-SPARQL test
set.

Usage:
    python3 evaluate_all.py                           # run all 4 models
    python3 evaluate_all.py --model gemini            # run one model only
    python3 evaluate_all.py --limit 10               # quick test
"""

import json, time, requests, csv, os, argparse
from openai import OpenAI

# ── API KEY ───────────────────────────────────────────────
OPENROUTER_KEY = "API KEY HERE"

# ── MODELS ─────────────────────────────────────────────────────
MODELS = {
    "gpt-5.4":   "openai/gpt-5.4",
    "claude":    "anthropic/claude-opus-4.8",
    "gemini":    "google/gemini-3.1-flash-lite",
    "deepseek":  "deepseek/deepseek-v4-flash",
}

# ── SETTINGS ───────────────────────────────────────────────────
API_DELAY      = 2.0
WIKIDATA_DELAY = 1.5
TIMEOUT        = 30
MAX_RETRIES    = 3
MAX_TOKENS     = 1024   # increased — prevents query truncation
# ──────────────────────────────────────────────────────────────

WIKIDATA_URL  = "https://query.wikidata.org/sparql"
SYSTEM_PROMPT = (
    "You are a SPARQL expert for the Wikidata knowledge graph. "
    "Generate a valid SPARQL query that answers the given question. "
    "Output ONLY the SPARQL query, nothing else."
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY
)


def clean_sparql(text):
    """Extract SPARQL from model output, removing preamble and markdown fences."""
    if not text:
        return ""
    text = text.strip()

    # Remove markdown code fences
    if "```" in text:
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Strip any preamble before the actual SPARQL keyword
    sparql_starters = ["SELECT", "ASK", "CONSTRUCT", "DESCRIBE", "PREFIX", "BASE"]
    upper = text.upper()
    earliest = len(text)
    for kw in sparql_starters:
        idx = upper.find(kw)
        if idx != -1 and idx < earliest:
            earliest = idx
    if earliest > 0:
        text = text[earliest:]

    return text.strip()


def run_sparql(query):
    """Execute SPARQL on Wikidata. Returns (success, result_values)."""
    time.sleep(WIKIDATA_DELAY)
    try:
        r = requests.get(
            WIKIDATA_URL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": "ThesisSPARQLEval/1.0"},
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return False, set()
        bindings = r.json().get("results", {}).get("bindings", [])
        values = set()
        for row in bindings:
            for v in row.values():
                val = v.get("value", "")
                if "wikidata.org/entity/" in val:
                    val = val.split("/")[-1]
                values.add(val)
        return True, values
    except Exception:
        return False, set()


def jaccard(a, b):
    if not a and not b: return 1.0
    if not a or not b:  return 0.0
    return len(a & b) / len(a | b)


def generate_sparql(model_id, instruction):
    """Call model via OpenRouter. Retries if response is empty."""
    for attempt in range(MAX_RETRIES):
        time.sleep(API_DELAY)
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": f"Question: {instruction}"}
                ],
                max_tokens=MAX_TOKENS,
                temperature=0
            )
            content = response.choices[0].message.content
            if content:
                return clean_sparql(content)
            wait = 2 ** attempt
            print(f"    Empty response (attempt {attempt+1}/{MAX_RETRIES}), retrying in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2 ** attempt
            print(f"    Error attempt {attempt+1}: {str(e)[:60]} — retrying in {wait}s...")
            time.sleep(wait)
    return ""


def run_model(name, model_id, test, limit=None):
    outfile  = f"results_{name}.csv"
    rows_all = test[:limit] if limit else test

    done = set()
    if os.path.exists(outfile):
        with open(outfile) as f:
            done = {int(r["index"]) for r in csv.DictReader(f)}
        print(f"  Resuming — {len(done)} rows already done")

    fields = ["index", "complexity", "instruction",
              "generated_query", "syntax", "jaccard", "error"]
    empty_count = 0

    with open(outfile, "a" if done else "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not done:
            writer.writeheader()

        for i, ex in enumerate(rows_all):
            if i in done:
                continue

            generated, error = "", ""
            try:
                generated = generate_sparql(model_id, ex["instruction"])
                if not generated:
                    error = "empty response after retries"
                    empty_count += 1
            except Exception as e:
                error = str(e)[:120]
                print(f"    [{i}] API error: {error}")

            syntax, pred_vals = False, set()
            if generated:
                syntax, pred_vals = run_sparql(generated)

            jac = 0.0
            if syntax:
                _, gold_vals = run_sparql(ex["query"])
                jac = jaccard(pred_vals, gold_vals)

            writer.writerow({
                "index":           i,
                "complexity":      ex["complexity"],
                "instruction":     ex["instruction"],
                "generated_query": generated,
                "syntax":          syntax,
                "jaccard":         round(jac, 4),
                "error":           error
            })
            f.flush()

            if (i + 1) % 10 == 0:
                print(f"    {i+1}/{len(rows_all)} done — empty so far: {empty_count}")

    rows        = list(csv.DictReader(open(outfile)))
    total       = len(rows)
    empty       = sum(1 for r in rows if r["error"] == "empty response after retries")
    syntax_pct  = sum(1 for r in rows if r["syntax"] == "True") / total * 100
    jaccard_pct = sum(float(r["jaccard"]) for r in rows) / total * 100

    if empty > 0:
        print(f"\n  ⚠️  {empty}/{total} empty responses ({empty/total*100:.0f}%)")

    print(f"\n  {'Complexity':<10} {'N':>5} {'Syntax':>8} {'Jaccard':>9}")
    print(f"  {'-'*36}")
    for c in ["simple", "medium", "complex"]:
        sub = [r for r in rows if r["complexity"] == c]
        if not sub:
            continue
        s = sum(1 for r in sub if r["syntax"] == "True") / len(sub) * 100
        j = sum(float(r["jaccard"]) for r in sub) / len(sub) * 100
        print(f"  {c:<10} {len(sub):>5} {s:>7.1f}% {j:>8.1f}%")
    print(f"  {'TOTAL':<10} {total:>5} {syntax_pct:>7.1f}% {jaccard_pct:>8.1f}%")

    return {"model": name, "syntax": syntax_pct, "jaccard": jaccard_pct, "empty": empty}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS.keys()))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    with open("test.json") as f:
        test = json.load(f)

    to_run = {args.model: MODELS[args.model]} if args.model else MODELS

    summaries = []
    for name, model_id in to_run.items():
        print(f"\n{'='*52}")
        print(f"  MODEL : {name}")
        print(f"  ID    : {model_id}")
        print(f"  ROWS  : {args.limit or len(test)}")
        print(f"{'='*52}")
        summary = run_model(name, model_id, test, args.limit)
        summaries.append(summary)

    if len(summaries) > 1:
        print(f"\n{'='*52}")
        print("  FINAL COMPARISON")
        print(f"{'='*52}")
        print(f"  {'Model':<12} {'Syntax':>8} {'Jaccard':>9} {'Empty':>7}")
        print(f"  {'-'*40}")
        for s in summaries:
            flag = " ⚠️" if s["empty"] > 0 else ""
            print(f"  {s['model']:<12} {s['syntax']:>7.1f}% {s['jaccard']:>8.1f}% {s['empty']:>6}{flag}")


if __name__ == "__main__":
    main()
