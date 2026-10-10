# K1-Lens evaluation report

Synthetic data only. These scans were generated from the seed for this
run. The image PDFs are not stored in the repository. The extractor is
the deterministic backend with Tesseract.

## Run

- Backend: `deterministic`
- Fixtures: `/tmp/k1lens-scans`
- Seed: 1065
- Documents: 30
- OCR enabled: yes
- Tesseract: tesseract 5.3.4
- Roster: none
- Confidently read ids: 21 of 60 sections
- Money tolerance: 1.00
- Distribution: `scans`
- Review threshold: 0.80

## Overall

| Metric | Value |
| --- | --- |
| Comparisons | 1914 |
| Accuracy | 54.8% (1048/1914) |
| Precision | 98.8% (1048/1061) |
| Recall | 54.8% (1048/1914) |
| Correct | 1048 |
| Both null | 0 |
| Mismatch | 13 |
| Missed | 853 |
| Spurious | 0 |
| Straight-through | 0.0% (0/30) |

Straight-through counts documents that need no review. Field accuracy above
counts fields. A document can be field-accurate and still fail a required-field
rule, including a missing tax year.

## By source

Text layer is every variant that still has text. Image-only variants are
`rasterized` and `scan_*`. Those pages are read with Tesseract. Overall
is the two together.

| Scope | Comparisons | Accuracy | Precision | Recall |
| --- | --- | --- | --- | --- |
| text layer | 0 | n/a | n/a | n/a |
| rasterized | 1914 | 54.8% (1048/1914) | 98.8% (1048/1061) | 54.8% (1048/1914) |
| overall | 1914 | 54.8% (1048/1914) | 98.8% (1048/1061) | 54.8% (1048/1914) |

## Review flags

The review UI highlights a field when its confidence is below 0.80.
A wrong value is a mismatch or a spurious extraction.
An incorrect comparison also includes a miss.
OCR fields routed to review: 478/1074.

| Scope | Wrong values flagged | Incorrect comparisons flagged |
| --- | --- | --- |
| text layer | n/a | n/a |
| rasterized | 100.0% (13/13) | 100.0% (866/866) |
| overall | 100.0% (13/13) | 100.0% (866/866) |

## Reliability

Text-layer confidence takes few distinct values because the signals are coarse:
an exact label, one proximity bin for a normal line, and a format check.
This is a reliability table for those levels, not a fitted probability.
Each comparison falls in the bucket of the confidence the extractor stored.
An error is a mismatch, a miss, or a spurious value.
The lowest populated bucket (0.00-0.19) has error rate 100.0% (844/844), which is higher than the highest populated bucket (0.80-1.00) at 0.0% (0/596). A format failure, an item L mismatch, or an untested item L account can also lower confidence on a value that still matches the facsimile, so a middle bucket can be mostly correct.
Distinct confidence values: 384. Expected calibration error (bucket ECE): 0.150.

| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |
| --- | --- | --- | --- | --- | --- |
| 0.00-0.19 | 844 | 0.000 | 0.0% (0/844) | 844 | 100.0% (844/844) |
| 0.20-0.39 | 10 | 0.265 | 10.0% (1/10) | 9 | 90.0% (9/10) |
| 0.40-0.59 | 317 | 0.498 | 97.2% (308/317) | 9 | 2.8% (9/317) |
| 0.60-0.79 | 147 | 0.738 | 97.3% (143/147) | 4 | 2.7% (4/147) |
| 0.80-1.00 | 596 | 0.829 | 100.0% (596/596) | 0 | 0.0% (0/596) |

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
| scan_catalog | 503 | 81.1% (408/503) | 97.8% (408/417) | 81.1% (408/503) | 0.0% (0/8) |
| scan_dev_b | 515 | 84.7% (436/515) | 100.0% (436/436) | 84.7% (436/515) | 0.0% (0/8) |
| scan_dev_statement | 515 | 27.0% (139/515) | 97.2% (139/143) | 27.0% (139/515) | 0.0% (0/8) |
| scan_hard | 381 | 17.1% (65/381) | 100.0% (65/65) | 17.1% (65/381) | 0.0% (0/6) |

## By document

Each row is one image-only scan. Straight-through is that document
passing with no review needed.

