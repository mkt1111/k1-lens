# K1-Lens evaluation report

Synthetic data only. These numbers are from a corpus generated from the seed
and the deterministic extractor unless the header says otherwise.

## Run

- Backend: `deterministic`
- Fixtures: `fixtures/synthetic`
- Seed: 1065
- Documents: 14
- OCR enabled: yes
- Tesseract: tesseract 5.3.4
- Roster: none
- Confidently read ids: 21 of 28 sections
- Money tolerance: 1.00
- Distribution: `in_distribution`
- Review threshold: 0.80

## Overall

| Metric | Value |
| --- | --- |
| Comparisons | 890 |
| Accuracy | 99.3% (884/890) |
| Precision | 99.9% (878/879) |
| Recall | 99.3% (878/884) |
| Correct | 878 |
| Both null | 6 |
| Mismatch | 1 |
| Missed | 5 |
| Spurious | 0 |
| Straight-through | 0.0% (0/14) |

Straight-through counts documents that need no review. Field accuracy above
counts fields. A document can be field-accurate and still fail a required-field
rule, including a missing tax year.

## By source

Text layer is every variant that still has text. Image-only variants are
`rasterized` and `scan_*`. Those pages are read with Tesseract. Overall
is the two together.

| Scope | Comparisons | Accuracy | Precision | Recall |
| --- | --- | --- | --- | --- |
| text layer | 759 | 100.0% (759/759) | 100.0% (753/753) | 100.0% (753/753) |
| rasterized | 131 | 95.4% (125/131) | 99.2% (125/126) | 95.4% (125/131) |
| overall | 890 | 99.3% (884/890) | 99.9% (878/879) | 99.3% (878/884) |

## Review flags

The review UI highlights a field when its confidence is below 0.80.
A wrong value is a mismatch or a spurious extraction.
An incorrect comparison also includes a miss.
OCR fields routed to review: 39/128.

| Scope | Wrong values flagged | Incorrect comparisons flagged |
| --- | --- | --- |
| text layer | n/a | n/a |
| rasterized | 100.0% (1/1) | 100.0% (6/6) |
| overall | 100.0% (1/1) | 100.0% (6/6) |

## Reliability

Text-layer confidence takes few distinct values because the signals are coarse:
an exact label, one proximity bin for a normal line, and a format check.
This is a reliability table for those levels, not a fitted probability.
Each comparison falls in the bucket of the confidence the extractor stored.
An error is a mismatch, a miss, or a spurious value.
The lowest populated bucket (0.00-0.19) has error rate 45.5% (5/11), which is higher than the highest populated bucket (0.80-1.00) at 0.0% (0/594). A format failure, an item L mismatch, or an untested item L account can also lower confidence on a value that still matches the facsimile, so a middle bucket can be mostly correct.
Distinct confidence values: 83. Expected calibration error (bucket ECE): 0.213.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 11 | 0.005 | 54.5% (6/11) | 5 | 45.5% (5/11) |
| 0.20-0.39 | 0 | n/a | n/a | 0 | n/a |
| 0.40-0.59 | 250 | 0.491 | 100.0% (250/250) | 0 | 0.0% (0/250) |
| 0.60-0.79 | 35 | 0.701 | 97.1% (34/35) | 1 | 2.9% (1/35) |
| 0.80-1.00 | 594 | 0.920 | 100.0% (594/594) | 0 | 0.0% (0/594) |

## Validation catch rate

Caught means the rules engine emitted an error whose rule id is the planted defect.
Ground truth measures the rules. Post-extraction measures whether the defect
is still visible after extraction.

| Scope | Value |
| --- | --- |
| Ground truth | 100.0% (6/6) |
| Post-extraction | 100.0% (6/6) |

## By variant

| Variant | Comparisons | Accuracy | Precision | Recall | Straight-through |
| --- | --- | --- | --- | --- | --- |
| clean | 257 | 100.0% (257/257) | 100.0% (257/257) | 100.0% (257/257) | 0.0% (0/4) |
| inconsistent_capital | 130 | 100.0% (130/130) | 100.0% (130/130) | 100.0% (130/130) | 0.0% (0/2) |
| invalid_ein | 60 | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) | 0.0% (0/1) |
| invalid_percentage | 63 | 100.0% (63/63) | 100.0% (63/63) | 100.0% (63/63) | 0.0% (0/1) |
| missing_fields | 124 | 100.0% (124/124) | 100.0% (118/118) | 100.0% (118/118) | 0.0% (0/2) |
| rasterized | 131 | 95.4% (125/131) | 99.2% (125/126) | 95.4% (125/131) | 0.0% (0/2) |
| rotated | 125 | 100.0% (125/125) | 100.0% (125/125) | 100.0% (125/125) | 0.0% (0/2) |

