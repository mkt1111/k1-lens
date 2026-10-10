"""Create the seeded corpora when a checkout does not contain them."""

from __future__ import annotations

from pathlib import Path

from k1lens.generate.corpus import DEFAULT_SEED, generate_corpus
from k1lens.generate.dev_b import generate_dev_b
from k1lens.generate.dev_layouts import generate_dev
from k1lens.generate.geometry import generate_dev_geometry
from k1lens.generate.scans import generate_scans


def corpus_ready(dest: Path) -> bool:
    return (dest / "manifest.json").is_file()


def ensure_corpus(dest: Path, kind: str, *, seed: int = DEFAULT_SEED) -> None:
    """Write ``kind`` into ``dest`` when ``manifest.json`` is missing."""

    if corpus_ready(dest):
        return
    if kind == "synthetic":
        generate_corpus(dest, seed=seed, count=14)
        return
    if kind == "dev":
        generate_dev(dest, seed=seed)
        return
    if kind == "dev_b":
        generate_dev_b(dest, seed=seed)
        return
    if kind == "dev_geometry":
        generate_dev_geometry(dest, seed=seed)
        return
    if kind == "scans":
        generate_scans(dest, seed=seed)
        return
    raise ValueError(f"Unknown corpus kind: {kind}")


def ensure_review_corpora(root: Path = Path("fixtures"), *, seed: int = DEFAULT_SEED) -> None:
    """Generate the text corpora the review UI and the eval read.

    Image-only scans stay out of this helper. They are large and are generated
    by ``k1lens generate --scans`` or by ``k1lens eval --compare``.
    """

    ensure_corpus(root / "synthetic", "synthetic", seed=seed)
    ensure_corpus(root / "dev", "dev", seed=seed)
    ensure_corpus(root / "dev_b", "dev_b", seed=seed)
    ensure_corpus(root / "dev_geometry", "dev_geometry", seed=seed)
