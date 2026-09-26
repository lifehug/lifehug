"""Landmark and cornerstone VIEWS — two read models on the calculated projection.

Owner design, 2026-09-25 (v360): on the Timeline, below the chart, two
square buttons — Landmarks and Cornerstones — each open a VIEW of what he has
given. This module is the framework half: it publishes the two views as
additive keys on the calculated projection (``landmarks_view`` and
``cornerstones_view``, beside v358's ``relation_words``), and a host renders
them. Nothing here decides a placement, mints a card or writes a receipt; both
views are display decisions over the SAME generation, so
`temporal_timeline.CALCULATION_RULE_VERSION` does not move.

**Revision (2026-09-25, "Landmark and cornerstone views" batch):** the
Landmarks view now shows SPAN kinds only — homes, schools, work, mission (a
mention-opened kind) and military — and hides any kind with no entries
outright (no "Military — none" row). Partnerships/marriage, children, family,
losses and birth are no longer Landmarks lanes; they ride the Cornerstones
view instead. A single ``cornerstone_markers`` row is published pinned at the
top of the Landmarks lanes: one ◆ per required-set birth/wedding/death, a
wedding a plain ◆ like any other (no line — "marriage is a discrete date"),
omitting anything dated before his own birth so the axis never reads a
parent's or grandparent's cornerstone as his own (:func:`cornerstone_markers`).
The Cornerstones view gains an ``others``
section: another person's cornerstone-type event (birth, wedding, divorce,
death), or another person's partnership, shown only when he gave a discrete
(stated or documented, not story-derived) date (:func:`_others_section`). His
kids' weddings and divorces join the REQUIRED set once mentioned, never as a
default question. Business partners (a company or fund a `partnerships`
entry misfiles) never appear in either view.

**The landmarks view** (:func:`landmarks_view`) is every landmark entry he gave,
after the merge records (`landmark_projection.load_landmark_sources` applies
them; `landmark_projection.project_landmark_entries` draws them), grouped by
domain. Each landmark carries its stay(s) at the grain he gave; a place he
lived in twice is ONE landmark with both stays. Residences always carry
nickname, address, city, state, country — read from the entry's own fields,
never invented, and ``None`` where he has not said, so a missing field shows.
The three chain domains (`landmarks_interaction.CHAIN_DOMAINS`) get their
gaps: a hole of more than :data:`GAP_MONTHS` months between consecutive stays
(:data:`A_GAP_IS_A_HOLE_OF_MORE_THAN_TWO_MONTHS`), unless another landmark
covers it (:data:`A_COVERED_STRETCH_IS_NOT_A_GAP` — his mission). A gap never
becomes a card here; `landmarks_interaction.residence_gaps` stays the one
residence-gap UNKNOWN, and a residence gap row names its key when that
year-grain unknown exists for the same hole.

**The cornerstones view** (:func:`cornerstones_view`) is one row per person in
the cornerstone set (`cornerstones.CORNERSTONES`: the owner, spouse, children,
parents, siblings, grandparents) with born / married / divorced / died, each
with its grain and a status (:data:`CELL_STATUSES`). Who is who is
`cornerstones.Relations`; what each is called is `relation_words` plus what he
calls them (`roster_relations.with_called_by`: "Dad", "Mom", "AJ").

Pure. Synthetic data only in its tests (`tests/test_v360_views.py`); never
references any real vault.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import cornerstones as cs  # noqa: E402
import landmark_identity as lid  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from temporal_claims import collapsed_text, normalized_mention_key  # noqa: E402

#: The two views' own rule identity. A display rule, like `relation_words`'s.
TIMELINE_VIEWS_RULE_VERSION = "timeline-views:1"

LANDMARKS_VIEW_KEY = "landmarks_view"
CORNERSTONES_VIEW_KEY = "cornerstones_view"

# --------------------------------------------------------------------------
# The rules, as the text every seat cites
# --------------------------------------------------------------------------

#: How long a hole must be before it is a gap.
GAP_MONTHS = 2

A_GAP_IS_A_HOLE_OF_MORE_THAN_TWO_MONTHS = (
    "in a chain domain (residences, schools, work), a gap is a hole of more "
    "than two whole months between the end of one stay and the start of the "
    "next, after overlapping stays are merged; nothing before the first stay "
    "and nothing after the last is a gap; a gap is SHOWN, never asked"
)

A_COVERED_STRETCH_IS_NOT_A_GAP = (
    "a stretch another landmark accounts for — a mission, military service — "
    "is covered, not a gap: a hole inside it is marked covered_by that "
    "landmark, and a stay inside it is marked within it"
)

A_HOME_SHOWS_EVERY_FIELD = (
    "a residence always carries nickname, address, city, state, country and "
    "its stays; each is read from the entry's own fields and is null when he "
    "has not said it, so the view shows what is missing; a country is derived "
    "only where it is unambiguous (a US state means the United States; a city "
    "field or address naming a country means that country)"
)

#: The owner's own words for the design.
OWNER_WORDS = (
    "In my case you should have everything",
)

#: v360 (owner, 2026-09-25) (the edit forms). Every stay the view publishes names
#: the interval-aware key it was drawn under, so ▸ can open a form for exactly
#: that stay and ▶ can file the owner's edit against exactly it.
A_STAY_IS_NAMED_BY_ITS_REF = (
    "every published stay carries ref {domain, entry_key, slot} — the key "
    "`landmark_projection.stay_slots` drew it under — and every landmark "
    "carries refs, one per drawn entry, dated or not; a host edits or deletes "
    "a landmark by naming them, never by its label"
)

#: v360 (owner, 2026-09-25): "Mission homes are listed only under Missions, with
#: one 'on your mission' line in Homes."
A_MISSION_HOME_IS_LISTED_UNDER_MISSIONS = (
    "a residence whose every stay falls inside his mission stretch is listed "
    "only in the Missions lane; Homes shows the stretch as ONE covered line "
    "(◇ on your mission · Aug 2000 – Jun 2002) in its place"
)

# --------------------------------------------------------------------------
# Domains
# --------------------------------------------------------------------------

#: Display order and names. Presentation only; the slug is the ladder's.
#: **Span kinds only** (timeline-views:1 revision, 2026-09-25): partnerships,
#: children, family, losses and birth are cornerstone material now, not
#: Landmarks lanes — see :func:`cornerstones_view` and :func:`with_views`.
DOMAIN_ORDER = ("residences", "schools", "work", "missions", "military")
DOMAIN_LABELS = {
    "residences": "Homes",
    "schools": "Schools",
    "work": "Work",
    "missions": "Missions",
    "military": "Military",
}
#: A domain the Landmarks view never shows, even if a fold or a caller still
#: files entries there — removed defensively rather than trusted to be empty.
NON_SPAN_DOMAINS = ("partnerships", "children", "family", "losses", "birth")
CHAIN_DOMAINS = tuple(li.CHAIN_DOMAINS)

#: The node event kind a domain's landmark folds into (for its Play and node).
EVENT_KIND_OF_DOMAIN = {"residences": "residence", "schools": "school", "work": "job",
                        "missions": "mission", "military": "military"}

#: How each chain domain's gap reads. Work gaps are neutral on purpose.
GAP_WORDS = {"residences": "nothing recorded", "schools": "nothing recorded",
             "work": "nothing recorded"}

#: A landmark that COVERS a stretch of the chains: its own domain, or words
#: that name a mission (`landmark_opportunities` keys the mission domain the
#: same way).
COVERING_DOMAINS = ("missions", "military")
_MISSION_RE = re.compile(r"\bmission(?:ary|aries|s)?\b", re.IGNORECASE)
COVERED_WORDS = {"missions": "on your mission", "military": "in the military"}

# --------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------


def _text(entry: object, key: str) -> str | None:
    value = entry.get(key) if isinstance(entry, dict) else None
    body = collapsed_text(value) if isinstance(value, str) else ""
    return body or None


def _slug(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", lid.fold(text)).strip("-")[:48] or "entry"


def _bound(record: object, *, end: bool) -> tuple[str | None, str | None]:
    """``(iso, grain)`` for one span bound: the earliest of a start, the latest
    of an end, at the grain he gave. ``(None, None)`` when unreadable."""
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None, None
    value = (parsed.latest or parsed.earliest) if end else (parsed.earliest or parsed.latest)
    if not value:
        return None, None
    grain = {4: "year", 7: "month", 10: "day"}.get(len(value), parsed.granularity)
    return value, grain


def _approximate(record: object) -> bool:
    parsed = chrono.from_dict(record)
    return bool(parsed and parsed.confidence not in ("certain",))


def _month_record(iso: str, *, end: bool = False) -> object:
    """A bare ISO bound as a record `chronology.gap_months` can read."""
    return chrono.parse_edtf(iso)


def _padded(iso: str, *, end: bool) -> str:
    """An ISO bound filled to a day, upward for an end, for ordering."""
    if len(iso) == 4:
        return f"{iso}-12-31" if end else f"{iso}-01-01"
    if len(iso) == 7:
        return f"{iso}-31" if end else f"{iso}-01"
    return iso


def months_between(end_iso: str, start_iso: str) -> int | None:
    """Whole months between one stay's END and a LATER stay's start
    (`chronology.gap_months`, which is order-blind); ``None`` when they
    overlap or the start is not after the end."""
    left, right = _month_record(end_iso), _month_record(start_iso)
    if left is None or right is None:
        return None
    if _padded(start_iso, end=False) <= _padded(end_iso, end=True):
        return None
    return chrono.gap_months(left, right)


def _later(a: str | None, b: str | None) -> str | None:
    """The later of two ISO ends."""
    if a is None:
        return b
    if b is None:
        return a
    return b if _padded(b, end=True) > _padded(a, end=True) else a


# --------------------------------------------------------------------------
# Residences: nickname, address, city, state, country
# --------------------------------------------------------------------------

#: Countries a residence's own text may name. A small closed list — a trailing
#: word that is not on it and not a US state is left alone rather than
#: guessed at (:data:`A_HOME_SHOWS_EVERY_FIELD`).
COUNTRIES = {
    "switzerland": "Switzerland", "germany": "Germany", "mexico": "Mexico",
    "canada": "Canada", "france": "France", "italy": "Italy", "austria": "Austria",
    "spain": "Spain", "england": "England", "united kingdom": "United Kingdom",
    "uk": "United Kingdom", "japan": "Japan", "australia": "Australia",
    "brazil": "Brazil", "united states": "United States", "usa": "United States",
    "us": "United States", "united states of america": "United States",
}
UNITED_STATES = "United States"

_POSTAL_RE = re.compile(r"\b(?:[A-Z]{1,2}-)?\d{4,5}(?:-\d{4})?\b")
_STATE_CODE_RE = re.compile(r"^\s*([A-Za-z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def _state_name(text: object) -> str | None:
    """A US state's display name from its name or postal code, else ``None``."""
    body = collapsed_text(text)
    if not body:
        return None
    match = _STATE_CODE_RE.match(body)
    token = match.group(1) if match else body
    folded = lid.canonical_region(token)
    if folded in lid.US_STATES.values():
        return " ".join(word.capitalize() for word in folded.split())
    return None


