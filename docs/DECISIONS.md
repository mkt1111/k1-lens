# Design decisions

Each section lists options that were on the table and the tradeoff of the option the code uses.

## Deterministic-first

Options considered:

- Send every document to a model.
- Parse with a deterministic extractor, and call a model only for fields that are missing or below the review threshold, and for unrecognized layouts.

Tradeoffs:

- A model on every page costs money and can invent a value that is not on the page.
- A parser misses captions it has not seen. Those pages are the ones the model is allowed to fill.
- With no API key, the pipeline still runs. The model step does nothing.

## The confidence signals

Options considered:

- Use the model's own score as the field confidence.
- Use one fixed score per extractor.
- Combine label-match quality, a text layer or Tesseract word confidence, proximity of the value to its label, whether the token parsed, whether an EIN, TIN, percentage, or withdrawal has a legal shape, and whether item L ties or could not be tested.

Tradeoffs:

- A self-report can be high on a value the page does not contain.
- One fixed score does not separate a clean text line from a bad scan.
- The combined score does not look at ground truth. On a text layer it takes few distinct values, so the reliability table is not a fitted probability.

## The threshold

Options considered:

- A hard-coded 0.80.
- A threshold set by `--threshold` or `K1LENS_REVIEW_THRESHOLD`.

Tradeoffs:

- One constant is what the published numbers use, and it is easy to state.
- A lower threshold that did not move the caps would let a capped field through. The caps sit under the configured threshold. The default is 0.80.

## The unrecognized-layout cap

Options considered:

- Trust every parsed value on a page with few matching labels.
- Cap every confidence below the threshold when fewer than four lines match strongly, or when the strong matches are under half of the printed lines.
- Cap deterministic values, and let a model value clear the threshold only when it sits in that field's own label region and is not the low-confidence read, or when it fixes a failed cross-check.

Tradeoffs:

- Trusting the parse lets a lucky read through without review.
- Capping a grounded model value as well sends a correct read to a person on purpose.
- The code caps deterministic field confidences on an unrecognized document, and the LLM-only backend uses that same cap on those fields. That blanket does not rewrite tax_year_confidence. Every llm-leg value is capped at LLM_ONLY_CONFIDENCE_CAP (0.79 at the default threshold), so llm mode never clears a field. Hybrid stores a model value only for a missing money or percent amount, a missing coded-line amount, or a missing tax year, and only when that string is in the field's own label region, at or below below_review_threshold (0.49 at 0.80). A coded line the rules did not read is stored only when the layout is unrecognized. No model value clears the threshold, including one that would fix a failed item L or guaranteed-payment check. A malformed reply is retried once, then that document keeps the deterministic values.

## The append-only hash-chained audit

Options considered:

- A log that can be updated or deleted.
- An append-only table. SQLite triggers abort UPDATE and DELETE. Each row stores the previous row's hash. `k1lens verify-audit` checks the chain.

Tradeoffs:

- A mutable log can be edited in place.
- Triggers and a hash chain do not stop someone who can replace the SQLite file. They stop SQL updates and deletes through the application. Re-ingest appends a row and does not wipe the log. If a non-human value changed, the approval drops back to pending and that audit row stores the old value and the new value. An unchanged re-ingest keeps the approval. A human correction stays.

## The approval gate

Options considered:

- Let a reviewer approve from the queue with no further check.
- Refuse approval and export while a low-confidence field or a validation error has no override, and require a reason on the override.

Tradeoffs:

- An open approve button is faster to click.
- The gate uses the same unresolved-issues check as straight-through. Warnings do not block. An override is an audit row with a reason. The reviewer name is typed into the form. There is no authentication.

## The eval protocol

Options considered:

- Publish one accuracy number.
- Report in-distribution, scanned images, and dev layouts separately, with straight-through and the confident-wrong count, and say which sets were seen.

Tradeoffs:

- One number hides a layout the parser does not read.
- In-distribution and `layout_shift` share the catalog labels. `fixtures/dev` and `dev_b` were inspected during development. The held-out set is scored by an independent reviewer; not in this repo.
- CI floors are the measured rates, including the known-failure pages. A confident wrong value at or above the threshold is recorded. It is not removed to raise the score.
- Model comparison tests use recorded HTTP responses. The committed live run is docs/eval-live/report.md, measured on the pre-release source of v0.1.0 (src/ differs from the tag only in one docstring), with report-run1.json and report-run2.json beside it. `uv run k1lens eval --backend hybrid --live` is the command that calls OpenAI once `OPENAI_API_KEY` is set. The default ceiling is $3.
