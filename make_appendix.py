"""make_appendix.py — generate the data-driven parts of the appendix.

Usage: python3 make_appendix.py        (a second or two; no network, no endpoint)
"""
import ast, csv, os, re, sys, hashlib, textwrap, json

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(ROOT, "thesis_latex", "tables")
FIGS = os.path.join(ROOT, "thesis_latex", "figures")
os.makedirs(OUT, exist_ok=True)

written = []


def w(name, body):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body if body.endswith("\n") else body + "\n")
    written.append(name)


def esc(s):
    """Escape a plain string for LaTeX running text, unicode included."""
    s = str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}"), ("~", r"\textasciitilde{}"),
                 ("^", r"\textasciicircum{}")]:
        s = s.replace(a, b)
    for a, b in UNI.items():
        s = s.replace(a, b)
    return s


def trunc(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# Unicode that appears in the markdown logs and has no place in a .tex file.
UNI = {"→": r"$\rightarrow$", "←": r"$\leftarrow$", "≈": r"$\approx$",
       "≤": r"$\leq$", "≥": r"$\geq$", "×": r"$\times$", "−": "--",
       "—": "---", "–": "--", "…": r"\ldots{}", "κ": r"$\kappa$",
       "ρ": r"$\rho$", "∅": r"$\emptyset$", "“": "``", "”": "''",
       "‘": "`", "’": "'", " ": "~", "\u202f": r"\,"}


def md(s):
    r"""Escape a markdown fragment for LaTeX, turning `code` into \texttt{}."""
    parts = str(s).split("`")
    # odd indices sat between backticks
    return "".join((r"\texttt{" + esc(p) + "}") if i % 2 else esc(p)
                   for i, p in enumerate(parts))


# ---------------------------------------------------------------- prompts
def module_string(path, name):
    """Return the value of a module-level string constant, via AST."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise KeyError(f"{name} not found as a module-level string in {path}")


def source_of(path, funcname):
    """Return the source text of a function definition."""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == funcname:
            return ast.get_source_segment(src, node)
    raise KeyError(f"{funcname} not found in {path}")


def listing(caption, label, text):
    return (f"\\begin{{lstlisting}}[caption={{{caption}}},label={{{label}}},"
            f"basicstyle=\\ttfamily\\scriptsize,breaklines=true,captionpos=b]\n"
            f"{text.strip()}\n\\end{{lstlisting}}\n")


try:
    gen = module_string(os.path.join(ROOT, "pipeline_e2e.py"), "GEN_SYSTEM")
    w("app_prompts_generation.tex",
      listing("Generation system prompt (baseline).",
              "lst:prompt-gen", gen))
except Exception as e:
    print("  ! generation prompt:", e)

# the disambiguation prompt is an f-string inside a function; take the function
try:
    dis = source_of(os.path.join(ROOT, "pipeline_e2e.py"), "disambiguate")
    # keep the prompt itself plus the signature, drop the API plumbing
    cut = dis.split("time.sleep(API_DELAY)")[0].rstrip()
    w("app_prompts_disambiguation.tex",
      listing("Disambiguation prompt, as built by the pipeline. "
              "The candidate list is injected at \\texttt{\\{cand\\_text\\}}. "
              "The reported runs send this prompt through Anthropic's batch interface or, for the "
              "open models, through vLLM. If the answer contains no identifier, or a request fails, "
              "the first search result is used instead; in the reported frontier-model runs all "
              "4,063 requests returned an answer line, so this fallback was never used.",
              "lst:prompt-disamb", cut))
except Exception as e:
    print("  ! disambiguation prompt:", e)

try:
    base = module_string(os.path.join(ROOT, "prompt_idioms.py"), "BASE_SYSTEM")
    idiom = module_string(os.path.join(ROOT, "prompt_idioms.py"), "IDIOM_GUIDE")
    w("app_prompts_idiom.tex",
      listing("Idiom-guidance prompt. "
              "The idiom arm is \\textsc{base} followed by \\textsc{idiom guide}; "
              "the baseline arm is \\textsc{base} alone.",
              "lst:prompt-idiom", base.strip() + "\n\n" + idiom.strip()))
except Exception as e:
    print("  ! idiom prompt:", e)

# schema cards are built by two functions rather than being constants
try:
    # the card-building code (schema_grounded.py) stays in the repository;
    # the appendix shows one example card of each kind
    body = ""
    ex = []
    for f, kind in [("data/schema_cards_working.json", "verbose"),
                    ("data/schema_cards_targeted_working.json", "targeted")]:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            k = next((x for x in sorted(d) if d[x].strip()), None)
            if k:
                ex.append(f"--- {kind} card (row {k}) ---\n{d[k].strip()}")
    if ex:
        body += listing("Example schema cards, one of each form, as supplied to the generator.",
                               "lst:schema-cards", "\n\n".join(ex))
    w("app_prompts_schema.tex", body)
except Exception as e:
    print("  ! schema prompt:", e)


# ---------------------------------------------------------------- annotations
def read(path):
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


try:
    rows = read("annotations/annotation_clean.csv")
    lines = [r"\footnotesize\sloppy",  # a few technical property paths (p:P2048/psn:...)
             # have no spaces to break at; \sloppy lets LaTeX stretch
             # inter-word spacing rather than overflow the column
             r"\begin{longtable}{@{}r >{\raggedright\arraybackslash}p{1.7cm} >{\raggedright\arraybackslash}p{4.6cm} >{\raggedright\arraybackslash}p{2.5cm} >{\raggedright\arraybackslash}p{4.4cm}@{}}",
             r"\caption{All thirty annotated failure cases.}"
             r"\label{tab:app-annotations}\\",
             r"\toprule",
             r"ID & Complexity & Question & Category & Annotator note \\ \midrule",
             r"\endfirsthead",
             r"\multicolumn{5}{@{}l}{\footnotesize\itshape continued from previous page}\\",
             r"\toprule ID & Complexity & Question & Category & Annotator note \\ \midrule",
             r"\endhead",
             r"\midrule \multicolumn{5}{r@{}}{\footnotesize\itshape continued overleaf}\\",
             r"\endfoot", r"\bottomrule", r"\endlastfoot"]
    for r in rows:
        lines.append(" & ".join([
            esc(r.get("index", "")),
            esc(r.get("complexity", "")),
            esc(trunc(r.get("question", ""), 150)),
            r"\texttt{" + esc(r.get("error_category", "")) + "}",
            esc(trunc(r.get("notes", "").replace(" — ", "; "), 150)).replace("/", r"/\allowbreak{}"),
        ]) + r" \\")
    lines.append(r"\end{longtable}")
    lines.append(r"\fussy\normalsize")
    w("app_annotations.tex", "\n".join(lines))
except Exception as e:
    print("  ! annotations:", e)


# ------------------------------------------------- inter-annotator agreement
try:
    rows_ia = read("results_tables/inter_annotator.csv")
    agree = sum(1 for r in rows_ia if r["agree"] == "1")
    lines = [r"\begin{table}[htbp]", r"\centering", r"\footnotesize",
             r"\caption{Second-annotator comparison, all thirty cases.}",
             r"\label{tab:app-interannotator}",
             r"\resizebox{\ifdim\width>\textwidth\textwidth\else\width\fi}{!}{%",
             r"\begin{tabular}{@{}r l l l l@{}}", r"\toprule",
             r"case & complexity & author & second annotator & agree \\ \midrule"]
    for r in rows_ia:
        lines.append(" & ".join([
            esc(r["case"]), esc(r["complexity"]),
            r"\texttt{" + esc(r["author"]) + "}",
            r"\texttt{" + esc(r["second_annotator"]) + "}",
            r"\checkmark" if r["agree"] == "1" else ""]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}}",
              r"\tabnote{Labels assigned by the author and by the second annotator, case by case.}",
              r"\end{table}"]
    w("app_interannotator.tex", "\n".join(lines))
except Exception as e:
    print("  ! inter-annotator table:", e)

# ---------------------------------------------------------------- CSV tables
def csv_table(src, caption, label, colspec=None, note=None, fmt=None, columns=None):
    # columns: optional {csv column: printed header}; keeps only those columns,
    # in that order, so raw CSV names never reach the page
    rows = read(src)
    if not rows:
        raise ValueError("empty")
    if columns:
        rows = [{h: r[c] for c, h in columns.items()} for r in rows]
    cols = list(rows[0].keys())
    spec = colspec or ("@{}l" + "r" * (len(cols) - 1) + "@{}")
    out = [r"\begin{table}[htbp]", r"\centering", r"\footnotesize",
           f"\\caption{{{caption}}}", f"\\label{{{label}}}",
           r"\resizebox{\ifdim\width>\textwidth\textwidth\else\width\fi}{!}{%",
           f"\\begin{{tabular}}{{{spec}}}", r"\toprule",
           " & ".join(esc(c) for c in cols) + r" \\ \midrule"]
    for r in rows:
        vals = []
        for c in cols:
            v = r[c]
            vals.append(esc(fmt(c, v)) if fmt else esc(v))
        out.append(" & ".join(vals) + r" \\")
    out += [r"\bottomrule", r"\end{tabular}}"]
    if note:
        out.append(r"\tabnote{" + note + "}")
    out.append(r"\end{table}")
    return "\n".join(out)


TABLES = [
    ("results_tables/master_results_v2.csv", "app_master_results.tex",
     "Full strict-set results with per-run denominators, working split.",
     "tab:app-master",
     "All 400 strict-set questions count in the pooled columns, and a question "
     "without a scored query counts as zero (the gold-label condition has no "
     "labelled query for ten of them). Entity-level Jaccard is averaged over the "
     "questions on which it is defined for each run; their number is given in "
     "the last column."),
    ("results_tables/official_split_results.csv", "app_official.tex",
     "Pipeline stage outcomes on the official split.", "tab:app-official",
     "Stage rates are over all 495 questions of the split; Jaccard is over all 370 "
     "strict-set questions, and a question without a generated query counts as zero."),
    ("results_tables/linker_confidence.csv", "app_linker_ci.tex",
     "Linking F1 with bootstrap confidence intervals.", "tab:app-linker-ci",
     "$B = 2{,}000$ resamples over the 1,086 entity mentions every linker scored; "
     "the same resample is applied to all linkers on each draw."),
    ("results_tables/gap_decomposition.csv", "app_gap.tex",
     "Decomposition of the 66.5-point gap, with Wilson intervals.", "tab:app-gap",
     "Shares count failing rows rather than shares of the accuracy deficit. "
     "Intervals are wide and should be quoted with the point estimates."),
]
COLUMNS = {
    "app_linker_ci.tex": {"comparison": "Linker or paired difference",
                          "estimate": "F1 / difference",
                          "ci_low": "95\u202f% CI low", "ci_high": "95\u202f% CI high"},
}
for src, name, cap, lab, note in TABLES:
    try:
        w(name, csv_table(src, cap, lab, note=note, columns=COLUMNS.get(name)))
    except Exception as e:
        print(f"  ! {name}:", e)



# ---------------------------------------------------------------- inventory
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()[:12]


try:
    man = {}
    mp = os.path.join(ROOT, "results_tables", "figure_manifest.csv")
    if os.path.exists(mp):
        for r in read(mp):
            k = r.get("figure") or r.get("file") or ""
            man[os.path.basename(k)] = r
    figs = sorted(f for f in os.listdir(FIGS) if f.endswith(".pdf"))
    lines = [r"\footnotesize",
             r"\begin{longtable}{@{}>{\raggedright\arraybackslash}p{4.5cm} >{\raggedright\arraybackslash}p{2.5cm} >{\raggedright\arraybackslash}p{6.5cm}@{}}",
             r"\caption{Every figure in this thesis, with its source data and content hash.}"
             r"\label{tab:app-inventory}\\",
             r"\toprule File & sha256 (12) & Built from \\ \midrule",
             r"\endfirsthead",
             r"\toprule File & sha256 (12) & Built from \\ \midrule", r"\endhead",
             r"\bottomrule", r"\endlastfoot"]
    for f in figs:
        row = man.get(f, {})
        src = row.get("source") or row.get("source_data") or ""
        lines.append(" & ".join([r"\texttt{" + esc(f.replace(".pdf", "")) + "}",
                                 r"\texttt{" + sha(os.path.join(FIGS, f)) + "}",
                                 esc(trunc(src, 90)) or "---"]) + r" \\")
    lines.append(r"\end{longtable}")
    lines.append(r"\fussy\normalsize")
    w("app_inventory.tex", "\n".join(lines))
    print(f"  inventory: {len(figs)} figures hashed")
except Exception as e:
    print("  ! inventory:", e)

print("\nwrote to thesis_latex/tables/:")
for n in written:
    print("  ", n)
