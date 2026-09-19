#!/usr/bin/env python3
"""The resolver: answer "when did this happen?" from everything the vault holds.

The extraction layer turns a story into events and free-text handles ("the
founding of the company", "18"). Until now the only path from a handle to a
date was a mechanical join — an exact label, an exact quote, a candidate list
built by keyword rules — and every failed join became a question for the
owner. The owner's own reading of that page: *if you can answer this from the
repo, so should the system, and once answered it must never be asked again.*

So this module does what a careful assistant does with the same question:

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
   claim under extractor ``resolver/rule:1`` whose evidence is the citations —
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
LEDGER_RELATIVE = Path("state") / "resolver" / "resolutions.json"
RESPONSES_RELATIVE = Path("state") / "resolver" / "responses"
MAX_SOURCE_CHARS = 7000
MAX_PASSAGE_CHARS = 700
RETRIEVE_PER_EVENT = 6
RETRIEVE_CAP = 18
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
    """The facts every question is read against: birth, stays, tenures, dated landmarks."""
    profile = {}
    try:
        from lifehug_core import load_config  # noqa: PLC0415
        profile = load_config() or {}
    except Exception:  # noqa: BLE001
        profile = {}
    from temporal_timeline import is_owner_reference_only  # noqa: PLC0415

    owner_names = {_norm(profile.get(k)) for k in ("name", "full_name") if profile.get(k)}
    owner_names |= {n.split()[0] for n in list(owner_names) if n}

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
        self.db.execute("CREATE VIRTUAL TABLE passages USING fts5(doc_id UNINDEXED, title, body)")
        self.db.executemany(
            "INSERT INTO passages(doc_id, title, body) VALUES (?, ?, ?)",
            [(d["doc_id"], d["title"], d["text"]) for d in docs],
        )
        self.db.commit()

    @staticmethod
    def terms(text: object) -> list[str]:
        seen: list[str] = []
        for token in _TOKEN_RE.findall(_norm(text)):
            if token not in _STOP and token not in seen:
                seen.append(token)
        return seen

    def search(self, text: object, *, k: int = RETRIEVE_PER_EVENT, exclude_path: str = "") -> list[dict]:
        terms = self.terms(text)
        if not terms:
            return []
        query = " OR ".join(f'"{term}"' for term in terms[:24])
        try:
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


def targets(root: Path, projection: dict, index: dict, *, scopes=("owner",)) -> dict[str, list[dict]]:
    """``source_path -> [target]`` for every unplaced node of the given scopes."""
    import classifier_claims as ccl  # noqa: PLC0415
    import event_identity as ei  # noqa: PLC0415

    claims = {row.get("claim_id"): row for row in index.get("claims") or ()}
    events = _classification_events(root)
    revisions: dict[str, str | None] = {}
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for node in projection.get("nodes") or ():
        if node.get("usable_placement") or node.get("node_kind") == "period":
            continue
        if node.get("occurrence_subject_scope") not in scopes:
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
        by_source[story_path].append({
            "node_id": node["node_id"], "label": collapsed_text(node.get("label")),
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
  "also_resolves": ["<other node_ids from this list the same answer settles>"]
}}
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


def build_prompt(*, source_path: str, story: str, rows: list[dict], sp: dict, passages: list[dict]) -> str:
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


def verify(item: dict, *, story: str, passages: dict[str, dict], sp: dict, story_path: str = "") -> tuple[dict | None, str]:
    """``(normalized answer, reason)``; the answer is ``None`` when it did not verify."""
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
    if target.get("telling_ref"):
        extractor = ei.declare_tellings(
            extractor, telling_keys={claim["claim_id"]: target["telling_ref"]},
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


def resolve_vault(root: Path, *, model: str, execute: bool, limit: int, concurrency: int,
                  only_sources: set[str] | None, force: bool, now: str, retry_failed: bool = False) -> dict:
    import event_identity as ei  # noqa: PLC0415
    import temporal_publication as pub  # noqa: PLC0415

    projection = pub.read_projection(root) or {}
    index = store.fold_active_index(root)
    ledger = load_ledger(root)
    sp = spine(root, projection)
    docs = story_documents(root) + fact_documents(root, projection)
    fts = Index(docs)
    all_targets = targets(root, projection, index)
    prior = prior_resolver_claims(index)
    pending: list[tuple[str, list[dict]]] = []
    deterministic: list[tuple[str, dict, int]] = []
    for source_path in sorted(all_targets):
        if only_sources and source_path not in only_sources:
            continue
        rows = []
        for r in all_targets[source_path]:
            status = (ledger["nodes"].get(r["node_id"]) or {}).get("status")
            settled = ("resolved", "unknown") if retry_failed else ("resolved", "unknown", *RETRY_STATUSES)
            if not force and status in settled:
                continue
            # A bare age written where an anchor should be is arithmetic against
            # the birth date; it needs no model and no question.
            aged = [(age_from_handle(a), h.get("relation")) for h in r["handles"] for a in (h.get("anchors") or ())]
            aged = [(a, rel) for a, rel in aged if a is not None]
            if aged and sp["birth"] and len({a for a, _ in aged}) == 1 and age_range(sp["birth"], aged[0][0], aged[0][1]):
                deterministic.append((source_path, r, aged[0]))
            else:
                rows.append(r)
        if rows:
            pending.append((source_path, rows))
    report = {"model": model, "execute": execute, "sources_with_targets": len(all_targets),
              "sources_pending": len(pending), "events_pending": sum(len(r) for _s, r in pending),
              "deterministic_age_handles": len(deterministic),
              "selected": min(limit, len(pending)), "outcomes": collections.Counter(), "usage": collections.Counter(),
              "filed": 0, "errors": 0, "bases": collections.Counter()}
    if execute:
        for source_path, target, (age, relation) in deterministic:
            resolved = {"record": age_range(sp["birth"], age, relation), "basis": "derived", "confidence": 0.9,
                        "citations": [{"doc": "spine", "quote": f"Born: {sp['birth']}"}],
                        "fact_key": f"age_{age}", "reason": f"The handle is the bare age {age} ({relation or 'within'}); computed from the birth date."}
            try:
                filed = file_resolution(root, target, resolved, story_path=source_path, model="deterministic", now=now, prior=prior)
                ledger["nodes"][target["node_id"]] = {"label": target["label"], "source_path": source_path, "model": "deterministic",
                                                     "at": now, "status": "resolved", "answer": resolved["record"], "basis": "derived",
                                                     "confidence": 0.9, "citations": resolved["citations"], "fact_key": resolved["fact_key"],
                                                     "reason": resolved["reason"], **filed}
                report["filed"] += 1; report["bases"]["derived"] += 1; report["outcomes"]["resolved"] += 1
            except Exception as exc:  # noqa: BLE001
                report["outcomes"]["file_error:" + type(exc).__name__] += 1
                report.setdefault("error_samples", []).append(f"{target['node_id']}: {str(exc)[:200]}")
    pending = pending[:limit]
    if not execute:
        sample = pending[:1]
        if sample:
            source_path, rows = sample[0]
            passages = _retrieve(fts, rows, source_path)
            report["sample_prompt_chars"] = len(build_prompt(
                source_path=source_path, story=_story_text(root, source_path), rows=rows, sp=sp, passages=passages))
            report["sample_source"] = source_path
            report["sample_passages"] = [d["doc_id"] for d in passages]
        report["outcomes"] = dict(report["outcomes"]); report["usage"] = dict(report["usage"]); report["bases"] = dict(report["bases"])
        return report

    complete = make_completer(model)
    CHUNK = 4

    def prepare(source_path: str, rows: list[dict]):
        story = _story_text(root, source_path)
        passages = _retrieve(fts, rows, source_path)
        prompt = build_prompt(source_path=source_path, story=story, rows=rows, sp=sp, passages=passages)
        key = _digest({"source": source_path, "nodes": [r["node_id"] for r in rows], "model": model})[7:39]
        return (source_path, rows, story, {d["doc_id"]: d for d in passages}, prompt, key)

    def work(item):
        source_path, rows, story, passages, prompt, key = item
        cached = _json(_response_path(root, key), None)
        # A saved response is reused only when it is a usable answer: a cut-off
        # or unparseable one is bought again, in a smaller chunk.
        if (isinstance(cached, dict) and isinstance(cached.get("text"), str) and cached["text"].strip()
                and not cached.get("truncated") and parse_answers(cached["text"])):
            return source_path, rows, story, passages, cached["text"], {"cached": 1}
        text, usage = complete(prompt, key)
        truncated = usage.get("stop_reason") == "max_tokens" or not text.strip()
        _save_response(root, key, {"key": key, "source_path": source_path, "model": model,
                                   "nodes": [r["node_id"] for r in rows], "usage": usage, "text": text,
                                   "truncated": truncated})
        return source_path, rows, story, passages, ("" if truncated else text), usage

    def fan_out(items):
        results = []
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(work, item) for item in items]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    report["errors"] += 1
                    report["outcomes"]["call_error:" + type(exc).__name__] += 1
                    report.setdefault("error_samples", []).append(str(exc)[:200])
        return results

    def absorb(results) -> list[tuple[str, dict]]:
        """File what verified; return the (source, target) pairs that got no row."""
        missing: list[tuple[str, dict]] = []
        for source_path, rows, story, passages, text, usage in results:
            for k, v in usage.items():
                if isinstance(v, int):
                    report["usage"][k] += v
            answers = {collapsed_text(a.get("node_id")): a for a in parse_answers(text)}
            for target in rows:
                node_id = target["node_id"]
                item = answers.get(node_id)
                if item is None:
                    missing.append((source_path, target))
                    continue
                entry = {"label": target["label"], "source_path": source_path, "model": model, "at": now,
                         "fact_key": collapsed_text(item.get("fact_key")) or None}
                resolved, why = verify(item, story=story, passages=passages, sp=sp, story_path=source_path)
                if resolved is not None:
                    entry.update({"answer": resolved["record"], "basis": resolved["basis"],
                                  "confidence": resolved["confidence"], "citations": resolved["citations"],
                                  "reason": resolved["reason"]})
                    try:
                        entry.update({"status": "resolved", **file_resolution(
                            root, target, resolved, story_path=source_path, model=model, now=now, prior=prior)})
                        report["filed"] += 1
                        report["bases"][resolved["basis"]] += 1
                    except Exception as exc:  # noqa: BLE001
                        entry.update({"status": "file_error", "error": type(exc).__name__, "detail": str(exc)[:200]})
                        report.setdefault("error_samples", []).append(f"{node_id}: {str(exc)[:160]}")
                elif item.get("answer") is None:
                    entry.update({"status": "unknown", "question": collapsed_text(item.get("question")) or None,
                                  "also_resolves": [collapsed_text(x) for x in item.get("also_resolves") or ()],
                                  "reason": collapsed_text(item.get("reason"))[:400]})
                else:
                    entry.update({"status": "unverified", "why": why, "proposed": item.get("answer"),
                                  "reason": collapsed_text(item.get("reason"))[:400]})
                report["outcomes"][entry["status"]] += 1
                ledger["nodes"][node_id] = entry
        return missing

    # Round 1: one call per story. Round 2: the events that came back without a
    # row (a truncated or partial answer) are re-asked in small chunks so a long
    # story cannot starve its own moments.
    missing = absorb(fan_out([prepare(s, r) for s, r in pending]))
    report["round1_missing"] = len(missing)
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for source_path, target in missing:
        by_source[source_path].append(target)
    round2 = []
    for source_path, rows in by_source.items():
        for start in range(0, len(rows), CHUNK):
            round2.append(prepare(source_path, rows[start:start + CHUNK]))
    still_missing = absorb(fan_out(round2)) if round2 else []
    for source_path, target in still_missing:
        ledger["nodes"][target["node_id"]] = {"label": target["label"], "source_path": source_path, "model": model,
                                             "at": now, "status": "no_answer_returned"}
        report["outcomes"]["no_answer_returned"] += 1
    save_ledger(root, ledger)
    if report["filed"]:
        store.rebuild_active_index(root)
        ei.rebuild_telling_manifest(root)
        import timeline  # noqa: PLC0415
        timeline.publish_calculated_timeline(root)
    report["outcomes"] = dict(report["outcomes"]); report["usage"] = dict(report["usage"]); report["bases"] = dict(report["bases"])
    report["open_questions"] = open_questions(ledger)[:25]
    return report


def _retrieve(fts: Index, rows: list[dict], source_path: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        event = row["event"]
        query = " ".join(str(event.get(k) or "") for k in ("title", "description", "when_hint", "anchor"))
        query += " " + " ".join(a for h in row["handles"] for a in h.get("anchors") or [])
        for doc in fts.search(query, exclude_path=source_path):
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
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=20, help="sources per invocation")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--force", action="store_true", help="re-resolve nodes already in the ledger")
    parser.add_argument("--retry-failed", action="store_true", help="re-verify unverified, unanswered and unfiled nodes (cached responses cost nothing)")
    parser.add_argument("--eval", type=Path, help="JSON list of {question, expected:{earliest,latest}, hint}")
    parser.add_argument("--refile", action="store_true", help="re-file ledger answers without a model call, then publish")
    args = parser.parse_args()
    root = args.vault_root.resolve()
    os.environ.setdefault("LIFEHUG_VAULT_ROOT", str(root))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if args.refile:
        print(json.dumps(refile_from_ledger(root, now=now, only_sources=set(args.source) or None), indent=1))
        return 0
    if args.eval:
        graded = answer_questions(root, _json(args.eval, []), model=args.model)
        print(json.dumps(graded, indent=1, ensure_ascii=False))
        total = len(graded)
        print(f"\nEVAL: {sum(g['overlap'] for g in graded)}/{total} overlap, {sum(g['exact'] for g in graded)}/{total} exact, "
              f"{sum(g['verified'] for g in graded)}/{total} verified")
        return 0
    report = resolve_vault(root, model=args.model, execute=args.execute, limit=args.limit, concurrency=args.concurrency,
                           only_sources=set(args.source) or None, force=args.force, now=now,
                           retry_failed=args.retry_failed)
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
