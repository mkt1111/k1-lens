# Live evaluation: repository sets, ground-truth roster

Measured on the pre-release source of v0.1.0; src/ differs from the tag only in one docstring. Two runs, both shown, because live results vary between runs even at temperature 0.

Run times, from the run logs: run 1: 2026-10-08 05:00:39 CDT to 2026-10-08 05:35:56 CDT; run 2: 2026-10-08 05:36:02 CDT to 2026-10-08 06:11:17 CDT. CDT is US Central time.

**Roster disclosure.** Every run below passed a roster built with `k1lens write-roster` from the same ground-truth JSON the eval scores against. The identity of every matched document (name, EIN or TIN, street, city, state, ZIP) was known before scoring. Identity straight-through on these sets is therefore not evidence about unseen partners. The model has no role in identity: a model identity value stays under 0.80 at any confidence, and a section with a model value is not lifted by a roster match. Only page-read identity fields with a confidently read id and a full exact roster match are lifted, to exactly 0.80.

**Llm mode.** Every value from the llm backend is capped at 0.79, under the 0.80 review threshold, so an llm value never clears a field on its own. Every llm value goes to review. In hybrid mode the model is called when the layout is unrecognized, or when a field is missing or below the review threshold. It stores the model's value only for a missing money or percent amount or a missing tax year, and only when that string is in the field's own label region. A field that already has a value keeps the rules value. The stored confidence stays at or below 0.49, under the 0.80 review threshold.

Scope: the five repository sets only (`fixtures/synthetic`, `fixtures/dev`, `fixtures/dev_b`, `fixtures/dev_geometry`, `fixtures/scans`), seed 1065. No held-out or blind data is in this report.

## Confident wrong

A confident wrong value is a mismatch or a spurious extraction stored at confidence 0.80 or above.

| Set | hybrid run 1 | hybrid run 2 | llm run 1 | llm run 2 |
| --- | --- | --- | --- | --- |
| In distribution (`fixtures/synthetic`) | 0 | 0 | 0 | 0 |
| Dev layouts (`fixtures/dev`) | 0 | 0 | 0 | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 0 | 0 | 0 | 0 |
| Colon-free (`fixtures/dev_geometry`) | 0 | 0 | 0 | 0 |
| Scanned images (`fixtures/scans`) | 0 | 0 | 0 | 0 |
| **All sets** | 0 | 0 | 0 | 0 |

## Accuracy, precision, straight-through

Accuracy is (correct + both null) / comparisons. Precision is correct / (correct + mismatch + spurious). Field straight-through is comparisons stored at 0.80 or above / comparisons. Document straight-through is documents with no error-severity finding and no field under 0.80, tax year included / documents.

### hybrid backend

| Set | Run | Docs | Accuracy | Precision | Field straight-through | Document straight-through | Confident wrong |
| --- | --- | --- | --- | --- | --- | --- | --- |
| In distribution (`fixtures/synthetic`) | 1 | 14 | 99.3% (884/890) | 99.9% (878/879) | 77.4% (689/890) | 28.6% (4/14) | 0 |
| In distribution (`fixtures/synthetic`) | 2 | 14 | 99.3% (884/890) | 99.9% (878/879) | 77.4% (689/890) | 28.6% (4/14) | 0 |
| Dev layouts (`fixtures/dev`) | 1 | 8 | 68.0% (349/513) | 100.0% (349/349) | 50.1% (257/513) | 50.0% (4/8) | 0 |
| Dev layouts (`fixtures/dev`) | 2 | 8 | 68.0% (349/513) | 100.0% (349/349) | 50.1% (257/513) | 50.0% (4/8) | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 1 | 4 | 98.4% (253/257) | 100.0% (253/253) | 98.4% (253/257) | 0.0% (0/4) | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 2 | 4 | 98.4% (253/257) | 100.0% (253/253) | 98.4% (253/257) | 0.0% (0/4) | 0 |
| Colon-free (`fixtures/dev_geometry`) | 1 | 12 | 100.0% (767/767) | 100.0% (767/767) | 55.3% (424/767) | 25.0% (3/12) | 0 |
| Colon-free (`fixtures/dev_geometry`) | 2 | 12 | 100.0% (767/767) | 100.0% (767/767) | 55.3% (424/767) | 25.0% (3/12) | 0 |
| Scanned images (`fixtures/scans`) | 1 | 30 | 55.3% (1059/1914) | 99.2% (1059/1068) | 38.6% (739/1914) | 0.0% (0/30) | 0 |
| Scanned images (`fixtures/scans`) | 2 | 30 | 55.3% (1059/1914) | 99.2% (1059/1068) | 38.6% (739/1914) | 0.0% (0/30) | 0 |

