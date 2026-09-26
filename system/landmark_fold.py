"""A move moment folds into its landmark — v365 (owner, 2026-09-26) (the owner).

The owner, on the Timeline rows beside the continuous landmark brackets: a
moment that IS a landmark's own start or end is not a row of its own —
"Move to Figers House", "Moved in from Yucaipa Avenue F", "Moved into Hope St",
starting or finishing that school or job, leaving on or returning from the
mission. The bracket's rounded cap and the hairline boundary between rows
already say it. Its tellings are NOT deleted: they attach to the landmark and
show in the landmark's form under "Your words about this".

A moment that merely MENTIONS a move, or that moves to a state or region
rather than to one of his homes ("Family moved to Arizona", owner-confirmed),
stays a normal row.

:data:`A_MOVE_MOMENT_FOLDS_INTO_ITS_LANDMARK` is the rule, deterministic and
conservative. A node folds into ONE landmark stay when ALL of these hold:

1. **It is one of his own moments** — ``occurrence_subject_scope`` owner (or
   undeclared), an event kind that can be a boundary (``moment``, ``move``,
   ``started``, ``ended``, ``graduation``, ``event``), and not itself a
   landmark's own node or a period.
2. **It says a boundary** — its title opens with a boundary verb
   (:data:`START_VERBS` / :data:`END_VERBS`: "move to", "moved into",
   "move out of", "left", "started", "start of", "graduated", "returned
   from"…), optionally after "Family"/"We"/"I". A title that only mentions
   one ("Preparing to leave on mission", "Frequent childhood moves") is not a
   boundary.
3. **It names that landmark** — the landmark's nickname, label, the name
   before a comma ("Friedrichshafen"), a parenthetical ("MTC"), an acronym of
   a three-word name ("ASU"), or its street ("Ravensburger"), as whole words;
   the mission as a whole is named by the word "mission". A city, state or
   region that is not one of his landmarks names nothing, so "Family moved to
   Arizona" never folds. The binder's own links break a tie: a moment whose
   ``proposed_links`` bind it to a landmark's node prefers that landmark.
4. **It is dated at that stay's start or end** — the moment's window opens
   within a month of the stay's start (a start) or closes within a month of
   its end (an end); a stay given only as a year is matched by that year.
   The moment never reaches past the stay's far side.

Direction: a name after "from" / "out of" (and every end verb) is that
landmark's END; otherwise its START. So "Moved in from Yucaipa Avenue F" is
Avenue F's end.

The fold hides nothing it cannot give back. The node stays in ``nodes`` with
``folded_into_landmark`` (the entry id) and ``folded_boundary``
(``landmark:<entry_id>:<stay_index>:start|end``, the same anchor a drop on a
boundary names), so audits, Mirror and search still see it; the Timeline
rows skip it. The landmark carries ``tellings`` — each folded node, its
boundary, and his words (the evidence quotes of its claims) — and the view
lists every fold in ``folds`` so a false fold can be caught.

Pure and deterministic over one generation: nodes, the landmarks view, and
the claims in. Synthetic data only in its tests.
"""

from __future__ import annotations

import re

from temporal_claims import collapsed_text

import drag_tighten as dt

#: The owner's ruling, as the rule's name (v365 (owner, 2026-09-26)).
A_MOVE_MOMENT_FOLDS_INTO_ITS_LANDMARK = (
    "a moment of his own whose title opens with a boundary verb, names one of "
    "his landmarks and is dated at that stay's start or end month is that "
    "landmark's start or end: it is not drawn as a row, its tellings attach to "
    "the landmark, and the node stays published, marked folded"
)

#: Owner, 2026-09-26: "We no longer need a row for Longfellow Elementary
#: because the landmark contains that information. I don't think we need rows
#: for landmark information." A node that IS a landmark (its own node) or only
#: restates it — its title, once the landmark's name, its own place words and
#: the words for a home, a school, a job or a mission are taken out, says
#: nothing more ("Longfellow Elementary", "Residence at Hope St.", "Residence
#: at the MTC", "Mission to Switzerland at 19") — and is dated inside that
#: stay, folds into it like a start or an end. A title with anything left
#: over ("Quitting janitor job over snowboarding", "Started Etherfuse to serve
#: non-US markets") is a story: a row.
A_LANDMARK_RESTATEMENT_FOLDS_INTO_IT = (
    "a node that is a landmark's own node, or whose title only restates the "
    "landmark and is dated inside its stay, folds into it; a title that says "
    "more is a story and stays a row"
)

