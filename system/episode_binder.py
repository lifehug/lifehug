"""Event identity I2 — the binder: retrieve, then decide, one telling at a time.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 —
§4.1 (retrieval and the plausibility filter), §4.2 (rung R1), §4.5 (the
safeguards that ship WITH R1), §5.6 (the re-audit), §6.1's caps and §8's
dry-run. Phase **I2**. I0 settled what a record MEANS
(`system/event_identity.py`, `system/episode_fold_contract.py`,
`system/episode_routing_contract.py`); I1 taught the fold to APPLY one
(`system/episode_fold.py`); this is the first phase that DECIDES one.

**What a binder is.** Coreference search, in three steps and no more: one
telling, a handful of candidates retrieved cheaply, one decision with a
receipt. There is no clustering pass over the life, no similarity threshold,
no embedding and no model call — R1 is arithmetic over what the tellings
themselves say, and everything R1 declines becomes a QUESTION rather than a
guess (Law 6: *a miss is cheap, a wrong link is not*).

**Nothing here is a question, by itself.** The binder emits pairwise
`same_event` and `possible_overmerge` OUTPUTS — rows carrying the pair key C4
pinned, the reasons, and the inputs the queue's existing value scoring reads.
:func:`same_event_work_items` and :func:`possible_overmerge_work_items`
(event identity **I3**) turn those rows into ordinary
`temporal_projection.TemporalWorkItem`s through the SAME value-scoring
formula every other kind uses (`temporal_timeline.work_item_score`) — no
priority of their own, exactly as §4.1 requires. Probe text, the five
answers and `resolve-work-item` live in `identity_questions.py`, I3's own
module; this file only says what happened, never how a person answers it.

**Nothing here writes by itself.** `bind_episodes(..., apply=False)` — the
`--dry-run` the owner reviews before anything applies (§8.1) — writes not one
byte and prints every §4.2 condition's pass and fail per pair. `--apply` goes
through `event_identity`'s ordinary writers, so replay is a no-op by
arithmetic and the delete-and-reproduce promise (G1) holds for what it wrote.

**The deterministic act is a `create` over the whole cluster**, and that is
the one place §4.2's prose had to be read rather than transcribed — see
:data:`CLUSTER_RULE_TEXT`. Everything else in R1 is the design's own seven
conditions, in its own order, with its own names.

Synthetic data only; this module NEVER references any real vault.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import cross_dating  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from identity_resolution import REPEATABLE_EVENT_KINDS  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
)

# --------------------------------------------------------------------------
# Vocabulary — imported, never restated (ADR 0021)
# --------------------------------------------------------------------------

#: The rule this module's records name. ONE HOME: C3's. A second assignment
#: anywhere in this program's modules fails
#: `test_event_identity_i0_operations.py`'s one-home sweep, which this phase
#: widens to include this file.
RULE_VERSION = efc.IDENTITY_RULE_VERSION

#: The deterministic rung's own id, on every binding it files. `R1` is the
#: design's name for it (§4.2) and the record carries it so a later rung, a
#: later rule version or a human reading a receipt can tell what decided.
RULE_ID = "R1"

#: The work-item kind a declined pair becomes. Registered in
#: `temporal_projection.WORK_ITEM_KINDS` at event identity I3, once
#: `identity_questions.py` exists to file the five answers it can be asked.
SAME_EVENT_KIND = "same_event"

#: §4.5/§5.6's second kind, defined once by C4.
POSSIBLE_OVERMERGE_KIND = erc.POSSIBLE_OVERMERGE_KIND


# --------------------------------------------------------------------------
# §4.1 — retrieval
# --------------------------------------------------------------------------

#: §4.1's six blocking signals, in the design's own order. A candidate episode
#: shares ANY of them with the telling, and the SCORE below is one point per
#: independent signal — "independent" being why the label token and the
#: participants are two rows and not one: a re-extraction that rewrote the
#: label did not also rewrite who was there.
RETRIEVAL_SIGNALS = (
    "participant",
    "place",
    "era",
    "bounds_in_frame",
    "label_token",
    "source_document",
)

#: Below this, the candidate is DROPPED SILENTLY (§4.1). Not asked, not
#: reported to the person, not remembered as a negative: absence is not a
#: decision, and a queue full of "these two things share the word Tuesday" is
#: how a question surface stops being read.
PLAUSIBILITY_FLOOR = 2

#: A label token is retrieval evidence only when it could be a NAME. Four
#: characters is the design's number; the stopword table below is what keeps
#: "with", "from" and "about" out of it.
LABEL_TOKEN_MIN_CHARS = 4

#: Fixed, small, and deliberately not a language model's idea of a stopword
#: list: these are the words that survive `normalized_mention_key` at four or
#: more characters and say nothing about WHICH event a sentence is about.
LABEL_TOKEN_STOPWORDS = frozenset({
    "about", "after", "again", "along", "already", "also", "another", "around",
    "back", "because", "been", "before", "being", "between", "both", "came",
    "come", "could", "does", "doing", "done", "down", "during", "each", "even",
    "ever", "every", "from", "gone", "have", "having", "here", "into", "just",
    "know", "less", "like", "made", "make", "many", "more", "most", "much",
    "must", "near", "next", "once", "only", "onto", "other", "over", "really",
    "said", "same", "several", "should", "since", "some", "somebody",
    "something", "sometime", "still", "such", "than", "that", "their", "them",
    "then", "there", "these", "they", "thing", "things", "this", "those",
    "though", "three", "through", "time", "times", "under", "until", "upon",
    "very", "want", "well", "went", "were", "what", "when", "where", "which",
    "while", "with", "within", "without", "would", "your",
})

#: §4.1's ERA signal is served from an ARGUMENT, and nothing on the vault path
#: populates it yet. Named here rather than left to be discovered in a diff:
#: era membership is decided by the fold, over records this module does not
#: own, and is keyed on a CALCULATED node id — so producing it inside the
#: binder would mean either a second copy of the eras fold or a whole fold
#: pass per run, and the design's own §5.7 budget did not buy one. The
#: consequence is honest and one-directional: on a live vault a pair scores
#: one signal FEWER, so it can only ever be retrieved less, never bound
#: wrongly. The seam is `plan(era_memberships=...)` and `bind_episodes(
#: era_memberships=...)`; a host that already holds the fold's memberships
#: passes them and the signal fires, which is what the test proves.
ERA_SIGNAL_IS_SUPPLIED_BY_THE_HOST = (
    "the era retrieval signal is an input, not a derivation: a host that "
    "holds the fold's memberships supplies them and the signal fires; the "
    "binder never re-derives era membership, and without them a pair simply "
    "scores one signal fewer"
)

#: How far apart two dated tellings must be before a PLACE disagreement stops
#: being evidence against them (§4.5, time-decay). Three years is the design's
#: "wide gap" made a number: a company that moved office between two tellings
#: is the ordinary case, and vetoing on it is how a real episode stays split.
TIME_DECAY_GAP_YEARS = 3


# --------------------------------------------------------------------------
# §4.2 condition 1 — the kind-family table, parity-pinned
# --------------------------------------------------------------------------

#: §4.2 condition 1's `moment`+`job`… table, in code. Two kinds are compatible
#: when they share a family; `moment` is a member of every family because the
#: classifier's own kind for "a thing that happened" is `moment` and refusing
#: it would refuse the entire classifier lane — but it is a WILDCARD, not a
#: solvent: `job` and `school` still share no family, and neither does `idea`
#: with anything, which is the design's own founder counterexample.
#:
#: PARITY: the members are `temporal_claims.EVENT_KINDS` plus `moment` and
#: `residence`, and `test_event_identity_i2_binder.py` sweeps the seed list so
#: an event kind added upstream cannot silently fall out of every family and
#: become quietly un-bindable.
KIND_WILDCARD = "moment"

KIND_FAMILIES = (
    ("work", ("job", "started", "ended", "transition", "span")),
    ("schooling", ("school", "graduation")),
    ("dwelling", ("move", "residence")),
    ("partnership", ("first_met", "dating_started", "engaged", "married",
                     "separated", "divorced", "reconciled")),
    ("arrival", ("birth", "child_born")),
    ("parting", ("death", "loss")),
    ("service", ("military",)),
)

#: Event kinds with no family at all — named so the refusal reads as a
#: DECISION rather than as a table nobody finished. An unfamilied kind is
#: retrieved, scored and asked about; it is never deterministically bound.
UNFAMILIED_KINDS_ARE_ASKED = (
    "a kind that is in no family is never bound by R1 and is always asked; "
    "the family table is a floor on certainty, not a list of what may exist"
)


# --------------------------------------------------------------------------
# §4.2 condition 3 — exact label stems, over a fixed event-verb table
# --------------------------------------------------------------------------

#: The fixed event-verb table §4.2 condition 3 requires — twenty-one entries,
#: each mapping the ways one act is said to ONE stem. It is deliberately a
#: closed table rather than a stemmer: "started", "founded" and "co-founded"
#: are one act and must produce one stem, while "ran" and "sold" are different
#: acts that a stemmer would happily leave adjacent. A verb outside this table
#: stays a subject token, so an unrecognized verb makes a stem MORE specific
#: and can only ever refuse a bind.
EVENT_VERB_STEMS = {
    "found": "found", "founded": "found", "founding": "found",
    "cofound": "found", "cofounded": "found", "cofounding": "found",
    "start": "found", "started": "found", "starting": "found",
    "launch": "found", "launched": "found", "launching": "found",
    "join": "join", "joined": "join", "joining": "join",
    "leave": "leave", "left": "leave", "leaving": "leave",
    "quit": "leave", "resign": "leave", "resigned": "leave",
    "move": "move", "moved": "move", "moving": "move",
    "marry": "marry", "married": "marry", "marrying": "marry", "wed": "marry",
    "meet": "meet", "met": "meet", "meeting": "meet",
    "graduate": "graduate", "graduated": "graduate", "graduating": "graduate",
    "born": "born", "birth": "born",
    "die": "die", "died": "die", "death": "die", "passed": "die",
    "buy": "buy", "bought": "buy", "buying": "buy", "purchased": "buy",
    "sell": "sell", "sold": "sell", "selling": "sell",
    "build": "build", "built": "build", "building": "build",
    "hire": "hire", "hired": "hire", "hiring": "hire",
    "study": "study", "studied": "study", "studying": "study",
    "serve": "serve", "served": "serve", "serving": "serve",
    "visit": "visit", "visited": "visit", "visiting": "visit",
    "adopt": "adopt", "adopted": "adopt", "adopting": "adopt",
    "retire": "retire", "retired": "retire", "retiring": "retire",
}

#: Words that carry no act and no name; dropped before a stem is formed so
#: "Co-founded Etherfuse" and "Started Etherfuse" reduce to the same thing.
STEM_STOPWORDS = frozenset(LABEL_TOKEN_STOPWORDS | {
    "a", "an", "and", "as", "at", "be", "but", "by", "co", "did", "do", "for",
    "got", "had", "has", "he", "her", "him", "his", "i", "in", "is", "it",
    "its", "me", "my", "no", "not", "of", "off", "on", "one", "or", "our",
    "out", "she", "so", "the", "to", "two", "up", "us", "was", "we",
    "who", "why", "you",
})

#: How a stem is spelled. The design writes it `etherfuse-found`; this is that
#: sentence as a format, so a fixture and the code cannot disagree about it.
STEM_JOIN = "-"


# --------------------------------------------------------------------------
# §4.2 condition 4 — the non-label, non-owner signals
# --------------------------------------------------------------------------

#: §4.2 condition 4's four, verbatim. TWO of them must hold, and neither the
#: label nor the owner may be one of them — the owner is on every telling, so
#: agreeing about him is not evidence about anything.
INDEPENDENT_SIGNALS = ("source_document", "place", "participant", "bounds")

#: How many of them (§4.2 condition 4).
REQUIRED_INDEPENDENT_SIGNALS = 2


# --------------------------------------------------------------------------
# §4.2 — the seven conditions, in order and by name
# --------------------------------------------------------------------------

#: The conditions §4.2 enumerates, in §4.2's order. Every dry-run line prints
#: all seven with a verdict, because §4.2's own last sentence is that the dry
#: run prints per-pair REASONS and not counts.
R1_CONDITIONS = (
    "kind_family",
    "repeatable_protection",
    "label_stems_match",
    "two_independent_signals",
    "one_surviving_candidate",
    "no_not_same",
    "not_joining_two_mature_episodes",
)

#: What a pair can come to. `blocked` is the one outcome that produces NOTHING
#: — no bind, no question, no row — because the person already answered it.
VERDICTS = ("bind", "part_of", "proposal", "ambiguous", "asked", "blocked")

#: An episode holding this many tellings is "mature" for §4.2 condition 7.
MATURE_EPISODE_MEMBERS = 2

#: §4.2, verbatim, so the module states the rule it implements.
R1_RULE_TEXT = (
    "R1 binds `same` with origin `deterministic` iff all seven hold: the "
    "kinds are in one family; a repeatable-kind episode is never joined by an "
    "undated telling; the label stems match exactly; two independent signals "
    "beyond the owner and beyond the label agree; exactly one candidate "
    "survives conditions 1-4; there is no active or entailed `not_same`; and "
    "the bind would not join two episodes that each hold two or more "
    "tellings. A label-only match is a proposal, never a bind."
)

#: Where §4.2's prose had to be READ rather than transcribed, stated in the
#: module rather than discovered in a diff.
CLUSTER_RULE_TEXT = (
    "§4.2 names the seven conditions and §5.8 row 1 names the envelope for "
    "the case it enumerates — two standalone tellings become one `create`. It "
    "does not name the envelope for a telling joining an episode that already "
    "exists, and the operation vocabulary C2 froze has no `add`. So the "
    "binder's deterministic act is ONE `create` over the whole cluster, and "
    "growth reuses §3.2's own rule-version mechanism: the new create lists "
    "the superseded episode in `aliases_created` and supersedes its "
    "bindings, so no id is ever orphaned. An ADOPTED episode, or one made by "
    "human authority, is never superseded this way — G1 says a deterministic "
    "rule may file proposals against what a person acted on and may not move "
    "it — so a telling that would join one becomes a proposal instead."
)


# --------------------------------------------------------------------------
# §4.2 — deterministic `part_of` needs explicit containment language
# --------------------------------------------------------------------------

#: The substring `part_of` rule is DELETED (audit A4). Deterministic `part_of`
#: requires the telling to SAY it is inside something, and these are the ways
#: it says so. A phrase is followed by the container's name within
#: :data:`CONTAINMENT_WINDOW` tokens, or it is not containment language.
CONTAINMENT_PHRASES = (
    ("during",), ("while", "at"), ("while", "i", "was", "at"),
    ("at", "the"), ("in", "the", "middle", "of"), ("partway", "through"),
    ("halfway", "through"), ("as", "part", "of"), ("part", "of"),
    ("over", "at"), ("back", "at"),
)

#: How many tokens after the phrase may name the container.
CONTAINMENT_WINDOW = 4


# --------------------------------------------------------------------------
# §6.1 — the caps
# --------------------------------------------------------------------------

#: §6.1: the product surfaces at most ONE pair per telling at a time. The
#: binder emits every plausible pair as DATA and marks which one is eligible
#: to be surfaced; I3 is what shows it and what makes the next one eligible
#: after a `Different`.
SURFACED_PAIRS_PER_TELLING = 1

#: §4.1's global open-question cap — an owner knob, and this is its default.
GLOBAL_QUESTION_CAP = 25


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class EpisodeBinderError(TemporalContractError):
    """The binder was handed something it will not reason over."""


#: Every refusal this module raises, enumerated the way
#: `temporal_claims.ERROR_CODES` is, and swept from source by a test.
BINDER_ERROR_CODES = (
    "binder_unknown_verdict",
    "binder_apply_needs_a_plan",
    "binder_cap_out_of_range",
)


def _require(condition: object, code: str, message: str, **detail: object) -> None:
    if not condition:
        raise EpisodeBinderError(code, message, detail=detail or None)


# --------------------------------------------------------------------------
# Label stems and tokens
# --------------------------------------------------------------------------


def label_tokens(text: object) -> tuple[str, ...]:
    """The normalized word tokens of a label, in order, nothing dropped."""
    return tuple(normalized_mention_key(text).split())


def proper_noun_tokens(text: object) -> frozenset[str]:
    """§4.1's retrieval token set: >= 4 characters, not a stopword.

    Deliberately not "capitalized in the source": the substrate stores
    `normalized_mention_key` output, capitalization is gone by the time the
    binder sees anything, and a rule that depended on it would work on the
    classifier's lane and silently never fire on the recorder's.
    """
    return frozenset(
        token for token in label_tokens(text)
        if len(token) >= LABEL_TOKEN_MIN_CHARS and token not in LABEL_TOKEN_STOPWORDS
    )


#: The recorder puts a telling's ACT in `event_kind` (`started`, `married`,
#: `move`) and its NAME in `subject_mention` ("Etherfuse", "Boeing"), while the
#: classifier puts both in one sentence ("Started Etherfuse"). §4.2 condition 3
#: compares stems exactly, so reading the verb only out of prose made every
#: recorder telling's stem a bare name and no recorder telling could ever match
#: a classifier one — which on the founder's vault meant the DATED landmark
#: rows, the only rows that can date anything, were unmatchable by
#: construction. The kind is folded in as a verb when it names one, so the same
#: rule reads the same fact from wherever a source kind keeps it. This makes a
#: recorder stem MORE specific, never less: it can only ever refuse a match
#: that a bare name would have allowed, and it changes no bind on the founder
#: vault (§4.2 condition 4 still gates every one of them).
KIND_IS_THE_VERB_FOR_A_RECORDER_TELLING = (
    "a telling's act is a verb in its words or a kind in its record; the stem "
    "reads whichever one the source kind carries, and never invents a second "
    "rule for the other"
)


def label_stem(text: object, participants: object = (), event_kind: object = None) -> str:
    """The exact stem §4.2 condition 3 compares — `etherfuse-found`.

    Subject tokens and verb stems, each sorted, joined by :data:`STEM_JOIN`.

    Two things this has to get right that a first reading does not:

    * **Participants are removed, but never down to nothing.** Who was there
      is condition 4's evidence and counting it twice would let one fact
      satisfy two supposedly independent signals — so "Co-founded Etherfuse
      with AJ" drops `aj` and keeps `etherfuse-found`. But a RECORDER telling's
      subject IS the thing ("Etherfuse", started, 2022-05), so subtracting it
      erased the entire label and left a stem of `""` that could never match
      anything. The cast is evidence BESIDE the label, never INSTEAD of it: if
      the subtraction empties the stem, the unsubtracted stem stands.
    * **The act may be a kind rather than a word**
      (:data:`KIND_IS_THE_VERB_FOR_A_RECORDER_TELLING`).

    A label with no tokens at all still has no stem, and a telling with no stem
    never matches anything — absence never binds.
    """
    known = {normalized_mention_key(value) for value in participants or ()}
    known |= {part for value in known for part in value.split()}
    subjects: set[str] = set()
    dropped: set[str] = set()
    verbs: set[str] = set()
    for token in label_tokens(text):
        if token in STEM_STOPWORDS:
            continue
        if token in EVENT_VERB_STEMS:
            verbs.add(EVENT_VERB_STEMS[token])
            continue
        if token in known:
            dropped.add(token)
            continue
        subjects.add(token)
    kind_verb = EVENT_VERB_STEMS.get(collapsed_text(event_kind))
    if kind_verb:
        verbs.add(kind_verb)
    if not subjects and dropped:
        subjects = dropped
    parts = sorted(subjects) + sorted(verbs)
    return STEM_JOIN.join(parts)


def containment_targets(texts: object) -> frozenset[str]:
    """Tokens a telling names as its CONTAINER, per :data:`CONTAINMENT_PHRASES`.

    "Big Etherfuse event during Etherfuse" is not what makes the containment;
    "during Etherfuse" is, and only the tokens inside the window after the
    phrase count. A telling that merely MENTIONS a name yields nothing here,
    which is the deleted substring rule staying deleted.
    """
    found: set[str] = set()
    for text in texts or ():
        tokens = label_tokens(text)
        for index in range(len(tokens)):
            for phrase in CONTAINMENT_PHRASES:
                end = index + len(phrase)
                if tuple(tokens[index:end]) != phrase:
                    continue
                for token in tokens[end:end + CONTAINMENT_WINDOW]:
                    if len(token) >= LABEL_TOKEN_MIN_CHARS and \
                            token not in LABEL_TOKEN_STOPWORDS:
                        found.add(token)
    return frozenset(found)


def kind_families(kind: object) -> frozenset[str]:
    """Every family one event kind belongs to; the wildcard is in all of them."""
    key = collapsed_text(kind)
    if not key:
        return frozenset()
    if key == KIND_WILDCARD:
        return frozenset(name for name, _members in KIND_FAMILIES)
    return frozenset(name for name, members in KIND_FAMILIES if key in members)


def kinds_compatible(left: object, right: object) -> bool:
    """§4.2 condition 1. Two kinds are compatible iff they share a family."""
    return bool(kind_families(left) & kind_families(right))


def is_repeatable(kind: object) -> bool:
    """§4.2 condition 2's gate, over `identity_resolution`'s own list.

    Imported rather than restated: a life can hold more than one job and that
    fact already has exactly one home in this repo.
    """
    return collapsed_text(kind) in REPEATABLE_EVENT_KINDS


# --------------------------------------------------------------------------
# What the binder reasons over
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TellingView:
    """One telling, reduced to the six things §4.1 and §4.2 actually read.

    Built once per telling and never rebuilt: every pair the telling takes
    part in reads the same view, which is what keeps a run over a whole vault
    linear in claims rather than quadratic in them.
    """

    telling_ref: str
    event_kind: str
    label: str
    stem: str
    tokens: frozenset
    places: frozenset
    participants: frozenset
    eras: frozenset
    documents: frozenset
    bounds: object = None
    dated: bool = False
    containment: frozenset = frozenset()
    created_at: str = ""
    eligible: bool = True
    ineligible_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "telling_ref": self.telling_ref,
            "event_kind": self.event_kind,
            "label": self.label,
            "stem": self.stem,
            "tokens": sorted(self.tokens),
            "places": sorted(self.places),
            "participants": sorted(self.participants),
            "eras": sorted(self.eras),
            "documents": sorted(self.documents),
            "dated": self.dated,
            "containment": sorted(self.containment),
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
        }


@dataclass(frozen=True)
class Candidate:
    """One unit a telling may be about: an existing episode, or one standalone
    telling that would become one.

    A standalone telling is a candidate because §5.8 row 1 says two of them
    become an episode — so the retrieval side cannot only know about episodes
    that already exist, or a virgin vault would have nothing to bind to and
    the binder would only ever grow what somebody had already made by hand.
    """

    key: str
    kind: str                      # "episode" | "prospective"
    members: tuple
    event_kind: str
    stems: frozenset
    tokens: frozenset
    places: frozenset
    participants: frozenset
    eras: frozenset
    documents: frozenset
    bounds: object = None
    dated: bool = False
    episode_id: str = ""
    adopted: bool = False
    authority: str = ""

    @property
    def mature(self) -> bool:
        """§4.2 condition 7's "two or more tellings"."""
        return len(self.members) >= MATURE_EPISODE_MEMBERS


