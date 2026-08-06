#!/usr/bin/env python3
"""AI correspondent dossiers (v108): auto-applied calibration, not per-item
approval.

Heuristics can't know that an unknown high-volume correspondent is the owner's
sister. For the top UNCLASSIFIED correspondents (not declared VIPs, not
roster/wiki-known, above a volume floor, not automated senders), sample 2–3 of
their highest-narrative-density threads, read those bodies narrowly, and ask
the model for one compact JSON verdict — who is this person to the owner?

Privacy guardrails (hard rules):
- Content is read NARROWLY for classification. Only the classification verdict
  persists (state/connectors/<name>_dossiers.json) — never the model's
  reasoning about the content.
- Bodies are cached (committed) under state/connectors/<name>_body_cache/
  keyed by message id, so re-runs, promotions, and future passes never
  re-fetch what was already pulled.
- A correspondent with a fresh dossier is never re-classified unless their
  ledger stats changed materially (new messages since classified_at) or
  --redossier is passed.
- Verdicts auto-apply during scoring only as VIPs (configured classes at/over
  the confidence floor); the owner vetoes via vip_blocklist in weights.json.

The AI caller is injectable (same pattern as the GmailClient injection) —
tests never touch the network or a real model.
"""

from __future__ import annotations

import re
from pathlib import Path

from lifehug_core import load_config, now_utc, read_json, write_json
from connectors.scoring import (
    address_tokens,
    is_noreply,
    load_scoring_config,
    tokens_known,
)

CLASSIFICATIONS = ("family", "close_friend", "colleague", "service", "unknown")

DEFAULT_DOSSIER_LIMIT = 30
SAMPLE_THREAD_COUNT = 3
MAX_SAMPLE_MESSAGES = 6   # per sampled thread, keeps the prompt bounded
MAX_BODY_WORDS = 2000

_QUOTED_HEADER_RE = re.compile(r"^On .{0,120}wrote:\s*$")


# ---------------------------------------------------------------------------
# Dossier persistence
# ---------------------------------------------------------------------------

def load_dossiers(path: Path) -> dict:
    """The dossier store: {"version": 1, "dossiers": {email: verdict-record}}.
    Each record carries the verdict, model, classified_at, sampled thread ids,
    and the correspondent's message count at classification time."""
    data = read_json(path, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "dossiers": {}}
    data.setdefault("version", 1)
    if not isinstance(data.get("dossiers"), dict):
        data["dossiers"] = {}
    return data


# ---------------------------------------------------------------------------
# Body preparation: quoted chains stripped, each message ~2000 words max
# ---------------------------------------------------------------------------

def strip_quoted(text: str) -> str:
    """Drop quoted-reply chains: '>' lines, and everything after an
    'On … wrote:' header. Keeps only what THIS sender wrote."""
    lines: list[str] = []
    for line in str(text or "").splitlines():
        if _QUOTED_HEADER_RE.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def truncate_words(text: str, max_words: int = MAX_BODY_WORDS) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    return " ".join(words[:max_words]).strip() + " …"


def prepare_excerpt(body: str) -> str:
    return truncate_words(strip_quoted(body))


# ---------------------------------------------------------------------------
# Prompt + verdict
# ---------------------------------------------------------------------------

