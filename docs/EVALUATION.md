# Evaluation

The headline table in the README is the deterministic run with no roster. Backend: deterministic. Seed: 1065. Review threshold: 0.80. Tesseract: 5.3.4 on this measurement and on the Ubuntu CI runner. Another box measures differently on Tesseract 5.5.0. Live confident-wrong is 0 on hybrid and on llm, in both runs, on every repository set. Those figures were measured on the pre-release source of v0.1.0 (src/ differs from the tag only in one docstring). The report is [docs/eval-live/report.md](eval-live/report.md). With no key, `uv run k1lens eval --backend hybrid --live` exits and does not call a model.

In-distribution figures are copied from [`docs/eval-report.md`](eval-report.md). The `fixtures/dev` figures are copied from [`docs/eval-report-dev.md`](eval-report-dev.md). The `fixtures/dev_b` figures are copied from [`docs/eval-report-dev-b.md`](eval-report-dev-b.md). The colon-free figures are copied from [`docs/eval-report-dev-geometry.md`](eval-report-dev-geometry.md). The scan figures are copied from [`docs/eval-report-scans.md`](eval-report-scans.md). Those five files are the no-roster measurement. Backend: deterministic. Seed: 1065. OCR: yes. Tesseract: 5.3.4. Money tolerance: 1.00. Review threshold: 0.80. Document straight-through is the share of documents that pass with no review: no error-severity finding and no field, including tax year, under 0.80. Field straight-through is the share of comparisons stored at or above 0.80. Warnings do not block. Field accuracy is a different number. The held-out set is scored by an independent reviewer; not in this repo.

Name, street, city, state, and ZIP are lifted to exactly 0.80, and not higher, only when a roster is passed, the key id was read confidently and passes the format check, and every field in that section matches the same record. Each value has to be read from its own field region, with no fallback, repair, or model value. A partial match lifts nothing. The partnership section is keyed by the EIN. The partner section is keyed by the TIN. Entity type is not in that set. The form prints no options for that item, and a roster match does not clear it. The value stored is the page string. The roster value is never written back. Each lifted field is an audit row whose action is `roster_exact_match`. A lift needs a confident id plus a full exact match. Unseen layouts are not supported. Without a roster the finding is `no_roster` and every identity field stays in review. A confident key with no record is `new_partner`, and document straight-through on that document is 0 by design. Two roster records with the same EIN or TIN are `duplicate_roster_key` and are not a match.

The id check is a format check: nine digits, the EIN pattern `NN-NNNNNNN` or the SSN pattern `NNN-NN-NNNN`, and not masked. EINs that start with `00-` and SSNs that start with `000-` are accepted. Those ranges are obviously synthetic. They are not issued by the IRS or SSA. A masked id (asterisks, Xs, or only the last four digits) is `no_tin` and is not used as a key. Digits are not repaired, guessed, or check-digit-corrected. If OCR word confidence on any id digit is under 0.80, the id is not a match (`no_roster_match`). Each report header counts sections that had a confidently read id. That count does not depend on whether a roster was passed.

A blank field on the page against a complete roster record is `identity_mismatch`. ZIP matches after whitespace is removed, and the hyphen stays, so ZIP5 does not match ZIP+4. Adding or dropping a middle initial is a mismatch. Names, streets, cities, and states match after case and repeated whitespace are folded, and nothing else. A roster record with a blank field cannot clear that field, and the whole section stays under 0.80. The right id with the wrong name, the right id with the wrong address, and a name that belongs to a different record are `identity_mismatch`. A low-confidence id, including a well-formed text-layer read under 0.80, is not a key. An invalid id is not a key. Nothing lifts on a partial match. The stored value stays the page string when the roster differs only in case or spacing.

### How the roster was built

`k1lens write-roster --fixtures DIR --out PATH` copies partnership and investor identity from that corpus's ground-truth JSON. The written file says those documents' identity was known before scoring. `evaluate()` does not build a roster and does not read ground truth into one. The with-roster column below is that file, passed as `k1lens eval --roster PATH`. `fixtures/example-roster.json` is a separate example (EIN `00-9000001`, SSN `000-90-0001`). Eval does not load it unless you pass it. A test scores one clean document against that example, and straight-through is 0.

The same flag is `k1lens extract --roster`, `k1lens validate --roster`, and `k1lens serve --roster`. `K1LENS_ROSTER` is the same path. `POST /api/roster` takes the roster JSON.

### Without a roster