| Document | Layout | DPI | Accuracy | Precision | Recall | Straight-through | Degradation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K1-SCAN-0001 | catalog | 150 | 98.3% (57/58) | 98.3% (57/58) | 98.3% (57/58) | 0.0% (0/1) | dpi=150 rot=-1.37 skew=-0.018 noise=4.1 blur=0.20 jpeg=90 contrast=0.96 |
| K1-SCAN-0002 | dev_statement | 170 | 34.8% (23/66) | 100.0% (23/23) | 34.8% (23/66) | 0.0% (0/1) | dpi=170 rot=-0.80 skew=-0.014 noise=4.0 blur=0.40 jpeg=82 contrast=0.97 |
| K1-SCAN-0003 | dev_b | 190 | 97.0% (64/66) | 100.0% (64/64) | 97.0% (64/66) | 0.0% (0/1) | dpi=190 rot=-1.73 skew=-0.021 noise=10.8 blur=0.60 jpeg=55 contrast=0.90 |
| K1-SCAN-0004 | catalog | 210 | 88.1% (59/67) | 98.3% (59/60) | 88.1% (59/67) | 0.0% (0/1) | dpi=210 rot=1.55 skew=0.037 noise=13.0 blur=0.90 jpeg=55 contrast=0.91 |
| K1-SCAN-0005 | dev_statement | 230 | 0.0% (0/60) | n/a | 0.0% (0/60) | 0.0% (0/1) | dpi=230 rot=2.48 skew=0.041 noise=10.9 blur=1.20 jpeg=40 contrast=0.42 faint |
| K1-SCAN-0006 | dev_b | 250 | 98.5% (64/65) | 100.0% (64/64) | 98.5% (64/65) | 0.0% (0/1) | dpi=250 rot=-0.83 skew=-0.027 noise=11.9 blur=0.30 jpeg=90 contrast=0.99 |
| K1-SCAN-0007 | catalog | 275 | 87.5% (56/64) | 100.0% (56/56) | 87.5% (56/64) | 0.0% (0/1) | dpi=275 rot=1.75 skew=-0.017 noise=9.5 blur=0.80 jpeg=82 contrast=0.96 |
| K1-SCAN-0008 | dev_statement | 300 | 32.8% (22/67) | 95.7% (22/23) | 32.8% (22/67) | 0.0% (0/1) | dpi=300 rot=-2.21 skew=0.017 noise=4.1 blur=1.00 jpeg=90 contrast=0.90 |
| K1-SCAN-0009 | dev_b | 150 | 96.9% (62/64) | 100.0% (62/62) | 96.9% (62/64) | 0.0% (0/1) | dpi=150 rot=-1.00 skew=0.031 noise=10.1 blur=0.20 jpeg=55 contrast=0.90 |
| K1-SCAN-0010 | catalog | 170 | 0.0% (0/60) | n/a | 0.0% (0/60) | 0.0% (0/1) | dpi=170 rot=-0.77 skew=-0.021 noise=12.5 blur=0.40 jpeg=40 contrast=0.42 faint |
| K1-SCAN-0011 | dev_statement | 190 | 32.4% (22/68) | 95.7% (22/23) | 32.4% (22/68) | 0.0% (0/1) | dpi=190 rot=0.62 skew=0.026 noise=5.0 blur=0.60 jpeg=90 contrast=0.93 |
| K1-SCAN-0012 | dev_b | 210 | 96.8% (60/62) | 100.0% (60/60) | 96.8% (60/62) | 0.0% (0/1) | dpi=210 rot=0.80 skew=-0.016 noise=12.9 blur=0.90 jpeg=90 contrast=0.96 |
| K1-SCAN-0013 | catalog | 230 | 85.0% (51/60) | 96.2% (51/53) | 85.0% (51/60) | 0.0% (0/1) | dpi=230 rot=-2.18 skew=-0.040 noise=5.5 blur=1.20 jpeg=82 contrast=0.93 |
| K1-SCAN-0014 | dev_statement | 250 | 33.3% (21/63) | 100.0% (21/21) | 33.3% (21/63) | 0.0% (0/1) | dpi=250 rot=1.60 skew=0.033 noise=8.6 blur=0.30 jpeg=55 contrast=0.97 |
| K1-SCAN-0015 | dev_b | 275 | 0.0% (0/65) | n/a | 0.0% (0/65) | 0.0% (0/1) | dpi=275 rot=1.08 skew=-0.020 noise=11.0 blur=0.80 jpeg=40 contrast=0.42 faint |
| K1-SCAN-0016 | catalog | 300 | 95.6% (65/68) | 98.5% (65/66) | 95.6% (65/68) | 0.0% (0/1) | dpi=300 rot=0.51 skew=0.041 noise=8.7 blur=1.00 jpeg=82 contrast=0.94 |
| K1-SCAN-0017 | dev_statement | 150 | 28.8% (19/66) | 100.0% (19/19) | 28.8% (19/66) | 0.0% (0/1) | dpi=150 rot=1.59 skew=-0.036 noise=5.4 blur=0.20 jpeg=55 contrast=0.91 |
| K1-SCAN-0018 | dev_b | 170 | 98.5% (64/65) | 100.0% (64/64) | 98.5% (64/65) | 0.0% (0/1) | dpi=170 rot=-1.08 skew=-0.015 noise=4.4 blur=0.40 jpeg=55 contrast=0.98 |
| K1-SCAN-0019 | catalog | 190 | 95.4% (62/65) | 96.9% (62/64) | 95.4% (62/65) | 0.0% (0/1) | dpi=190 rot=1.04 skew=-0.028 noise=9.8 blur=0.60 jpeg=90 contrast=0.98 |
| K1-SCAN-0020 | dev_statement | 210 | 28.3% (17/60) | 89.5% (17/19) | 28.3% (17/60) | 0.0% (0/1) | dpi=210 rot=-0.80 skew=0.045 noise=12.8 blur=0.90 jpeg=70 contrast=0.93 |
| K1-SCAN-0021 | dev_b | 230 | 96.9% (62/64) | 100.0% (62/62) | 96.9% (62/64) | 0.0% (0/1) | dpi=230 rot=-0.52 skew=-0.020 noise=8.2 blur=1.20 jpeg=82 contrast=0.94 |
| K1-SCAN-0022 | catalog | 250 | 95.1% (58/61) | 96.7% (58/60) | 95.1% (58/61) | 0.0% (0/1) | dpi=250 rot=-0.80 skew=-0.020 noise=7.3 blur=0.30 jpeg=82 contrast=0.93 |
| K1-SCAN-0023 | dev_statement | 275 | 23.1% (15/65) | 100.0% (15/15) | 23.1% (15/65) | 0.0% (0/1) | dpi=275 rot=-1.08 skew=0.034 noise=12.7 blur=0.80 jpeg=70 contrast=0.94 |
| K1-SCAN-0024 | dev_b | 300 | 93.8% (60/64) | 100.0% (60/60) | 93.8% (60/64) | 0.0% (0/1) | dpi=300 rot=-1.37 skew=0.035 noise=10.5 blur=1.00 jpeg=90 contrast=0.99 |
| K1-FAIL-0001 | catalog | 40 | 0.0% (0/66) | n/a | 0.0% (0/66) | 0.0% (0/1) | failure=low_dpi dpi=40 rot=0.00 skew=0.000 noise=0.0 blur=0.00 jpeg=70 contrast=1.00 |
| K1-FAIL-0002 | catalog | 200 | 0.0% (0/72) | n/a | 0.0% (0/72) | 0.0% (0/1) | failure=skew dpi=200 rot=20.00 skew=0.450 noise=0.0 blur=0.00 jpeg=80 contrast=1.00 |
| K1-FAIL-0003 | catalog | 200 | 5.1% (3/59) | 100.0% (3/3) | 5.1% (3/59) | 0.0% (0/1) | failure=stain dpi=200 rot=0.00 skew=0.000 noise=0.0 blur=0.00 jpeg=75 contrast=1.00 |
| K1-FAIL-0004 | catalog | 200 | 58.7% (37/63) | 100.0% (37/37) | 58.7% (37/63) | 0.0% (0/1) | failure=handwriting dpi=200 rot=0.00 skew=0.000 noise=0.0 blur=0.00 jpeg=80 contrast=1.00 |
| K1-FAIL-0005 | catalog | 200 | 41.7% (25/60) | 100.0% (25/25) | 41.7% (25/60) | 0.0% (0/1) | failure=crop dpi=200 rot=0.00 skew=0.000 noise=0.0 blur=0.00 jpeg=85 contrast=1.00 |
| K1-FAIL-0006 | catalog | 200 | 0.0% (0/61) | n/a | 0.0% (0/61) | 0.0% (0/1) | failure=blank dpi=200 rot=0.00 skew=0.000 noise=0.0 blur=0.00 jpeg=70 contrast=1.00 |

