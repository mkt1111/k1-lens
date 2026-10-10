"""The fund-administrator development set stays out of the extractor."""

import random
from pathlib import Path

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import (
    CODED_BOXES,
    REVIEW_THRESHOLD,
    SCALAR_BY_LABEL,
    SCALAR_FIELDS,
)
from k1lens.eval.harness import evaluate
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.ocr import within_one_edit
from k1lens.extract.text import parse_lines, plain_text
from k1lens.generate.build import Variant, build_document
from k1lens.generate.dev_b import ADMIN_CODED, ADMIN_LABELS, generate_dev_b, render_dev_b
from k1lens.generate.dev_layouts import DEV_STATEMENT_CODED, DEV_STATEMENT_LABELS

_EXTRACT_DIR = Path(__file__).resolve().parents[1] / "src" / "k1lens" / "extract"


def test_admin_labels_cover_fields_without_reusing_known_wording() -> None:
    assert set(ADMIN_LABELS) == {spec.path for spec in SCALAR_FIELDS}
    assert set(ADMIN_CODED) == {spec.path for spec in CODED_BOXES}
    catalog = set(SCALAR_BY_LABEL)
    dev = set(DEV_STATEMENT_LABELS.values())
    for label in ADMIN_LABELS.values():
        assert label not in catalog
        assert label not in dev
        assert not any(within_one_edit(label, known) for known in catalog)
        assert not any(within_one_edit(label, known) for known in dev)
    assert set(ADMIN_CODED.values()).isdisjoint(DEV_STATEMENT_CODED.values())


def test_admin_captions_are_not_in_the_extractor() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _EXTRACT_DIR.glob("*.py"))
    for label in (*ADMIN_LABELS.values(), *ADMIN_CODED.values()):
        assert label not in source
    for label in DEV_STATEMENT_LABELS.values():
        assert label not in source


def test_admin_pdf_does_not_print_catalog_or_dev_labels(tmp_path: Path) -> None:
    document = build_document(random.Random(5), 2, Variant.CLEAN).model_copy(
        update={"variant": "dev_b"}
    )
    dest = tmp_path / "admin.pdf"
    render_dev_b(document, dest)
    labels = set(parse_lines(plain_text(dest)))
    assert labels.isdisjoint(SCALAR_BY_LABEL)
    assert labels.isdisjoint(DEV_STATEMENT_LABELS.values())
    for label in labels:
        for box in CODED_BOXES:
            assert not label.startswith(f"{box.pdf_prefix} ")
    assert any(label.startswith("Ln 1 ") for label in labels)
    assert any("Dist. code" in label for label in labels)


def test_dev_b_corpus_writes_four_documents(tmp_path: Path) -> None:
    dest = tmp_path / "dev_b"
    manifest = generate_dev_b(dest, seed=1065)
    assert manifest.count == 4
    assert manifest.generator_version == "dev-b-1"
    assert {item.variant for item in manifest.documents} == {"dev_b"}
    assert (dest / "K1-0001.pdf").is_file()
    assert (dest / "manifest.json").is_file()


def test_dev_b_is_scored_separately_and_dev_statement_is_unrecognized() -> None:
    admin = evaluate(Path("fixtures/dev_b"), distribution="dev_b")
    assert admin.distribution == "dev_b"
    assert "development set" in " ".join(admin.notes)
    assert admin.overall.spurious == 0
    assert admin.by_field["tax_year"].missed == admin.documents
    assert admin.straight_through == 0
    extracted = DeterministicExtractor().extract(Path("fixtures/dev_b/K1-0001.pdf"))
    assert extracted.document_id == "K1-0001"

    dev = DeterministicExtractor().extract(Path("fixtures/dev/K1-0005.pdf"))
    assert dev.layout_recognized is False
    scores = [get_extracted(dev, spec.path).confidence for spec in SCALAR_FIELDS]
    for box in CODED_BOXES:
        scores.extend(item.amount.confidence for item in get_coded(dev, box.path))
    assert scores
    assert all(score < REVIEW_THRESHOLD for score in scores)
