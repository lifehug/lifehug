#!/usr/bin/env python3
"""Runtime authority for the registered Landmarks Interaction (v199).

The always-present dating question set is the sixth child of Conversation
(`interactions/README.md` § "The child-interaction paradigm"). Its one goal:
**collect the small set of dated facts that makes every other memory cheap to
place** — and never feel like a form.

Everything here is pure — no writes, no model calls, no lifecycle. The
question set, the specificity ladders, the stage, the closed validator and the
lints are all deterministic functions over data the caller supplies, exactly
as `timeline_interaction` and `arc_walk` are.

The mechanic these answers enable has a name: **cross-dating** — dating an
undated sequence by matching it against an already-dated one
(`system/research/go-deep.md` §7's terminology table). The landmarks are the
dated sequence; every other memory is the undated one.

**Naming** (owner-set, 2026-08-23): **Landmarks** is the product word AND the
package/module/CLI name, so there is one name from the surface down to this
file. `anchor` keeps the meaning it already had in code — the *derived* index
a landmark's date becomes once it can bound something (`timeline.anchor_index`,
`basis: "anchor"`, `chronology.from_anchor`). A landmark is the question and
the answer; an anchor is what the answer turns into. The join is
:func:`anchors_from_landmarks`.

Why this exists (`system/research/landmarks.md` §3.7): the arithmetic was
built before the inputs. `chronology.from_age` needs a birthday that nothing
ever supplied, and `PLAYBOOK_STEPS` rungs 5-6 are marked `needs_anchor` over
an anchor index that is nearly always empty. This Interaction fills it.

Three owner rulings shape the surface (2026-08-23):

1. Onboarding asks in **generalities** — "do you remember where you lived?
   where was that?" — and takes a skip without comment.
2. A landmark that is unanswered **or below target specificity** stays
   **open on the Timeline**, forever, answerable at any time. Never in the
   daily queue, never a reminder, never a nag. An open landmark is a normal
   resting state, not a debt.
3. A vague answer is an **answer**. "The eighties, somewhere in Ohio" bounds
   things already; the ladder exists because *more* would unlock more, not
   because less is a failure.

Contract: ``docs/pr-specs/landmarks.md``.
Research: ``system/research/landmarks.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml  # noqa: E402


class LandmarkInteractionError(ValueError):
    """A domain, rung, stage or landmark record is unusable."""


# --------------------------------------------------------------------------
# The question set (interactions/landmarks/questions.yaml)
# --------------------------------------------------------------------------

QUESTIONS_FILE = "questions.yaml"

#: Every field a domain row carries, and how it is coerced.
_BOOL_FIELDS = ("onboarding", "chain", "sensitive")
_LIST_FIELDS = ("ladder", "unlocks")


def _questions_path(framework_root: str | Path | None = None) -> Path:
    root = Path(framework_root) / "interactions" if framework_root else INTERACTIONS_DIR
    return Path(root) / "landmarks" / QUESTIONS_FILE


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1"}


def _as_tuple(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    return tuple(part.strip() for part in text.split("|") if part.strip())


def load_questions(framework_root: str | Path | None = None) -> tuple[dict, ...]:
    """The ordered question set as rows.

    Each row: ``{domain, order, onboarding, ask, ladder, complete_at,
    precision, unlocks, chain, sensitive, why}``. Order is the file's
    ``domains`` line, not dictionary order, so the set's sequence is one
    edit in one place.
    """
    raw = _parse_simple_yaml(_questions_path(framework_root))
    if not raw:
        raise LandmarkInteractionError("landmarks/questions.yaml is missing or empty")
    domains = _as_tuple(raw.get("domains"))
    if not domains:
        raise LandmarkInteractionError("landmarks/questions.yaml declares no domains")
    rows: list[dict] = []
    for index, domain in enumerate(domains, start=1):
        row: dict = {"domain": domain, "order": index}
        for field in ("ask", "complete_at", "precision", "why"):
            row[field] = str(raw.get(f"{domain}.{field}") or "").strip()
        for field in _BOOL_FIELDS:
            row[field] = _as_bool(raw.get(f"{domain}.{field}"))
        for field in _LIST_FIELDS:
            row[field] = _as_tuple(raw.get(f"{domain}.{field}"))
        if not row["ask"] or not row["ladder"]:
            raise LandmarkInteractionError(f"landmark domain {domain!r} is incomplete")
        if row["complete_at"] not in row["ladder"]:
            raise LandmarkInteractionError(
                f"landmark domain {domain!r} completes at {row['complete_at']!r}, "
                "which is not on its ladder"
            )
        rows.append(row)
    return tuple(rows)


def domain_row(domain: object, *, framework_root: str | Path | None = None) -> dict:
    """One domain's row, by key. Raises on an unknown domain — closed set."""
    key = str(domain or "").strip()
    for row in load_questions(framework_root):
        if row["domain"] == key:
            return row
    raise LandmarkInteractionError(f"unknown landmark domain: {key!r}")


