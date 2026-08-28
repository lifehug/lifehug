"""`era-record` — one sentence becomes an era, in one act.

Eras design §4.4/§4.5 (lifehug-platform `docs/design/eras.md`), phase E3.

Somebody says *"I think of 2007 through 2011 as my College years."* That one
sentence creates an identity, names it, decides whether it is a stretch or a
thread, asserts two dates, links those dates to the thing they are about, and
possibly says where it sits. Six writes. If they are six verbs a caller
sequences, then a job that dies between the third and the fourth leaves a
vault holding half a thought, and the retry — under a NEW mutation key,
because the caller re-derived one — makes a second era with the same name.
That is exactly the state §4.4 exists to make impossible.

So it is ONE call:

    ensure identity → label/kind records → bind + file claims → `within`
    constraint → membership assertions → publish

and **every step is a no-op on replay** by construction, not by a lock:

* the identity is content-addressed by the OPERATION id (`session_ref#turn_ref`),
  so the retry lands on the same `era_id` and `create_or_keep` writes nothing;
* the claims go through `temporal_store.file_message_extraction`, which is
  promote-then-receipt and idempotent on the utterance's own digest;
* a resolution's id is digest(claim, mention, rule, supersedes);
* an ordering constraint's id is `move_digest`;
* the publish is `temporal_publication.publish`, whose semantic no-op means a
  second identical run mints no generation.

A job that dies mid-way and is retried under the same mutation id therefore
completes the remaining steps and duplicates none of the finished ones
(T-W-02/03) — which is tested by running the writer with each step as a crash
point and then running it whole.

**What this module deliberately does not own.** The membership receipt is
O-E2's (`sources/eras/memberships/` — :func:`era_memberships.file_era_membership`),
reached here through ONE named seam (:func:`membership_writer`) that BINDS
that function rather than reimplementing it. Per ADR 0021 an unwired seam
FAILS LOUD: a payload carrying `memberships` with no writer is refused BEFORE
the first byte is written, rather than filing five sixths of the act and
shrugging about the sixth.

That guard was load-bearing for a whole release and nobody noticed, which is
worth writing down. This module was authored against O-E2 before O-E2 landed
and guessed the module name — `era_membership`, singular, with a
`file_membership_assertion` inside it. v247 shipped `era_memberships` with
`file_era_membership`. The lazy import raised `ImportError`, the seam
answered `None` honestly, and `era-record` correctly refused every payload
carrying memberships — so the fifth leg was not *broken*, it was *never
performed*, on any vault, for the entire life of the verb (lifehug#270). The
refusal is why this cost nothing but a missing feature. The lesson is that a
seam resolved by a STRING needs a test that the string names something real,
which is what `tests/test_eras_e3b.py`'s import guard now is.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import era_identity as ei  # noqa: E402
import event_binding as eb  # noqa: E402
import general_listener as gl  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    normalized_timestamp,
)

#: The extractor version an `era-record` filing stamps on its claims. It is a
#: SECOND name beside `landmark_recorder`'s and never a rename: "what did the
#: era writer hear" and "what did the landmark recorder hear" have to stay
#: separately answerable, exactly as `date_record` stands beside
#: `landmark_record` in the budget (ADR 0029).
ERA_RECORD_EXTRACTOR = "era_record"

#: The payload's closed key set. Closed for the same reason
#: `general_listener.CLAIM_PROMPT_KEYS` is: a key nothing reads is a key a
#: caller was told a falsehood about.
PAYLOAD_KEYS = frozenset({
    "era_id", "operation_id", "label", "aliases", "era_kind", "claims",
    "within", "memberships", "session_ref", "turn_ref", "message_text",
    "author", "occurred_at", "supersedes_label", "supersedes_kind", "origin",
})

ERA_RECORD_ERROR_CODES = (
    "era_payload_not_a_mapping",
    "era_payload_unknown_key",
    "era_payload_needs_operation",
    "era_payload_needs_message",
    "era_payload_claim_refused",
    "era_membership_unwired",
)


class EraRecordError(TemporalContractError):
    """One `era-record` act could not be performed, with a named code."""


# --------------------------------------------------------------------------
# The O-E2 seam
# --------------------------------------------------------------------------

#: Set by a test (or a host with its own binding) to the function that files
#: ONE membership assertion: ``fn(vault_root, *, member_node_id, era_node_id,
#: relation, source_ref, basis, now) -> (record, created)``. Left ``None``,
#: :func:`membership_writer` binds O-E2's real writer through
#: :func:`_adapt_membership_writer`.
MEMBERSHIP_WRITER: Callable | None = None

#: The module O-E2 shipped the receipt writer in, and the function inside it.
#: Named as constants because the whole defect this pair exists to prevent was
#: a *string* — `era_record` lazily imported ``era_membership`` (singular) for
#: a module O-E2 shipped as ``era_memberships``, so the seam resolved to
#: ``None`` on every vault and the fifth leg of the atomic writer was refused
#: rather than performed (lifehug#270). A name in a constant is a name the
#: import guard can check.
MEMBERSHIP_MODULE = "era_memberships"
MEMBERSHIP_FUNCTION = "file_era_membership"

#: What an era-record membership asserts by default. NOT ``"stated"`` — that
#: word is not in :data:`temporal_claims.CLAIM_BASES` and the receipt writer
#: refuses it. A person saying "during College" in their own sentence is
#: `explicit`, which is also O-E2's own default.
MEMBERSHIP_DEFAULT_BASIS = "explicit"

#: What an era-record membership asserts when the row does not say.
MEMBERSHIP_DEFAULT_RELATION = "within"


def membership_writer() -> Callable | None:
    """The membership receipt writer, or ``None`` when nothing is wired.

    Explicit override first, then O-E2's module. Returning ``None`` is the
    honest answer and the caller refuses on it — a silent skip here would be
    exactly the "wired into some hosts and silently does less in others"
    failure ADR 0021 was ratified over.

    There is ONE writer and this does not become a second one: the adapter
    below translates names and return shape and files nothing itself.
    """
    if MEMBERSHIP_WRITER is not None:
        return MEMBERSHIP_WRITER
    try:
        import era_memberships  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the module is vendored beside us
        return None
    filer = getattr(era_memberships, MEMBERSHIP_FUNCTION, None)
    if filer is None:  # pragma: no cover - guarded by the import-name test
        return None
    return _adapt_membership_writer(era_memberships, filer)


def _adapt_membership_writer(module, filer: Callable) -> Callable:
    """O-E2's writer, wearing the seam's signature. Adapts; never re-implements.

    Two things differ and only two: the clock parameter is spelled
    ``occurred_at`` there and ``now`` here, and O-E2 returns the normalized row
    while this seam promised ``(record, created)``. ``created`` is *observed*
    — the receipt is content-addressed, so whether this call minted the file is
    exactly whether its path was absent a moment ago — rather than recomputed
    by a parallel copy of ``_create_or_keep``'s logic, which is the shape ADR
    0021 exists to forbid.
    """

    def write(
        vault_root,
        *,
        member_node_id,
        era_node_id,
        relation=MEMBERSHIP_DEFAULT_RELATION,
        source_ref=None,
        basis=MEMBERSHIP_DEFAULT_BASIS,
        now=None,
        **extra,
    ):
        verb = collapsed_text(relation).lower() or MEMBERSHIP_DEFAULT_RELATION
        relative = module.membership_relative_path(
            module.membership_digest(
                member_node_id=member_node_id,
                era_node_id=era_node_id,
                relation=verb,
                source_ref=source_ref,
            )
        )
        existed = store.store_path(Path(vault_root), relative).exists()
        record = filer(
            vault_root,
            member_node_id=collapsed_text(member_node_id),
            era_node_id=collapsed_text(era_node_id),
            source_ref=source_ref,
            relation=verb,
            basis=basis,
            occurred_at=now,
            **extra,
        )
        return record, not existed

    return write


# --------------------------------------------------------------------------
# Stretch vs thread (§4.5)
# --------------------------------------------------------------------------

#: A stated interval, or begin/end language. "2007 through 2011", "from 1998
#: to 2004", "it started in the spring", "that ended when we moved".
_STRETCH_RES = (
    re.compile(r"\b\d{4}\s*(?:-|–|—|to|through|until|till)\s*\d{4}\b", re.I),
    re.compile(r"\bfrom\b.{0,40}\bto\b", re.I | re.S),
    re.compile(r"\b(?:started|began|start|begin|ended|finished|left|graduated|"
               r"moved out|wrapped up)\b", re.I),
)

#: Recurring presence: a thing that runs THROUGH a life rather than sitting in
#: a stretch of it. "over the years", "on and off", "always", "ever since",
#: "it kept coming back".
_THREAD_RES = (
    re.compile(r"\bover the years\b", re.I),
    re.compile(r"\bon and off\b", re.I),
    re.compile(r"\b(?:ever since|all along|throughout|the whole time)\b", re.I),
    re.compile(r"\b(?:always|never really stopped|kept coming back|"
               r"comes and goes|off and on)\b", re.I),
)


def era_kind_from_words(text: object, *, has_within: bool = False) -> str | None:
    """``stretch``, ``thread``, or ``None`` — decided from what they SAID.

    ``None`` means ambiguous, and ambiguous is ONE scope question, never a
    default (§4.5). Defaulting to `stretch` would mint a span work item
    against a thing that has no honest end and then ask the person, forever,
    when their friendship with Ruth finished.

    A stated interval or a `within` wins outright: "College was in my 20s"
    puts an era inside a bounded stretch of the axis, which is what a stretch
    IS. Recurring-presence language wins when no interval was stated. Both
    kinds of language in one sentence is genuinely ambiguous and says so.
    """
    said = str(text or "")
    stretch = bool(has_within) or any(rx.search(said) for rx in _STRETCH_RES)
    thread = any(rx.search(said) for rx in _THREAD_RES)
    if stretch and not thread:
        return "stretch"
    if thread and not stretch:
        return "thread"
    return None


#: The Focus type a flipped-to-thread era becomes a candidate for. A thread is
#: a recurring presence through a life — which is what a theme Focus is — and
#: `period` is deliberately NOT used, because the whole content of the flip is
#: "this was never a period".
THREAD_FOCUS_TYPE = "theme"


def flip_era_kind(
    vault_root: str | Path,
    *,
    era_id: object,
    era_kind: str,
    supersedes: object = None,
    reason: object = None,
    now: object = None,
) -> dict:
    """Flip stretch↔thread. Identity, memberships, links and sessions untouched.

    §4.5 and T-NE-16. The flip is ONE kind decision record on the SAME
    `era_id`, and everything that hangs off that id keeps hanging off it —
    which is the entire payoff of an opaque identity and is why this function
    is four lines rather than a migration.

    The two consequences the design names are both derived, not stored:

    * **the open span work item retires.** It is generated by the fold for a
      `stretch` with a missing bound; a `thread` has no bound to miss, so the
      row stops being produced. Nothing is deleted, and flipping back
      re-mints it — which is what makes this reversible rather than
      destructive.
    * **a Focus candidate is minted** — a recurring presence is a thing to
      write about, not a thing to date. The row is appended to
      `state/focus_recommendations.json` idempotently by id, and it creates
      no Focus: the person still decides.
    """
    kind = collapsed_text(era_kind)
    if supersedes is None:
        # A flip that does not name the decision it replaces is not a flip —
        # it is a second opinion, and `era_views` would then have to break the
        # tie by timestamp on records whose digests deliberately exclude one.
        # The predecessor is read here rather than demanded of the caller: the
        # caller knows what it wants the era to BE, and "which record says the
        # opposite" is this module's own bookkeeping.
        current = (ei.era_views(vault_root).get(collapsed_text(era_id)) or {})
        path = current.get("kind_path")
        if path:
            standing = ei.read_era_record(vault_root, path)
            if standing is not None:
                supersedes = ei._digest_of(standing)
    record, created = ei.file_era_kind(
        vault_root, era_id=era_id, era_kind=kind, supersedes=supersedes,
        reason=reason, occurred_at=now,
    )
    summary = {
        "era_id": collapsed_text(era_id),
        "era_kind": kind,
        "kind_record": record["relative_path"],
        "created": created,
        "span_work_item": "retired" if kind == "thread" else "minted",
        "focus_candidate": None,
    }
    if kind == "thread":
        view = ei.era_views(vault_root).get(collapsed_text(era_id)) or {}
        label = collapsed_text(view.get("label")) or collapsed_text(era_id)
        summary["focus_candidate"] = _append_thread_focus_candidate(
            vault_root, label=label, now=now
        )
    return summary


#: Verbatim, constant, and NOT templated — the same discipline
#: `recommend_focuses.ENTITY_ONBOARDING_REASON` holds: a reason line that
#: varies per row stops being readable as a class.
THREAD_FOCUS_REASON = "an era the person called a recurring presence, not a stretch"


def _append_thread_focus_candidate(
    vault_root: str | Path, *, label: str, now: object = None
) -> dict:
    """Append one pending Focus recommendation for a thread. Idempotent by id.

    Written here against the supplied vault root rather than through
    `recommend_focuses.append_entity_recommendation`, which reads the ENTITY
    ROSTER (a thread is not a roster entity) and binds the interpreter to one
    vault. The row's SHAPE is still that module's — `RECOMMENDATION_ROW_KEYS`
    is imported and asserted against, so a key added there fails here rather
    than drifting.
    """
    from recommend_focuses import RECOMMENDATION_ROW_KEYS  # noqa: PLC0415

    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "era"
    row = {
        "id": f"rec-{slug}",
        "entity": label,
        "type": THREAD_FOCUS_TYPE,
        "score": 0.0,
        "evidence_strength": "weak",
        "mention_count": 0,
        "unique_answers": 0,
        "cross_categories": [],
        "emotional_weight": 0.0,
        "evidence": [],
        "reason": THREAD_FOCUS_REASON,
        "status": "pending",
        "created_at": normalized_timestamp(now, error=EraRecordError),
        "ready_to_start": False,
    }
    assert set(row) == set(RECOMMENDATION_ROW_KEYS)  # noqa: S101 - shape pin

    relative = "state/focus_recommendations.json"
    text = store.read_store_text(vault_root, relative)
    try:
        state = json.loads(text) if text else {}
    except (TypeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    recs = [r for r in (state.get("recommendations") or ()) if isinstance(r, dict)]
    if any(r.get("id") == row["id"] for r in recs):
        return {"created": False, "recommendation": row["id"]}
    state.setdefault("version", 1)
    state.setdefault("generated_at", row["created_at"])
    state["recommendations"] = [*recs, row]
    state.setdefault("dismissed", [])
    path = store.store_path(vault_root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    from vault_paths import atomic_write_vault_text  # noqa: PLC0415

    atomic_write_vault_text(
        path,
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        vault_root=Path(vault_root),
    )
    return {"created": True, "recommendation": row["id"]}


# --------------------------------------------------------------------------
# The atomic writer
# --------------------------------------------------------------------------


def validate_payload(value: object) -> dict:
    """One `era-record` payload, through one door, before a byte is written."""
    if not isinstance(value, dict) or not value:
        raise EraRecordError(
            "era_payload_not_a_mapping", "an era-record payload is a mapping"
        )
    unknown = sorted(set(value) - PAYLOAD_KEYS)
    if unknown:
        raise EraRecordError(
            "era_payload_unknown_key",
            f"unknown era-record key(s): {', '.join(unknown)}",
            detail=unknown,
        )
    payload = dict(value)
    era_id = collapsed_text(payload.get("era_id"))
    operation = collapsed_text(payload.get("operation_id"))
    session = collapsed_text(payload.get("session_ref"))
    turn = collapsed_text(payload.get("turn_ref"))
    if not era_id and not operation:
        if not (session and turn):
            raise EraRecordError(
                "era_payload_needs_operation",
                "creating an era names the act that created it: an explicit "
                "operation_id, or the session and turn it was said in",
            )
        operation = ei.turn_operation_id(session, turn)
    if era_id:
        ei.era_digest(era_id)  # guard

    drafts, findings = gl.parse_claims(payload.get("claims") or ())
    if findings:
        # A refused claim is NOT dropped quietly here. `parse_claims` drops
        # per-claim so a good sibling survives, which is right for a live
        # conversation turn; this verb is a deliberate act with a payload
        # somebody assembled, and half-filing it silently is how a caller
        # learns nothing.
        raise EraRecordError(
            "era_payload_claim_refused",
            f"{len(findings)} claim(s) refused: {', '.join(findings)}",
            detail=list(findings),
        )

    memberships = [row for row in (payload.get("memberships") or ())
                   if isinstance(row, dict) and row]
    if memberships and membership_writer() is None:
        raise EraRecordError(
            "era_membership_unwired",
            "this payload asks for membership assertions and no membership "
            "writer is wired (O-E2). Refusing the WHOLE act rather than "
            "filing five sixths of it.",
        )

    message = collapsed_text(payload.get("message_text"))
    if drafts and not message:
        raise EraRecordError(
            "era_payload_needs_message",
            "a claim cites the words it came from; promote the message or "
            "file no claims",
        )
    return {
        "era_id": era_id,
        "operation_id": operation,
        "origin": collapsed_text(payload.get("origin")) or "person",
        "label": collapsed_text(payload.get("label")),
        "aliases": list(payload.get("aliases") or ()),
        "era_kind": collapsed_text(payload.get("era_kind")),
        "supersedes_label": collapsed_text(payload.get("supersedes_label")) or None,
        "supersedes_kind": collapsed_text(payload.get("supersedes_kind")) or None,
        "claims": list(drafts),
        "within": collapsed_text(payload.get("within")),
        "memberships": memberships,
        "session_ref": session,
        "turn_ref": turn,
        "message_text": message,
        "author": collapsed_text(payload.get("author")) or None,
        "occurred_at": payload.get("occurred_at"),
    }


#: The ordered step names, so a crash point in a test is a NAME rather than an
#: index, and the summary reads in the order the vault moved.
STEPS = ("identity", "label", "kind", "claims", "within", "memberships", "publish")


def record_era(
    vault_root: str | Path,
    payload: object,
    *,
    now: object = None,
    stop_after: str | None = None,
) -> dict:
    """The whole act. Returns a summary naming every step and what it did.

    ``stop_after`` exists for ONE reason: proving T-W-02/03. It stops the run
    after the named step so a test can simulate a job dying mid-way, then
    re-run the same payload whole and assert the vault converges on exactly
    the file set an uninterrupted run produces. It is not an option a caller
    has any other use for and the CLI does not expose it.
    """
    plan = validate_payload(payload)
    when = plan["occurred_at"] if plan["occurred_at"] is not None else now
    summary: dict = {"steps": {}, "era_id": plan["era_id"]}

    def done(step: str) -> bool:
        return stop_after is not None and step == stop_after

    # 1 — identity, content-addressed by the operation id.
    if plan["era_id"]:
        era_id = plan["era_id"]
        summary["steps"]["identity"] = {"era_id": era_id, "created": False,
                                        "reason": "named by the caller"}
    else:
        record, created = ei.file_era_identity(
            vault_root,
            operation_id=plan["operation_id"],
            origin=plan["origin"],
            era_kind=plan["era_kind"] or None,
            session_ref=plan["session_ref"],
            turn_ref=plan["turn_ref"],
            author=plan["author"],
            occurred_at=when,
            label_hint=plan["label"],
        )
        era_id = record["era_id"]
        summary["steps"]["identity"] = {"era_id": era_id, "created": created,
                                        "path": record["relative_path"]}
    summary["era_id"] = era_id
    if done("identity"):
        return summary

    # 2 — the label decision.
    if plan["label"]:
        record, created = ei.file_era_label(
            vault_root, era_id=era_id, label=plan["label"],
            aliases=plan["aliases"], supersedes=plan["supersedes_label"],
            author=plan["author"], occurred_at=when,
        )
        summary["steps"]["label"] = {"created": created,
                                     "path": record["relative_path"],
                                     "label": plan["label"]}
    if done("label"):
        return summary

    # 3 — the kind decision.
    if plan["era_kind"]:
        record, created = ei.file_era_kind(
            vault_root, era_id=era_id, era_kind=plan["era_kind"],
            supersedes=plan["supersedes_kind"], author=plan["author"],
            occurred_at=when,
        )
        summary["steps"]["kind"] = {"created": created,
                                    "path": record["relative_path"],
                                    "era_kind": plan["era_kind"]}
    if done("kind"):
        return summary

    # 4 — bind and file the claims. The ORDER is the durability rule: a claim
    #     id exists only once the message is a source, and a resolution names
    #     a claim id, so promotion → binding → receipt → resolutions, and a
    #     crash anywhere in it is completed by the identical re-run.
    if plan["claims"]:
        summary["steps"]["claims"] = _file_claims_and_bind(
            vault_root, plan, era_id=era_id, when=when
        )
    if done("claims"):
        return summary

    # 5 — the `within` relation. A containment, never a bound (§4.2): the
    #     fold publishes it as `possible_temporal_value` and leaves
    #     `best_temporal_value` empty.
    if plan["within"]:
        constraint = store.file_ordering_constraint(
            vault_root,
            relation="within",
            subject_node_id=era_id,
            anchor_node_ids=[plan["within"]],
            reason=plan["message_text"] or None,
            subject_label=plan["label"] or era_id,
            author=plan["author"],
            occurred_at=when,
        )
        summary["steps"]["within"] = {"constraint_id": constraint["constraint_id"],
                                      "anchor": plan["within"],
                                      "path": constraint["relative_path"]}
    if done("within"):
        return summary

    # 6 — membership assertions, through O-E2's seam. `validate_payload` has
    #     already refused the whole act if this is unwired, so reaching here
    #     with rows means the writer exists.
    if plan["memberships"]:
        writer = membership_writer()
        rows = []
        for row in plan["memberships"]:
            record, created = writer(  # type: ignore[misc]
                vault_root,
                member_node_id=collapsed_text(row.get("member_node_id")),
                era_node_id=era_id,
                relation=collapsed_text(row.get("relation"))
                or MEMBERSHIP_DEFAULT_RELATION,
                source_ref=_membership_source_ref(row, summary, plan),
                basis=collapsed_text(row.get("basis")) or MEMBERSHIP_DEFAULT_BASIS,
                now=when,
            )
            rows.append({
                "created": created,
                "assertion_id": (record or {}).get("assertion_id"),
                "path": (record or {}).get("relative_path"),
                "record": record,
            })
        summary["steps"]["memberships"] = rows
    if done("memberships"):
        return summary

    # 7 — publish, through the ONE publisher. `event_resolution_records=None`
    #     means "read this vault's filed bindings", so the projection this act
    #     produces HAS the bindings this act just wrote.
    from temporal_publication import publish  # noqa: PLC0415

    published = publish(vault_root, now=when)
    summary["steps"]["publish"] = {
        "generation": published["generation"],
        "unchanged": published["unchanged"],
        "nodes": published["nodes"],
    }
    return summary


def _membership_source_ref(row: dict, summary: dict, plan: dict) -> object:
    """What one membership assertion CITES, in the order the design permits.

    An explicit `source_ref` on the row first — a caller that already knows the
    evidence is not overruled. Otherwise **this act's own promoted source**: the
    `SourceRef` the claims leg promoted, passed WHOLE rather than as its
    `source_id`, because `era_memberships.membership_digest` keys identity on
    `source_id@revision` and a bare id would make this the one receipt in the
    vault citing a source at no revision.

    Last, the operation id — for the payload that asserts a membership and
    files no claim, so promoted nothing. It is a real, stable citation of the
    act that said so, and the alternative is an empty `source_ref`, which O-E2
    refuses outright ("date overlap is not evidence").
    """
    stated = row.get("source_ref")
    if isinstance(stated, dict) or hasattr(stated, "to_dict"):
        return stated
    text = collapsed_text(stated)
    if text:
        return text
    promoted = (summary.get("steps") or {}).get("claims") or {}
    return promoted.get("source_ref") or plan["operation_id"]


def _file_claims_and_bind(
    vault_root: str | Path, plan: dict, *, era_id: str, when: object
) -> dict:
    """Promote once, file one receipt with N claims, then file the bindings."""
    minted: list[dict] = []

    def claims_for(source_ref):
        bound = gl.bind_claims(
            plan["claims"], source_ref=source_ref,
            extractor_version=ERA_RECORD_EXTRACTOR, now=when,
        )
        minted.extend(bound)
        return bound

    metadata = {key: plan[key] for key in ("session_ref", "turn_ref") if plan[key]}
    if when is not None:
        metadata["occurred_at"] = when
    source_ref, receipt = store.file_message_extraction(
        vault_root,
        message_text=plan["message_text"],
        extractor_version=ERA_RECORD_EXTRACTOR,
        claims_for=claims_for,
        metadata=metadata,
        recorder=ERA_RECORD_EXTRACTOR,
        now=when,
    )

    index = ei.label_index(ei.era_views(vault_root))
    bindings: list[dict] = []
    for claim in minted:
        mention = collapsed_text(claim.get("event_mention"))
        if not mention:
            continue
        ref, how, candidates = eb.bind_event_mention(
            mention, index=index, target_era_id=era_id
        )
        record, created = eb.file_event_resolution(
            vault_root,
            claim_id=claim["claim_id"],
            event_mention=mention,
            event_ref=ref,
            bound_by=how,
            candidates=candidates,
            now=when,
        )
        row = {"claim_id": claim["claim_id"], "event_mention": mention,
               "event_ref": ref, "bound_by": how, "created": created}
        if ref is None and len(candidates) > 1:
            row["work_item"] = eb.ambiguous_work_item(
                mention, candidates, views=ei.era_views(vault_root)
            )
        elif ref is None:
            row["finding"] = eb.UNBOUND_FINDING
        bindings.append(row)

    return {
        "source_id": source_ref.source_id,
        "source_path": source_ref.source_path,
        # The WHOLE ref, not just its id: the membership leg cites a source AT
        # A REVISION, and `source_id` alone silently drops the revision half.
        "source_ref": source_ref.to_dict(),
        "receipt": Path(receipt).name,
        "claim_ids": [claim["claim_id"] for claim in minted],
        "bindings": bindings,
    }


def describe(summary: object) -> list[str]:
    """One `era-record` act as lines a human reads in a terminal."""
    row = summary if isinstance(summary, dict) else {}
    steps = row.get("steps") or {}
    lines = [f"✓ era {row.get('era_id')}"]
    identity = steps.get("identity") or {}
    lines.append(
        f"  identity: {'created' if identity.get('created') else 'already there'}"
    )
    for name in ("label", "kind"):
        step = steps.get(name)
        if step:
            what = step.get("label") or step.get("era_kind")
            lines.append(
                f"  {name}: {what} "
                f"({'filed' if step.get('created') else 'unchanged'})"
            )
    claims = steps.get("claims")
    if claims:
        lines.append(f"  claims: {len(claims.get('claim_ids') or ())} filed from "
                     f"{claims.get('source_id')}")
        for binding in claims.get("bindings") or ():
            if binding.get("event_ref"):
                lines.append(f"    “{binding['event_mention']}” → "
                             f"{binding['event_ref']} (via {binding['bound_by']})")
            elif binding.get("work_item"):
                lines.append(f"    “{binding['event_mention']}” → unbound: "
                             f"{binding['work_item']['headline']}")
            else:
                lines.append(f"    “{binding['event_mention']}” → unbound "
                             "(nothing answers to that name yet)")
    within = steps.get("within")
    if within:
        lines.append(f"  within: {within['anchor']} ({within['constraint_id']})")
    memberships = steps.get("memberships")
    if memberships:
        lines.append(f"  memberships: {len(memberships)} assertion(s)")
    published = steps.get("publish")
    if published:
        lines.append(
            f"  projection generation {published['generation']}"
            + (" (unchanged — nothing written)" if published.get("unchanged") else "")
        )
    return lines


__all__ = [
    "ERA_RECORD_ERROR_CODES",
    "ERA_RECORD_EXTRACTOR",
    "MEMBERSHIP_DEFAULT_BASIS",
    "MEMBERSHIP_DEFAULT_RELATION",
    "MEMBERSHIP_FUNCTION",
    "MEMBERSHIP_MODULE",
    "MEMBERSHIP_WRITER",
    "PAYLOAD_KEYS",
    "STEPS",
    "THREAD_FOCUS_REASON",
    "THREAD_FOCUS_TYPE",
    "EraRecordError",
    "describe",
    "era_kind_from_words",
    "flip_era_kind",
    "membership_writer",
    "record_era",
    "validate_payload",
]