LANDMARK_FOLD_RULE_VERSION = "landmark-fold:3"

#: v365 (owner, 2026-09-26): a fold HE made by dropping a row on a landmark line
#: (`timeline_combine.A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT`) is applied
#: first and wins over any fold this module would have guessed for that node.
A_STATED_FOLD_OUTRANKS_A_GUESSED_ONE = (
    "a fold the person stated is applied as stated, before and over any fold "
    "the restatement or boundary rules would have made for that node"
)

FOLDABLE_KINDS = frozenset({"moment", "move", "started", "ended", "graduation", "event", ""})
#: Kinds that can restate a landmark (owner 2026-09-26: "I don't think we need
#: rows for landmark information") — its boundary kinds, and the span kinds a
#: telling of the stay itself is filed as.
RESTATABLE_KINDS = FOLDABLE_KINDS | {"residence", "school", "job", "transition", "span", "military",
                                     "memory"}

_SUBJECT = r"(?:(?:the |our |my )?family |we |i |you )?"

#: Verbs that open a stay: moving in, starting, leaving FOR the mission.
START_VERBS = re.compile(
    r"^" + _SUBJECT + r"(?:"
    r"(?:move[sd]?|moving)(?: back| together| in)*(?: to| into| in| at)\b"
    r"|(?:move[sd]?|moving)(?: back)? in\b|move-in\b"
    r"|start(?:ed|s|ing)?\b|start of\b|began\b|begin(?:ning|s)?\b|joined\b|entered\b"
    r"|enroll(?:ed|s)?\b|hired\b"
    r"|(?:leav(?:e|es|ing)|left|depart(?:s|ed|ing)?) (?:for|on)\b"
    r")",
    re.I,
)

#: Verbs that close one: moving out, leaving, finishing, graduating, returning.
END_VERBS = re.compile(
    r"^" + _SUBJECT + r"(?:"
    r"(?:move[sd]?|moving) (?:out|away)\b|move-out\b"
    r"|left\b|leaves\b|leaving\b|quit(?:s|ting)?\b|end of\b"
    r"|graduat(?:ed|es|ing|ion)\b|finish(?:ed|es|ing)?\b"
    r"|return(?:ed|s|ing)?(?: home)? from\b|came home from\b"
    r")",
    re.I,
)

#: Moving verbs fold only into a home (or a mission home); graduating only
#: into a school.
_MOVE_WORD = re.compile(r"^" + _SUBJECT + r"(?:move|moving|moved|moves)", re.I)
_GRADUATE_WORD = re.compile(r"^" + _SUBJECT + r"graduat", re.I)

GENERIC_WORDS = frozenset({
    "the", "a", "an", "of", "at", "in", "and", "house", "home", "residence", "apartment",
    "apt", "st", "str", "street", "ave", "avenue", "dr", "drive", "rd", "road", "ln",
    "lane", "blvd", "way", "ct", "court", "pl", "place", "n", "s", "e", "w", "north",
    "south", "east", "west", "school", "elementary", "middle", "high", "university",
    "college", "company", "inc", "llc",
})


def _tokens(text: object) -> list[str]:
    body = collapsed_text(text).lower().replace("’", "'")
    body = re.sub(r"'s\b", "", body)
    words = re.findall(r"[a-z0-9]+", body)
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words]


def _phrase_in(name: list[str], words: list[str]) -> int | None:
    """Where the whole-word phrase ``name`` starts in ``words``, else None."""
    if not name:
        return None
    for index in range(len(words) - len(name) + 1):
        if words[index:index + len(name)] == name:
            return index
    return None


