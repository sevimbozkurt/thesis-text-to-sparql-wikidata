# Second-annotator guide — error taxonomy

Thank you for doing this. It should take 45–75 minutes.

## What you are doing

A system translated natural-language questions into SPARQL queries against Wikidata. All thirty cases in the worksheet are **failures** — the generated query did not return the reference answer. Your job is to decide, for each one, **what went wrong**, choosing exactly one of eight categories.

Please **do not** read the thesis or any results file before you finish. The point of this exercise is that your judgement is independent of the author's.

## How to fill it in

Open `inter_annotator_worksheet.csv` in Excel, Numbers or a text editor. For each row put one category name in **YOUR_CATEGORY**. Use exactly these spellings:

```
structure
triple_flip
wrong_entity
wrong_property
unresolved
execution
near_miss
benchmark_noise
```

If you hesitated between two, put the runner-up in **second_choice**. Add anything you noticed in **your_note**. Leave nothing blank in YOUR_CATEGORY — if you truly cannot tell, pick the closest and say so in the note.

## Reading a row

- `question` — what was asked.
- `reference_query` — the benchmark's correct query.
- `generated_query` — what the system produced. Identifiers appear as readable labels in brackets, e.g. `wdt:[property:director]`.
- `fully_linked` / `executed` / `exec_error` — whether every label resolved, and whether the query ran.
- `jaccard` — overlap with the reference answer; 0 means no overlap.

## A 60-second primer on Wikidata's query shapes

You need this only for the `structure` category.

- `wdt:P57` — the **shortcut**: goes straight from item to value.
- `p:P39` + `ps:P39` — goes via a **statement node** instead. Same answer, but the statement node can carry extra detail.
- `pq:P580` — a **qualifier** (a date, a role) hanging off a statement node. Reachable *only* through `p:`.
- `psv:` — a **normalised value**, carrying the unit a quantity was recorded in. Needed when comparing quantities.
- `wdt:P31/wdt:P279*` — **subclass closure**: all members of a class *including* members of its subclasses. Plain `wdt:P31` misses those.

The shortcut is always allowed by the syntax, so a query that uses it where a richer form was needed still runs — it just answers a different question.

## The categories

### `structure`

The generated query is syntactically fine and its identifiers are right, but it is built the wrong SHAPE: it uses the direct shortcut `wdt:` where the reference needs a richer construct -- a subclass closure (`wdt:P31/wdt:P279*`), a qualifier reachable only through `p:`/`pq:`, a normalised value node (`psv:`) for a quantity with units, an aggregation (COUNT/AVG/GROUP BY), an alternation over allowed values, or the lexeme/sitelink model.

*Example:* Gold averages heights through the value node so units are normalised; the generated query averages the raw numbers.

### `wrong_property`

The shape is right but a PROPERTY identifier is wrong -- a different Wikidata property was chosen than the reference uses.

*Example:* Gold uses `position held` (P39); generated uses `occupation` (P106).

### `wrong_entity`

The shape is right but an ENTITY identifier is wrong.

*Example:* Gold uses the film Q25188; generated uses the soundtrack album.

### `near_miss`

Both queries answer the question, but they PROJECT different variables, so the returned sets do not overlap. Typically gold returns the subject of a relation and the generated query returns its object.

*Example:* Gold returns the directors; generated returns the films they directed.

### `triple_flip`

Subject and object of a triple pattern are REVERSED, so the query asks the relation backwards.

*Example:* `?x wdt:P57 wd:Q25188` written as `wd:Q25188 wdt:P57 ?x`.

### `unresolved`

A label was never linked to an identifier at all -- the query still contains an unresolved placeholder, or the linking stage returned nothing for it.

*Example:* `wdt:[property:significant achievement]` left in the query.

### `execution`

The query failed to run, or the endpoint refused it (syntax error, timeout, result too large). Judge this from the `executed` and `exec_error` columns.

*Example:* HTTP error because prose was appended after the query.

### `benchmark_noise`

The REFERENCE query is itself wrong -- it does not answer the question it is paired with. The generated query may even be better.

*Example:* Question asks for the heaviest humans; gold returns the classes of things that have a weight.

## DECISION ORDER — apply these tests in order and stop at the first that fits.

  1. Did the query fail to run?                          -> execution
  2. Is there still an unresolved [entity:...] or
     [property:...] placeholder in it?                   -> unresolved
  3. Does the REFERENCE query fail to answer its own
     question?                                           -> benchmark_noise
  4. Is a triple written backwards?                      -> triple_flip
  5. Do both queries answer the question, but return
     different COLUMNS?                                  -> near_miss
  6. Is the query the wrong SHAPE (missing closure,
     qualifier, value node, aggregation)?                -> structure
  7. Is the shape right but an identifier wrong?         -> wrong_property
                                                            or wrong_entity

Step 6 before step 7 is deliberate and is the hardest call in this task. If the
query would still be wrong AFTER swapping in the correct property, the problem
is the shape: choose `structure`. If swapping the property alone would make it
right, choose `wrong_property`. Use the `second_choice` column whenever you
hesitate between two categories -- recording the hesitation is useful data, and
it does not count against agreement.
