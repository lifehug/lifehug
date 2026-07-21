#!/usr/bin/env python3
"""Six-axis deterministic relevance scoring for connector ledger threads.

Each thread scores 0–1 on six axes; the weighted total decides its fate
(band assignment). Heuristics only — zero AI cost, and metadata only
(subjects/correspondents; bodies are fetched lazily at promotion or during
calibration sampling, never here).

Three axes are TIME-VARYING by design: relationship_signal, discovery_signal,
and novelty score against the wiki/rosters/sources as they exist at run time.
That is why scores are recomputed on every excavation and never trusted
beyond the run that computed them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lifehug_core import read_json, slugify

SCHEMA_VERSION = 1

AXES = (
    "date_anchor",
    "relationship_signal",
    "discovery_signal",
    "narrative_density",
    "novelty",
    "reciprocity",
)

# Committed starting weights — the owner calibrates these once against a
# shadow run (connector-calibrate), and the calibrated values are versioned
# in state/connectors/weights.json. The defaults here are the fresh-install
# config block; the state file overrides them key-by-key.
DEFAULT_WEIGHTS = {
    "date_anchor": 0.20,
    "relationship_signal": 0.25,
    "discovery_signal": 0.15,
    "narrative_density": 0.15,
    "novelty": 0.10,
    "reciprocity": 0.15,
}

# Band boundaries on the weighted total: <noise is ledger-only; noise–evidence
# yields metadata (dates/entities/discovery) but is never read; evidence–
# promote is the near-band (AI snippet scoring may refine later); >=promote
# auto-promotes to an immutable source. date_evidence is date_anchor's own
# lower bar for metadata harvesting — a utility bill never promotes but
# always yields its date+address.
DEFAULT_THRESHOLDS = {
    "noise": 0.15,
    "evidence": 0.45,
    "promote": 0.60,
    "date_evidence": 0.40,
}

BANDS = ("noise", "evidence", "near_band", "promote")

# Institutional/service senders whose mail carries authoritative dates and
# places (registrar@asu.edu, airlines, banks, landlords, utilities).
INSTITUTIONAL_DOMAIN_KEYWORDS = (
    "edu", "registrar", "university", "college", "mit.", "asu.",
    "bank", "chase", "amex", "wellsfargo", "citi", "paypal", "venmo",
    "airline", "airlines", "united", "delta", "southwest", "jetblue", "alaskaair", "aa.com",
    "utility", "utilities", "electric", "power", "water",
    "insurance", "health", "hospital", "clinic", "pharmacy",
    "gov", "irs", "usps", "ups", "fedex", "dhl",
    "landlord", "leasing", "apartments", "mortgage", "realty",
    "payroll", "benefits",
)

# Subjects that mark a dated record rather than a conversation.
DATE_SUBJECT_KEYWORDS = (
    "confirmation", "confirm", "receipt", "statement", "invoice",
    "itinerary", "reservation", "booking", "appointment",
    "enrollment", "enrolled", "registration", "transcript", "diploma",
    "acceptance", "admission", "admitted",
    "lease", "renewal", "payment", "bill",
    "ticket", "boarding", "schedule",
)

_NOREPLY_LOCALS = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon")

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "your", "you",
    "are", "was", "were", "have", "has", "re", "fw", "fwd",
    "com", "www", "mail", "email",
}


def is_noreply(address: str) -> bool:
    local = str(address or "").split("@", 1)[0].lower()
    return any(local.startswith(marker) for marker in _NOREPLY_LOCALS)


def text_tokens(text: str) -> set[str]:
    """Significant lowercase tokens from free text (names, subjects, slugs)."""
    if not str(text or "").strip():
        return set()
    return {
        token
        for token in _TOKEN_RE.findall(slugify(text).replace("-", " "))
        if len(token) >= 2 and token not in _STOPWORDS
    }


def address_tokens(from_name: str, from_email: str) -> set[str]:
    """Matchable tokens for a correspondent: display-name words plus the
    email local part's words ('Joe Smith <joe.smith@x>' → {joe, smith})."""
    local = str(from_email or "").split("@", 1)[0]
    return text_tokens(f"{from_name or ''} {local}")


def subject_tokens(subject: str) -> set[str]:
    """Longer, content-bearing subject tokens (skips Re:/Fwd: and stopwords)."""
    return {token for token in text_tokens(subject) if len(token) >= 4}


