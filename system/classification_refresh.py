#!/usr/bin/env python3
"""Run one bounded local archive-classification refresh batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


class ClassificationRefreshError(RuntimeError):
    """A canonical refresh had pending work but could not make progress."""


def _batch_id(plan_items: list[dict], response_items: list[dict]) -> str:
    identity = [
        {
            "source_path": planned["source_path"],
            "mode": planned["mode"],
            "snapshot": planned["snapshot"],
            "response_text": response["response_text"],
        }
        for planned, response in zip(plan_items, response_items, strict=True)
    ]
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    return f"local-refresh-{digest}"


def run_batch(
    vault_root: str | Path,
    *,
    limit: int,
    model: str | None = None,
) -> dict:
    """Select, call, and file one canonical batch using existing classifier APIs.

    Provider calls are intentionally serial here. Hosted batching is a separate
    concern; this local worker owns one bounded archive transaction at a time.
    """
    import classifier_context
    import classify_story

    root = Path(vault_root)
    sources, ineligible = classify_story.classification_inventory()
    selection = classifier_context.select_refresh_targets(root, sources, limit=limit)
    selection["ineligible_count"] = len(ineligible)
    selection["ineligible_items"] = ineligible
    selection["complete"] = bool(selection["complete"] and not ineligible)
    if selection["selected_count"] == 0:
        if not selection["complete"]:
            raise ClassificationRefreshError(
                "canonical refresh made no progress because source inventory was ineligible"
            )
        return {
            "status": "unchanged",
            "selection": selection,
            "accepted_sources": [],
            "counts": {"accepted": 0, "refused": 0, "already_current": 0},
        }

    selected_sources = [root / row["source_path"] for row in selection["targets"]]
    plan = classify_story.build_batch_plan(
        limit=limit,
        sources=selected_sources,
        skip_candidates=True,
    )
    if plan["selected_count"] == 0:
        raise ClassificationRefreshError(
            "canonical refresh selected pending work but the archive batch planned none"
        )

    selected_model = model or classify_story.get_model(SimpleNamespace(model=None))
    response_items = []
    for item in plan["items"]:
        response = classify_story.classify_with_ai(item["prompt"], selected_model)
        response_items.append({
            "source_path": item["source_path"],
            "mode": item["mode"],
            "response_text": json.dumps(response, sort_keys=True),
        })

    envelope = {
        "schema_version": 1,
        "batch_id": _batch_id(plan["items"], response_items),
        "skip_candidates": True,
        "items": response_items,
    }
    receipt = classify_story.file_batch_response(envelope, model=selected_model)
    accepted_sources = [
        item["source_path"]
        for item in receipt["items"]
        if item["status"] == "accepted"
    ]
    if not accepted_sources:
        raise ClassificationRefreshError(
            "canonical archive batch filed no accepted classification changes"
        )
    return {
        "status": "accepted" if receipt["counts"]["refused"] == 0 else "partial",
        "selection": selection,
        "plan": {
            key: plan[key]
            for key in ("selected_count", "pending_count", "remaining_count")
        },
        "receipt_path": receipt["receipt_path"],
        "counts": receipt["counts"],
        "accepted_sources": accepted_sources,
    }