| Set | Accuracy | Precision | Field straight-through | Document straight-through | Confident wrong | Confidently read ids |
| --- | --- | --- | --- | --- | --- | --- |
| In distribution | 99.3% (884/890) | 99.9% (878/879) | 594/890 | 0.0% (0/14) | 0 | 21 of 28 |
| Development layouts | 68.0% (349/513) | 100.0% (349/349) | 217/513 | 0.0% (0/8) | 0 | 8 of 16 |
| dev_b | 98.4% (253/257) | 100.0% (253/253) | 213/257 | 0.0% (0/4) | 0 | 8 of 8 |
| Colon-free layouts | 100.0% (767/767) | 100.0% (767/767) | 304/767 | 0.0% (0/12) | 0 | 24 of 24 |
| Scanned images | 54.8% (1048/1914) | 98.8% (1048/1061) | 596/1914 | 0.0% (0/30) | 0 | 21 of 60 |

The 0.80 bucket has 0 errors on every set. Accuracy and precision are the page read. They do not change when a roster is passed, because the stored string is not replaced.

### With a roster built from that set's ground truth

Identity on these documents was known before scoring. Document straight-through rises only where the whole section matched and no other gate remained.

| Set | Field straight-through | Document straight-through | Confident wrong | 0.80 bucket errors |
| --- | --- | --- | --- | --- |
| In distribution | 689/890 | 28.6% (4/14), clean 4/4 | 0 | 0 |
| Development layouts | 257/513 | 50.0% (4/8), layout_shift 4/4 | 0 | 0 |
| dev_b | 253/257 | 0.0% (0/4) | 0 | 0 |
| Colon-free layouts | 424/767 | 25.0% (3/12) | 0 | 0 |
| Scanned images | 691/1914 | 0.0% (0/30) | 0 | 0 |

`dev_statement` stays 0/4 because the layout is unrecognized, so the roster match does not lift those fields. `dev_b` stays 0/4 because the tax year is missed. Colon-free document straight-through is `stacked` 2/2 and `stacked_columns` 1/2. The same-line layouts stay in review because a wide gap keeps correct amounts at 0.784. Scans stay 0/30.

### Unseen roster entries

A document whose EIN and TIN are absent from the roster is `new_partner`. Document straight-through is 0 by design. The example roster is that case for the generated corpora. The full sets below were not re-scored against the example file. One clean document was, and straight-through was 0.

### In distribution

Fixtures: `fixtures/synthetic`. Documents: 14. The generator and the extractor share one label catalog. Confidently read ids: 21 of 28 sections.

| Scope | Comparisons | Accuracy | Precision | Recall | Straight-through |
| --- | --- | --- | --- | --- | --- |
| Text layer | 759 | 100.0% (759/759) | 100.0% (753/753) | 100.0% (753/753) | 0.0% (0/12) |
| Rasterized (OCR) | 131 | 95.4% (125/131) | 99.2% (125/126) | 95.4% (125/131) | 0.0% (0/2) |
| Overall | 890 | 99.3% (884/890) | 99.9% (878/879) | 99.3% (878/884) | 0.0% (0/14) |

Overall counts: correct 878, both null 6, mismatch 1, missed 5, spurious 0. Tax year is 14/14. With no roster, straight-through is 0.0% (0/14). The straight-through floor is 0.0, this measured rate. It is a minimum and has no ceiling. Accuracy and precision floors did not move. With the ground-truth roster, straight-through is 4/14, all four of them the clean variant. Text-layer straight-through on that pass is 4/12. Rasterized stays 0/2.

| Variant | Comparisons | Accuracy | Precision | Recall | Straight-through, no roster | Straight-through, ground-truth roster |
| --- | --- | --- | --- | --- | --- | --- |
| clean | 257 | 100.0% (257/257) | 100.0% (257/257) | 100.0% (257/257) | 0.0% (0/4) | 100.0% (4/4) |
| inconsistent_capital | 130 | 100.0% (130/130) | 100.0% (130/130) | 100.0% (130/130) | 0.0% (0/2) | 0.0% (0/2) |
| invalid_ein | 60 | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) | 0.0% (0/1) | 0.0% (0/1) |
| invalid_percentage | 63 | 100.0% (63/63) | 100.0% (63/63) | 100.0% (63/63) | 0.0% (0/1) | 0.0% (0/1) |
| missing_fields | 124 | 100.0% (124/124) | 100.0% (118/118) | 100.0% (118/118) | 0.0% (0/2) | 0.0% (0/2) |
| rasterized | 131 | 95.4% (125/131) | 99.2% (125/126) | 95.4% (125/131) | 0.0% (0/2) | 0.0% (0/2) |
| rotated | 125 | 100.0% (125/125) | 100.0% (125/125) | 100.0% (125/125) | 0.0% (0/2) | 0.0% (0/2) |