def landmark_names(landmark: dict) -> list[list[str]]:
    """The spellings that name a landmark, as token phrases (longest first).

    Nickname, label, the name before a comma, a parenthetical, the acronym of
    a name of three or more words, and the street of its address. A phrase
    that is only generic words ("house", "the") names nothing."""
    raw: list[str] = []
    for key in ("nickname", "label", "name"):
        text = collapsed_text(landmark.get(key))
        if not text:
            continue
        raw.append(text)
        raw.append(re.sub(r"\([^)]*\)", " ", text))
        raw.extend(re.findall(r"\(([^)]*)\)", text))
        raw.append(text.split(",")[0])
        raw.append(text.split(" - ")[0])
        significant = [w for w in re.findall(r"[A-Za-z]+", re.sub(r"\([^)]*\)", " ", text))
                       if w.lower() not in ("of", "the", "and")]
        if len(significant) >= 3:
            raw.append("".join(w[0] for w in significant))
    street = collapsed_text(landmark.get("address")).split(",")[0]
    if street:
        raw.append(" ".join(w for w in re.findall(r"[A-Za-z]+", street)))
    out: list[list[str]] = []
    for text in raw:
        whole = _tokens(text)
        words = list(whole)
        while words and words[0] in GENERIC_WORDS:
            words = words[1:]
        while words and words[-1] in GENERIC_WORDS:
            words = words[:-1]
        if len(words) == 1 and len(words[0]) < 3 and len(whole) > 1:
            # "Avenue F", "BJ's House": the short name only names it whole.
            words = whole
        elif not words or all(w in GENERIC_WORDS or len(w) < 2 for w in words):
            continue
        if len(words) == 1 and len(words[0]) < 3:
            continue
        if words not in out:
            out.append(words)
    return sorted(out, key=len, reverse=True)


def _significant(name: list[str]) -> list[str]:
    return [w for w in name if w not in GENERIC_WORDS and len(w) >= 3]


def _name_match(names: list[list[str]], words: list[str]) -> tuple[int, int, set[int]] | None:
    """``(strength, position, matched word indexes)`` of the best spelling in
    ``words``: a whole phrase first; else, for a name of two or more
    significant words, every one of them present in order ("Start of Boeing
    job in Seattle" names "Boeing in Seattle")."""
    for name in names:
        at = _phrase_in(name, words)
        if at is not None:
            return 2 * len(name), at, set(range(at, at + len(name)))
    for name in names:
        key = _significant(name)
        if len(key) < 2:
            continue
        cursor, hits = 0, []
        for token in key:
            try:
                cursor = words.index(token, cursor) + 1
            except ValueError:
                break
            hits.append(cursor - 1)
        else:
            return len(key), hits[0], set(hits)
    return None


#: Words a title may carry and still only RESTATE a landmark — the boundary
#: verbs, filler, and the words for a home, a school, a job, a mission. What
#: is left once these, the landmark's name and its own place words are taken
#: out is the story's own content; a title with any left is a row.
RESTATEMENT_WORDS = frozenset(_tokens(
    "the a an of at in into to from out on for back together up away over there "
    "family we i you your our my his "
    "move moved moves moving move-in move-out left leave leaves leaving depart departed departs "
    "departing start started starts starting began begin beginning joined entered enrolled hired "
    "quit quits quitting graduated graduates graduating graduation finished finish finishes finishing "
    "returned return returns returning came home arrived arrival end ended "
    "residence residing resided reside lived living live house apartment apt st str street ave avenue "
    "dr drive rd road ln lane blvd way ct court pl place "
    "school elementary middle high junior college university kindergarten grade "
    "job work worked working company startup business attended attending went "
    "mission missions missionary church served serving lds age "
    # v365 (owner, 2026-09-26) (the owner): "Brief residence in Solothurn" and
    # "Mission assignment to Solothurn" only restate the Solothurn stay.
    "brief briefly assignment assigned stay stayed staying time"
))

_HOME_WORDS = frozenset(_tokens("residence house home apartment apt st str street ave avenue dr drive "
                                "rd road ln lane blvd way ct court pl place"))


def _place_words(landmark: dict) -> set[str]:
    out: set[str] = set()
    for key in ("city", "state", "country", "address", "address_full", "place", "where", "label"):
        out.update(_tokens(landmark.get(key)))
    return out


def _direction(label: str, words: list[str], at: int) -> str:
    # The nearest preposition before the name, up to three words back
    # ("from Yucaipa Avenue F" is Avenue F's end; "to Figers House" a start).
    for index in range(at - 1, max(-1, at - 4), -1):
        word = words[index]
        if word == "from" or (word == "of" and index > 0 and words[index - 1] == "out"):
            return "end"
        if word in ("to", "into", "at"):
            break
    if END_VERBS.search(label) and not START_VERBS.search(label):
        return "end"
    return "start"