def onboarding_domains(framework_root: str | Path | None = None) -> tuple[str, ...]:
    """The domains asked at onboarding, in order (owner ruling 1)."""
    return tuple(row["domain"] for row in load_questions(framework_root)
                 if row["onboarding"])


# --------------------------------------------------------------------------
# The specificity ladder (owner ruling 3)
# --------------------------------------------------------------------------

#: What each rung asks for, per domain. `{label}` is the subject when there is
#: one (a place, a school, a person); the bare form opens the domain.
RUNG_TEXTS = {
    ("birth", "year"): "What year were you born?",
    ("birth", "month"): "What month?",
    ("birth", "day"): "And the day?",
    ("residences", "city"): "Do you remember where you lived? Where was that?",
    ("residences", "address"): "Do you remember the address on {label}?",
    ("residences", "span"): "When did you move into {label}, and when did you leave?",
    ("residences", "household"): "Who else was in the house on {label}?",
    ("schools", "name"): "Which schools did you go to?",
    ("schools", "place"): "Where was {label} — what town?",
    ("schools", "grades"): "Which grades were you at {label}?",
    ("schools", "span"): "Roughly when did you start and finish at {label}?",
    ("partnerships", "happened"): "Have you ever been married, or had a long partnership?",
    ("partnerships", "who"): "Who was that?",
    ("partnerships", "year"): "Roughly what year did that begin?",
    ("partnerships", "month"): "Do you remember the month?",
    ("children", "happened"): "Do you have children?",
    ("children", "who"): "What are their names?",
    ("children", "year"): "What year was {label} born?",
    ("children", "month"): "Do you remember the month?",
    ("work", "what"): "What work have you done?",
    ("work", "where"): "Where was that?",
    ("work", "span"): "Roughly what years were you at {label}?",
    ("military", "happened"): "Did you serve?",
    ("military", "branch"): "Which branch?",
    ("military", "span"): "When did you go in, and when did you come out?",
    ("losses", "happened"): "Is there someone you have lost that belongs on this?",
    ("losses", "who"): "Who was that?",
    ("losses", "year"): "What year was that?",
}

#: A rung the person has not reached costs more to ask than one they have.
#: The ladder is walked one rung at a time, never skipped ahead.
LADDER_COST = {"city": 1, "name": 1, "what": 1, "happened": 1, "year": 1,
               "who": 2, "place": 2, "where": 2, "branch": 2, "month": 2,
               "address": 3, "grades": 3, "day": 3,
               "span": 4, "household": 5}
DEFAULT_RUNG_COST = 3


def rung_reached(entry: object, row: object) -> str | None:
    """The finest ladder rung this entry actually satisfies, or None.

    A rung is satisfied when the entry carries a non-empty value under that
    rung's key. Rungs are checked in ladder order and the walk STOPS at the
    first unsatisfied one — a person who gave a span but no address is at
    ``address``'s predecessor, because the ladder is a ladder.
    """
    if not isinstance(entry, dict) or not isinstance(row, dict):
        return None
    reached: str | None = None
    for rung in row.get("ladder") or ():
        value = entry.get(rung)
        if rung == "span":
            value = entry.get("span") or entry.get("date")
        if value in (None, "", (), [], {}):
            break
        reached = rung
    return reached


def status_for_domain(entries: object, row: object) -> str:
    """``open`` | ``partial`` | ``complete`` for one landmark domain.

    ``open``     nothing filed at all.
    ``partial``  filed, but at least one entry is below ``complete_at``.
    ``complete`` every entry has reached ``complete_at``, and — for a chain
                 domain — the person has said the list is finished.
    """
    if not isinstance(row, dict):
        raise LandmarkInteractionError("status_for_domain needs a domain row")
    rows = [e for e in (entries or ()) if isinstance(e, dict)]
    if not rows:
        return "open"
    ladder = list(row.get("ladder") or ())
    target = row.get("complete_at")
    target_index = ladder.index(target) if target in ladder else len(ladder) - 1
    for entry in rows:
        reached = rung_reached(entry, row)
        if reached is None or ladder.index(reached) < target_index:
            return "partial"
    if row.get("chain") and not any(e.get("chain_complete") for e in rows):
        return "partial"
    return "complete"