The text-layer score shows that the shared label catalog round-trips. The same strings are printed by the generator and read by the extractor. That score is evidence the plumbing works. It is weak evidence about a K-1 whose labels were not in that catalog. The rotated documents are inside that 100% text-layer score. A 1.2° rotation still leaves a text layer, so the values parse, and rotated field accuracy is 100.0% (125/125). The word boxes on one printed line no longer share a baseline, so those fields are not anchored to the label. They are not that field's own region, and a roster match does not lift them. Rotated straight-through is 0.0% (0/2) either way.

The rasterized errors are six comparisons on the two scans, and all six were flagged for review: 100.0% (6/6). One is a mismatch. On K1-0008, box 2 is 12239 on the facsimile and was read as 1239.00 at confidence 0.78. The other five are misses: item L beginning and withdrawals on K1-0007 did not parse, and three coded lines whose labels were not recovered (confidence 0). Those two item L lines are confidence 0.03 after the untested-account penalty. Scoring tax year added two correct OCR comparisons, so rasterized accuracy is 95.4% (125/131). The six errors are the same six. With no roster, OCR fields routed to review are 39/128. With the ground-truth roster, 19/128. Spurious values: 0.

Text-layer confidence uses coarse signals, so many text fields share a level. An exact catalog label, proximity 1, a text-layer source, and a successful parse with no format rule land at 0.92. A format check adds 0.08. With no roster, identity fields are then capped under 0.80. Across the whole run there are 83 distinct confidence values. Bucket expected calibration error is 0.213. This table is a reliability check of those stored levels. It is not a fitted probability.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 11 | 0.005 | 54.5% (6/11) | 5 | 45.5% (5/11) |
| 0.20-0.39 | 0 | n/a | n/a | 0 | n/a |
| 0.40-0.59 | 250 | 0.491 | 100.0% (250/250) | 0 | 0.0% (0/250) |
| 0.60-0.79 | 35 | 0.701 | 97.1% (34/35) | 1 | 2.9% (1/35) |
| 0.80-1.00 | 594 | 0.920 | 100.0% (594/594) | 0 | 0.0% (0/594) |

Every extraction error is below 0.80. The top bucket has zero errors in 594 comparisons. The 0.60-0.79 error is the K1-0008 box 2 mismatch. The six both-null rows in 0.00-0.19 are the planted missing fields. The two K1-0007 item L parse failures sit in that same bucket at 0.03. With the ground-truth roster the 0.40-0.59 bucket is 155 comparisons at mean 0.492, all correct, the 0.60-0.79 bucket is unchanged, and the 0.80-1.00 bucket is 689 comparisons at mean 0.904 with 0 errors. A lifted field is stored at exactly 0.80, which is why that mean is lower than the no-roster top bucket. Distinct confidence values on that pass: 84. Expected calibration error: 0.180.

### Development layouts

Fixtures: `fixtures/dev`. Documents: 8. Four are `layout_shift`: the catalog labels, in Times, in a different order, with wider spacing. Four are `dev_statement`: a second layout whose captions are not in the extractor catalog. Those captions were inspected, so this layout is a development set. The extractor is not given the caption strings. `dev_statement` is set in Courier. `fixtures/dev_b` is scored in the next section. It is not part of this table. Confidently read ids: 8 of 16 sections.

This directory was previously `fixtures/heldout`, and the eval distribution was `held_out`. That name was wrong: both layouts were available while the extractor was being written, and `dev_statement` was inspected. The rename does not change the measured rates below. The held-out set is scored by an independent reviewer; not in this repo.

| Scope | Comparisons | Accuracy | Precision | Recall | Straight-through, no roster | Straight-through, ground-truth roster |
| --- | --- | --- | --- | --- | --- | --- |
| layout_shift | 257 | 100.0% (257/257) | 100.0% (257/257) | 100.0% (257/257) | 0.0% (0/4) | 100.0% (4/4) |
| dev_statement | 256 | 35.9% (92/256) | 100.0% (92/92) | 35.9% (92/256) | 0.0% (0/4) | 0.0% (0/4) |
| Development layouts | 513 | 68.0% (349/513) | 100.0% (349/349) | 68.0% (349/513) | 0.0% (0/8) | 50.0% (4/8) |