def _stay_window(stay: dict, side: str) -> tuple[int, int] | None:
    """The months a boundary is matched in: its month ±1, or its whole year
    when the stay gives only a year."""
    value = collapsed_text(stay.get(side))
    if not value:
        return None
    month = dt.month_of(value, end=(side == "end"))
    if month is None:
        return None
    if re.fullmatch(r"~?\d{4}", value):
        year = month // 12
        return year * 12, year * 12 + 11
    return month - 1, month + 1


def _stay_months(stay: dict, now_month: int | None) -> tuple[int | None, int | None]:
    low = dt.month_of(stay.get("start"))
    high = (now_month if stay.get("ongoing") else dt.month_of(stay.get("end"), end=True))
    return low, high


def _matches(node: dict, stay: dict, direction: str, now_month: int | None) -> bool:
    low, high = dt._record_bounds(dt.placement_of(node))  # noqa: SLF001 — one reader
    if low is None and high is None:
        return False
    window = _stay_window(stay, direction)
    if window is None:
        return False
    stay_low, stay_high = _stay_months(stay, now_month)
    boundary = stay_low if direction == "start" else stay_high
    if (low is not None and high is not None and high - low <= 11 and boundary is not None
            and low <= boundary <= high):
        # A moment given only as a year (or a season) holds the boundary.
        return True
    if direction == "start":
        at = low if low is not None else high
        if not window[0] <= at <= window[1]:
            return False
        return high is None or stay_high is None or high <= stay_high + 1
    at = high if high is not None else low
    if not window[0] <= at <= window[1]:
        return False
    return low is None or stay_low is None or low >= stay_low - 1


def _residual(words: list[str], matched: set[int], allowed: set[str]) -> list[str]:
    return [w for i, w in enumerate(words)
            if i not in matched and w not in RESTATEMENT_WORDS and w not in allowed and not w.isdigit()]


def _overlap(node: dict, stay: dict, now_month: int | None) -> int | None:
    """Months the moment's window shares with the stay (±1 month of slack),
    or ``None`` when they are disjoint or the moment is undated."""
    low, high = dt._record_bounds(dt.placement_of(node))  # noqa: SLF001 — one reader
    if low is None and high is None:
        return None
    low = high if low is None else low
    high = low if high is None else high
    stay_low, stay_high = _stay_months(stay, now_month)
    if stay_low is None:
        return None
    stay_high = stay_low if stay_high is None else stay_high
    shared = min(high, stay_high + 1) - max(low, stay_low - 1) + 1
    return shared if shared > 0 else None


def _pick_stay(node: dict, landmark: dict, boundary: str, now_month: int | None) -> dict | None:
    """The stay a fold lands on: one dated AT that boundary first, else the
    one the moment overlaps most."""
    stays = [s for s in landmark.get("stays") or () if isinstance(s, dict)]
    if boundary in ("start", "end"):
        exact = [s for s in stays if _matches(node, s, boundary, now_month)]
        if exact:
            return exact[-1]
    scored = [(o, -int(s.get("stay_index") or 0), s) for s in stays
              if (o := _overlap(node, s, now_month)) is not None]
    return max(scored, key=lambda row: (row[0], row[1]))[2] if scored else None


def _mission_boundary(label: str) -> bool:
    return bool(re.search(r"\bmission\b", label, re.I))