@dataclass(frozen=True)
class Condition:
    """One of §4.2's seven, with the reason it went the way it went."""

    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"condition": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class Pair:
    """One (telling, candidate) pair: its signals, its seven conditions, its
    verdict, and the one line a dry run prints for it.

    R1 is evaluated in BOTH directions — it has to be, because four of the
    seven conditions are asymmetric (a repeatable-kind episode protects itself
    only in the direction that reaches it) and because a bind requires both
    sides to have chosen each other. But a pair is ONE thing: two tellings are
    the same event or they are not. :attr:`units` is that identity, and
    `plan()` reports and emits exactly one row per unit pair.
    """

    telling_ref: str
    home_key: str
    candidate_key: str
    candidate_episode_id: str
    candidate_kind: str
    signals: tuple = ()
    plausibility: int = 0
    conditions: tuple = ()
    verdict: str = "asked"
    relation_hint: str = efc.GROUPING_RELATION
    part_of_suggestive: bool = False
    surfaced: bool = False
    reason: str = ""
    #: The other direction's failed conditions, folded in when the two rows
    #: collapsed — so a merged row still says everything either side refused.
    also_failed: tuple = ()

    @property
    def units(self) -> tuple:
        """The unordered pair of UNITS — the pair's own identity.

        Not the two episode ids: for a telling measured against an existing
        episode, the reverse direction names a *prospective* episode id built
        out of one member and the telling, which is a different string for the
        same question.
        """
        return tuple(sorted((self.home_key, self.candidate_key)))

    @property
    def event_key(self) -> str:
        """§6.1's pair key, minted by C4 and never re-spelled here."""
        return erc.pair_event_key(self.telling_ref, self.candidate_episode_id)

    def failed(self) -> tuple:
        return tuple(row.name for row in self.conditions if not row.passed)

    def as_dict(self) -> dict:
        return {
            "telling_ref": self.telling_ref,
            "home_key": self.home_key,
            "candidate_key": self.candidate_key,
            "units": list(self.units),
            "candidate_episode_id": self.candidate_episode_id,
            "candidate_kind": self.candidate_kind,
            "event_key": self.event_key,
            "signals": list(self.signals),
            "plausibility": self.plausibility,
            "conditions": [row.as_dict() for row in self.conditions],
            "failed": list(self.failed()),
            "also_failed": list(self.also_failed),
            "verdict": self.verdict,
            "relation_hint": self.relation_hint,
            "part_of_suggestive": self.part_of_suggestive,
            "surfaced": self.surfaced,
            "reason": self.reason,
        }