`layout_shift` at 100.0% (257/257) shows the line parser is not tied to the generator's coordinates. It still uses the shared labels, so it is the same kind of evidence as the in-distribution text layer. With no roster those four documents stay in review. With the ground-truth roster they clear. `dev_statement` at 35.9% (92/256) is the development-set score. Precision is 100.0% (92/92): mismatch 0, spurious 0, missed 164. Four of those misses are the tax year. The statement prints `Form year` with no colon, so it is not a labeled line. The 92 hits are real reads of wording that overlaps the public line names. Four of them are the retirement-plan line: the public caption "if this partner is a retirement plan" overlaps the inspected wording "Retirement plan partner flag". That fixture caption was not added as an alias. They are not a blind test, because those captions were inspected. The layout is unrecognized, so a roster match does not lift it. Straight-through on those four documents is 0.0% (0/4) either way. There is no rasterized document in this set.

With no roster, the 92 correct statement values and the held identity fields sit in 0.40-0.59: 132 comparisons, mean confidence 0.490, error rate 0.0% (0/132). The 164 misses sit in 0.00-0.19. 217 comparisons sit in 0.80-1.00, mean confidence 0.936, error rate 0.0% (0/217). Distinct confidence values: 4. Expected calibration error: 0.158. With the ground-truth roster, 0.40-0.59 is the 92 statement values, 0.80-1.00 is 257 comparisons at mean 0.915 with 0 errors, distinct confidence values are 5, and expected calibration error is 0.134. A correct number on an unrecognized layout is still sent to a person.

### Development set

Fixtures: `fixtures/dev_b`. Documents: 4, variant `dev_b`. This is a Harbor Lane supplemental statement: box and line numbers, with abbreviated line names, in a different order from the catalog. It was seen during development. The amounts are the in-distribution records K1-0001 through K1-0004 with the captions changed. The typeface is Helvetica, the same family as those facsimiles. This section reports a seen development set. The matcher does not contain the caption strings. Abbreviations in the matcher are only ones sourced from the public IRS Schedule K-1 (Form 1065) instructions or from general accounting usage, and each key is labeled with that category in `extract/labels.py`. Confidently read ids: 8 of 8 sections.

| Scope | Comparisons | Accuracy | Precision | Recall | Straight-through |
| --- | --- | --- | --- | --- | --- |
| dev_b | 257 | 98.4% (253/257) | 100.0% (253/253) | 98.4% (253/257) | 0.0% (0/4) |

Spurious 0. Mismatch 0. Missed 4, all `tax_year`. The year caption is `Reporting period`, not `TAX YEAR`, so the tax year is missed on every document. That miss fails `required_fields` with "Tax year is missing." Straight-through is 0.0% (0/4) with a roster and without one. Field accuracy of 98.4% (253/257) would hide that rate if tax year were left unscored. With no roster, 213 comparisons sit in 0.80-1.00, mean confidence 0.924, error rate 0.0% (0/213), and 40 identity fields sit in 0.40-0.59 at 0.49. Distinct confidence values: 6. Expected calibration error: 0.142. With the ground-truth roster those identity fields are lifted to exactly 0.80: 253 comparisons sit in 0.80-1.00, mean confidence 0.905, error rate 0.0% (0/253). Distinct confidence values: 6. Expected calibration error: 0.094. The layout is recognized. This number shows that this seen caption style, with public box numbers and the sourced abbreviations, round-trips on the text layer except for the year caption. It does not show performance on an unseen K-1. The caption was not added as an alias.

### Colon-free development layouts

Fixtures: `fixtures/dev_geometry`. Documents: 12. This is a round-trip set. It prints the same catalog strings the extractor lists, from seed 1065. It is not evidence for an unseen layout. Two of each layout: `face_aligned` puts the catalog label on the left and the amount right-aligned, with no colon; `box_grid` rules a box, a description, and an amount; `two_column` puts two pairs on one baseline; `statement_columns` prints Part I and Part II in one column and Part III in two; `stacked` puts the catalog label on one line and the amount on the next line in the same column; `stacked_columns` puts two labels on one baseline and each amount on the next line under its label. The held-out set is scored by an independent reviewer; not in this repo. Confidently read ids: 24 of 24 sections.