def _country_name(text: object) -> str | None:
    folded = " ".join(lid.fold(re.sub(r"\d", " ", str(text or ""))).split())
    folded = re.sub(r"^[a-z]\s+", "", folded)  # "D-88046 ..." leaves a stray "d"
    return COUNTRIES.get(folded)


def residence_fields(entry: object) -> dict:
    """:data:`A_HOME_SHOWS_EVERY_FIELD`, for one drawn residence entry.

    ``{"nickname", "address", "address_full", "postal_code", "city", "state",
    "country"}``. ``address`` is the street line (the address up to its first
    comma); ``address_full`` is exactly what he gave.
    """
    row = entry if isinstance(entry, dict) else {}
    address_full = _text(row, "address")
    city_field = _text(row, "city")
    parts = [part.strip() for part in (address_full or "").split(",") if part.strip()]
    street = parts[0] if parts else None
    city = state = country = None
    if city_field:
        city_parts = [part.strip() for part in city_field.split(",") if part.strip()]
        city = city_parts[0] if city_parts else None
        for tail in city_parts[1:]:
            state = state or _state_name(tail)
            country = country or _country_name(tail)
        if city and (_state_name(city) or _country_name(city)):
            # "Arizona" alone in the city field is a state, not a city.
            state = state or _state_name(city)
            country = country or _country_name(city)
            city = None
    for part in parts[1:]:
        state = state or _state_name(part)
        country = country or _country_name(part)
    if city is None and len(parts) > 1:
        candidate = _POSTAL_RE.sub("", parts[-2] if len(parts) > 2 else parts[1]).strip()
        if candidate and not _state_name(candidate) and not _country_name(candidate):
            city = candidate
    if len(parts) == 1 and street and not re.search(r"\d", street):
        # A bare place ("San Diego") is not a street line.
        street = None
    if state and not country:
        country = UNITED_STATES
    postal = None
    for part in parts[1:]:
        found = _POSTAL_RE.search(part)
        if found:
            postal = found.group(0)
    return {
        "nickname": _text(row, "nickname"),
        "address": street,
        "address_full": address_full,
        "postal_code": postal,
        "city": city,
        "state": state,
        "country": country,
    }


# --------------------------------------------------------------------------
# Landmarks: entries -> landmarks with stays
# --------------------------------------------------------------------------


def _stay_of(entry: dict) -> dict | None:
    """One drawn entry's stay: its span, or its single date, at its grain.

    With the drawing's ``ref`` (`landmark_projection.project_landmark_entries`
    ``with_refs``) the stay carries it, so the edit form can name exactly this
    stay back to `landmark_edit` (:data:`A_STAY_IS_NAMED_BY_ITS_REF`)."""
    stay = _bare_stay_of(entry)
    if stay is not None and isinstance(entry.get("ref"), dict):
        stay["ref"] = dict(entry["ref"])
    return stay


def _bare_stay_of(entry: dict) -> dict | None:
    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    ongoing = bool(entry.get("ongoing"))
    start, start_grain = _bound(span.get("start"), end=False) if span.get("start") else (None, None)
    end, end_grain = _bound(span.get("end"), end=True) if span.get("end") else (None, None)
    if start or end:
        return {"start": start, "start_grain": start_grain,
                "end": end, "end_grain": end_grain,
                "ongoing": ongoing and end is None,
                "approximate": _approximate(span.get("start")) or _approximate(span.get("end")),
                "point": False}
    date = entry.get("date")
    if isinstance(date, dict):
        value, grain = _bound(date, end=False)
        if value:
            latest, _ = _bound(date, end=True)
            return {"start": value, "start_grain": grain,
                    "end": latest if latest != value else value, "end_grain": grain,
                    "ongoing": False, "approximate": _approximate(date), "point": True}
    return None


#: The words each kind's edit form prefills from (v360, owner 2026-09-25).
GENERIC_FIELDS = ("who", "subject", "what", "where", "name", "relation", "place")
EDITABLE_FIELDS_OF = {
    "schools": ("name", "level", "grades", "place", "link", "note"),
    "work": ("what", "where", "note"),
    "missions": ("what", "where", "place", "note"),
    "military": ("what", "where", "branch", "note"),
}


def _detail_of(domain: str, entry: dict) -> dict:
    """The per-stay words that differ between two stays of one landmark."""
    keys = {"schools": ("grades", "place"), "work": ("what", "where"),
            "residences": ("note", "household")}.get(domain, ("what", "where", "relation"))
    return {key: _text(entry, key) for key in keys if _text(entry, key)}


def _landmark_key(domain: str, entry: dict) -> str:
    if domain == "residences" and _text(entry, "place_ref"):
        return f"place:{_text(entry, 'place_ref')}"
    label = _text(entry, "label") or _text(entry, "who") or _text(entry, "name") \
        or _text(entry, "what") or ""
    return f"label:{lid.fold(label)}"


def _problems_of(entry: dict, stay: dict | None) -> list[str]:
    out: list[str] = []
    span = entry.get("span") if isinstance(entry.get("span"), dict) else None
    for bound in ("start", "end"):
        if span and span.get(bound) is not None and _bound(span.get(bound), end=bound == "end")[0] is None:
            out.append("unparsed_date")
    if stay is None:
        out.append("undated")
    elif not stay["point"]:
        if not stay["start"]:
            out.append("missing_start")
        if not stay["end"] and not stay["ongoing"]:
            out.append("missing_end")
    alternates = entry.get(li.SPAN_ALTERNATES_KEY) or entry.get(li.DATE_ALTERNATES_KEY)
    if alternates:
        out.append("alternate_dates")
    return list(dict.fromkeys(out))


