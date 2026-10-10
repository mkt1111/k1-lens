"""Compare an eval report to committed accuracy floors."""

from __future__ import annotations

import json
from pathlib import Path

from k1lens.eval.harness import EvalReport


def load_floors(path: Path, distribution: str) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or distribution not in payload:
        raise ValueError(f"Baseline {path} has no {distribution} object")
    block = payload[distribution]
    if not isinstance(block, dict):
        raise ValueError(f"Baseline {distribution} must be an object")
    floors: dict[str, float] = {}
    for key, value in block.items():
        if key == "note":
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"Baseline floor {distribution}.{key} is not a number")
        floors[str(key)] = float(value)
    return floors


def baseline_failures(report: EvalReport, floors: dict[str, float]) -> list[str]:
    """Return human-readable failures. An empty list means the floors held."""

    failures: list[str] = []
    for key, floor in floors.items():
        ceiling = key.startswith("max_")
        metric = key.removeprefix("max_") if ceiling else key
        actual = _actual(report, metric)
        if actual is None:
            if floor > 0:
                failures.append(f"{key}: no rate to compare with floor {floor:.4f}")
            continue
        if ceiling:
            if actual > floor + 1e-9:
                failures.append(f"{key}: {actual:.4f} is above ceiling {floor:.4f}")
            continue
        if actual + 1e-9 < floor:
            failures.append(f"{key}: {actual:.4f} is below floor {floor:.4f}")
    return failures


def _actual(report: EvalReport, key: str) -> float | None:
    if key == "text_layer_accuracy":
        return report.text_layer.accuracy
    if key == "rasterized_accuracy":
        return report.rasterized.accuracy
    if key == "overall_accuracy":
        return report.overall.accuracy
    if key == "ground_truth_catch_rate":
        return report.ground_truth_catch.rate
    if key == "min_documents":
        return float(report.documents)
    if key == "confident_wrong":
        return float(len(report.confident_wrong))
    if key == "straight_through_rate":
        if report.documents == 0:
            return None
        return report.straight_through / report.documents
    if key == "overall_precision":
        return report.overall.precision
    if key == "text_layer_precision":
        return report.text_layer.precision
    if key == "rasterized_precision":
        return report.rasterized.precision
    if key.startswith("variant_precision:"):
        name = key.removeprefix("variant_precision:")
        counts = report.by_variant.get(name)
        if counts is None:
            return None
        return counts.precision
    if key.startswith("variant:"):
        name = key.removeprefix("variant:")
        counts = report.by_variant.get(name)
        if counts is None:
            return None
        return counts.accuracy
    raise ValueError(f"Unknown baseline key {key}")