def tokens_known(tokens: set[str], known_token_sets: list[set[str]]) -> bool:
    """A correspondent is known when some roster/wiki token set is wholly
    contained in their address tokens ('Betty Jo' matches alias {betty, jo})."""
    return bool(tokens) and any(known and known <= tokens for known in known_token_sets)


@dataclass
class ScoringContext:
    """Everything a scoring run needs, built fresh from the CURRENT repo on
    every excavation. Never persisted — the next run rebuilds it against
    whatever the wiki/rosters/sources look like that day."""

    owner_email: str = ""
    known_person_token_sets: list[set[str]] = field(default_factory=list)
    known_any_token_sets: list[set[str]] = field(default_factory=list)
    covered_tokens: set[str] = field(default_factory=set)
    correspondent_stats: dict[str, dict] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))


def load_scoring_config(path: Path | None = None) -> dict:
    """Committed defaults, overridden key-by-key by the owner's calibrated
    state/connectors/weights.json when present."""
    config = {
        "version": SCHEMA_VERSION,
        "weights": dict(DEFAULT_WEIGHTS),
        "thresholds": dict(DEFAULT_THRESHOLDS),
    }
    data = read_json(path, default=None) if path else None
    if isinstance(data, dict):
        for key, value in (data.get("weights") or {}).items():
            if key in AXES:
                config["weights"][key] = float(value)
        for key, value in (data.get("thresholds") or {}).items():
            if key in DEFAULT_THRESHOLDS:
                config["thresholds"][key] = float(value)
    return config


def assign_band(total: float, thresholds: dict[str, float]) -> str:
    if total < thresholds["noise"]:
        return "noise"
    if total < thresholds["evidence"]:
        return "evidence"
    if total < thresholds["promote"]:
        return "near_band"
    return "promote"


def group_threads(entries: list[dict]) -> dict[str, list[dict]]:
    threads: dict[str, list[dict]] = {}
    for entry in entries:
        key = str(entry.get("thread_id") or entry.get("message_id") or "")
        if key:
            threads.setdefault(key, []).append(entry)
    return threads


def correspondent_stats(entries: list[dict], owner_email: str = "") -> dict[str, dict]:
    """Ledger-global per-correspondent stats: message volume, span, and
    whether the owner ever wrote back. Feeds discovery_signal and the
    discovery miner — both need the whole ledger, not one thread."""
    threads = group_threads(entries)
    stats: dict[str, dict] = {}
    for thread_id, thread_entries in threads.items():
        owner_count = sum(
            1 for e in thread_entries
            if e.get("sent_by_owner") or (owner_email and e.get("from_email") == owner_email)
        )
        seen_in_thread: set[str] = set()
        for entry in thread_entries:
            email = str(entry.get("from_email") or "").lower()
            if not email or entry.get("sent_by_owner") or (owner_email and email == owner_email):
                continue
            slot = stats.setdefault(email, {
                "name": str(entry.get("from_name") or ""),
                "messages": 0,
                "first": None,
                "last": None,
                "owner_replies": 0,
                "thread_count": 0,
            })
            if entry.get("from_name"):
                slot["name"] = str(entry["from_name"])
            slot["messages"] += 1
            timestamp = int(entry.get("timestamp") or 0)
            slot["first"] = timestamp if slot["first"] is None else min(slot["first"], timestamp)
            slot["last"] = timestamp if slot["last"] is None else max(slot["last"], timestamp)
            if email not in seen_in_thread:
                seen_in_thread.add(email)
                slot["owner_replies"] += owner_count
                slot["thread_count"] += 1
    for slot in stats.values():
        first = slot.pop("first")
        last = slot.pop("last")
        if first is None or last is None:
            slot["span_days"] = 0
            slot["first_date"] = ""
            slot["last_date"] = ""
        else:
            slot["span_days"] = max(0, round((last - first) / 86400))
            from datetime import datetime, timezone
            slot["first_date"] = datetime.fromtimestamp(first, tz=timezone.utc).date().isoformat()
            slot["last_date"] = datetime.fromtimestamp(last, tz=timezone.utc).date().isoformat()
    return stats


