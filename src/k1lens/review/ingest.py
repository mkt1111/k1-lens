"""Load a generated corpus into the review queue."""

from __future__ import annotations

import logging
from pathlib import Path

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.assemble import assemble
from k1lens.extract.base import Extractor
from k1lens.generate.corpus import load_manifest
from k1lens.review.store import ReviewStore
from k1lens.roster import bind_roster
from k1lens.validate.engine import validate_document

logger = logging.getLogger(__name__)


def ingest_fixtures(
    store: ReviewStore,
    fixture_dir: Path,
    extractor: Extractor,
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> int:
    manifest = load_manifest(fixture_dir)
    for entry in manifest.documents:
        pdf_path = fixture_dir / entry.pdf
        try:
            extracted = extractor.extract(pdf_path, threshold=threshold)
        except Exception as exc:
            logger.exception("Skipping %s (%s)", entry.pdf, type(exc).__name__)
            extracted = assemble(
                entry.document_id,
                {},
                extractor=getattr(extractor, "name", "deterministic"),
                threshold=threshold,
                ocr_failed_pages=(1,),
            )
        extracted = extracted.model_copy(
            update={"document_id": entry.document_id, "variant": entry.variant}
        )
        extracted = bind_roster(extracted, store.roster, threshold=threshold)
        findings = validate_document(extracted, roster=store.roster)
        store.upsert(extracted, pdf_path.read_bytes(), findings)
    return len(manifest.documents)
