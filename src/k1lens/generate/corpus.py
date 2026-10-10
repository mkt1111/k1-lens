"""Write a seeded corpus of PDFs and ground-truth JSON."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from k1lens.domain.models import ScheduleK1
from k1lens.generate.build import (
    DEFAULT_PLAN,
    PLANTED_DEFECTS,
    Variant,
    build_document,
    plan_for_count,
)
from k1lens.generate.pdf import render_pdf

GENERATOR_VERSION = "1"
DEFAULT_SEED = 1065


class ManifestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    variant: str
    pdf: str
    ground_truth: str
    planted_defects: list[str]
    layout: str = ""
    dpi: int | None = None
    degradation: str = ""


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    count: int
    generator_version: str
    synthetic_only: Literal[True] = True
    documents: list[ManifestDocument]


class GroundTruthFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic_only: Literal[True] = True
    planted_defects: list[str]
    document: ScheduleK1


def generate_corpus(
    dest: Path,
    *,
    seed: int = DEFAULT_SEED,
    count: int | None = None,
    plan: tuple[Variant, ...] | None = None,
) -> Manifest:
    """Write a reproducible corpus. Same seed and plan always write the same JSON.

    PDF bytes are reproducible when reportlab's invariant mode and the pinned
    renderer versions are used.
    """

    variants = plan_for_count(count if count is not None else len(DEFAULT_PLAN), plan)
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("K1-*"):
        if stale.suffix in {".pdf", ".json"}:
            stale.unlink()
    rng = random.Random(seed)
    documents: list[ManifestDocument] = []
    for index, variant in enumerate(variants, start=1):
        document = build_document(rng, index, variant)
        pdf_name = f"{document.document_id}.pdf"
        json_name = f"{document.document_id}.json"
        render_pdf(document, dest / pdf_name)
        truth = GroundTruthFile(
            planted_defects=list(PLANTED_DEFECTS[variant]),
            document=document,
        )
        (dest / json_name).write_text(truth.model_dump_json(indent=2) + "\n", encoding="utf-8")
        documents.append(
            ManifestDocument(
                document_id=document.document_id,
                variant=variant.value,
                pdf=pdf_name,
                ground_truth=json_name,
                planted_defects=list(PLANTED_DEFECTS[variant]),
            )
        )
    manifest = Manifest(
        seed=seed,
        count=len(documents),
        generator_version=GENERATOR_VERSION,
        documents=documents,
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(directory: Path) -> Manifest:
    return Manifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))


def load_ground_truth(path: Path) -> GroundTruthFile:
    return GroundTruthFile.model_validate_json(path.read_text(encoding="utf-8"))
