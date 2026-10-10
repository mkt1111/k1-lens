# K1-Lens evaluation report

Synthetic data only. These numbers are from a corpus generated from the seed
and the deterministic extractor unless the header says otherwise.

## Run

- Backend: `deterministic`
- Fixtures: `fixtures/dev`
- Seed: 1065
- Documents: 8
- OCR enabled: yes
- Tesseract: tesseract 5.3.4
- Roster: none
- Confidently read ids: 8 of 16 sections
- Money tolerance: 1.00
- Distribution: `dev`
- Review threshold: 0.80

## Overall

| Metric | Value |
| --- | --- |
| Comparisons | 513 |
| Accuracy | 68.0% (349/513) |
| Precision | 100.0% (349/349) |
| Recall | 68.0% (349/513) |
| Correct | 349 |
| Both null | 0 |
| Mismatch | 0 |
| Missed | 164 |
| Spurious | 0 |
| Straight-through | 0.0% (0/8) |

Straight-through counts documents that need no review. Field accuracy above
counts fields. A document can be field-accurate and still fail a required-field
rule, including a missing tax year.

## By source

Text layer is every variant that still has text. Image-only variants are
`rasterized` and `scan_*`. Those pages are read with Tesseract. Overall
is the two together.

| Scope | Comparisons | Accuracy | Precision | Recall |
| --- | --- | --- | --- | --- |
| text layer | 513 | 68.0% (349/513) | 100.0% (349/349) | 68.0% (349/513) |
| rasterized | 0 | n/a | n/a | n/a |
| overall | 513 | 68.0% (349/513) | 100.0% (349/349) | 68.0% (349/513) |

## Review flags

The review UI highlights a field when its confidence is below 0.80.
A wrong value is a mismatch or a spurious extraction.
An incorrect comparison also includes a miss.
OCR fields routed to review: 0/0.

| Scope | Wrong values flagged | Incorrect comparisons flagged |
| --- | --- | --- |
| text layer | n/a | 100.0% (164/164) |
| rasterized | n/a | n/a |
| overall | n/a | 100.0% (164/164) |

## Reliability

Text-layer confidence takes few distinct values because the signals are coarse:
an exact label, one proximity bin for a normal line, and a format check.
This is a reliability table for those levels, not a fitted probability.
Each comparison falls in the bucket of the confidence the extractor stored.
An error is a mismatch, a miss, or a spurious value.
The lowest populated bucket (0.00-0.19) has error rate 100.0% (164/164), which is higher than the highest populated bucket (0.80-1.00) at 0.0% (0/217). A format failure, an item L mismatch, or an untested item L account can also lower confidence on a value that still matches the facsimile, so a middle bucket can be mostly correct.
Distinct confidence values: 4. Expected calibration error (bucket ECE): 0.158.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 164 | 0.000 | 0.0% (0/164) | 164 | 100.0% (164/164) |
| 0.20-0.39 | 0 | n/a | n/a | 0 | n/a |
| 0.40-0.59 | 132 | 0.490 | 100.0% (132/132) | 0 | 0.0% (0/132) |
| 0.60-0.79 | 0 | n/a | n/a | 0 | n/a |
| 0.80-1.00 | 217 | 0.936 | 100.0% (217/217) | 0 | 0.0% (0/217) |

## Validation catch rate

Caught means the rules engine emitted an error whose rule id is the planted defect.
Ground truth measures the rules. Post-extraction measures whether the defect
is still visible after extraction.

| Scope | Value |
| --- | --- |
| Ground truth | n/a |
| Post-extraction | n/a |

## By variant

| Variant | Comparisons | Accuracy | Precision | Recall | Straight-through |
| --- | --- | --- | --- | --- | --- |
| dev_statement | 256 | 35.9% (92/256) | 100.0% (92/92) | 35.9% (92/256) | 0.0% (0/4) |
| layout_shift | 257 | 100.0% (257/257) | 100.0% (257/257) | 100.0% (257/257) | 0.0% (0/4) |

## By field