@dataclass
class BinderPlan:
    """Everything one run decided, and not one byte written.

    `--dry-run` prints this; `--apply` files :attr:`envelopes` and
    :attr:`proposals` through `event_identity`'s ordinary writers and files
    nothing else. Questions are OUTPUTS: I3 turns them into probes.
    """

    pairs: list = field(default_factory=list)
    #: Every row R1 actually judged, both directions. `pairs` is the collapsed
    #: view and is what everything downstream reads; this is kept because the
    #: asymmetric conditions are only visible here.
    directional: list = field(default_factory=list)
    envelopes: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    overmerges: list = field(default_factory=list)
    bridges: list = field(default_factory=list)
    reaudits: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    dropped: int = 0
    views: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule_version": RULE_VERSION,
            "rule_id": RULE_ID,
            "pairs": [row.as_dict() for row in self.pairs],
            "directional_pairs": len(self.directional),
            "envelopes": [
                {"operation": row["operation"], "bindings": row["bindings"],
                 "aliases_created": row["operation"]["aliases_created"]}
                for row in self.envelopes
            ],
            "proposals": list(self.proposals),
            "questions": list(self.questions),
            "overmerges": list(self.overmerges),
            "bridges": list(self.bridges),
            "reaudits": list(self.reaudits),
            "counts": dict(self.counts),
        }


# --------------------------------------------------------------------------
# Building the views
# --------------------------------------------------------------------------


def _claim_texts(claims: Sequence[object]) -> tuple[str, ...]:
    """The telling's own words: its event mentions and its evidence quotes.

    §4.2 says containment language is "parsed by the recorder into the
    signature". No extractor emits a structured containment field today, so
    the binder reads the telling's OWN words — never a neighbouring telling's,
    never a candidate's — and the named phrase table is the parse. See the PR
    body's deviation note.
    """
    found: list[str] = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        for value in (row.get("event_mention"), row.get("subject_mention")):
            text = collapsed_text(value)
            if text:
                found.append(text)
        for span in row.get("evidence") or ():
            cell = span if isinstance(span, dict) else {}
            quote = collapsed_text(cell.get("quote"))
            if quote:
                found.append(quote)
    return tuple(dict.fromkeys(found))


def _label_of(claims: Sequence[object]) -> str:
    """What the telling calls the thing — its event mentions, deduped, joined.

    Joined rather than "the first one" because a telling with two claims about
    one event may name it twice, and a stem built from half a label would
    match things the whole label does not. Joining can only ever make a stem
    MORE specific, which is the safe direction.
    """
    found: list[str] = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        text = collapsed_text(row.get("event_mention"))
        if text and text not in found:
            found.append(text)
    if found:
        return " ".join(found)
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        text = collapsed_text(row.get("subject_mention"))
        if text:
            return text
    return ""


def _kind_of(claims: Sequence[object]) -> str:
    """The telling's event kind: a real one if it has one, else the wildcard.

    Sorted-then-first among the non-wildcard kinds, so a telling whose claims
    disagree resolves the same way on every machine and in every order.
    """
    kinds = sorted({
        collapsed_text((claim if isinstance(claim, dict) else {}).get("event_kind"))
        for claim in claims or ()
    } - {""})
    real = [kind for kind in kinds if kind != KIND_WILDCARD]
    return real[0] if real else (kinds[0] if kinds else "")


def _documents_of(telling_ref: str, claims: Sequence[object]) -> frozenset:
    """The source DOCUMENTS a telling came out of, not its own source id.

    A classifier telling's ref is ``classification:<stem>#<event key>`` — one
    story, many events — so the stem is what "the same source-local document
    narrating both" (§4.2 condition 4) actually means. Splitting on ``#``
    rather than re-deriving it keeps this module out of `classifier_claims`'
    business.
    """
    found: set[str] = set()
    head, _, tail = telling_ref.partition("#")
    if tail:
        found.add(head)
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        ref = row.get("source_ref") if isinstance(row.get("source_ref"), dict) else {}
        source_id = collapsed_text(ref.get("source_id"))
        if source_id:
            found.add(source_id.partition("#")[0])
    return frozenset(found)


def _bounds_of(claims: Sequence[object]) -> tuple[object, bool]:
    """``(the telling's stated interval, whether it is dated at all)``.

    `chronology.intersect` is the whole rule: the tightest bounds every dated
    claim in the telling allows, and ``None`` when they are DISJOINT — which
    is a contradiction inside one telling and not this module's to settle, so
    it reads as "no usable bounds" and the telling simply never satisfies the
    bounds signal.
    """
    records = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        record = chrono.from_dict(row.get("temporal_value"))
        if record is not None:
            records.append(record)
    if not records:
        return None, False
    return chrono.intersect(*records), True


def telling_views(claims: object, *, manifest: object = None,
                  era_memberships: object = None) -> dict:
    """``{telling_ref: TellingView}`` — pure, over the claims and nothing else.

    The claim→telling map is `episode_fold.claim_telling_index`, which is C1's
    own; a second answer to "which telling is this claim part of" is exactly
    the drift this program exists to remove.

    ``era_memberships`` is ``{telling_ref: [era id, …]}`` and is an ARGUMENT
    rather than a read: era membership is decided by the fold over records
    this module does not own, and re-deriving it here would be a second copy
    of the eras fold living inside the binder.
    """
    rows = [row for row in (claims or ()) if isinstance(row, dict)]
    index = ef.claim_telling_index(rows, manifest)
    by_telling: dict[str, list] = {}
    for claim in rows:
        telling_ref = collapsed_text(index.get(collapsed_text(claim.get("claim_id"))))
        if telling_ref:
            by_telling.setdefault(telling_ref, []).append(claim)
    eras = {
        collapsed_text(key): frozenset(
            collapsed_text(value) for value in (values or ()) if collapsed_text(value)
        )
        for key, values in dict(era_memberships or {}).items()
    }

    views: dict[str, TellingView] = {}
    for telling_ref in sorted(by_telling):
        rows_here = by_telling[telling_ref]
        signature = ei.telling_signature(rows_here)
        label = _label_of(rows_here)
        participants = frozenset(signature.get("participant_set") or ())
        bounds, dated = _bounds_of(rows_here)
        about_an_era = ei.telling_is_about_an_era(rows_here)
        # §5.1 is claim-precise, and so is this. A telling ABOUT an era (C1's
        # own subject-side predicate) is never a binding target. A telling
        # whose every claim is era-BOUND is not one either — C3 refuses each
        # of those claims individually, so a bind on it would group nothing
        # and be reported as `identity_binding_to_era_bound_claim`. A telling
        # with one era-bound claim among several keeps FULL eligibility: that
        # is audit F-pin 1's own failure case and it stays a candidate.
        era_bound = [row for row in rows_here
                     if efc.claim_event_ref_kind(row) == "era"]
        all_era_bound = bool(rows_here) and len(era_bound) == len(rows_here)
        views[telling_ref] = TellingView(
            telling_ref=telling_ref,
            event_kind=_kind_of(rows_here),
            label=label,
            stem=label_stem(label, participants, event_kind=_kind_of(rows_here)),
            tokens=proper_noun_tokens(label),
            places=frozenset(signature.get("place_set") or ()),
            participants=participants,
            eras=eras.get(telling_ref, frozenset()),
            documents=_documents_of(telling_ref, rows_here),
            bounds=bounds,
            dated=dated,
            containment=containment_targets(_claim_texts(rows_here)),
            created_at=max(
                (collapsed_text(row.get("created_at")) for row in rows_here), default=""
            ),
            eligible=not (about_an_era or all_era_bound),
            ineligible_reason=(
                ei.INELIGIBLE_TELLING_IS_AN_ERA if about_an_era
                else (efc.DIAGNOSTIC_BINDING_TO_ERA_CLAIM if all_era_bound else "")
            ),
        )
    return views


# --------------------------------------------------------------------------
# Candidates — existing episodes, and the standalone tellings that could be one
# --------------------------------------------------------------------------


def prospective_episode_id(member_refs: Sequence[object]) -> str:
    """The episode id a `create` over exactly these members WOULD mint.

    Used as the candidate component of a pair key (§6.1) when the candidate is
    a standalone telling: the pair has to be nameable BEFORE anything exists,
    and naming it by arithmetic means that if the person later says "yes", the
    episode the answer creates is the very id the question was asked about.
    Nothing is written to compute it — it is `event_identity`'s own digest.
    """
    return ei.episode_id_for(
        ei.operation_digest(
            authority="deterministic", op="create", rule_version=RULE_VERSION,
            member_refs=list(member_refs),
        )
    )


def _unit(key: str, kind: str, members: Sequence[str], views: Mapping[str, TellingView],
          *, event_kind: str = "", episode_id: str = "", adopted: bool = False,
          authority: str = "") -> Candidate:
    rows = [views[ref] for ref in members if ref in views]
    records = [row.bounds for row in rows if row.bounds is not None]
    bounds = chrono.intersect(*records) if records else None
    kinds = sorted({row.event_kind for row in rows} - {"", KIND_WILDCARD})
    return Candidate(
        key=key,
        kind=kind,
        members=tuple(sorted(members)),
        event_kind=collapsed_text(event_kind) or (kinds[0] if kinds else KIND_WILDCARD),
        stems=frozenset(row.stem for row in rows if row.stem),
        tokens=frozenset().union(*[row.tokens for row in rows]) if rows else frozenset(),
        places=frozenset().union(*[row.places for row in rows]) if rows else frozenset(),
        participants=(frozenset().union(*[row.participants for row in rows])
                      if rows else frozenset()),
        eras=frozenset().union(*[row.eras for row in rows]) if rows else frozenset(),
        documents=frozenset().union(*[row.documents for row in rows]) if rows else frozenset(),
        bounds=bounds,
        dated=any(row.dated for row in rows),
        episode_id=episode_id,
        adopted=adopted,
        authority=authority,
    )