def build_context(
    repo_dir: Path,
    entries: list[dict],
    config: dict,
    owner_email: str = "",
) -> ScoringContext:
    """Build the scoring context from the repo AS IT EXISTS NOW: entity
    rosters, wiki page slugs, source coverage, and ledger-global
    correspondent stats."""
    repo_dir = Path(repo_dir)
    known_person_token_sets: list[set[str]] = []
    known_any_token_sets: list[set[str]] = []
    covered_tokens: set[str] = set()

    rosters_dir = repo_dir / "state" / "entity_rosters"
    if rosters_dir.exists():
        for roster_file in sorted(rosters_dir.glob("*.json")):
            data = read_json(roster_file, default=None) or {}
            token_sets: list[set[str]] = []
            for entity in data.get("entities") or []:
                names = [entity.get("name", ""), entity.get("slug", ""), *(entity.get("aliases") or [])]
                for raw in names:
                    tokens = text_tokens(str(raw or ""))
                    if tokens:
                        token_sets.append(tokens)
            known_any_token_sets.extend(token_sets)
            if roster_file.stem == "person":
                known_person_token_sets.extend(token_sets)

    wiki_dir = repo_dir / "wiki"
    if wiki_dir.exists():
        for page in sorted(wiki_dir.rglob("*.md")):
            if page.name == ".gitkeep":
                continue
            tokens = text_tokens(page.stem)
            covered_tokens |= tokens
            if tokens:
                known_any_token_sets.append(tokens)
                if page.parent.name == "people":
                    known_person_token_sets.append(tokens)

    sources_dir = repo_dir / "sources"
    if sources_dir.exists():
        for path in sorted(sources_dir.rglob("*.md")):
            if path.name == ".gitkeep":
                continue
            stem = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", path.stem)
            covered_tokens |= text_tokens(stem)

    return ScoringContext(
        owner_email=owner_email,
        known_person_token_sets=known_person_token_sets,
        known_any_token_sets=known_any_token_sets,
        covered_tokens=covered_tokens,
        correspondent_stats=correspondent_stats(entries, owner_email),
        weights=config["weights"],
        thresholds=config["thresholds"],
    )


# ---------------------------------------------------------------------------
# The six axes — each returns (score 0–1, short human reason for reports)
# ---------------------------------------------------------------------------

def date_anchor_score(entries: list[dict]) -> tuple[float, str]:
    """Institutional/service sender + dated-record subject. The utility-bill
    rule: content is noise, but date+address is proof. Also used standalone
    for date-evidence harvesting (message-level)."""
    best = 0.0
    best_reason = "no institutional sender signals"
    for entry in entries:
        domain = str(entry.get("from_email") or "").split("@")[-1].lower()
        subject = str(entry.get("subject") or "").lower()
        score = 0.0
        bits: list[str] = []
        if any(keyword in domain for keyword in INSTITUTIONAL_DOMAIN_KEYWORDS):
            score += 0.5
            bits.append(f"institutional sender {domain}")
        if any(keyword in subject for keyword in DATE_SUBJECT_KEYWORDS):
            score += 0.4
            bits.append("dated-record subject")
        if entry.get("noreply"):
            score += 0.2
            bits.append("automated sender")
        if score > best:
            best = min(1.0, score)
            best_reason = "; ".join(bits)
    return best, best_reason


def _relationship(others: dict[str, dict], context: ScoringContext) -> tuple[float, str]:
    """Share of correspondents matching the CURRENT person roster or wiki
    people pages. Time-varying: a roster gain re-scores old mail upward."""
    if not others:
        return 0.0, "no other correspondents"
    known = [
        email for email, info in others.items()
        if tokens_known(info["tokens"], context.known_person_token_sets)
    ]
    if not known:
        return 0.0, "no correspondent in the current person roster/wiki"
    return len(known) / len(others), f"{len(known)}/{len(others)} correspondents known ({', '.join(sorted(known))})"


def _discovery(others: dict[str, dict], context: ScoringContext) -> tuple[float, str]:
    """Significant correspondent ABSENT from every roster and the wiki.
    Time-varying: once they get a page, this axis stops firing."""
    unknown = {
        email: info for email, info in others.items()
        if not tokens_known(info["tokens"], context.known_any_token_sets)
    }
    if not unknown:
        return 0.0, "all correspondents already known"
    primary, _info = max(unknown.items(), key=lambda item: item[1]["count"])
    stats = context.correspondent_stats.get(primary, {})
    volume = int(stats.get("messages") or unknown[primary]["count"])
    span_days = int(stats.get("span_days") or 0)
    reciprocal = int(stats.get("owner_replies") or 0) > 0
    score = (
        min(1.0, volume / 50) * 0.5
        + min(1.0, span_days / 1095) * 0.3
        + (0.2 if reciprocal else 0.0)
    )
    return min(1.0, score), f"unknown correspondent {primary}: {volume} messages over {span_days}d"


