# Fixtures

The corpora are generated from seed `1065`. They are not stored in git.

```bash
uv run k1lens generate --out fixtures/synthetic --seed 1065 --count 14
uv run k1lens generate --dev --out fixtures/dev --seed 1065
uv run k1lens generate --dev-b --out fixtures/dev_b --seed 1065
uv run k1lens generate --dev-geometry --out fixtures/dev_geometry --seed 1065
uv run k1lens generate --scans --out fixtures/scans --seed 1065
```

`fixtures/heldout` is a two-document set stored in git: one clean catalog page and one prose letter. The review API can ingest it without generating a corpus. It is not the development layouts, and it is not the independent held-out set.

`k1lens serve` writes `fixtures/synthetic` when that manifest is missing. `k1lens eval --compare` and `k1lens eval --backend hybrid --live` write any missing set, including the colon-free `fixtures/dev_geometry` layouts. Pytest generates the text corpora at the start of the session. `fixtures/dev_geometry` prints catalog labels with no colon. It is a seen development set. The held-out set is scored by an independent reviewer; not in this repo.
