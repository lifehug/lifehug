#!/usr/bin/env python3
"""The resolver: answer "when did this happen?" from everything the vault holds.

The extraction layer turns a story into events and free-text handles ("the
founding of the company", "18"). Until now the only path from a handle to a
date was a mechanical join — an exact label, an exact quote, a candidate list
built by keyword rules — and every failed join became a question for the
owner. The owner's own reading of that page: *if you can answer this from the
repo, so should the system, and once answered it must never be asked again.*

So this module does what a careful assistant does with the same question.
The intended loop, in the owner's words, is *a model resolving and calculating
placement against a spine*: the spine (``spine``) is the lifetime frame —
birth and the age table it implies, stays, tenures, dated points, people —
generic at first and made specific by the landmarks and keystone answers the
person adds. Everything below reads the vault against that spine
(ADR 0037):

1. **Index everything.** Every source, answer, landmark record, placed fact and
   prior resolution goes into one full-text index (SQLite FTS5, rebuilt per
   run — the vault is a few megabytes).
2. **Retrieve, then ask the model to ANSWER, with citations.** For one story at
   a time, the model sees the story, the vault's spine (birth, residences,
   tenures, dated landmarks), the passages the index returns for that story's
   events, and the events that still have no date. It answers each with a date
   or range, a basis (``stated`` / ``derived`` / ``inferred``), a confidence,
   citations, and — when the vault genuinely cannot tell — the ONE question
   that would settle it and which other events that answer would settle too.
3. **Verify only what a machine can verify.** Every cited quote must occur in
   the cited passage; every date must parse; ranges must be ordered; a
   ``derived`` answer must cite the spine fact it was derived from. An answer
   that fails verification is kept in the ledger as unverified and files
   nothing.
4. **File the answer as a claim** on the event's existing node — a ``date``
   claim under extractor ``resolver/rule:3`` whose evidence is the citations,
   declared on the classifier's own telling —
   and retire the raw handle claim it replaces with a supersession correction.
   The fold, the projection and the page then treat it like any other claim:
   durable, dated, correctable, never asked again.
5. **Remember.** ``state/resolver/resolutions.json`` records every event's
   outcome (resolved / unverified / unknown, with the proposed question), so a
   later run skips what is settled and the question list is deduplicated by
   the fact it asks for.

Owner statements outrank inference, the latest correction wins, and nothing
here edits a source. Private vault data never enters this module's tests.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as store  # noqa: E402
from lifehug_core import split_frontmatter  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402
from vault_paths import atomic_write_vault_text  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-5"
EXTRACTOR_VERSION = "resolver/rule:3"
PRIOR_EXTRACTOR_VERSIONS = ("resolver/rule:1", "resolver/rule:2")
SOURCE_ID_PREFIX = "resolver:"
SUPERSEDE_SCOPE = "resolver_resolution"

#: v333, defect A. A resolver reading is ANOTHER READING OF ONE TELLING and
#: never an event of its own — and until this release that was a best effort:
#: :func:`file_resolution` declared the telling it re-read only when
#: :func:`targets` had found one, and where it had not, the claim carried no
#: declaration at all. `event_identity.telling_ref_for_claim` then fell back to
#: the claim's own `source_ref.source_id`, the reading became a telling nobody
#: else shares, the fold gave it a node of its own — and the node it answered
#: kept its "when did this happen?" card while the answer sat on a duplicate
#: beside it. On the owner's vault that is `node:e6f9cc1e…` "Harvey's birth as
#: turning point" placed 11 October 2021 next to `node:1f65aa7a…`, the same
#: label, unplaced, still asking.
#:
#: So the declaration is now unconditional. When the target names the telling
#: this reading re-reads, that is the declaration. When it does not,
#: :func:`reading_telling_ref` mints one that names the NODE the reading is
#: about — which `episode_binder.reads_node` recognizes as a derived reading, so
#: the binder's `R2a` rung puts it back on that node's episode even for a
#: receipt filed before this release.
READING_IS_NOT_AN_EVENT = (
    "a resolver reading is another reading of one telling; it is declared under "
    "that telling, or under a ref naming the node it read, and never left to "
    "fall back to its own source id"
)

#: A MOMENT THAT NEVER HAPPENED IS NOT A DATING PROBLEM (ADR 0037's amendment,
#: lifehug#365 item 5). The classifier reads a story and files what reads like
#: an occurrence; some of what it reads is not one. Four shapes, and the set is
#: CLOSED because a free-text verdict is a verdict nobody can verify:
#:
#: * ``future`` — an anticipated or hypothetical milestone ("when the shop
#:   finally opens"). It has not happened, so there is no date to find.
#: * ``meta`` — a conversation about the data itself: a correction, a
#:   clarification, "no, that was the other James".
#: * ``fact_statement`` — a bare fact rather than something that happened: a
#:   person's full name, somebody else's birthday stated as a fact.
#: * ``duplicate`` — a restatement of a moment already dated elsewhere; the
#:   reason must cite that node's id.
NOT_AN_EVENT_KINDS = ("future", "meta", "fact_statement", "duplicate")

#: The ledger status and the correction scope a verdict is filed under. The
#: scope is its own — never `SUPERSEDE_SCOPE` — so "this was never an event"
#: is legible on the vault's own record as a different act from "this reading
#: was replaced by a better one".
NOT_AN_EVENT_STATUS = "not_an_event"
NOT_AN_EVENT_SCOPE = "resolver_not_an_event"

#: What a verdict RETRACTS: the claims that assert this moment happened and
#: when. ``identity`` is deliberately absent — an identity claim says WHO, and
#: a landmark entry's identity claim is the person's own ladder answer, which
#: the resolver has no business withdrawing.
NOT_AN_EVENT_CLAIM_TYPES = ("occurrence", "date", "range", "age", "duration",
                            "relative_order")
LEDGER_RELATIVE = Path("state") / "resolver" / "resolutions.json"
RESPONSES_RELATIVE = Path("state") / "resolver" / "responses"
MAX_SOURCE_CHARS = 7000
MAX_PASSAGE_CHARS = 700
RETRIEVE_PER_EVENT = 6
RETRIEVE_CAP = 18
#: v325. How many settled-unknown moments ONE newly filed source may re-open in
#: a single plan. Each is a line in a prompt that is being bought anyway, never
#: a call of its own; the cap keeps a long story from re-asking the whole ledger.
MAX_REVISITS = 8
#: v325. How many paragraphs of a triggering message ride into a re-opened
#: moment's prompt whole (a conversation turn is short; a pasted record is not).
INCLUDE_PASSAGE_CAP = 12
#: v325. A resolver-dated moment whose range spans at least this many calendar
#: years is "wide", and a new story that bears on it may re-ask it to sharpen
#: the date. The person's own stated dates are never re-asked: only readings
#: the resolver itself filed are the resolver's to refine.
REFINE_MIN_YEARS = 1
#: v325. What an estimate may rest on. "other" is allowed and named so a reader
#: can tell a basis the model could not classify from a missing one.
ESTIMATE_BASIS_KINDS = ("residence", "tenure", "life_stage", "related_moment", "story", "spine", "other")
MAX_ESTIMATE_BASIS = 4
MAX_ESTIMATE_TEXT = 200
#: v325. The conversation a promoted message came from names the work item the
#: person was answering: ``conversation:cand:work_item:work:<hex>``.
SESSION_WORK_ITEM_MARKER = "work_item:"
BASES = ("stated", "derived", "inferred")
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOP = frozenset("""the and for with that this from was were are you your our his her they them
their when what where which who how did does have has had not but into about after before
during while then than also just very like more most some any all one two his she him
narrator self author owner story event events told said says day days year years time
of in on at to is it my we he up so no do be by as or an if me us am go got get""".split())


# --------------------------------------------------------------------------
# Vault reading
# --------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def story_documents(root: Path) -> list[dict]:
    """Every narrative file as passages: ``{doc_id, kind, path, title, text}``."""
    docs: list[dict] = []
    for folder, kind in (("answers", "answer"), ("sources", "source")):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith("sources/corrections/temporal-"):
                continue
            metadata, body = split_frontmatter(_read(path))
            title = str(metadata.get("title") or metadata.get("question_text") or path.stem)
            body = body.strip()
            if not body:
                continue
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            for index, paragraph in enumerate(paragraphs):
                docs.append({
                    "doc_id": f"{rel}#p{index}", "kind": kind, "path": rel,
                    "title": title, "text": paragraph[:MAX_PASSAGE_CHARS * 3],
                })
    return docs


def fact_documents(root: Path, projection: dict) -> list[dict]:
    """Placed nodes and landmark records, each as one fact passage."""
    docs: list[dict] = []
    for node in projection.get("nodes") or ():
        best = node.get("best_temporal_value") or {}
        if not node.get("usable_placement") or not best.get("best"):
            continue
        label = collapsed_text(node.get("label"))
        text = (f"{label} — {chrono.display_date(best, with_basis=False)} "
                f"({best.get('basis')}, {best.get('confidence')}); kind {node.get('event_kind')}; "
                f"subject {', '.join(node.get('subject_refs') or [])}")
        docs.append({"doc_id": f"fact:{node['node_id']}", "kind": "fact",
                     "path": "", "title": label, "text": text,
                     "earliest": best.get("earliest"), "latest": best.get("latest")})
    landmarks = _json(root / "state" / "landmarks.json", {}) or {}
    for domain, rows in (landmarks.get("domains") or {}).items():
        for index, entry in enumerate(rows or ()):
            if not isinstance(entry, dict):
                continue
            span = entry.get("span") or {}
            start = (span.get("start") or {}).get("best") or (entry.get("date") or {}).get("best") or "?"
            end = (span.get("end") or {}).get("best") or ("present" if entry.get("ongoing") else "?")
            bits = [f"{domain}: {entry.get('label') or entry.get('name') or ''}", f"{start} to {end}"]
            for key in ("city", "address", "nickname", "what", "where", "grades", "relation", "events"):
                if entry.get(key):
                    bits.append(f"{key} {entry[key]}")
            docs.append({"doc_id": f"landmark:{domain}:{index}", "kind": "landmark", "path": "",
                         "title": str(entry.get("label") or ""), "text": "; ".join(str(b) for b in bits)})
    return docs


def spine(root: Path, projection: dict) -> dict:
    """The spine: the dated facts every "when?" is read against.

    Birth and the age table it implies, stays, tenures and schooling as
    intervals, dated points, people. Generic at first (a birthday alone fills
    the age table); the person's landmarks and keystone answers make it theirs.
    """
    import temporal_publication as pub  # noqa: PLC0415
    from temporal_timeline import is_owner_reference_only  # noqa: PLC0415

    # v328: the ONE definition of the owner's spellings (`temporal_publication.
    # owner_names_from_profile`, read from this vault) — plus each one's first
    # word, which only the resolver wants (`owner_name_variants`).
    profile = pub.owner_profile(root)
    whole = pub.owner_names_from_profile(profile)
    owner_names = {_norm(n) for n in pub.owner_name_variants(whole)}

    def _is_owner(refs) -> bool:
        refs = [collapsed_text(r) for r in (refs or ()) if collapsed_text(r)]
        return bool(refs) and all(
            is_owner_reference_only(r) or r == "self" or _norm(r) in owner_names for r in refs
        )

    birth = None
    tenures, stays, points, people = [], [], [], []
    for node in projection.get("nodes") or ():
        best = node.get("best_temporal_value") or {}
        if not node.get("usable_placement") or not best.get("best"):
            continue
        scope = node.get("occurrence_subject_scope")
        kind = collapsed_text(node.get("event_kind"))
        label = collapsed_text(node.get("label"))
        shown = chrono.display_date(best, with_basis=False)
        if kind == "birth" and _is_owner(node.get("subject_refs")) and best.get("granularity") == "day":
            birth = birth or best.get("best")
        elif kind in ("birth", "death", "child_born"):
            people.append(f"- {label}: {shown} [{node['node_id']}]")
        if node.get("node_kind") == "episode" and scope == "owner":
            (stays if kind == "residence" else tenures).append(f"- {label}: {shown} [{node['node_id']}]")
        elif scope == "owner" and kind in ("married", "graduation", "move", "founded", "death", "child_born"):
            points.append(f"- {label}: {shown} [{node['node_id']}]")
    return {
        "owner_name": str(profile.get("full_name") or profile.get("name") or "the owner"),
        # v325: every spelling the profile gives the owner — `name` AND `full_name`
        # and each one's first word ("Dave", "David") — so the refusal that
        # protects other people's ages never fires on the owner's own nickname.
        # v328: derived from the same definition the fold uses; the first words
        # are the resolver's own addition and never reach the fold.
        "owner_names": sorted(n for n in owner_names if n),
        "birth": birth,
        "stays": stays[:60],
        "tenures": sorted(set(tenures))[:60],
        "points": sorted(set(points))[:40],
        "people": sorted(set(people))[:60],
        "ages": age_table(birth),
    }


def age_table(birth: object, *, upto: int = 50) -> list[str]:
    """``"18 -> 1999-07-11 to 2000-07-10"`` lines, so nobody does birthday arithmetic."""
    text = collapsed_text(birth)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return []
    year, month, day = (int(g) for g in match.groups())
    import datetime as dt  # noqa: PLC0415

    def birthday(in_year: int) -> dt.date:
        # A February 29 birthday falls on February 28 in a common year.
        try:
            return dt.date(in_year, month, day)
        except ValueError:
            return dt.date(in_year, month, 28)

    lines = []
    for age in range(0, upto + 1):
        start = birthday(year + age)
        end = birthday(year + age + 1) - dt.timedelta(days=1)
        lines.append(f"{age} -> {start.isoformat()} to {end.isoformat()}")
    return lines


_AGE_HANDLE_RE = re.compile(r"^(?:at|age|aged|when i was|when he was|turned|turning)?\s*(\d{1,2})(?:\s*years?\s*old)?$", re.IGNORECASE)


def age_from_handle(text: object) -> int | None:
    """A bare age the extractor wrote where an anchor should be, or ``None``."""
    match = _AGE_HANDLE_RE.match(collapsed_text(text))
    if not match:
        return None
    age = int(match.group(1))
    return age if 0 <= age <= 100 else None


def age_range(birth: object, age: int, relation: str = "within") -> dict | None:
    """The year of life the owner was ``age`` as a date record; ``after`` opens
    the end and ``before`` opens the start, exactly as the handle said."""
    for line in age_table(birth, upto=max(age, 0)):
        if line.startswith(f"{age} -> "):
            start, end = line.split(" -> ")[1].split(" to ")
            text = {"after": f"{start}/..", "before": f"../{end}"}.get(collapsed_text(relation), f"{start}/{end}")
            record = chrono.parse_stated_date(text)
            return record.to_dict() if record else None
    return None


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------

class Index:
    """In-memory FTS5 over every passage; rebuilt per run."""

    def __init__(self, docs: list[dict]) -> None:
        self.docs = {doc["doc_id"]: doc for doc in docs}
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE passages USING fts5(doc_id UNINDEXED, path UNINDEXED, title, body)")
        self.db.executemany(
            "INSERT INTO passages(doc_id, path, title, body) VALUES (?, ?, ?, ?)",
            [(d["doc_id"], d.get("path") or "", d["title"], d["text"]) for d in docs],
        )
        self.db.commit()

    @staticmethod
    def terms(text: object) -> list[str]:
        seen: list[str] = []
        for token in _TOKEN_RE.findall(_norm(text)):
            if token not in _STOP and token not in seen:
                seen.append(token)
        return seen

    def search(self, text: object, *, k: int = RETRIEVE_PER_EVENT, exclude_path: str = "",
               only_path: str = "") -> list[dict]:
        """The best ``k`` passages for ``text``; ``only_path`` keeps one source's own
        (v325: the passages of the story that just re-opened a question)."""
        terms = self.terms(text)
        if not terms:
            return []
        query = " OR ".join(f'"{term}"' for term in terms[:24])
        try:
            if only_path:
                # v325: filtered IN the query — after the LIMIT, a short
                # message's paragraphs lose to the whole vault's on rank and
                # the one that carries the date is exactly the one cut.
                rows = self.db.execute(
                    "SELECT doc_id, bm25(passages) AS score FROM passages WHERE passages MATCH ? "
                    "AND path = ? ORDER BY score LIMIT ?", (query, only_path, k * 3),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT doc_id, bm25(passages) AS score FROM passages WHERE passages MATCH ? "
                    "ORDER BY score LIMIT ?", (query, k * 3),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        found: list[dict] = []
        for doc_id, _score in rows:
            doc = self.docs.get(doc_id)
            if doc is None or (exclude_path and doc.get("path") == exclude_path):
                continue
            if only_path and doc.get("path") != only_path:
                continue
            found.append(doc)
            if len(found) >= k:
                break
        return found


# --------------------------------------------------------------------------
# Targets: unplaced owner events, joined back to their classification events
# --------------------------------------------------------------------------

def _classification_events(root: Path) -> dict[str, tuple[str, dict]]:
    """``"stem#event_key" -> (source_path, event)`` over current classifications."""
    import timeline_evidence as te  # noqa: PLC0415

    found: dict[str, tuple[str, dict]] = {}
    for path in sorted((root / "state" / "classifications").glob("*.json")):
        data = _json(path, None)
        if not isinstance(data, dict):
            continue
        source_path = collapsed_text(data.get("source_path"))
        for event in data.get("events") or ():
            if isinstance(event, dict):
                found[f"{path.stem}#{te.event_key(event)}"] = (source_path, event)
    return found


def targets(root: Path, projection: dict, index: dict, *, scopes=("owner",),
            include_placed: frozenset | set = frozenset()) -> dict[str, list[dict]]:
    """``source_path -> [target]`` for every unplaced node ON THE OWNER'S AXIS.

    Two ways to be on it and the second one is why this is not a scope test
    (`timeline-rules:9`): the owner's own occurrences, and an occurrence that
    happened to somebody ELSE which the owner lived through — a grandparent's
    death told as "when I was in 9th grade" is `other_person` /
    `lived_effect`, and it is dated from the owner's own spine because the
    owner's own telling is what dates it. `temporal_projection.AXIS_RELATIONS`
    is the same tuple the fold and the page read, so "is this on the
    timeline?" has one answer everywhere.

    A `contextual_only` node — a relative's own milestone, family history from
    before the owner's life — is never planned. Nothing in this vault dates
    it, and the spine here belongs to one person.
    """
    import classifier_claims as ccl  # noqa: PLC0415
    import event_identity as ei  # noqa: PLC0415
    import temporal_projection as tp  # noqa: PLC0415

    claims = {row.get("claim_id"): row for row in index.get("claims") or ()}
    events = _classification_events(root)
    revisions: dict[str, str | None] = {}
    # v333 (:data:`RESTATEMENT_IS_NOT_A_QUESTION`). Worked out ONCE, before the
    # sweep, so asking is refused rather than asked and then withdrawn.
    restated = restated_placed_nodes(projection)
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for node in projection.get("nodes") or ():
        if node.get("node_kind") == "period":
            continue
        if node.get("usable_placement") and node.get("node_id") not in include_placed:
            continue
        if node.get("node_id") in restated and node.get("node_id") not in include_placed:
            continue
        if node.get("occurrence_subject_scope") not in scopes and \
                collapsed_text(node.get("owner_timeline_relation")) not in tp.AXIS_RELATIONS:
            continue
        if node.get("node_kind") == "episode" and collapsed_text(node.get("event_kind")) == "residence":
            # A residence is dated by the ladder in the person's own words or is
            # a duplicate of a stay that already is; a span guessed for it draws
            # the person living in two places at once. Identity, not dating.
            continue
        handles: list[dict] = []
        story_path, event, subject, stem = "", None, "", ""
        telling_event_ref, telling_event_kind = "", ""
        landmark_path, landmark_entry_id = "", ""
        fallback_claim = None
        for claim_id in node.get("input_claim_refs") or ():
            claim = claims.get(claim_id) or {}
            ref = claim.get("source_ref") or {}
            source_id = collapsed_text(ref.get("source_id"))
            subject = subject or collapsed_text(claim.get("subject_mention"))
            if source_id.startswith("classification:"):
                key = source_id.split(":", 1)[1].split(":link")[0]
                if key in events and event is None:
                    story_path, event = events[key]
                    stem = key.split("#", 1)[0]
                    # The telling's OWN event: for a member folded into an
                    # episode the projection node is the episode, and a claim
                    # about the telling must name the telling's event, not the
                    # episode it was bound into.
                    telling_event_ref = collapsed_text(claim.get("event_ref"))
                    telling_event_kind = collapsed_text(claim.get("event_kind"))
                    subject = collapsed_text(claim.get("subject_mention")) or subject
            if source_id.startswith("landmark:") and not landmark_path:
                landmark_path = collapsed_text(ref.get("source_path"))
                landmark_entry_id = source_id.partition(":")[2]
            if fallback_claim is None and collapsed_text(ref.get("source_path")) \
                    and (root / collapsed_text(ref.get("source_path"))).is_file():
                fallback_claim = claim
            if claim.get("claim_type") == "relative_order":
                value = claim.get("temporal_value") or {}
                handles.append({"claim_id": claim_id, "relation": value.get("relation"),
                                "anchors": list(value.get("anchors") or [])})
        fallback_telling = ""
        if not story_path and fallback_claim is not None:
            # A node with no classifier event behind it (a landmark record, a
            # conversation message the listener heard) still has a source the
            # person wrote. That source is the story, and the claim's own
            # telling is what the resolver's reading is declared under.
            ref = fallback_claim.get("source_ref") or {}
            story_path = collapsed_text(ref.get("source_path"))
            label = collapsed_text(node.get("label"))
            event = {"title": label, "description": f"{label} ({collapsed_text(node.get('event_kind'))}); source {collapsed_text(ref.get('source_id'))}"}
            telling_event_ref = collapsed_text(fallback_claim.get("event_ref")) or node["node_id"]
            telling_event_kind = collapsed_text(fallback_claim.get("event_kind")) or collapsed_text(node.get("event_kind"))
            subject = collapsed_text(fallback_claim.get("subject_mention")) or subject
            try:
                receipt_rel = collapsed_text(fallback_claim.get("receipt_path"))
                receipt = _json(root / receipt_rel, None) if receipt_rel else None
                fallback_telling = ei.telling_ref_for_claim(fallback_claim, receipt=receipt)
            except Exception:  # noqa: BLE001 - an undeclarable telling files undeclared
                fallback_telling = ei.landmark_telling_ref(landmark_entry_id) if landmark_entry_id else ""
            # A conversation telling is ONE event inside ONE message; a bare
            # message id would span every event it holds, so it is not declared.
            if fallback_telling.startswith("conversation:") and "#" not in fallback_telling:
                fallback_telling = ""
        if not story_path:
            continue
        if story_path not in revisions:
            revisions[story_path] = ccl.document_revision(root, story_path)
        # The claims a `not_an_event` verdict would retract: this node's own
        # active occurrence, relation and date claims, in the fold's order.
        # Carried on the target because the target is what a verdict answers
        # about, and because `_targets_digest` reads node ids and handles
        # alone — so adding it churns no plan identity.
        node_claim_refs = [
            claim_id for claim_id in (node.get("input_claim_refs") or ())
            if collapsed_text((claims.get(claim_id) or {}).get("claim_type"))
            in NOT_AN_EVENT_CLAIM_TYPES
        ]
        by_source[story_path].append({
            "node_id": node["node_id"], "label": collapsed_text(node.get("label")),
            "node_claim_refs": node_claim_refs,
            "event_ref": telling_event_ref or node["node_id"],
            "event_kind": telling_event_kind or collapsed_text(node.get("event_kind")) or "moment",
            "subject": subject or "self", "event": event or {}, "handles": handles,
            "resolution_status": node.get("timeline_resolution_status"),
            # The resolver's claim is ANOTHER READING OF THE SAME TELLING, so it
            # is declared under the classifier's telling ref and follows that
            # telling's bindings instead of minting a second node.
            "telling_ref": (ei.classifier_telling_ref(stem, event) if (stem and event and not fallback_telling)
                            else fallback_telling),
            "document_revision": revisions[story_path],
        })
    return dict(by_source)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

PROMPT = """You are dating moments from one person's life story for a private timeline.
Everything you may rely on is in this message: the owner's spine of known facts, the
story the moments come from, and passages retrieved from the rest of the vault. The
owner has said: "I have given enough information to answer nearly all of these."
Read like a careful biographer: combine the story with the spine and the passages,
do arithmetic against the birth date when the story gives an age or a grade, use a
residence stay or a tenure as a range when the story places itself inside one, and
give a RANGE rather than nothing when the exact date is not stated. Never invent a
date the evidence does not support; when the vault truly cannot tell, say so and
propose the single question that would settle it.