| Scope | Comparisons | Accuracy | Precision | Recall | Straight-through, no roster | Straight-through, ground-truth roster |
| --- | --- | --- | --- | --- | --- | --- |
| face_aligned | 124 | 100.0% (124/124) | 100.0% (124/124) | 100.0% (124/124) | 0.0% (0/2) | 0.0% (0/2) |
| box_grid | 133 | 100.0% (133/133) | 100.0% (133/133) | 100.0% (133/133) | 0.0% (0/2) | 0.0% (0/2) |
| two_column | 125 | 100.0% (125/125) | 100.0% (125/125) | 100.0% (125/125) | 0.0% (0/2) | 0.0% (0/2) |
| statement_columns | 131 | 100.0% (131/131) | 100.0% (131/131) | 100.0% (131/131) | 0.0% (0/2) | 0.0% (0/2) |
| stacked | 124 | 100.0% (124/124) | 100.0% (124/124) | 100.0% (124/124) | 0.0% (0/2) | 100.0% (2/2) |
| stacked_columns | 130 | 100.0% (130/130) | 100.0% (130/130) | 100.0% (130/130) | 0.0% (0/2) | 50.0% (1/2) |
| Colon-free layouts | 767 | 100.0% (767/767) | 100.0% (767/767) | 100.0% (767/767) | 0.0% (0/12) | 25.0% (3/12) |

Mismatch 0. Spurious 0. Missed 0. With no roster, field straight-through is 304/767 and document straight-through is 0.0% (0/12). 342 of the 767 correct fields sit in 0.60-0.79, mean confidence 0.784. A right-aligned amount is a wide gap. Once that gap is 120 points or more, proximity is 0.15. An exact label (0.40), that proximity (0.024), a text-layer source (0.24), and a successful parse (0.12) sum to 0.784, under 0.80. Column membership chooses the value. It is not scored as proximity 1, and the weights were not refit to make an in-column label clear review. 121 correct fields sit in 0.40-0.59 at mean 0.490. That bucket holds identity fields, which stay under 0.80 because no roster was passed, and the E-file IRS center. 304 fields sit in 0.80-1.00 at mean 0.914, with 0 errors. Distinct confidence values: 18. Expected calibration error: 0.211.

With the ground-truth roster, field straight-through is 424/767. 342 comparisons sit in 0.60-0.79 at mean 0.784. One comparison stays in 0.40-0.59 at 0.490. 424 sit in 0.80-1.00 at mean 0.882, with 0 errors. Distinct confidence values: 19. Expected calibration error: 0.162. Document straight-through is 3/12. The same-line documents stay in review because those amounts stay at 0.784. A production calibration step would fit that proximity weight, or the review threshold, on a reviewed gold set, not on this generator.

A value on the next line is paired only with words that start inside that caption's column, before the next caption. `dev_statement` still misses its capital lines because those captions are not catalog labels or public line names, and they were not added. A bare box letter plus an amount is not a Part I box: `C 824.00` is a code and an amount, not the IRS center. A bare box number plus an amount is read when the value fits that box. This section does not measure an unseen K-1 face.

Accuracy is `(correct + both null) / comparisons`. Precision is `correct / (correct + mismatch + spurious)`. Recall is `correct / (correct + mismatch + missed)`. Straight-through is documents with no review needed, divided by documents. Caught means validation emitted an error whose rule id is the planted defect. The six planted defects are two missing-field documents, two inconsistent capital accounts, one invalid EIN, and one profit percentage of 140. CI runs the in-distribution eval, `fixtures/dev`, `fixtures/dev_geometry`, and `fixtures/dev_b`, and fails if a headline in [`docs/eval-baseline.json`](eval-baseline.json) drops under its floor. Those CI runs pass no roster. Precision floors are 1.0 on the text-layer set, on `fixtures/dev`, on `dev_statement`, on `dev_b`, and on `fixtures/dev_geometry`. The rasterized accuracy floor is 0.90, under the measured 95.4% (125/131), and its precision floor is 0.95, under the measured 99.2% (125/126). The text-layer accuracy floor is 1.0. The `dev_b` accuracy floor is 0.984, the measured 98.4% (253/257). The colon-free accuracy floor is 1.0. This run measured 100.0% (767/767). Straight-through floors are 0.0 (0/14), 0.0 (0/8), 0.0 (0/4), and 0.0 (0/12). They are minimums and have no ceilings. Accuracy and precision floors did not move. A floor of 0 cannot fail if straight-through rises, so a unit test locks the `dev_b` rate at 0. A pass there guards this seen set. It is not a blind-test claim.

