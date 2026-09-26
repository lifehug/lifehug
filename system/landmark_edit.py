#!/usr/bin/env python3
"""The owner's EDIT FORMS — a landmark or a cornerstone person, as he typed it.

v360 (owner, 2026-09-25), the owner's words: *"For each landmark when I press the
play button, I want just to pop up a form with every field for a landmark
that's possible … I can just input exactly what I want and when I press play
it adds it as user updated."* And, for the Cornerstones grid: *"a form field
opens where I can put in a date for each of those person types … Darvin
Burrows Beauchamp is my grandpa, and it's in Others. There needs to be a way I
can … change the category to grandparents, others, or siblings."*

Two verbs, one module, and NO store of their own. Everything a form files goes
through the machinery that already holds the thing it edits:

* **A landmark stay** (`landmark-edit`). The stay the form was opened on is
  named by the ``ref`` the Landmarks view published
  (`timeline_views.A_STAY_IS_NAMED_BY_ITS_REF`). Its tellings are RETIRED —
  one supersede correction (`landmark_projection.retire_entry`, scope
  ``landmarks/<domain>``) — and the form's record is filed in their place
  through `timeline.save_landmark` in its ``exact`` mode, as a stated record.
  The promoted sources are never touched; the old stay stops standing and the
  new one stands, and the next redraw and publish recalculate everything that
  hung on it.
* **Delete** is the retirement alone, and its correction id comes back so
  **undo** can reinstate it (`temporal_store.reinstate_corrections`).
* **A person** (`person-edit`). Who they are — category, the word he calls
  them, a grandparent's side, the full name — is the ROSTER row
  (`entity_verdict.apply_verdict`, the one roster writer; ``--ensure`` for a
  person only a landmark named, like Darvin). Their dates are landmark
  records marked ``form: owner`` (born → ``family``/``children``, died →
  ``losses``, married/divorced → ``partnerships``), filed after the earlier
  landmark date claims for the same entry are superseded, and the roster's
  own ``born``/``died`` follow. An Others row's 🗑 supersedes the claims
  behind that discrete date (`timeline_views._claim_ids_of`), undoable.

The basis of everything filed here is ``stated``: it is the owner's own
statement, and `temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT` places it over
any reading or inference (:data:`OWNER_EDIT_IS_EXACT`).

Idempotent: a save whose record already IS the drawn stay files nothing, and a
re-run after a crash converges on the same source digest
(:func:`edit_digest`). Pure helpers are separated from the writers; the writers
take the vault root and assert it is the one `timeline` is bound to.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402

#: The one rule, as the text every seat cites.
OWNER_EDIT_IS_EXACT = (
    "a landmark or a person edited on the owner's form is filed exactly as he "
    "typed it, basis stated: the stay he opened is retired by a correction "
    "(never deleted) and his record stands in its place, and nothing a reader "
    "or the resolver inferred outranks it"
)

#: The kinds the landmark form edits. A mission area is a residence stay
#: inside the mission stretch (`timeline_views._mission_domain_row`), so it
#: files as one.
FORM_KINDS = ("residences", "schools", "work", "missions")
FILED_DOMAIN = {"residences": "residences", "schools": "schools", "work": "work",
                "missions": "residences"}

#: A school's level, closed (the owner: "maybe you do level").
SCHOOL_LEVELS = ("elementary", "middle", "high", "college", "training")

#: The person form's categories -> the roster's relationship
#: (`focus_candidate.FOCUS_RELATIONSHIPS`).
CATEGORY_RELATIONSHIP = {"self": None, "spouse": "spouse", "child": "child",
                         "parent": "parent", "sibling": "sibling",
                         "grandparent": "grandparent", "other": "other"}
SIDES = {"maternal": "maternal", "paternal": "paternal", "mom": "maternal",
         "dad": "paternal", "": ""}

#: The word he calls a person by, read for its gender (v358's
#: `relation_words` field) — never guessed from anything else.
WORD_GENDER = {"dad": "male", "father": "male", "grandpa": "male", "grandfather": "male",
               "brother": "male", "son": "male", "husband": "male",
               "mom": "female", "mother": "female", "grandma": "female",
               "grandmother": "female", "sister": "female", "daughter": "female",
               "wife": "female"}

EDIT_SCOPE = "landmarks/{domain}"
PERSON_SCOPE = "cornerstones/others"
FORM_MARK = "owner"
_US_COUNTRY = {"united states", "usa", "us", "u.s.", "united states of america"}


class LandmarkEditError(ValueError):
    """A form payload that must not file. Raised before any write."""


# --------------------------------------------------------------------------
# Pure: dates and records
# --------------------------------------------------------------------------


def form_date(value: object) -> dict | None:
    """A form date — ``"1989"``, ``"1989-06"``, ``"1989-06-01"`` or
    ``{"year", "month", "day"}`` (day optional) — as a stated, certain
    `chronology` record at the grain he gave. ``None`` when empty."""
    if isinstance(value, dict):
        year = collapsed_text(value.get("year"))
        month = collapsed_text(value.get("month"))
        day = collapsed_text(value.get("day"))
        if not year:
            return None
        text = year
        if month:
            text += f"-{int(month):02d}"
            if day:
                text += f"-{int(day):02d}"
    else:
        text = collapsed_text(value)
    if not text:
        return None
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", text):
        raise LandmarkEditError(f"not a date the form gives: {text!r}")
    parsed = chrono.parse_edtf(text, basis="stated")
    if parsed is None:
        raise LandmarkEditError(f"not a date: {text!r}")
    record = chrono.normalized_date(parsed.to_dict()) or parsed.to_dict()
    record["confidence"] = "certain"
    record["basis"] = "stated"
    return record


def _place(city: object, state: object, country: object) -> str:
    """``"San Diego, California"`` / ``"Solothurn, Switzerland"`` — the city
    field's own shape (`timeline_views.residence_fields` reads it back)."""
    parts = [collapsed_text(city), collapsed_text(state)]
    body = collapsed_text(country)
    if body and body.casefold() not in _US_COUNTRY:
        parts.append(body)
    return ", ".join(part for part in parts if part)