def _alternates_of(entry: dict) -> list[dict]:
    """The dates a merge folded under the kept one — shown, never dropped."""
    out: list[dict] = []
    spans = entry.get(li.SPAN_ALTERNATES_KEY)
    if isinstance(spans, dict):
        for bound in ("start", "end"):
            for record in spans.get(bound) or ():
                value, grain = _bound(record, end=bound == "end")
                if value:
                    out.append({"bound": bound, "value": value, "grain": grain})
    for record in entry.get(li.DATE_ALTERNATES_KEY) or ():
        value, grain = _bound(record, end=False)
        if value:
            out.append({"bound": "date", "value": value, "grain": grain})
    return out


def _is_covering(domain: str, entry: dict) -> str:
    """The covering kind (``missions``/``military``) this entry is, or ``""``."""
    if domain in COVERING_DOMAINS:
        return domain
    words = " ".join(str(entry.get(key) or "") for key in ("label", "what", "name", "event"))
    return "missions" if _MISSION_RE.search(words) else ""


def _landmarks_of(domain: str, entries: list, *, nodes_by_kind: dict,
                  open_items: dict) -> list[dict]:
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for entry in entries or ():
        if not isinstance(entry, dict) or entry.get("none"):
            continue
        key = _landmark_key(domain, entry)
        if key == "label:" and domain != "birth":
            continue
        stay = _stay_of(entry)
        if key not in grouped:
            label = (_text(entry, "label") or _text(entry, "who") or _text(entry, "name")
                     or _text(entry, "what") or DOMAIN_LABELS.get(domain, domain))
            grouped[key] = {
                "entry_id": f"{domain}:{_slug(label)}",
                "domain": domain,
                "label": label,
                "stays": [],
                "problems": [],
                "alternates": [],
                "node_ids": [],
                "covering": _is_covering(domain, entry) or None,
                "refs": [],
            }
            if domain == "residences":
                grouped[key].update(residence_fields(entry))
                grouped[key]["link"] = _text(entry, "link")
                for field in ("household", "note", "place_ref"):
                    grouped[key][field] = _text(entry, field)
            else:
                for field in EDITABLE_FIELDS_OF.get(domain, GENERIC_FIELDS):
                    if _text(entry, field) and field != "label":
                        grouped[key][field] = _text(entry, field)
                place_text = _text(entry, "place") or _text(entry, "where")
                if place_text and domain in ("schools", "work"):
                    parsed = residence_fields({"city": place_text})
                    for field in ("city", "state", "country"):
                        grouped[key][field] = parsed.get(field)
            order.append(key)
        landmark = grouped[key]
        if isinstance(entry.get("ref"), dict) and entry["ref"] not in landmark["refs"]:
            landmark["refs"].append(dict(entry["ref"]))
        if domain == "residences":
            # A second stay that says more fills a field the first left empty.
            for field, value in residence_fields(entry).items():
                if landmark.get(field) is None and value is not None:
                    landmark[field] = value
        if stay is not None:
            stay = {**stay, **({"detail": _detail_of(domain, entry)}
                               if _detail_of(domain, entry) else {})}
            landmark["stays"].append(stay)
        for problem in _problems_of(entry, stay):
            if problem not in landmark["problems"]:
                landmark["problems"].append(problem)
        landmark["alternates"].extend(_alternates_of(entry))
    out: list[dict] = []
    for key in order:
        landmark = grouped[key]
        landmark["stays"].sort(key=lambda s: (s["start"] or s["end"] or "9999"))
        for index, stay in enumerate(landmark["stays"]):
            stay["stay_index"] = index
        if not landmark["stays"] and "undated" not in landmark["problems"]:
            landmark["problems"].append("undated")
        if landmark["stays"]:
            landmark["problems"] = [p for p in landmark["problems"] if p != "undated"]
        landmark["node_ids"] = _matching_nodes(domain, landmark, nodes_by_kind)
        landmark["play"] = _landmark_play(domain, landmark, open_items)
        out.append(landmark)
    # Oldest first; undated last, in filing order.
    out.sort(key=lambda row: (not row["stays"],
                              (row["stays"][0]["start"] or row["stays"][0]["end"] or "")
                              if row["stays"] else ""))
    _unique_ids(out)
    return out