def fold_candidates(nodes: object, view: object, *, now_month: int | None = None) -> list[dict]:
    """:data:`A_MOVE_MOMENT_FOLDS_INTO_ITS_LANDMARK` and
    :data:`A_LANDMARK_RESTATEMENT_FOLDS_INTO_IT`, as decisions. Pure.

    One row per folded node: ``{node_id, label, domain, entry_id,
    landmark_label, stay_index, boundary, anchor, linked, why}``, where
    ``boundary`` is ``start`` / ``end`` (a move, a start or an end) or
    ``stay`` (the landmark itself, restated), and ``anchor`` is ``None`` for a
    ``stay``."""
    domains = [d for d in ((view or {}).get("domains") or ()) if isinstance(d, dict)]
    landmarks: list[tuple[str, str, dict]] = []
    own_nodes: dict[str, tuple[str, str, dict]] = {}
    for domain in domains:
        family = dt.FAMILY_OF_DOMAIN.get(collapsed_text(domain.get("domain")))
        if not family:
            continue
        for landmark in domain.get("landmarks") or ():
            if not isinstance(landmark, dict) or not landmark.get("stays"):
                continue
            row = (family, collapsed_text(domain.get("domain")), landmark)
            landmarks.append(row)
            for node_id in landmark.get("node_ids") or ():
                own_nodes[collapsed_text(node_id)] = row
    names = {collapsed_text(l.get("entry_id")): landmark_names(l) for _, _, l in landmarks}
    places = {collapsed_text(l.get("entry_id")): _place_words(l) for _, _, l in landmarks}
    missions = [(f, d, l) for f, d, l in landmarks if f == "mission" and d == "missions"]
    mission_places: set[str] = set()
    for _, _, landmark in missions:
        mission_places |= _place_words(landmark)
    out: list[dict] = []

    def emit(node: dict, domain: str, landmark: dict, stay: dict, boundary: str,
             linked: bool, why: str) -> None:
        entry_id = collapsed_text(landmark.get("entry_id"))
        stay_index = int(stay.get("stay_index") or 0)
        out.append({
            "node_id": collapsed_text(node.get("node_id")),
            "label": collapsed_text(node.get("label")),
            "domain": domain,
            "entry_id": entry_id,
            "landmark_label": collapsed_text(landmark.get("nickname")) or collapsed_text(landmark.get("label")),
            "stay_index": stay_index,
            "boundary": boundary,
            "anchor": boundary_anchor(entry_id, stay_index, boundary) if boundary != "stay" else None,
            "linked": linked,
            "why": why,
        })

    for node in nodes or ():
        if not isinstance(node, dict) or node.get("node_kind") == "period":
            continue
        node_id = collapsed_text(node.get("node_id"))
        if not node_id:
            continue
        if collapsed_text(node.get("occurrence_subject_scope")) not in ("", "owner"):
            continue
        if node_id in own_nodes:
            # The landmark's own node — the stay itself, drawn as a row.
            _, domain, landmark = own_nodes[node_id]
            stay = _pick_stay(node, landmark, "stay", now_month) or landmark["stays"][0]
            emit(node, domain, landmark, stay, "stay", True, "the landmark's own node")
            continue
        if collapsed_text(node.get("event_kind")) not in RESTATABLE_KINDS:
            continue
        label = collapsed_text(node.get("label"))
        opens_start = bool(START_VERBS.search(label))
        opens_end = bool(END_VERBS.search(label))
        graduation = collapsed_text(node.get("event_kind")) == "graduation"
        words = _tokens(label)
        moving = bool(_MOVE_WORD.search(label))
        graduating = graduation or bool(_GRADUATE_WORD.search(label))
        linked = {collapsed_text(link.get("episode_node_id"))
                  for link in node.get("proposed_links") or () if isinstance(link, dict)}
        found: list[tuple] = []
        for family, domain, landmark in landmarks:
            if moving and family not in ("home", "mission"):
                continue
            if graduating and family != "school":
                continue
            entry_id = collapsed_text(landmark.get("entry_id"))
            hit = _name_match(names[entry_id], words)
            if hit is None:
                continue
            strength, at, matched = hit
            if _residual(words, matched, places[entry_id]):
                continue  # the title says more than the landmark: a story, a row
            if opens_start or opens_end or graduation:
                boundary = "end" if graduation and not (opens_start or opens_end) \
                    else _direction(label, words, at)
            else:
                boundary = "stay"
            if (boundary == "end" and family == "home" and not moving
                    and not (set(words) & _HOME_WORDS)
                    and not (set(_tokens(landmark.get("nickname") or landmark.get("label"))) & _HOME_WORDS)):
                # "You leaves Kristen": leaving a name that is not plainly a
                # home may be leaving a person. A row.
                continue
            stay = _pick_stay(node, landmark, boundary, now_month)
            if stay is None:
                continue
            exact = boundary != "stay" and _matches(node, stay, boundary, now_month)
            bound = bool(linked & {collapsed_text(n) for n in landmark.get("node_ids") or ()})
            found.append((int(exact), int(bound), strength, -int(stay.get("stay_index") or 0),
                          domain, landmark, stay, boundary, bound))
        if not found and _mission_boundary(label) and missions and not moving:
            if not _residual(words, set(), mission_places):
                ordered = sorted(((dt.month_of(s.get("start")) or 0, l, s) for _, _, l in missions
                                  for s in l.get("stays") or ()), key=lambda row: row[0])
                if opens_end and not re.search(r"\b(?:leav\w*|left|depart\w*) (?:for|on)\b", label, re.I):
                    boundary, (_, landmark, stay) = "end", ordered[-1]
                elif opens_start:
                    boundary, (_, landmark, stay) = "start", ordered[0]
                else:
                    boundary = "stay"
                    held = [row for row in ordered if _overlap(node, row[2], now_month)]
                    _, landmark, stay = held[0] if held else ordered[0]
                first = dt.month_of(ordered[0][2].get("start"))
                last = _stay_months(ordered[-1][2], now_month)[1]
                stretch = {"start": ordered[0][2].get("start"), "end": ordered[-1][2].get("end")}
                if first is not None and last is not None and _overlap(node, stretch, now_month):
                    found.append((0, 0, 0, 0, "missions", landmark, stay, boundary, False))
        if not found:
            continue
        found.sort(key=lambda row: row[:4], reverse=True)
        _, _, _, _, domain, landmark, stay, boundary, bound = found[0]
        why = {"start": "its start", "end": "its end", "stay": "restates it"}[boundary]
        emit(node, domain, landmark, stay, boundary, bound, why)
    return sorted(out, key=lambda row: (row["entry_id"], row["stay_index"], row["boundary"], row["node_id"]))


