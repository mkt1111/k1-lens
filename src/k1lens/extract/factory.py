"""Pick an extraction backend by name."""

from __future__ import annotations

from k1lens.extract.base import Extractor
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.hybrid import HybridExtractor
from k1lens.extract.llm import LLMExtractor, llm_configured

__all__ = ["get_extractor", "llm_configured"]


def get_extractor(backend: str) -> Extractor:
    name = backend.strip().lower()
    if name == "deterministic":
        return DeterministicExtractor()
    if name == "llm":
        return LLMExtractor()
    if name == "hybrid":
        return HybridExtractor()
    raise ValueError(f"Unknown extraction backend: {backend}. Use deterministic, llm, or hybrid.")