def _span(stay: dict) -> tuple[dict, bool]:
    start = form_date(stay.get("from"))
    ongoing = bool(stay.get("still_here"))
    end = None if ongoing else form_date(stay.get("to"))
    span = {}
    if start:
        span["start"] = start
    if end:
        span["end"] = end
    if start and end and chrono.from_dict(end).latest < chrono.from_dict(start).earliest:
        raise LandmarkEditError("a stay cannot end before it starts")
    return span, ongoing


#: What each kind's form controls — everything else the drawn entry carried
#: (``place_ref`` above all) is kept as it was.
FORM_KEYS = {
    "residences": ("label", "nickname", "address", "city", "link", "household", "note"),
    "schools": ("label", "name", "level", "grades", "place", "link", "note"),
    "work": ("label", "what", "where", "note"),
}
_NEVER_CARRIED = ("span", "date", "span_alternates", "date_alternates", "ref", "source_ids",
                  "ongoing", "none", "skipped", "domain")


def build_record(kind: str, fields: object, stay: object, *, carried: object = None) -> dict:
    """The one record a form files for ONE stay. PURE.

    ``carried`` is the drawn entry the form was opened on; the keys the form
    does not control are kept from it (a residence's ``place_ref``)."""
    if kind not in FORM_KINDS:
        raise LandmarkEditError(f"the form does not edit {kind!r}")
    f = fields if isinstance(fields, dict) else {}
    text = {key: collapsed_text(value) for key, value in f.items() if isinstance(value, (str, int))}
    domain = FILED_DOMAIN[kind]
    record: dict = {}
    if isinstance(carried, dict):
        for key, value in carried.items():
            if key not in _NEVER_CARRIED and key not in FORM_KEYS[domain]:
                record[key] = value
    record["domain"] = domain
    if domain == "residences":
        nickname = text.get("nickname") or text.get("area")
        address = text.get("address")
        place = _place(text.get("city"), text.get("state"), text.get("country"))
        label = nickname or address or place
        if not label:
            raise LandmarkEditError("a home needs a nickname, an address or a city")
        record.update({"label": label})
        for key, value in (("nickname", nickname), ("address", address), ("city", place),
                           ("link", text.get("link")), ("household", text.get("household")),
                           ("note", text.get("note"))):
            if value:
                record[key] = value
    elif domain == "schools":
        name = text.get("name")
        if not name:
            raise LandmarkEditError("a school needs its name")
        level = text.get("level", "").casefold()
        if level and level not in SCHOOL_LEVELS:
            raise LandmarkEditError(f"a school's level is one of {', '.join(SCHOOL_LEVELS)}")
        record.update({"label": name, "name": name})
        place = _place(text.get("city"), text.get("state"), text.get("country"))
        for key, value in (("level", level), ("grades", text.get("grades")), ("place", place),
                           ("link", text.get("link")), ("note", text.get("note"))):
            if value:
                record[key] = value
    else:  # work
        employer = text.get("employer")
        if not employer:
            raise LandmarkEditError("work needs the employer")
        record.update({"label": employer, "what": text.get("role") or employer})
        place = _place(text.get("city"), text.get("state"), text.get("country"))
        if place:
            record["where"] = place
        if text.get("note"):
            record["note"] = text["note"]
    span, ongoing = _span(stay if isinstance(stay, dict) else {})
    if span:
        record["span"] = span
    if ongoing:
        record["ongoing"] = True
    return record