## Confident wrong values

A confident wrong value is a mismatch or a spurious extraction whose
confidence is at or above 0.80. Each one is a bug. The scan
baseline ceiling is the count on the measured run. A higher count fails CI.

Count: 0.


## Known failure cases

These pages are damaged on purpose. The extractor is not adjusted for them.
A miss is a ground-truth value the extractor left empty. A mismatch is a
different value. A confident wrong value cleared the review threshold and
was not flagged. That is a bug.

| Document | Failure | Accuracy | Missed | Mismatch | Spurious | Confident wrong | Straight-through |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K1-FAIL-0001 | low_dpi | 0.0% (0/66) | 66 | 0 | 0 | 0 | 0.0% (0/1) |
| K1-FAIL-0002 | skew | 0.0% (0/72) | 72 | 0 | 0 | 0 | 0.0% (0/1) |
| K1-FAIL-0003 | stain | 5.1% (3/59) | 56 | 0 | 0 | 0 | 0.0% (0/1) |
| K1-FAIL-0004 | handwriting | 58.7% (37/63) | 26 | 0 | 0 | 0 | 0.0% (0/1) |
| K1-FAIL-0005 | crop | 41.7% (25/60) | 35 | 0 | 0 | 0 | 0.0% (0/1) |
| K1-FAIL-0006 | blank | 0.0% (0/61) | 61 | 0 | 0 | 0 | 0.0% (0/1) |