def candidates(views: Mapping[str, TellingView], *, episode_records: object = ()) -> dict:
    """Every unit a telling could be about, keyed for a deterministic sweep.

    Existing episodes come from the ACTIVE bindings — never from an
    operation's ``members``, which §3.2 makes an audit copy — and each
    unbound, eligible telling is its own prospective unit.
    """
    records = ef.normalize_episode_records(episode_records)
    episodes = ef.episode_index(records["operations"], records["bindings"])
    active = efc.active_binding_index(records["bindings"])
    authority_of = {
        collapsed_text(row.get("episode_id")): collapsed_text(row.get("authority"))
        for row in sorted(records["operations"],
                          key=lambda row: collapsed_text(row.get("operation_id")))
        if collapsed_text(row.get("op")) == "create"
    }

    members: dict[str, list] = {}
    bound: set[str] = set()
    for telling_ref, rows in sorted(active.items()):
        binding = efc.grouping_binding(telling_ref, active)
        if binding is None:
            continue
        episode_id = collapsed_text(binding.get("episode_id"))
        if not episode_id:
            continue
        members.setdefault(episode_id, []).append(telling_ref)
        bound.add(telling_ref)

    units: dict[str, Candidate] = {}
    for episode_id, refs in sorted(members.items()):
        view = episodes.get(episode_id)
        units[episode_id] = _unit(
            episode_id, "episode", refs, views,
            event_kind=(view.canonical_event_kind if view else "") or "",
            episode_id=episode_id,
            adopted=bool(view.adopted) if view else False,
            authority=authority_of.get(episode_id, ""),
        )
    for telling_ref, row in sorted(views.items()):
        if telling_ref in bound or not row.eligible:
            continue
        units[telling_ref] = _unit(telling_ref, "prospective", [telling_ref], views)
    return units


def unit_of(telling_ref: str, units: Mapping[str, Candidate]) -> str:
    """Which unit a telling is currently part of, or ``""``."""
    for key in sorted(units):
        if telling_ref in units[key].members:
            return key
    return ""


# --------------------------------------------------------------------------
# §4.1 — the signals, and the score
# --------------------------------------------------------------------------


def _same_frame(left: object, right: object, frames: object) -> bool:
    """Both intervals inside ONE age frame — `cross_dating.frame_for`'s answer.

    Not "the same decade" computed here: age frames are the Timeline's
    permanent coordinate system and have exactly one definition (eras ADR
    0030). With no frames supplied the signal simply cannot fire, and the dry
    run reports how many frames it had, so a reader can tell "no frame" from
    "different frames".
    """
    if not frames or left is None or right is None:
        return False
    here = cross_dating.frame_for(frames, left)
    there = cross_dating.frame_for(frames, right)
    return bool(here) and here == there


def retrieval_signals(view: TellingView, candidate: Candidate,
                      *, frames: object = ()) -> tuple:
    """§4.1's blocking signals that this pair actually shares, in table order."""
    found: list[str] = []
    if view.participants & candidate.participants:
        found.append("participant")
    if view.places & candidate.places:
        found.append("place")
    if view.eras & candidate.eras:
        found.append("era")
    if view.bounds is not None and candidate.bounds is not None and \
            chrono.intersect(view.bounds, candidate.bounds) is not None and \
            _same_frame(view.bounds, candidate.bounds, frames):
        found.append("bounds_in_frame")
    if view.tokens & candidate.tokens:
        found.append("label_token")
    if view.documents & candidate.documents:
        found.append("source_document")
    return tuple(name for name in RETRIEVAL_SIGNALS if name in found)


def plausibility(signals: Sequence[str]) -> int:
    """§4.1's zero-model score: one point per independent signal. No weights,
    no learned threshold, no model — a number a person can recompute by hand
    from the dry run's own reason line."""
    return len(tuple(signals or ()))


def retrieve(view: TellingView, units: Mapping[str, Candidate],
             *, frames: object = ()) -> tuple:
    """``((candidate, signals), …)`` above the floor — the rest dropped SILENTLY.

    A dropped candidate produces no record, no question and no negative
    (§4.1). It is counted, because "how many did retrieval throw away" is a
    calibration number, and it is never named, because naming it would make
    absence into a decision.
    """
    found = []
    home = unit_of(view.telling_ref, units)
    for key in sorted(units):
        candidate = units[key]
        if key == home or view.telling_ref in candidate.members:
            continue
        signals = retrieval_signals(view, candidate, frames=frames)
        if plausibility(signals) < PLAUSIBILITY_FLOOR:
            continue
        found.append((candidate, signals))
    found.sort(key=lambda row: (-plausibility(row[1]), row[0].key))
    return tuple(found)


# --------------------------------------------------------------------------
# §4.2 — the seven conditions
# --------------------------------------------------------------------------


def independent_of_the_label(view: TellingView, candidate: Candidate) -> frozenset:
    """The shared participants that are not simply the label said again.

    On a recorder telling the subject IS the thing — `Boeing`, started, 1998 —
    so "Boeing" is at once the label and the only `participant`. Counting it as
    condition 4 evidence beside a label match would let ONE fact satisfy two
    signals the condition calls independent, which is the exact failure the
    word "independent" is in the sentence to prevent. Observed live: nine
    recorder pairs on the founder's vault reported `1 of 2: participant` where
    the participant and the matched stem were the same token.
    """
    shared = view.participants & candidate.participants
    label_tokens_here = set(view.stem.split(STEM_JOIN)) | {
        token for stem in candidate.stems for token in stem.split(STEM_JOIN)
    }
    return frozenset(
        value for value in shared
        if not set(value.split()) <= label_tokens_here
    )


def independent_signals(view: TellingView, candidate: Candidate) -> tuple:
    """§4.2 condition 4's agreements — never the label, never the owner.

    ``bounds`` counts only when BOTH sides are dated, which is the condition's
    own wording: two undated tellings agreeing that neither knows when is not
    evidence that they are the same thing. And a shared participant that is
    just the label again is not a second signal
    (:func:`independent_of_the_label`).
    """
    found: list[str] = []
    if view.documents & candidate.documents:
        found.append("source_document")
    if view.places & candidate.places:
        found.append("place")
    if independent_of_the_label(view, candidate):
        found.append("participant")
    if view.dated and candidate.dated and view.bounds is not None and \
            candidate.bounds is not None and \
            chrono.intersect(view.bounds, candidate.bounds) is not None:
        found.append("bounds")
    return tuple(name for name in INDEPENDENT_SIGNALS if name in found)


def _not_same_blocked(view: TellingView, candidate: Candidate,
                      active: Mapping[str, tuple], entailed: Sequence[tuple]) -> bool:
    """§4.2 condition 6 — an ACTIVE or an ENTAILED negative, both.

    Entailment is C3's (`entailed_not_same`) and is recomputed here rather
    than stored, for its reason: a negative that outlives its premise is a
    phantom the person can never clear.
    """
    for row in active.get(view.telling_ref) or ():
        if collapsed_text(row.get("relation")) != "not_same":
            continue
        if collapsed_text(row.get("episode_id")) == candidate.episode_id:
            return True
    pairs = {tuple(sorted(pair)) for pair in entailed or ()}
    for member in candidate.members:
        if tuple(sorted((view.telling_ref, member))) in pairs:
            return True
    return False


def r1_conditions(view: TellingView, candidate: Candidate, *, survivors: int = 1,
                  active: Mapping[str, tuple] | None = None,
                  entailed: Sequence[tuple] = ()) -> tuple:
    """§4.2's seven, evaluated in §4.2's order, each with its own reason.

    Condition 5 is handed in as ``survivors`` because it is the only one that
    is not a property of the pair — it is a property of the whole retrieval,
    and computing it inside a pair would either be wrong or would make this
    function quadratic.
    """
    active = dict(active or {})
    stems = candidate.stems
    independent = independent_signals(view, candidate)
    joining_two_mature = candidate.mature and _home_is_mature(view, active)
    blocked = _not_same_blocked(view, candidate, active, entailed)
    rows = [
        Condition(
            "kind_family",
            kinds_compatible(view.event_kind, candidate.event_kind),
            f"{view.event_kind or '—'} vs {candidate.event_kind or '—'}: "
            + (", ".join(sorted(kind_families(view.event_kind)
                                & kind_families(candidate.event_kind))) or "no shared family"),
        ),
        Condition(
            "repeatable_protection",
            not is_repeatable(candidate.event_kind) or view.dated,
            f"{candidate.event_kind} is repeatable and this telling is undated"
            if is_repeatable(candidate.event_kind) and not view.dated
            else ("not a repeatable kind" if not is_repeatable(candidate.event_kind)
                  else "repeatable, and the telling carries its own date"),
        ),
        Condition(
            "label_stems_match",
            bool(view.stem) and view.stem in stems,
            f"{view.stem or '—'} vs {sorted(stems) or '—'}",
        ),
        Condition(
            "two_independent_signals",
            len(independent) >= REQUIRED_INDEPENDENT_SIGNALS,
            f"{len(independent)} of {REQUIRED_INDEPENDENT_SIGNALS}: "
            + (", ".join(independent) or "none"),
        ),
        Condition(
            # §4.2 condition 5 is "exactly one survives", and its FAILURE mode
            # is two. Zero survivors is not ambiguity — it is conditions 1-4
            # having already refused — so the condition is vacuous below two
            # and the count printed is the real one, never a coerced 1.
            "one_surviving_candidate",
            survivors <= 1,
            f"{survivors} candidate(s) survive conditions 1-4",
        ),
        Condition(
            "no_not_same",
            not blocked,
            "an active or entailed not_same stands between them" if blocked
            else "no negative on this pair",
        ),
        Condition(
            "not_joining_two_mature_episodes",
            not joining_two_mature,
            "both sides already hold two or more tellings; that is a merge"
            if joining_two_mature else "at most one side is mature",
        ),
    ]
    ordered = {row.name: row for row in rows}
    return tuple(ordered[name] for name in R1_CONDITIONS)


def _home_is_mature(view: TellingView, active: Mapping[str, tuple]) -> bool:
    """Is the telling itself already inside an episode of two or more?"""
    binding = efc.grouping_binding(view.telling_ref, active)
    if binding is None:
        return False
    episode_id = collapsed_text(binding.get("episode_id"))
    count = 0
    for telling_ref in active:
        row = efc.grouping_binding(telling_ref, active)
        if row is not None and collapsed_text(row.get("episode_id")) == episode_id:
            count += 1
    return count >= MATURE_EPISODE_MEMBERS


# --------------------------------------------------------------------------
# §4.2 — the decision
# --------------------------------------------------------------------------

#: Verdicts from most conservative to least. When the two directions of one
#: pair disagree, the pair takes the FIRST of these either direction reached:
#: a refusal in either direction is a refusal of the pair, because R1's whole
#: posture is that a miss is cheap and a wrong link is not.
VERDICT_PRECEDENCE = ("blocked", "ambiguous", "asked", "proposal", "part_of", "bind")

#: §6.1 keys a work item on `(telling_ref, candidate_episode_id)`, which is
#: directional by construction — so a pair that was evaluated twice has to pick
#: ONE direction or it mints two items for one question. The rule, in order:
#: a telling measured against an EXISTING episode is always the canonical
#: direction (the reverse names a prospective episode built from one member
#: and the telling — a different string for the same question, and a worse
#: framing of it); otherwise the direction whose telling ref sorts first. C4's
#: key is untouched; this only says which direction is handed to it.
CANONICAL_DIRECTION_RULE = (
    "one pair, one item: a telling against an existing episode is the "
    "canonical direction; between two prospective units the lower telling ref "
    "wins. Both directions are still EVALUATED — four of R1's conditions are "
    "asymmetric — and the surviving row carries what either direction refused."
)

#: Why a verdict was reached, one sentence each, so a dry-run line reads as
#: prose rather than as a set of flags.
VERDICT_REASONS = {
    "bind": "every condition holds; R1 binds `same`",
    "part_of": "the telling says it happened inside this one, in its own words",
    "proposal": "the label matches but R1's floor does not; the person is asked",
    "ambiguous": "two candidates survive; no bind, and one question names both",
    "asked": "R1 declines and the pair is plausible enough to be worth asking",
    "blocked": "the person already said these are different things",
}


