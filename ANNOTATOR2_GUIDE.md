# Second-adjudicator guide — are the benchmark's own queries any good?

Thank you for doing this. It should take **60–90 minutes**, and you can stop
part-way: the rows are ordered so that a partial return is still usable.

## What you are doing

This thesis evaluates a system that translates questions into SPARQL queries
over Wikidata. Every such system is scored against a benchmark's **reference
queries** — the queries its authors wrote as the correct answer.

An earlier check suggested some of those reference queries **do not actually
answer the question they are attached to**. If that is true and common, then
every system measured on this benchmark, including this thesis's, is being
marked against a partly wrong answer key.

Your job is one judgement per row:

> **Does this reference query fairly answer its question — yes or no?**

You are judging **the benchmark**, not the thesis and not any system's output.

## Why you specifically

The rate has so far been established by me alone, and as the author of the thesis
I have an interest in the answer. Your verdicts will be compared against
mine to produce an agreement figure, and used separately to produce a second,
independent estimate of the rate. Please **do not discuss individual rows with
me before you finish**, and do not read the thesis — if we agree, that has to
mean something.

## How to do it

Open **`gold_audit_annotator2.html`** by double-clicking it. It works offline in
any browser. For each row you see:

- **the question**, in plain English;
- **what the reference query actually returns** — the first few result rows,
  with Wikidata identifiers resolved to readable names where possible;
- **the SPARQL itself**, folded away under "show the SPARQL".

Click **Yes, it answers it** or **No, it does not**. Add a short note when you
say no — one clause is plenty ("returns a count, not the items"). The notes are
the most useful part: they are what made the earlier objections convincing.

Your answers save as you go, so you can close the tab and come back. When you
are done (or have done as many as you want), click **Download answers** and send
the CSV back.

## What "no" means

Say **no** when the query would not give a reasonable person what they asked
for. Examples of genuine faults found earlier:

- the question asks for Czech buildings; the query has no country constraint
- the question asks for poems; the query never restricts to poems
- the question asks *which* items; the query returns only a **count**
- the question asks for the **top 20 by weight**; the query has no ordering
- the query computes a flag (`female`, `noble`) and then never filters on it

## What is NOT a fault — this matters

- **The query looks inelegant, or you would have written it differently.** Not a
  fault. Only ask whether it answers the question.
- **It returns a lot of rows, or rows you did not expect.** Not by itself a
  fault — Wikidata is large and messy.
- **A yellow box says "Did not execute on this endpoint".** This means the query
  uses syntax our query engine does not support, or refers to items removed from
  Wikidata since 2019. **Failing to run is not the same as failing to answer the
  question.** Judge those from the SPARQL text.
- **A column is blank.** Wikidata often has no label in English for an item.

When you genuinely cannot tell, pick the closer answer and say so in the note.
Leaving a row unanswered is also fine — it is simply excluded.

## What happens to your work

Two numbers, both reported in the thesis with your role described: agreement
between the two of us (Cohen's kappa), and the rate of faulty reference queries
estimated from your verdicts alone. You will be credited as an independent
adjudicator; your name is included only if you want it.