#: The sides an anchor names: a stay's start, its end, or (v365,
#: owner 2026-09-26, the empty-landmark row) the whole stay — a drop INTO it.
ANCHOR_SIDES = ("start", "end", "stay")


def boundary_anchor(entry_id: str, stay_index: int, side: str) -> str:
    """``landmark:<entry_id>:<stay_index>:start|end|stay`` — a landmark stay's
    start or end, or the stay itself, as a drop or a fold names it."""
    return f"landmark:{entry_id}:{int(stay_index)}:{side}"


def parse_boundary_anchor(text: object) -> tuple[str, int, str] | None:
    """``(entry_id, stay_index, side)`` or ``None``."""
    body = collapsed_text(text)
    if not body.startswith("landmark:"):
        return None
    parts = body[len("landmark:"):].rsplit(":", 2)
    if len(parts) != 3 or parts[2] not in ANCHOR_SIDES or not parts[1].isdigit() or not parts[0]:
        return None
    return parts[0], int(parts[1]), parts[2]


#: What is NOT his words: the system's own derivations, the landmark
#: record's field echoes, and a quote that is a data fragment.
NOT_HIS_WORDS_EXTRACTORS = ("landmark-record/", "legacy-entry-import/")
_DATA_QUOTE = re.compile(r'^\s*["{\[]|^[\w.]+\s*=|^(?:spine|fact|story):', re.I)


def _words_of(node: dict, claims_by_id: dict) -> list[str]:
    """His words about a folded moment: the evidence quotes of its claims,
    without the system's own derivations or data fragments."""
    quotes: list[str] = []
    for ref in node.get("input_claim_refs") or ():
        claim = claims_by_id.get(collapsed_text(ref))
        if not isinstance(claim, dict) or collapsed_text(claim.get("source_kind")) == "system_derived":
            continue
        if collapsed_text(claim.get("extractor_version")).startswith(NOT_HIS_WORDS_EXTRACTORS):
            continue
        for row in claim.get("evidence") or ():
            quote = collapsed_text(row.get("quote")) if isinstance(row, dict) else ""
            if quote and not _DATA_QUOTE.search(quote) and quote not in quotes:
                quotes.append(quote)
    return quotes[:4]