def _growable(candidate: Candidate) -> bool:
    """May a deterministic rule GROW this unit (see :data:`CLUSTER_RULE_TEXT`)?

    A prospective unit always. An existing episode only when it is neither
    adopted nor human authority: G1 says a deterministic rule may file
    proposals against what a person acted on and may never move it.
    """
    if candidate.kind == "prospective":
        return True
    return not candidate.adopted and candidate.authority != "human"


def says_it_is_inside(view: TellingView, candidate: Candidate) -> bool:
    """Does the telling's OWN language put it inside this candidate?

    Two clauses, both narrowing:

    * the container's name the telling actually used must be a SUBSET of the
      candidate's tokens, not merely intersect them — "during Etherfuse"
      names Etherfuse and nothing else, and an intersection would let any
      candidate that happened to share one word claim the containment;
    * the candidate must be an EPISODE that already exists. A prospective
      unit is not a thing to be inside yet, and proposing "this happened
      during that" about two tellings neither of which has been decided is
      two decisions wearing one record.
    """
    return (candidate.kind == "episode"
            and bool(view.containment)
            and view.containment <= candidate.tokens)


def verdict_for(view: TellingView, candidate: Candidate, conditions: Sequence[Condition]) -> str:
    """One of :data:`VERDICTS`, from §4.2's own conditions in §4.2's own order."""
    failed = {row.name for row in conditions if not row.passed}
    if "no_not_same" in failed:
        return "blocked"
    if "kind_family" in failed:
        return "asked"
    if says_it_is_inside(view, candidate):
        return "part_of"
    if "label_stems_match" in failed:
        return "asked"
    if "one_surviving_candidate" in failed:
        return "ambiguous"
    if failed:
        return "proposal"
    return "bind" if _growable(candidate) else "proposal"


def _pairs_for(view: TellingView, units: Mapping[str, Candidate], *, frames: object,
               active: Mapping[str, tuple], entailed: Sequence[tuple]) -> list:
    """Every pair one telling produces, with §4.2 evaluated twice.

    Twice on purpose: conditions 1-4 decide who SURVIVES, and condition 5 is a
    fact about the survivors — so the first pass counts them and the second
    pass records the seven conditions each pair actually met.
    """
    retrieved = retrieve(view, units, frames=frames)
    home = unit_of(view.telling_ref, units)
    survivors = 0
    for candidate, signals in retrieved:
        rows = r1_conditions(view, candidate, survivors=1,
                             active=active, entailed=entailed)
        if all(row.passed for row in rows[:4]):
            survivors += 1
    found = []
    for candidate, signals in retrieved:
        rows = r1_conditions(view, candidate, survivors=survivors,
                             active=active, entailed=entailed)
        pair = Pair(
            telling_ref=view.telling_ref,
            home_key=home or view.telling_ref,
            candidate_key=candidate.key,
            candidate_episode_id=(candidate.episode_id or
                                  prospective_episode_id(
                                      sorted({view.telling_ref, *candidate.members}))),
            candidate_kind=candidate.kind,
            signals=tuple(signals),
            plausibility=plausibility(signals),
            conditions=rows,
        )
        pair.verdict = verdict_for(view, candidate, rows)
        pair.relation_hint = "part_of" if pair.verdict == "part_of" else efc.GROUPING_RELATION
        pair.part_of_suggestive = _time_decayed(view, candidate)
        pair.reason = VERDICT_REASONS[pair.verdict]
        found.append(pair)
    return found


def canonical_direction(rows: Sequence[Pair], units: Mapping[str, Candidate]) -> Pair:
    """Which of a pair's two rows is THE row (:data:`CANONICAL_DIRECTION_RULE`)."""
    against_episode = [
        row for row in rows
        if (units.get(row.candidate_key).kind if row.candidate_key in units else "")
        == "episode"
    ]
    pool = against_episode or list(rows)
    return sorted(pool, key=lambda row: (row.telling_ref, row.candidate_key))[0]


def collapse_directions(rows: Sequence[Pair], units: Mapping[str, Candidate]) -> list:
    """Two rows per pair in, ONE row per pair out.

    The surviving row keeps its own conditions — they are the ones the
    canonical question was actually judged on — and gains the other
    direction's refusals in ``also_failed``, so nothing a direction found is
    lost. The verdict is the more conservative of the two
    (:data:`VERDICT_PRECEDENCE`), except that a `part_of` reading is
    directional by nature and is never overwritten by the artifact direction's
    opinion of it.
    """
    grouped: dict[tuple, list] = {}
    for row in rows:
        grouped.setdefault(row.units, []).append(row)
    collapsed = []
    for key in sorted(grouped):
        found = grouped[key]
        chosen = canonical_direction(found, units)
        others = [row for row in found if row is not chosen]
        # A COPY. The directional rows are the record of what each direction
        # judged, and a collapse that rewrote one of them in place would erase
        # the asymmetry it exists to summarize — the reading `direction_of`
        # needs and the reading the person is shown are two different rows.
        winner = replace(chosen)
        if winner.verdict != "part_of":
            verdicts = {row.verdict for row in found}
            for name in VERDICT_PRECEDENCE:
                if name in verdicts:
                    if name != winner.verdict:
                        winner.verdict = name
                        winner.reason = VERDICT_REASONS[name]
                    break
        winner.also_failed = tuple(sorted({
            name for row in others for name in row.failed()
        } - set(winner.failed())))
        winner.part_of_suggestive = any(row.part_of_suggestive for row in found)
        collapsed.append(winner)
    return collapsed


def _time_decayed(view: TellingView, candidate: Candidate) -> bool:
    """§4.5's time-decay: a wide-gap place mismatch is `part_of`-suggestive.

    NOT a veto — that is the whole point. Two dated tellings more than
    :data:`TIME_DECAY_GAP_YEARS` apart that name different places are exactly
    what a relocation inside one long episode looks like, so the pair is
    flagged for the question rather than struck from it.
    """
    if not (view.dated and candidate.dated):
        return False
    if not view.places or not candidate.places or (view.places & candidate.places):
        return False
    here, there = view.bounds, candidate.bounds
    if here is None or there is None:
        return False
    years = []
    for record in (here, there):
        for value in (record.earliest, record.latest, record.best):
            text = collapsed_text(value)
            if text[:4].isdigit():
                years.append(int(text[:4]))
                break
    return len(years) == 2 and abs(years[0] - years[1]) >= TIME_DECAY_GAP_YEARS


# --------------------------------------------------------------------------
# §4.5 — the safeguards that ship WITH R1
# --------------------------------------------------------------------------

#: The reason line an over-merge row carries, so the item explains itself
#: without the reader holding the design open.
OVERMERGE_DISJOINT_REASON = (
    "these tellings are inside one episode and the dates they state cannot "
    "both be true of one event"
)


def disjoint_bounds_item_id(*, episode_id: object, telling_refs: Sequence[object]) -> str:
    """The id of §4.5's disjoint-bounds item.

    C4's `possible_overmerge_id` keys the ARRIVAL-AMBIGUITY item and needs two
    episodes; §4.5's item is about ONE episode whose own members disagree, so
    it has no second episode to key on and gets its own minter in the same
    kind. Two mint sites, both named, neither guessing at the other's key.
    """
    return digest_id(POSSIBLE_OVERMERGE_KIND, {
        "episode_id": collapsed_text(episode_id),
        "telling_refs": sorted({collapsed_text(ref) for ref in telling_refs or ()} - {""}),
        "rule_version": RULE_VERSION,
    })


def overmerge_audit(views: Mapping[str, TellingView], units: Mapping[str, Candidate]) -> list:
    """§4.5: `same` members whose STATED outer bounds are disjoint.

    One item per episode, never a split: an automatic split is the mirror
    image of the automatic merge this whole design refuses, and it would throw
    away the person's own dates to make the system's grouping look tidy.
    """
    found = []
    for key in sorted(units):
        candidate = units[key]
        if candidate.kind != "episode" or len(candidate.members) < MATURE_EPISODE_MEMBERS:
            continue
        dated = [(ref, views[ref].bounds) for ref in candidate.members
                 if ref in views and views[ref].dated and views[ref].bounds is not None]
        if len(dated) < MATURE_EPISODE_MEMBERS:
            continue
        if chrono.intersect(*[record for _ref, record in dated]) is not None:
            continue
        refs = sorted(ref for ref, _record in dated)
        found.append({
            "kind": POSSIBLE_OVERMERGE_KIND,
            "item_id": disjoint_bounds_item_id(episode_id=candidate.episode_id,
                                               telling_refs=refs),
            "episode_id": candidate.episode_id,
            "telling_refs": refs,
            "finding": "disjoint_stated_bounds",
            "reason": OVERMERGE_DISJOINT_REASON,
            "identity_rule_version": RULE_VERSION,
        })
    return found


def bridge_diagnostics(episode_records: object = ()) -> list:
    """§4.5's articulation diagnostic, computed over the OPERATION graph.

    Every active operation is a clique over the tellings it names. An
    operation is a BRIDGE when removing its clique leaves the episode's
    members in two or more components — *"this one receipt is the only thing
    holding these two halves together"*.

    An episode joined by exactly ONE receipt is reported as ``sole_receipt``
    rather than as a bridge. The statement is true there too and says
    nothing: of course the only receipt is holding it together. A diagnostic
    that fires on every episode is a diagnostic nobody reads.
    """
    records = ef.normalize_episode_records(episode_records)
    operations = [row for row in records["operations"]
                  if collapsed_text(row.get("status") or "active") == "active"]
    active = efc.active_binding_index(records["bindings"])
    members: dict[str, set] = {}
    for telling_ref in sorted(active):
        binding = efc.grouping_binding(telling_ref, active)
        if binding is not None:
            members.setdefault(collapsed_text(binding.get("episode_id")), set()).add(telling_ref)

    by_episode: dict[str, list] = {}
    for row in sorted(operations, key=lambda row: collapsed_text(row.get("operation_id"))):
        episode_id = collapsed_text(row.get("episode_id"))
        if episode_id in members and row.get("members"):
            by_episode.setdefault(episode_id, []).append(row)

    found = []
    for episode_id in sorted(members):
        rows = by_episode.get(episode_id) or []
        present = members[episode_id]
        if len(present) < MATURE_EPISODE_MEMBERS:
            continue
        if len(rows) < 2:
            found.append({
                "episode_id": episode_id, "finding": "sole_receipt",
                "operation_id": collapsed_text(rows[0].get("operation_id")) if rows else "",
                "members": sorted(present),
            })
            continue
        for row in rows:
            others = [other for other in rows if other is not row]
            if len(_components(present, others)) > 1:
                found.append({
                    "episode_id": episode_id, "finding": "bridge",
                    "operation_id": collapsed_text(row.get("operation_id")),
                    "members": sorted(present),
                })
    return found


def _components(members: set, operations: Sequence[Mapping]) -> list:
    """Connected components of the members under the operations' cliques."""
    parent = {ref: ref for ref in members}

    def find(ref: str) -> str:
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    for row in operations:
        named = [ref for ref in (row.get("members") or ()) if ref in parent]
        for ref in named[1:]:
            a, b = find(named[0]), find(ref)
            if a != b:
                parent[a] = b
    groups: dict[str, list] = {}
    for ref in sorted(members):
        groups.setdefault(find(ref), []).append(ref)
    return [sorted(rows) for _key, rows in sorted(groups.items())]