## The owner
Name: {owner}. Born: {birth}.
The owner speaks in the first person; "narrator", "the author", "self" and the owner's
own name all mean the owner.

### Residence stays (owner's own words; each stay is a range)
{stays}

### Tenures: jobs, schools, missions (owner's own words or inherited from stays)
{tenures}

### Other dated landmarks
{points}

### Births and deaths of other people, as recorded (use for ages and "when X was born")
{people}

### The owner's age table (copy from here; never compute ages yourself)
{ages}

## The story ({source_path})
{story}

## Retrieved passages from the rest of the vault
Each passage has an id you must cite exactly.
{passages}

## Moments from this story that still have no date
{events}

## Open questions elsewhere in the vault this story may bear on
Moments from OTHER stories the vault could not date yet. They are asked again on their
own with this story among their passages; here they are so you can say when a moment
above IS one of them ("duplicate", cite the node_id) or NAMES one of them as its
unresolved handle ("handle_binds").
{open_questions}

## Answer
Return ONLY a JSON object: {{"answers": [ ... one per moment, in the order given ... ]}}
Each answer:
{{
  "node_id": "<copied verbatim from the list above, character for character>",
  "answer": {{"earliest": "YYYY or YYYY-MM or YYYY-MM-DD", "latest": "same shape, or null for ongoing"}} or null,
  "basis": "stated" | "derived" | "inferred",
  "confidence": 0.0-1.0,
  "citations": [{{"doc": "<passage id, or 'story' for the story above, or 'spine' for a spine fact>", "quote": "<exact words copied from that passage, story, or spine line>"}}],
  "fact_key": "<short snake_case name of the fact this date rests on, e.g. company_founding, mission_start, age_18>",
  "reason": "<one or two sentences>",
  "question": null or "<the one question to the owner that would settle this, only when answer is null>",
  "also_resolves": ["<other node_ids from this list the same answer settles>"],
  "estimate": {{"earliest": "YYYY or YYYY-MM", "latest": "YYYY or YYYY-MM",
               "basis": [{{"kind": "residence" | "tenure" | "life_stage" | "related_moment" | "story" | "spine" | "other", "text": "<one line: what this rests on>"}}],
               "confidence": 0.0-1.0}},
  "handle_binds": [{{"handle": "<the anchor words of one of this moment's unresolved handles, e.g. grandpa's death>", "node_id": "<the node_id — from this list, the open questions, or a fact passage — that those words name>"}}]
}}
The "estimate" is REQUIRED whenever "answer" is null and there is no "not_an_event": your
best reading of the stretch this moment falls in, from the shape of the owner's life as the
spine shows it — the residence or tenure the story sits in, the life stage, a related dated
moment. It is an estimate and is drawn as one, never as a placement; give the honest widest
stretch you actually believe, never a single year you do not. When a moment's unresolved
handle names something that IS in the passages or the open questions (a birth, a move, a
death listed as a fact), return it in "handle_binds" — that is how the handle stops being a
question — and still answer the moment itself. Omit "handle_binds" only when nothing here
names it.
The "question" asks for the LEAST fidelity that would settle the moment. Ask for a
year when a year settles it; name a finer grain — a month, a season, a day — only when
this same answer would also settle other moments you are listing in "also_resolves" or
in the open questions above, and say in the question itself which grain you need and
why it reaches further. A moment that stands alone gets the plain question and nothing
more: higher fidelity on a single anecdote is not worth asking for, and a question that
asks the owner to split hairs over one story he has already told is a question that
should not have been asked at all.
Some listed moments are not moments at all. When that is so, set "answer" to null and
add, instead of a question:
  "not_an_event": {{"kind": "future" | "meta" | "fact_statement" | "duplicate", "reason": "<one sentence>"}}