def comparable(entry: object) -> str:
    """One entry reduced to what a form could have typed — for "unchanged"."""
    row = entry if isinstance(entry, dict) else {}
    keep = {key: value for key, value in row.items()
            if key not in ("ref", "source_ids", "span_alternates", "date_alternates", "domain")}
    span = keep.pop("span", None) or {}
    keep["span"] = {bound: (span.get(bound) or {}).get("best") for bound in ("start", "end")}
    keep["ongoing"] = bool(keep.get("ongoing"))
    return json.dumps(keep, sort_keys=True, ensure_ascii=False)


def edit_digest(record: dict, replaces: object) -> str:
    """The filed source's identity: the record plus the tellings it replaces,
    so a retry after a crash files the same source, and an edit back to an
    earlier value is a new telling rather than a superseded one."""
    payload = json.dumps({"verb": "landmark-edit", "record": record,
                          "replaces": sorted(set(replaces or ()))},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ref_of(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    domain = collapsed_text(value.get("domain"))
    key = value.get("entry_key")
    slot = value.get("slot")
    if not domain or not isinstance(key, str) or not isinstance(slot, int):
        return None
    return {"domain": domain, "entry_key": key, "slot": slot}


# --------------------------------------------------------------------------
# The vault: the stay a ref names, as drawn right now
# --------------------------------------------------------------------------


def _bound(vault_root: object):
    import timeline  # noqa: PLC0415

    root = Path(str(vault_root)).expanduser().resolve()
    if timeline._projection_vault_root().expanduser().resolve() != root:  # noqa: SLF001
        raise LandmarkEditError("landmark-edit must run against the vault timeline is bound to")
    return root, timeline


def drawn_with_refs(vault_root: object) -> dict:
    """``{(domain, entry_key, slot): entry}`` — the drawing, keyed (pure read)."""
    import landmark_projection as lp  # noqa: PLC0415
    import temporal_store as store  # noqa: PLC0415

    index = store.fold_active_index(vault_root)
    drawn = lp.project_landmark_entries(index, sources=lp.load_landmark_sources(vault_root),
                                        owner_names=lp.owner_names_for(vault_root),
                                        with_refs=True)
    out = {}
    for entries in (drawn.get("domains") or {}).values():
        for entry in entries:
            ref = entry.get("ref") or {}
            out[(ref.get("domain"), ref.get("entry_key"), ref.get("slot"))] = entry
    return out


def _slot_sources(vault_root: object, ref: dict) -> set[str]:
    import landmark_projection as lp  # noqa: PLC0415

    return lp.entry_source_ids(lp.load_landmark_sources(vault_root), domain=ref["domain"],
                               entry_key=ref["entry_key"], slot=ref["slot"])


def _retire(vault_root: object, ref: dict, reason: str) -> str | None:
    import landmark_projection as lp  # noqa: PLC0415

    correction = lp.retire_entry(vault_root, domain=ref["domain"], entry_key=ref["entry_key"],
                                 slot=ref["slot"], reason=reason)
    return getattr(correction, "correction_id", None) if correction is not None else None


# --------------------------------------------------------------------------
# landmark-edit
# --------------------------------------------------------------------------


def edit_landmark(vault_root: object, payload: object) -> dict:
    """File one landmark form. ``payload``:

    ``{"mode": "save", "kind", "fields": {...}, "stays": [{"ref"?, "from",
    "to", "still_here"}], "retire": [ref, ...]}`` — every stay the form holds,
    each with the ref it was opened on (none for a new stay), and the refs of
    stays the form removed;
    ``{"mode": "delete", "refs": [ref, ...]}`` — the whole landmark;
    ``{"mode": "undo", "corrections": [correction_id, ...]}``.

    Returns ``{"mode", "filed": [...], "retired": [...], "corrections":
    [...], "unchanged": n}``. Publishes once, at the end.
    """
    body = payload if isinstance(payload, dict) else {}
    mode = collapsed_text(body.get("mode")) or "save"
    root, timeline = _bound(vault_root)
    summary: dict = {"mode": mode, "filed": [], "retired": [], "corrections": [], "unchanged": 0}
    with timeline.landmark_publication_batch(root):
        if mode == "undo":
            _undo(root, body, summary, scope_hint="landmark-edit")
        elif mode == "delete":
            refs = [_ref_of(ref) for ref in body.get("refs") or ()]
            if not refs or None in refs:
                raise LandmarkEditError("a delete names every stay of the landmark by its ref")
            for ref in refs:
                correction = _retire(root, ref, "deleted by the owner on the landmark form "
                                                "(landmark-edit; undo reinstates it)")
                summary["retired"].append(ref)
                if correction:
                    summary["corrections"].append(correction)
            timeline.redraw_landmarks()
        elif mode == "save":
            _save(root, timeline, body, summary)
        else:
            raise LandmarkEditError(f"unknown mode {mode!r}")
    return summary


def _save(root: Path, timeline, body: dict, summary: dict) -> None:
    kind = collapsed_text(body.get("kind"))
    if kind not in FORM_KINDS:
        raise LandmarkEditError(f"the form edits {', '.join(FORM_KINDS)}, not {kind!r}")
    stays = [stay for stay in body.get("stays") or () if isinstance(stay, dict)] or [{}]
    drawn = drawn_with_refs(root)
    plan = []
    for stay in stays:
        ref = _ref_of(stay.get("ref")) if stay.get("ref") is not None else None
        if stay.get("ref") is not None and ref is None:
            raise LandmarkEditError("a stay's ref is {domain, entry_key, slot}")
        current = drawn.get((ref["domain"], ref["entry_key"], ref["slot"])) if ref else None
        record = build_record(kind, body.get("fields"), stay, carried=current)
        plan.append((ref, current, record))
    retire = [_ref_of(ref) for ref in body.get("retire") or ()]
    if None in retire:
        raise LandmarkEditError("a removed stay is named by its ref")
    for ref, current, record in plan:
        if current is not None and comparable(current) == comparable({**record, "domain": None}):
            summary["unchanged"] += 1
            continue
        replaces = _slot_sources(root, ref) if ref else set()
        if ref:
            correction = _retire(root, ref, "edited by the owner on the landmark form "
                                            "(landmark-edit): his record replaces this stay")
            summary["retired"].append(ref)
            if correction:
                summary["corrections"].append(correction)
        timeline.save_landmark(record["domain"], dict(record), exact=True,
                               digest_override=edit_digest(record, replaces))
        summary["filed"].append(record)
    for ref in retire:
        correction = _retire(root, ref, "removed by the owner on the landmark form (landmark-edit)")
        summary["retired"].append(ref)
        if correction:
            summary["corrections"].append(correction)
    timeline.redraw_landmarks()


def _undo(root: Path, body: dict, summary: dict, *, scope_hint: str) -> None:
    import temporal_store as store  # noqa: PLC0415

    ids = sorted({collapsed_text(c) for c in body.get("corrections") or () if collapsed_text(c)})
    if not ids:
        raise LandmarkEditError("an undo names the corrections it reinstates")
    already = set(store.reinstated_correction_ids(root))
    todo = [c for c in ids if c not in already]
    if todo:
        record = store.reinstate_corrections(
            root, todo, reason=f"undone by the owner ({scope_hint})",
            title=f"Undo {len(todo)} {scope_hint} correction(s)")
        summary["corrections"].append(record.correction_id)
    summary["reinstated"] = todo
    import timeline  # noqa: PLC0415

    timeline.redraw_landmarks()


# --------------------------------------------------------------------------
# person-edit
# --------------------------------------------------------------------------


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "person"


def _person_slug(person_ref: str, name: str) -> str:
    if person_ref.startswith("person/"):
        return person_ref.partition("/")[2]
    return _slugify(name)


def _entry_key(label: str) -> str:
    return label.strip().casefold()


def _supersede_landmark_dates(root: Path, domain: str, label: str, *, event_kinds: tuple,
                              reason: str) -> str | None:
    """Supersede the active DATE claims of the landmark entry ``label`` names
    in ``domain`` (never its identity claim), so the form's date is the only
    landmark date that entry holds. ``None`` when there were none."""
    import landmark_projection as lp  # noqa: PLC0415
    import temporal_store as store  # noqa: PLC0415

    ids = lp.entry_source_ids(lp.load_landmark_sources(root), domain=domain,
                              entry_key=_entry_key(label))
    if not ids:
        return None
    index = store.fold_active_index(root)
    claims = [row["claim_id"] for row in store.active_claims(index)
              if row.get("claim_type") == "date"
              and collapsed_text((row.get("source_ref") or {}).get("source_id")) in ids
              and (not event_kinds or collapsed_text(row.get("event_kind")) in event_kinds)]
    if not claims:
        return None
    return store.supersede_claims(root, sorted(claims), reason=reason,
                                  scope=f"landmarks/{domain}").correction_id


def edit_person(vault_root: object, payload: object) -> dict:
    """File one person form. ``payload``:

    ``{"mode": "save", "person_ref", "name", "category", "relation_word",
    "side", "born", "died", "married": {"date", "to"}, "divorced"}`` — each
    date a form date (day optional); an empty field leaves what is there;
    ``{"mode": "delete", "person_ref", "milestone", "claim_ids": [...]}`` —
    an Others row's 🗑;
    ``{"mode": "undo", "corrections": [...]}``.
    """
    body = payload if isinstance(payload, dict) else {}
    mode = collapsed_text(body.get("mode")) or "save"
    root, timeline = _bound(vault_root)
    summary: dict = {"mode": mode, "roster": None, "filed": [], "corrections": []}
    with timeline.landmark_publication_batch(root):
        if mode == "undo":
            _undo(root, body, summary, scope_hint="person-edit")
        elif mode == "delete":
            _delete_other(root, body, summary)
            timeline.redraw_landmarks()
        elif mode == "save":
            _save_person(root, timeline, body, summary)
        else:
            raise LandmarkEditError(f"unknown mode {mode!r}")
    return summary


def _delete_other(root: Path, body: dict, summary: dict) -> None:
    import temporal_store as store  # noqa: PLC0415

    wanted = {collapsed_text(c) for c in body.get("claim_ids") or () if collapsed_text(c)}
    if not wanted:
        raise LandmarkEditError("an Others delete names the claims behind its date")
    index = store.fold_active_index(root)
    active = {row["claim_id"] for row in store.active_claims(index)}
    claims = sorted(wanted & active)
    if claims:
        correction = store.supersede_claims(
            root, claims, scope=PERSON_SCOPE,
            reason=(f"removed by the owner from Others ({collapsed_text(body.get('milestone'))} "
                    f"of {collapsed_text(body.get('person_ref'))}); person-edit undo reinstates it"))
        summary["corrections"].append(correction.correction_id)
    summary["retired_claims"] = claims


def _save_person(root: Path, timeline, body: dict, summary: dict) -> None:
    import entity_verdict as ev  # noqa: PLC0415
    import entity_roster as er  # noqa: PLC0415
    from lifehug_core import read_json, write_json  # noqa: PLC0415

    person_ref = collapsed_text(body.get("person_ref"))
    name = collapsed_text(body.get("name"))
    category = collapsed_text(body.get("category")).casefold() or ("self" if person_ref == "self" else "")
    if category not in CATEGORY_RELATIONSHIP:
        raise LandmarkEditError(f"a person's category is one of {', '.join(CATEGORY_RELATIONSHIP)}")
    is_self = category == "self" or person_ref == "self"
    if not is_self and not name:
        raise LandmarkEditError("a person needs their full name")
    relationship = CATEGORY_RELATIONSHIP[category]
    word = " ".join(collapsed_text(body.get("relation_word")).split())
    side = SIDES.get(collapsed_text(body.get("side")).casefold())
    if side is None:
        raise LandmarkEditError("a grandparent's side is mom's or dad's")
    if relationship != "grandparent":
        side = ""
    dates = {key: form_date(body.get(key)) for key in ("born", "died", "divorced")}
    married = body.get("married") if isinstance(body.get("married"), dict) else {}
    dates["married"] = form_date(married.get("date"))
    partner = collapsed_text(married.get("to"))

    if not is_self:
        slug = _person_slug(person_ref, name)
        path = er.roster_file("person")
        roster = read_json(path, default=None) or {}
        existing = next((e for e in roster.get("entities") or ()
                         if isinstance(e, dict) and e.get("slug") == slug), None)
        verdict = (existing or {}).get("owner_verdict") or "clear"
        entity = ev.apply_verdict(
            "person", slug, verdict if verdict in ev.VERDICTS else "clear",
            relationship=relationship, ensure=True, name=name,
            born=chrono.to_edtf(chrono.from_dict(dates["born"])) if dates["born"] else None,
            died=chrono.to_edtf(chrono.from_dict(dates["died"])) if dates["died"] else None,
            living=False if dates["died"] else None,
            grandparent_side=side, relation_word=word)
        # The full name he typed is the row's name; the old one stays an alias.
        if name and collapsed_text(entity.get("name")) != name:
            data = read_json(path, default=None) or {}
            for row in data.get("entities") or ():
                if isinstance(row, dict) and row.get("slug") == slug:
                    old = collapsed_text(row.get("name"))
                    row["name"] = name
                    aliases = [a for a in row.get("aliases") or () if collapsed_text(a) != name]
                    if old and old not in aliases:
                        aliases.append(old)
                    row["aliases"] = aliases
                    entity = row
            write_json(path, data)
        gender = WORD_GENDER.get(word.casefold())
        if gender:
            import relation_words as rw  # noqa: PLC0415

            try:
                rw.record_relation_gender(root, slug, gender, basis=rw.BASIS_STATED)
            except ValueError:
                pass
        summary["roster"] = {"slug": slug, "relationship": entity.get("relationship"),
                             "grandparent_side": entity.get("grandparent_side"),
                             "relation_word": entity.get("relation_word")}
    label = name or "self"
    reason = "replaced by the owner's person form (person-edit)"
    if dates["born"] and not is_self:
        domain = "children" if relationship == "child" else "family"
        _supersede_landmark_dates(root, domain, label, event_kinds=("birth",), reason=reason)
        record = {"domain": domain, "label": label, "who": label, "date": dates["born"],
                  "form": FORM_MARK}
        if domain == "family" and relationship:
            record["relation"] = relationship
        timeline.save_landmark(domain, record, exact=True)
        summary["filed"].append(record)
    if dates["born"] and is_self:
        born = chrono.from_dict(dates["born"])
        parts = (born.best or "").split("-")
        record = {"domain": "birth", "year": parts[0], "date": dates["born"], "form": FORM_MARK}
        if len(parts) > 1:
            record["month"] = parts[1]
        if len(parts) > 2:
            record["day"] = parts[2]
        _supersede_landmark_dates(root, "birth", "", event_kinds=(), reason=reason)
        timeline.save_landmark("birth", record, exact=True)
        summary["filed"].append(record)
    if dates["died"] and not is_self:
        _supersede_landmark_dates(root, "losses", label, event_kinds=("death",), reason=reason)
        record = {"domain": "losses", "label": label, "who": label, "date": dates["died"],
                  "form": FORM_MARK}
        timeline.save_landmark("losses", record, exact=True)
        summary["filed"].append(record)
    if (dates["married"] or dates["divorced"]) and (partner or not is_self):
        to = partner or ("" if is_self else "")
        record = {"domain": "partnerships", "label": to or f"{label}'s partner", "event": "married",
                  "form": FORM_MARK}
        if to:
            record["who"] = to
        if not is_self:
            record["subject"] = label
        if dates["married"]:
            record["date"] = dates["married"]
        if dates["divorced"]:
            record["span"] = {"end": dates["divorced"]}
        _supersede_landmark_dates(root, "partnerships", record["label"], event_kinds=(), reason=reason)
        timeline.save_landmark("partnerships", record, exact=True)
        summary["filed"].append(record)
    timeline.redraw_landmarks()


# --------------------------------------------------------------------------
# CLI seam (`lifehug.py landmark-edit` / `person-edit`, JSON on stdin)
# --------------------------------------------------------------------------


def main(verb: str, raw: str, vault_root: object) -> tuple[int, dict]:
    try:
        payload = json.loads(raw or "{}")
    except ValueError as exc:
        return 1, {"error": f"{verb} reads one JSON payload on stdin ({exc})"}
    if not isinstance(payload, dict):
        return 1, {"error": f"{verb} reads one JSON OBJECT on stdin"}
    try:
        if verb == "landmark-edit":
            return 0, edit_landmark(vault_root, payload)
        return 0, edit_person(vault_root, payload)
    except LandmarkEditError as exc:
        return 1, {"error": str(exc)}


__all__ = [
    "CATEGORY_RELATIONSHIP", "FORM_KINDS", "LandmarkEditError", "OWNER_EDIT_IS_EXACT",
    "SCHOOL_LEVELS", "build_record", "comparable", "drawn_with_refs", "edit_digest",
    "edit_landmark", "edit_person", "form_date", "main",
]