### llm backend

| Set | Run | Docs | Accuracy | Precision | Field straight-through | Document straight-through | Confident wrong |
| --- | --- | --- | --- | --- | --- | --- | --- |
| In distribution (`fixtures/synthetic`) | 1 | 14 | 94.9% (845/890) | 99.9% (839/840) | 0.0% (0/890) | 0.0% (0/14) | 0 |
| In distribution (`fixtures/synthetic`) | 2 | 14 | 94.9% (845/890) | 99.9% (839/840) | 0.0% (0/890) | 0.0% (0/14) | 0 |
| Dev layouts (`fixtures/dev`) | 1 | 8 | 88.4% (473/535) | 99.1% (453/457) | 0.0% (0/535) | 0.0% (0/8) | 0 |
| Dev layouts (`fixtures/dev`) | 2 | 8 | 87.9% (459/522) | 98.9% (453/458) | 0.0% (0/522) | 0.0% (0/8) | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 1 | 4 | 84.1% (217/258) | 99.5% (217/218) | 0.0% (0/258) | 0.0% (0/4) | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 2 | 4 | 84.1% (217/258) | 99.5% (217/218) | 0.0% (0/258) | 0.0% (0/4) | 0 |
| Colon-free (`fixtures/dev_geometry`) | 1 | 12 | 92.3% (708/767) | 99.0% (708/715) | 0.0% (0/767) | 0.0% (0/12) | 0 |
| Colon-free (`fixtures/dev_geometry`) | 2 | 12 | 92.3% (708/767) | 99.0% (708/715) | 0.0% (0/767) | 0.0% (0/12) | 0 |
| Scanned images (`fixtures/scans`) | 1 | 30 | 51.3% (991/1932) | 89.6% (977/1090) | 0.0% (0/1932) | 0.0% (0/30) | 0 |
| Scanned images (`fixtures/scans`) | 2 | 30 | 51.2% (987/1927) | 91.6% (974/1063) | 0.0% (0/1927) | 0.0% (0/30) | 0 |

### Deterministic baseline in the same commands

Each live command also scores the deterministic backend with the same roster. Those figures are the same in all four commands.

| Set | Accuracy | Precision | Field straight-through | Document straight-through | Confident wrong |
| --- | --- | --- | --- | --- | --- |
| In distribution (`fixtures/synthetic`) | 99.3% (884/890) | 99.9% (878/879) | 77.4% (689/890) | 28.6% (4/14) | 0 |
| Dev layouts (`fixtures/dev`) | 68.0% (349/513) | 100.0% (349/349) | 50.1% (257/513) | 50.0% (4/8) | 0 |
| Dev layouts, dev_b (`fixtures/dev_b`) | 98.4% (253/257) | 100.0% (253/253) | 98.4% (253/257) | 0.0% (0/4) | 0 |
| Colon-free (`fixtures/dev_geometry`) | 100.0% (767/767) | 100.0% (767/767) | 55.3% (424/767) | 25.0% (3/12) | 0 |
| Scanned images (`fixtures/scans`) | 55.3% (1059/1914) | 99.2% (1059/1068) | 38.6% (739/1914) | 0.0% (0/30) | 0 |

Hybrid equals this deterministic baseline on every set in both runs: yes. Llm backend, both runs, all sets: 0 comparisons stored at 0.80 or above and 0 documents straight-through, consistent with the 0.79 cap. `Fields requested` is counted from hybrid traces only, so it is 0 for the llm backend.

## OCR failures, stops, malformed replies

