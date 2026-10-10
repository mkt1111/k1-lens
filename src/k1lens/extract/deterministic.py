"""Label parser for machine-readable K-1 facsimiles. No network, no API key."""

from __future__ import annotations

from pathlib import Path

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.extract.assemble import assemble, has_field_labels
from k1lens.extract.labels import canonicalize_observed
from k1lens.extract.ocr import ocr_enabled, read_ocr
from k1lens.extract.text import UnreadablePdf, read_observed


class DeterministicExtractor:
    name = "deterministic"

    def extract(self, pdf_path: Path, *, threshold: float = REVIEW_THRESHOLD) -> ScheduleK1:
        blank: list[int] = []
        try:
            raw = read_observed(pdf_path, extractor=self.name, blank_pages=blank)
        except UnreadablePdf:
            return assemble(
                pdf_path.stem,
                {},
                extractor=self.name,
                threshold=threshold,
                ocr_failed_pages=(1,),
            )
        observed, stats = canonicalize_observed(raw)
        failed: tuple[int, ...] = ()
        if blank:
            if ocr_enabled():
                ocr = read_ocr(pdf_path, only_pages=tuple(blank))
                if ocr is None:
                    failed = tuple(blank)
                else:
                    failed = ocr.failed_pages
                    if ocr.fields:
                        merged = dict(raw)
                        for label, rows in ocr.fields.items():
                            merged.setdefault(label, []).extend(rows)
                        observed, stats = canonicalize_observed(merged)
            else:
                failed = tuple(blank)
        elif not has_field_labels(observed) and ocr_enabled():
            ocr = read_ocr(pdf_path)
            if ocr is not None:
                failed = ocr.failed_pages
                if ocr.fields:
                    observed, stats = canonicalize_observed(ocr.fields)
        return assemble(
            pdf_path.stem,
            observed,
            extractor=self.name,
            layout_stats=stats,
            threshold=threshold,
            ocr_failed_pages=failed,
        )