### K1-FAIL-0001 (low_dpi)

Missed 66 fields, including `part_i.ein`, `part_i.name`, `part_i.street`, `part_i.city`, `part_i.state`, `part_i.zip_code`, `part_i.irs_center`, `part_i.is_ptp`, and 58 more.
Missed fields at or above 0.80: 0.

### K1-FAIL-0002 (skew)

Missed 72 fields, including `part_i.ein`, `part_i.name`, `part_i.street`, `part_i.city`, `part_i.state`, `part_i.zip_code`, `part_i.irs_center`, `part_i.is_ptp`, and 64 more.
Missed fields at or above 0.80: 0.

### K1-FAIL-0003 (stain)

Missed 56 fields, including `part_i.ein`, `part_i.name`, `part_i.street`, `part_i.city`, `part_i.state`, `part_i.zip_code`, `part_i.irs_center`, `part_i.is_ptp`, and 48 more.
Missed fields at or above 0.80: 0.

### K1-FAIL-0004 (handwriting)

Missed 26 fields, including `part_i.ein`, `part_i.city`, `part_i.state`, `part_i.irs_center`, `part_i.is_ptp`, `part_ii.tin`, `part_ii.city`, `part_ii.state`, and 18 more.
Missed fields at or above 0.80: 0.

### K1-FAIL-0005 (crop)

Missed 35 fields, including `part_ii.tin`, `part_ii.name`, `part_ii.street`, `part_ii.city`, `part_ii.state`, `part_ii.zip_code`, `part_ii.is_general_partner`, `part_ii.is_domestic`, and 27 more.
Missed fields at or above 0.80: 0.

### K1-FAIL-0006 (blank)

Missed 61 fields, including `part_i.ein`, `part_i.name`, `part_i.street`, `part_i.city`, `part_i.state`, `part_i.zip_code`, `part_i.irs_center`, `part_i.is_ptp`, and 53 more.
Missed fields at or above 0.80: 0.

## By field

