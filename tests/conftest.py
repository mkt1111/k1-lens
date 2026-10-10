"""Shared fixtures. Corpus generation stays small so the suite stays quick."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from k1lens.generate.build import Variant
from k1lens.generate.corpus import generate_corpus
from k1lens.review.app import create_app

PLAN = (
    Variant.CLEAN,
    Variant.INCONSISTENT_CAPITAL,
    Variant.MISSING_FIELDS,
    Variant.INVALID_EIN,
    Variant.INVALID_PERCENTAGE,
)


@pytest.fixture(scope="session", autouse=True)
def _review_corpora() -> None:
    """The text corpora are generated from the seed and are not stored in git."""

    from k1lens.generate.ensure import ensure_review_corpora

    ensure_review_corpora()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    dest = tmp_path / "corpus"
    generate_corpus(dest, seed=7, count=len(PLAN), plan=PLAN)
    return dest


@pytest.fixture
def client(corpus: Path, tmp_path: Path) -> Iterator[TestClient]:
    application = create_app(db_path=tmp_path / "review.db", fixture_dir=corpus, auto_ingest=True)
    with TestClient(application) as test_client:
        yield test_client