def next_rung(entries: object, row: object) -> dict | None:
    """The next thing to ask for this domain, or None when it is complete.

    Returns ``{"domain", "rung", "subject", "text", "cost"}``. The subject is
    the entry the question is about when the ladder is per-entry (a place, a
    school, a child); it is ``None`` for the domain's opening question.
    """
    if not isinstance(row, dict):
        raise LandmarkInteractionError("next_rung needs a domain row")
    domain = row["domain"]
    ladder = list(row.get("ladder") or ())
    target = row.get("complete_at")
    target_index = ladder.index(target) if target in ladder else len(ladder) - 1
    rows = [e for e in (entries or ()) if isinstance(e, dict)]
    if not rows:
        return _rung(domain, ladder[0], None)
    for entry in rows:
        reached = rung_reached(entry, row)
        index = ladder.index(reached) if reached in ladder else -1
        if index < target_index:
            return _rung(domain, ladder[index + 1], entry.get("label"))
    if row.get("chain") and not any(e.get("chain_complete") for e in rows):
        return _rung(domain, ladder[0], None, chain_more=True)
    return None


def _rung(domain: str, rung: str, subject: object, *, chain_more: bool = False) -> dict:
    label = str(subject).strip() if subject else ""
    text = RUNG_TEXTS.get((domain, rung))
    if text is None:
        raise LandmarkInteractionError(f"no rung text for {domain}.{rung}")
    if chain_more:
        text = CHAIN_MORE_TEXTS.get(domain, text)
    return {
        "domain": domain,
        "rung": rung,
        "subject": label or None,
        "text": text.format(label=label or "that one"),
        "cost": LADDER_COST.get(rung, DEFAULT_RUNG_COST),
    }


#: Walking a chain forward is a different question from opening it.
CHAIN_MORE_TEXTS = {
    "residences": "And where did you go after that?",
    "schools": "Was there another school after that?",
    "work": "And after that?",
}


# --------------------------------------------------------------------------
# The landmark ledger the host renders (owner ruling 2)
# --------------------------------------------------------------------------

LANDMARK_STATUSES = ("open", "partial", "complete")