Use "future" for an anticipated or hypothetical milestone that has not happened yet,
"meta" for a conversation about the data itself (a correction or a clarification),
"fact_statement" for a bare statement of a fact (a name, somebody else's birthday)
rather than something that happened, and "duplicate" for a restatement of a moment
already dated elsewhere — cite that node_id in the reason. Use this only when you are
sure; a moment you simply cannot date takes a question, not a verdict.
Rules: "stated" means a passage or the story states the date; "derived" means arithmetic
from a stated fact (cite the fact); "inferred" means you reasoned from ranges (cite them).
An answer with no valid citation will be discarded, so cite the exact words. Prefer the
owner's explicit statements over anything inferred. Keep ranges honest: a moment "during
high school" is the high school tenure's range, not a single year.
"""


def _event_lines(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        event = row["event"]
        date = event.get("date") or {}
        handle = "; ".join(
            f"{h.get('relation')} '{', '.join(h.get('anchors') or [])}'" for h in row["handles"]
        )
        lines.append(
            f"- node_id {row['node_id']} | title: {event.get('title') or row['label']} | "
            f"description: {event.get('description') or ''} | when_hint: {event.get('when_hint') or ''} | "
            f"anchor: {event.get('anchor') or ''} | stated date field: {date.get('stated') or ''} | "
            f"age field: {date.get('age') or ''} | unresolved handle: {handle or 'none'} | subject: {row['subject']}"
        )
    return "\n".join(lines)


def _open_lines(rows: list[dict]) -> str:
    """v325. The settled-unknown moments a story may bear on, one line each."""
    lines = []
    for row in rows:
        handle = "; ".join(
            f"{h.get('relation')} '{', '.join(h.get('anchors') or [])}'" for h in row.get("handles") or ()
        )
        lines.append(
            f"- node_id {row['node_id']} | title: {row.get('label') or ''} | "
            f"open question: {row.get('question') or ''} | unresolved handle: {handle or 'none'} | "
            f"from: {row.get('source_path') or ''}"
        )
    return "\n".join(lines)


def build_prompt(*, source_path: str, story: str, rows: list[dict], sp: dict, passages: list[dict],
                 open_rows: list[dict] | tuple = ()) -> str:
    return PROMPT.format(
        owner=sp["owner_name"], birth=sp["birth"] or "unknown",
        stays="\n".join(sp["stays"]) or "- none recorded",
        tenures="\n".join(sp["tenures"]) or "- none recorded",
        points="\n".join(sp["points"]) or "- none recorded",
        people="\n".join(sp.get("people") or []) or "- none recorded",
        ages="\n".join(sp.get("ages") or []) or "- birth date unknown",
        source_path=source_path, story=story[:MAX_SOURCE_CHARS],
        passages="\n".join(f"[{d['doc_id']}] ({d['kind']}) {d['text'][:MAX_PASSAGE_CHARS]}" for d in passages) or "(none)",
        events=_event_lines(rows),
        open_questions=_open_lines(list(open_rows)) or "(none)",
    )


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _quote_in(quote: str, text: str) -> bool:
    """Exact words, tolerant only of whitespace, case and punctuation."""
    q, t = _norm(quote), _norm(text)
    if not q or len(q) < 3:
        return False
    if q in t:
        return True
    ql = _letters(q)
    return len(ql) >= 6 and ql in _letters(t)


def _record(answer: dict):
    earliest = collapsed_text(answer.get("earliest"))
    latest = answer.get("latest")
    latest = collapsed_text(latest) if latest is not None else None
    if not earliest:
        return None
    text = earliest if latest in (None, "", earliest) else f"{earliest}/{latest}"
    if latest is None and earliest:
        text = f"{earliest}/.." if answer.get("open") else earliest
    record = chrono.parse_stated_date(text)
    if record is None and latest is None:
        record = chrono.parse_stated_date(earliest)
    return record


#: The refusal `timeline-rules:9` added. The owner's age table answers "how
#: old was the OWNER in year X"; it says nothing whatever about how old
#: anybody else was, and the arithmetic that reads "mom got married young, at
#: 21" off the owner's birthday produces a date for the mother's wedding from
#: a fact about her son. Mechanical, like every other verification here.
SUBJECT_AGE_NOT_OWNER = "subject_age_not_owner"


def _subject_is_owner(subject: object, sp: dict) -> bool:
    """Is this target's subject the vault's owner, under any spelling?"""
    from temporal_timeline import is_owner_reference_only  # noqa: PLC0415

    text = collapsed_text(subject)
    if not text or text == "self" or is_owner_reference_only(text):
        return True
    owner = _norm(sp.get("owner_name"))
    names = {owner} | ({owner.split()[0]} if owner else set())
    names |= {_norm(n) for n in (sp.get("owner_names") or ()) if _norm(n)}
    names.discard("")
    return bool(names) and _norm(text) in names


def _is_age_of_subject(item: dict, target: object) -> bool:
    """Does this answer rest on HOW OLD THE SUBJECT WAS?

    Two mechanical signals, both of them the model's or the classifier's own
    words: a `fact_key` the model itself named `age_*`, and an age field the
    extractor wrote on the moment (including a bare age sitting where an
    anchor should be).
    """
    if collapsed_text(item.get("fact_key")).lower().startswith("age"):
        return True
    row = target if isinstance(target, dict) else {}
    date = (row.get("event") or {}).get("date") or {}
    if collapsed_text(date.get("age")):
        return True
    return any(
        age_from_handle(anchor) is not None
        for handle in row.get("handles") or ()
        for anchor in (handle.get("anchors") or ())
    )


def _cites_owner_age_table(citations, sp: dict) -> bool:
    """Does any verified citation quote the owner's birth or his age table?"""
    lines = [f"Born: {sp['birth']}"] if sp.get("birth") else []
    lines.extend(sp.get("ages") or ())
    if not lines:
        return False
    text = "\n".join(lines)
    return any(
        collapsed_text(row.get("doc")) == "spine" and _quote_in(str(row.get("quote") or ""), text)
        for row in citations
    )


def verify(item: dict, *, story: str, passages: dict[str, dict], sp: dict, story_path: str = "",
           target: object = None) -> tuple[dict | None, str]:
    """``(normalized answer, reason)``; the answer is ``None`` when it did not verify.

    ``target`` is the planned moment this answer is for. It is optional so the
    eval lane (which has no vault node) still calls this the same way, and
    when it IS given it carries the one thing the citations cannot say for
    themselves: whose occurrence this is. See :data:`SUBJECT_AGE_NOT_OWNER`.
    """
    answer = item.get("answer")
    if not isinstance(answer, dict):
        return None, "no_answer"
    basis = collapsed_text(item.get("basis"))
    if basis not in BASES:
        return None, "basis_invalid"
    record = _record(answer)
    if record is None:
        return None, "date_unparseable"
    if record.earliest and record.latest and record.earliest > record.latest:
        return None, "range_reversed"
    spine_text = "\n".join([f"Born: {sp['birth']}", *sp["stays"], *sp["tenures"], *sp["points"], *sp.get("people", []), *sp.get("ages", [])])
    valid: list[dict] = []
    for citation in item.get("citations") or ():
        if not isinstance(citation, dict):
            continue
        doc, quote = collapsed_text(citation.get("doc")), str(citation.get("quote") or "")
        path = doc.split("#", 1)[0]
        if doc == "story" or (story_path and path == story_path):
            ok = _quote_in(quote, story)
        elif doc == "spine":
            ok = _quote_in(quote, spine_text)
        elif doc in passages:
            ok = _quote_in(quote, passages[doc]["text"])
        else:
            # A path cited without its paragraph id: any retrieved passage of it.
            ok = any(_quote_in(quote, p["text"]) for p in passages.values() if p.get("path") == path)
        if ok:
            valid.append({"doc": doc, "quote": quote[:tc.MAX_EVIDENCE_QUOTE_CHARS]})
    if not valid:
        return None, "citations_unverified"
    if basis == "derived" and sp["birth"] and not any(c["doc"] == "spine" or c["doc"].startswith("fact:") for c in valid):
        # arithmetic must name the fact it was done against
        valid.append({"doc": "spine", "quote": f"Born: {sp['birth']}"})
    if target is not None and not _subject_is_owner((target or {}).get("subject"), sp) \
            and _is_age_of_subject(item, target) and _cites_owner_age_table(valid, sp):
        # Somebody else's age, answered off the owner's birthday. The reading
        # may even be right — but nothing in this vault says so, and a date
        # filed on that arithmetic is the owner's life drawn over his
        # mother's. It stays in the ledger as unverified, which is what keeps
        # the moment askable.
        return None, SUBJECT_AGE_NOT_OWNER
    confidence = item.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "record": record.to_dict(), "basis": basis, "confidence": confidence,
        "citations": valid, "fact_key": collapsed_text(item.get("fact_key")) or "unspecified",
        "reason": collapsed_text(item.get("reason"))[:400],
    }, "ok"


def verify_estimate(item: dict, *, sp: dict, subject: object = None) -> tuple[dict | None, str]:
    """v325. ``(normalized estimate, reason)``; ``None`` when there is none worth keeping.

    An estimate is what the model believes when the vault cannot tell: a bounded
    stretch with at least one line saying what it rests on. It is verified
    MECHANICALLY like everything else here — parseable, ordered, closed at both
    ends, not before the owner was born (a stretch wholly before the birth is
    family history, not a guess about this life) — and never against a quote,
    because it is not a claim. It is stored beside the question, published as
    the dot's ``probable_window``, and files nothing.

    v330: the pre-birth floor is the OWNER's. ``subject`` is the target's
    subject (:func:`_subject_is_owner`); a moment that happened to somebody
    else — the father's mission, a grandparent's move — may well fall before
    the owner was born, and dropping its window as ``pre_birth`` threw away
    exactly the estimate the vault could make (2026-09-23, the owner's vault:
    "James Edwin Taylor was born 4 June 1954 … early-to-mid 1970s" → dropped).
    ``None`` reads as the owner, which is what every caller before v330 meant.
    """
    raw = item.get("estimate")
    if not isinstance(raw, dict):
        return None, "no_estimate"
    record = _record(raw)
    if record is None:
        return None, "estimate_unparseable"
    if not record.earliest or not record.latest:
        return None, "estimate_open_ended"
    if record.earliest > record.latest:
        return None, "estimate_reversed"
    birth = collapsed_text(sp.get("birth"))
    try:
        if birth and int(record.latest[:4]) < int(birth[:4]) and _subject_is_owner(subject, sp):
            return None, "pre_birth"
    except ValueError:
        return None, "estimate_unparseable"
    basis: list[dict] = []
    for row in raw.get("basis") if isinstance(raw.get("basis"), list) else ():
        if not isinstance(row, dict):
            continue
        text = collapsed_text(row.get("text"))[:MAX_ESTIMATE_TEXT]
        if not text:
            continue
        kind = collapsed_text(row.get("kind"))
        entry = {"kind": kind if kind in ESTIMATE_BASIS_KINDS else "other", "text": text}
        ref = collapsed_text(row.get("ref"))
        if ref:
            entry["ref"] = ref[:MAX_ESTIMATE_TEXT]
        basis.append(entry)
        if len(basis) >= MAX_ESTIMATE_BASIS:
            break
    if not basis:
        return None, "estimate_without_basis"
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.4
    return {"earliest": record.earliest, "latest": record.latest, "basis": basis,
            "confidence": confidence}, "ok"


_HANDLE_RELATION_RE = re.compile(r"^(?:before|after|between|within|during|around)\s+", re.IGNORECASE)


def _handle_text(value: object) -> str:
    """The anchor words out of a copied handle line — ``after 'grandpa's death'``
    → ``grandpa's death``. Models copy the whole line; the check is on the words."""
    text = collapsed_text(value)
    text = _HANDLE_RELATION_RE.sub("", text).strip()
    while len(text) >= 2 and text[0] in "'\"‘“" and text[-1] in "'\"’”":
        text = text[1:-1].strip()
    return text


def verify_handle_binds(item: dict, *, target: dict, known_nodes: dict) -> list[dict]:
    """v325. The handle binds this answer names that the vault can actually take.

    A bind says "this moment's unresolved handle names THAT node". Mechanical
    checks only: the handle must be one of the target's own, the node must exist
    in the published projection and not be the target itself. Keyed through
    `temporal_work_items.anchor_handle_ref`, the same normalisation the fold's
    anchor index and the `anchor:` work items use, so a bind and the handle it
    answers agree on what the words are.
    """
    import temporal_work_items as twi  # noqa: PLC0415

    raw = item.get("handle_binds")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        handle = _handle_text(row.get("handle"))
        node_id = collapsed_text(row.get("node_id"))
        if not handle or node_id not in known_nodes or node_id == target["node_id"]:
            continue
        wanted = twi.anchor_handle_ref(handle)
        for h in target.get("handles") or ():
            claim_id = collapsed_text(h.get("claim_id"))
            for anchor in h.get("anchors") or ():
                if twi.anchor_handle_ref(anchor) != wanted or (claim_id, node_id) in seen:
                    continue
                seen.add((claim_id, node_id))
                out.append({"claim_id": claim_id, "relation": collapsed_text(h.get("relation")) or "after",
                            "handle": collapsed_text(anchor), "node_id": node_id,
                            "label": collapsed_text((known_nodes.get(node_id) or {}).get("label"))})
    return out