The reports were measured with Tesseract 5.3.4, and each report header records `tesseract --version`. Ubuntu 24.04 CI installs the distro `tesseract-ocr` package and prints that version. That package is 5.3.4 here. Another box measures differently on Tesseract 5.5.0. The Docker image uses Debian bookworm's Tesseract 5.3.0. CI does not build that image. CI is not pinned to 5.3.0, and it does not install 5.5.0, because that would mean installing a foreign package or rebuilding Tesseract. Rasterized accuracy and precision floors sit under the 5.3.4 rates, so a small accuracy move from a one-version OCR disagreement does not fail those floors. `max_confident_wrong` is not one of those floors. It is a ceiling of 0, measured on 5.3.4. A state token is checked against the USPS two-letter list. A mixed-case value that is still one of those codes is stored uppercase, so `Ca` becomes `CA` and is not a confident wrong. A token that is not on the list fails the format check and stays under 0.80. That is the check for a Tesseract build that emits mixed-case state codes. A collapse of image-only accuracy still fails the accuracy floors.

### Image-only scans

The two in-distribution rasterized pages are K1-0007 and K1-0008. They are generated from the seed with the rest of that corpus. The OCR measurement is a separate set of 30 image-only documents, generated in CI from seed 1065. The PDFs are not stored in the repository. `k1lens generate --scans` rewrites them. Figures are copied from [`docs/eval-report-scans.md`](eval-report-scans.md). Tesseract 5.3.4. Twenty-four are mild scans: eight catalog, eight `dev_statement`, and eight `dev_b`. Six more are catalog pages damaged on purpose. `dev_statement` and `dev_b` were seen. The held-out set is scored by an independent reviewer; not in this repo. Confidently read ids: 21 of 60 sections, with a roster and without one.

Each mild scan varies DPI from 150 to 300, a rotation of a few degrees, a small skew, noise, blur, and JPEG compression. Three of those scans, one in each layout, are faint: contrast 0.42, brightness 0.72, JPEG quality 40. Those three were read at 0.0%. EINs use the `00-` prefix. Those prefixes are obviously synthetic. They are not issued by the IRS or SSA.

| Scope | Comparisons | Accuracy | Precision | Recall | Straight-through |
| --- | --- | --- | --- | --- | --- |
| catalog | 503 | 81.1% (408/503) | 97.8% (408/417) | 81.1% (408/503) | 0.0% (0/8) |
| dev_b | 515 | 84.7% (436/515) | 100.0% (436/436) | 84.7% (436/515) | 0.0% (0/8) |
| dev_statement | 515 | 27.0% (139/515) | 97.2% (139/143) | 27.0% (139/515) | 0.0% (0/8) |
| known failures | 381 | 17.1% (65/381) | 100.0% (65/65) | 17.1% (65/381) | 0.0% (0/6) |
| All 30 scans | 1914 | 54.8% (1048/1914) | 98.8% (1048/1061) | 54.8% (1048/1914) | 0.0% (0/30) |

Overall: correct 1048, both null 0, mismatch 13, missed 853, spurious 0. Straight-through is 0/30 with a roster and without one. A document at high field accuracy still had a field under 0.80 or a validation error, so none passed without review. The per-document table is in the scan report. Variant accuracy is the same on the ground-truth roster pass.

The reliability table for these scans, with no roster: distinct confidence values 384, expected calibration error 0.150. The 0.80-1.00 bucket is 100.0% (596/596), with 0 errors. All 13 mismatches are under 0.80: 9 in 0.40-0.59 and 4 in 0.60-0.79. OCR fields routed to review: 478/1074. The six known-failure pages contributed no confident wrong value. With the ground-truth roster the 0.80-1.00 bucket is 691 comparisons at mean 0.825 with 0 errors, distinct confidence values are 385, expected calibration error is 0.135, and OCR fields routed to review are 383/1074. The 13 mismatches stay under 0.80.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 844 | 0.000 | 0.0% (0/844) | 844 | 100.0% (844/844) |
| 0.20-0.39 | 10 | 0.265 | 10.0% (1/10) | 9 | 90.0% (9/10) |
| 0.40-0.59 | 317 | 0.498 | 97.2% (308/317) | 9 | 2.8% (9/317) |
| 0.60-0.79 | 147 | 0.738 | 97.3% (143/147) | 4 | 2.7% (4/147) |
| 0.80-1.00 | 596 | 0.829 | 100.0% (596/596) | 0 | 0.0% (0/596) |

