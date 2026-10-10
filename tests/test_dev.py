"""Development layouts stay outside the extractor's label catalog."""

import random
from pathlib import Path

from k1lens.domain.fields import CODED_BOXES, SCALAR_BY_LABEL, SCALAR_FIELDS
from k1lens.eval.harness import evaluate
from k1lens.extract.ocr import within_one_edit
from k1lens.extract.text import parse_lines, plain_text
from k1lens.generate.build import Variant, build_document
from k1lens.generate.dev_layouts import (
    DEV_STATEMENT_CODED,
    DEV_STATEMENT_LABELS,
    generate_dev,
    render_dev,
)


def test_dev_statement_labels_cover_the_catalog_without_reusing_it() -> None:
    assert set(DEV_STATEMENT_LABELS) == {spec.path for spec in SCALAR_FIELDS}
    assert set(DEV_STATEMENT_CODED) == {spec.path for spec in CODED_BOXES}
    catalog = set(SCALAR_BY_LABEL)
    for label in DEV_STATEMENT_LABELS.values():
        assert label not in catalog
        assert not any(within_one_edit(label, known) for known in catalog)


def test_dev_statement_pdf_does_not_print_catalog_labels(tmp_path: Path) -> None:
    document = build_document(random.Random(3), 1, Variant.CLEAN).model_copy(
        update={"variant": "dev_statement"}
    )
    dest = tmp_path / "dev-statement.pdf"
    render_dev(document, dest, kind="dev_statement")
    labels = set(parse_lines(plain_text(dest)))
    assert labels.isdisjoint(SCALAR_BY_LABEL)
    for label in labels:
        for box in CODED_BOXES:
            assert not label.startswith(f"{box.pdf_prefix} ")


def test_layout_shift_keeps_catalog_labels_and_dev_statement_does_not(tmp_path: Path) -> None:
    dest = tmp_path / "dev"
    generate_dev(dest, seed=11)
    report = evaluate(dest, distribution="dev")
    assert report.by_variant["layout_shift"].accuracy == 1
    statement = report.by_variant["dev_statement"]
    assert statement.mismatch == 0
    assert statement.spurious == 0
    assert statement.precision == 1
    assert statement.missed > statement.correct