def reaudit_findings(units: Mapping[str, Candidate],
                     pairs: Sequence[Pair], *, trigger: str = "maintenance_sweep",
                     episode_records: object = (), answered_pairs: Sequence = (),
                     open_items: Sequence = ()) -> list:
    """§5.6's re-audit, one row per already-bound telling with a NEW candidate.

    Every action comes out of C4's `reaudit`, which returns
    :data:`episode_routing_contract.REAUDIT_MINT` or
    :data:`episode_routing_contract.REAUDIT_NO_ACTION` and can return nothing
    else — so a re-audit structurally cannot move, split, keep or re-confirm a
    bind. This function's whole job is finding the pairs to hand it.
    """
    records = ef.normalize_episode_records(episode_records)
    active = efc.active_binding_index(records["bindings"])
    found = []
    for pair in sorted(pairs, key=lambda row: (row.telling_ref, row.candidate_episode_id)):
        binding = efc.grouping_binding(pair.telling_ref, active)
        if binding is None:
            continue
        if collapsed_text(binding.get("origin")) != "deterministic":
            continue
        bound = collapsed_text(binding.get("episode_id"))
        candidate = units.get(pair.candidate_key)
        if candidate is None or not candidate.episode_id or candidate.episode_id == bound:
            continue
        found.append(erc.reaudit(
            trigger=trigger, telling_ref=pair.telling_ref, bound_episode_id=bound,
            candidate_episode_id=candidate.episode_id, bindings=active,
            answered_pairs=answered_pairs, open_items=open_items,
        ))
    return found


# --------------------------------------------------------------------------
# The envelope one accepted pair becomes
# --------------------------------------------------------------------------


def _members_of(view: TellingView, candidate: Candidate,
                active: Mapping[str, tuple]) -> tuple:
    home = efc.grouping_binding(view.telling_ref, active)
    mine = {view.telling_ref}
    if home is not None:
        episode_id = collapsed_text(home.get("episode_id"))
        for telling_ref in active:
            row = efc.grouping_binding(telling_ref, active)
            if row is not None and collapsed_text(row.get("episode_id")) == episode_id:
                mine.add(telling_ref)
    return tuple(sorted(mine | set(candidate.members)))


def create_envelope(view: TellingView, candidate: Candidate, *, pair: Pair,
                    active: Mapping[str, tuple], views: Mapping[str, TellingView],
                    now: object = None) -> dict:
    """The `create` envelope one accepted pair becomes (:data:`CLUSTER_RULE_TEXT`).

    The operation id digests the MEMBER SET and nothing else — no invocation
    id, no clock, and deliberately no ``acted_on_episode_ids``, because a
    create whose id depended on what happened to exist when it ran could not
    survive the deletion of that state (G1). Every superseded episode is named
    in ``aliases_created``, so no id this run retires is ever orphaned.
    """
    members = _members_of(view, candidate, active)
    operation_id = ei.operation_digest(
        authority="deterministic", op="create", rule_version=RULE_VERSION,
        member_refs=members,
    )
    episode_id = ei.episode_id_for(operation_id)
    superseded: dict[str, str] = {}
    aliases: set[str] = set()
    for telling_ref in members:
        row = efc.grouping_binding(telling_ref, active)
        if row is None:
            continue
        previous = collapsed_text(row.get("episode_id"))
        if previous and previous != episode_id:
            superseded[telling_ref] = collapsed_text(row.get("identity_id"))
            aliases.add(previous)

    bindings = []
    for telling_ref in members:
        row = views.get(telling_ref)
        bindings.append({
            "telling_ref": telling_ref,
            "episode_id": episode_id,
            "relation": efc.GROUPING_RELATION,
            "origin": "deterministic",
            "rule_version": RULE_VERSION,
            "rule_id": RULE_ID,
            "operation_id": operation_id,
            "candidates": [pair.candidate_episode_id],
            "evidence": {
                "telling_quote": row.label if row else "",
                "episode_quote": views[candidate.members[0]].label
                if candidate.members and candidate.members[0] in views else "",
                "signals": list(pair.signals),
            },
            "created_at": now,
        })
    binding_ids = [ei.validate_event_identity(row)["identity_id"] for row in bindings]
    for index, telling_ref in enumerate(members):
        if telling_ref in superseded:
            bindings[index]["supersedes"] = superseded[telling_ref]
            binding_ids[index] = ei.validate_event_identity(bindings[index])["identity_id"]
    operation = {
        "authority": "deterministic",
        "op": "create",
        "episode_id": episode_id,
        "members": list(members),
        "creates_binding_ids": binding_ids,
        "supersedes_binding_ids": sorted(superseded.values()),
        "aliases_created": sorted(aliases),
        "canonical_event_kind": _canonical_kind(members, views, candidate),
        "rule_version": RULE_VERSION,
        "created_at": now,
    }
    return {
        "operation": ei.validate_episode_operation(operation),
        "bindings": [ei.validate_event_identity(row) for row in bindings],
        "pair": pair.event_key,
    }


#: §3.2: the canonical kind is the DATED telling's kind, else a fixed
#: precedence — never "whichever claim arrived first". The precedence is the
#: family table's own order, so it is one table rather than two.
KIND_PRECEDENCE = tuple(kind for _name, members in KIND_FAMILIES for kind in members)


def _canonical_kind(members: Sequence[str], views: Mapping[str, TellingView],
                    candidate: Candidate) -> str:
    if candidate.kind == "episode" and candidate.event_kind:
        return candidate.event_kind
    dated = sorted(ref for ref in members
                   if ref in views and views[ref].dated and views[ref].event_kind)
    for ref in dated:
        if views[ref].event_kind != KIND_WILDCARD:
            return views[ref].event_kind
    kinds = {views[ref].event_kind for ref in members if ref in views} - {""}
    for kind in KIND_PRECEDENCE:
        if kind in kinds:
            return kind
    return min(kinds) if kinds else KIND_WILDCARD


def part_of_proposal(view: TellingView, candidate: Candidate, *, pair: Pair,
                     now: object = None) -> dict:
    """The record explicit containment language mints — a `proposed` `part_of`.

    §4.2 wants deterministic `part_of` here. C2's validator refuses it:
    `identity_deterministic_relation_unsupported` pins the narrow reading that
    a ``deterministic`` origin binds ``same`` and nothing else. Rather than
    widen a frozen contract from a later phase, the containment lands as a
    ``proposed`` record — which by §2.3 changes no drawing, renders as this
    node's ``proposed_links`` and ranks the question — and the pair is asked.
    Named in the PR body as a design item that could not be honored as
    written.
    """
    return ei.validate_event_identity({
        "telling_ref": view.telling_ref,
        "episode_id": pair.candidate_episode_id,
        "relation": "part_of",
        "origin": "proposed",
        "rule_version": RULE_VERSION,
        "rule_id": f"{RULE_ID}-containment",
        "candidates": [pair.candidate_episode_id],
        "evidence": {
            "telling_quote": view.label,
            "episode_quote": ", ".join(sorted(candidate.tokens & view.containment)),
            "signals": list(pair.signals),
        },
        "created_at": now,
    })


# --------------------------------------------------------------------------
# §6.1 — the question rows, and the caps
# --------------------------------------------------------------------------


def question_row(pair: Pair, view: TellingView, candidate: Candidate) -> dict:
    """One `same_event` pair, as DATA. No probe text, no answers, no state.

    ``score_inputs`` is what §4.1 says feeds the EXISTING work-item value
    scoring — *"identity pairs enter the existing value scoring like every
    other kind; the kind never outranks keystones by fiat"* — so the binder
    supplies the inputs and computes no priority of its own.
    """
    return {
        "kind": SAME_EVENT_KIND,
        "event_key": pair.event_key,
        "telling_ref": pair.telling_ref,
        # BOTH sides. §6.1's "one pair per telling at a time" is a promise
        # about a telling's workload, and after the two directions collapse a
        # telling appears as `telling_ref` on only some of the pairs it is
        # actually in — so the cap counts the pair against every unit in it.
        "units": list(pair.units),
        "candidate_episode_id": pair.candidate_episode_id,
        "candidate_kind": pair.candidate_kind,
        "candidate_members": list(candidate.members),
        "relation_hint": pair.relation_hint,
        "part_of_suggestive": pair.part_of_suggestive,
        "verdict": pair.verdict,
        "failed_conditions": list(pair.failed()),
        "signals": list(pair.signals),
        "surfaced": pair.surfaced,
        "identity_rule_version": RULE_VERSION,
        "score_inputs": {
            "plausibility": pair.plausibility,
            "label_match": "label_stems_match" not in pair.failed(),
            "candidate_is_dated": candidate.dated,
            "telling_recency": view.created_at,
            "candidate_member_count": len(candidate.members),
        },
        "quotes": {
            "telling_quote": view.label,
            "episode_quote": ", ".join(sorted(candidate.stems)) or "",
        },
    }


def apply_caps(rows: Sequence[dict], *, cap: int = GLOBAL_QUESTION_CAP) -> list:
    """§6.1's caps, applied to the ROWS and never to the decisions.

    At most :data:`SURFACED_PAIRS_PER_TELLING` per telling and at most ``cap``
    overall carry ``surfaced: true``. Nothing is DROPPED — a pair below the
    cap is still emitted, still keyed, still answerable when its turn comes —
    because dropping it would make the cap a silent decision about which of a
    person's questions exist.
    """
    _require(isinstance(cap, int) and cap >= 0, "binder_cap_out_of_range",
             f"the open-question cap is a non-negative integer; got {cap!r}")
    ordered = sorted(
        rows,
        key=lambda row: (
            -int(row["score_inputs"]["plausibility"]),
            not row["score_inputs"]["label_match"],
            not row["score_inputs"]["candidate_is_dated"],
            row["event_key"],
        ),
    )
    per_unit: dict[str, int] = {}
    surfaced = 0
    for row in ordered:
        sides = list(row.get("units") or [row["telling_ref"]])
        room = all(per_unit.get(side, 0) < SURFACED_PAIRS_PER_TELLING for side in sides)
        row["surfaced"] = bool(room and surfaced < cap)
        if row["surfaced"]:
            for side in sides:
                per_unit[side] = per_unit.get(side, 0) + 1
            surfaced += 1
    return sorted(ordered, key=lambda row: row["event_key"])


# --------------------------------------------------------------------------
# Event identity I3 — question rows and audit rows become WORK ITEMS
# --------------------------------------------------------------------------
#
# §4.1's own ruling: identity pairs enter the EXISTING work-item value
# scoring like every other kind, never a priority of their own. Both
# functions below are pure — a `BinderPlan` in, `TemporalWorkItem` dicts out
# — and neither writes anything; wiring the result into the published
# `work-items.json` generation is a maintenance-step / platform concern
# (I-P), exactly as R1's own decisions are filed by `apply_plan`, not by
# `plan` itself.


def _same_event_prompt(quotes: Mapping[str, object]) -> str:
    telling_quote = collapsed_text(quotes.get("telling_quote"))
    episode_quote = collapsed_text(quotes.get("episode_quote"))
    if not telling_quote or not episode_quote:
        return ""
    return f"Is “{telling_quote}” the same thing as “{episode_quote}”?"


def same_event_work_item(row: Mapping[str, object], *, now: object = None) -> dict | None:
    """One `question_row` (§6.1), minted as an ordinary `same_event` item.

    Returns ``None`` for a row this phase's value validator refuses (an
    empty pair key, most concretely) rather than raising — a generation pass
    over many pairs should not die on one malformed row, the same
    `question_withheld`-shaped tolerance `_mint_work_item` extends to a
    template that failed to render.
    """
    inputs = row.get("score_inputs") or {}
    reach = min(1.0, float(inputs.get("plausibility") or 0) / len(RETRIEVAL_SIGNALS))
    scores = tt.work_item_score(SAME_EVENT_KIND, system_value=reach)
    quotes = row.get("quotes") or {}
    payload = {
        "kind": SAME_EVENT_KIND,
        "event_ref": row.get("event_key"),
        "allowed_surfaces": list(tt.work_item_surfaces(SAME_EVENT_KIND)),
        "score_rule": tt.SCORE_FORMULA_VERSION,
        "prompt_intent": _same_event_prompt(quotes) or None,
    }
    payload.update(scores)
    try:
        item = tp.validate_temporal_work_item(payload, now=now)
    except TemporalContractError:
        return None
    # Additive, non-identity rendering fields (design §6.1's "quotes") — read
    # by `timeline_interaction.work_item_probe` as a bare work item's own
    # optional keys, never part of `WORK_ITEM_IDENTITY_KEYS`.
    item["telling_quote"] = collapsed_text(quotes.get("telling_quote"))
    item["episode_quote"] = collapsed_text(quotes.get("episode_quote"))
    return item