CI generates this set and fails if a headline in the `scans` block of [`docs/eval-baseline.json`](eval-baseline.json) drops under its floor, or if the set has fewer than 30 documents. `docs/scan-hashes.json` is pinned to the CI runner image. Eight documents differ on another Linux box, so a local byte comparison is skipped outside CI. The CI byte check still fails the job on a mismatch. The floors are the earlier measured rates and were not lowered: overall accuracy 54.4% (1041/1914), catalog 81.1% (408/503), `dev_b` 84.7% (436/515), `dev_statement` 25.6% (132/515), and the hard pages 17.1% (65/381). This run is above those floors. Precision floors are those earlier precisions, including 100.0% (65/65) on the hard pages. A hard page that scores 0% does not fail CI. A drop below the floor does. `max_confident_wrong` is 0. That key is a ceiling. One value at or above 0.80 that is wrong fails CI.

### Hybrid

The tables above are the deterministic backend, with no roster, on Tesseract 5.3.4. Live confident-wrong is 0 on hybrid and on llm, in both runs, on every repository set. Those figures were measured on the pre-release source of v0.1.0 (src/ differs from the tag only in one docstring). The report is [docs/eval-live/report.md](eval-live/report.md), with `report-run1.json` and `report-run2.json` beside it. Every live run passed a roster built with `k1lens write-roster` from the same ground-truth JSON the eval scores against, so the identity of every matched document was known before scoring. Unseen layouts are not supported. The live measurement used Tesseract 5.5.0. Model `gpt-4o-mini`. Estimated spend for the repository sets, both backends and both runs, is $0.341834. None of the deterministic tables above is a model score.

| Set | Hybrid run 1 | Hybrid run 2 | Llm run 1 | Llm run 2 |
| --- | --- | --- | --- | --- |
| In distribution | 0 | 0 | 0 | 0 |
| Development | 0 | 0 | 0 | 0 |
| dev_b | 0 | 0 | 0 | 0 |
| Colon-free | 0 | 0 | 0 | 0 |
| Scans | 0 | 0 | 0 | 0 |

Hybrid, both runs: in distribution 99.3% (884/890), precision 99.9% (878/879), field straight-through 77.4% (689/890), document straight-through 28.6% (4/14). Development 68.0% (349/513), precision 100.0% (349/349), field straight-through 50.1% (257/513), document straight-through 50.0% (4/8). dev_b 98.4% (253/257), precision 100.0% (253/253), field straight-through 98.4% (253/257), document straight-through 0.0% (0/4). Colon-free 100.0% (767/767), precision 100.0% (767/767), field straight-through 55.3% (424/767), document straight-through 25.0% (3/12). Scans 55.3% (1059/1914), precision 99.2% (1059/1068), field straight-through 38.6% (739/1914), document straight-through 0.0% (0/30).

Llm field straight-through is 0.0% and document straight-through is 0.0% on every set in both runs. Llm run 1: in distribution 94.9% (845/890), precision 99.9% (839/840); development 88.4% (473/535), precision 99.1% (453/457); dev_b 84.1% (217/258), precision 99.5% (217/218); colon-free 92.3% (708/767), precision 99.0% (708/715); scans 51.3% (991/1932), precision 89.6% (977/1090). Llm run 2: in distribution 94.9% (845/890), precision 99.9% (839/840); development 87.9% (459/522), precision 98.9% (453/458); dev_b 84.1% (217/258), precision 99.5% (217/218); colon-free 92.3% (708/767), precision 99.0% (708/715); scans 51.2% (987/1927), precision 91.6% (974/1063).

The model is not on the identity path. A model identity value at any confidence stays under 0.80. Hybrid calls the model when the layout is unrecognized, or when a field is missing or below the review threshold. It stores the model's value only for a missing money or percent amount, a missing coded-line amount, or a missing tax year, and only when that string is in the field's own label region. A coded line the rules did not read is stored only when the layout is unrecognized. A field that already has a value keeps the rules value. The stored confidence is never raised above the number the model reported, and it stays at or below below_review_threshold (0.49 when the threshold is 0.80). A non-finite model confidence is rejected. A finite confidence outside 0 to 1 is clamped. Llm mode never clears a field. Every llm value goes to review. A blank line stays null. A model value that fails the same format check is discarded, and the deterministic value or a null is kept. The LLM-only path stops on a persistent 5xx, a timeout, or a malformed reply. Hybrid keeps the deterministic values in those cases.

### Known failure cases

Six catalog pages are damaged on purpose. The same layout, without that damage, is the catalog row above. The extractor is not adjusted for these pages. A miss at confidence 0.00 is highlighted and blocks approval. A wrong value at or above 0.80 is not highlighted. That is a bug. None of these six pages produced one. Figures are copied from the known-failure section of [`docs/eval-report-scans.md`](eval-report-scans.md).