def verify_not_an_event(item: dict) -> tuple[dict | None, str]:
    """``({"kind", "reason"} , "ok")`` for an accepted verdict, else ``(None, why)``.

    Mechanical and total, like every other verification here. Two conditions
    and no more: the model must be claiming nothing about WHEN (``answer`` is
    null), and the kind must be one of :data:`NOT_AN_EVENT_KINDS`. A verdict
    that arrives beside a date is a contradiction, not a verdict, and is
    refused so the answer can be read as an ordinary reading instead.
    """
    verdict = item.get("not_an_event") if isinstance(item, dict) else None
    if not isinstance(verdict, dict):
        return None, "no_verdict"
    if item.get("answer") is not None:
        return None, "verdict_with_an_answer"
    kind = collapsed_text(verdict.get("kind"))
    if kind not in NOT_AN_EVENT_KINDS:
        return None, "verdict_kind_unknown"
    return {"kind": kind, "reason": collapsed_text(verdict.get("reason"))[:400]}, "ok"


# --------------------------------------------------------------------------
# Filing
# --------------------------------------------------------------------------

def prior_resolver_claims(index: dict) -> dict[str, list[str]]:
    """``node id -> claim ids`` filed by an earlier resolver rule, from one fold."""
    found: dict[str, list[str]] = collections.defaultdict(list)
    for row in store.active_claims(index):
        if collapsed_text(row.get("extractor_version")) in PRIOR_EXTRACTOR_VERSIONS:
            found[collapsed_text(row.get("event_ref"))].append(collapsed_text(row.get("claim_id")))
    return dict(found)


def reading_telling_ref(target: dict) -> str:
    """``resolver:<24 hex>`` naming the NODE this reading is about.

    The fallback half of :data:`READING_IS_NOT_AN_EVENT`, and it is keyed on the
    target's ``event_ref`` rather than on its ``node_id`` on purpose: a telling
    folded into an episode is published under the EPISODE's node id, while the
    claim filed about it names the telling's own event — so keying on the node
    id would mint a ref naming a node the reading's own `event_ref` never
    mentions, and `episode_binder.reads_node` (which requires exactly one named
    node) would not recognize it.
    """
    node = collapsed_text(target.get("event_ref")) or collapsed_text(target.get("node_id"))
    return f"{SOURCE_ID_PREFIX}{node.split(':')[-1]}"


def file_resolution(root: Path, target: dict, resolved: dict, *, story_path: str, model: str, now: str,
                    prior: dict[str, list[str]] | None = None) -> dict:
    """One receipt with one ``date`` claim on the event's own node; retire its raw handle."""
    record = dict(resolved["record"])
    if resolved["basis"] != "stated":
        # The store's basis vocabulary: arithmetic from an age is `age`; a date
        # worked out from stays, tenures and other anchors is `anchor`. Neither
        # is held more firmly than `inferred`.
        record["confidence"] = chrono.at_most(record.get("confidence") or "inferred", "inferred")
        record["basis"] = "age" if resolved["basis"] == "derived" and resolved["fact_key"].startswith("age") else "anchor"
    evidence = [{"quote": tc.bounded_quote(
        " | ".join(f"{c['doc']}: {c['quote']}" for c in resolved["citations"])[:tc.MAX_EVIDENCE_QUOTE_CHARS]
    )}]
    revision = _digest({"node": target["node_id"], "record": record, "citations": resolved["citations"], "model": model,
                        "telling": target.get("telling_ref") or ""})
    source_ref = {"source_id": f"{SOURCE_ID_PREFIX}{target['node_id'].split(':')[-1]}",
                  "revision": revision, "source_path": story_path}
    claim = tc.validate_temporal_claim({
        "source_ref": source_ref, "source_kind": "system_derived", "claim_type": "date",
        "subject_mention": target["subject"], "event_kind": target["event_kind"],
        "event_ref": target.get("event_ref") or target["node_id"],
        "event_mention": target["label"][:tc.MAX_EVENT_MENTION_CHARS],
        "temporal_value": record, "evidence": evidence,
        "basis": "explicit" if resolved["basis"] == "stated" else "inferred",
        "confidence": resolved["confidence"], "extractor_version": EXTRACTOR_VERSION,
    }, now=now)
    import event_identity as ei  # noqa: PLC0415

    extractor = {"name": "resolver", "rule_version": EXTRACTOR_VERSION.rsplit(":", 1)[-1], "model": model,
                 "deterministic": model == "deterministic", "basis": resolved["basis"], "fact_key": resolved["fact_key"]}
    # UNCONDITIONAL (:data:`READING_IS_NOT_AN_EVENT`). A reading with no telling
    # to re-read is still not an event of its own.
    extractor = ei.declare_tellings(
        extractor,
        telling_keys={claim["claim_id"]: target.get("telling_ref") or reading_telling_ref(target)},
        document_revision=target.get("document_revision"),
    )
    # A reading of this node filed by an earlier resolver rule is retired first;
    # the new receipt stands beside it, never over it.
    if prior is None:
        prior = prior_resolver_claims(store.fold_active_index(root))
    earlier = [c for c in {*prior.get(target["node_id"], []), *prior.get(target.get("event_ref") or "", [])} if c]
    if earlier:
        store.supersede_claims(root, earlier, reason=f"Re-filed under {EXTRACTOR_VERSION} with its telling declared",
                               scope=SUPERSEDE_SCOPE, title="Resolver reading re-filed", author="resolver", occurred_at=now)
    path = store.write_receipt(root, {
        "source_ref": source_ref, "extractor_version": EXTRACTOR_VERSION,
        "extractor": extractor, "claims": [claim],
    }, now=now)
    handles = [h["claim_id"] for h in target["handles"] if h.get("claim_id")]
    if handles:
        store.supersede_claims(
            root, handles,
            reason=(f"Resolved by {EXTRACTOR_VERSION} ({resolved['basis']}, fact {resolved['fact_key']}): "
                    f"{resolved['reason']}"),
            scope=SUPERSEDE_SCOPE, title="Handle resolved to a dated claim",
            author="resolver", occurred_at=now,
        )
    return {"receipt_path": str(path), "claim_id": claim["claim_id"], "superseded": handles}


def file_handle_bind(root: Path, target: dict, bind: dict, *, story_path: str, model: str, now: str) -> dict:
    """v325. One receipt with one ``relative_order`` claim whose anchor IS a node id.

    The raw handle said "after grandpa's death" in the person's words and the fold
    could not tell which node those words name — an anchor two nodes answer to
    resolves to neither, by design. The bind re-files the SAME relation with the
    node the model pointed at as its anchor (`_anchor_index` seeds every node id
    as its own key, so the edge resolves without a word match), and retires the
    raw handle beside it with a supersession correction — durable, cited on the
    story that answered it, and correctable exactly like a date. The fold then
    places the moment through the ordinary edge, and the `missing_anchor` work
    item that asked whose event it was goes away because nothing is missing.
    """
    import event_identity as ei  # noqa: PLC0415

    relation = bind["relation"] if bind["relation"] in tc.CONSTRAINT_RELATIONS else "after"
    revision = _digest({"node": target["node_id"], "handle": bind["handle"], "bound": bind["node_id"],
                        "model": model, "telling": target.get("telling_ref") or ""})
    source_ref = {"source_id": f"{SOURCE_ID_PREFIX}{target['node_id'].split(':')[-1]}",
                  "revision": revision, "source_path": story_path}
    claim = tc.validate_temporal_claim({
        "source_ref": source_ref, "source_kind": "system_derived", "claim_type": "relative_order",
        "subject_mention": target["subject"], "event_kind": target["event_kind"],
        "event_ref": target.get("event_ref") or target["node_id"],
        "event_mention": target["label"][:tc.MAX_EVENT_MENTION_CHARS],
        "temporal_value": {"relation": relation, "anchors": [bind["node_id"]]},
        "evidence": [{"quote": tc.bounded_quote(f"{bind['handle']} names {bind['label'] or bind['node_id']}")}],
        "basis": "inferred", "confidence": 0.7, "extractor_version": EXTRACTOR_VERSION,
    }, now=now)
    extractor = {"name": "resolver", "rule_version": EXTRACTOR_VERSION.rsplit(":", 1)[-1], "model": model,
                 "deterministic": False, "basis": "handle_bind", "fact_key": "handle_bind"}
    extractor = ei.declare_tellings(
        extractor,
        telling_keys={claim["claim_id"]: target.get("telling_ref") or reading_telling_ref(target)},
        document_revision=target.get("document_revision"),
    )
    path = store.write_receipt(root, {
        "source_ref": source_ref, "extractor_version": EXTRACTOR_VERSION,
        "extractor": extractor, "claims": [claim],
    }, now=now)
    superseded = [bind["claim_id"]] if bind.get("claim_id") else []
    if superseded:
        store.supersede_claims(
            root, superseded,
            reason=(f"Handle '{bind['handle']}' bound by {EXTRACTOR_VERSION} to {bind['node_id']}"
                    f" ({bind['label'] or 'unlabelled'})"),
            scope=SUPERSEDE_SCOPE, title="Handle bound to a moment",
            author="resolver", occurred_at=now,
        )
    return {"receipt_path": str(path), "claim_id": claim["claim_id"], "superseded": superseded,
            "handle": bind["handle"], "node_id": bind["node_id"]}


def file_not_an_event(root: Path, target: dict, verdict: dict, *, now: str) -> dict:
    """Retract the claims behind a moment that was never one. A CORRECTION.

    Never a delete. The claims stay on disk with a dated retraction beside
    them saying who withdrew them and why — the same durable path a person's
    own correction takes (`temporal_store.retract_claims`), under this
    verdict's own scope so the record can tell the two acts apart. The node
    leaves the projection on the republish that follows filing, because the
    fold draws from the ACTIVE claims and there are now none.

    Returns ``{"retracted", "correction_id", "correction_path"}``; a verdict
    that names no claim retracts nothing and says so rather than filing an
    empty correction.
    """
    claim_ids = [collapsed_text(ref) for ref in target.get("node_claim_refs") or ()
                 if collapsed_text(ref)]
    if not claim_ids:
        return {"retracted": [], "correction_id": "", "correction_path": ""}
    reason = (f"Not an event ({verdict['kind']}) by {EXTRACTOR_VERSION}: "
              f"{verdict['reason'] or 'the moment is not something that happened'}")
    correction = store.retract_claims(
        root, claim_ids, reason=reason, scope=NOT_AN_EVENT_SCOPE,
        title="Moment retired as not an event", author="resolver", occurred_at=now,
    )
    return {"retracted": sorted(claim_ids),
            "correction_id": correction.correction_id,
            "correction_path": correction.relative_path}


#: v333, defect B, the resolver's half. A card that asks for a date the vault
#: already holds is worse than no card: the owner types the answer, the answer
#: lands on a node of its own, and the next publication asks again. So before
#: anything is asked, an unplaced node whose normalized label and subject match
#: a node the projection has already PLACED is not a question — it is the same
#: moment, said twice. The resolver refuses to ask it and emits a `same_as`
#: row; :func:`file_same_as` turns that row into the ordinary deterministic
#: `same` binding `episode_binder` would have filed, through
#: `event_identity`'s own writers, so the two nodes become one episode and the
#: unplaced one inherits the placement it was asking for.
#:
#: Conservative on purpose, and in three ways: the labels must be IDENTICAL once
#: normalized (a resemblance is the binder's business, not the resolver's), the
#: subjects must agree, and a pair a person has already called `not_same` is
#: refused by the binder's own :func:`episode_binder.link_refusal`, which this
#: leg calls rather than reimplements.
RESTATEMENT_IS_NOT_A_QUESTION = (
    "an unplaced moment whose normalized label and subject already name a "
    "placed node is a retelling, not a question: the resolver binds it instead "
    "of asking, and a human `not_same` still refuses the bind"
)


def _subject_key(node: dict) -> tuple:
    refs = [collapsed_text(ref) for ref in (node.get("subject_refs") or ()) if collapsed_text(ref)]
    return tuple(sorted({_norm(ref) for ref in refs} - {""}))


def restated_placed_nodes(projection: dict) -> dict[str, dict]:
    """``{unplaced node id: the placed node it restates}``.

    One pass over the projection, keyed on ``(normalized label, subject)``. A
    key that names more than one placed node is SKIPPED — two placements to
    inherit is no placement at all, and guessing between them is the defect
    this rule exists to end.
    """
    placed: dict[tuple, list] = {}
    unplaced: list[dict] = []
    for node in projection.get("nodes") or ():
        if collapsed_text(node.get("node_kind")) == "period":
            continue
        label = _norm(node.get("label"))
        if not label:
            continue
        key = (label, _subject_key(node))
        if node.get("usable_placement"):
            placed.setdefault(key, []).append(node)
        else:
            unplaced.append(node)
    found: dict[str, dict] = {}
    for node in unplaced:
        rows = placed.get((_norm(node.get("label")), _subject_key(node))) or []
        if len(rows) != 1:
            continue
        other = rows[0]
        if other["node_id"] == node["node_id"]:
            continue
        found[node["node_id"]] = {
            "node_id": other["node_id"],
            "label": collapsed_text(other.get("label")),
            "reason": (f"{collapsed_text(node.get('label'))!r} is already placed as "
                       f"{other['node_id']}"),
        }
    return found


def _tellings_of(node: dict, index: dict, by_claim: dict) -> list[str]:
    refs = []
    for claim_id in node.get("input_claim_refs") or ():
        telling_ref = collapsed_text(by_claim.get(collapsed_text(claim_id)))
        if telling_ref and telling_ref not in refs:
            refs.append(telling_ref)
    return refs