- Run 1, hybrid: stopped: no; malformed replies: 0; documents with OCR-failed pages: 0.
- Run 1, llm: stopped: no; malformed replies: 0; documents with OCR-failed pages: 0.
- Run 2, hybrid: stopped: no; malformed replies: 0; documents with OCR-failed pages: 0.
- Run 2, llm: stopped: no; malformed replies: 0; documents with OCR-failed pages: 0.
- OCR timeout or failure lines in the console logs: none (no OCR failure, timeout, malformed-reply, retry, or stop line in either run's console log).

## Spend and usage

Repo sets only. Cost is the repo's list-price estimate from token counts, not an invoice. Spend ceiling $3.00 per command.

| Run | Backend | Estimated spend (repo sets only) | Input tokens | Output tokens | LLM calls | Fields requested | Start | End |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | hybrid | $0.085446 | 267411 | 75558 | 68 | 2177 | 2026-10-08 05:00:39 CDT | 2026-10-08 05:20:11 CDT |
| 1 | llm | $0.085499 | 267411 | 75645 | 68 | 0 | 2026-10-08 05:20:11 CDT | 2026-10-08 05:35:56 CDT |
| 2 | hybrid | $0.085553 | 267411 | 75735 | 68 | 2177 | 2026-10-08 05:36:02 CDT | 2026-10-08 05:52:53 CDT |
| 2 | llm | $0.085336 | 267411 | 75374 | 68 | 0 | 2026-10-08 05:52:53 CDT | 2026-10-08 06:11:17 CDT |
| 1 | both | $0.170945 | | | | | | |
| 2 | both | $0.170889 | | | | | | |
| **Total, repo sets only** | | **$0.341834** | | | | | | |

## Setup

- Source: the pre-release source of v0.1.0 (src/ differs from the tag only in one docstring), clean checkout, `uv sync`.
- Date: run 1: 2026-10-08 05:00:39 CDT to 2026-10-08 05:35:56 CDT; run 2: 2026-10-08 05:36:02 CDT to 2026-10-08 06:11:17 CDT.
- Requested model: `gpt-4o-mini`. Model version string returned by the API: `gpt-4o-mini-2024-07-18` (every reply in all four commands). System fingerprints seen: `fp_804263d44d`, `fp_f18cf25064`.
- Temperature 0. No API seed is sent.
- Runs: 2 per backend. Corpus seed: 1065. Review threshold 0.80. Money tolerance 1.00.
- Tesseract on this machine: 5.5.0. CI uses a different version: the ubuntu-24.04 distro package, Tesseract 5.3.4, which is also the version behind the deterministic README tables. Scan results depend on the Tesseract version. `OMP_THREAD_LIMIT=1`.
- Roster: `gt-roster.json` (sha256 `b9a1d8a7708d1554807df158d51b9d6d1bfcd7ad1aa2a5ecf7b1efa3c0770a46`), 31 partnership records and 30 investor records, one record per EIN or TIN.

### Commands

```bash
# Setup (clean checkout of the pre-release source of v0.1.0; src/ differs from the tag only in one docstring)
export OMP_THREAD_LIMIT=1
uv sync
uv run k1lens generate --out fixtures/synthetic --seed 1065 --count 14
uv run k1lens generate --dev --out fixtures/dev --seed 1065
uv run k1lens generate --dev-b --out fixtures/dev_b --seed 1065
uv run k1lens generate --dev-geometry --out fixtures/dev_geometry --seed 1065
uv run k1lens generate --scans --out fixtures/scans --seed 1065

# Ground-truth roster: one write-roster per set, then merged into one file (one record per id;
# investor ids 00-1000009 and 00-1000010 have a blank name in fixtures/synthetic K1-0009/K1-0010
# ground truth and a full record in dev_geometry and scans; the complete record is kept).
for s in synthetic dev dev_b dev_geometry scans; do
  uv run k1lens write-roster --fixtures fixtures/$s --out roster-parts/$s.json
done

# Live eval, all five sets per command, run twice (N=1, 2), each command run alone at nice 19
for B in hybrid llm; do
  OMP_THREAD_LIMIT=1 nice -n 19 uv run k1lens eval --backend $B --live --max-spend 3 \
    --roster gt-roster.json --report runN/$B/eval-live.md   # outside the checkout
done
```

Each live command was launched through a small observation wrapper (`capture_live.py`, kept outside the repo) that calls the same `k1lens` CLI entry point with the arguments above and records what the run already computes but `eval-live.json` does not carry: the calibration buckets (for field straight-through), the confident-wrong judgments, OCR-failed pages, and the `model` and `system_fingerprint` fields of each API reply. It sends nothing and changes no value. Documents, accuracy, precision, confident wrong, and document straight-through in the wrapper's record were checked against each `eval-live.json` and agree on every set. Field-level straight-through comes from that record. The per-set roster check, run on that pre-release source: scoring `fixtures/synthetic` and `fixtures/dev_geometry` deterministically with the merged roster and with that set's own `write-roster` file gives identical reports (4/14 and 3/12 documents straight-through).

## Run files

The full per-document and per-field output of each run is in `report-run1.json` and `report-run2.json` next to this file. Each holds that run's hybrid and llm `eval-live` JSON unchanged, under the keys `hybrid` and `llm`. Commit them with this report so every number above can be traced.