def landmark_rows(landmarks: object, *, keystone_domains: object = (),
                  framework_root: str | Path | None = None) -> tuple[dict, ...]:
    """Every domain with its status and its next question.

    This is what a host renders: ONLY the rows whose status is not
    ``complete`` are offerable, and each carries the exact next question so
    the surface never has to invent one. ``keystone: true`` marks the domain
    holding the highest-leverage anchor — the star moves with it.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    starred = {str(k).strip() for k in (keystone_domains or ()) if str(k).strip()}
    rows: list[dict] = []
    for row in load_questions(framework_root):
        entries = filed.get(row["domain"]) or ()
        status = status_for_domain(entries, row)
        question = next_rung(entries, row)
        rows.append({
            "domain": row["domain"],
            "order": row["order"],
            "status": status,
            "onboarding": row["onboarding"],
            "sensitive": row["sensitive"],
            "precision": row["precision"],
            "unlocks": row["unlocks"],
            "count": len([e for e in entries if isinstance(e, dict)]),
            "next": question,
            "keystone": row["domain"] in starred,
        })
    return tuple(rows)


def open_landmarks(rows: object) -> tuple[dict, ...]:
    """The offerable rows, keystone first, then by ladder cost, then order.

    Complete domains never appear. Sensitive domains sort last within their
    cost — offered, never pressed (`landmarks.md` §5.2).
    """
    offerable = [r for r in (rows or ())
                 if isinstance(r, dict) and r.get("status") != "complete"]
    offerable.sort(key=lambda r: (
        not r.get("keystone"),
        bool(r.get("sensitive")),
        int((r.get("next") or {}).get("cost") or 99),
        int(r.get("order") or 99),
    ))
    return tuple(offerable)


# --------------------------------------------------------------------------
# The stage (the caller's deterministic decision)
# --------------------------------------------------------------------------

VALID_LANDMARK_STAGES = frozenset({"open", "ask", "close"})

#: Stop rules, mirroring the timeline lane: a landmark pass is never an
#: interrogation. The knobs in interaction.yaml carry the same two numbers and
#: a test pins them equal.
MAX_ASKS = 4
STOP_AFTER_SKIPS = 2


def landmark_stage_for_session(session: object, *, user_leaving: bool = False,
                               all_settled: bool = False,
                               skip_streak: int = 0) -> str:
    """``open`` on the first turn, ``close`` when done, ``ask`` in between.

    Pure. The caller supplies the things only it can know — the router's
    departure signal, whether every offered landmark is settled, and how many
    skips in a row the person has given.
    """
    turns = _user_turns(session)
    if turns <= 0:
        return "open"
    if user_leaving or all_settled:
        return "close"
    if skip_streak >= STOP_AFTER_SKIPS or turns >= MAX_ASKS:
        return "close"
    return "ask"


def _user_turns(session: object) -> int:
    if not isinstance(session, dict):
        return 0
    turns = session.get("turns")
    if not isinstance(turns, list):
        return 0
    return sum(1 for t in turns if isinstance(t, dict) and t.get("role") == "user")


# --------------------------------------------------------------------------
# The one additive turn-output field
# --------------------------------------------------------------------------

#: Free-text fields a landmark record may carry, and their length caps. A
#: label is a name, not a story.
_TEXT_CAPS = {"label": 120, "place": 120, "subject": 120}
_RUNG_MAX_CHARS = 32


def validate_landmark(value: object, *,
                      framework_root: str | Path | None = None) -> dict | None:
    """Closed validation of the model's one additive output field.

    Accepts ``{"domain", "label", "date"?, "place"?, "subject"?,
    "chain_complete"?, "skipped"?}``. Returns the normalized record, or None
    when the value is unusable, absent, or a skip with nothing in it. The
    domain must be one the question set declares — an invented domain is
    dropped, never stored.
    """
    if not isinstance(value, dict):
        return None
    domain = str(value.get("domain") or "").strip()
    if not domain:
        return None
    try:
        row = domain_row(domain, framework_root=framework_root)
    except LandmarkInteractionError:
        return None
    if value.get("skipped"):
        return {"domain": domain, "skipped": True}
    record: dict = {"domain": domain}
    for field, cap in _TEXT_CAPS.items():
        text = value.get(field)
        if isinstance(text, str) and text.strip():
            record[field] = text.strip()[:cap]
    date = _normalized_date(value.get("date"))
    if date is not None:
        record["date"] = date
    span = value.get("span")
    if isinstance(span, dict):
        bounds = {}
        for bound in ("start", "end"):
            parsed = _normalized_date(span.get(bound))
            if parsed is not None:
                bounds[bound] = parsed
        if bounds:
            record["span"] = bounds
    for rung in row["ladder"]:
        if rung in ("span", "date"):
            continue
        raw = value.get(rung)
        if isinstance(raw, str) and raw.strip():
            record[rung] = raw.strip()[:_RUNG_MAX_CHARS * 4]
        elif raw is True:
            record[rung] = True
    if value.get("chain_complete"):
        record["chain_complete"] = True
    # A record that carries nothing but its domain is not a landmark.
    if len(record) == 1:
        return None
    return record


def _normalized_date(value: object) -> dict | None:
    """One date, with its bounds filled in.

    A model supplies ``best`` and rarely the bounds; a record with no
    ``earliest``/``latest`` renders as an empty string and dates nothing
    (`chronology.display_date`, `chronology.year_of`). So every landmark date
    is re-derived through `chronology.parse_edtf`, which fills the bounds from
    the EDTF expression, and the model's own granularity / confidence / basis
    are kept where it gave them.
    """
    parsed = chrono.from_dict(value)
    if parsed is None:
        return None
    if parsed.earliest or parsed.latest:
        return parsed.to_dict()
    rebuilt = chrono.parse_edtf(parsed.best, basis=parsed.basis)
    if rebuilt is None:
        return parsed.to_dict()
    supplied = value if isinstance(value, dict) else {}
    return chrono.DateRecord(
        best=rebuilt.best,
        earliest=rebuilt.earliest,
        latest=rebuilt.latest,
        granularity=supplied.get("granularity") or rebuilt.granularity,
        confidence=supplied.get("confidence") or rebuilt.confidence,
        basis=parsed.basis,
        anchors=parsed.anchors,
        provenance=parsed.provenance,
    ).to_dict()


# --------------------------------------------------------------------------
# The lints
# --------------------------------------------------------------------------

LANDMARK_LINT_CLASSES = (
    "landmark_gates.no_year_demand",
    "landmark_gates.accepts_vague",
    "landmark_gates.no_form_voice",
    "landmark_gates.one_domain_per_turn",
    "landmark_gates.never_presses_sensitive",
    # v198 (go-deep.md §4.3): a session never names a date and asks for
    # agreement. The DEFINITION is `timeline_interaction.proposes_a_date` —
    # one definition, two callers, per the recurring-defect doctrine.
    "landmark_gates.never_proposes_a_date",
)

#: Asking a person to produce a year for a MEMORY is the banned move
#: (chronology.md §6 rule 1). The birth date is the sole carve-out, and it is
#: recognized by the stage's own domain, not by phrasing.
_YEAR_DEMAND_RES = (
    re.compile(r"\bwhat year (?:was|did|were)\b", re.IGNORECASE),
    re.compile(r"\bwhich year\b", re.IGNORECASE),
    re.compile(r"\bcan you give me (?:the|a) year\b", re.IGNORECASE),
    re.compile(r"\bexact(?:ly)? what year\b", re.IGNORECASE),
)

#: Form voice — the thing this Interaction must never sound like.
_FORM_VOICE_RES = (
    re.compile(r"\bplease (?:enter|provide|complete|fill)\b", re.IGNORECASE),
    re.compile(r"\b(?:field|form|questionnaire|survey) (?:is |are )?(?:required|incomplete)\b",
               re.IGNORECASE),
    re.compile(r"\byou (?:still )?(?:need|have) to (?:answer|complete|finish)\b",
               re.IGNORECASE),
    re.compile(r"\b\d+ (?:of|out of) \d+ (?:remaining|left|to go)\b", re.IGNORECASE),
)

#: Pressing someone about a loss, or refusing a skip.
_PRESSURE_RES = (
    re.compile(r"\b(?:are you sure|surely|try (?:harder|again)|think (?:harder|back))\b",
               re.IGNORECASE),
    re.compile(r"\bI (?:really )?need (?:you to|to know)\b", re.IGNORECASE),
    re.compile(r"\bwe can'?t (?:move on|continue) (?:until|without)\b", re.IGNORECASE),
)

#: A reply that treats a coarse answer as a miss.
_REJECTS_VAGUE_RES = (
    re.compile(r"\bthat'?s (?:too )?(?:vague|not specific enough|not enough)\b",
               re.IGNORECASE),
    re.compile(r"\bI (?:need|'ll need) (?:something )?more (?:specific|precise|exact)\b",
               re.IGNORECASE),
    re.compile(r"\bcan you be more (?:specific|precise|exact)\b", re.IGNORECASE),
)

_SPAN_LIMIT = 400


def lint_landmark_reply(text: object, *, stage: str, domain: object = None,
                        sensitive: bool = False,
                        domains_named: object = ()) -> list[dict]:
    """Deterministic findings for the five ``landmark_gates.*`` classes.

    Pure — no model, no I/O. Findings share `conversation_lints.lint_turn`'s
    shape (`lint` / `detail` / `span`), exactly as
    `timeline_interaction.lint_timeline_reply` does, so one caller can merge
    both sets of findings uniformly. An unrecognized stage is treated as
    ``"ask"`` — fail toward the strictest ordinary rule.
    """
    body = text if isinstance(text, str) else ""
    if stage not in VALID_LANDMARK_STAGES:
        stage = "ask"
    findings: list[dict] = []

    def _first(patterns) -> object:
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                return match
        return None

    # The birthday is the sole carve-out (landmarks.md §2.1): it is
    # overlearned semantic knowledge, not a reconstruction.
    if str(domain or "") != "birth":
        match = _first(_YEAR_DEMAND_RES)
        if match:
            findings.append({
                "lint": "landmark_gates.no_year_demand",
                "detail": "never ask for a calendar year outright — ask what else "
                          "was true then and let the date fall out",
                "span": [match.start(), match.end()],
            })

    match = _first(_REJECTS_VAGUE_RES)
    if match:
        findings.append({
            "lint": "landmark_gates.accepts_vague",
            "detail": "a coarse answer is an answer — a decade still bounds "
                      "everything it overlaps; never ask them to sharpen it",
            "span": [match.start(), match.end()],
        })

    match = _first(_FORM_VOICE_RES)
    if match:
        findings.append({
            "lint": "landmark_gates.no_form_voice",
            "detail": "this is a conversation, not a form — no counts, no "
                      "remaining, no required fields",
            "span": [match.start(), match.end()],
        })

    named = {str(d).strip() for d in (domains_named or ()) if str(d).strip()}
    if len(named) > 1:
        findings.append({
            "lint": "landmark_gates.one_domain_per_turn",
            "detail": f"asks across {len(named)} landmark domains in one turn — "
                      "one domain per turn, or it reads as intake",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    if sensitive:
        match = _first(_PRESSURE_RES)
        if match:
            findings.append({
                "lint": "landmark_gates.never_presses_sensitive",
                "detail": "a sensitive landmark is offered, never pressed — "
                          "dating is never worth the relationship",
                "span": [match.start(), match.end()],
            })

    # go-deep.md §4.3: the shared rule, from the shared definition.
    import timeline_interaction as _ti  # noqa: PLC0415

    proposal = _ti.proposes_a_date(body)
    if proposal is not None:
        findings.append({
            "lint": "landmark_gates.never_proposes_a_date",
            "detail": "never name a date and ask them to agree — ask, bound, "
                      "and do the arithmetic (go-deep.md §4.3, Lindsay et al. "
                      "2004)",
            "span": [proposal.start(), proposal.end()],
        })
    return findings


# --------------------------------------------------------------------------
# Filing (the package names it; the host writes it)
# --------------------------------------------------------------------------

def landmark_invocation(record: object) -> list[str] | None:
    """The ``lifehug.py landmark-record`` argv that files one landmark, or None.

    One writer for the whole set: a landmark with a date, a landmark with only
    a span, and a landmark with neither (a city, a school name) all file the
    same way, and `timeline.save_landmark` merges by label so the ladder's
    later rungs land on the same entry.
    """
    if not isinstance(record, dict) or record.get("skipped"):
        return None
    domain = str(record.get("domain") or "").strip()
    if not domain:
        return None
    label = str(record.get("label") or "").strip()
    date = record.get("date")
    argv = ["landmark-record", domain]
    if label:
        argv += ["--label", label]
    for field in ("place", "subject"):
        value = str(record.get(field) or "").strip()
        if value:
            argv += [f"--{field}", value]
    edtf = chrono.to_edtf(chrono.from_dict(date)) if date else None
    if edtf:
        argv += ["--date", edtf]
    span = record.get("span") if isinstance(record.get("span"), dict) else {}
    for bound in ("start", "end"):
        value = chrono.to_edtf(chrono.from_dict(span.get(bound))) if span.get(bound) else None
        if value:
            argv += [f"--{bound}", value]
    for rung in ("city", "address", "household", "name", "grades",
                 "happened", "who", "what", "where", "branch",
                 "year", "month", "day"):
        value = record.get(rung)
        if isinstance(value, str) and value.strip():
            argv += [f"--{rung}", value.strip()]
    if record.get("chain_complete"):
        argv.append("--complete")
    return argv


# --------------------------------------------------------------------------
# Anchors: the whole point (landmarks.md §3.7)
# --------------------------------------------------------------------------

#: How each landmark domain enters `timeline.anchor_index`.
ANCHOR_KINDS = {
    "birth": "birth",
    "residences": "residence",
    "schools": "period",
    "partnerships": "landmark",
    "children": "landmark",
    "work": "period",
    "military": "period",
    "losses": "landmark",
}


def anchors_from_landmarks(landmarks: object) -> dict:
    """``{key: {label, date, kind}}`` — the filed landmarks as an anchor index.

    This is the function that makes `chronology.from_age` reachable: the
    birthday enters as ``birth``, and every dated landmark enters with the
    kind `timeline.anchor_index` already understands.

    It is also the join between the two vocabularies. The product word for the
    question set is **Landmarks**; `anchor` already names the derived index in
    code (`anchor_index`, `basis: "anchor"`, `from_anchor`). This function is
    where one becomes the other, and **cross-dating** is the name of what
    happens next (`go-deep.md` §7).
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    index: dict[str, dict] = {}
    for domain, entries in filed.items():
        kind = ANCHOR_KINDS.get(str(domain), "landmark")
        for position, entry in enumerate(entries or (), start=1):
            if not isinstance(entry, dict):
                continue
            record = _entry_date(entry)
            if record is None:
                continue
            label = str(entry.get("label") or domain).strip()
            key = "birth" if domain == "birth" else _anchor_key(domain, label, position)
            index.setdefault(key, {"label": _anchor_label(domain, label),
                                   "date": record, "kind": kind})
    return index