def file_same_as(root: Path, *, now: str) -> dict:
    """File every :func:`restated_placed_nodes` pair as one `same` binding.

    Through `episode_binder`'s OWN grouping and `event_identity`'s own writers —
    never by hand. The grouping matters as much as the writing: the first version
    of this filed one envelope per pair and the clone refused it by name
    (`identity_conflict: resolver:9508e174… carries 2 active same bindings`),
    because both of the owner's "Dottie's birth" nodes restate the SAME placed
    node and one telling cannot belong to two episodes. `exact_identity_groups`
    is where that is already solved — it refuses a pair a person called
    `not_same`, expands a group to whole existing episodes, and coalesces groups
    that meet — so this leg builds the links and hands them over.

    Returns a report; writes nothing when there is nothing to write, and
    re-publishes only when it wrote.
    """
    import episode_binder as eb  # noqa: PLC0415
    import episode_fold as ef  # noqa: PLC0415
    import event_identity as ei  # noqa: PLC0415
    import temporal_publication as pub  # noqa: PLC0415

    projection = pub.read_projection(root) or {}
    pairs = restated_placed_nodes(projection)
    report = {"pairs": len(pairs), "filed": 0, "refused": [], "skipped": 0, "episodes": []}
    if not pairs:
        return report
    index = store.fold_active_index(root)
    claims = [row for row in (index.get("claims") or ()) if isinstance(row, dict)]
    by_claim = ef.claim_telling_index(claims, ei.read_telling_manifest(root))
    nodes = {node["node_id"]: node for node in projection.get("nodes") or ()}
    views = eb.telling_views(claims, entity_index=eb.ec.load_entity_index(root))
    records = ef.load_episode_records(root)
    normalized = ef.normalize_episode_records(records)
    active = eb.efc.active_binding_index(normalized["bindings"])
    entailed = eb.efc.entailed_not_same(normalized["bindings"])
    units = eb.candidates(views, episode_records=records)

    links: list = []
    for node_id in sorted(pairs):
        other = pairs[node_id]
        mine = [ref for ref in _tellings_of(nodes.get(node_id) or {}, index, by_claim)
                if ref in views]
        theirs = [ref for ref in _tellings_of(nodes.get(other["node_id"]) or {}, index, by_claim)
                  if ref in views]
        if not mine or not theirs:
            report["skipped"] += 1
            continue
        for left in mine:
            for right in theirs:
                if left != right:
                    links.append(eb.ExactLink(
                        rule_id=eb.RULE_ID_SAME_LABEL, left=left, right=right,
                        key=_norm(other["label"]), reason=other["reason"]))
    groups = eb.exact_identity_groups(
        links, views, units, active=active, entailed=entailed,
        refused=report["refused"],
    )
    for group in groups:
        envelope = eb.group_envelope(group, views=views, active=active, now=now)
        outcome = ei.file_operation_envelope(
            root, operation=envelope["operation"], bindings=envelope["bindings"])
        report["filed"] += 1 if outcome["created"] else 0
        report["episodes"].append(envelope["operation"]["episode_id"])
    report["groups"] = len(groups)
    if report["filed"]:
        _republish(root)
    return report


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

def load_ledger(root: Path) -> dict:
    return _json(root / LEDGER_RELATIVE, {"version": 1, "nodes": {}}) or {"version": 1, "nodes": {}}


def save_ledger(root: Path, ledger: dict) -> None:
    atomic_write_vault_text(
        LEDGER_RELATIVE,
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        vault_root=root,
    )


def open_questions(ledger: dict) -> list[dict]:
    """Unknowns grouped by fact, most leverage first — the owner's short list."""
    groups: dict[str, dict] = {}
    for node_id, row in (ledger.get("nodes") or {}).items():
        if row.get("status") != "unknown" or not row.get("question"):
            continue
        key = row.get("fact_key") or row["question"]
        group = groups.setdefault(key, {"fact_key": key, "question": row["question"], "nodes": [], "labels": []})
        group["nodes"].append(node_id)
        group["labels"].append(row.get("label", ""))
    return sorted(groups.values(), key=lambda g: (-len(g["nodes"]), g["fact_key"]))


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

def make_completer(model: str):
    """A ``prompt -> (text, usage)`` callable.

    The hosted platform's adapter when ``LIFEHUG_PLATFORM_API_ROOT`` names it
    (one transport, one key custody); otherwise the package's own gateway,
    `ai_provider.call_ai`, which is what every other model-calling verb uses.
    """
    api_root = os.environ.get("LIFEHUG_PLATFORM_API_ROOT", "")
    if not api_root:
        from ai_provider import call_ai  # noqa: PLC0415

        def complete_local(prompt: str, key: str):
            return call_ai(prompt, model), {}

        return complete_local
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    os.environ["LIFEHUG_LLM_LIVE_MODE"] = "1"
    # The platform package is outside this repository; it is reached by name
    # only when its root was supplied, never by an import the package sweep
    # would have to resolve.
    import importlib  # noqa: PLC0415

    AnthropicLlmAdapter = importlib.import_module("app.llm.anthropic_live").AnthropicLlmAdapter
    LlmRequest = importlib.import_module("app.llm.interfaces").LlmRequest

    class _Secrets:
        def get_secret(self, name):
            return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None if name == "ANTHROPIC_API_KEY" else None

    adapter = AnthropicLlmAdapter(_Secrets(), timeout_seconds=600.0, max_retries=2)

    def complete(prompt: str, key: str):
        result = adapter.complete(LlmRequest(
            tenant_id="local-resolver", vault_id="local-resolver", purpose="classify",
            prompt=prompt, model=model, max_tokens=16000, idempotency_key=key,
            thinking="adaptive", wall_timeout_seconds=None,
        ))
        return result.text, {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                             "stop_reason": result.stop_reason}

    return complete


