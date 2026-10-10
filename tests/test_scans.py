"""Image-only scan corpus. The PDFs are generated from the seed, not committed."""

import json
import random
from pathlib import Path

import pdfplumber
import pytest
from typer.testing import CliRunner

from k1lens.cli import app
from k1lens.eval.harness import is_image_only
from k1lens.generate.corpus import load_ground_truth, load_manifest
from k1lens.generate.scans import (
    FAILURE_COUNT,
    FAILURE_MODES,
    MIN_SCANS,
    SCAN_COUNT,
    _degrade,
    failure_mode_of,
    failure_recipes,
    generate_scans,
    scan_recipes,
)

runner = CliRunner()


def test_scan_recipes_cover_layouts_and_degradation() -> None:
    recipes = scan_recipes(SCAN_COUNT, random.Random(1065))
    assert len(recipes) >= MIN_SCANS
    layouts = {recipe.layout for recipe in recipes}
    assert layouts == {"catalog", "dev_statement", "dev_b"}
    assert min(recipe.dpi for recipe in recipes) >= 150
    assert max(recipe.dpi for recipe in recipes) <= 300
    assert len({recipe.dpi for recipe in recipes}) >= 4
    assert any(recipe.faint for recipe in recipes)
    assert sum(recipe.faint for recipe in recipes) >= 3
    assert all(abs(recipe.rotation) >= 0.4 for recipe in recipes)
    assert all(recipe.blur > 0 for recipe in recipes)
    assert all(40 <= recipe.jpeg_quality <= 95 for recipe in recipes)
    assert all(recipe.noise > 0 for recipe in recipes)
    assert all(abs(recipe.skew) >= 0.01 for recipe in recipes)


def test_failure_recipes_are_deliberately_hard() -> None:
    recipes = failure_recipes()
    assert [recipe.failure for recipe in recipes] == list(FAILURE_MODES)
    assert len(recipes) == FAILURE_COUNT
    by_mode = {recipe.failure: recipe for recipe in recipes}
    assert all(recipe.layout == "catalog" for recipe in recipes)
    assert all(recipe.variant == "scan_hard" for recipe in recipes)
    assert by_mode["low_dpi"].dpi <= 72
    assert by_mode["low_dpi"].dpi < 150
    assert abs(by_mode["skew"].rotation) >= 12
    assert abs(by_mode["skew"].skew) >= 0.2
    assert all(failure_mode_of(recipe.describe()) == recipe.failure for recipe in recipes)
    assert failure_mode_of("dpi=200") == ""