def build_prompt(email: str, stats: dict, samples: list[dict]) -> str:
    """samples: [{thread_id, subject, messages: [{date, from_name, from_email, body}]}]."""
    display = stats.get("name") or email
    lines = [
        "You are calibrating a private life-story archive's email evidence. Below are",
        "sample email threads between the archive owner and ONE correspondent. Judge",
        "who this correspondent is (or was) to the owner.",
        "",
        f"Correspondent: {display} <{email}>",
        f"Ledger stats: {stats.get('messages', 0)} messages over {stats.get('span_days', 0)} days "
        f"({stats.get('first_date', '?')} → {stats.get('last_date', '?')}); "
        f"owner replied in {stats.get('owner_replies', 0)} thread(s).",
        "",
    ]
    for sample in samples:
        lines.append(f"### Thread \"{sample['subject']}\" ({len(sample['messages'])} message(s) shown)")
        lines.append("")
        for message in sample["messages"]:
            sender = message.get("from_name") or message.get("from_email") or "?"
            lines.append(f"[{message.get('date', '?')}] {sender} <{message.get('from_email', '?')}>:")
            lines.append(message.get("body") or "(no plain-text body)")
            lines.append("")
    lines += [
        "Reply with ONLY a JSON object, no commentary:",
        '{"classification": "family|close_friend|colleague|service|unknown",',
        ' "significance": "one line on who they are to the owner",',
        ' "suggested_label": "Full Name (relation)",',
        ' "confidence": 0.0}',
        "",
        '"service" covers businesses, newsletters, and automated senders. confidence is',
        "your calibrated 0.0–1.0 certainty in the classification.",
    ]
    return "\n".join(lines)


def normalize_verdict(raw: dict, fallback_label: str) -> dict:
    """Coerce the model's JSON into the persisted verdict shape; anything
    unrecognized degrades to 'unknown' at zero confidence rather than
    crashing the pass."""
    classification = str(raw.get("classification") or "unknown").strip().lower()
    if classification not in CLASSIFICATIONS:
        classification = "unknown"
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "classification": classification,
        "significance": str(raw.get("significance") or "").strip(),
        "suggested_label": str(raw.get("suggested_label") or "").strip() or fallback_label,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Injectable AI + model resolution (CLI flag > config.yaml > default)
# ---------------------------------------------------------------------------

def resolve_model(model: str | None = None) -> str:
    """CLI flag > config.yaml dossier_model > config.yaml classify_model >
    default. dossier_model (v113) lets the connector dossier run on a
    different provider (e.g. Kimi) without moving the weekly classifier."""
    if model:
        return model
    from classify_story import DEFAULT_MODEL  # local import keeps tests light
    config = load_config()
    return config.get("dossier_model") or config.get("classify_model", DEFAULT_MODEL)


def _resolve_ai(ai_caller=None):
    if ai_caller is not None:
        return ai_caller
    from ai_provider import call_ai
    return call_ai


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def _correspondent_automated_share(entries: list[dict], email: str) -> float:
    own = [e for e in entries if str(e.get("from_email") or "").lower() == email]
    if not own:
        return 0.0
    automated = sum(
        1 for e in own if e.get("list_id") or e.get("has_unsubscribe") or e.get("noreply"))
    return automated / len(own)