def parse_answers(text: str) -> list[dict]:
    """The answer rows in a response; an unparseable response is simply no rows."""
    import classify_story  # noqa: PLC0415

    # A model occasionally writes code into a string (`"node:...".replace(...)`);
    # the string itself is the answer, the call is noise.
    text = re.sub(r"(\"[^\"]*\")\s*\.replace\([^)]*\)", r"\1", text)
    try:
        payload = classify_story.extract_json(text) if "answers" in text else {}
    except Exception:  # noqa: BLE001 - one bad response marks its own source only
        return []
    rows = payload.get("answers") if isinstance(payload, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _response_path(root: Path, key: str) -> Path:
    return root / RESPONSES_RELATIVE / f"{key}.json"


def _save_response(root: Path, key: str, payload: dict) -> None:
    """A purchase is durable before anything reads it; a rerun never buys it twice.
    Written through the vault's own atomic, no-follow authority."""
    atomic_write_vault_text(
        RESPONSES_RELATIVE / f"{key}.json",
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        vault_root=root,
    )


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

def _story_text(root: Path, source_path: str) -> str:
    """The story with its own record line first: a source's date is evidence too."""
    meta, body = split_frontmatter(_read(root / source_path))
    bits = [f"source {source_path}"]
    for key in ("title", "captured_at", "answered_date", "asked_at", "date"):
        if meta.get(key):
            bits.append(f"{key}: {meta[key]}")
    return "[" + " | ".join(str(b) for b in bits) + "]\n\n" + body.strip()


RETRY_STATUSES = ("unverified", "no_answer_returned", "file_error")

#: A story whose answer came back short is re-asked in small groups, so one
#: long story cannot starve its own moments.
CHUNK = 4
#: Twice. A story that returns nothing for a moment twice is not asked again
#: without ``--retry-failed``: the third purchase has never bought anything.
MAX_ATTEMPTS = 2
PLAN_SCHEMA_VERSION = 1
ENVELOPE_SCHEMA_VERSION = 1
MAX_OUTPUT_TOKENS = 16000
_UNBOUNDED = 1 << 30


# --------------------------------------------------------------------------
# The two legs: a plan anyone can buy, and an envelope anyone can file
# --------------------------------------------------------------------------
#
# The local run is one process: read the vault, ask the model, file what
# verified. A host cannot be one process — it holds the key, it buys the
# completion somewhere else, and it may deliver the same answer twice. So the
# same work is expressed as two pure legs with the vault in between:
#
#   plan_items()   read-only. Which moments are still unplaced, and the exact
#                  prompt that would answer them, with an identity stamp of
#                  the bytes the prompt was built from.
#   file_envelope()  the answers come back; verify them against the vault as it
#                  is NOW, refuse the ones whose story moved under them, file
#                  the rest exactly as the local run does.
#
# `resolve_vault` is those two legs composed in memory with the response cache
# between them, which is why the local behaviour is unchanged.


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _source_sha256(root: Path, source_path: str) -> str:
    """The story's bytes, hashed.

    The host echoes it back with the answer; a story the owner edited while
    the model was thinking refuses the answer instead of filing a reading of
    a page that no longer exists.
    """
    if not source_path:
        return ""
    return hashlib.sha256(_read_bytes(root / source_path)).hexdigest()


def _targets_digest(node_ids: list[str], by_node: dict) -> str:
    """The moments an item was planned for AND the raw handles it would retire.

    Empty when a node is no longer a target at all — something else placed it,
    and an answer to a question that is already settled must not be filed.
    """
    values: list[str] = []
    for node_id in node_ids:
        found = by_node.get(node_id)
        if found is None:
            return ""
        values.append(node_id)
        values.extend(collapsed_text(h.get("claim_id")) for h in found[1].get("handles") or ()
                      if h.get("claim_id"))
    return _digest(sorted(set(values)))


class _Read:
    """One read of the vault, shared by a plan and by the filing that answers it.

    Everything a plan needs and everything absorbing an answer needs, derived
    once: the published projection, the folded index, the ledger, the spine,
    the full-text index and the targets. A composed local run holds ONE of
    these across both rounds, so the ledger it mutates is the ledger it plans
    against.
    """

    def __init__(self, root: Path, *, triggers=None) -> None:
        import temporal_publication as pub  # noqa: PLC0415

        self.root = root
        self.projection = pub.read_projection(root) or {}
        self.work_items = pub.read_work_items(root) or {}
        self.known_nodes = {collapsed_text(n.get("node_id")): n
                            for n in (self.projection.get("nodes") or ()) if isinstance(n, dict)}
        self.index = store.fold_active_index(root)
        self.ledger = load_ledger(root)
        self.spine = spine(root, self.projection)
        self.fts = Index(story_documents(root) + fact_documents(root, self.projection))
        self.targets = targets(root, self.projection, self.index)
        self.prior = prior_resolver_claims(self.index)
        # v325. Placed moments the RESOLVER dated to a wide range are kept
        # reachable, so a story that carries the exact date can sharpen them.
        wide = frozenset(node_id for node_id, row in (self.ledger.get("nodes") or {}).items()
                         if _wide_resolution(row))
        if wide:
            for source_path, rows in targets(root, self.projection, self.index, include_placed=wide).items():
                have = {t["node_id"] for t in self.targets.get(source_path, [])}
                extra = [t for t in rows if t["node_id"] in wide and t["node_id"] not in have]
                if extra:
                    self.targets.setdefault(source_path, []).extend(extra)
        self.by_node = {t["node_id"]: (s, t) for s, rows in self.targets.items() for t in rows}
        self.spine_digest = _digest(self.spine)
        # v325. The stories that were just filed, and the settled-unknown moments
        # elsewhere they may bear on. Empty when nothing was named.
        self.triggers = {collapsed_text(t) for t in (triggers or ()) if collapsed_text(t)}
        self.revisit = revisit_targets(self)

    def row(self, node_id: str) -> dict:
        return (self.ledger.get("nodes") or {}).get(node_id) or {}

    def include_paths(self, rows: list[dict]) -> list[str]:
        """The triggering stories whose passages these rows' prompt must carry.

        v330: a trigger that is a CONVERSATION message brings the rest of its
        card session along (:func:`_session_siblings`). The person answers a
        card across several messages — "19-21 years old", then "he was 19-21,
        not me", then his birthday — and only the last carried a year; a
        prompt that saw that one alone reasoned from "missionaries
        traditionally serve at 19" instead of from what the person said.
        """
        out: set[str] = set()
        for t in rows:
            info = self.revisit.get(t["node_id"])
            if not info:
                continue
            out.add(info["trigger"])
            out.update(self.session_siblings(info["trigger"]))
        return sorted(out)

    def session_siblings(self, source_path: str) -> list[str]:
        """The OTHER messages of the card session ``source_path`` belongs to, cached."""
        cache = self.__dict__.setdefault("_siblings", {})
        if source_path not in cache:
            cache[source_path] = _session_siblings(self.root, source_path)
        return cache[source_path]

    def open_rows_for(self, source_path: str) -> list[dict]:
        """The open questions a TRIGGERING story's own prompt lists (v325)."""
        if source_path not in self.triggers:
            return []
        out: list[dict] = []
        for node_id, info in self.revisit.items():
            if info["trigger"] != source_path or node_id not in self.by_node:
                continue
            other_source, target = self.by_node[node_id]
            out.append({"node_id": node_id, "label": target["label"], "source_path": other_source,
                        "question": collapsed_text(self.row(node_id).get("question")),
                        "handles": target["handles"]})
        return out


def _approx_years(text: object) -> float | None:
    """``YYYY[-MM[-DD]]`` → a fractional year, for comparing widths only."""
    parts = collapsed_text(text).split("-")
    try:
        year = int(parts[0]); month = int(parts[1]) if len(parts) > 1 else 1; day = int(parts[2]) if len(parts) > 2 else 1
    except (ValueError, IndexError):
        return None
    return year + (month - 1) / 12 + (day - 1) / 365.25


def _width_years(answer: object) -> float | None:
    row = answer if isinstance(answer, dict) else {}
    a, b = _approx_years(row.get("earliest")), _approx_years(row.get("latest"))
    return None if a is None or b is None else b - a


def _wide_resolution(row: dict) -> bool:
    """A reading the resolver filed whose range spans REFINE_MIN_YEARS or more."""
    if collapsed_text(row.get("status")) != "resolved":
        return False
    width = _width_years(row.get("answer"))
    return width is not None and width >= REFINE_MIN_YEARS


def _session_siblings(root: Path, source_path: str) -> list[str]:
    """Every other file beside ``source_path`` whose frontmatter names the SAME
    ``session_ref`` — the earlier and later messages of one card conversation.
    ``[]`` when the file has no session, does not exist, or sits alone."""
    path = root / source_path
    if not path.is_file():
        return []
    meta, _body = split_frontmatter(_read(path))
    wanted = collapsed_text(meta.get("session_ref"))
    if not wanted:
        return []
    out: list[str] = []
    for sibling in sorted(path.parent.glob("*.md")):
        if sibling == path:
            continue
        try:
            other, _ = split_frontmatter(_read(sibling))
        except Exception:  # noqa: BLE001 — a file that will not parse is not a message
            continue
        if collapsed_text(other.get("session_ref")) == wanted:
            out.append(sibling.relative_to(root).as_posix())
    return out


def _work_item_of_session(session_ref: object) -> str:
    """``conversation:cand:work_item:work:<hex>`` → ``work:<hex>``, else ``""``."""
    text = collapsed_text(session_ref)
    if SESSION_WORK_ITEM_MARKER not in text:
        return ""
    return text.split(SESSION_WORK_ITEM_MARKER, 1)[1].strip()


def revisit_targets(read: "_Read") -> dict[str, dict]:
    """v325. ``node_id -> {"trigger", "why"}``: the settled unknowns a new story re-opens.

    Before v325 an ``unknown`` in the ledger was terminal: the resolver planned
    the story that was just filed and nothing else, so a fact that answered an
    OLD question only helped if it happened to become a new dated event with the
    same words. Three signals, computed on the fly from what the vault already
    holds — never a stored graph that could go stale:

    * **conversation** — the promoted message's own ``session_ref`` names the work
      item the person was answering (the platform's ``cand:work_item:`` session).
      Its node, or every moment whose unresolved handle IS that ``anchor:`` item,
      is re-asked first, whatever the words.
    * **retrieval** — a settled unknown whose own retrieval query now returns a
      passage of the new story. The same index the prompt is built from, so a
      moment is re-asked exactly when the new text would be in its passages.

    A moment is re-asked ONCE per trigger (``revisited_by`` on the ledger row),
    and at most :data:`MAX_REVISITS` are re-opened by retrieval per plan.

    A REFINE (a wide reading the resolver itself filed, re-asked to sharpen
    it) by retrieval needs the new story to carry a date at all
    (`chronology.YEAR_RE`): a broad life story that merely mentions the same
    words cannot sharpen anything, and on the owner's vault one such story
    bought three re-asks that all kept the standing answer (v326).
    """
    if not read.triggers:
        return {}
    import temporal_work_items as twi  # noqa: PLC0415

    out: dict[str, dict] = {}

    def add(node_id: str, trigger: str, why: str) -> None:
        if node_id in out or node_id not in read.by_node:
            return
        if read.by_node[node_id][0] in read.triggers:
            return  # the story's own moments are planned anyway
        row = read.row(node_id)
        if trigger in (row.get("revisited_by") or ()) or trigger in (row.get("refine_attempted_by") or ()):
            return  # asked once with this story already
        out[node_id] = {"trigger": trigger, "why": why}

    dated_triggers = {t for t in read.triggers
                      if (read.root / t).is_file() and chrono.YEAR_RE.search(_read(read.root / t))}
    items = [row for row in (read.work_items.get("work_items") or ()) if isinstance(row, dict)]
    aliases = read.work_items.get("work_item_aliases") if isinstance(read.work_items.get("work_item_aliases"), dict) else {}
    for trigger in sorted(read.triggers):
        path = read.root / trigger
        if not path.is_file():
            continue
        meta, _body = split_frontmatter(_read(path))
        wanted = _work_item_of_session(meta.get("session_ref"))
        if not wanted:
            continue
        wanted = collapsed_text(aliases.get(wanted, wanted))
        for row in items:
            wid = collapsed_text(row.get("work_item_id"))
            if wid != wanted and collapsed_text(aliases.get(wid, wid)) != wanted:
                continue
            node_ref = collapsed_text(row.get("node_ref"))
            if node_ref:
                add(node_ref, trigger, "conversation")
            subject = collapsed_text(row.get("subject_ref"))
            if twi.is_anchor_handle_ref(subject):
                for node_id, (_source, target) in read.by_node.items():
                    if any(twi.anchor_handle_ref(a) == subject
                           for h in target["handles"] for a in (h.get("anchors") or ())):
                        add(node_id, trigger, "conversation")
    by_retrieval = 0
    for node_id, (source, target) in read.by_node.items():
        if by_retrieval >= MAX_REVISITS:
            break
        if node_id in out or source in read.triggers:
            continue
        row = read.row(node_id)
        status = collapsed_text(row.get("status"))
        refine = _wide_resolution(row)
        if status not in ("unknown", "unverified") and not refine:
            continue
        for doc in read.fts.search(_query(target), exclude_path=source):
            if doc.get("path") not in read.triggers:
                continue
            if refine and doc["path"] not in dated_triggers:
                continue  # nothing to sharpen with: the story names no date
            before = len(out)
            add(node_id, doc["path"], "refine" if refine else "retrieval")
            by_retrieval += len(out) - before
            break
    return out


def _attempts(row: dict) -> int:
    try:
        return max(0, int(row.get("attempts") or 0))
    except (TypeError, ValueError):
        return 0


def _still_asking(row: dict, *, retry_failed: bool, force: bool, revisit: bool = False,
                  estimate_missing: bool = False) -> bool:
    """Is this moment still a question? Once answered, never asked again —
    except (v325) when a new story bears on it, which re-opens an ``unknown``
    (or a wide resolver-dated reading, to sharpen it) once for that story; and
    an ``unknown`` with no estimate yet is asked once more when a run is told
    to fill estimates in (``--estimate-missing``, the one-time backfill)."""
    if force:
        return True
    status = collapsed_text(row.get("status"))
    if not status:
        return True
    if revisit and (status in ("unknown", "unverified") or _wide_resolution(row)):
        return True
    if estimate_missing and status in ("unknown", "unverified") and not isinstance(row.get("estimate"), dict):
        return True
    if status in ("resolved", "unknown", NOT_AN_EVENT_STATUS):
        # A moment judged not to be an event is as settled as a dated one:
        # re-planning it would buy the same verdict again, and `--refile` has
        # nothing to re-file (there is no answer, only a retraction that
        # already stands).
        return False
    if status == "no_answer_returned":
        # The round-2 re-ask, made re-entrant: a row the model skipped is
        # asked once more in a smaller group, and then left alone.
        return retry_failed or _attempts(row) < MAX_ATTEMPTS
    if status in RETRY_STATUSES:
        return retry_failed
    return True


def _pending(read: _Read, *, only_sources=None, retry_failed: bool = False, force: bool = False,
             restrict: bool = False, estimate_missing: bool = False,
             ) -> tuple[list[tuple[str, list[dict]]], list[tuple[str, dict, tuple]]]:
    """``([(source_path, rows)], [(source_path, target, (age, relation))])``.

    The second list is the moments a bare age handle already answers: they need
    no model and no question, so they are counted apart and filed by arithmetic.
    """
    birth = read.spine["birth"]
    pending: list[tuple[str, list[dict]]] = []
    deterministic: list[tuple[str, dict, tuple]] = []
    for source_path in sorted(read.targets):
        rows = []
        for target in read.targets[source_path]:
            revisit = target["node_id"] in read.revisit
            # A restricted run keeps to the named stories — plus (v325) the
            # moments elsewhere those stories re-open.
            if restrict and only_sources and source_path not in only_sources and not revisit:
                continue
            if not _still_asking(read.row(target["node_id"]), retry_failed=retry_failed, force=force,
                                 revisit=revisit, estimate_missing=estimate_missing):
                continue
            aged = [(age_from_handle(a), h.get("relation"))
                    for h in target["handles"] for a in (h.get("anchors") or ())]
            aged = [(a, rel) for a, rel in aged if a is not None]
            # The same rule `verify` applies, at the lane that never reaches
            # it: a bare age is arithmetic off the OWNER's birthday, so it is
            # arithmetic only when the moment is the owner's. Somebody else's
            # "at 21" goes to the model with the rest of its story.
            if aged and birth and _subject_is_owner(target.get("subject"), read.spine) \
                    and len({a for a, _ in aged}) == 1 and age_range(birth, aged[0][0], aged[0][1]):
                deterministic.append((source_path, target, aged[0]))
            else:
                rows.append(target)
        if rows:
            pending.append((source_path, rows))
    return pending, deterministic


def _ordered(read: _Read, pending: list, only_sources) -> list:
    """The story the owner just told first, then the longest-waiting, then the new.

    A host plans one item at a time and loops; the order is what decides which
    question its next purchase answers.
    """
    named = set(only_sources or ())
    # v325: the stories whose moments the named story just re-opened come
    # right after it, so a host buying one item per hop reaches them next.
    reopened = {read.by_node[n][0] for n in read.revisit if n in read.by_node}
    oldest: dict[str, str] = {}
    for row in (read.ledger.get("nodes") or {}).values():
        source_path, at = collapsed_text(row.get("source_path")), collapsed_text(row.get("at"))
        if source_path and at and at < oldest.get(source_path, "~"):
            oldest[source_path] = at

    def rank(entry):
        source_path, _rows = entry
        if source_path in named:
            return (0, "", source_path)
        if source_path in reopened:
            return (1, "", source_path)
        seen = oldest.get(source_path)
        return (2, seen, source_path) if seen else (3, "", source_path)

    return sorted(pending, key=rank)


def _groups(read: _Read, rows: list[dict], *, unanswered_only: bool) -> list[list[dict]]:
    """One item per story — except the rows a previous round left unanswered."""
    fresh, again = [], []
    for target in rows:
        row = read.row(target["node_id"])
        (again if collapsed_text(row.get("status")) == "no_answer_returned" else fresh).append(target)
    groups = [] if unanswered_only or not fresh else [fresh]
    groups += [again[start:start + CHUNK] for start in range(0, len(again), CHUNK)]
    return groups


def plan_items(root: Path, *, limit: int = 1, only_sources=None, retry_failed: bool = False,
               force: bool = False, model: str = DEFAULT_MODEL, read: _Read | None = None,
               restrict: bool = False, unanswered_only: bool = False, estimate_missing: bool = False) -> dict:
    """Leg A. What is still unplaced, and the exact prompt that would place it.

    Read-only: nothing under the vault is touched — no ledger, no filing, no
    publish, no response cache. ``only_sources`` orders the named stories first
    (that is the story the person just told); ``restrict=True`` makes it a
    filter instead, which is what the local run and the batch hook want.
    """
    read = read or _Read(root, triggers=only_sources)
    pending, deterministic = _pending(read, only_sources=only_sources, retry_failed=retry_failed,
                                      force=force, restrict=restrict, estimate_missing=estimate_missing)
    items: list[dict] = []
    cap = max(0, int(limit))
    for source_path, rows in _ordered(read, pending, only_sources):
        for group in _groups(read, rows, unanswered_only=unanswered_only):
            if len(items) >= cap:
                break
            node_ids = [target["node_id"] for target in group]
            include_paths = read.include_paths(group)
            passages = _retrieve(read.fts, group, source_path, include_paths=include_paths)
            items.append({
                # v325: the triggering stories are part of the purchase's identity —
                # a re-ask with NEW passages is a new question, never the cached
                # answer to the old one ("a rerun never buys twice" still holds
                # for the same source, the same moments and the same evidence).
                "key": _digest({"source": source_path, "nodes": node_ids, "model": model,
                                **({"include": include_paths} if include_paths else {})})[7:39],
                "source_path": source_path,
                "node_ids": node_ids,
                # v325, additive: the stories whose passages this prompt carries
                # because they re-opened one of these moments, and whether this
                # story is one that was just filed. Leg C reads both back so the
                # passages a citation is verified against are the ones planned.
                "include_paths": include_paths,
                "trigger": source_path in read.triggers,
                "revisits": sorted(n for n in node_ids if n in read.revisit),
                "prompt": build_prompt(source_path=source_path, story=_story_text(root, source_path),
                                       rows=group, sp=read.spine, passages=passages,
                                       open_rows=read.open_rows_for(source_path)),
                "identity": {
                    "source_sha256": _source_sha256(root, source_path),
                    "spine_digest": read.spine_digest,
                    "targets_digest": _targets_digest(node_ids, read.by_node),
                },
            })
        if len(items) >= cap:
            break
    pending_events = sum(len(rows) for _s, rows in pending)
    remaining_events = pending_events - sum(len(item["node_ids"]) for item in items)
    # Filing this plan also files every bare age handle (that is what leg C
    # does first), so they only keep the vault incomplete when nothing is being
    # filed at all.
    remaining_deterministic = 0 if items else len(deterministic)
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "model_hint": model,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "items": items,
        "pending_sources": len(pending),
        "pending_events": pending_events,
        "deterministic_pending": len(deterministic),
        "complete": not remaining_events and not remaining_deterministic,
    }