| Document | What it got wrong | Why | How the system flagged it | What would fix it |
| --- | --- | --- | --- | --- |
| K1-FAIL-0001 | All 66 fields missed. Accuracy 0.0% (0/66). Mismatch 0. | Rasterized at 40 DPI. The glyphs are a few pixels tall, so Tesseract returned no fields. | Every miss is confidence 0.00, under 0.80. Required fields are empty, so the document cannot be approved. Straight-through 0/1. No value cleared 0.80. | Rescan at 200 DPI or more, or reject the page before extraction. |
| K1-FAIL-0002 | All 72 fields missed. Accuracy 0.0% (0/72). Mismatch 0. | The page is rotated 20 degrees and sheared by 0.45. The lines are not horizontal. | Misses at confidence 0.00. Straight-through 0/1. Nothing at or above 0.80. | Deskew the page before OCR. |
| K1-FAIL-0003 | 56 fields missed. 3 fields still matched. Accuracy 5.1% (3/59). Mismatch 0. | Brown translucent ellipses cover most of both pages. | The 56 misses sit under 0.80 (54 at confidence 0.00, 2 at 0.25: tax year and box 4a) and are highlighted. The 3 surviving reads were correct. Straight-through 0/1. | Detect the occluded region and leave it for a person, or ask for another scan. |
| K1-FAIL-0004 | 26 fields missed, including the EIN, city, state, and TIN. 37 fields still matched. Accuracy 58.7% (37/63). Mismatch 0. | Pen strikes and scribbles cross printed lines. The crossed lines do not parse. Lines the pen missed still read. | The 26 misses are under 0.80. The 37 reads were correct, so none is a confident wrong value. Straight-through 0/1. | A person reads the marked lines. A pen stroke should not replace a printed amount without review. |
| K1-FAIL-0005 | 35 fields missed, including the partner TIN, name, address, and the lower boxes. 25 fields on the remaining top of the page matched. Accuracy 41.7% (25/60). Mismatch 0. | The bottom 72% of each page is white, so those boxes are not in the image. | The cropped fields are misses at confidence 0.00. The fields still on the page were read correctly. Straight-through 0/1. | Reject a page that does not contain the full form. |
| K1-FAIL-0006 | All 61 fields missed. Accuracy 0.0% (0/61). Mismatch 0. | The page is blended 99.2% toward white. The ink is a ghost. | No value was emitted. Confidence on every field is 0.00. Straight-through 0/1. | Reject a page with almost no ink before extraction. |

Two other scans, not in that six, still misread item L withdrawals. The digits were not corrected. Both amounts now stay under 0.80, so the confident-wrong count on this set is 0.

| Document | Field | Gold | Predicted | Confidence |
| --- | --- | --- | --- | --- |
| K1-SCAN-0004 | `part_ii.capital.withdrawals` | 9298 | 298.00 | 0.66 |
| K1-SCAN-0013 | `part_ii.capital.withdrawals` | 14365 | 44365.00 | 0.62 |

K1-SCAN-0004 is a mild catalog page at 210 DPI. Tesseract read `L Withdrawals and distributions: $298.00`. The leading 9 of 9298 was read as `$`. The label was an exact catalog match (0.40). That line has a colon, so the colon reader is used. It does not take proximity from the OCR word boxes, so proximity is the unknown-proximity credit (0.072). The mean word confidence was 0.858 (0.206). The token parsed as money (0.12) and the withdrawal was non-negative (0.08). Those signals summed to 0.88. Capital contributed on the same page was read as `17835:00` and did not attach, so item L was incomplete and the cross-check never ran.

K1-SCAN-0013 is a mild catalog page at 230 DPI. Tesseract read `44365.00` for gold 14365. The leading 1 was read as 4. The same five signals summed to 0.84: exact label 0.40, unknown proximity 0.072, word confidence 0.72 (0.173), a money parse 0.12, and a non-negative withdrawal 0.08. Beginning capital was missed, and ending capital was `21 1275.00`, which did not parse. Item L was incomplete, so the cross-check never ran.

An untested item L now takes the same 0.22 penalty as an account that does not tie. 0.88 becomes 0.66 and 0.84 becomes 0.62. Both are under 0.80. The rule does not name these documents or these amounts. A parsed item L value whose siblings are missing cannot clear the default review threshold, because 1.00 minus 0.22 is 0.78.