def same_event_work_items(result: BinderPlan, *, now: object = None) -> list[dict]:
    """Every SURFACED `same_event` pair in ``plan.questions``, as work items.

    Only ``surfaced`` rows become items — §6.1's per-telling and global caps
    (already applied by :func:`apply_caps`) are what "surfaced" means; the
    rest stay in ``plan.questions`` as data nobody is asked about yet, and
    reappear here the moment a `Different` answer frees the next candidate
    (§13.3: *at most one pair per telling is surfaced at a time*).
    """
    items = []
    for row in result.questions:
        if not row.get("surfaced"):
            continue
        item = same_event_work_item(row, now=now)
        if item is not None:
            items.append(item)
    return items


def _possible_overmerge_item(
    *, item_id: object, reason: object, telling_quote: object = None,
    episode_quote: object = None, now: object = None,
) -> dict | None:
    scores = tt.work_item_score(POSSIBLE_OVERMERGE_KIND, system_value=0.6)
    payload = {
        "kind": POSSIBLE_OVERMERGE_KIND,
        "event_ref": item_id,
        "allowed_surfaces": list(tt.work_item_surfaces(POSSIBLE_OVERMERGE_KIND)),
        "score_rule": tt.SCORE_FORMULA_VERSION,
        "prompt_intent": collapsed_text(reason) or None,
    }
    payload.update(scores)
    try:
        item = tp.validate_temporal_work_item(payload, now=now)
    except TemporalContractError:
        return None
    item["telling_quote"] = collapsed_text(telling_quote)
    item["episode_quote"] = collapsed_text(episode_quote)
    return item


def possible_overmerge_work_items(result: BinderPlan, *, now: object = None) -> list[dict]:
    """`plan.overmerges` (§4.5) and `plan.reaudits`' mints (§5.6), as items.

    Both producers already mint a stable, canonical identity —
    :func:`disjoint_bounds_item_id` for a mature episode's own disjoint
    bounds, :func:`episode_routing_contract.possible_overmerge_id` for a
    re-audit's existing-bind-vs-new-candidate pair — so this only carries
    that id into `derive_work_item_id`'s ``event_ref`` and runs the SAME
    value-scoring formula every other kind uses. A `no_action` re-audit row
    mints nothing: :data:`FORBIDDEN_REAUDIT_ACTIONS` names why there is
    nothing else it could do.
    """
    items = []
    for row in result.overmerges:
        item = _possible_overmerge_item(
            item_id=row.get("item_id"), reason=row.get("reason"), now=now,
        )
        if item is not None:
            items.append(item)
    for row in result.reaudits:
        if row.get("action") != erc.REAUDIT_MINT:
            continue
        item = _possible_overmerge_item(
            item_id=row.get("item_id"), reason=row.get("reason"), now=now,
        )
        if item is not None:
            items.append(item)
    return items


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

#: Why an accepted bind can still be demoted. Law 3: *no transitive merge* —
#: every membership is individually attributable, union-find may PROPOSE and
#: never apply. Two tellings joining one unit in a single run would be a
#: three-member group nobody decided pairwise, so both become proposals.
NON_TRANSITIVE_RULE_TEXT = (
    "R1 decides one PAIR at a time. A bind is accepted only when both sides "
    "chose each other and no third telling chose the same unit in the same "
    "run; anything else is a proposal, because a group formed by transitivity "
    "is a membership nobody decided."
)


def plan(claims: object, *, episode_records: object = (), frames: object = (),
         era_memberships: object = None, manifest: object = None,
         question_cap: int = GLOBAL_QUESTION_CAP, trigger: str = "maintenance_sweep",
         answered_pairs: Sequence = (), open_items: Sequence = (),
         now: object = None) -> BinderPlan:
    """One binder run, decided and not written. Pure.

    Deterministic end to end: tellings are swept in sorted order, candidates
    in sorted order, and every id in the result is a digest over semantic
    inputs. Run it twice on the same inputs and the two plans are equal.
    """
    views = telling_views(claims, manifest=manifest, era_memberships=era_memberships)
    units = candidates(views, episode_records=episode_records)
    records = ef.normalize_episode_records(episode_records)
    active = efc.active_binding_index(records["bindings"])
    entailed = efc.entailed_not_same(records["bindings"])

    result = BinderPlan(views=views)
    dropped = 0
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible:
            continue
        found = _pairs_for(view, units, frames=frames, active=active, entailed=entailed)
        home = unit_of(telling_ref, units)
        considered = sum(1 for key in units
                         if key != home and telling_ref not in units[key].members)
        dropped += considered - len(found)
        result.directional.extend(found)
    result.dropped = dropped

    # --- a telling is inside at most ONE episode ---------------------------
    # I1's own rule, applied one layer up: two containing episodes are NO pick
    # at all. Filing both would also be `identity_conflict` on the next read,
    # since `part_of` is a grouping relation — so the ambiguity is a question.
    containers: dict[str, list] = {}
    for pair in result.directional:
        if pair.verdict == "part_of":
            containers.setdefault(pair.telling_ref, []).append(pair)
    for telling_ref, rows in sorted(containers.items()):
        if len(rows) < 2:
            continue
        for pair in rows:
            pair.verdict = "asked"
            pair.relation_hint = "part_of"
            pair.reason = ("two candidate containers; an ambiguity is a question, "
                           "never a pick")

    # --- accept the binds that are mutual and vertex-disjoint --------------
    chosen: dict[str, str] = {}
    for pair in result.directional:
        if pair.verdict == "bind":
            chosen[pair.telling_ref] = pair.candidate_key
    claimed: dict[str, list] = {}
    for telling_ref, key in sorted(chosen.items()):
        claimed.setdefault(key, []).append(telling_ref)
    accepted: set[tuple] = set()
    for pair in result.directional:
        if pair.verdict != "bind":
            continue
        candidate = units[pair.candidate_key]
        contested = len(claimed.get(pair.candidate_key, ())) > 1
        mutual = True
        if candidate.kind == "prospective":
            other = candidate.members[0]
            mutual = chosen.get(other) == unit_of(pair.telling_ref, units)
        if contested or not mutual:
            pair.verdict = "proposal"
            pair.reason = (VERDICT_REASONS["proposal"] + "; " + NON_TRANSITIVE_RULE_TEXT
                           if contested else
                           VERDICT_REASONS["proposal"] + "; the other side did not choose back")
            continue
        accepted.add(tuple(sorted({pair.telling_ref, *candidate.members})))

    seen: set[tuple] = set()
    for pair in sorted(result.directional, key=lambda row: (row.telling_ref, row.candidate_key)):
        if pair.verdict != "bind":
            continue
        members = tuple(sorted({pair.telling_ref, *units[pair.candidate_key].members}))
        if members not in accepted or members in seen:
            continue
        seen.add(members)
        result.envelopes.append(create_envelope(
            views[pair.telling_ref], units[pair.candidate_key], pair=pair,
            active=active, views=views, now=now,
        ))

    # --- ONE row per pair, from here on ------------------------------------
    # Everything above needed both directions; nothing below does. A question
    # surface that showed the same pair twice would be counting its own
    # bookkeeping as the person's workload.
    result.pairs = collapse_directions(result.directional, units)

    # --- proposals, questions, safeguards ---------------------------------
    rows = []
    for pair in result.pairs:
        if pair.verdict in ("bind", "blocked"):
            continue
        if pair.verdict == "part_of":
            result.proposals.append(part_of_proposal(
                views[pair.telling_ref], units[pair.candidate_key], pair=pair, now=now,
            ))
        rows.append(question_row(pair, views[pair.telling_ref], units[pair.candidate_key]))
    result.questions = apply_caps(rows, cap=question_cap)

    result.overmerges = overmerge_audit(views, units)
    result.bridges = bridge_diagnostics(episode_records)
    # DIRECTIONAL on purpose: a re-audit is "this bound telling has a new
    # candidate", which is a statement about one telling and one episode. The
    # collapsed view keeps one direction per pair and would silently skip the
    # re-audit for whichever bound telling lost the coin toss.
    result.reaudits = reaudit_findings(
        units, result.directional, trigger=trigger, episode_records=episode_records,
        answered_pairs=answered_pairs, open_items=open_items,
    )
    result.counts = plan_counts(result, units)
    return result


def plan_counts(result: BinderPlan, units: Mapping[str, Candidate]) -> dict:
    """§8.1's report, tallied ONCE over the collapsed pairs.

    Every number below is derived from the same two sequences — the collapsed
    pairs and the records the run would file — because the first version of
    this function counted `proposals` off the containment RECORDS and
    `verdicts.proposal` off the pair rows, and on the founder's vault it
    printed `proposals: 0` beside `proposal=16`. Two tallies of one word is a
    report nobody can trust, so there is one tally and the fields say which
    thing they count.
    """
    by_telling: dict[str, int] = {}
    for pair in result.pairs:
        by_telling[pair.telling_ref] = by_telling.get(pair.telling_ref, 0) + 1
    verdicts = {name: 0 for name in VERDICTS}
    for pair in result.pairs:
        verdicts[pair.verdict] = verdicts.get(pair.verdict, 0) + 1
    would_bind = sum(len(row["operation"]["members"]) for row in result.envelopes)
    joined = sum(max(0, len(row["operation"]["members"]) - 1) for row in result.envelopes)
    return {
        "tellings": len(result.views),
        "eligible_tellings": sum(1 for row in result.views.values() if row.eligible),
        "units": len(units),
        # UNIQUE pairs. `directions_judged` is the bookkeeping behind them and
        # is reported beside it rather than instead of it, so "why is this
        # twice that" has an answer on the page.
        "pairs": len(result.pairs),
        "directions_judged": len(result.directional),
        "dropped_below_floor": result.dropped,
        "max_candidates_per_telling": max(by_telling.values(), default=0),
        "verdicts": verdicts,
        "would_bind_tellings": would_bind,
        "would_bind_episodes": len(result.envelopes),
        # Named for what each one COUNTS. `proposal_pairs` is the verdict line's
        # own number, read off the same tally; `part_of_records` is the
        # containment bindings an apply would file, which is a different thing
        # that used to be called "proposals" and disagreed with it in public.
        "proposal_pairs": verdicts.get("proposal", 0),
        "part_of_records": len(result.proposals),
        "questions": len(result.questions),
        "surfaced_questions": sum(1 for row in result.questions if row["surfaced"]),
        "possible_overmerge": len(result.overmerges),
        "bridges": sum(1 for row in result.bridges if row["finding"] == "bridge"),
        "sole_receipts": sum(1 for row in result.bridges if row["finding"] == "sole_receipt"),
        "reaudits_minted": sum(1 for row in result.reaudits
                               if row["action"] == erc.REAUDIT_MINT),
        # §8.1's headline: a `same`-bound telling is never asked WHEN, so this
        # is how many "when did this happen?" questions the apply would end.
        "when_items_that_would_disappear": joined,
    }


# --------------------------------------------------------------------------
# The dry run's own words
# --------------------------------------------------------------------------


def describe_pair(pair: Pair) -> list:
    """One pair as the owner reads it: the verdict, then all seven conditions.

    §4.2's last sentence — *"`bind-episodes --dry-run` prints per-pair reasons
    (every rule that passed and failed), not counts alone"* — is this
    function. A summary that only counted would be exactly the review the
    rollout gate says it will not accept.
    """
    mark = {"bind": "→", "part_of": "⊂", "proposal": "?", "ambiguous": "⁇",
            "asked": "·", "blocked": "✗"}[pair.verdict]
    lines = [
        f"  {mark} {pair.telling_ref}  vs  {pair.candidate_key}",
        f"      verdict: {pair.verdict} — {pair.reason}",
        (f"      signals: {', '.join(pair.signals) or 'none'} "
         f"(plausibility {pair.plausibility})"),
    ]
    for row in pair.conditions:
        lines.append(f"      [{'pass' if row.passed else 'FAIL'}] {row.name}: {row.detail}")
    if pair.part_of_suggestive:
        lines.append("      note: wide gap with a place mismatch — part_of-suggestive, "
                     "not a veto (§4.5)")
    return lines