def select_candidates(
    entries: list[dict],
    context,
    config: dict,
    existing: dict,
    *,
    redossier: bool = False,
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Top unclassified correspondents worth a dossier: not declared VIPs, not
    roster/wiki-known (address alias or name tokens), strictly above the
    message-volume floor, not noreply/mostly-automated. Correspondents with a
    fresh dossier are skipped (returned as the second list) unless their
    ledger stats changed materially or redossier is set."""
    floor = int(config.get("dossier_min_messages") or 0)
    candidates: list[tuple[str, dict]] = []
    skipped_fresh: list[str] = []
    for email, stats in context.correspondent_stats.items():
        if email in context.vip_correspondents:
            continue
        if email in context.known_emails:
            continue
        if is_noreply(email):
            continue
        if int(stats.get("messages") or 0) <= floor:
            continue
        if tokens_known(address_tokens(stats.get("name", ""), email), context.known_any_token_sets):
            continue
        if _correspondent_automated_share(entries, email) > 0.5:
            continue
        prior = existing.get(email)
        if prior and not redossier:
            previous_volume = int(prior.get("messages_at_classification") or 0)
            if int(stats.get("messages") or 0) <= previous_volume:
                skipped_fresh.append(email)
                continue
        candidates.append((email, stats))
    candidates.sort(key=lambda item: (-item[1]["messages"], item[0]))
    return candidates, skipped_fresh


def run_dossier_pass(
    connector,
    *,
    entries: list[dict] | None = None,
    client=None,
    limit: int | None = None,
    model: str | None = None,
    redossier: bool = False,
    dry_run: bool = False,
    ai_caller=None,
) -> dict:
    """Classify the top unclassified correspondents and persist verdicts.
    Called by `connector-dossier` directly and by excavate BEFORE scoring, so
    fresh verdicts calibrate the same run."""
    from connectors.base import load_ledger  # local import: base lazily imports us

    entries = entries if entries is not None else load_ledger(connector.ledger_path)
    summary: dict[str, object] = {
        "connector": connector.name,
        "dry_run": dry_run,
        "candidates": [],
        "classified": [],
        "skipped_fresh": [],
        "errors": [],
    }
    if not entries:
        return summary

    config = load_scoring_config(connector.weights_path)
    context, threads, scored = connector.score_ledger(entries, client=client)
    data = load_dossiers(connector.dossiers_path)
    existing = data["dossiers"]
    candidates, skipped_fresh = select_candidates(
        entries, context, config, existing, redossier=redossier)
    limit = DEFAULT_DOSSIER_LIMIT if limit is None else max(0, int(limit))
    summary["skipped_fresh"] = sorted(skipped_fresh)
    summary["candidates"] = [
        {
            "email": email,
            "name": stats.get("name") or email,
            "messages": stats.get("messages", 0),
            "span_days": stats.get("span_days", 0),
        }
        for email, stats in candidates[:limit]
    ]

    print(f"connector-{connector.name} dossier pass{' (dry run)' if dry_run else ''}: "
          f"{len(summary['candidates'])} correspondent(s) to classify "
          f"({len(candidates) - len(summary['candidates'])} over limit {limit}, "
          f"{len(skipped_fresh)} fresh)")
    if dry_run:
        for row in summary["candidates"]:
            print(f"  would dossier: {row['name']} <{row['email']}> — "
                  f"{row['messages']} messages over {row['span_days']}d")
        return summary

    batch = candidates[:limit]
    if not batch:
        return summary
    ai = _resolve_ai(ai_caller)
    used_model = resolve_model(model)
    now = now_utc()
    for email, stats in batch:
        try:
            thread_ids = [
                tid for tid, thread_entries in threads.items()
                if any(str(e.get("from_email") or "").lower() == email for e in thread_entries)
            ]
            thread_ids.sort(
                key=lambda tid: (-scored[tid]["scores"]["narrative_density"], tid))
            samples: list[dict] = []
            for tid in thread_ids[:SAMPLE_THREAD_COUNT]:
                messages = connector.fetch_thread_cached(client, tid, threads[tid])
                excerpts = [
                    {
                        "date": str(m.get("date") or ""),
                        "from_name": str(m.get("from_name") or ""),
                        "from_email": str(m.get("from_email") or ""),
                        "body": prepare_excerpt(str(m.get("body") or "")),
                    }
                    for m in messages[:MAX_SAMPLE_MESSAGES]
                ]
                subject = next(
                    (str(e.get("subject") or "") for e in threads[tid] if e.get("subject")),
                    "(no subject)")
                samples.append({"thread_id": tid, "subject": subject, "messages": excerpts})
            prompt = build_prompt(email, stats, samples)
            from classify_story import extract_json  # local import keeps it keyless
            verdict = normalize_verdict(extract_json(ai(prompt, used_model)),
                                        fallback_label=stats.get("name") or email)
            existing[email] = {
                **verdict,
                "model": used_model,
                "classified_at": now,
                "thread_ids": [sample["thread_id"] for sample in samples],
                "messages_at_classification": int(stats.get("messages") or 0),
            }
            write_json(connector.dossiers_path, data)  # persist per correspondent
            summary["classified"].append(email)
            print(f"  {email}: {verdict['classification']} ({verdict['confidence']:.2f}) — "
                  f"{verdict['suggested_label']}")
        except Exception as exc:  # noqa: BLE001 — one bad correspondent must not kill the run
            summary["errors"].append(f"{email}: {exc}")
    if summary["errors"]:
        print(f"  {len(summary['errors'])} dossier error(s) — see excavation report/summary")
    return summary