def write_plan(plan: dict, out: object, *, vault_root: Path) -> Path:
    """Write a plan to ``out``, which must be OUTSIDE the vault.

    A plan is a host's scratch file, not vault data: it holds prompts, and
    prompts are a reconstruction of the vault rather than a record of it. The
    vault's own no-follow writer is the authority for vault paths and is not a
    general-purpose file API, so an ``--out`` inside the vault root is refused
    rather than quietly filed where a fold would later read it.
    """
    destination = Path(out).expanduser().resolve()
    root = Path(vault_root).resolve()
    if destination == root or root in destination.parents:
        raise ValueError(f"--out must be outside the vault root ({root}): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Deliberately the builtin writer: this path is not a vault path, and
    # routing it through `vault_paths` would claim an authority over it that
    # the vault does not have.
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return destination


def _unanswered(read: _Read, target: dict, *, source_path: str, model: str, now: str,
                spine_changed: bool) -> None:
    """The model returned nothing for this moment. Remember that it was asked."""
    entry = {"label": target["label"], "source_path": source_path, "model": model, "at": now,
             "status": "no_answer_returned", "attempts": _attempts(read.row(target["node_id"])) + 1}
    if spine_changed:
        entry["spine_changed"] = True
    read.ledger["nodes"][target["node_id"]] = entry


def _absorb(read: _Read, report: dict, rows: list[dict], *, text: str, story: str, passages: dict,
            source_path: str, model: str, now: str, spine_changed: bool) -> None:
    """Verify, file, remember — for every moment the item was planned for."""
    answers = {collapsed_text(a.get("node_id")): a for a in parse_answers(text)}
    for target in rows:
        node_id = target["node_id"]
        item = answers.get(node_id)
        if item is None:
            _unanswered(read, target, source_path=source_path, model=model, now=now,
                        spine_changed=spine_changed)
            report["outcomes"]["no_answer_returned"] += 1
            continue
        entry = {"label": target["label"], "source_path": source_path, "model": model, "at": now,
                 "fact_key": collapsed_text(item.get("fact_key")) or None}
        # v325: remember which stories re-opened this moment, so each does so once.
        previous = read.row(node_id)
        revisit = read.revisit.get(node_id)
        revisited_by = sorted({*(previous.get("revisited_by") or ()), *([revisit["trigger"]] if revisit else [])})
        if revisited_by:
            entry["revisited_by"] = revisited_by
        if revisit:
            entry["revisit_why"] = revisit["why"]
        if spine_changed:
            # The frame moved after the prompt was built. The citations are
            # still verified against the text as it is now, so this is a note
            # on the reading, not a reason to throw it away.
            entry["spine_changed"] = True
        resolved, why = verify(item, story=story, passages=passages, sp=read.spine,
                               story_path=source_path, target=target)
        verdict, _verdict_why = verify_not_an_event(item)
        if previous.get("status") == "resolved":
            # v325: a wide reading re-asked to sharpen it. Only a NARROWER
            # verified answer replaces the one standing; anything else keeps
            # it — a refine can never downgrade a placed moment to a question.
            standing = _width_years(previous.get("answer"))
            sharper = resolved is not None and standing is not None and \
                (_width_years(resolved["record"]) or 0.0) < standing
            if not sharper:
                kept = dict(previous)
                kept["refine_attempted_by"] = sorted({*(previous.get("refine_attempted_by") or ()),
                                                      *([revisit["trigger"]] if revisit else [])})
                read.ledger["nodes"][node_id] = kept
                report["outcomes"]["kept_resolved"] += 1
                continue
            entry["refined_from"] = previous.get("answer")
        if resolved is not None:
            entry.update({"answer": resolved["record"], "basis": resolved["basis"],
                          "confidence": resolved["confidence"], "citations": resolved["citations"],
                          "reason": resolved["reason"]})
            try:
                entry.update({"status": "resolved", **file_resolution(
                    read.root, target, resolved, story_path=source_path, model=model, now=now,
                    prior=read.prior)})
                report["filed"] += 1
                report["bases"][resolved["basis"]] += 1
            except Exception as exc:  # noqa: BLE001
                entry.update({"status": "file_error", "error": type(exc).__name__, "detail": str(exc)[:200]})
                report.setdefault("error_samples", []).append(f"{node_id}: {str(exc)[:160]}")
        elif verdict is not None:
            # NOT AN EVENT (ADR 0037's amendment). The moment is retired
            # through the ordinary correction path, so the loop cleans this
            # up itself instead of asking the owner a question about a
            # milestone that has not happened. Both legs reach this branch:
            # `file_envelope` and the composed local run share this function.
            entry.update({"kind": verdict["kind"], "reason": verdict["reason"]})
            try:
                entry.update({"status": NOT_AN_EVENT_STATUS, **file_not_an_event(
                    read.root, target, verdict, now=now)})
                report["retracted"] += len(entry.get("retracted") or ())
            except Exception as exc:  # noqa: BLE001
                entry.update({"status": "file_error", "error": type(exc).__name__,
                              "detail": str(exc)[:200]})
                report.setdefault("error_samples", []).append(f"{node_id}: {str(exc)[:160]}")
        elif item.get("answer") is None:
            entry.update({"status": "unknown", "question": collapsed_text(item.get("question")) or None,
                          "also_resolves": [collapsed_text(x) for x in item.get("also_resolves") or ()],
                          "reason": collapsed_text(item.get("reason"))[:400]})
        else:
            entry.update({"status": "unverified", "why": why, "proposed": item.get("answer"),
                          "reason": collapsed_text(item.get("reason"))[:400]})
        if entry["status"] in ("unknown", "unverified"):
            # v325: what the model believes while the vault cannot tell. Kept
            # beside the question, never filed; the page draws it as sky.
            estimate, estimate_why = verify_estimate(item, sp=read.spine, subject=target.get("subject"))
            if estimate is None and entry["status"] == "unverified":
                # The answer failed a mechanical check, so it files nothing —
                # but it is still the model's reading of where this falls, and
                # a dot drawn over it beats a dot drawn over the whole life.
                estimate, estimate_why = verify_estimate(
                    {"estimate": {**(item.get("answer") or {}), "confidence": 0.3,
                                  "basis": [{"kind": "story", "text": (collapsed_text(item.get("reason"))
                                                                        or "the resolver's own reading, not verified")[:MAX_ESTIMATE_TEXT]}]}},
                    sp=read.spine, subject=target.get("subject"))
            if estimate is not None:
                entry["estimate"] = estimate
                report["estimates"] += 1
            else:
                entry["estimate_dropped"] = estimate_why
        if resolved is None and verdict is None:
            # v325: a handle this answer could point at a node. A dated answer
            # already retired every handle; a verdict is retracting the moment.
            binds = verify_handle_binds(item, target=target, known_nodes=read.known_nodes)
            filed_binds: list[dict] = []
            for bind in binds:
                try:
                    filed_binds.append(file_handle_bind(read.root, target, bind, story_path=source_path,
                                                        model=model, now=now))
                except Exception as exc:  # noqa: BLE001
                    entry.setdefault("bind_errors", []).append(f"{type(exc).__name__}: {str(exc)[:160]}")
            if filed_binds:
                entry["handle_binds"] = filed_binds
                report["bound"] += len(filed_binds)
        report["outcomes"][entry["status"]] += 1
        read.ledger["nodes"][node_id] = entry


def _file_deterministic(read: _Read, report: dict, deterministic: list, *, now: str) -> None:
    """A bare age where an anchor should be is arithmetic, not a question."""
    birth = read.spine["birth"]
    for source_path, target, (age, relation) in deterministic:
        resolved = {"record": age_range(birth, age, relation), "basis": "derived", "confidence": 0.9,
                    "citations": [{"doc": "spine", "quote": f"Born: {birth}"}],
                    "fact_key": f"age_{age}",
                    "reason": f"The handle is the bare age {age} ({relation or 'within'}); computed from the birth date."}
        try:
            filed = file_resolution(read.root, target, resolved, story_path=source_path,
                                    model="deterministic", now=now, prior=read.prior)
            read.ledger["nodes"][target["node_id"]] = {
                "label": target["label"], "source_path": source_path, "model": "deterministic",
                "at": now, "status": "resolved", "answer": resolved["record"], "basis": "derived",
                "confidence": 0.9, "citations": resolved["citations"], "fact_key": resolved["fact_key"],
                "reason": resolved["reason"], **filed}
            report["filed"] += 1
            report["bases"]["derived"] += 1
            report["outcomes"]["resolved"] += 1
        except Exception as exc:  # noqa: BLE001
            report["outcomes"]["file_error:" + type(exc).__name__] += 1
            report.setdefault("error_samples", []).append(f"{target['node_id']}: {str(exc)[:200]}")


def _republish(root: Path) -> None:
    import event_identity as ei  # noqa: PLC0415
    import timeline  # noqa: PLC0415

    store.rebuild_active_index(root)
    ei.rebuild_telling_manifest(root)
    timeline.publish_calculated_timeline(root)


def file_envelope(root: Path, envelope: object, *, now: str, model: str | None = None,
                  read: _Read | None = None, only_sources=None, restrict: bool = False,
                  retry_failed: bool = False, force: bool = False, deterministic: bool = True,
                  finalize: bool = True) -> dict:
    """Leg C. File the answers a plan asked for: verify, file, remember, publish.

    The passages a citation is checked against are RE-RETRIEVED here rather
    than carried across the wire: the same vault bytes retrieve the same
    passages, so a host never has to store them and can never send stale ones.

    An item whose story changed since the plan was built is refused
    (``stale_source``), as is one whose moments are no longer the moments it
    was planned for (``stale_targets``) — which is also what makes filing the
    same envelope twice file nothing the second time. A moved spine is a note
    on the ledger entry, not a refusal: the citations are verified against the
    text either way.

    Raises ``ValueError`` on an envelope that is not one; nothing is written.
    """
    if not isinstance(envelope, dict) or not isinstance(envelope.get("items"), list):
        raise ValueError("an envelope is an object with an `items` list")
    model = collapsed_text(model) or collapsed_text(envelope.get("model")) or DEFAULT_MODEL
    read = read or _Read(root, triggers=set(only_sources or ()) or _triggers_of(envelope))
    report: dict = {"filed": 0, "retracted": 0, "bound": 0, "estimates": 0,
                    "outcomes": collections.Counter(),
                    "bases": collections.Counter(), "usage": collections.Counter(),
                    "refused_items": []}
    if deterministic:
        _file_deterministic(read, report, _pending(
            read, only_sources=only_sources, retry_failed=retry_failed, force=force,
            restrict=restrict)[1], now=now)
    for raw in envelope["items"]:
        if not isinstance(raw, dict):
            report["refused_items"].append({"key": "", "reason": "item_not_an_object"})
            continue
        key = collapsed_text(raw.get("key"))
        source_path = collapsed_text(raw.get("source_path"))
        node_ids = [collapsed_text(n) for n in raw.get("node_ids") or () if collapsed_text(n)]
        identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        if collapsed_text(identity.get("source_sha256")) != _source_sha256(root, source_path):
            report["refused_items"].append({"key": key, "reason": "stale_source"})
            continue
        if collapsed_text(identity.get("targets_digest")) != _targets_digest(node_ids, read.by_node):
            report["refused_items"].append({"key": key, "reason": "stale_targets"})
            continue
        spine_changed = collapsed_text(identity.get("spine_digest")) != read.spine_digest
        rows = [read.by_node[node_id][1] for node_id in node_ids]
        for name, value in (raw.get("usage") or {}).items():
            if isinstance(value, int):
                report["usage"][name] += value
        text = raw.get("text") if isinstance(raw.get("text"), str) else ""
        if raw.get("truncated") or not text.strip():
            for target in rows:
                _unanswered(read, target, source_path=source_path, model=model, now=now,
                            spine_changed=spine_changed)
                report["outcomes"]["no_answer_returned"] += 1
            continue
        include = [collapsed_text(p) for p in (raw.get("include_paths") or ()) if collapsed_text(p)]
        _absorb(read, report, rows, text=text, story=_story_text(root, source_path),
                passages={d["doc_id"]: d for d in _retrieve(read.fts, rows, source_path, include_paths=include)},
                source_path=source_path, model=model, now=now, spine_changed=spine_changed)
    if finalize:
        save_ledger(root, read.ledger)
        if report["filed"] or report["retracted"] or report["bound"] or report["estimates"]:
            # A bind moves the vault as a filing does (an edge the fold can now
            # follow); an estimate moves the page (a dot that now floats where
            # it probably belongs). Both republish.
            # A retraction moves the vault exactly as a filing does — it is
            # how a retired non-event leaves the page — so it republishes.
            _republish(root)
    remaining, remaining_deterministic = _pending(read)
    report["outcomes"] = dict(report["outcomes"])
    report["bases"] = dict(report["bases"])
    report["usage"] = dict(report["usage"])
    report["remaining_events"] = sum(len(rows) for _s, rows in remaining)
    report["remaining_sources"] = len(remaining)
    report["complete"] = not report["remaining_events"] and not remaining_deterministic
    report["open_questions"] = open_questions(read.ledger)[:25]
    return report


def _triggers_of(envelope: object) -> set[str]:
    """v325. The stories an envelope was planned FROM: its own trigger items and
    every story a re-opened item carries passages of. Leg C reads them back so
    the filing knows which moments were revisits without a second argument."""
    out: set[str] = set()
    items = envelope.get("items") if isinstance(envelope, dict) else None
    for raw in items or ():
        if not isinstance(raw, dict):
            continue
        if raw.get("trigger") and collapsed_text(raw.get("source_path")):
            out.add(collapsed_text(raw.get("source_path")))
        for path in raw.get("include_paths") or ():
            if collapsed_text(path):
                out.add(collapsed_text(path))
    return out


def adopt_proposals_as_estimates(read: "_Read", *, sp: dict) -> int:
    """v325. Every ``unverified`` ledger row whose refused proposal parses becomes
    that row's estimate, with no model call: the answer failed a mechanical
    check and files nothing, but it is still the model's reading of where the
    moment falls, and a dot over it beats a dot over the whole life. Returns
    how many rows gained an estimate; the caller saves the ledger."""
    adopted = 0
    for node_id, row in (read.ledger.get("nodes") or {}).items():
        if not isinstance(row, dict) or row.get("status") != "unverified" or isinstance(row.get("estimate"), dict):
            continue
        proposed = row.get("proposed")
        if not isinstance(proposed, dict):
            continue
        known = read.by_node.get(node_id)
        estimate, _why = verify_estimate({"estimate": {
            **proposed, "confidence": 0.3,
            "basis": [{"kind": "story", "text": (collapsed_text(row.get("reason"))
                                                 or "the resolver's own reading, not verified")[:MAX_ESTIMATE_TEXT]}]}},
            sp=sp, subject=known[1].get("subject") if known else None)
        if estimate is not None:
            row["estimate"] = estimate
            row.pop("estimate_dropped", None)
            adopted += 1
    return adopted


def resolve_vault(root: Path, *, model: str, execute: bool, limit: int, concurrency: int,
                  only_sources: set[str] | None, force: bool, now: str, retry_failed: bool = False,
                  estimate_missing: bool = False) -> dict:
    """The local run: the two legs composed in one process, with the cache between.

    Round 1 plans one item per pending story and buys it; round 2 re-asks, in
    chunks, the moments round 1 came back silent about. Both rounds are plans
    and both are filed through `file_envelope`, so a host that runs the legs
    separately gets exactly what the local run gets.
    """
    read = _Read(root, triggers=only_sources)
    adopted = adopt_proposals_as_estimates(read, sp=read.spine) if estimate_missing else 0
    plan = plan_items(root, limit=max(1, limit), only_sources=only_sources, retry_failed=retry_failed,
                      force=force, model=model, read=read, restrict=True, estimate_missing=estimate_missing)
    report: dict = {"model": model, "execute": execute, "sources_with_targets": len(read.targets),
                    "sources_pending": plan["pending_sources"], "events_pending": plan["pending_events"],
                    "deterministic_age_handles": plan["deterministic_pending"],
                    "revisits": len(read.revisit), "estimates_adopted": adopted,
                    "selected": min(limit, plan["pending_sources"]),
                    "outcomes": collections.Counter(), "usage": collections.Counter(),
                    "filed": 0, "retracted": 0, "bound": 0, "estimates": 0, "errors": 0,
                    "bases": collections.Counter()}

    def flatten() -> dict:
        report["outcomes"] = dict(report["outcomes"])
        report["usage"] = dict(report["usage"])
        report["bases"] = dict(report["bases"])
        return report

    if not execute:
        if adopted:
            save_ledger(root, read.ledger)
            _republish(root)
        if plan["items"]:
            item = plan["items"][0]
            rows = [read.by_node[n][1] for n in item["node_ids"] if n in read.by_node]
            report["sample_prompt_chars"] = len(item["prompt"])
            report["sample_source"] = item["source_path"]
            report["sample_passages"] = [d["doc_id"] for d in _retrieve(read.fts, rows, item["source_path"])]
        return flatten()

    complete = make_completer(model)

    def buy(item: dict) -> dict:
        """One purchase, durable before anything reads it; a rerun never buys twice."""
        key = item["key"]
        answered = {name: item[name] for name in ("key", "source_path", "node_ids", "identity")}
        answered.update({name: item[name] for name in ("include_paths", "trigger") if name in item})
        cached = _json(_response_path(root, key), None)
        # A saved response is reused only when it is a usable answer: a cut-off
        # or unparseable one is bought again, in a smaller chunk.
        if (isinstance(cached, dict) and isinstance(cached.get("text"), str) and cached["text"].strip()
                and not cached.get("truncated") and parse_answers(cached["text"])):
            return {**answered, "text": cached["text"], "usage": {"cached": 1}, "truncated": False}
        text, usage = complete(item["prompt"], key)
        truncated = usage.get("stop_reason") == "max_tokens" or not text.strip()
        _save_response(root, key, {"key": key, "source_path": item["source_path"], "model": model,
                                   "nodes": item["node_ids"], "usage": usage, "text": text,
                                   "truncated": truncated})
        return {**answered, "text": ("" if truncated else text), "usage": usage, "truncated": truncated}

    def fan_out(items: list[dict]) -> list[dict]:
        bought: list[dict] = []
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(buy, item) for item in items]
            for future in as_completed(futures):
                try:
                    bought.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    report["errors"] += 1
                    report["outcomes"]["call_error:" + type(exc).__name__] += 1
                    report.setdefault("error_samples", []).append(str(exc)[:200])
        return bought

    def file_round(round_plan: dict, *, deterministic: bool) -> dict:
        envelope = {"schema_version": ENVELOPE_SCHEMA_VERSION, "model": model,
                    "items": fan_out(round_plan["items"])}
        sub = file_envelope(root, envelope, now=now, model=model, read=read, only_sources=only_sources,
                            restrict=True, retry_failed=retry_failed, force=force,
                            deterministic=deterministic, finalize=False)
        report["filed"] += sub["filed"]
        report["retracted"] += sub.get("retracted") or 0
        report["bound"] += sub.get("bound") or 0
        report["estimates"] += sub.get("estimates") or 0
        for name, value in sub["outcomes"].items():
            report["outcomes"][name] += value
        for name, value in sub["bases"].items():
            report["bases"][name] += value
        for name, value in sub["usage"].items():
            report["usage"][name] += value
        for name in ("refused_items", "error_samples"):
            if sub.get(name):
                report.setdefault(name, []).extend(sub[name])
        return sub

    first = file_round(plan, deterministic=True)
    report["round1_missing"] = first["outcomes"].get("no_answer_returned", 0)
    if plan["items"]:
        # Round 2: only the moments round 1 came back silent about, in chunks
        # of CHUNK, and only within the stories round 1 actually asked about.
        again = plan_items(root, limit=_UNBOUNDED, only_sources={i["source_path"] for i in plan["items"]},
                           retry_failed=retry_failed, model=model, read=read, restrict=True,
                           unanswered_only=True)
        if again["items"]:
            file_round(again, deterministic=False)
    save_ledger(root, read.ledger)
    if report["filed"] or report["retracted"] or report["bound"] or report["estimates"] or adopted:
        _republish(root)
    report["open_questions"] = open_questions(read.ledger)[:25]
    return flatten()


