# Text-to-SPARQL over Wikidata with Frozen Frontier Models

Code, data and results for the master's thesis *Text-to-SPARQL over Wikidata with
Frozen Frontier Models: A Stage-Wise Analysis of Entity Linking and Query
Generation in a Modular Pipeline* (Sevim Bozkurt, M.Sc. Management & Data Science,
Leuphana Universität Lüneburg).

## Quick start

Requirements: Python 3.10 or newer.

```bash
git clone https://github.com/sevimbozkurt/thesis-text-to-sparql-wikidata.git
cd thesis-text-to-sparql-wikidata
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash reproduce.sh
```

`reproduce.sh` takes a few minutes. It recomputes every reported number from the
stored model outputs, writes `VERIFICATION_REPORT_<date>.md`, and regenerates the
tables and figures in `thesis_latex/`. It does not repeat the model calls, which
used paid APIs (OpenRouter, Anthropic) and a GPU server.

To also re-execute the stored queries against a QLever endpoint (about 80 minutes),
set the endpoint in the environment or in a `.env` file (`SPARQL_ENDPOINT`, and
`SPARQL_USER` / `SPARQL_PASS` if it needs a login), then run:

```bash
bash reproduce.sh --with-endpoint
```

## Repository layout

```
.
├── README.md
├── requirements.txt
├── reproduce.sh              runs the full offline reproduction
├── *.py, run_*.sh            pipeline, linkers, scoring and analysis scripts
├── ANNOTATOR2_GUIDE.md       guide given to the second annotator
├── inter_annotator_GUIDE.md  guide given to the second judge
├── data/                     inputs
│   ├── test.json, train.json, val.json    working split of Instruct-to-SPARQL
│   ├── official_test.json                 official test split
│   ├── gold_links*.json                   linking ground truth (both splits)
│   ├── candidates_*.json, pool_*.json     candidate pools
│   ├── gold_status_qlever.csv             which reference queries execute
│   ├── schema_*.json                      schema evidence for the grounding arms
│   └── lcquad_*.json                      LC-QuAD 2.0 replication sample
├── outputs/                  stored model outputs and scored runs
│   ├── results_*.csv                      generated queries with scores, per run
│   ├── linked_*.csv/json                  labelled queries after linking, per arm
│   ├── preds_*.jsonl                      linker predictions, per linker and split
│   └── qlever/, qlever_v2/                runs re-scored on the QLever endpoint
├── annotations/              error-analysis annotations and reference-query audit
├── results_tables/           result tables and saved analysis outputs (RESULT_*.txt)
└── thesis_latex/             LaTeX sources of the thesis
```

## Re-running the experiments

The original runs are not part of `reproduce.sh`. The scripts that produced the
stored outputs are listed at the end of `reproduce.sh`. They need, in addition to
`requirements.txt`:

- API access: `pip install openai anthropic`; the OpenRouter key goes into
  `OPENROUTER_KEY` at the top of `evaluate_all.py`, `evaluate_fewshot.py`,
  `link_entities.py` and `pipeline_e2e.py`, and the Anthropic key into `.env` as
  `ANTHROPIC_API_KEY`
- the benchmark: `pip install datasets` (Instruct-to-SPARQL on Hugging Face)
- open-model disambiguation: a GPU with vLLM (`run_arm.sh`, `run_arms.sh`,
  `run_both.sh`; set `CONDA_SH`, `CONDA_ENV` and `HF_HOME` if your setup differs)
- the fine-tuned linkers: the ReFinED and BLINK/ELQ repositories, and GLiNKER

## Not included

Credentials (`.env`), the cached reference result sets (`data/gold_results.json`,
rebuilt by `diagnose_gold.py` against the endpoint), the benchmark authors' result
file, and the Wikidata Query Logs dataset
(https://wdql.cs.uni-freiburg.de/data/latest/wdql-one-per-cluster.tar.gz, place
under `external/wdql/`).

All queries were executed against a QLever instance indexing the Wikidata dump of
14 March 2026.