## By field

| Field | Comparisons | Accuracy | Precision | Recall | Missed | Mismatch |
| --- | --- | --- | --- | --- | --- | --- |
| `part_i.ein` | 14 | 100.0% (14/14) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_i.name` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.street` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.city` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.state` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.zip_code` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.irs_center` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_i.is_ptp` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.tin` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.name` | 14 | 100.0% (14/14) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.street` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.city` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.state` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.zip_code` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.is_general_partner` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.is_domestic` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.entity_type` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.is_retirement_plan` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.profit_beginning` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.profit_ending` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.loss_beginning` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.loss_ending` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital_share_beginning` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital_share_ending` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.liability_nonrecourse` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.liability_qualified_nonrecourse` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.liability_recourse` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital_method` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital.beginning` | 14 | 92.9% (13/14) | 100.0% (13/13) | 92.9% (13/14) | 1 | 0 |
| `part_ii.capital.contributed` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital.current_year_net_income` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital.other_increase_decrease` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_ii.capital.withdrawals` | 14 | 92.9% (13/14) | 100.0% (13/13) | 92.9% (13/14) | 1 | 0 |
| `part_ii.capital.ending` | 14 | 100.0% (14/14) | 100.0% (12/12) | 100.0% (12/12) | 0 | 0 |
| `part_ii.contributed_builtin_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.ordinary_business_income` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.net_rental_real_estate` | 14 | 92.9% (13/14) | 92.9% (13/14) | 92.9% (13/14) | 0 | 1 |
| `part_iii.other_net_rental` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.guaranteed_payments_services` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.guaranteed_payments_capital` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.guaranteed_payments_total` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.interest_income` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.ordinary_dividends` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.qualified_dividends` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.dividend_equivalents` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.royalties` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.net_short_term_capital_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.net_long_term_capital_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.collectibles_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.unrecaptured_1250_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.net_section_1231_gain` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.section_179_deduction` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.schedule_k3_attached` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.foreign_taxes_paid` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `tax_year` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.amt_items[B]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.distributions[C]` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.distributions[A]` | 14 | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 0 | 0 |
| `part_iii.other_income[B]` | 4 | 75.0% (3/4) | 100.0% (3/3) | 75.0% (3/4) | 1 | 0 |
| `part_iii.other_income[C]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.other_income[E]` | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0 | 0 |
| `part_iii.other_deductions[W]` | 5 | 100.0% (5/5) | 100.0% (5/5) | 100.0% (5/5) | 0 | 0 |
| `part_iii.other_deductions[B]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_deductions[A]` | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 0 |
| `part_iii.amt_items[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.amt_items[C]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_income[A]` | 7 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 0 | 0 |
| `part_iii.credits[P]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[B]` | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0 | 0 |
| `part_iii.tax_exempt_and_nondeductible[A]` | 7 | 85.7% (6/7) | 100.0% (6/6) | 85.7% (6/7) | 1 | 0 |
| `part_iii.tax_exempt_and_nondeductible[C]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.other_information[B]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_information[N]` | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) | 0 | 0 |
| `part_iii.other_deductions[I]` | 3 | 66.7% (2/3) | 100.0% (2/2) | 66.7% (2/3) | 1 | 0 |
| `part_iii.other_deductions[H]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.credits[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.credits[C]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.other_information[V]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_information[A]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_income[F]` | 1 | 100.0% (1/1) | 100.0% (1/1) | 100.0% (1/1) | 0 | 0 |
| `part_iii.other_information[Z]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.self_employment[A]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |
| `part_iii.self_employment[C]` | 2 | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) | 0 | 0 |

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
- In-distribution text-layer documents use the same label catalog the generator prints. A high score shows that catalog round-trips. It does not show that the extractor can read unseen wording. dev_statement and fixtures/dev_b were both inspected, so they are development scores. The held-out set is scored by an independent reviewer; not in this repo.
- Rasterized documents have no text layer and are read with Tesseract. OCR confidence follows word confidence. It is not capped under the review threshold.
- A 1.2 degree rotation still has a text layer, so the strings still parse. Word boxes on one printed line no longer share a baseline, so the extractor cannot confirm that the value sits with its label. Those fields are capped below the review threshold.
- No roster was passed. Every name, street, city, state, and ZIP stays in review, with a no_roster finding. That is by design.