def _query(row: dict) -> str:
    """One moment's retrieval query: its telling's words and its handles."""
    event = row["event"]
    query = " ".join(str(event.get(k) or "") for k in ("title", "description", "when_hint", "anchor"))
    return query + " " + " ".join(a for h in row["handles"] for a in h.get("anchors") or [])


def _retrieve(fts: Index, rows: list[dict], source_path: str, *, include_paths=()) -> list[dict]:
    """The passages a prompt carries. v325: the stories in ``include_paths`` — the
    ones that re-opened these moments — come FIRST and are never squeezed out
    by the cap, matched passages where the query finds any, the opening
    paragraphs otherwise, so the new evidence is in front of the model."""
    seen: dict[str, dict] = {}
    for path in include_paths:
        if not path or path == source_path:
            continue
        # The whole message, in its own order: a conversation turn is short,
        # and the paragraph that carries the date is often the one no query
        # term reaches ("Death • 3 Sources / 4 April 1996"). Capped so a long
        # pasted document cannot take the prompt over.
        whole = [d for d in fts.docs.values() if d.get("path") == path][:INCLUDE_PASSAGE_CAP]
        for doc in whole:
            seen.setdefault(doc["doc_id"], doc)
    for row in rows:
        for doc in fts.search(_query(row), exclude_path=source_path):
            seen.setdefault(doc["doc_id"], doc)
        if len(seen) >= RETRIEVE_CAP:
            break
    return list(seen.values())[:RETRIEVE_CAP]


def answer_questions(root: Path, questions: list[dict], *, model: str) -> list[dict]:
    """Eval mode: free questions with expected answers; returns graded rows."""
    import temporal_publication as pub  # noqa: PLC0415

    projection = pub.read_projection(root) or {}
    sp = spine(root, projection)
    fts = Index(story_documents(root) + fact_documents(root, projection))
    complete = make_completer(model)
    graded = []
    for question in questions:
        passages = fts.search(question["question"], k=RETRIEVE_CAP)
        rows = [{"node_id": "q", "label": question["question"], "subject": "self", "handles": [],
                 "event": {"title": question["question"], "description": question.get("hint", "")}}]
        prompt = build_prompt(source_path="(question)", story=question["question"], rows=rows, sp=sp, passages=passages)
        text, usage = complete(prompt, _digest(question["question"])[7:39])
        items = parse_answers(text)
        item = items[0] if items else {}
        resolved, why = verify(item, story=question["question"], passages={d["doc_id"]: d for d in passages}, sp=sp)
        got = (resolved or {}).get("record") or {}
        exp = question.get("expected") or {}
        overlap = bool(got) and (got.get("earliest") or "") <= (exp.get("latest") or "9999") and (exp.get("earliest") or "") <= (got.get("latest") or "9999")
        exact = bool(got) and got.get("earliest") == exp.get("earliest") and got.get("latest") == exp.get("latest")
        graded.append({"question": question["question"], "expected": exp, "got": {k: got.get(k) for k in ("earliest", "latest", "best")},
                       "basis": (resolved or {}).get("basis"), "verified": resolved is not None, "why": why,
                       "overlap": overlap, "exact": exact, "reason": collapsed_text(item.get("reason"))[:200],
                       "citations": (resolved or {}).get("citations", [])[:2], "usage": usage})
    return graded


def refile_from_ledger(root: Path, *, now: str, only_sources: set[str] | None = None) -> dict:
    """Re-file every ledger answer without a model call; then publish."""
    import event_identity as ei  # noqa: PLC0415
    import temporal_publication as pub  # noqa: PLC0415
    import timeline  # noqa: PLC0415

    projection = pub.read_projection(root) or {}
    index = store.fold_active_index(root)
    ledger = load_ledger(root)
    by_node = {t["node_id"]: (s, t) for s, rows in targets(root, projection, index).items() for t in rows}
    prior = prior_resolver_claims(index)
    report = collections.Counter()
    for node_id, entry in ledger["nodes"].items():
        if entry.get("status") not in ("resolved", "file_error") or not entry.get("answer"):
            report["skipped"] += 1
            continue
        if only_sources and entry.get("source_path") not in only_sources:
            report["skipped"] += 1
            continue
        found = by_node.get(node_id)
        if found is None:
            report["target_gone"] += 1
            continue
        source_path, target = found
        resolved = {"record": entry["answer"], "basis": entry.get("basis") or "inferred",
                    "confidence": entry.get("confidence") or 0.5, "citations": entry.get("citations") or [],
                    "fact_key": entry.get("fact_key") or "unspecified", "reason": entry.get("reason") or ""}
        try:
            filed = file_resolution(root, target, resolved, story_path=source_path, model=entry.get("model") or "unknown", now=now, prior=prior)
            entry.update({"status": "resolved", **filed}); entry.pop("error", None); entry.pop("detail", None)
            report["refiled"] += 1
        except Exception as exc:  # noqa: BLE001
            entry.update({"status": "file_error", "error": type(exc).__name__, "detail": str(exc)[:200]})
            report["file_error"] += 1
            report[f"err:{str(exc)[:80]}"] += 1
    save_ledger(root, ledger)
    store.rebuild_active_index(root)
    ei.rebuild_telling_manifest(root)
    timeline.publish_calculated_timeline(root)
    return dict(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="call the model and file verified answers")
    parser.add_argument("--model", default=None, help=f"model id (default {DEFAULT_MODEL}); with --from-response, overrides the envelope's own")
    parser.add_argument("--limit", type=int, default=None, help="items per plan (default 1) / sources per local run (default 20)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--force", action="store_true", help="re-resolve nodes already in the ledger")
    parser.add_argument("--retry-failed", action="store_true", help="re-verify unverified, unanswered and unfiled nodes (cached responses cost nothing)")
    parser.add_argument("--estimate-missing", action="store_true",
                        help="v325: also ask every settled unknown that has no estimate yet for one (one-time backfill)")
    parser.add_argument("--eval", type=Path, help="JSON list of {question, expected:{earliest,latest}, hint}")
    parser.add_argument("--refile", action="store_true", help="re-file ledger answers without a model call, then publish")
    parser.add_argument("--bind-restatements", action="store_true",
                        help="v333: file every unplaced moment whose normalized label and subject already name a "
                             "PLACED node as one `same` binding, then publish; no model call "
                             "(RESTATEMENT_IS_NOT_A_QUESTION)")
    # The two legs a host runs separately (ADR 0037). --plan reads and writes
    # nothing under the vault; --from-response files an envelope of answers
    # exactly as the local --execute run files its own.
    parser.add_argument("--plan", action="store_true", help="write the prompts a host should buy to --out; touches nothing in the vault")
    parser.add_argument("--out", type=Path, help="where --plan writes its JSON (must be outside the vault root)")
    parser.add_argument("--from-response", type=Path, help="file the answers in a response envelope a host bought")
    args = parser.parse_args()
    root = args.vault_root.resolve()
    os.environ.setdefault("LIFEHUG_VAULT_ROOT", str(root))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    model = args.model or DEFAULT_MODEL
    limit = args.limit if args.limit is not None else (1 if args.plan else 20)
    if args.plan:
        if args.out is None:
            parser.error("--plan writes a file: pass --out")
        plan = plan_items(root, limit=limit, only_sources=set(args.source) or None,
                          retry_failed=args.retry_failed, model=model, estimate_missing=args.estimate_missing)
        try:
            written = write_plan(plan, args.out, vault_root=root)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({**{k: v for k, v in plan.items() if k != "items"},
                          "out": str(written), "items": len(plan["items"]),
                          "keys": [item["key"] for item in plan["items"]]},
                         indent=1, ensure_ascii=False))
        return 0
    if args.from_response:
        try:
            report = file_envelope(root, _json(args.from_response, None), now=now, model=args.model)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
        return 0
    if args.refile:
        print(json.dumps(refile_from_ledger(root, now=now, only_sources=set(args.source) or None), indent=1))
        return 0
    if args.bind_restatements:
        print(json.dumps(file_same_as(root, now=now), indent=1, ensure_ascii=False))
        return 0
    if args.eval:
        graded = answer_questions(root, _json(args.eval, []), model=model)
        print(json.dumps(graded, indent=1, ensure_ascii=False))
        total = len(graded)
        print(f"\nEVAL: {sum(g['overlap'] for g in graded)}/{total} overlap, {sum(g['exact'] for g in graded)}/{total} exact, "
              f"{sum(g['verified'] for g in graded)}/{total} verified")
        return 0
    report = resolve_vault(root, model=model, execute=args.execute, limit=limit, concurrency=args.concurrency,
                           only_sources=set(args.source) or None, force=args.force, now=now,
                           retry_failed=args.retry_failed, estimate_missing=args.estimate_missing)
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
