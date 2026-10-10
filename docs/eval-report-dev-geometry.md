# K1-Lens evaluation report

Synthetic data only. These numbers are from a corpus generated from the seed
and the deterministic extractor unless the header says otherwise.

## Run

- Backend: `deterministic`
- Fixtures: `fixtures/dev_geometry`
- Seed: 1065
- Documents: 12
- OCR enabled: yes
- Tesseract: tesseract 5.3.4
- Roster: none
- Confidently read ids: 24 of 24 sections
- Money tolerance: 1.00
- Distribution: `dev_geometry`
- Review threshold: 0.80

## Overall

| Metric | Value |
| --- | --- |
| Comparisons | 767 |
| Accuracy | 100.0% (767/767) |
| Precision | 100.0% (767/767) |
| Recall | 100.0% (767/767) |
| Correct | 767 |
| Both null | 0 |
| Mismatch | 0 |
| Missed | 0 |
| Spurious | 0 |
| Straight-through | 0.0% (0/12) |

Straight-through counts documents that need no review. Field accuracy above
counts fields. A document can be field-accurate and still fail a required-field
rule, including a missing tax year.

## By source

Text layer is every variant that still has text. Image-only variants are
`rasterized` and `scan_*`. Those pages are read with Tesseract. Overall
is the two together.

| Scope | Comparisons | Accuracy | Precision | Recall |
| --- | --- | --- | --- | --- |
| text layer | 767 | 100.0% (767/767) | 100.0% (767/767) | 100.0% (767/767) |
| rasterized | 0 | n/a | n/a | n/a |
| overall | 767 | 100.0% (767/767) | 100.0% (767/767) | 100.0% (767/767) |

## Review flags

The review UI highlights a field when its confidence is below 0.80.
A wrong value is a mismatch or a spurious extraction.
An incorrect comparison also includes a miss.
OCR fields routed to review: 0/0.

| Scope | Wrong values flagged | Incorrect comparisons flagged |
| --- | --- | --- |
| text layer | n/a | n/a |
| rasterized | n/a | n/a |
| overall | n/a | n/a |

## Reliability

Text-layer confidence takes few distinct values because the signals are coarse:
an exact label, one proximity bin for a normal line, and a format check.
This is a reliability table for those levels, not a fitted probability.
Each comparison falls in the bucket of the confidence the extractor stored.
An error is a mismatch, a miss, or a spurious value.
The lowest populated bucket (0.40-0.59) has error rate 0.0% (0/121), which is the same as the highest populated bucket (0.80-1.00) at 0.0% (0/304). A format failure, an item L mismatch, or an untested item L account can also lower confidence on a value that still matches the facsimile, so a middle bucket can be mostly correct.
Distinct confidence values: 18. Expected calibration error (bucket ECE): 0.211.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 0 | n/a | n/a | 0 | n/a |
| 0.20-0.39 | 0 | n/a | n/a | 0 | n/a |
| 0.40-0.59 | 121 | 0.490 | 100.0% (121/121) | 0 | 0.0% (0/121) |
| 0.60-0.79 | 342 | 0.784 | 100.0% (342/342) | 0 | 0.0% (0/342) |
| 0.80-1.00 | 304 | 0.914 | 100.0% (304/304) | 0 | 0.0% (0/304) |

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
| box_grid | 133 | 100.0% (133/133) | 100.0% (133/133) | 100.0% (133/133) | 0.0% (0/2) |
| face_aligned | 124 | 100.0% (124/124) | 100.0% (124/124) | 100.0% (124/124) | 0.0% (0/2) |
| stacked | 124 | 100.0% (124/124) | 100.0% (124/124) | 100.0% (124/124) | 0.0% (0/2) |
| stacked_columns | 130 | 100.0% (130/130) | 100.0% (130/130) | 100.0% (130/130) | 0.0% (0/2) |
| statement_columns | 131 | 100.0% (131/131) | 100.0% (131/131) | 100.0% (131/131) | 0.0% (0/2) |
| two_column | 125 | 100.0% (125/125) | 100.0% (125/125) | 100.0% (125/125) | 0.0% (0/2) |

## By field

| Field | Comparisons | Accuracy | Precision | Recall | Missed | Mismatch |
| --- | --- | --- | --- | --- | --- | --- |
| `part_i.ein` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.name` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.street` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.city` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.state` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.zip_code` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.irs_center` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.is_ptp` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.tin` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.name` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.street` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.city` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.state` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.zip_code` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.is_general_partner` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.is_domestic` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.entity_type` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.is_retirement_plan` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.profit_beginning` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.profit_ending` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.loss_beginning` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.loss_ending` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital_share_beginning` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital_share_ending` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.liability_nonrecourse` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.liability_qualified_nonrecourse` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.liability_recourse` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital_method` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.beginning` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.contributed` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.current_year_net_income` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.other_increase_decrease` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.withdrawals` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.capital.ending` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.contributed_builtin_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.ordinary_business_income` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.net_rental_real_estate` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.other_net_rental` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.guaranteed_payments_services` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.guaranteed_payments_capital` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.guaranteed_payments_total` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.interest_income` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.ordinary_dividends` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.qualified_dividends` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.dividend_equivalents` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.royalties` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.net_short_term_capital_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.net_long_term_capital_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.collectibles_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.unrecaptured_1250_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.net_section_1231_gain` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.section_179_deduction` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.schedule_k3_attached` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.foreign_taxes_paid` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `tax_year` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.amt_items[B]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.distributions[C]` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.distributions[A]` | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_iii.other_income[B]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.other_income[C]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_income[E]` | 5 | 100.0% (5/5) | 100.0% (5/5) | 100.0% (5/5) | 0 | 0 |
| `part_iii.other_deductions[W]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.other_deductions[B]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_deductions[A]` | 7 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 0 | 0 |
| `part_iii.amt_items[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.amt_items[C]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_income[A]` | 5 | 100.0% (5/5) | 100.0% (5/5) | 100.0% (5/5) | 0 | 0 |
| `part_iii.credits[P]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[B]` | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[A]` | 7 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[C]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.other_information[B]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_information[N]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_deductions[I]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_deductions[H]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.credits[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.credits[C]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.other_information[V]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_information[A]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_income[F]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_information[Z]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.self_employment[A]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.self_employment[C]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |

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
- fixtures/dev_geometry is a round-trip set. It prints the same catalog strings the extractor already lists, from seed 1065, with no colon: a right-aligned amount, a box grid, two columns on one baseline, a statement that mixes those, and a label with the amount on the next line in the same column. It is not evidence for an unseen layout. The held-out set is scored by an independent reviewer; not in this repo.
- A wide gap between a label and a right-aligned amount lowers proximity, so a correct value can stay under 0.80. A value on the next line in that caption's column is the field's own box. Name, street, city, state, and ZIP stay under 0.80 unless a confident id and a full exact match lift that section to exactly the review threshold. A partial match lifts nothing. The weights were not refit.
- No roster was passed. Every name, street, city, state, and ZIP stays in review, with a no_roster finding. That is by design.