def _narrative_density(
    entries: list[dict],
    others: dict[str, dict],
    automated_count: int,
    owner_count: int,
    other_count: int,
    span_days: int,
) -> tuple[float, str]:
    """Personal exchange vs automated mail. List-Id / unsubscribe / noreply
    blasts score ~0; long reciprocal one-on-one threads score high."""
    total = len(entries)
    if total and automated_count > total / 2:
        return 0.05, "mostly automated mail (list-id/unsubscribe/noreply)"
    score = 0.5 * min(1.0, total / 8)
    bits = [f"{total} messages"]
    if owner_count and other_count:
        score += 0.2
        bits.append("two-way exchange")
    if len(others) == 1 and owner_count:
        score += 0.15
        bits.append("one-on-one thread")
    span_score = 0.15 * min(1.0, span_days / 30)
    score += span_score
    if span_score:
        bits.append(f"spans {span_days}d")
    return min(1.0, score), "; ".join(bits)


def _novelty(others: dict[str, dict], entries: list[dict], context: ScoringContext) -> tuple[float, str]:
    """Entity/topic coverage not already in wiki pages or source files.
    Prevents re-deriving what the Loop already knows."""
    tokens: set[str] = set()
    for info in others.values():
        tokens |= info["tokens"]
    for entry in entries:
        tokens |= subject_tokens(str(entry.get("subject") or ""))
    if not tokens:
        return 0.5, "no matchable tokens"
    hits = {token for token in tokens if token in context.covered_tokens}
    score = 1.0 - len(hits) / len(tokens)
    if hits:
        return score, f"already covered: {', '.join(sorted(hits))}"
    return score, "nothing covered yet"


def _reciprocity(owner_count: int, other_count: int, span_days: int) -> tuple[float, str]:
    """Two-way exchange over time vs one-way blasts — separates relationships
    from subscriptions."""
    if not owner_count or not other_count:
        return 0.05, "one-way mail"
    total = owner_count + other_count
    balance = min(owner_count, other_count) / max(owner_count, other_count)
    score = (
        0.5 * balance
        + 0.3 * min(1.0, span_days / 180)
        + 0.2 * min(1.0, total / 10)
    )
    return min(1.0, score), f"{owner_count} sent / {other_count} received over {span_days}d"


def score_thread(entries: list[dict], context: ScoringContext) -> dict:
    """Score one thread (its ledger entries) on all six axes plus the
    weighted total and band. Deterministic: same ledger + same repo state →
    same scores, every run."""
    timestamps = [int(e.get("timestamp") or 0) for e in entries if e.get("timestamp")]
    span_days = max(0, round((max(timestamps) - min(timestamps)) / 86400)) if timestamps else 0
    others: dict[str, dict] = {}
    owner_count = 0
    automated_count = 0
    for entry in entries:
        email = str(entry.get("from_email") or "").lower()
        if entry.get("sent_by_owner") or (context.owner_email and email == context.owner_email):
            owner_count += 1
        elif email:
            slot = others.setdefault(email, {
                "count": 0,
                "tokens": address_tokens(str(entry.get("from_name") or ""), email),
            })
            slot["count"] += 1
        if entry.get("list_id") or entry.get("has_unsubscribe") or entry.get("noreply"):
            automated_count += 1
    other_count = sum(info["count"] for info in others.values())

    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    scores["date_anchor"], reasons["date_anchor"] = date_anchor_score(entries)
    scores["relationship_signal"], reasons["relationship_signal"] = _relationship(others, context)
    scores["discovery_signal"], reasons["discovery_signal"] = _discovery(others, context)
    scores["narrative_density"], reasons["narrative_density"] = _narrative_density(
        entries, others, automated_count, owner_count, other_count, span_days)
    scores["novelty"], reasons["novelty"] = _novelty(others, entries, context)
    scores["reciprocity"], reasons["reciprocity"] = _reciprocity(owner_count, other_count, span_days)

    total = round(sum(scores[axis] * context.weights.get(axis, 0.0) for axis in AXES), 4)
    return {
        "scores": scores,
        "total": total,
        "band": assign_band(total, context.thresholds),
        "reasons": reasons,
    }
