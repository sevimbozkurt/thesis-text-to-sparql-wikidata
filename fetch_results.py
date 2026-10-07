"""fetch_results.py — Robust replacement for the `fetch-gen` and `fetch-disamb`
commands of run_official_batch.py.

Usage:
    python3 fetch_results.py gen
    python3 fetch_results.py disamb
"""

import json, os, sys, time, re
import requests

STATE      = "batch_state.json"
GEN_OUT    = "outputs/batch_generated.json"
CAND_OUT   = "data/batch_candidates.json"
DISAMB_MAP = "outputs/batch_disamb_map.json"
DISAMB_OUT = "outputs/batch_disambiguated.json"
LINKLOG    = "official_linking_log.jsonl"

API = "https://api.anthropic.com/v1/messages/batches"

def load(p, d):
    return json.load(open(p)) if os.path.exists(p) else d

def save(p, o):
    json.dump(o, open(p, "w"), indent=1)

def api_key():
    # read from .env the same way endpoint.py does
    if os.path.exists(".env"):
        for line in open(".env"):
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if not k:
        sys.exit("ANTHROPIC_API_KEY not found in .env or environment")
    return k

HEADERS = None

def download(batch_id, outfile):
    """Download the results jsonl, retrying on network errors."""
    if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
        print(f"using existing {outfile} ({os.path.getsize(outfile)} bytes)")
        return outfile
    meta = requests.get(f"{API}/{batch_id}", headers=HEADERS, timeout=60).json()
    url = meta.get("results_url")
    if not url:
        sys.exit(f"batch not finished yet — processing_status="
                 f"{meta.get('processing_status')}")
    for attempt in range(6):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp = outfile + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp, outfile)
            print(f"downloaded {outfile} ({os.path.getsize(outfile)} bytes)")
            return outfile
        except Exception as e:
            wait = 3 * (attempt + 1)
            print(f"  attempt {attempt+1} failed ({type(e).__name__}), retry in {wait}s")
            time.sleep(wait)
    sys.exit("download failed after 6 attempts")

def entries(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def text_of(entry):
    msg = entry.get("result", {}).get("message", {})
    return "".join(b.get("text", "") for b in msg.get("content", [])
                   if b.get("type") == "text")

def strip_fences(t):
    if "```" in t:
        t = "\n".join(l for l in t.split("\n")
                      if not l.strip().startswith("```")).strip()
    return t.strip()


def do_gen():
    st = load(STATE, {})
    bid = st.get("gen_batch_id") or sys.exit("no gen batch in state")
    path = download(bid, f"batch_gen_{bid}.jsonl")
    gen = load(GEN_OUT, {})
    ok = err = 0
    for e in entries(path):
        rid = e["custom_id"].split("gen-", 1)[1]
        if e.get("result", {}).get("type") == "succeeded":
            gen[rid] = strip_fences(text_of(e)); ok += 1
        else:
            gen.setdefault(rid, ""); err += 1
    save(GEN_OUT, gen)
    print(f"parsed: {ok} succeeded, {err} failed; {GEN_OUT} holds {len(gen)} rows")
    print("next:  python3 run_official_batch.py candidates")


def do_disamb():
    st = load(STATE, {})
    bid = st.get("disamb_batch_id") or sys.exit("no disamb batch in state")
    path = download(bid, f"batch_disamb_{bid}.jsonl")
    mapping = load(DISAMB_MAP, {})
    cands   = load(CAND_OUT, {})
    res     = load(DISAMB_OUT, {})
    ok = err = 0
    with open(LINKLOG, "a") as log:
        for e in entries(path):
            trip = mapping.get(e["custom_id"])
            if not trip:
                continue
            rid, kind, label = trip
            pool = cands.get(rid, {}).get(kind, {}).get(label, [])
            chosen = pool[0]["id"] if pool else ""
            if e.get("result", {}).get("type") == "succeeded":
                t = text_of(e)
                m = re.search(r'ANSWER:\s*([QP]\d+)', t) or re.search(r'\b([QP]\d+)\b', t)
                if m:
                    chosen = m.group(1)
                ok += 1
            else:
                err += 1
            res.setdefault(rid, {}).setdefault(kind, {})[label] = chosen
            log.write(json.dumps({"id": rid, "kind": kind, "label": label,
                                  "candidates": [c["id"] for c in pool],
                                  "chosen": chosen}) + "\n")
    save(DISAMB_OUT, res)
    print(f"parsed: {ok} succeeded, {err} failed")
    print("next:  python3 run_official_batch.py finalize")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("gen", "disamb"):
        sys.exit("usage: python3 fetch_results.py gen|disamb")
    HEADERS = {"x-api-key": api_key(), "anthropic-version": "2023-06-01"}
    (do_gen if sys.argv[1] == "gen" else do_disamb)()