| Field | Comparisons | Accuracy | Precision | Recall | Missed | Mismatch |
| --- | --- | --- | --- | --- | --- | --- |
| `part_i.ein` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_i.name` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_i.street` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_i.city` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_i.state` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_i.zip_code` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_i.irs_center` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_i.is_ptp` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.tin` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.name` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.street` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.city` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.state` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.zip_code` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.is_general_partner` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.is_domestic` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.entity_type` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.is_retirement_plan` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.profit_beginning` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.profit_ending` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.loss_beginning` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.loss_ending` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital_share_beginning` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital_share_ending` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.liability_nonrecourse` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.liability_qualified_nonrecourse` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.liability_recourse` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.capital_method` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_ii.capital.beginning` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital.contributed` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital.current_year_net_income` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital.other_increase_decrease` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital.withdrawals` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.capital.ending` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_ii.contributed_builtin_gain` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.ordinary_business_income` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.net_rental_real_estate` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.other_net_rental` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.guaranteed_payments_services` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.guaranteed_payments_capital` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.guaranteed_payments_total` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.interest_income` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.ordinary_dividends` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.qualified_dividends` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.dividend_equivalents` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.royalties` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.net_short_term_capital_gain` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.net_long_term_capital_gain` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.collectibles_gain` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.unrecaptured_1250_gain` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.net_section_1231_gain` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.section_179_deduction` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.schedule_k3_attached` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.foreign_taxes_paid` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `tax_year` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.amt_items[B]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.distributions[C]` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.distributions[A]` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.other_income[B]` | 4 | 50.0% (2/4) | 100.0% (2/2) | 50.0% (2/4) | 2 | 0 |
| `part_iii.other_income[C]` | 3 | 33.3% (1/3) | 100.0% (1/1) | 33.3% (1/3) | 2 | 0 |
| `part_iii.other_income[E]` | 4 | 50.0% (2/4) | 100.0% (2/2) | 50.0% (2/4) | 2 | 0 |
| `part_iii.other_deductions[W]` | 3 | 33.3% (1/3) | 100.0% (1/1) | 33.3% (1/3) | 2 | 0 |
| `part_iii.other_deductions[B]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_deductions[A]` | 4 | 50.0% (2/4) | 100.0% (2/2) | 50.0% (2/4) | 2 | 0 |
| `part_iii.amt_items[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.amt_items[C]` | 3 | 33.3% (1/3) | 100.0% (1/1) | 33.3% (1/3) | 2 | 0 |
| `part_iii.other_income[A]` | 4 | 25.0% (1/4) | 100.0% (1/1) | 25.0% (1/4) | 3 | 0 |
| `part_iii.credits[P]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[B]` | 4 | 25.0% (1/4) | 100.0% (1/1) | 25.0% (1/4) | 3 | 0 |
| `part_iii.tax_exempt_and_nondeductible[A]` | 4 | 25.0% (1/4) | 100.0% (1/1) | 25.0% (1/4) | 3 | 0 |
| `part_iii.tax_exempt_and_nondeductible[C]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_information[B]` | 2 | 50.0% (1/2) | 100.0% (1/1) | 50.0% (1/2) | 1 | 0 |
| `part_iii.other_information[N]` | 2 | 50.0% (1/2) | 100.0% (1/1) | 50.0% (1/2) | 1 | 0 |
| `part_iii.other_deductions[I]` | 2 | 50.0% (1/2) | 100.0% (1/1) | 50.0% (1/2) | 1 | 0 |
| `part_iii.other_deductions[H]` | 2 | 50.0% (1/2) | 100.0% (1/1) | 50.0% (1/2) | 1 | 0 |
| `part_iii.credits[A]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.credits[C]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_information[V]` | 2 | 50.0% (1/2) | 100.0% (1/1) | 50.0% (1/2) | 1 | 0 |
| `part_iii.other_information[A]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_income[F]` | 1 | 0.0% (0/1) | n/a | 0.0% (0/1) | 1 | 0 |
| `part_iii.other_information[Z]` | 1 | 0.0% (0/1) | n/a | 0.0% (0/1) | 1 | 0 |

## Definitions

- Accuracy = (correct + both null) / comparisons.
- Precision = correct / (correct + mismatch + spurious).
- Precision is n/a when that denominator is zero.
- Recall = correct / (correct + mismatch + missed).
- Recall is n/a when that denominator is zero.
- Money and percentages match within the absolute tolerance.
- Other fields match exactly.
- Coded lines are scored per code.
- Tax year is one comparison per document.
- A code present on only one side is a miss or a spurious value.
- Straight-through = documents with no error-severity finding and no field below the review threshold, including tax year, divided by documents.
- Warnings do not block straight-through.
- A wrong value is flagged when its confidence is below the review threshold.
- Calibration buckets are half-open ranges of stored confidence. 1.00 is in the top bucket.

