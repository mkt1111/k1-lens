"""Extractor interface shared by the deterministic and LLM backends."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1


class Extractor(Protocol):
    name: str

    def extract(self, pdf_path: Path, *, threshold: float = REVIEW_THRESHOLD) -> ScheduleK1:
        """Read one PDF and return a synthetic Schedule K-1."""


class ExtractionError(Exception):
    """The extractor could not turn the response into a Schedule K-1."""


class MalformedReply(ExtractionError):
    """The model reply was not valid JSON in the expected shape."""


class LLMNotConfiguredError(ExtractionError):
    """No API key is set. The caller should skip the LLM backend."""


class SpendCeilingExceeded(ExtractionError):
    """The next model call would pass the per-run spend ceiling."""

    def __init__(self, spent: float, ceiling: float) -> None:
        self.spent = spent
        self.ceiling = ceiling
        super().__init__(
            f"Spend ceiling of ${ceiling:.2f} reached at ${spent:.4f}. "
            "Stopped before the next model call."
        )


class UnpricedModelError(ExtractionError):
    """The model has no list price, so a spend ceiling cannot be enforced."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"Model {model} has no list price in this repo, so the spend ceiling "
            "cannot be enforced. Pick a priced model such as gpt-4o-mini."
        )