def stated_fold_rows(nodes: object, view: object, stated: object) -> list[dict]:
    """:data:`A_STATED_FOLD_OUTRANKS_A_GUESSED_ONE` — the folds he made, as
    fold rows. A stated fold whose node is gone is followed by its tellings (a
    combine or a rebind moves a node id); one naming no drawn landmark stay is
    dropped."""
    by_node = {collapsed_text(n.get("node_id")): n for n in nodes or () if isinstance(n, dict)}
    by_telling: dict[str, str] = {}
    for node_id, node in by_node.items():
        for telling in node.get("tellings") or ():
            by_telling.setdefault(collapsed_text(telling), node_id)
    landmarks = {collapsed_text(l.get("entry_id")): (collapsed_text(d.get("domain")), l)
                 for d in ((view or {}).get("domains") or ()) for l in d.get("landmarks") or ()}
    out: list[dict] = []
    for fold in stated or ():
        node_id = collapsed_text(fold.get("node_id"))
        if node_id not in by_node:
            node_id = next((by_telling[t] for t in fold.get("tellings") or () if t in by_telling), "")
        found = landmarks.get(collapsed_text(fold.get("entry_id")))
        if not node_id or found is None or by_node[node_id].get("node_kind") == "period":
            continue
        domain, landmark = found
        index = int(fold.get("stay_index") or 0)
        if index not in {int(s.get("stay_index") or 0) for s in landmark.get("stays") or ()}:
            continue
        out.append({
            "node_id": node_id,
            "label": collapsed_text(by_node[node_id].get("label")),
            "domain": domain,
            "entry_id": collapsed_text(landmark.get("entry_id")),
            "landmark_label": collapsed_text(landmark.get("nickname")) or collapsed_text(landmark.get("label")),
            "stay_index": index,
            "boundary": "stay",
            "anchor": None,
            "linked": False,
            "why": "you folded it",
            "stated": True,
            "fold_id": collapsed_text(fold.get("fold_id")),
        })
    return out


def apply_folds(nodes: object, view: object, *, claims: object = (),
                now_month: int | None = None, stated: object = ()) -> list[dict]:
    """Fold, in place: mark each folded node, attach its tellings to its
    landmark (``tellings``), and list the folds on the view (``folds``).

    ``stated`` is the owner's own folds (`timeline_combine.stated_folds`),
    applied first (:data:`A_STATED_FOLD_OUTRANKS_A_GUESSED_ONE`).

    Returns the fold rows. A vault with nothing to fold publishes exactly as
    before (no keys added)."""
    if not isinstance(view, dict):
        return []
    mine = stated_fold_rows(nodes, view, stated)
    taken = {row["node_id"] for row in mine}
    rows = mine + [row for row in fold_candidates(nodes, view, now_month=now_month)
                   if row["node_id"] not in taken]
    rows.sort(key=lambda row: (row["entry_id"], row["stay_index"], row["boundary"], row["node_id"]))
    if not rows:
        return []
    by_node = {collapsed_text(n.get("node_id")): n for n in nodes or () if isinstance(n, dict)}
    claims_by_id = {collapsed_text(c.get("claim_id")): c for c in claims or () if isinstance(c, dict)}
    landmarks = {collapsed_text(l.get("entry_id")): l
                 for d in view.get("domains") or () for l in d.get("landmarks") or ()}
    for row in rows:
        node = by_node[row["node_id"]]
        node["folded_into_landmark"] = row["entry_id"]
        if row["anchor"]:
            node["folded_boundary"] = row["anchor"]
        else:
            node["folded_as"] = "stated" if row.get("stated") else "restatement"
        if row.get("fold_id"):
            node["fold_id"] = row["fold_id"]
        record = dt.placement_of(node) or {}
        landmark = landmarks[row["entry_id"]]
        landmark.setdefault("tellings", []).append({
            "node_id": row["node_id"],
            "label": row["label"],
            "boundary": row["boundary"],
            "stay_index": row["stay_index"],
            "when": collapsed_text(record.get("best")) or None,
            "words": _words_of(node, claims_by_id),
            **({"stated": True, "fold_id": row["fold_id"]} if row.get("stated") else {}),
        })
    view["folds"] = rows
    view["fold_rule_version"] = LANDMARK_FOLD_RULE_VERSION
    return rows


__all__ = [
    "A_LANDMARK_RESTATEMENT_FOLDS_INTO_IT", "A_MOVE_MOMENT_FOLDS_INTO_ITS_LANDMARK",
    "A_STATED_FOLD_OUTRANKS_A_GUESSED_ONE", "ANCHOR_SIDES", "END_VERBS", "LANDMARK_FOLD_RULE_VERSION",
    "START_VERBS", "apply_folds", "boundary_anchor", "fold_candidates", "landmark_names",
    "parse_boundary_anchor", "stated_fold_rows",
]