def _entry_date(entry: dict) -> object:
    """One entry's date record — a point, or a span read as one interval.

    A span is composed through :func:`chronology.parse_edtf` so the resulting
    record carries real ``earliest``/``latest`` bounds; a half-open span
    yields the open interval EDTF already understands (``1984/..``).
    """
    direct = chrono.from_dict(entry.get("date"))
    if direct is not None:
        return direct
    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    start = chrono.to_edtf(chrono.from_dict(span.get("start")))
    end = chrono.to_edtf(chrono.from_dict(span.get("end")))
    if not start and not end:
        return None
    if start and end:
        return chrono.parse_edtf(f"{start}/{end}", basis="stated")
    if start:
        return chrono.parse_edtf(f"{start}/..", basis="stated")
    return chrono.parse_edtf(f"../{end}", basis="stated")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _anchor_key(domain: str, label: str, position: int) -> str:
    slug = _SLUG_RE.sub("-", label.lower()).strip("-")[:40]
    return f"{domain}-{slug or position}"


def _anchor_label(domain: str, label: str) -> str:
    if domain == "birth":
        return "when you were born"
    if domain == "residences":
        return label
    if domain == "schools":
        return label
    return label


# --------------------------------------------------------------------------
# The gap only a landmark can reveal (landmarks.md §5.3)
# --------------------------------------------------------------------------