def describe(result: BinderPlan, *, applied: bool = False) -> list:
    """The whole run, per pair and then in counts."""
    lines = [
        f"Event identity — the binder ({RULE_VERSION}, rung {RULE_ID})",
        "APPLIED" if applied else "DRY RUN — nothing was written",
        "",
    ]
    if not result.pairs:
        lines.append("  no candidate pair reached the plausibility floor")
    for pair in sorted(result.pairs, key=lambda row: (row.telling_ref, row.candidate_key)):
        lines.extend(describe_pair(pair))
        lines.append("")
    counts = result.counts
    lines.append("Summary")
    for key in ("tellings", "eligible_tellings", "units", "pairs",
                "directions_judged", "dropped_below_floor",
                "max_candidates_per_telling", "would_bind_tellings",
                "would_bind_episodes", "proposal_pairs", "part_of_records",
                "questions", "surfaced_questions", "possible_overmerge",
                "bridges", "sole_receipts", "reaudits_minted",
                "when_items_that_would_disappear"):
        lines.append(f"  {key}: {counts.get(key)}")
    lines.append("  verdicts: " + ", ".join(
        f"{name}={counts['verdicts'].get(name, 0)}" for name in VERDICTS
    ))
    for row in result.overmerges:
        lines.append(f"  ⚠ possible_overmerge {row['item_id']}: {row['reason']}")
    for row in result.bridges:
        if row["finding"] == "bridge":
            lines.append(f"  ⚠ bridge: {row['operation_id']} alone holds "
                         f"{row['episode_id']} together")
    return lines


# --------------------------------------------------------------------------
# The two functions that touch a vault
# --------------------------------------------------------------------------

#: The state file the binder's own outputs land in when a run applies. It is a
#: PROJECTION of the run, never a store: delete it and re-run and it comes
#: back, which is why it lives under `state/` beside the identity index.
BINDER_OUTPUT_FILE = f"{ei.TEMPORAL_STATE_DIR}/identity_candidates.json"

#: §8, in one constant. The weekly maintenance step calls :func:`binder_step`,
#: which is `--dry-run` by construction — a report, not a writer — and
#: `--apply` is the owner-run door. I3 ships the confirmation, split and
#: `possible_overmerge` FLOWS this constant used to say were missing; what it
#: still guards is §8's OWNER-REVIEWED DRY RUN before the founder vault is
#: ever bound, and the all-tenant backfill being its own platform deliverable
#: (I-P) — neither of those is a scheduled writer, and this constant is why
#: one never becomes one by accident.
MAINTENANCE_STEP_IS_A_DRY_RUN = (
    "The binder runs as a maintenance step and never inside `compile`. Even "
    "with I3's confirmation, split and possible_overmerge flows built, the "
    "scheduled step REPORTS and does not write: rollout step 1 requires the "
    "owner to review every would-bind pair and its reasons on a fresh clone "
    "before any `--apply` touches a live vault, and a scheduled writer would "
    "skip that review."
)


#: Why the binder folds before it binds. The age frames are calculated from
#: the RESOLVED owner-birth group, and only `temporal_timeline` can identify
#: it: subjects resolve inside the fold (v221), so a raw claim carries
#: `subject_ref: None` and the owner's own birthday can arrive as
#: `subject_mention: "birth"`. I2's first cut wrote its own owner predicate
#: over raw claims, matched nothing on the founder's vault, and reported
#: `age_frames: 0` — with the `bounds_in_frame` signal dead on all 883
#: tellings. There is one definition of a life's age frames and this is how it
#: is reached: ask the fold.
FRAMES_COME_FROM_THE_FOLD = (
    "the binder does not derive age frames; it folds once and reads the ones "
    "the fold calculated, because the owner's birth is only identifiable "
    "after subject resolution and a second predicate over raw claims is a "
    "second, worse answer to a settled question"
)


def read_vault_inputs(vault_root: str | Path, *, now: object = None) -> dict:
    """Everything one run needs, off a vault. The only impure read here.

    `episode_fold.load_episode_records` reads the identity records — both
    authorities, both validated, an incomplete envelope refused — and
    `temporal_timeline.derive_calculated_timeline` supplies the age frames
    (:data:`FRAMES_COME_FROM_THE_FOLD`). Both are CALLED rather than
    reimplemented, for the reason every other reader in this program is.

    The fold pass is the honest cost of that: one derivation per binder run,
    on the records the vault already holds. §5.7's budget is the fold's own and
    is unchanged by being read from here — and the binder is a maintenance
    step, never a turn and never a compile.
    """
    index = store.fold_active_index(vault_root)
    claims = [row for row in (index.get("claims") or ()) if isinstance(row, dict)]
    records = ef.load_episode_records(vault_root)
    return {
        "claims": claims,
        "episode_records": records,
        "frames": fold_age_frames(claims, episode_records=records, now=now),
    }


def fold_age_frames(claims: object, *, episode_records: object = (),
                    now: object = None) -> tuple:
    """The age frames THE FOLD calculated for these claims. Pure.

    Exposed so a test can prove the binder's frames are the fold's own, and so
    a host that already holds a `CalculatedTimeline` can hand over
    ``result.age_frames`` instead of paying for a second pass.
    """
    import temporal_timeline as tt  # noqa: PLC0415

    rows = [dict(row) for row in (claims or ()) if isinstance(row, dict)]
    if not rows:
        return ()
    result = tt.derive_calculated_timeline(
        {"version": store.INDEX_VERSION, "claims": rows},
        episode_records=episode_records, now=now,
    )
    return tuple(result.age_frames)


def apply_plan(vault_root: str | Path, result: BinderPlan) -> dict:
    """File a plan through `event_identity`'s ORDINARY writers. Replay is a no-op.

    Nothing is written by hand: every envelope goes through
    `file_operation_envelope` (bindings first, operation last, so a crash
    leaves inert records rather than an operation promising records the vault
    does not hold) and every containment proposal through
    `file_event_identity`'s create-or-keep. Applying the same plan twice
    creates nothing the second time, by digest arithmetic.

    There is deliberately no ``now`` here: every record already carries the
    clock the PLAN stamped, and a writer that re-stamped it would make "when
    was this decided" a property of when it was filed.
    """
    _require(isinstance(result, BinderPlan), "binder_apply_needs_a_plan",
             "apply files a BinderPlan; run `plan()` first")
    filed = {"envelopes": [], "proposals": [], "created": 0}
    for row in result.envelopes:
        outcome = ei.file_operation_envelope(
            vault_root, operation=row["operation"], bindings=row["bindings"],
        )
        filed["envelopes"].append(outcome["operation"]["operation_id"])
        filed["created"] += 1 if outcome["created"] else 0
    for record in result.proposals:
        _row, created = ei.file_event_identity(vault_root, **dict(record))
        filed["proposals"].append(record["identity_id"])
        filed["created"] += 1 if created else 0
    return filed


def bind_episodes(vault_root: str | Path, *, apply: bool = False,
                  question_cap: int = GLOBAL_QUESTION_CAP,
                  trigger: str = "maintenance_sweep",
                  era_memberships: object = None, now: object = None) -> dict:
    """`bind-episodes`, as a function. ``apply=False`` writes NOTHING.

    Returns ``{"plan", "report", "applied", "filed"}`` — the plan for a
    caller, the lines for a terminal, and what was filed when anything was.
    """
    inputs = read_vault_inputs(vault_root, now=now)
    result = plan(
        inputs["claims"], episode_records=inputs["episode_records"],
        frames=inputs["frames"], era_memberships=era_memberships,
        question_cap=question_cap, trigger=trigger, now=now,
    )
    filed = apply_plan(vault_root, result) if apply else None
    return {
        "plan": result,
        "report": describe(result, applied=bool(apply)),
        "applied": bool(apply),
        "filed": filed,
        "frames": len(inputs["frames"]),
    }


def binder_step(vault_root: str | Path, *, now: object = None,
                era_memberships: object = None,
                question_cap: int = GLOBAL_QUESTION_CAP) -> dict:
    """The maintenance seam: run the binder after recording, WRITE NOTHING.

    :data:`MAINTENANCE_STEP_IS_A_DRY_RUN` is the whole contract. The weekly
    loop calls this; the owner calls `bind-episodes --apply` once, after
    reviewing the dry run, and only once I3 exists.
    """
    outcome = bind_episodes(vault_root, apply=False, question_cap=question_cap,
                            era_memberships=era_memberships, now=now,
                            trigger="maintenance_sweep")
    return {
        "counts": dict(outcome["plan"].counts),
        "report": outcome["report"],
        "questions": list(outcome["plan"].questions),
        "overmerges": list(outcome["plan"].overmerges),
        "wrote": False,
    }


__all__ = [
    "BINDER_ERROR_CODES",
    "BINDER_OUTPUT_FILE",
    "CANONICAL_DIRECTION_RULE",
    "CLUSTER_RULE_TEXT",
    "CONTAINMENT_PHRASES",
    "CONTAINMENT_WINDOW",
    "ERA_SIGNAL_IS_SUPPLIED_BY_THE_HOST",
    "EVENT_VERB_STEMS",
    "FRAMES_COME_FROM_THE_FOLD",
    "GLOBAL_QUESTION_CAP",
    "INDEPENDENT_SIGNALS",
    "KIND_FAMILIES",
    "KIND_IS_THE_VERB_FOR_A_RECORDER_TELLING",
    "KIND_PRECEDENCE",
    "KIND_WILDCARD",
    "LABEL_TOKEN_MIN_CHARS",
    "LABEL_TOKEN_STOPWORDS",
    "MAINTENANCE_STEP_IS_A_DRY_RUN",
    "MATURE_EPISODE_MEMBERS",
    "NON_TRANSITIVE_RULE_TEXT",
    "OVERMERGE_DISJOINT_REASON",
    "PLAUSIBILITY_FLOOR",
    "POSSIBLE_OVERMERGE_KIND",
    "R1_CONDITIONS",
    "R1_RULE_TEXT",
    "REQUIRED_INDEPENDENT_SIGNALS",
    "RETRIEVAL_SIGNALS",
    "RULE_ID",
    "RULE_VERSION",
    "SAME_EVENT_KIND",
    "STEM_JOIN",
    "STEM_STOPWORDS",
    "SURFACED_PAIRS_PER_TELLING",
    "TIME_DECAY_GAP_YEARS",
    "UNFAMILIED_KINDS_ARE_ASKED",
    "VERDICTS",
    "VERDICT_PRECEDENCE",
    "VERDICT_REASONS",
    "BinderPlan",
    "Candidate",
    "Condition",
    "EpisodeBinderError",
    "Pair",
    "TellingView",
    "apply_caps",
    "apply_plan",
    "bind_episodes",
    "binder_step",
    "bridge_diagnostics",
    "candidates",
    "canonical_direction",
    "collapse_directions",
    "containment_targets",
    "create_envelope",
    "describe",
    "describe_pair",
    "disjoint_bounds_item_id",
    "fold_age_frames",
    "independent_of_the_label",
    "independent_signals",
    "is_repeatable",
    "kind_families",
    "kinds_compatible",
    "label_stem",
    "label_tokens",
    "overmerge_audit",
    "part_of_proposal",
    "plan",
    "plan_counts",
    "plausibility",
    "possible_overmerge_work_items",
    "proper_noun_tokens",
    "prospective_episode_id",
    "question_row",
    "r1_conditions",
    "read_vault_inputs",
    "reaudit_findings",
    "retrieval_signals",
    "retrieve",
    "same_event_work_item",
    "same_event_work_items",
    "says_it_is_inside",
    "telling_views",
    "unit_of",
    "verdict_for",
]
