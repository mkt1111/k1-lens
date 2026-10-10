"""SHA-256 check for a generated scan corpus.

``docs/scan-hashes.json`` is pinned to the CI runner image. CI builds the
scans once and compares every file. Eight documents differ on another Linux
box, so ``check_scan_hashes`` returns without comparing unless ``CI`` is set.
``require_scan_hashes`` itself always exits on a mismatch. A unit test checks
that comparison on a few bytes. It does not rebuild the corpus.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def file_hashes(dest: Path) -> dict[str, str]:
    """SHA-256 of each file in ``dest``, keyed by file name."""

    hashes: dict[str, str] = {}
    for path in sorted(dest.iterdir()):
        if path.is_file():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def manifest_is_enforced() -> bool:
    """True on the CI runner, where the committed hashes were pinned.

    GitHub Actions sets ``CI``. Another Linux box can rewrite eight of the
    same-seed documents, so a local run does not treat that as a failure.
    """

    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def check_scan_hashes(dest: Path, manifest: Path) -> None:
    """Compare scan bytes when this process is the CI runner.

    Outside CI this returns without reading the files. CI calls
    ``require_scan_hashes`` directly and still fails on a mismatch.
    """

    if manifest_is_enforced():
        require_scan_hashes(dest, manifest)


def require_scan_hashes(dest: Path, manifest: Path) -> None:
    """Exit when ``dest`` is not the byte corpus named by ``manifest``."""

    loaded = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str) for name, digest in loaded.items()
    ):
        raise SystemExit(f"{manifest.name}: expected a filename to sha256 map")
    expected = {name: digest for name, digest in loaded.items()}
    actual = file_hashes(dest)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(name for name in expected if name in actual and expected[name] != actual[name])
    if not missing and not extra and not changed:
        return
    parts: list[str] = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if extra:
        parts.append("extra " + ", ".join(extra))
    if changed:
        parts.append("changed " + ", ".join(changed))
    raise SystemExit(f"scan hashes do not match {manifest.name}: " + "; ".join(parts))
