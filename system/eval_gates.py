"""Generic score-threshold arithmetic for independent Interaction harnesses."""

from __future__ import annotations


def check_score_gates(
    scores: dict[str, dict],
    gates: dict[str, dict[str, float]],
    *,
    prefix: str,
) -> list[str]:
    """Return every absent/below-threshold metric in deterministic order."""
    failures: list[str] = []
    for score_class, thresholds in gates.items():
        class_scores = scores.get(score_class, {})
        for metric, threshold in thresholds.items():
            actual = class_scores.get(metric)
            if actual is None or actual < threshold:
                failures.append(
                    f"{prefix}.{score_class}.{metric}: {actual!r} < {threshold} required"
                )
    return failures
