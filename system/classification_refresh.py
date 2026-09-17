"""Drain local archive-classification refresh work in bounded batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

MAX_BATCHES = 1_000


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


def _selection_id(selection: dict) -> str:
    """Name the canonical pending snapshot set for the no-progress guard."""
    payload = [
        {
            "source_path": item.get("source_path"),
            "reason": item.get("reason"),
            "snapshot": item.get("snapshot"),
        }
        for item in selection.get("targets", [])
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _compile_checkpoint(root: Path) -> Path:
    from vault_paths import vault_data_path

    return vault_data_path("compile_needed", vault_root=root)


def _mark_publication_needed(root: Path) -> None:
    from vault_paths import atomic_write_vault_text

    atomic_write_vault_text(
        _compile_checkpoint(root),
        "classification refresh requires publication\n",
        vault_root=root,
    )


def clear_publication_checkpoint(vault_root: str | Path) -> None:
    """Clear the existing compile checkpoint after full downstream success."""
    from vault_paths import unlink_vault_file

    root = Path(vault_root)
    unlink_vault_file(
        _compile_checkpoint(root),
        vault_root=root,
        missing_ok=True,
    )


def _migrate(root: Path, sources: list[str] | None) -> dict:
    import classifier_claims

    return classifier_claims.migrate_classifier_moments(
        root,
        sources=sources,
        dry_run=False,
        publish=False,
    )


def run_batch(
    vault_root: str | Path,
    *,
    limit: int,
    model: str | None = None,
) -> dict:
    """Drain canonical work through bounded batches and checkpoint publication.

    Provider calls are intentionally serial here. Hosted batching is a separate
    concern; this local worker owns one bounded archive transaction at a time.
    Migration runs between batches because accepted direct facts can make older
    stories newly eligible for link-only refresh. The existing compile-needed
    sentinel is the crash checkpoint: a retry migrates current classifications
    before replanning, then the CLI retires and compiles once at the end.
    """
    import classifier_context
    import classify_story

    root = Path(vault_root)
    if limit < 1:
        raise ValueError("classification refresh limit must be positive")
    selected_model = model
    checkpoint = _compile_checkpoint(root)
    publication_needed = checkpoint.is_file()
    if publication_needed:
        # Filing may have completed before migration or compile. Rebuilding
        # from every current classification is idempotent and needs no model.
        _migrate(root, None)

    accepted_sources: list[str] = []
    receipt_paths: list[str] = []
    counts = {"accepted": 0, "refused": 0, "already_current": 0}
    plans: list[dict] = []
    seen_pending: set[str] = set()
    batch_number = 0

    while True:
        sources, ineligible = classify_story.classification_inventory()
        selection = classifier_context.select_refresh_targets(
            root, sources, limit=limit
        )
        selection["ineligible_count"] = len(ineligible)
        selection["ineligible_items"] = ineligible
        selection["complete"] = bool(selection["complete"] and not ineligible)
        if selection["selected_count"] == 0:
            if not selection["complete"]:
                raise ClassificationRefreshError(
                    "canonical refresh made no progress because source inventory was ineligible"
                )
            status = (
                "accepted"
                if accepted_sources
                else ("resume" if publication_needed else "unchanged")
            )
            return {
                "status": status if counts["refused"] == 0 else "partial",
                "selection": selection,
                "plans": plans,
                "receipt_paths": receipt_paths,
                "counts": counts,
                "accepted_sources": accepted_sources,
                "publication_needed": publication_needed,
                "batch_count": len(plans),
            }

        if batch_number >= MAX_BATCHES:
            raise ClassificationRefreshError(
                f"canonical refresh exceeded the {MAX_BATCHES}-batch progress bound"
            )

        pending_id = _selection_id(selection)
        if pending_id in seen_pending:
            raise ClassificationRefreshError(
                "canonical refresh repeated the same pending snapshot set without progress"
            )
        seen_pending.add(pending_id)

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

        response_items = []
        if selected_model is None:
            selected_model = classify_story.get_model(SimpleNamespace(model=None))
        for item in plan["items"]:
            response = classify_story.classify_with_ai(item["prompt"], selected_model)
            response_items.append(
                {
                    "source_path": item["source_path"],
                    "mode": item["mode"],
                    "response_text": json.dumps(response, sort_keys=True),
                }
            )

        envelope = {
            "schema_version": 1,
            "batch_id": _batch_id(plan["items"], response_items),
            "skip_candidates": True,
            "items": response_items,
        }
        # Filing can durably replace classifications before it returns. Record
        # the downstream obligation first so a crash in that window is safe.
        _mark_publication_needed(root)
        publication_needed = True
        receipt = classify_story.file_batch_response(envelope, model=selected_model)
        accepted = [
            item["source_path"]
            for item in receipt["items"]
            if item["status"] == "accepted"
        ]
        if not accepted:
            raise ClassificationRefreshError(
                "canonical archive batch filed no accepted classification changes"
            )

        batch_number += 1
        accepted_sources.extend(accepted)
        receipt_paths.append(receipt["receipt_path"])
        for name in counts:
            counts[name] += receipt["counts"][name]
        plans.append(
            {
                "batch": batch_number,
                **{
                    key: plan[key]
                    for key in ("selected_count", "pending_count", "remaining_count")
                },
            }
        )
        _migrate(root, accepted)