def _unique_ids(rows: list[dict]) -> None:
    seen: dict[str, int] = {}
    for row in rows:
        base = row["entry_id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            row["entry_id"] = f"{base}-{seen[base]}"


def _matching_nodes(domain: str, landmark: dict, nodes_by_kind: dict) -> list[str]:
    """The fold's nodes this landmark drew — same label, same event kind."""
    kind = EVENT_KIND_OF_DOMAIN.get(domain)
    if not kind:
        return []
    want = lid.fold(landmark["label"])
    found = []
    for node in nodes_by_kind.get(kind, ()):
        subjects = [lid.fold(s) for s in node.get("subject_refs") or ()]
        if lid.fold(node.get("label")) == want or want in subjects:
            found.append(str(node.get("node_id")))
    return sorted(set(found))


def _landmark_play(domain: str, landmark: dict, open_items: dict) -> dict:
    """The work item open on this landmark's node, else its landmarks Play."""
    for node_id in landmark["node_ids"]:
        item = open_items.get(node_id)
        if item:
            return {"kind": "work_item", "work_item_id": item}
    return {"kind": "landmark", "domain": domain, "subject": landmark["label"]}


# --------------------------------------------------------------------------
# Gaps and covered stretches
# --------------------------------------------------------------------------


def covered_stretches(landmarks_by_domain: dict) -> list[dict]:
    """Every covering landmark's stays, merged where they touch (within
    :data:`GAP_MONTHS`) into one stretch per kind — the MTC and the mission
    field are one mission."""
    rows: list[tuple[str, str, str, dict]] = []
    for domain, landmarks in landmarks_by_domain.items():
        for landmark in landmarks:
            kind = landmark.get("covering")
            if not kind:
                continue
            for stay in landmark["stays"]:
                if stay["start"] and stay["end"]:
                    rows.append((stay["start"], stay["end"], kind, landmark))
    rows.sort(key=lambda row: row[0])
    stretches: list[dict] = []
    for start, end, kind, landmark in rows:
        ref = {"domain": landmark["domain"], "entry_id": landmark["entry_id"],
               "label": landmark["label"]}
        last = stretches[-1] if stretches else None
        if last is not None and last["kind"] == kind:
            gap = months_between(last["end"], start)
            if gap is None or gap <= GAP_MONTHS:
                last["end"] = _later(last["end"], end)
                if ref not in last["covered_by"]:
                    last["covered_by"].append(ref)
                continue
        stretches.append({"kind": kind, "start": start, "end": end,
                          "covered_by": [ref], "label": COVERED_WORDS[kind]})
    for index, stretch in enumerate(stretches):
        stretch["stretch_id"] = f"covered:{stretch['kind']}:{index}"
    return stretches


def _inside(start: str, end: str, stretch: dict, *, slack: int = GAP_MONTHS) -> bool:
    """Is ``start..end`` inside the stretch, give or take ``slack`` months?"""
    if _padded(start, end=False) < _padded(stretch["start"], end=False):
        before = chrono.gap_months(_month_record(start), _month_record(stretch["start"]))
        if before is None or before + 1 >= slack:
            return False
    if _padded(end, end=True) > _padded(stretch["end"], end=True):
        after = chrono.gap_months(_month_record(stretch["end"]), _month_record(end))
        if after is None or after + 1 >= slack:
            return False
    return True


def chain_rows(domain: str, landmarks: list[dict], stretches: list[dict], *,
               residence_gap_keys: dict | None = None) -> dict:
    """The domain's stays and gaps, oldest first.

    ``{"rows": [...], "gaps": [...], "covered": [...]}``; each row is
    ``{"kind": "stay"|"gap"|"covered", "start", "end", ...}``.

    A covering stretch (his mission) explains a real HOLE here — nothing to
    fill it, but not a problem either, so it draws ◇ rather than ░
    (:data:`A_COVERED_STRETCH_IS_NOT_A_GAP`). It no longer decorates a stay
    that already has its own data: once the stretch has its OWN lane
    (item 3, 2026-09-25 owner feedback — :func:`_mission_domain_row`), a
    redundant "covered" banner over stays that are simply THERE (Homes during
    his mission, in full) reads as a hatched box nobody asked for; a
    :func:`landmarks_view` chain domain's ordinary stays are always plain,
    whatever else covers their dates.
    """
    stays: list[tuple[str, str | None, dict, dict]] = []
    for landmark in landmarks:
        for stay in landmark["stays"]:
            if not stay["start"]:
                continue
            stays.append((stay["start"], stay["end"], landmark, stay))
    stays.sort(key=lambda row: (row[0][:7], row[0]))
    # A domain is not covered by its own covering landmark (the mission work
    # entry does not cover the work chain it is a link of).
    own = [s for s in stretches
           if not all(ref["domain"] == domain for ref in s["covered_by"])]
    rows: list[dict] = []
    gaps: list[dict] = []
    covered: list[dict] = []
    frontier: str | None = None
    frontier_landmark: dict | None = None
    open_ended = False
    for start, end, landmark, stay in stays:
        if frontier is not None and not open_ended:
            gap = months_between(frontier, start)
            if gap is not None and gap > GAP_MONTHS:
                row = {"kind": "gap", "start": frontier, "end": start, "months": gap,
                       "after": frontier_landmark["entry_id"] if frontier_landmark else None,
                       "before": landmark["entry_id"], "label": GAP_WORDS[domain]}
                cover = next((s for s in own if _inside(frontier, start, s)), None)
                if cover is not None:
                    # The covered line reads the stretch itself where it
                    # explains the hole ("on your mission · Aug 2000 – Jun
                    # 2002"), clipped to the hole it fills.
                    row["start"] = max(frontier, cover["start"], key=lambda v: _padded(v, end=False))
                    row["end"] = min(start, cover["end"], key=lambda v: _padded(v, end=True))
                    row["kind"] = "covered"
                    row["covered_by"] = cover["covered_by"]
                    row["stretch_id"] = cover["stretch_id"]
                    row["label"] = cover["label"]
                    if not any(c["stretch_id"] == cover["stretch_id"] for c in covered):
                        covered.append({"kind": "covered", "start": cover["start"], "end": cover["end"],
                                        "stretch_id": cover["stretch_id"], "label": cover["label"],
                                        "covered_by": cover["covered_by"]})
                elif residence_gap_keys and domain == "residences":
                    key = residence_gap_keys.get((frontier[:4], start[:4]))
                    if key:
                        row["unknown_key"] = key
                if row["kind"] == "gap":
                    gaps.append(row)
                rows.append(row)
        rows.append({"kind": "stay", "start": start, "end": end, "ongoing": stay["ongoing"],
                     "entry_id": landmark["entry_id"], "stay_index": stay["stay_index"]})
        later = _later(frontier, end or start)
        if later != frontier:
            frontier_landmark = landmark
        frontier = later
        if stay["ongoing"]:
            open_ended = True  # an open stay runs to today: nothing after it is a hole
    return {"rows": rows, "gaps": gaps, "covered": covered}


def _residence_gap_keys(domains: dict) -> dict:
    """`landmarks_interaction.residence_gaps`' own keys, by (end year, start
    year) — the ONE residence-gap unknown, named rather than redefined."""
    out: dict = {}
    try:
        rows = li.residence_gaps(domains)
    except Exception:  # noqa: BLE001 - a naming nicety never breaks the view
        return out
    for row in rows:
        years = row.get("years") or ()
        if len(years) == 2:
            out[(str(years[0]), str(years[1]))] = row.get("key")
    return out


def _mission_domain_row(stretches: list[dict], by_domain: dict) -> dict | None:
    """A mention-opened ``missions`` lane, built from the covered stretch —
    never filed as its own landmark entries (owner feedback item 3,
    2026-09-25): "his mission isn't filed as a missions-domain entry — it's
    the covered stretch built from the Missionary work entry + MTC school
    entry, with the MTC and Swiss/German stays nested."

    The nested stays are his RESIDENCE stays whose dates fall inside a
    ``missions``-kind stretch (:func:`covered_stretches`) — the finest-grain
    location record he has for that stretch — each copied into its own
    ``missions``-domain landmark (same fields, so a bar's tooltip reads the
    same "name · span · place") entirely separate from what still shows,
    undecorated, in Homes. ``None`` when nothing was ever covered (no mission
    mentioned) or nothing narrower nests inside it.
    """
    missions = [s for s in stretches if s["kind"] == "missions"]
    if not missions:
        return None
    residences = by_domain.get("residences") or []
    out_landmarks: list[dict] = []
    for stretch in missions:
        for landmark in residences:
            within = [stay for stay in landmark["stays"]
                     if stay["start"] and _inside(stay["start"], stay["end"] or stay["start"],
                                                  stretch, slack=1)]
            if not within:
                continue
            copy = dict(landmark)
            copy["entry_id"] = f"missions:{landmark['entry_id'].partition(':')[2] or landmark['entry_id']}"
            copy["domain"] = "missions"
            copy["stays"] = [{**stay, "stay_index": i} for i, stay in enumerate(within)]
            copy["covering"] = "missions"
            copy["play"] = {"kind": "landmark", "domain": "missions", "subject": copy["label"]}
            out_landmarks.append(copy)
    if not out_landmarks:
        return None
    out_landmarks.sort(key=lambda lm: lm["stays"][0]["start"] or "")
    _unique_ids(out_landmarks)
    rows = [{"kind": "stay", "start": stay["start"], "end": stay["end"], "ongoing": stay["ongoing"],
             "entry_id": lm["entry_id"], "stay_index": stay["stay_index"]}
            for lm in out_landmarks for stay in lm["stays"]]
    rows.sort(key=lambda r: r["start"] or "")
    return {"domain": "missions", "label": DOMAIN_LABELS.get("missions", "Missions"), "chain": False,
            "none": False, "landmarks": out_landmarks, "rows": rows, "gaps": [], "covered": []}


#: The words a marker's own label puts after who it is about.
MARKER_VERB = {"birth": "born", "wedding": "married", "death": "died"}
_MARKER_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _marker_date_text(iso: object) -> str:
    """``"21 Dec 2010"`` / ``"Dec 2010"`` / ``"2010"`` — mirrors the web's own
    ``view-dates.ts:shortDate`` so the two never drift."""
    body = collapsed_text(iso).split("/")[0].strip()
    if not body or body in ("..",):
        return ""
    parts = body.split("-")
    year = parts[0]
    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
        return f"{int(parts[2])} {_MARKER_MONTHS[int(parts[1]) - 1]} {year}"
    if len(parts) >= 2 and parts[1].isdigit():
        return f"{_MARKER_MONTHS[int(parts[1]) - 1]} {year}"
    return year


def _residence_at(date_iso: object, residences: list) -> str | None:
    """The residence landmark covering ``date_iso``: its nickname, else its
    label — the residence :data:`A_HOME_SHOWS_EVERY_FIELD` names, so a marker
    can say "while at BJ's House"."""
    body = collapsed_text(date_iso).split("/")[0].strip()
    if not body:
        return None
    padded = _padded(body, end=False)
    for landmark in residences or ():
        for stay in landmark.get("stays") or ():
            start = stay.get("start")
            if not start or padded < _padded(start, end=False):
                continue
            end = stay.get("end")
            if stay.get("ongoing") or not end or padded <= _padded(end, end=True):
                return landmark.get("nickname") or landmark.get("label")
    return None


def _marker(kind: str, cell: dict, *, person_ref: str, label: str, residences: list) -> dict:
    date = cell.get("value")
    residence = _residence_at(date, residences) if date else None
    text = _marker_date_text(date) if date else ""
    tooltip = " · ".join(part for part in (label, text, f"while at {residence}" if residence else "") if part)
    return {"marker_id": f"cornerstone:{kind}:{person_ref}", "kind": kind, "date": date,
            "grain": cell.get("grain"), "person_ref": person_ref, "label": label,
            "tooltip": tooltip, "residence": residence}


def _self_born(cornerstones: dict) -> str | None:
    """His own birth date, plain ISO — the marker row's own axis start
    (owner, 2026-09-25: "the axis is his life")."""
    for group in cornerstones.get("groups") or ():
        if group.get("group") != "you":
            continue
        for row in group.get("people") or ():
            born = row.get("born") if isinstance(row, dict) else None
            if isinstance(born, dict) and born.get("value"):
                return collapsed_text(born["value"]).split("/")[0]
        break
    return None


def cornerstone_markers(cornerstones: object, *, residences: list = ()) -> list[dict]:
    """One ◆ marker per required-set birth, wedding and death, pinned as its
    own row at the top of the Landmarks lanes (owner design item 2).

    A wedding is a plain ◆ at its date, like every other cornerstone —
    "marriage is a discrete date" (owner, 2026-09-25); no line, no open span.
    Hover/focus names the cornerstone and the residence that covers its date
    (:func:`_residence_at`); a click target is the row's own ``person_ref``,
    so a host opens the Cornerstones view scrolled to it.

    **The axis is his life.** A cornerstone dated before his own birth — his
    parents' wedding, a parent's or grandparent's birth — reads as HIS own
    when clamped onto the start of an axis that begins at his birth, so it is
    OMITTED from this row entirely (owner, 2026-09-25); it still shows in the
    Cornerstones grid, which has no such axis to misread it against.
    """
    view = cornerstones if isinstance(cornerstones, dict) else None
    if not view:
        return []
    self_born = _self_born(view)
    markers: list[dict] = []
    seen_weddings: set = set()
    for group in view.get("groups") or ():
        for row in group.get("people") or ():
            if not isinstance(row, dict):
                continue
            ref = row.get("person_ref") or ""
            display = row.get("display_name") or row.get("name") or ""
            born = row.get("born")
            if isinstance(born, dict) and born.get("value"):
                markers.append(_marker("birth", born, person_ref=ref,
                                       label=f"{display} born", residences=residences))
            died = row.get("died")
            if isinstance(died, dict) and died.get("value"):
                markers.append(_marker("death", died, person_ref=ref,
                                       label=f"{display} died", residences=residences))
            married = row.get("married")
            if isinstance(married, dict) and married.get("value"):
                value = married["value"]
                if value in seen_weddings:
                    continue
                seen_weddings.add(value)
                markers.append(_marker("wedding", married, person_ref=ref,
                                       label=f"{display} married", residences=residences))
    if self_born:
        floor = _padded(self_born, end=False)
        markers = [m for m in markers
                  if _padded(collapsed_text(m["date"]).split("/")[0], end=False) >= floor]
    markers.sort(key=lambda m: collapsed_text(m["date"]).split("/")[0])
    return markers


def landmarks_view(domains: object, *, nodes: object = (), work_items: object = (),
                   cornerstones: object = None) -> dict:
    """The landmarks view over one drawn landmark set.

    ``domains`` is `landmark_projection.project_landmark_entries(...)["domains"]`
    (the same ``{domain: [entry, ...]}`` `state/landmarks.json` holds).

    **Span kinds only.** Only :data:`DOMAIN_ORDER` (homes, schools, work,
    missions, military) is ever drawn here; :data:`NON_SPAN_DOMAINS` (marriage,
    children, family, losses, birth) is cornerstone material and never a lane
    even if a fold still files entries there. A kind with no entries is
    HIDDEN outright — no "Military — none" row — rather than shown empty.

    ``cornerstones``, when given the same generation's :func:`cornerstones_view`
    result, publishes one ``cornerstone_markers`` row pinned at the top: see
    :func:`cornerstone_markers`.
    """
    filed = domains if isinstance(domains, dict) else {}
    nodes_by_kind: dict[str, list[dict]] = {}
    for node in nodes or ():
        if isinstance(node, dict):
            nodes_by_kind.setdefault(collapsed_text(node.get("event_kind")), []).append(node)
    open_items = _open_items_by_node(work_items)
    names = [d for d in DOMAIN_ORDER if d in filed]
    by_domain = {domain: _landmarks_of(domain, filed.get(domain) or [],
                                       nodes_by_kind=nodes_by_kind, open_items=open_items)
                 for domain in names}
    stretches = covered_stretches(by_domain)
    gap_keys = _residence_gap_keys(filed)
    # Mission is mention-opened (item 3, 2026-09-25): a REAL `missions` domain
    # entry wins; absent one, it is derived from the covered stretch. Built
    # BEFORE Homes is trimmed, from every residence stay inside the stretch.
    mission_row = None if by_domain.get("missions") else _mission_domain_row(stretches, by_domain)
    if mission_row and by_domain.get("residences"):
        # :data:`A_MISSION_HOME_IS_LISTED_UNDER_MISSIONS`.
        missions = [s for s in stretches if s["kind"] == "missions"]
        by_domain["residences"] = [
            landmark for landmark in by_domain["residences"]
            if not landmark["stays"] or not all(
                stay["start"] and any(_inside(stay["start"], stay["end"] or stay["start"], m, slack=1)
                                      for m in missions)
                for stay in landmark["stays"])]
    out_domains = []
    earliest: str | None = None
    for domain in names:
        landmarks = by_domain[domain]
        if not landmarks:
            continue  # a kind with no entries is hidden, not shown "none"
        row = {"domain": domain, "label": DOMAIN_LABELS.get(domain, domain.capitalize()),
               "chain": domain in CHAIN_DOMAINS, "none": False,
               "landmarks": landmarks}
        if domain in CHAIN_DOMAINS:
            row.update(chain_rows(domain, landmarks, stretches,
                                  residence_gap_keys=gap_keys))
        else:
            row["rows"] = [{"kind": "stay", "start": stay["start"], "end": stay["end"],
                            "ongoing": stay["ongoing"], "entry_id": landmark["entry_id"],
                            "stay_index": stay["stay_index"]}
                           for landmark in landmarks for stay in landmark["stays"]]
            row["rows"].sort(key=lambda r: r["start"] or "")
            row["gaps"], row["covered"] = [], []
        for landmark in landmarks:
            for stay in landmark["stays"]:
                if stay["start"] and (earliest is None or stay["start"] < earliest):
                    earliest = stay["start"]
        out_domains.append(row)
    # Mission is mention-opened (item 3, 2026-09-25): a REAL `missions`
    # domain entry (above) wins; absent one, derive it from the covered
    # stretch so it still gets its own lane, under Work.
    if not any(row["domain"] == "missions" for row in out_domains):
        if mission_row:
            insert_at = next((i + 1 for i, row in enumerate(out_domains) if row["domain"] == "work"),
                             len(out_domains))
            out_domains.insert(insert_at, mission_row)
    problems = [
        {"domain": landmark["domain"], "entry_id": landmark["entry_id"],
         "label": landmark["label"], "problems": list(landmark["problems"])}
        for domain in names for landmark in by_domain[domain] if landmark["problems"]
    ]
    markers = cornerstone_markers(cornerstones, residences=by_domain.get("residences") or [])
    return {
        "rule_version": TIMELINE_VIEWS_RULE_VERSION,
        "gap_months": GAP_MONTHS,
        "earliest": earliest,
        "domains": out_domains,
        "covered": stretches,
        "problems": problems,
        "cornerstone_markers": markers,
    }


# --------------------------------------------------------------------------
# Cornerstones
# --------------------------------------------------------------------------

EXACT = "exact"
NEEDS_DAY = "needs_day"
DISAGREEMENT = "disagreement"
MISSING = "missing"
#: A cell the set does not owe (a living person's death; a child's wedding).
NOT_OWED = "not_owed"
CELL_STATUSES = (EXACT, NEEDS_DAY, DISAGREEMENT, MISSING, NOT_OWED)

#: The grid's groups, in the owner's order.
GROUPS = (("self", "you", "You"), ("spouse", "spouse", "Spouse"),
          ("child", "children", "Children"), ("parent", "parents", "Parents"),
          ("sibling", "siblings", "Siblings"), ("grandparent", "grandparents", "Grandparents"))
GROUP_OF = {relationship: (key, label) for relationship, key, label in GROUPS}

#: Where a cell's Play walks when no work item is open on it: the landmarks
#: ladder domain that asks that milestone for that person.
PLAY_DOMAIN = {("birth", "self"): "birth", ("birth", "child"): "children",
               ("birth", "parent"): "family", ("birth", "sibling"): "family",
               ("birth", "spouse"): "family", ("birth", "grandparent"): "family",
               ("wedding", "self"): "partnerships", ("wedding", "spouse"): "partnerships",
               ("wedding", "parent"): "family",
               ("divorce", "self"): "partnerships", ("divorce", "spouse"): "partnerships",
               ("death", "parent"): "losses", ("death", "spouse"): "losses",
               ("death", "sibling"): "losses", ("death", "child"): "losses",
               ("death", "grandparent"): "losses"}

COLUMNS = (("born", "birth"), ("married", "wedding"), ("divorced", "divorce"),
           ("died", "death"))


def _open_items_by_node(work_items: object) -> dict:
    """``node_id -> work_item_id`` for every OPEN item naming a node."""
    out: dict[str, str] = {}
    for item in work_items or ():
        if not isinstance(item, dict) or collapsed_text(item.get("state")) not in ("", "open"):
            continue
        for key in ("node_ref", "event_ref"):
            ref = collapsed_text(item.get(key))
            if ref and ref not in out:
                out[ref] = str(item.get("work_item_id"))
    return out


def _open_contradictions(work_items: object) -> dict:
    out: dict[str, str] = {}
    for item in work_items or ():
        if (isinstance(item, dict) and item.get("kind") == "contradiction"
                and collapsed_text(item.get("state")) in ("", "open")):
            for key in ("node_ref", "event_ref"):
                ref = collapsed_text(item.get(key))
                if ref:
                    out.setdefault(ref, str(item.get("work_item_id")))
    return out


def _cell(record: object, *, members: list, contradictions: dict, open_items: dict,
          owed: bool, play_domain: str | None, subject: str) -> dict:
    parsed = chrono.from_dict(record) if record else None
    node_ids = [str(n.get("node_id")) for n in members if n.get("node_id")]
    conflict = next((contradictions[n] for n in node_ids if n in contradictions), None)
    if parsed is None and not members:
        status = MISSING if owed else NOT_OWED
    elif conflict:
        status = DISAGREEMENT
    elif parsed is None:
        status = MISSING
    elif cs.is_a_day(parsed):
        status = EXACT
    else:
        status = NEEDS_DAY
    play = None
    if status in (NEEDS_DAY, DISAGREEMENT, MISSING):
        item = conflict or next((open_items[n] for n in node_ids if n in open_items), None)
        if item:
            play = {"kind": "work_item", "work_item_id": item}
        elif play_domain:
            play = {"kind": "landmark", "domain": play_domain, "subject": subject}
    value = chrono.to_edtf(parsed) if parsed else None
    return {
        "status": status,
        "value": value,
        "grain": cs._grain(parsed) if parsed else None,  # noqa: SLF001 — cornerstones' own reader
        "display": chrono.display_date(parsed, with_basis=False) if parsed else None,
        "node_id": node_ids[0] if node_ids else None,
        "nodes": len(node_ids),
        "play": play,
    }


#: The words a person uses to their face, preferred over the formal ones.
INFORMAL_WORDS = frozenset({"dad", "mom", "grandpa", "grandma"})


def _display_name(person: object, called: tuple, relationship: str) -> str:
    """What he calls them: a nickname he uses ("AJ"); for a parent or a
    grandparent, the relation word he uses ("Dad", "Grandpa"); else the given
    name."""
    words = set(cs.ir.RELATIONSHIP_MENTION_WORDS)
    nickname = relation = ""
    for spelling in called or ():
        body = collapsed_text(spelling)
        tokens = [t for t in re.findall(r"[A-Za-z.]+", body) if t.lower() not in ("my", "the")]
        if not tokens:
            continue
        if all(t.lower() in words for t in tokens):
            word = " ".join(t.capitalize() for t in tokens)
            if not relation or (word.lower() in INFORMAL_WORDS
                                and relation.lower() not in INFORMAL_WORDS):
                relation = word
        elif len(tokens) == 1 and "(" not in body:
            nickname = nickname or tokens[0]
    name = collapsed_text(getattr(person, "name", ""))
    if relation and relationship == "parent":
        return relation
    if relationship == "grandparent":
        # "Grandma Betty Jo" already says both; else the word he uses.
        if name.split() and name.split()[0].lower() in INFORMAL_WORDS | {"grandfather", "grandmother"}:
            return name
        if relation:
            return relation
    if nickname:
        return nickname
    name = collapsed_text(getattr(person, "name", ""))
    first = name.split()[0] if name else ""
    if first.lower() in ("grandma", "grandpa") and len(name.split()) > 1:
        return name
    return first or name


def cornerstones_view(nodes: object, relations: object, *, roster: object = (),
                      work_items: object = (), relation_rows: object = (),
                      called_by: object = None, landmark_domains: object = None,
                      owner_name: object = "") -> dict:
    """One row per person in the cornerstone set, born / married / divorced /
    died, each a cell with its grain and :data:`CELL_STATUSES` status.

    Also returns ``others``: another person's cornerstone-type event or
    partnership, shown only with a discrete date he gave
    (:func:`_others_section`)."""
    if not isinstance(relations, cs.Relations):
        relations = cs.Relations(roster, (), owner_names=())
    held = milestone_nodes(nodes, relations)
    contradictions = _open_contradictions(work_items)
    open_items = _open_items_by_node(work_items)
    words = {row.get("subject_ref"): row for row in relation_rows or () if isinstance(row, dict)}
    called = called_by if isinstance(called_by, dict) else {}
    parents_wedding = _parents_wedding(nodes, relations, landmark_domains)
    losses = {normalized_mention_key(e.get("who") or e.get("label"))
              for e in ((landmark_domains or {}).get("losses") or ()) if isinstance(e, dict)}

    roster_rows = _roster_rows_by_ref(roster)
    form_dates = _form_dates(landmark_domains, relations)
    people: list[tuple[str, object, str]] = [("self", cs.SELF, cs.SELF)]
    for person in relations.people:
        if person.relationship in GROUP_OF and person.relationship != "self" \
                and not person.key.startswith(("relation:",)):
            people.append((person.relationship, person, person.key))
    rows_by_group: dict[str, list[dict]] = {key: [] for _, key, _ in GROUPS}
    for relationship, person, key in people:
        name = (collapsed_text(owner_name) or "You") if person == cs.SELF else person.name
        ref = key if key.startswith("person/") else None
        word = words.get(ref) if ref else None
        display = "You" if person == cs.SELF else _display_name(
            person, tuple(called.get(ref) or ()), relationship)
        entity = roster_rows.get(ref) if ref else None
        said_word = collapsed_text((entity or {}).get("relation_word"))
        if said_word and person != cs.SELF:
            display = said_word  # the word he chose on the person form
        row = {"person_ref": ref or key, "name": name, "display_name": display,
               "relationship": relationship,
               "relation_word": (word or {}).get("label") or None,
               # v360 (owner, 2026-09-25) (the person form): what the form prefills.
               "slug": collapsed_text((entity or {}).get("slug")) or None,
               "said_word": said_word or None,
               "side": collapsed_text((entity or {}).get("grandparent_side")) or None}
        for column, milestone in COLUMNS:
            members = list(held.get((milestone, cs.SELF if person == cs.SELF else key)) or ())
            owed_rel = cs.SELF if person == cs.SELF else relationship
            record = members[0].get("best_temporal_value") if members else None
            owed = False
            if milestone == "birth":
                owed = owed_rel in cs.WHOSE["birth"] or relationship == "grandparent"
                if record is None and person != cs.SELF and getattr(person, "born", None):
                    record = person.born
            elif milestone in ("wedding", "divorce"):
                if relationship in ("self", "spouse"):
                    members = list(held.get((milestone, cs.SELF)) or ())
                    record = members[0].get("best_temporal_value") if members else None
                    owed = milestone == "wedding"
                elif relationship == "parent" and milestone == "wedding":
                    members, record = parents_wedding
                    owed = True
                elif relationship == "child":
                    # "Kids' partnerships, business, and record fixes"
                    # (2026-09-25): a wedding or a divorce joins the required
                    # set once he mentions it — never a default question, so
                    # unmentioned (no members) is NOT_OWED, not MISSING.
                    owed = bool(members)
                else:
                    row[column] = None
                    continue
            elif milestone == "death":
                owed = bool(person != cs.SELF and any(
                    normalized_mention_key(n) in losses for n in getattr(person, "names", ())))
                if person == cs.SELF:
                    row[column] = None
                    continue
            said = form_dates.get((milestone, cs.SELF if person == cs.SELF else key))
            if said is not None:
                # :data:`A_FORM_DATE_IS_THE_CELL` — what he typed on the form.
                record = said
            cell = _cell(record, members=members, contradictions=contradictions,
                         open_items=open_items, owed=owed,
                         play_domain=PLAY_DOMAIN.get((milestone, owed_rel)),
                         subject=name)
            if milestone == "divorce" and cell["status"] == NOT_OWED:
                row[column] = None
                continue
            row[column] = cell
        group, _ = GROUP_OF.get(relationship, ("", ""))
        if group:
            rows_by_group[group].append(row)
    for group_rows in rows_by_group.values():
        group_rows.sort(key=lambda r: ((r.get("born") or {}).get("value") or "9999", r["name"]))
    groups = [{"group": key, "label": label, "people": rows_by_group[key]}
              for _, key, label in GROUPS if rows_by_group[key]]
    counts: dict[str, int] = {status: 0 for status in CELL_STATUSES}
    for group in groups:
        for row in group["people"]:
            for column, _ in COLUMNS:
                cell = row.get(column)
                if isinstance(cell, dict):
                    counts[cell["status"]] += 1
    others = _others_section(held, relations, landmark_domains)
    return {"rule_version": TIMELINE_VIEWS_RULE_VERSION,
            "columns": [column for column, _ in COLUMNS],
            "groups": groups, "counts": counts, "others": others}


#: v360 (owner, 2026-09-25) (the person form). A date he typed on a person form is
#: filed as a landmark record marked ``form: owner`` (`landmark_edit`), and
#: the grid shows it as the cell — it is his own statement, which outranks
#: any reading (`temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT`).
A_FORM_DATE_IS_THE_CELL = (
    "a born/married/divorced/died date the owner typed on the person form is "
    "that person's cell, whatever the fold's nodes read; the same record also "
    "reaches the fold as his stated claim"
)

FORM_MARK = "owner"
_FORM_MILESTONE_OF_DOMAIN = {"family": "birth", "children": "birth", "losses": "death"}


def _roster_rows_by_ref(roster: object) -> dict:
    import axis_membership as axm  # noqa: PLC0415
    import roster_relations as rr  # noqa: PLC0415

    out: dict = {}
    for row in axm.roster_person_rows(roster):
        ref = rr.entity_ref("person", row)
        if ref:
            out[ref] = row
    return out


def _form_dates(landmark_domains: object, relations: object) -> dict:
    """``{(milestone, whose key): DateRecord}`` for every date filed from the
    person form (:data:`A_FORM_DATE_IS_THE_CELL`); later filings win."""
    out: dict = {}
    for domain, entries in (landmark_domains or {}).items():
        for entry in entries or ():
            if not isinstance(entry, dict) or entry.get("form") != FORM_MARK:
                continue
            if domain == "partnerships":
                subject = relations.person_for(entry.get("subject")) if entry.get("subject") else cs.SELF
                key = cs.SELF if subject == cs.SELF else getattr(subject, "key", None)
                if key is None:
                    continue
                if isinstance(entry.get("date"), dict):
                    out[("wedding", key)] = entry["date"]
                end = (entry.get("span") or {}).get("end") if isinstance(entry.get("span"), dict) else None
                if isinstance(end, dict):
                    out[("divorce", key)] = end
                continue
            milestone = _FORM_MILESTONE_OF_DOMAIN.get(domain)
            if not milestone or not isinstance(entry.get("date"), dict):
                continue
            person = relations.person_for(entry.get("who") or entry.get("label"))
            key = cs.SELF if person == cs.SELF else getattr(person, "key", None)
            if key:
                out[(milestone, key)] = entry["date"]
    return out


def milestone_nodes(nodes: object, relations: object) -> dict:
    """``{(milestone, whose key): [node, ...]}`` for every milestone node about
    the owner or a person the roster or a landmark entry holds, best-placed
    first (`cornerstones._rank`).

    `cornerstones.cornerstone_nodes` groups only the fold's cornerstones; the
    view also shows a grandparent's birth (a row it draws, never a card it
    asks). One reading differs, and it is the couple's: a wedding or a divorce
    whose subjects include the owner or his spouse is HIS couple's even when
    the classifier also named a parent on it (his own wedding reception "in
    mother-in-law's backyard" carries his mother as a subject) — so it can
    never be read as his parents' wedding. His parents' wedding is
    :func:`_parents_wedding`'s.

    A wedding or divorce that is NOT the owner's couple attaches to whoever it
    IS about (:func:`~cornerstones.Relations.whose`) rather than being
    dropped — his kids' weddings (required, once mentioned) and other
    people's (Others, with a discrete date) both read this same dict.
    """
    grouped: dict[tuple, list] = {}
    for node in nodes or ():
        if not isinstance(node, dict):
            continue
        status, milestone, whose = cs.node_status(node, relations)
        if not milestone:
            continue
        if milestone in ("wedding", "divorce"):
            whose = cs.SELF if _is_the_owners_couple(node, relations) else \
                relations.whose(node.get("subject_refs") or ())
        if whose != cs.SELF and not (isinstance(whose, cs.Person) and cs.is_known_person(whose)):
            continue
        key = cs.SELF if whose == cs.SELF else whose.key
        grouped.setdefault((milestone, key), []).append(node)
    return {key: sorted(rows, key=cs._rank)  # noqa: SLF001 — cornerstones' own ranking
            for key, rows in sorted(grouped.items())}


def _is_the_owners_couple(node: dict, relations: object) -> bool:
    for subject in node.get("subject_refs") or ():
        person = relations.person_for(subject)
        if person == cs.SELF or (isinstance(person, cs.Person) and person.relationship == "spouse"):
            return True
    return False


def _parents_wedding(nodes: object, relations: object, landmark_domains: object) -> tuple[list, object]:
    """His parents' wedding: a wedding node about his parents (the couple or
    either of them), best-placed first; else the `family` entry that dates
    it."""
    members = []
    for node in nodes or ():
        if not isinstance(node, dict) or cs.milestone_of_node(node) != "wedding":
            continue
        if _is_the_owners_couple(node, relations):
            continue
        whose = relations.whose(node.get("subject_refs") or ())
        subjects = " ".join(str(s) for s in node.get("subject_refs") or ())
        if (isinstance(whose, cs.Person) and whose.relationship == "parent") or \
                re.search(r"\bparents\b", subjects + " " + str(node.get("label") or ""), re.I):
            members.append(node)
    members.sort(key=cs._rank)  # noqa: SLF001 — cornerstones' own ranking
    if members:
        return members, members[0].get("best_temporal_value")
    for entry in (landmark_domains or {}).get("family") or ():
        if (isinstance(entry, dict) and re.search(r"\bparents\b", str(entry.get("who") or entry.get("label") or ""), re.I)
                and isinstance(entry.get("date"), dict)):
            return [], entry["date"]
    return [], None


# --------------------------------------------------------------------------
# Others: another person's cornerstone-type event, discrete dates only
# --------------------------------------------------------------------------

#: ``(relationship, milestone)`` already drawn as a REQUIRED cell above —
#: never repeated in Others. Birth and death are owed for every required-set
#: relationship (grandparent birth and child death included, item 2's grid);
#: wedding/divorce are owed only for self, spouse, his parents, and — once
#: mentioned — his children (:data:`OWNER_WORDS`, "Kids' partnerships,
#: business, and record fixes").
REQUIRED_CELLS = frozenset({
    ("self", "birth"), ("spouse", "birth"), ("parent", "birth"), ("sibling", "birth"),
    ("child", "birth"), ("grandparent", "birth"),
    ("self", "wedding"), ("spouse", "wedding"), ("parent", "wedding"), ("child", "wedding"),
    ("self", "divorce"), ("spouse", "divorce"), ("child", "divorce"),
    ("parent", "death"), ("spouse", "death"), ("sibling", "death"), ("child", "death"),
    ("grandparent", "death"),
})

#: A company or fund a `partnerships` entry misfiled — never a partnership,
#: landmark or cornerstone here, whatever domain holds it today ("Kids'
#: partnerships, business, and record fixes": Castle Island Ventures).
#: Defensive only; the filing itself is fixed elsewhere.
_BUSINESS_WORDS_RE = re.compile(
    r"\b(ventures?|capital|holdings?|partners(?!hip)|fund|llc|inc\.?|ltd\.?|corp\.?|"
    r"company|co\.?|group|labs?|studios?|technologies)\b", re.IGNORECASE)


def _is_business_text(*texts: object) -> bool:
    return any(_BUSINESS_WORDS_RE.search(collapsed_text(t)) for t in texts if collapsed_text(t))


def _has_discrete_date(record: object) -> bool:
    """Did he GIVE this date — stated, or read off a document — rather than a
    story-derived age or anchor reading kept only for calculation? A date
    with no such basis is used to place things but never shown here."""
    parsed = chrono.from_dict(record) if record else None
    return bool(parsed and parsed.basis in ("stated", "document"))


def _milestone_others(held: dict, relations: object, required: frozenset) -> list[dict]:
    """Another known person's cornerstone-type node — birth, wedding, divorce
    or death — outside :data:`REQUIRED_CELLS`, with a discrete date."""
    rows: list[dict] = []
    for (milestone, key), members in held.items():
        if key == cs.SELF or milestone == "baptism":
            continue  # his own row, or a milestone that is only ever his
        person = next((p for p in relations.people if p.key == key), None)
        if person is None or (person.relationship, milestone) in required:
            continue
        if _is_business_text(person.name, *person.names):
            continue
        best = next((n for n in members if _has_discrete_date(n.get("best_temporal_value"))), None)
        if best is None:
            continue
        parsed = chrono.from_dict(best.get("best_temporal_value"))
        value = chrono.to_edtf(parsed)
        rows.append({
            "person_ref": key, "name": person.name, "display_name": person.name,
            "relationship": person.relationship or "", "milestone": milestone,
            "node_id": collapsed_text(best.get("node_id")) or None,
            "value": value, "grain": cs._grain(parsed),  # noqa: SLF001
            "display": _marker_date_text(value),
            # v360 (owner, 2026-09-25): the claims behind the discrete date, which
            # 🗑 on this row retires (`landmark_edit.edit_person`, undoable).
            "claim_ids": _claim_ids_of(best.get("best_temporal_value")),
        })
    return rows


def _claim_ids_of(record: object) -> list[str]:
    ids = []
    for item in (record or {}).get("provenance") or () if isinstance(record, dict) else ():
        claim = collapsed_text(item.get("claim_id")) if isinstance(item, dict) else ""
        if claim and claim not in ids:
            ids.append(claim)
    return ids


def _other_partnerships(landmark_domains: object, relations: object) -> list[dict]:
    """Another person's partnership — his sister's, say — same rule: only
    with a discrete date, never his or his kids' (those are personal,
    :data:`OWNER_WORDS`-adjacent), never a marriage already read as a wedding
    node (that reaches Others through :func:`_milestone_others` instead), and
    never a business (:func:`_is_business_text`, defensive)."""
    out: list[dict] = []
    for entry in (landmark_domains or {}).get("partnerships") or ():
        if not isinstance(entry, dict) or entry.get("none"):
            continue
        subject_text = _text(entry, "subject")
        partner_text = _text(entry, "label") or _text(entry, "who") or _text(entry, "name")
        if not subject_text:
            continue  # no named subject: his own, by the domain's own convention
        if _is_business_text(subject_text, partner_text, _text(entry, "what")):
            continue
        subject = relations.person_for(subject_text)
        if subject == cs.SELF or (isinstance(subject, cs.Person) and subject.relationship == "child"):
            continue  # "Partnerships in the view are his and his kids' only."
        if cs.Relations.partnership_is_a_marriage(entry):
            continue  # a marriage of theirs surfaces as a wedding node instead
        span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
        record = entry.get("date") if isinstance(entry.get("date"), dict) else span.get("start")
        if not _has_discrete_date(record):
            continue
        parsed = chrono.from_dict(record)
        value = chrono.to_edtf(parsed)
        who_name = subject.name if isinstance(subject, cs.Person) else subject_text
        out.append({
            "person_ref": subject.key if isinstance(subject, cs.Person) else f"text:{lid.fold(subject_text)}",
            "name": who_name, "display_name": who_name,
            "relationship": subject.relationship if isinstance(subject, cs.Person) else "",
            "milestone": "partnership", "partner": partner_text,
            "node_id": None, "value": value, "grain": cs._grain(parsed),  # noqa: SLF001
            "display": _marker_date_text(value),
            "refs": [dict(entry["ref"])] if isinstance(entry.get("ref"), dict) else [],
        })
    return out


def _others_section(held: dict, relations: object, landmark_domains: object) -> list[dict]:
    """"OTHERS": another person's cornerstone-type event or partnership,
    shown ONLY with a discrete date he gave (2026-09-25, "What the
    Cornerstones view shows"). Sorted oldest first, then by name."""
    rows = _milestone_others(held, relations, REQUIRED_CELLS)
    rows.extend(_other_partnerships(landmark_domains, relations))
    rows.sort(key=lambda r: (collapsed_text(r.get("value")).split("/")[0] or "9999", r["name"]))
    return rows


# --------------------------------------------------------------------------
# The publication seam
# --------------------------------------------------------------------------


def with_views(payloads: dict, *, projection_key: str, index: object,
               landmark_entries: object, roster: object, owner_names: object = (),
               claims: object = ()) -> dict:
    """Publish both views onto the rendered projection, in place.

    Only when there is something to show, so a vault with no landmarks and
    no cornerstones publishes byte-identically to before. Returns the two
    views (``None`` for one not published).
    """
    import landmark_projection as lp  # noqa: PLC0415 - avoids an import cycle
    import roster_relations as rr  # noqa: PLC0415
    import temporal_timeline as tt  # noqa: PLC0415

    projection = payloads.get(projection_key)
    if not isinstance(projection, dict):
        return {LANDMARKS_VIEW_KEY: None, CORNERSTONES_VIEW_KEY: None}
    nodes = [n for n in projection.get("nodes") or () if isinstance(n, dict)]
    work_items = [w for w in projection.get("work_items") or () if isinstance(w, dict)]
    drawn = lp.project_landmark_entries(index, sources=landmark_entries or (),
                                        owner_names=owner_names or (), with_refs=True)
    domains = drawn.get("domains") or {}
    relations = cs.Relations(roster, landmark_entries or (), owner_names=owner_names or ())
    annotated = rr.with_called_by(roster, tt.telling_texts(claims))
    import axis_membership as axm  # noqa: PLC0415
    called = {rr.entity_ref("person", row): tuple(row.get("called_by") or ())
              for row in axm.roster_person_rows(annotated)}
    names = [collapsed_text(n) for n in owner_names or () if collapsed_text(n)]
    owner = max(names, key=len) if names else ""
    # Cornerstones first: the Landmarks lanes' pinned marker row (item 2)
    # reads its births/weddings/deaths off this SAME generation's view.
    view = cornerstones_view(nodes, relations, roster=roster, work_items=work_items,
                             relation_rows=projection.get("relation_words") or (),
                             called_by=called, landmark_domains=domains, owner_name=owner)
    if any(group["people"] for group in view["groups"]) and (
            len(view["groups"]) > 1 or view.get("others") or any(
                (row.get("born") or {}).get("status") != MISSING
                for group in view["groups"] for row in group["people"])):
        projection[CORNERSTONES_VIEW_KEY] = view
    else:
        view = None
    landmarks = landmarks_view(domains, nodes=nodes, work_items=work_items,
                               cornerstones=view) if domains else None
    if landmarks and (landmarks["domains"] or landmarks["cornerstone_markers"]):
        projection[LANDMARKS_VIEW_KEY] = landmarks
    else:
        landmarks = None
    return {LANDMARKS_VIEW_KEY: landmarks, CORNERSTONES_VIEW_KEY: view}


__all__ = [
    "A_COVERED_STRETCH_IS_NOT_A_GAP", "A_GAP_IS_A_HOLE_OF_MORE_THAN_TWO_MONTHS",
    "A_HOME_SHOWS_EVERY_FIELD", "CELL_STATUSES", "CORNERSTONES_VIEW_KEY", "DISAGREEMENT",
    "DOMAIN_LABELS", "DOMAIN_ORDER", "EXACT", "GAP_MONTHS", "LANDMARKS_VIEW_KEY", "MISSING",
    "NEEDS_DAY", "NON_SPAN_DOMAINS", "NOT_OWED", "REQUIRED_CELLS", "TIMELINE_VIEWS_RULE_VERSION",
    "chain_rows", "cornerstone_markers", "cornerstones_view", "covered_stretches",
    "landmarks_view", "milestone_nodes", "months_between", "residence_fields", "with_views",
]