| Field | Comparisons | Accuracy | Precision | Recall | Missed | Mismatch |
| --- | --- | --- | --- | --- | --- | --- |
| `part_i.ein` | 30 | 63.3% (19/30) | 95.0% (19/20) | 63.3% (19/30) | 10 | 1 |
| `part_i.name` | 30 | 63.3% (19/30) | 95.0% (19/20) | 63.3% (19/30) | 10 | 1 |
| `part_i.street` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_i.city` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_i.state` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_i.zip_code` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_i.irs_center` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_i.is_ptp` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_ii.tin` | 30 | 43.3% (13/30) | 92.9% (13/14) | 43.3% (13/30) | 16 | 1 |
| `part_ii.name` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_ii.street` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.city` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_ii.state` | 30 | 66.7% (20/30) | 95.2% (20/21) | 66.7% (20/30) | 9 | 1 |
| `part_ii.zip_code` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_ii.is_general_partner` | 30 | 66.7% (20/30) | 100.0% (20/20) | 66.7% (20/30) | 10 | 0 |
| `part_ii.is_domestic` | 30 | 63.3% (19/30) | 100.0% (19/19) | 63.3% (19/30) | 11 | 0 |
| `part_ii.entity_type` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_ii.is_retirement_plan` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_ii.profit_beginning` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.profit_ending` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.loss_beginning` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_ii.loss_ending` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.capital_share_beginning` | 30 | 43.3% (13/30) | 100.0% (13/13) | 43.3% (13/30) | 17 | 0 |
| `part_ii.capital_share_ending` | 30 | 43.3% (13/30) | 100.0% (13/13) | 43.3% (13/30) | 17 | 0 |
| `part_ii.liability_nonrecourse` | 30 | 66.7% (20/30) | 100.0% (20/20) | 66.7% (20/30) | 10 | 0 |
| `part_ii.liability_qualified_nonrecourse` | 30 | 63.3% (19/30) | 95.0% (19/20) | 63.3% (19/30) | 10 | 1 |
| `part_ii.liability_recourse` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_ii.capital_method` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_ii.capital.beginning` | 30 | 43.3% (13/30) | 100.0% (13/13) | 43.3% (13/30) | 17 | 0 |
| `part_ii.capital.contributed` | 30 | 26.7% (8/30) | 66.7% (8/12) | 26.7% (8/30) | 18 | 4 |
| `part_ii.capital.current_year_net_income` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_ii.capital.other_increase_decrease` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.capital.withdrawals` | 30 | 33.3% (10/30) | 76.9% (10/13) | 33.3% (10/30) | 17 | 3 |
| `part_ii.capital.ending` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_ii.contributed_builtin_gain` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_iii.ordinary_business_income` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_iii.net_rental_real_estate` | 30 | 70.0% (21/30) | 95.5% (21/22) | 70.0% (21/30) | 8 | 1 |
| `part_iii.other_net_rental` | 30 | 56.7% (17/30) | 100.0% (17/17) | 56.7% (17/30) | 13 | 0 |
| `part_iii.guaranteed_payments_services` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_iii.guaranteed_payments_capital` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_iii.guaranteed_payments_total` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_iii.interest_income` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_iii.ordinary_dividends` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_iii.qualified_dividends` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_iii.dividend_equivalents` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_iii.royalties` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_iii.net_short_term_capital_gain` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_iii.net_long_term_capital_gain` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `part_iii.collectibles_gain` | 30 | 76.7% (23/30) | 100.0% (23/23) | 76.7% (23/30) | 7 | 0 |
| `part_iii.unrecaptured_1250_gain` | 30 | 70.0% (21/30) | 100.0% (21/21) | 70.0% (21/30) | 9 | 0 |
| `part_iii.net_section_1231_gain` | 30 | 53.3% (16/30) | 100.0% (16/16) | 53.3% (16/30) | 14 | 0 |
| `part_iii.section_179_deduction` | 30 | 43.3% (13/30) | 100.0% (13/13) | 43.3% (13/30) | 17 | 0 |
| `part_iii.schedule_k3_attached` | 30 | 73.3% (22/30) | 100.0% (22/22) | 73.3% (22/30) | 8 | 0 |
| `part_iii.foreign_taxes_paid` | 30 | 50.0% (15/30) | 100.0% (15/15) | 50.0% (15/30) | 15 | 0 |
| `tax_year` | 30 | 30.0% (9/30) | 100.0% (9/9) | 30.0% (9/30) | 21 | 0 |
| `part_iii.amt_items[B]` | 13 | 46.2% (6/13) | 100.0% (6/6) | 46.2% (6/13) | 7 | 0 |
| `part_iii.distributions[C]` | 30 | 40.0% (12/30) | 100.0% (12/12) | 40.0% (12/30) | 18 | 0 |
| `part_iii.distributions[A]` | 30 | 46.7% (14/30) | 100.0% (14/14) | 46.7% (14/30) | 16 | 0 |
| `part_iii.other_income[B]` | 10 | 20.0% (2/10) | 100.0% (2/2) | 20.0% (2/10) | 8 | 0 |
| `part_iii.other_income[C]` | 8 | 25.0% (2/8) | 100.0% (2/2) | 25.0% (2/8) | 6 | 0 |
| `part_iii.other_income[E]` | 9 | 55.6% (5/9) | 100.0% (5/5) | 55.6% (5/9) | 4 | 0 |
| `part_iii.other_deductions[W]` | 9 | 11.1% (1/9) | 100.0% (1/1) | 11.1% (1/9) | 8 | 0 |
| `part_iii.other_deductions[B]` | 6 | 33.3% (2/6) | 100.0% (2/2) | 33.3% (2/6) | 4 | 0 |
| `part_iii.other_deductions[A]` | 11 | 36.4% (4/11) | 100.0% (4/4) | 36.4% (4/11) | 7 | 0 |
| `part_iii.amt_items[A]` | 12 | 33.3% (4/12) | 100.0% (4/4) | 33.3% (4/12) | 8 | 0 |
| `part_iii.amt_items[C]` | 13 | 53.8% (7/13) | 100.0% (7/7) | 53.8% (7/13) | 6 | 0 |
| `part_iii.other_income[A]` | 11 | 45.5% (5/11) | 100.0% (5/5) | 45.5% (5/11) | 6 | 0 |
| `part_iii.credits[P]` | 7 | 57.1% (4/7) | 100.0% (4/4) | 57.1% (4/7) | 3 | 0 |
| `part_iii.tax_exempt_and_nondeductible[B]` | 10 | 40.0% (4/10) | 100.0% (4/4) | 40.0% (4/10) | 6 | 0 |
| `part_iii.tax_exempt_and_nondeductible[A]` | 12 | 25.0% (3/12) | 100.0% (3/3) | 25.0% (3/12) | 9 | 0 |
| `part_iii.tax_exempt_and_nondeductible[C]` | 4 | 25.0% (1/4) | 100.0% (1/1) | 25.0% (1/4) | 3 | 0 |
| `part_iii.other_information[B]` | 5 | 60.0% (3/5) | 100.0% (3/3) | 60.0% (3/5) | 2 | 0 |
| `part_iii.other_information[N]` | 9 | 44.4% (4/9) | 100.0% (4/4) | 44.4% (4/9) | 5 | 0 |
| `part_iii.other_deductions[I]` | 6 | 0.0% (0/6) | n/a | 0.0% (0/6) | 6 | 0 |
| `part_iii.other_deductions[H]` | 7 | 71.4% (5/7) | 100.0% (5/5) | 71.4% (5/7) | 2 | 0 |
| `part_iii.credits[A]` | 3 | 66.7% (2/3) | 100.0% (2/2) | 66.7% (2/3) | 1 | 0 |
| `part_iii.credits[C]` | 5 | 60.0% (3/5) | 100.0% (3/3) | 60.0% (3/5) | 2 | 0 |
| `part_iii.other_information[V]` | 8 | 50.0% (4/8) | 100.0% (4/4) | 50.0% (4/8) | 4 | 0 |
| `part_iii.other_information[A]` | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 0 | 0 |
| `part_iii.other_income[F]` | 4 | 50.0% (2/4) | 100.0% (2/2) | 50.0% (2/4) | 2 | 0 |
| `part_iii.other_information[Z]` | 7 | 42.9% (3/7) | 100.0% (3/3) | 42.9% (3/7) | 4 | 0 |
| `part_iii.self_employment[A]` | 6 | 50.0% (3/6) | 100.0% (3/3) | 50.0% (3/6) | 3 | 0 |
| `part_iii.self_employment[C]` | 6 | 50.0% (3/6) | 100.0% (3/3) | 50.0% (3/6) | 3 | 0 |

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
- These documents are image-only scans. CI generates them from seed 1065 with k1lens generate --scans. The PDFs are not stored in the repository. The same seed rewrites the same images on one machine. docs/scan-hashes.json is pinned to the CI runner image. Eight documents differ on another Linux box, so a local byte comparison is skipped outside CI. Pillow and pdfium can still differ across machines, and Tesseract 5.3.4 measured here can disagree with Docker's 5.3.0.
- Each mild scan is a synthetic K-1. EINs use the 00- prefix. Layouts cycle through the catalog facsimile, dev_statement, and dev_b. dev_statement and dev_b were seen during development. The held-out set is scored by an independent reviewer; not in this repo. Degradation varies DPI from 150 to 300, adds a slight rotation and skew, noise, blur, and JPEG compression. Three documents, one in each layout, are faint: lower contrast, lower brightness, and JPEG quality 40.
- Six more pages are known failures on the catalog layout: 40 DPI, a 20 degree rotation with heavy skew, a coffee-stain occlusion, handwritten strokes across printed lines, the bottom of the page cropped away, and a page faded almost to white. The extractor is not adjusted for them. Accuracy floors are the measured rates, so those failures are expected. A confident wrong value is a mismatch or a spurious extraction at or above the review threshold. Each one is listed in this report.
- Per-document accuracy, precision, recall, and straight-through are in the by-document table. The reliability table is the calibration for these scans. Field accuracy does not imply straight-through.
- No roster was passed. Every name, street, city, state, and ZIP stays in review, with a no_roster finding. That is by design.