def test_failure_damage_changes_the_page() -> None:
    from PIL import Image, ImageDraw

    page = Image.new("RGB", (240, 320), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    draw.rectangle((20, 40, 200, 280), fill=(0, 0, 0))
    original = page.tobytes()
    for recipe in failure_recipes():
        damaged = _degrade(page.copy(), recipe)
        assert damaged.mode == "RGB"
        assert damaged.tobytes() != original
    crop = next(recipe for recipe in failure_recipes() if recipe.failure == "crop")
    cropped = _degrade(page.copy(), crop)
    assert cropped.getpixel((10, 300)) == (255, 255, 255)
    assert cropped.getpixel((30, 40)) != (255, 255, 255)


def test_readme_names_the_known_failure_cases() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    evaluation = Path("docs/EVALUATION.md").read_text(encoding="utf-8")
    assert "Known failure cases" in readme
    assert "docs/EVALUATION.md#known-failure-cases" in readme
    assert "### Known failure cases" in evaluation
    readme = evaluation
    for document_id in (
        "K1-FAIL-0001",
        "K1-FAIL-0002",
        "K1-FAIL-0003",
        "K1-FAIL-0004",
        "K1-FAIL-0005",
        "K1-FAIL-0006",
        "K1-SCAN-0004",
        "K1-SCAN-0013",
    ):
        assert document_id in readme
    assert "9298" in readme
    assert "44365.00" in readme


def test_fewer_than_twenty_scans_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 20"):
        generate_scans(tmp_path, seed=1, count=19)
    with pytest.raises(ValueError, match="at least 1"):
        generate_scans(tmp_path, seed=1, count=0, include_failures=False)


def test_scan_command_rejects_a_short_corpus(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate", "--scans", "--out", str(tmp_path), "--count", "19"],
    )
    assert result.exit_code == 2
    assert "at least 20" in result.output


@pytest.mark.slow
def test_generated_scans_are_image_only_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = generate_scans(first, seed=1065, count=3, include_failures=False)
    again = generate_scans(second, seed=1065, count=3, include_failures=False)
    assert manifest.count == 3
    assert again.count == 3
    loaded = load_manifest(first)
    layouts = {entry.layout for entry in loaded.documents}
    assert layouts == {"catalog", "dev_statement", "dev_b"}
    assert all(is_image_only(entry.variant) for entry in loaded.documents)
    assert list(first.glob("K1-FAIL-*")) == []
    for entry in loaded.documents:
        assert (first / entry.pdf).read_bytes() == (second / entry.pdf).read_bytes()
        ein = load_ground_truth(first / entry.ground_truth).document.part_i.ein.value
        assert ein is not None and ein.startswith("00-")
    sample = loaded.documents[0]
    with pdfplumber.open(str(first / sample.pdf)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Partnership EIN" not in text
    assert text.strip() == ""


def test_scan_hash_manifest_names_a_changed_missing_or_extra_file(tmp_path: Path) -> None:
    from k1lens.generate.scan_hashes import file_hashes, require_scan_hashes

    dest = tmp_path / "scans"
    dest.mkdir()
    (dest / "a.pdf").write_bytes(b"one")
    (dest / "b.json").write_bytes(b"two")
    manifest = tmp_path / "hashes.json"
    manifest.write_text(json.dumps(file_hashes(dest)), encoding="utf-8")
    require_scan_hashes(dest, manifest)
    (dest / "a.pdf").write_bytes(b"changed")
    with pytest.raises(SystemExit, match=r"changed a\.pdf"):
        require_scan_hashes(dest, manifest)
    (dest / "a.pdf").unlink()
    with pytest.raises(SystemExit, match=r"missing a\.pdf"):
        require_scan_hashes(dest, manifest)
    (dest / "a.pdf").write_bytes(b"one")
    (dest / "c.pdf").write_bytes(b"extra")
    with pytest.raises(SystemExit, match=r"extra c\.pdf"):
        require_scan_hashes(dest, manifest)
    manifest.write_text("[]\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="filename to sha256 map"):
        require_scan_hashes(dest, manifest)


def test_scan_byte_check_is_skipped_outside_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from k1lens.generate.scan_hashes import check_scan_hashes, manifest_is_enforced

    monkeypatch.delenv("CI", raising=False)
    assert manifest_is_enforced() is False
    dest = tmp_path / "scans"
    dest.mkdir()
    (dest / "a.pdf").write_bytes(b"local-bytes")
    manifest = tmp_path / "hashes.json"
    manifest.write_text(json.dumps({"a.pdf": "0" * 64}), encoding="utf-8")
    check_scan_hashes(dest, manifest)
    monkeypatch.setenv("CI", "true")
    assert manifest_is_enforced() is True
    with pytest.raises(SystemExit, match=r"changed a\.pdf"):
        check_scan_hashes(dest, manifest)


def test_committed_scan_hash_manifest_lists_the_corpus() -> None:
    payload = json.loads(Path("docs/scan-hashes.json").read_text(encoding="utf-8"))
    names = set(payload)
    assert len(payload) == 61
    assert sum(name.endswith(".pdf") for name in names) == 30
    assert sum(name.endswith(".json") for name in names) == 31
    assert "manifest.json" in names
    assert all(isinstance(digest, str) and len(digest) == 64 for digest in payload.values())