#: A place the person told us about that has nothing in it. Not a DATING gap
#: (v196's `place_span` is that) — a STORY gap, and one the vault could not
#: express before a landmark named the place.
PLACE_NO_STORIES_KIND = "place_no_stories"

PLACE_NO_STORIES_OPENER = (
    "{label} — you lived there and there's nothing here from it. "
    "What happened there?"
)


def places_without_stories(landmarks: object, event_places: object = ()) -> tuple[dict, ...]:
    """Every residence with a known span and no moments attached.

    Returns unknown-shaped rows ``{kind, key, label, span, landmark, anchor,
    witnesses, probe}`` so the arc planner and the Mirror's gap finders consume
    them exactly like every other unknown.

    ``witnesses`` carries the people who were there — a witness being a living
    person who was there (`system/research/go-deep.md` §7; the term is law's
    and oral history's, "warm, honest, and free of collisions"). It comes from
    the residence ladder's own `household` rung, so no new state exists: the
    person already told us who was in the house, and those are exactly the
    people who can answer about it when they cannot.

    v200 adds three ADDITIVE fields so a consumer never re-derives what this
    function already knows (recurring-defect doctrine):

    * ``span`` — the person's OWN span, rendered the way they would recognise
      it (`chronology.display_date`, basis clause suppressed). It is what makes
      the arc-card line concrete ("they lived in Costa Mesa, 1990–1993"),
      and it is a REPORT of what they said, never a date proposed for
      agreement (`timeline_interaction.proposes_a_date`, go-deep.md §4.3).
    * ``landmark`` — ``{"domain": "residences", "label": ...}``, the reference
      back to the landmark entry this gap came from. `save_landmark` merges by
      label, so (domain, label) IS a landmark's identity.
    * ``anchor`` — the key `anchors_from_landmarks` mints for the same
      residence, so the story gap and the dating anchor can be joined without a
      second slug implementation anywhere.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    seen = {str(p).strip().lower() for p in (event_places or ()) if str(p).strip()}
    rows: list[dict] = []
    for position, entry in enumerate(filed.get("residences") or (), start=1):
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        if not label or label.lower() in seen:
            continue
        record = _entry_date(entry)
        if record is None:
            continue  # its span is the dating gap v196 already asks about
        anchor = _anchor_key("residences", label, position)
        household = str(entry.get("household") or "").strip()
        rows.append({
            "kind": PLACE_NO_STORIES_KIND,
            "key": f"{PLACE_NO_STORIES_KIND}:{anchor}",
            "label": label,
            "span": chrono.display_date(record, with_basis=False),
            "landmark": {"domain": "residences", "label": label},
            "anchor": anchor,
            "witnesses": household or None,
            "probe": {"step": "content", "cost": 1,
                      "text": PLACE_NO_STORIES_OPENER.format(label=label)},
        })
    return tuple(rows)


#: How a place-with-no-stories reads in a prompt. The sibling of
#: `timeline_interaction.render_whisper`, and deliberately the same shape: it
#: states what we know, names the gap, and hands the ask over as an
#: invitation — "if it fits" — rather than a script. The span is REPORTED
#: (the person's own words, back to them, showing the working); nothing here
#: names a date and invites agreement.
PLACE_NO_STORIES_LINE = (
    "{kind} — they lived in {label}{span} and there are no stories from "
    "there yet; if it fits, ask what life was like there"
)


def render_place_no_stories(item: object) -> str:
    """The place-with-no-stories intent's ONE rendering (v200).

    Degrades to the bare kind name when the intent carries no probe, exactly
    as `render_whisper` does — which is what keeps a bare
    ``{"kind": "place_no_stories"}`` intent rendering byte-for-byte like every
    other kind in `conversation._assemble_session_block`.
    """
    row = item if isinstance(item, dict) else {}
    probe = row.get("probe")
    probe_text = probe.get("text") if isinstance(probe, dict) else probe
    label = str(row.get("place") or row.get("label") or "").strip()
    if not str(probe_text or "").strip() or not label:
        return PLACE_NO_STORIES_KIND
    span = str(row.get("span") or "").strip()
    line = PLACE_NO_STORIES_LINE.format(
        kind=PLACE_NO_STORIES_KIND, label=label,
        span=f", {span}," if span else "",
    )
    witnesses = str(row.get("witnesses") or "").strip()
    if witnesses:
        line = f"{line} — someone who was there: {witnesses}"
    return line


# --------------------------------------------------------------------------
# The read-only plan verb
# --------------------------------------------------------------------------

DEFAULT_LANDMARK_PLAN_SIZE = 6


def build_landmarks_plan(landmarks: object, *, keystone_domains: object = (),
                         limit: int = DEFAULT_LANDMARK_PLAN_SIZE,
                         framework_root: str | Path | None = None) -> dict:
    """One Play's worth of open landmarks, best first.

    ``{"count", "complete", "items": [{domain, status, rung, text, keystone}]}``
    """
    rows = landmark_rows(landmarks, keystone_domains=keystone_domains,
                         framework_root=framework_root)
    offerable = open_landmarks(rows)
    items = []
    for row in offerable[:max(int(limit), 0)]:
        question = row.get("next") or {}
        items.append({
            "domain": row["domain"],
            "status": row["status"],
            "rung": question.get("rung"),
            "subject": question.get("subject"),
            "text": question.get("text"),
            "keystone": bool(row.get("keystone")),
            "sensitive": bool(row.get("sensitive")),
        })
    return {
        "count": len(offerable),
        "complete": sum(1 for r in rows if r["status"] == "complete"),
        "total": len(rows),
        "items": items,
    }


def describe_landmarks_plan(plan: object) -> list[str]:
    """Human lines for the CLI."""
    if not isinstance(plan, dict):
        return []
    lines = [f"Landmarks: {plan.get('complete', 0)} of {plan.get('total', 0)} complete, "
             f"{plan.get('count', 0)} open"]
    for item in plan.get("items") or ():
        star = "★ " if item.get("keystone") else "  "
        lines.append(f"{star}{item.get('domain')} [{item.get('status')}] "
                     f"— {item.get('text')}")
    return lines


def render_landmarks(rows: object, *, limit: int = 8) -> str:
    """The `{landmarks}` prompt block — what we already know, so the model
    never asks for it twice."""
    lines = []
    for row in (rows or ())[:max(int(limit), 0)]:
        if not isinstance(row, dict) or row.get("status") == "open":
            continue
        count = row.get("count") or 0
        lines.append(f"- {row.get('domain')}: {row.get('status')}"
                     + (f" ({count})" if count else ""))
    return "\n".join(lines) if lines else "(nothing yet)"


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    import timeline  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Plan a landmarks Play (read-only)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = timeline.timeline_data()
    rows = timeline.landmark_rows_for(data)
    starred = {row["domain"] for row in rows if row.get("keystone")}
    plan = build_landmarks_plan(
        timeline.load_landmarks(),
        keystone_domains=starred,
        limit=args.limit if args.limit is not None else DEFAULT_LANDMARK_PLAN_SIZE,
    )
    if args.json:
        print(json.dumps(json.loads(json.dumps(plan, default=str)),
                         indent=2, sort_keys=True))
    else:
        print("\n".join(describe_landmarks_plan(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