## Notes

- Ground truth was produced by the synthetic generator with seed 1065.
- No taxpayer data is in this run.
- Confidence is computed from label-match quality, text-layer presence or Tesseract word confidence, label/value proximity, parse and format checks, and whether item L reconciles or could not be tested. It does not use ground truth.
- A field is flagged for review when its confidence is below 0.80.
- A label one edit from exactly one known field label is accepted on OCR lines, at a lower label score. A period in an abbreviation or an initial, such as L.P. or Jr., is kept. Yes. and No. lose the separator period, and a trailing period on a capital-method checkbox is dropped.
- Other labels are matched from the public Schedule K-1 (Form 1065) box numbers, line names, and codes. Case and punctuation are normalized. Abbreviations are only those the IRS prints (EIN, SSN, TIN, PTP, AMT) or general accounting shortenings of the form's own words. A line is kept only when it beats the runner-up by a margin. An ambiguous line is left blank.
- When too few lines match, the document is an unrecognized layout. Deterministic field confidence is capped below the review threshold, including a lower --threshold, and the review UI says the layout was not recognized. The LLM-only backend uses that same cap. The unrecognized-layout cap still applies, including after a roster match: an unrecognized page does not clear identity. A numeric model proposal is stored only when the rules value is missing and the string appears in that field's own label region. Its confidence is never raised above the number the model reported, and it stays under the review threshold. A non-finite model confidence is rejected. A finite confidence outside 0 to 1 is clamped. Identity is not taken from the model at any confidence. A disagreeing model value is not stored. The LLM-only path stops on a persistent 5xx, a timeout, or a malformed reply. Hybrid keeps the deterministic values in those cases.
- Name, street, city, state, and ZIP are lifted to exactly the review threshold, and not higher, only when a roster is passed, the key id was read confidently and passes the format check, and every field in that section matches the same record. Each value has to be read from its own field region. A fallback, a repair, or a model value lifts nothing in that section. A partial match lifts nothing. An unrecognized layout lifts nothing. The partnership section is keyed by the EIN. The partner section is keyed by the TIN. The key must be nine digits in the EIN or SSN dash pattern, including the synthetic 00- and 000- ranges. An OCR id whose digit-word confidence is under the threshold is not a key. A text-layer id under the threshold is not a key. Digits are not repaired, guessed, or check-digit-corrected. A masked id is no_tin. Without a roster the finding is no_roster. A confident key with no record is new_partner. A key that is well formed but not confident is no_roster_match. Two roster records with the same EIN or TIN are duplicate_roster_key and are not a match. A key that matches, with any field different or blank on either side, is identity_mismatch. The value stored is the page string. Each lifted field is an audit row with reason roster_exact_match. A lift needs a confident id plus a full exact match. Entity type is not in this set. The form prints no options for that item, and a roster match does not clear it.
- Text-layer confidence takes few distinct values. An exact catalog label, a short gap (proximity 1), a text-layer source, and a successful parse with no format rule land at 0.92. A format check adds 0.08. A wide label-to-value gap, OCR word confidence, a failed parse, a failed format check, and the item L penalty move the score. The reliability table and the expected calibration error describe those levels. They are not a fitted probability.
- A wrong value is a mismatch or a spurious extraction.
- An incorrect comparison is a wrong value or a miss.
- A planted defect is caught when validation emits an error with that rule id.
- Capital tolerance is absolute dollars, not a percentage.
- Tax year is scored with the other fields. Straight-through is the share of documents with no error-severity finding and no field, including tax year, below the review threshold. Warnings do not block. Field accuracy does not imply that rate. It is the same check the approval gate uses before an override.
- Tesseract 5.3.4 is the version measured here and in Ubuntu CI. The Docker image uses Debian bookworm's 5.3.0. Rasterized accuracy and precision floors sit under the measured rates so that one-version OCR disagreement does not fail the check. The report header records the version that produced the numbers.
- layout_shift reprints the catalog labels in a different font, order, and spacing. A high score there shows the parser is not tied to the generator's coordinates. It still depends on those labels.
- dev_statement is a development layout with different wording. Those captions were inspected during development, so the score is not a blind test. The extractor is not given the caption strings. The held-out set is scored by an independent reviewer; not in this repo.
- No roster was passed. Every name, street, city, state, and ZIP stays in review, with a no_roster finding. That is by design.
