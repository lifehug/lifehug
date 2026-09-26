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

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import cross_dating  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from identity_resolution import (  # noqa: E402
    ONCE_PER_COUPLE_EVENT_KINDS,
    ONCE_PER_SUBJECT_EVENT_KINDS,
    OWNER_SUBJECT_MENTIONS,
    REPEATABLE_EVENT_KINDS,
    couple_key,
    is_unresolved_ref,
)
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
)
from vault_paths import atomic_write_vault_text  # noqa: E402

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

#: Event identity **I2b** (amendment v4.2 §12b ruling 1). The entity signal's
#: name, and the containment rung's two rule ids, imported from the module that
#: owns them. A second spelling here would be the drift ADR 0021 exists to
#: stop — and it is imported rather than re-declared because `episode_containers`
#: is where a reader goes to find out what a roster-resolved entity IS.
ENTITY_SIGNAL = ec.ENTITY_SIGNAL
CONTAINMENT_AUTHORITIES = ec.CONTAINMENT_AUTHORITIES
DEFAULT_CONTAINMENT_AUTHORITY = ec.DEFAULT_CONTAINMENT_AUTHORITY


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
    # I2b (§12b ruling 1). A roster-resolved same entity is a SEVENTH blocking
    # signal and one point of plausibility: the founder's dry run showed a
    # landmark telling ("Etherfuse", started 2022-05) and a classifier telling
    # ("Started Etherfuse") sharing nothing but a word, because the recorder
    # keeps the name in `subject_mention` and the classifier keeps it inside a
    # sentence. The roster is what recognizes the word as an entity this life
    # contains, and recognition is evidence a string match is not.
    ENTITY_SIGNAL,
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
    ("service", ("military", "mission")),
    # v356: a baptism is one dated ordinance, once per subject — its tellings
    # are one another's and nothing else's.
    ("ordinance", ("baptism",)),
)

#: Event kinds with no family at all — named so the refusal reads as a
#: DECISION rather than as a table nobody finished. An unfamilied kind is
#: retrieved, scored and asked about; it is never deterministically bound.
UNFAMILIED_KINDS_ARE_ASKED = (
    "a kind that is in no family is never bound by R1 and is always asked; "
    "the family table is a floor on certainty, not a list of what may exist"
)


# --------------------------------------------------------------------------
# R2 — the EXACT-IDENTITY rungs: one fact, one episode (v333)
# --------------------------------------------------------------------------

#: Why there is a second family of rungs at all, stated where the first one is.
#:
#: R1 is a SIMILARITY rung: it retrieves a handful of candidates, scores
#: independent signals and refuses anything under its floor. That floor is
#: right for "are these two stories the same afternoon" and it is the wrong
#: question for a duplicate that is not a resemblance but an ARITHMETIC fact —
#: the same node read twice, the same person's birth told twice, the same
#: sentence classified twice. On the owner's vault R1 judged 44,528 pairs and
#: bound none of them, while the timeline asked "When did Dottie's birth
#: happen?" beside a node that already said 15 January 2018.
#:
#: So these rungs do not score. Each one names an EXACT key two tellings either
#: share or do not, sweeps the tellings into buckets under that key, and binds
#: inside a bucket. They are cheap (one pass, bounded buckets), they are
#: conservative in the one direction that matters (a key that does not match
#: produces no pair at all, so a miss stays cheap), and they are reversible:
#: every one of them is refused by an active or entailed `not_same`, so a
#: person's own `Different` still wins, and none of them may move an adopted or
#: human-authority episode (G1, :data:`CLUSTER_RULE_TEXT`).
EXACT_IDENTITY_RULE_TEXT = (
    "R1 asks whether two tellings RESEMBLE each other and refuses below its "
    "floor. The R2 family asks whether they are the same thing by arithmetic — "
    "the same node read twice, one subject's one birth, one label said twice, "
    "one moment restated — binds on an exact key and never on a score, and is "
    "refused by a human `not_same` exactly as R1 is."
)

#: v340. *"A binder apply never moves a dated moment."* :func:`_dates_agree`
#: has refused a contradiction since v333, but it only ever read the dates a
#: telling's own claims STATE — and a moment that sits on the timeline at a
#: date the FOLD calculated (containment inside a stay, an anchor, an era's
#: span) states nothing at all, so both sides read as undated and the rung
#: waved them through. That is how, on 2026-09-23, the owner's vault bound
#: "Family moved to Yucaipa" (the childhood move, 1981-07-11/1982-07 — inferred
#: from the Yucaipa stay) to "Family moved to Yucaipa" (2013-06/.., inferred
#: from the North Desert Village stay) on `R2c`'s identical label, and the
#: childhood move came back out of the apply dated 2013: two different moves,
#: one label, 32 years apart.
#:
#: So `R2c` and `R2d` — the two rungs whose key is words rather than arithmetic
#: — read BOTH intervals. A pair is refused when the dates its tellings state
#: contradict, and refused again when the dates the fold already has them at
#: contradict. `R2a` (a reading names exactly one node) and `R2b` (one subject's
#: one birth) are deliberately untouched: their key is the identity of the fact,
#: two readings of one fact that disagree about its date are exactly the
#: contradiction a fold is FOR, and the vault's four duplicate-birth nodes fold
#: precisely because it does.
A_MERGE_NEVER_MOVES_A_DATED_MOMENT = (
    "R2c and R2d refuse a pair whose sides sit at non-overlapping dated "
    "windows — the dates the tellings state AND the dates the fold already "
    "placed them at — because a label said twice is not a reason to move a "
    "moment onto another moment's date"
)

#: A resolver reading of a node is not a second event (v333 defect A). The
#: resolver answers a question ABOUT a node and files its date as a claim; when
#: that claim declares no telling, `event_identity.telling_ref_for_claim` falls
#: back to the claim's own source id and the reading becomes a telling of its
#: own — so the answer lands on a node of its own and the node it answered
#: keeps its card. This rung says what the record already says: a telling every
#: one of whose claims is `system_derived`, whose ref is a bare `<name>:<24
#: hex>`, and which names exactly ONE node as its event, is a READING of that
#: node and belongs to whatever episode that node's telling belongs to.
RULE_ID_DERIVED_READING = "R2a"

#: One subject's one birth, one death, one marriage to one named person
#: (`identity_resolution.ONCE_PER_SUBJECT_EVENT_KINDS`).
RULE_ID_MILESTONE = "R2b"

#: The same label, said twice, about the same people.
RULE_ID_SAME_LABEL = "R2c"

#: One moment restated in other words — the seven "Isaac's first check" nodes.
RULE_ID_RESTATEMENT = "R2d"

#: The FAMILY's id, and the one that goes on a filed binding — never the
#: individual rung's. The clone is why: `resolver --bind-restatements` and
#: `bind-episodes --apply` can both reach the same group, and
#: `event_identity.file_event_identity` is a create-or-keep over canonical
#: BYTES — so two legs that agreed about the members and disagreed about which
#: rung to name produced `identity_envelope_incomplete`, an envelope naming
#: bindings the vault had kept under other bytes. Everything a filed binding
#: says is therefore a function of its MEMBERS alone, and which rung found them
#: lives in the plan, the dry-run lines and the report, where a reader wanting
#: that detail is already looking.
RULE_ID_EXACT = "R2"

#: Every rung in the family, in the order they are swept. The order is the
#: order of CERTAINTY: an arithmetic reading first, a once-per-life fact next,
#: an identical label next, a restatement last.
EXACT_IDENTITY_RULE_IDS = (
    RULE_ID_DERIVED_READING,
    RULE_ID_MILESTONE,
    RULE_ID_SAME_LABEL,
    RULE_ID_RESTATEMENT,
)

#: :data:`RULE_ID_DERIVED_READING`'s shape test. A telling ref with a `#` names
#: one event inside one source and is never a whole-node reading.
_DERIVED_READING_REF_RE = re.compile(r"^[a-z][a-z0-9_]*:[0-9a-f]{24}$")

#: The claim source kind a derived reading is made of.
DERIVED_READING_SOURCE_KIND = "system_derived"

#: `event_kind` -> the milestone it is, so `birth` and `child_born` are one
#: milestone and `death` and `loss` are one. Keyed on
#: `identity_resolution.ONCE_PER_SUBJECT_EVENT_KINDS` and swept against it by
#: `test_event_identity_i2_binder.py`, so a kind added there cannot silently
#: fall out of this table.
MILESTONE_OF_EVENT_KIND = {
    "birth": "birth",
    "child_born": "birth",
    "death": "death",
    "loss": "death",
    "married": "married",
}

#: The same milestone read out of the LABEL, through the module's own
#: event-verb table — because the classifier's kind for "a thing that happened"
#: is the `moment` wildcard, so "Dottie's birth" carries no `birth` kind at all
#: and the verb is the only place the milestone is written down.
MILESTONE_OF_VERB_STEM = {"born": "birth", "die": "death", "marry": "married"}

#: v345. *"A telling of a landmark folds onto the landmark, and a landmark is
#: drawn as what it is."* (Owner review of staging, 2026-09-24.)
#:
#: Three tellings of the owner's parents' wedding sat as three nodes. "Parents'
#: wedding date" carried the day, 1976-06-25; "Mom married dad at 21" carried
#: the age and no date at all, with its own *"when did this happen?"* card; and
#: the `family` landmark entry — a couple's wedding filed under a domain that
#: declares `date_semantics: birth` — was drawn a THIRD time as "Parents's
#: birth". Beside them, "Harvey arriving" stayed undated with its own card while
#: its evidence read *"Birth of Harvey during the Etherfuse chapter"* and the
#: vault had held Harvey's birthday, 2021-10-11, for weeks.
#:
#: The milestone rung could see none of it. Its key is (milestone, one person),
#: and the milestone is read from the `event_kind` or the label's own verb — so
#: "arriving" is not a birth, "wedding" is not a marriage, and a wedding's two
#: people are two keys rather than one couple.
A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT = (
    "R2b reads the milestone the EVIDENCE names, not only the one the kind or "
    "the label's verb does, and keys a marriage on the COUPLE rather than on "
    "one of the two people — so a telling of an event the vault already holds "
    "as a dated landmark folds onto the landmark instead of asking when it "
    "happened"
)

#: v350, and it is v345's own rule finishing its sentence. A COUPLE is two
#: people; it is not a relationship word found somewhere in what a telling is
#: called. The owner's vault: `node:b8681112f7eed9342e7e4d56` *"Wedding
#: reception in mother-in-law's backyard"* — HIS reception, his own anniversary
#: 2007-01-11, subject `self` — was folded into his PARENTS' wedding at
#: 1976-06-25 beside *"Mom married dad at 21"*, because a roster introduction
#: had filed ``mother`` as an alias of his mother and the run matcher read that
#: word out of ``mother-in-law``. It surfaced as a contradiction card, so v340
#: held; the merge was still wrong.
#:
#: Two legs and one seat each. The couple is read from the telling's own
#: SUBJECTS (`identity_resolution.couple_key`, now handed
#: :attr:`TellingView.subject_mentions`), so the owner's own subject names the
#: OWNER's couple and a word in a backyard names nobody; and a compound
#: relationship word is never the simple word inside it
#: (`identity_resolution.A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`,
#: enforced where the wrong person was resolved —
#: `episode_containers.resolve_entities` — so every rung that reads a roster
#: match is fixed once rather than R2b alone).
A_COUPLE_IS_TWO_PEOPLE = (
    "a couple is two people, not one relationship word: a couple key is read "
    "from a telling's own subjects — the owner's own subject naming the owner's "
    "couple — and a compound relationship word is never the simple word inside "
    "it, so mother-in-law is not mother and a wedding reception is not a "
    "wedding somebody else had"
)

#: The milestone read out of a NOUN the label carries. `wedding` alone, and the
#: omissions are the rule: `marriage` is a STATE a life spends years inside —
#: the owner's vault holds "Marriage became hard", "Early marriage arguments and
#: silence", "Went bankrupt early in marriage" and six more — and `anniversary`
#: recurs. A wedding is the day. Read through
#: :data:`MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER` so a noun that says WHEN rather
#: than WHAT ("Father fell ill after wedding") is not the telling's own event.
MILESTONE_OF_EVENT_NOUN = {"wedding": "married"}

#: Owner ruling, 2026-09-25 (the cornerstones ruling): *"A telling of the
#: owner's wedding to the same spouse IS that cornerstone."* Two readings the
#: milestone rung could not make, and his vault held SEVEN nodes for one
#: wedding because of them.
#:
#: * **"Marriage to Katie" is the wedding.** `marriage` stays out of
#:   :data:`MILESTONE_OF_EVENT_NOUN` — "Marriage became hard" is the stretch,
#:   not the day — but the noun followed by ``to`` and the person married is the
#:   act of marrying them (:data:`MILESTONE_OF_EVENT_NOUN_PHRASE`). The owner's
#:   ``answers/A15`` "Marriage to Katie" (*"Author married Katie when he was 26
#:   and she was 20"*) was drawn at 2001-07/2008-07 from that age, beside the
#:   stated 2007-01-11, as a node of its own.
#: * **The owner's couple needs no second name.** v345's couple bucket was only
#:   reached by a telling that ALSO named a non-owner person token, so "Married
#:   Katie", "Getting married to Katie" and "Married Katie Ann Merrill" — whose
#:   only subject is ``self``/``narrator``, and whose spouse the roster did not
#:   resolve into a person token — were never bucketed at all. The couple key
#:   (`identity_resolution.couple_key`, the owner's own subject naming the
#:   owner's couple) is the discriminator; the person tokens are not asked for.
#:
#: The age such a telling carries then folds as evidence on the wedding —
#: supporting when it contains the day, a contradiction card when it does not
#: (`temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT`) — never a separate node.
A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE = (
    "a telling of the owner's wedding folds onto the wedding: \"marriage to "
    "<someone>\" names the wedding, and the owner's couple key alone buckets a "
    "telling for R2b without a second person token, so an age said about the "
    "wedding is evidence on its day and never a node of its own"
)

#: ``(noun, next word)`` -> the milestone. "Marriage to Katie" is a wedding;
#: "Marriage became hard" is not.
MILESTONE_OF_EVENT_NOUN_PHRASE = {("marriage", "to"): "married"}

#: A preposition immediately before a milestone noun makes it an ADJUNCT: the
#: telling happened near that event and is not that event. "Father fell ill
#: after wedding" is an illness; "Parents' wedding date" is a wedding.
MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER = frozenset({
    "after", "before", "during", "since", "until", "till", "post", "pre",
    "in", "into", "at", "on", "from", "by", "near", "around", "about",
})

#: A roster entity ref's person prefix (`episode_containers` mints
#: `<roster type>/<key>`), so a rung can ask "which PEOPLE does this telling
#: name" without asking about places, themes or organisations.
PERSON_ENTITY_PREFIX = "person/"

#: :data:`RULE_ID_RESTATEMENT`'s floor: how many significant label tokens two
#: labels must SHARE before a restatement is a restatement. Three, and one of
#: them must be the named entity the bucket is keyed on — so "Isaac writes
#: first check" and "Isaac's first check for Etherfuse" share `isaac`, `first`
#: and `check` and are one moment, while "Meeting Isaac Saldana" shares
#: `isaac` and `saldana` with them and stays its own.
RESTATEMENT_SHARED_TOKENS = 3

#: And how many each side must HAVE, so a two-word label is never swallowed by
#: a longer one that happens to contain it.
RESTATEMENT_MIN_TOKENS = 3

#: A bucket bigger than this is not swept. A named entity that appears in
#: hundreds of labels is a life's centre of gravity, not a discriminator, and a
#: quadratic sweep over it would be both slow and the one place this family
#: could start guessing.
RESTATEMENT_BUCKET_CAP = 128


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
INDEPENDENT_SIGNALS = ("source_document", "place", "participant", ENTITY_SIGNAL, "bounds")

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
    #: v340. The interval the FOLD already has this telling's node at, which is
    #: not the same question as ``bounds``
    #: (:data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`).
    placed_bounds: object = None
    containment: frozenset = frozenset()
    created_at: str = ""
    eligible: bool = True
    ineligible_reason: str = ""
    #: I2b. Every roster entity this telling NAMES (its event and subject
    #: mentions, never its evidence prose) and, separately, the ones it is
    #: ABOUT. The split is what makes a container nameable without making every
    #: telling that mentions college into the college
    #: (:data:`episode_containers.CONTAINER_RULE_TEXT`).
    entities: frozenset = frozenset()
    subject_entities: frozenset = frozenset()
    #: The entities its PLACE mentions resolve to, kept apart so a place that
    #: already scored the `place` signal is not counted a second time as an
    #: entity (:data:`episode_containers.ONE_FACT_ONE_SIGNAL_TEXT`).
    place_entities: frozenset = frozenset()
    #: I2b. The stretch this telling's own words OPEN, and whether they closed
    #: it. `None` for a point-dated moment, which is not a container.
    span: object = None
    span_open_ended: bool = False
    #: v333, the R2 family. Every node ref this telling's claims name as their
    #: `event_ref` — the fold's own answer to "which event is this claim
    #: about", read rather than re-derived.
    node_refs: frozenset = frozenset()
    #: The node this telling is a DERIVED READING of, or `""`
    #: (:data:`RULE_ID_DERIVED_READING`).
    reads_node: str = ""
    #: The word tokens of every NON-OWNER person this telling names, from the
    #: roster where the roster resolves one and from the telling's own
    #: participant set where it does not. The owner is dropped for the reason
    #: :data:`INDEPENDENT_SIGNALS` drops him: he is on every telling.
    people: frozenset = frozenset()
    #: v350. This telling's own ``subject_mention`` texts, as written — who it
    #: is ABOUT, in the person's own words, owner mentions included. Read by
    #: :data:`A_COUPLE_IS_TWO_PEOPLE`'s couple key and by nothing else, and
    #: deliberately NOT :attr:`people`: `people` is every name anywhere in the
    #: telling, tokenized and roster-resolved, which is the right input for "did
    #: these two tellings name the same person" and the wrong one for "whose
    #: event is this".
    subject_mentions: tuple = ()
    #: v345. This telling's OWN sentences — its event mentions, its subject
    #: mentions and its evidence quotes (:func:`_claim_texts`, the same reader
    #: the containment rung uses). Read by :func:`milestone_of` and by nothing
    #: else: an evidence quote is prose the model transcribed, so it may name
    #: the KIND of a fact the classifier typed as the wildcard and it may never
    #: contribute a retrieval signal (:data:`ONE_FACT_ONE_SIGNAL_TEXT`'s own
    #: reason, and `_mention_texts`').
    phrases: frozenset = frozenset()
    #: lifehug#413 (`episode_containers.A_MISSION_CONTAINS_ITS_PLACES`). The
    #: place-containing span kinds this telling names as its SETTING ("on my
    #: mission"), and ``(kind, place ref)`` for every place it sets one in —
    #: an area a telling of the mission names, or the stay R7 dated a mission
    #: tenure from. Read by the containment rung and by nothing else.
    settings: frozenset = frozenset()
    setting_places: frozenset = frozenset()
    #: The stretch this telling's own claims cover WHATEVER their basis
    #: (`episode_containers.span_from_claims(require_stated=False)`), because a
    #: stay's two ends intersect to nothing and a stay still has an interval.
    stretch: object = None
    #: A place-containing span's own landmark words (label, where, place,
    #: city) — "Where did you serve?" — and nothing for any other telling.
    landmark_words: tuple = ()

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
            "placed": self.placed_bounds is not None,
            "containment": sorted(self.containment),
            "entities": sorted(self.entities),
            "subject_entities": sorted(self.subject_entities),
            "place_entities": sorted(self.place_entities),
            "opens_a_span": self.span is not None,
            "span_open_ended": self.span_open_ended,
            "node_refs": sorted(self.node_refs),
            "reads_node": self.reads_node,
            "people": sorted(self.people),
            "subject_mentions": list(self.subject_mentions),
            "phrases": sorted(self.phrases),
            "settings": sorted(self.settings),
            "setting_places": sorted(self.setting_places),
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
    #: I2b. The union of its members' named entities — the candidate side of
    #: the entity signal — and, apart, the ones its places already account for.
    entities: frozenset = frozenset()
    place_entities: frozenset = frozenset()
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
    #: I2b (§13.5). The containment rung's own report — one block per
    #: CONTAINER, its members listed under it with the rule and the reason that
    #: placed each one. Named `containments` when the host's authority is
    #: `applied` and `containment_proposals` when it is `proposed`, because
    #: those are two different promises to a reader and one word for both would
    #: be a lie in one of the two cases.
    containments: list = field(default_factory=list)
    #: Stamps that named no container this run knows (`question_context`).
    containment_diagnostics: list = field(default_factory=list)
    #: E-L2a §4.1 condition 4: the (telling, entity) pairs the rung REFUSED to
    #: place because the person was at that entity more than once. A REPORT,
    #: not a question: the question is minted once, in the fold
    #: (`temporal_timeline._apply_entity_ambiguity`), where every other work
    #: item is minted and where the published projection can carry it. Two
    #: minters for one `place_ambiguous` row would be the same defect class
    #: this phase retired `place_co_location` to end.
    containment_ambiguities: list = field(default_factory=list)

    #: §4.1 condition 6 (E-L2b). One row per pair the rung would have filed
    #: and did not, because the person had already decided it — the drag-out's
    #: durable negative, reported rather than merely obeyed.
    containment_negatives: list = field(default_factory=list)
    #: §12b ruling 6's upgrade path
    #: (`episode_fold_contract.CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT`).
    #: Records this rung ALREADY filed at the weaker authority, which this run
    #: would move to `deterministic` in place — same file, same identity_id,
    #: same evidence, same clock, one field. Empty at `proposed` authority by
    #: construction: `proposed` -> `proposed` is not a move.
    containment_upgrades: list = field(default_factory=list)
    #: The mirror image, and deliberately NOT symmetric: identity_ids already
    #: filed at `deterministic` that this run, at `proposed` authority, KEPT.
    #: A host that forgot its flag does not un-draw a containment a person can
    #: already see and already drag out — and a silent keep would be
    #: indistinguishable from a rung that found nothing.
    containment_kept_stronger: list = field(default_factory=list)
    #: v333, the R2 family. Every exact-identity link the rungs found, the
    #: components they became, and the ones a `not_same` or G1 refused — all
    #: three, because a dry run that printed only what it would file could not
    #: be reviewed for what it declined.
    exact_links: list = field(default_factory=list)
    exact_groups: list = field(default_factory=list)
    exact_refused: list = field(default_factory=list)
    #: The R2 family's own `create` envelopes, kept APART from R1's
    #: :attr:`envelopes` rather than appended to them. Two families decide here
    #: and a caller — a test, a dry run, a receipt — must be able to ask what
    #: each one did; one list would make "R1 bound nothing" unaskable, which is
    #: the very sentence the v333 incident turned on. `apply_plan` files both,
    #: in this order, through the same writers.
    exact_envelopes: list = field(default_factory=list)
    #: The authority the run filed under (`episode_fold_contract`'s flag).
    containment_authority: str = ec.DEFAULT_CONTAINMENT_AUTHORITY
    #: `{container_key: Container}` the run reasoned over, kept for a caller
    #: that wants the container itself rather than the report of it.
    containers: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    dropped: int = 0
    views: dict = field(default_factory=dict)

    @property
    def containment_block_name(self) -> str:
        """`containments` or `containment_proposals`, per the authority flag."""
        return ("containments" if self.containment_authority == "applied"
                else "containment_proposals")

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
            "exact_identity_rule_ids": list(EXACT_IDENTITY_RULE_IDS),
            "exact_links": [row.as_dict() for row in self.exact_links],
            "exact_groups": [
                {"members": list(row["members"]), "tellings": list(row["tellings"]),
                 "rule_ids": list(row["rule_ids"]), "reasons": list(row["reasons"])}
                for row in self.exact_groups
            ],
            "exact_refused": list(self.exact_refused),
            "exact_envelopes": [
                {"operation": row["operation"], "bindings": row["bindings"],
                 "rule_ids": row["rule_ids"],
                 "aliases_created": row["operation"]["aliases_created"]}
                for row in self.exact_envelopes
            ],
            "overmerges": list(self.overmerges),
            "bridges": list(self.bridges),
            "reaudits": list(self.reaudits),
            "containment_authority": self.containment_authority,
            self.containment_block_name: list(self.containments),
            "containment_diagnostics": list(self.containment_diagnostics),
            "containment_ambiguities": list(self.containment_ambiguities),
            "containment_negatives": list(self.containment_negatives),
            "containment_upgrades": list(self.containment_upgrades),
            "containment_kept_stronger": list(self.containment_kept_stronger),
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


def _mention_texts(claims: Sequence[object]) -> tuple:
    """``(every mention, the subject mentions)`` — the telling's NAMES.

    Deliberately not `_claim_texts`: that one reads evidence quotes for the
    containment-language parse, and the entity signal must not fire on prose
    the model transcribed. These are the fields the substrate already keeps AS
    names — what the telling calls the event, and who or what it is about.
    """
    every: list[str] = []
    subjects: list[str] = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        for value in (row.get("event_mention"),):
            text = collapsed_text(value)
            if text and text not in every:
                every.append(text)
        text = collapsed_text(row.get("subject_mention"))
        if text:
            if text not in subjects:
                subjects.append(text)
            if text not in every:
                every.append(text)
    return tuple(every), tuple(subjects)


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


def _node_refs_of(claims: Sequence[object]) -> frozenset:
    """Every `node:` ref these claims name as their own `event_ref`.

    The fold's own field, read and not re-derived: `event_ref` is where an
    extractor writes down which event its claim is about, and for a claim filed
    ABOUT a projection node it is that node's id.
    """
    found = set()
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        ref = collapsed_text(row.get("event_ref"))
        if ref.startswith("node:"):
            found.add(ref)
    return frozenset(found)


def reads_node(telling_ref: object, claims: Sequence[object]) -> str:
    """The node this telling is a DERIVED READING of, or ``""``.

    Three clauses, and all three are needed (:data:`RULE_ID_DERIVED_READING`):

    * every claim is `system_derived` — a reading is something this program
      worked out, never something a person said;
    * the ref is a bare ``<name>:<24 hex>`` with no ``#`` — a ref with a ``#``
      names one event inside one source, which is a telling and not a reading;
    * it names exactly ONE node. A reading that named two would be a reading of
      neither, and guessing which is the defect this rung exists to end.

    Deliberately NOT a list of extractor names. `resolver` is the one that
    files these today, and a rung keyed on its name would have to be edited for
    the second one — whereas the three clauses above are what makes a reading a
    reading whoever files it.
    """
    ref = collapsed_text(telling_ref)
    rows = [claim for claim in (claims or ()) if isinstance(claim, dict)]
    if not rows or not _DERIVED_READING_REF_RE.fullmatch(ref):
        return ""
    if any(collapsed_text(row.get("source_kind")) != DERIVED_READING_SOURCE_KIND
           for row in rows):
        return ""
    nodes = _node_refs_of(rows)
    return next(iter(nodes)) if len(nodes) == 1 else ""


def person_tokens(mentions: object, participants: object = (),
                  index: object = None) -> frozenset:
    """The word tokens of every NON-OWNER person this telling names.

    Two sources, narrowest first, and the second one is there because the first
    leaves a hole the owner's vault actually has:

    * the ROSTER, because a roster match turns "Isaac" and "Isaac Saldana" into
      one person rather than two strings;
    * the telling's own PARTICIPANT mentions, because that vault's entity index
      holds ELEVEN people and `Isaac`, `Dottie` and `Katie` — three of the five
      duplicate clusters the v333 incident is about — are in none of them, while
      every one of them is written down as somebody's `participant_set`.

    Tokens rather than whole keys, for the same reason: one telling says `isaac`
    and the next says `isaac saldana`, and a rule that compared whole keys would
    call one person two.

    Deliberately NOT the label's own proper nouns, even filtered through a
    vocabulary of every name the vault uses. That version was written and run on
    the clone: the vault's participant sets hold `arizona`, `redlands` and
    `young` as readily as `isaac`, so "a birth happens once to one person, and
    both tellings are arizona's" chained 104 tellings — four people's births and
    two towns — into one episode. Who was there is a field; what a sentence
    happens to contain is not.

    Also deliberately NOT an `identity_resolution.is_unresolved_ref` handle.
    `event_identity.telling_signature` writes a claim's raw `subject_ref` into
    `participant_set` unfiltered, and a bare first name the roster cannot
    resolve carries the handle `unresolved:<name>` there (the same shared
    name census `identity_resolution.shared_name_token_refs` is uncertain
    about) rather than a `person/` ref. Tokenizing that handle would read
    `unresolved:james` as the token `james` — the ONE name two different
    people share — so two different unresolved Jameses would look like one
    resolved person to this rung and a milestone or restatement rung could
    bind their tellings on that coincidence alone. An unresolved subject
    names nobody in particular here, so it contributes no token.
    """
    names: set[str] = set()
    # One read over both, so a name one of them gives a relationship word
    # holds in the other (`episode_containers.A_RELATION_WORD_WITH_ANOTHER_NAME_IS_NOT_THEM`).
    for ref in ec.resolve_entity_set(tuple(mentions or ()) + tuple(participants or ()), index):
        if collapsed_text(ref).startswith(PERSON_ENTITY_PREFIX):
            name = index.name_of(ref) if hasattr(index, "name_of") else ""
            names.add(collapsed_text(name) or collapsed_text(ref).split("/", 1)[1])
    names.update(
        collapsed_text(value) for value in participants or ()
        if not is_unresolved_ref(value)
    )
    tokens: set[str] = set()
    for name in names:
        if normalized_mention_key(name) in OWNER_SUBJECT_MENTIONS:
            continue
        for token in label_tokens(name):
            if len(token) >= LABEL_TOKEN_MIN_CHARS and token not in OWNER_SUBJECT_MENTIONS:
                tokens.add(token)
    return frozenset(tokens)


def _milestone_conflict(left: "TellingView", right: "TellingView") -> bool:
    """Do these two tellings name DIFFERENT once-per-subject milestones?

    A birth is not a death, whatever else two labels have in common. Without
    this, the founder vault's `R2d` read "Grandpa James Edwin Taylor Sr.'s
    death" and "James Edwin Taylor Sr's birth" as one moment, because the three
    tokens they share are all his name and the classifier's kind for both is the
    `moment` wildcard.
    """
    a, b = milestone_of(left), milestone_of(right)
    return bool(a) and bool(b) and a != b


def milestone_of(view: "TellingView") -> str:
    """Which once-per-subject milestone this telling is, or ``""``.

    The `event_kind` when it names one; otherwise the LABEL's own verb, because
    the classifier's kind for "a thing that happened" is the `moment` wildcard
    and "Dottie's birth" carries no `birth` kind anywhere.

    **v345** adds the two readings a label's verb cannot give
    (:data:`A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT`), in order of how much they
    claim:

    * the label's own NOUN (:data:`MILESTONE_OF_EVENT_NOUN`) — "Parents'
      wedding date" is a wedding and no verb in it says so — refused when the
      noun is an adjunct (:data:`MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER`);
    * the EVIDENCE, through `landmark_projection.names_a_birth` — "Harvey
      arriving" is Harvey's birth because the quote behind it says *"Birth of
      Harvey"*. The name the quote gives must be somebody the telling is ALREADY
      about (:meth:`TellingView.people`), so "the birth of the company" and a
      quote that mentions a third party's birth in passing say nothing. This
      reads the sentence; it never rewrites the receipt.
    """
    kind = collapsed_text(view.event_kind)
    if kind in MILESTONE_OF_EVENT_KIND:
        return MILESTONE_OF_EVENT_KIND[kind]
    if is_repeatable(kind):
        return ""
    tokens = label_tokens(view.label)
    words = tuple(sorted(view.people)) + tuple(view.subject_mentions)
    for token in tokens:
        milestone = MILESTONE_OF_VERB_STEM.get(EVENT_VERB_STEMS.get(token, ""))
        if milestone and token in MILESTONE_NOUNS_READ_STRICTLY:
            # :data:`A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE`: the
            # NOUN is the milestone only in a title that is nothing else.
            import cornerstones as cs  # noqa: PLC0415 - avoids an import cycle

            if MILESTONE_OF_CORNERSTONE.get(
                    cs.milestone_of_label(view.label, subject_words=words)) != milestone:
                continue
        if milestone:
            return milestone
    for index, token in enumerate(tokens):
        milestone = MILESTONE_OF_EVENT_NOUN.get(token)
        if not milestone and index + 1 < len(tokens):
            # :data:`A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE`.
            milestone = MILESTONE_OF_EVENT_NOUN_PHRASE.get((token, tokens[index + 1]), "")
        if not milestone:
            continue
        if index and tokens[index - 1] in MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER:
            continue
        return milestone
    if _evidence_names_this_telling_a_birth(view):
        return "birth"
    # :data:`A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE` — "Father
    # dies of COVID", "Dottie's birth": a title the cornerstones' own strict
    # reading calls a milestone (every word before it names who) is one.
    import cornerstones as cs  # noqa: PLC0415 - avoids an import cycle

    return MILESTONE_OF_CORNERSTONE.get(cs.milestone_of_label(view.label, subject_words=words), "")


#: v360 follow-up (owner, 2026-09-25) (item 4). The owner's father's death sat as
#: separate nodes — "Father dies of COVID" (2020) apart from "Father's death"
#: (his "right before we started Etherfuse", 2022) — because the milestone
#: rung's verb table knows "die"/"died" and not "dies", while it read the NOUN
#: "death" anywhere in a label, so "Begins processing father's death years
#: later" and "Father's death and marriage strain" were deaths and "Father dies
#: of COVID" was not. Both now read through `cornerstones.milestone_of_label`,
#: the one strict reading of a title that IS a milestone: one milestone word,
#: no conjunction, no adjunct, and every word before it a name, a relation
#: word or a possessive. R2b's own guards (the same people, dates that do not
#: contradict) are untouched.
A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE = (
    "a telling whose title is nothing but a milestone and whose it is — "
    "\"Father's death\", \"Dottie's birth\" — is that milestone for R2b, read "
    "through the cornerstones' strict title reading"
)

#: `cornerstones` milestone words -> this rung's.
MILESTONE_OF_CORNERSTONE = {"birth": "birth", "death": "death", "wedding": "married"}

#: The two NOUNS `EVENT_VERB_STEMS` folds into a milestone verb. A verb says
#: the milestone happened ("Father died of COVID"); the noun is as often the
#: thing a telling is ABOUT something else near ("Begins processing father's
#: death years later", "Father's death and marriage strain") — so the noun
#: counts only in a title the strict reading calls the milestone itself.
MILESTONE_NOUNS_READ_STRICTLY = frozenset({"death", "birth"})


def _evidence_names_this_telling_a_birth(view: TellingView) -> bool:
    """Does one of this telling's own sentences say it is a birth, and whose?

    `landmark_projection.names_a_birth` reads the sentence; this decides whether
    the name it read is THIS telling's subject, which is the half no word list
    can do. Both sides are compared as tokens, nested exactly as
    :func:`_same_people` nests them, so "Harvey" satisfies a telling about
    "Harvey Rex Taylor" and "Etherfuse" satisfies nothing.
    """
    if not view.people:
        return False
    for phrase in sorted(view.phrases):
        named = lp.names_a_birth(phrase)
        if not named:
            continue
        tokens = frozenset(
            token for token in label_tokens(named)
            if token and token not in OWNER_SUBJECT_MENTIONS
        )
        if tokens and (tokens <= view.people or view.people <= tokens):
            return True
    return False


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


#: The landmark fields a place-containing span names its places in.
PLACE_SPAN_LANDMARK_FIELDS = ("where", "place", "city", "label", "name")


def _place_span_landmark_words(landmark_entries: object) -> dict:
    """``{telling ref: the entry's own place words}`` for every landmark entry
    of a :data:`episode_containers.PLACE_CONTAINING_SPAN_KINDS` domain."""
    domains = set(ec.PLACE_CONTAINING_SPAN_KINDS.values())
    found: dict[str, tuple] = {}
    for row in landmark_entries or ():
        if not isinstance(row, dict) or collapsed_text(row.get("domain")) not in domains:
            continue
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        source_id = collapsed_text(row.get("source_id"))
        if not source_id:
            continue
        words = tuple(dict.fromkeys(
            collapsed_text(record.get(name)) for name in PLACE_SPAN_LANDMARK_FIELDS
            if collapsed_text(record.get(name))
        ))
        found[ei.landmark_telling_ref(source_id.partition(":")[2] or source_id)] = words
    return found


def _span_settings_of(rows: Sequence[object], mentions: Sequence[str],
                      subject_mentions: Sequence[str], subject_entities: object,
                      named: object, entity_index: object) -> tuple:
    """``(settings, setting_places)`` for one telling — lifehug#413.

    A telling that names a place-containing span as its setting (not by its
    MTC) files a place it names IN ITS OWN WORDS as that span's place
    ("Mission assignment to Solothurn" -> Solothurn, Switzerland) — never a
    place the classifier attached from the rest of the source ("Went on his
    mission" carries every town of the answer it came from). A telling v356's vocabulary says is OF the span, whose
    dates R7 inherited from a stay, files that stay's place ("Missionary — …",
    dated "from the dates of the Friedrichshafen, Germany stay"). The MTC is
    a setting and not an area: "Residence at the MTC" names Provo, which the
    mission does not cover.
    """
    settings, mtc = ec.span_settings(mentions, subject_mentions, subject_entities)
    places: set = set()
    named_places = {ref for ref in named or () if collapsed_text(ref).startswith("place/")}
    said = " " + " ".join(normalized_mention_key(text) for text in mentions) + " "
    in_words = {ref for ref in named_places
                if ec.place_in_words(ref, said, entity_index)}
    for kind in settings - mtc:
        places |= {(kind, ref) for ref in in_words}
    stays = ec.dated_from_stays(rows)
    if stays and any("mission" in text.casefold() for text in mentions):
        if not ec.about_someone_else(subject_mentions, subject_entities):
            for kind in ec.names_span_kind(mentions):
                places |= {(kind, ref) for ref in ec.resolve_entity_set(stays, entity_index)
                           if ref.startswith("place/")}
    return settings, frozenset(places)


def telling_views(claims: object, *, manifest: object = None,
                  era_memberships: object = None, entity_index: object = None,
                  participation_kinds: object = None,
                  placed_windows: object = None,
                  landmark_entries: object = ()) -> dict:
    """``{telling_ref: TellingView}`` — pure, over the claims and nothing else.

    The claim→telling map is `episode_fold.claim_telling_index`, which is C1's
    own; a second answer to "which telling is this claim part of" is exactly
    the drift this program exists to remove.

    ``era_memberships`` is ``{telling_ref: [era id, …]}`` and is an ARGUMENT
    rather than a read: era membership is decided by the fold over records
    this module does not own, and re-deriving it here would be a second copy
    of the eras fold living inside the binder.

    ``participation_kinds`` (E-L2a) is
    `landmark_projection.participation_kinds_by_telling`' map, and it is an
    argument for the third time for the same reason. A landmark entry of a
    span domain has ``started``/``ended`` claims and nothing else, so
    :func:`_kind_of` called a residence ``started`` — which
    :data:`KIND_FAMILIES` files under ``work``, so a house and a job were the
    same family and a house was in no family of its own. The domain is the
    kind (design §3.2); it is read off the promoted source's own frontmatter
    and never guessed from the words.

    ``placed_windows`` (v340) is ``{telling_ref: the interval the timeline
    already has that telling's node at}`` — :func:`placed_windows_of`' map, an
    argument for the same reason every other derived input here is one, and
    what :data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT` reads. A vault that hands
    over none simply has no placed-window half to its date test.

    ``entity_index`` (I2b) is the vault's rosters as one
    `episode_containers.EntityIndex`, and is an argument for the same reason —
    a roster is a vault read and this function is pure. With none supplied the
    entity signal simply never fires and every pair scores one signal fewer,
    which can only ever retrieve LESS, never bind wrongly.

    ``landmark_entries`` (v345) is `landmark_projection.load_landmark_sources`'
    list, and it is an argument for the fourth time for the same reason. It is
    read for ONE thing — `landmark_projection.read_landmark_dates`, so a
    landmark date claim reaches the milestone rung as the event its ENTRY dates
    (:data:`A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT`) — and the fold applies the
    identical read, so the binder and the drawing can never disagree about what
    a `family` entry's date is. A vault that hands over none is read exactly as
    it was before.
    """
    rows = lp.read_landmark_dates(claims, landmark_entries)
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

    kinds_by_telling = {
        collapsed_text(key): collapsed_text(value)
        for key, value in dict(participation_kinds or {}).items()
    }

    placed_by_telling: dict[str, object] = {}
    for key, value in dict(placed_windows or {}).items():
        record = value if isinstance(value, chrono.DateRecord) else chrono.from_dict(value)
        if record is not None and collapsed_text(key):
            placed_by_telling[collapsed_text(key)] = record

    words_by_telling = _place_span_landmark_words(landmark_entries)

    views: dict[str, TellingView] = {}
    for telling_ref in sorted(by_telling):
        rows_here = by_telling[telling_ref]
        event_kind = kinds_by_telling.get(telling_ref) or _kind_of(rows_here)
        signature = ei.telling_signature(rows_here)
        label = _label_of(rows_here)
        participants = frozenset(signature.get("participant_set") or ())
        bounds, dated = _bounds_of(rows_here)
        mentions, subject_mentions = _mention_texts(rows_here)
        entities = ec.resolve_entity_set(mentions, entity_index)
        subject_entities = ec.resolve_entity_set(subject_mentions, entity_index)
        place_entities = ec.resolve_entity_set(signature.get("place_set") or (), entity_index)
        span, span_open_ended = ec.span_from_claims(rows_here)
        settings, setting_places = _span_settings_of(
            rows_here, mentions, subject_mentions, subject_entities,
            entities | place_entities, entity_index)
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
            event_kind=event_kind,
            node_refs=_node_refs_of(rows_here),
            reads_node=reads_node(telling_ref, rows_here),
            people=person_tokens(tuple(mentions) + tuple(subject_mentions),
                                 participants, entity_index),
            subject_mentions=tuple(subject_mentions),
            phrases=frozenset(_claim_texts(rows_here)),
            label=label,
            stem=label_stem(label, participants, event_kind=event_kind),
            tokens=proper_noun_tokens(label),
            places=frozenset(signature.get("place_set") or ()),
            participants=participants,
            eras=eras.get(telling_ref, frozenset()),
            documents=_documents_of(telling_ref, rows_here),
            bounds=bounds,
            dated=dated,
            placed_bounds=placed_by_telling.get(telling_ref),
            containment=containment_targets(_claim_texts(rows_here)),
            entities=entities,
            subject_entities=subject_entities,
            place_entities=place_entities,
            span=span,
            span_open_ended=span_open_ended,
            settings=settings,
            setting_places=setting_places,
            stretch=(span if span is not None
                     else ec.span_from_claims(rows_here, require_stated=False)[0]),
            landmark_words=words_by_telling.get(telling_ref, ()),
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
        entities=(frozenset().union(*[row.entities for row in rows])
                  if rows else frozenset()),
        place_entities=(frozenset().union(*[row.place_entities for row in rows])
                        if rows else frozenset()),
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
    if view.entities & candidate.entities:
        found.append(ENTITY_SIGNAL)
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

    **The entity signal (I2b, §12b ruling 1)** is one signal here, and never
    two: whatever `independent_of_the_label` already credited as a participant
    is SUBTRACTED (`episode_containers.shared_entities`) before the shared
    entities are counted. So a recorder telling whose subject IS the label
    contributes the roster's recognition once, under one name, and R1's floor
    of two independent signals is unchanged — the entity signal has never
    bound anything on its own and cannot.
    """
    found: list[str] = []
    if view.documents & candidate.documents:
        found.append("source_document")
    counted: set = set()
    shared_places = view.places & candidate.places
    if shared_places:
        found.append("place")
        counted |= set(shared_places) | set(view.place_entities & candidate.place_entities)
    participants = independent_of_the_label(view, candidate)
    if participants:
        found.append("participant")
        counted |= set(participants)
    if ec.shared_entities(view.entities, candidate.entities, already_counted=counted):
        found.append(ENTITY_SIGNAL)
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
# --------------------------------------------------------------------------
# The R2 family — the exact-identity rungs (:data:`EXACT_IDENTITY_RULE_TEXT`)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExactLink:
    """Two tellings one R2 rung says are the same event, and why.

    A LINK, not a pair: nothing here is scored, nothing here is surfaced as a
    question, and a rung that finds no link produces no row at all — which is
    what keeps the family's failure mode "nothing happened" rather than "a
    guess happened".
    """

    rule_id: str
    left: str
    right: str
    key: str
    reason: str

    @property
    def members(self) -> tuple:
        return tuple(sorted((self.left, self.right)))

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "members": list(self.members),
                "key": self.key, "reason": self.reason}


def _dates_agree(left: object, right: object) -> bool:
    """Do two tellings' bounds leave any date they could BOTH be?

    `chronology.dates_agree` is the one definition (v342), read here under the
    rungs' own name because every rung below asks the question in these words.
    An undated side agrees with everything — it is the whole reason these rungs
    exist, since the unplaced retelling is the one asking for a date.
    """
    return chrono.dates_agree(left, right)


def _placements_agree(left: "TellingView", right: "TellingView") -> bool:
    """Do the dates the FOLD already has these two tellings at leave a date
    they could both be (:data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`)?

    The same arithmetic as :func:`_dates_agree` over a different pair of
    intervals: a telling whose node the fold has not placed agrees with
    everything, and two placed nodes must intersect. Read TOGETHER with
    :func:`_dates_agree` rather than instead of it — a telling may state a date
    its node's group does not carry, and either contradiction is enough to
    refuse.
    """
    return _dates_agree(left.placed_bounds, right.placed_bounds)


def _same_people(left: frozenset, right: frozenset) -> bool:
    """Do two tellings name the same non-owner people?

    NESTED rather than equal, and non-empty on both sides. Nested because one
    telling says `isaac` and the next says `isaac saldana`, and a rule that
    demanded equality would call one person two. Non-empty because the empty
    set is every person at once: two tellings that name nobody but the owner
    have agreed about nothing (:data:`INDEPENDENT_SIGNALS`' own rule).
    """
    if not left or not right:
        return False
    return left <= right or right <= left


def derived_reading_links(views: Mapping[str, TellingView]) -> list:
    """:data:`RULE_ID_DERIVED_READING` — a reading of a node IS that node.

    One pass. Every telling that reads exactly one node is linked to every
    telling whose claims name that same node as their own event — and never to
    another reading, because two readings of one node are already linked to it
    and a third edge would say nothing new.
    """
    by_node: dict[str, list] = {}
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible or view.reads_node:
            continue
        for ref in sorted(view.node_refs):
            by_node.setdefault(ref, []).append(telling_ref)
    rows: list = []
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible or not view.reads_node:
            continue
        for other in by_node.get(view.reads_node, ()):  # already sorted
            rows.append(ExactLink(
                rule_id=RULE_ID_DERIVED_READING, left=telling_ref, right=other,
                key=view.reads_node,
                reason=(f"{telling_ref} is a derived reading of {view.reads_node}, "
                        f"which {other} tells"),
            ))
    return rows


#: v360 (owner, 2026-09-25), the right person. His message *"James, AJ, is nine years
#: younger than me … He was born 03/20/1990"* is his BROTHER's birth, told by
#: the name his son goes by; read through what he calls people it looked like
#: his son's, and it joined his son's 2013 birth through the undated "James
#: born" tellings. The roster knows both men's births. A birth telling whose own
#: stated date contradicts the roster birth of every person it resolves to is
#: not their birth when that date is ANOTHER roster person's birth: R2b never
#: links it as theirs, and a group of that birth never takes it in.
A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS = (
    "a birth telling whose own stated date contradicts the roster's birth of "
    "every person it resolves to and is another roster person's birth is not "
    "theirs: R2b never links it as theirs and a birth group never takes it in"
)


def births_dated_elsewhere(views: Mapping[str, TellingView], index: object) -> frozenset:
    """:data:`A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS` — the telling refs."""
    born = getattr(index, "born", None) or {}
    if not born:
        return frozenset()
    out: set[str] = set()
    for telling_ref, view in views.items():
        if view.bounds is None or milestone_of(view) != "birth":
            continue
        people = _roster_people(view)
        known = [born[ref] for ref in people if ref in born]
        if not known or len(known) != len(people) \
                or any(_dates_agree(view.bounds, record) for record in known):
            continue
        # Dated ELSEWHERE: the date is another roster person's birth. A date
        # that fits nobody is left to the ordinary rungs and the fold's card.
        if any(_dates_agree(view.bounds, record)
               for ref, record in born.items() if ref not in people):
            out.add(telling_ref)
    return frozenset(out)


def milestone_links(views: Mapping[str, TellingView], *,
                    not_theirs: object = frozenset()) -> list:
    """:data:`RULE_ID_MILESTONE` — one subject, one milestone, one episode.

    **v345** sweeps a second set of buckets beside the per-person ones
    (:data:`A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT`). A marriage is
    once per COUPLE (`identity_resolution.ONCE_PER_COUPLE_EVENT_KINDS`), so a
    telling whose SUBJECTS are one couple (`identity_resolution.couple_key`) is
    bucketed under that couple as well as under each of its words — which is how
    *"Mom married dad at 21"* (subject ``mother``) reaches *"Parents' wedding
    date"* (subject ``Author's parents``) at all. Inside a couple bucket
    :func:`_same_people` is not asked, because the bucket key has already
    asserted the stronger thing: the two tellings name the same two people, in
    two vocabularies for them. Every other guard is the per-person rung's own —
    compatible kinds, and dates that do not contradict.

    **v350** (:data:`A_COUPLE_IS_TWO_PEOPLE`) changed WHICH words the couple key
    is read from: the telling's own ``subject_mention`` texts rather than every
    person token anywhere in it. A telling has a couple when it is ABOUT one;
    *"Wedding reception in mother-in-law's backyard"* is about the owner, and
    under the old reading it was about his mother because that word is inside
    that one.
    """
    buckets: dict[tuple, list] = {}
    couples: dict[tuple, list] = {}
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible:
            continue
        milestone = milestone_of(view)
        if not milestone:
            continue
        if telling_ref in not_theirs:
            # :data:`A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS`.
            continue
        for token in sorted(view.people):
            buckets.setdefault((milestone, token), []).append(telling_ref)
        # :data:`A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE`: the couple key
        # is its own discriminator, and a telling naming no second person
        # token is still a telling about that couple.
        if milestone in ONCE_PER_COUPLE_EVENT_KINDS:
            key = couple_key(view.subject_mentions)
            if key:
                couples.setdefault((milestone, key), []).append(telling_ref)
    rows: list = []
    seen: set[tuple] = set()

    def _sweep(source: dict, *, by_couple: bool) -> None:
        for (milestone, token), refs in sorted(source.items()):
            for index, left in enumerate(refs):
                for right in refs[index + 1:]:
                    pair = (left, right)
                    if pair in seen:
                        continue
                    a, b = views[left], views[right]
                    if not by_couple and not _same_people(a.people, b.people):
                        continue
                    if not by_couple and _two_roster_people(a, b):
                        continue
                    if not kinds_compatible(a.event_kind, b.event_kind):
                        continue
                    if not _dates_agree(a.bounds, b.bounds):
                        continue
                    seen.add(pair)
                    rows.append(ExactLink(
                        rule_id=RULE_ID_MILESTONE, left=left, right=right,
                        key=f"{milestone}:{token}",
                        reason=((f"a {milestone} happens once to one couple, and "
                                 f"both tellings are {token.split(':')[-1]}'")
                                if by_couple else
                                (f"a {milestone} happens once to one person, and "
                                 f"both tellings are {token}'s")),
                    ))

    _sweep(buckets, by_couple=False)
    _sweep(couples, by_couple=True)
    return rows


#: v360 follow-up (owner, 2026-09-25) (item 4). Token nesting is how "Isaac" and
#: "Isaac Saldana" are one person; it is also how "Grandfather's death at 66"
#: (his grandfather, the roster's James Edwin Taylor Sr., plus a Beauchamp)
#: nested over "Father dies of COVID" (James Taylor) — {james, taylor} inside
#: {james, edwin, taylor, …} — and a grandfather's death joined his father's.
#: When both tellings resolve to ROSTER people and no roster person is shared,
#: they are two people's milestones, whatever their tokens share.
A_MILESTONE_NEVER_JOINS_TWO_ROSTER_PEOPLE = (
    "R2b never joins two tellings that each resolve to roster people and share "
    "none of them: a father's death and a grandfather's death are two deaths "
    "even when one name's words sit inside the other's"
)


#: v360 (owner, 2026-09-25), the right couple and the right person. The expansion
#: step (:func:`exact_identity_groups`) takes a group into WHOLE existing
#: episodes, and an episode an earlier rule over-merged took its mistake into
#: every group that touched it. The owner's rig, twice:
#:
#: * his PARENTS' wedding (1976-06-25, "Mom married dad at 21", the family
#:   landmark "Parents' wedding") had been bound, before v350, beside his own
#:   "Wedding reception in mother-in-law's backyard"; the cornerstones rule
#:   then joined that reception to his wedding and the expansion carried his
#:   parents in with it, so his wedding read "11 January 2007 and 25 June 1976";
#: * "Charlee and James arrive" (his children, 2010-12-21 to 2013-05-10) sat in
#:   one episode with his brother AJ's roster birth, 1990-03-20.
#:
#: A group of one milestone takes an existing episode's member in only when that
#: member could be the same milestone of the same people: a member telling the
#: same milestone of ANOTHER couple (its own subjects' couple key) or of other
#: roster people (none shared) stays where it is. A group that declined a member
#: of the episode it sits in is filed as its own create, so the right tellings
#: leave; the episode keeps its id and its other members, and is never
#: redirected at the group that left it. When two such groups divide one
#: episode, the one holding most of it is the one that stays.
A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE = (
    "a group of one milestone takes an existing episode's member in only when "
    "it could be that milestone of the same people: a member telling it of "
    "another couple or of other roster people stays where it is, the group "
    "that declined it leaves as its own create, and the episode it left keeps "
    "its id and is never redirected at it"
)


def _group_identity(tellings: set, views: Mapping[str, "TellingView"]) -> tuple:
    """``(milestone, couples, roster people)`` a group's own tellings name, or
    ``("", …)`` when they name no single milestone
    (:data:`A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`)."""
    milestones: set[str] = set()
    couples: set[str] = set()
    people: set[str] = set()
    for ref in tellings:
        view = views.get(ref)
        if view is None:
            continue
        milestone = milestone_of(view)
        if milestone:
            milestones.add(milestone)
            if milestone in ONCE_PER_COUPLE_EVENT_KINDS:
                key = couple_key(view.subject_mentions)
                if key:
                    couples.add(key)
        people |= _roster_people(view)
    if len(milestones) != 1:
        return "", frozenset(), frozenset()
    return next(iter(milestones)), frozenset(couples), frozenset(people)


def _another_couples_milestone(view: "TellingView", identity: tuple) -> bool:
    """Is this episode member the group's milestone of somebody else?"""
    milestone, couples, people = identity
    if not milestone or view is None or milestone_of(view) != milestone:
        return False
    if milestone in ONCE_PER_COUPLE_EVENT_KINDS and couples:
        key = couple_key(view.subject_mentions)
        if key and key not in couples:
            return True
    # Another person, or somebody besides the group's people
    # (:data:`A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE`).
    theirs = _roster_people(view)
    return bool(people) and bool(theirs) and not (theirs <= people)


def _roster_people(view: "TellingView") -> frozenset:
    return frozenset(ref for ref in (view.entities | view.subject_entities)
                     if collapsed_text(ref).startswith(PERSON_ENTITY_PREFIX))


def _two_roster_people(left: "TellingView", right: "TellingView") -> bool:
    """:data:`A_MILESTONE_NEVER_JOINS_TWO_ROSTER_PEOPLE`, and
    :data:`A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE`."""
    a, b = _roster_people(left), _roster_people(right)
    if not a or not b:
        return False
    if not (a & b):
        return True
    return a != b and max(len(a), len(b)) > 1


#: v360 (owner, 2026-09-25), the right person. A telling that resolves to SEVERAL
#: roster people is not one person's milestone: the owner's message "AJ Taylor"
#: (subjects AJ, James, "my dad", "around 1990") named his brother, his son and
#: his father at once, and once a bare "James" read as his son it linked his
#: brother's birth to his son's and his father's 1954 birth to his brother's.
#: The per-person R2b rung joins such a telling only to one naming the same
#: people.
A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE = (
    "R2b joins a telling that resolves to several roster people only to a "
    "telling that resolves to the same people: a birth told about a brother, "
    "a son and a father at once is none of their births alone"
)


def same_label_links(views: Mapping[str, TellingView]) -> list:
    """:data:`RULE_ID_SAME_LABEL` — the same words, about the same people.

    Three guards keep this off a coincidence, and the first one is the one the
    founder vault taught:

    * **a bucket holding ONE repeatable-kind telling is refused whole.** Not
      "the repeatable telling is skipped" — skipping it is how three classifier
      tellings labelled "Joined Ridgeline", all carrying the `moment` wildcard,
      became one episode while the landmark telling beside them said `job` and
      a life may hold two stints at one employer. What makes the FACT
      repeatable is the strongest kind anybody gave it, so the veto is the
      bucket's and not the row's.
    * **both sides must name the same non-owner person, non-emptily.** An
      identical label about nobody in particular is a coincidence waiting to
      happen — "Christmas morning" is every Christmas morning — and the people
      are what make it one fact.
    * a label of one significant token is not an identity, so both sides carry
      at least :data:`RESTATEMENT_MIN_TOKENS` minus one, and the dates must not
      contradict — neither the dates the tellings THEMSELVES state nor the dates
      the fold already has them at
      (:data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`, v340).
    """
    buckets: dict[str, list] = {}
    repeatable: set[str] = set()
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible:
            continue
        key = normalized_mention_key(view.label)
        if not key:
            continue
        if is_repeatable(view.event_kind):
            repeatable.add(key)
            continue
        if len(view.tokens) < RESTATEMENT_MIN_TOKENS - 1 or not view.people:
            continue
        buckets.setdefault(key, []).append(telling_ref)
    rows: list = []
    for key, refs in sorted(buckets.items()):
        if len(refs) < 2 or key in repeatable:
            continue
        for index, left in enumerate(refs):
            for right in refs[index + 1:]:
                a, b = views[left], views[right]
                if not kinds_compatible(a.event_kind, b.event_kind):
                    continue
                if not _dates_agree(a.bounds, b.bounds) or _milestone_conflict(a, b):
                    continue
                if not _placements_agree(a, b):
                    continue
                if not _same_people(a.people, b.people):
                    continue
                rows.append(ExactLink(
                    rule_id=RULE_ID_SAME_LABEL, left=left, right=right, key=key,
                    reason=f"both tellings are labelled {a.label!r}",
                ))
    return rows


def restatement_links(views: Mapping[str, TellingView], *, index: object = None) -> list:  # noqa: ARG001
    """:data:`RULE_ID_RESTATEMENT` — one moment said again in other words.

    The rung the owner's seven "Isaac's first check" nodes need, and the only
    one in the family whose key is not the whole identity — so it is the one
    with the most guards:

    * the bucket is a PERSON this telling names (:func:`person_tokens`), never a
      bare word, so `check` and `first` cannot make a bucket and a sweep stays
      bounded — and never the roster alone, which on the owner's vault has never
      heard of Isaac;
    * a bucket over :data:`RESTATEMENT_BUCKET_CAP` is skipped entirely — a name
      in hundreds of labels is a life's centre of gravity, not a discriminator;
    * both sides carry at least :data:`RESTATEMENT_MIN_TOKENS` significant
      tokens and SHARE at least :data:`RESTATEMENT_SHARED_TOKENS` of them, one
      of which must be the bucket's own entity token;
    * the people agree, the kinds are in one family, no repeatable kind takes
      part, and the dates do not contradict — the stated ones and the placed
      ones both (:data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`, v340).
    """
    buckets: dict[str, list] = {}
    repeatable: set[str] = set()
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not view.eligible:
            continue
        if is_repeatable(view.event_kind):
            # :func:`same_label_links`' first guard, for the same reason: the
            # strongest kind anybody gave a name is what makes it repeatable.
            repeatable.update(view.people)
            continue
        if len(view.tokens) < RESTATEMENT_MIN_TOKENS or not view.people:
            continue
        for token in sorted(view.people):
            buckets.setdefault(token, []).append(telling_ref)
    rows: list = []
    seen: set[tuple] = set()
    for token, refs in sorted(buckets.items()):
        if len(refs) < 2 or len(refs) > RESTATEMENT_BUCKET_CAP or token in repeatable:
            continue
        for position, left in enumerate(refs):
            for right in refs[position + 1:]:
                pair = (left, right)
                if pair in seen:
                    continue
                a, b = views[left], views[right]
                shared = a.tokens & b.tokens
                if token not in shared or len(shared) < RESTATEMENT_SHARED_TOKENS:
                    continue
                # At least one shared token must be something OTHER than a
                # name. Three tokens of one person's name are three tokens of
                # one person, not one moment — that is how "Grandpa James Edwin
                # Taylor Sr.'s death" and "James Edwin Taylor Sr's birth" met.
                if not shared - (a.people | b.people):
                    continue
                if not kinds_compatible(a.event_kind, b.event_kind):
                    continue
                if not _dates_agree(a.bounds, b.bounds) or _milestone_conflict(a, b):
                    continue
                if not _placements_agree(a, b):
                    continue
                if not _same_people(a.people, b.people):
                    continue
                seen.add(pair)
                rows.append(ExactLink(
                    rule_id=RULE_ID_RESTATEMENT, left=left, right=right,
                    key="+".join(sorted(shared)),
                    reason=(f"{a.label!r} and {b.label!r} share "
                            f"{', '.join(sorted(shared))}"),
                ))
    return rows


def exact_identity_links(views: Mapping[str, TellingView], *,
                         entity_index: object = None) -> list:
    """Every R2 link, every rung, in :data:`EXACT_IDENTITY_RULE_IDS` order."""
    return [
        *derived_reading_links(views),
        *milestone_links(views, not_theirs=births_dated_elsewhere(views, entity_index)),
        *same_label_links(views),
        *restatement_links(views, index=entity_index),
    ]


def link_refusal(link: ExactLink, units: Mapping[str, Candidate], *,
                 active: Mapping[str, tuple], entailed: Sequence[tuple]) -> str:
    """Why this link may not be filed, or ``""``.

    Two refusals and both are the ones R1 already obeys, read here for a pair
    of TELLINGS rather than for a telling and a candidate:

    * a `not_same` the person filed, or one C3 entails from one they filed —
      so a human `Different` still wins over every rung in this family;
    * G1: a deterministic rule may file proposals against an episode a person
      adopted or made, and may never move it (:data:`CLUSTER_RULE_TEXT`).
    """
    pairs = {tuple(sorted(pair)) for pair in entailed or ()}
    if link.members in pairs:
        return "the person already said these are different things"
    for this, other in ((link.left, link.right), (link.right, link.left)):
        other_unit = units.get(unit_of(other, units))
        for row in active.get(this) or ():
            if collapsed_text(row.get("relation")) != "not_same":
                continue
            if other_unit is not None and \
                    collapsed_text(row.get("episode_id")) == other_unit.episode_id:
                return "the person already said these are different things"
    for ref in link.members:
        unit = units.get(unit_of(ref, units))
        if unit is not None and not _growable(unit):
            return (f"{unit.episode_id} was adopted or made by a person; a "
                    f"deterministic rung may not move it")
    return ""


def exact_identity_groups(links: Sequence[ExactLink], views: Mapping[str, TellingView],
                          units: Mapping[str, Candidate], *,
                          active: Mapping[str, tuple], entailed: Sequence[tuple],
                          refused: list | None = None,
                          not_theirs: object = frozenset()) -> list:
    """The groups the accepted links make — and the shape is the whole rule.

    R1 refuses to group at all (:data:`NON_TRANSITIVE_RULE_TEXT`) because a
    third telling choosing the same candidate is, in a similarity score,
    evidence of ambiguity. This family groups, but not by transitivity, and the
    clone is what settled the difference between the two:

    * :data:`RULE_ID_DERIVED_READING` chains FREELY. It is arithmetic — a
      reading names exactly one node — so a reading, the telling of that node
      and that node's other readings are one thing by construction, and nothing
      a later rung does may take a reading away from the node it read.
    * every other rung must form a CLIQUE. A component would chain: on the
      owner's vault `R2b` linked "Harvey's birth as turning point" to "Orion's
      birth in Redlands" through tellings that shared one name token each, and
      the transitive closure was 104 tellings — four people's births and two
      towns — in one episode. A clique says every member named every other
      member, which is the non-transitivity doctrine kept at group scale, and it
      cut that 104 back to the births it is actually about.

    The cliques are grown greedily over the tellings in sorted order, so one run
    twice gives one answer; a telling belongs to at most one group.
    """
    kept: list = []
    for link in links:
        why = link_refusal(link, units, active=active, entailed=entailed)
        if why:
            if refused is not None:
                refused.append({**link.as_dict(), "refused": why})
            continue
        kept.append(link)

    readings: dict[str, set] = {}
    neighbours: dict[str, set] = {}
    rule_of: dict[tuple, set] = {}
    reason_of: dict[tuple, str] = {}
    for link in kept:
        pair = link.members
        rule_of.setdefault(pair, set()).add(link.rule_id)
        reason_of.setdefault(pair, link.reason)
        if link.rule_id == RULE_ID_DERIVED_READING:
            readings.setdefault(link.left, set()).add(link.right)
            readings.setdefault(link.right, set()).add(link.left)
        else:
            neighbours.setdefault(link.left, set()).add(link.right)
            neighbours.setdefault(link.right, set()).add(link.left)

    # --- R2a first, and absolutely: the reading components -----------------
    parent: dict[str, str] = {}

    def find(ref: str) -> str:
        parent.setdefault(ref, ref)
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    for ref, others in readings.items():
        for other in others:
            left, right = find(ref), find(other)
            if left != right:
                parent[left] = right
    reading_group: dict[str, set] = {}
    for ref in sorted(parent):
        reading_group.setdefault(find(ref), set()).add(ref)

    # --- then the cliques, over the tellings that are not readings ---------
    taken: set[str] = set()
    cliques: list = []
    for telling_ref in sorted(neighbours):
        if telling_ref in taken or views.get(telling_ref) is None:
            continue
        clique = {telling_ref}
        for other in sorted(neighbours[telling_ref]):
            if other in taken or views.get(other) is None:
                continue
            if all(other in neighbours.get(member, ()) for member in clique):
                clique.add(other)
        if len(clique) < 2:
            continue
        taken |= clique
        cliques.append(clique)

    # --- one group per clique, plus every reading of every member ----------
    groups_by_member: list = []
    placed: set[str] = set()
    for clique in cliques:
        members = set(clique)
        for ref in clique:
            members |= reading_group.get(find(ref), set()) if ref in parent else set()
        groups_by_member.append(members)
        placed |= members
    for root in sorted(reading_group):
        rows = reading_group[root]
        if rows & placed:
            continue
        groups_by_member.append(set(rows))
        placed |= rows

    # --- expand each group to whole EXISTING episodes, then coalesce -------
    # Expansion is :data:`CLUSTER_RULE_TEXT`'s: the deterministic act is one
    # `create` over the whole cluster, so a group that takes in one member of an
    # episode takes in all of it or it orphans the rest.
    #
    # Coalescing is what the clone taught. Two cliques that expand into ONE
    # existing episode are two creates naming one telling, and the fold refuses
    # that by name — `identity_conflict: carries 2 active same bindings`. They
    # are merged instead, and that is not the transitivity this function
    # otherwise refuses: what joins them is an episode SOMEBODY ALREADY DECIDED,
    # so the merge grows one existing decision rather than inventing a new one.
    #
    # :data:`A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`: a member of an
    # existing episode that tells the group's milestone of somebody else is
    # DECLINED — left where it is, with its readings.
    expanded: list = []
    for tellings in groups_by_member:
        members = set(tellings)
        declined: set[str] = set()
        identity = _group_identity(tellings, views)
        for ref in tellings:
            unit = units.get(unit_of(ref, units))
            if unit is None:
                continue
            for member in unit.members:
                if member in tellings:
                    continue
                if _another_couples_milestone(views.get(member), identity) or (
                        member in not_theirs and identity[0] == "birth"):
                    declined.add(member)
                    declined |= reading_group.get(find(member), set()) if member in parent else set()
                else:
                    members.add(member)
        members -= declined - set(tellings)
        if len(members) >= 2:
            expanded.append((set(tellings), members, declined - members))
    coalesced: list = []
    for tellings, members, declined in expanded:
        for position, (other_tellings, other_members, other_declined) in enumerate(coalesced):
            if members & other_members:
                coalesced[position] = (other_tellings | tellings, other_members | members,
                                       (other_declined | declined) - (other_members | members))
                break
        else:
            coalesced.append((tellings, members, declined))
    merged = True
    while merged:
        merged = False
        for left in range(len(coalesced)):
            for right in range(left + 1, len(coalesced)):
                if coalesced[left][1] & coalesced[right][1]:
                    union = coalesced[left][1] | coalesced[right][1]
                    coalesced[left] = (coalesced[left][0] | coalesced[right][0], union,
                                       (coalesced[left][2] | coalesced[right][2]) - union)
                    del coalesced[right]
                    merged = True
                    break
            if merged:
                break

    def _episode(ref: str) -> str:
        return collapsed_text((efc.grouping_binding(ref, active) or {}).get("episode_id"))

    # Which group STAYS in an episode several groups divide: the one holding
    # most of it (then the first in member order). It is the only one that may
    # be skipped as already filed; every other group that declined a member of
    # its own episode leaves it as a create.
    share: dict[str, list] = {}
    for position, (_tellings, members, declined) in enumerate(coalesced):
        for episode_id in {_episode(ref) for ref in members | declined} - {""}:
            count = sum(1 for ref in members if _episode(ref) == episode_id)
            share.setdefault(episode_id, []).append((-count, tuple(sorted(members)), position))
    stays = {episode_id: min(rows)[2] for episode_id, rows in share.items()}

    groups: list = []
    for position, (tellings, members, declined) in enumerate(coalesced):
        # CONVERGENCE. A group whose every member already sits in ONE episode is
        # a decision this family has already filed, and re-filing it is not a
        # no-op: the first create superseded each member's previous binding and
        # the second would find nothing to supersede, so the two records differ
        # by `supersedes` — which IS in the binding digest — and the fold refuses
        # the pair by name (`identity_conflict: … asserted by 2 active records`).
        # The clone earned this line the hard way, on the second leg of a run.
        episodes = {_episode(ref) for ref in members}
        left_behind = {_episode(ref) for ref in declined} - {""}
        if len(episodes) == 1 and "" not in episodes:
            episode_id = next(iter(episodes))
            if episode_id not in left_behind:
                continue
            # A group that declined a member of its own episode is already
            # filed only when it is the group that stays there and every member
            # it declined is leaving with another group this run.
            others = {ref for index, (_t, other, _d) in enumerate(coalesced)
                      if index != position for ref in other}
            if stays.get(episode_id) == position and \
                    all(ref in others for ref in declined if _episode(ref) == episode_id):
                continue
        rules: set[str] = set()
        reasons: list[str] = []
        for pair, ids in rule_of.items():
            if set(pair) <= set(tellings):
                rules |= ids
                reasons.append(reason_of[pair])
        row = {
            "members": tuple(sorted(members)),
            "tellings": tuple(sorted(tellings)),
            "rule_ids": tuple(rule for rule in EXACT_IDENTITY_RULE_IDS if rule in rules),
            "reasons": tuple(sorted(set(reasons)))[:4],
        }
        if left_behind:
            # :data:`A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`: the
            # episodes this group leaves members in keep their ids, so the
            # create never names them in `aliases_created`.
            row["declined"] = tuple(sorted(declined))
            row["keeps_episodes"] = tuple(sorted(left_behind))
        groups.append(row)
    groups.sort(key=lambda row: row["members"])
    return groups


def group_envelope(group: Mapping[str, object], *, views: Mapping[str, TellingView],
                   active: Mapping[str, tuple], now: object = None) -> dict:
    """The one `create` an R2 component becomes.

    :func:`create_envelope`'s arithmetic, over an explicit member set instead of
    over one pair: the operation id digests the members and nothing else, and
    every episode the create retires is named in ``aliases_created``.

    Every byte of it is a function of the MEMBER SET — including the rule id
    (:data:`RULE_ID_EXACT`) and the evidence quotes — so two callers that agree
    about the members file the same record and the second one keeps the first's
    bytes rather than promising records the vault holds under other ones.
    """
    members = tuple(group["members"])  # type: ignore[arg-type]
    rule_ids = tuple(group.get("rule_ids") or ())  # type: ignore[union-attr]
    rule_id = RULE_ID_EXACT
    # :data:`A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`: a group that
    # leaves an episode names it as the episode it acted on. Without it a
    # carve-out whose members are exactly an episode an earlier create made
    # and a later one absorbed (his parents' wedding, on the owner's rig)
    # digests to THAT old operation, and the store keeps the old record's
    # bindings under the new one's name — `identity_envelope_incomplete`.
    kept = {collapsed_text(value) for value in group.get("keeps_episodes") or ()} - {""}
    operation_id = ei.operation_digest(
        authority="deterministic", op="create", rule_version=RULE_VERSION,
        member_refs=list(members), acted_on_episode_ids=sorted(kept),
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
            if previous not in kept:
                # :data:`A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`: an
                # episode that keeps members is still drawn, at its own id.
                aliases.add(previous)

    reasons = list(group.get("reasons") or ())  # type: ignore[union-attr]
    # Member-determined, every one of them (:data:`RULE_ID_EXACT`).
    anchor = next((views[ref].label for ref in members
                   if ref in views and views[ref].label), "")
    bindings = []
    for telling_ref in members:
        row = views.get(telling_ref)
        bindings.append({
            "telling_ref": telling_ref,
            "episode_id": episode_id,
            "relation": efc.GROUPING_RELATION,
            "origin": "deterministic",
            "rule_version": RULE_VERSION,
            "rule_id": rule_id,
            "operation_id": operation_id,
            # Empty, and member-determined like everything else here: the
            # episodes this create retires are named on the OPERATION, in
            # `aliases_created`, and naming them a second time on each binding
            # would make a re-run's bytes depend on what the last run left.
            "candidates": [],
            "evidence": {
                "telling_quote": row.label if row else "",
                "episode_quote": anchor,
                "signals": [],
            },
            "created_at": now,
        })
    binding_ids = [ei.validate_event_identity(row)["identity_id"] for row in bindings]
    for position, telling_ref in enumerate(members):
        if telling_ref in superseded:
            bindings[position]["supersedes"] = superseded[telling_ref]
            binding_ids[position] = ei.validate_event_identity(bindings[position])["identity_id"]
    kinds = {views[ref].event_kind for ref in members if ref in views} - {""}
    dated = sorted(ref for ref in members
                   if ref in views and views[ref].dated and views[ref].event_kind)
    canonical = ""
    for ref in dated:
        if views[ref].event_kind != KIND_WILDCARD:
            canonical = views[ref].event_kind
            break
    if not canonical:
        for kind in KIND_PRECEDENCE:
            if kind in kinds:
                canonical = kind
                break
    operation = {
        "authority": "deterministic",
        "op": "create",
        "episode_id": episode_id,
        "acted_on_episode_ids": sorted(kept),
        "members": list(members),
        "creates_binding_ids": binding_ids,
        "supersedes_binding_ids": sorted(superseded.values()),
        "aliases_created": sorted(aliases),
        "canonical_event_kind": canonical or (min(kinds) if kinds else KIND_WILDCARD),
        "rule_version": RULE_VERSION,
        "created_at": now,
    }
    return {
        "operation": ei.validate_episode_operation(operation),
        "bindings": [ei.validate_event_identity(row) for row in bindings],
        "pair": "+".join(rule_ids) or RULE_ID,
        "rule_ids": list(rule_ids),
        "reasons": reasons,
    }



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
         entity_index: object = None, question_contexts: object = None,
         containment_authority: object = None, landmark_entries: object = (),
         placed_windows: object = None, now: object = None) -> BinderPlan:
    """One binder run, decided and not written. Pure.

    Deterministic end to end: tellings are swept in sorted order, candidates
    in sorted order, and every id in the result is a digest over semantic
    inputs. Run it twice on the same inputs and the two plans are equal.

    **I2b's three new arguments**, all inputs and none of them reads:
    ``entity_index`` is the vault's rosters (§12b ruling 1);
    ``question_contexts`` is ``{telling_ref: container the session targeted}``,
    the recorder's own stamp (§12b ruling 5); ``containment_authority`` is the
    HOST's flag (§12b ruling 6) and chooses one field — ``origin`` — on the
    records the containment rung mints, and nothing else about them.

    ``placed_windows`` (v340) is where the timeline already has each telling,
    keyed by telling ref — :func:`placed_windows_of`, supplied by
    :func:`read_vault_inputs` over the published generation and the fold's own
    derivation — and it is what keeps `R2c`/`R2d` off a merge that would move a
    dated moment (:data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`).
    """
    authority = collapsed_text(containment_authority) or ec.DEFAULT_CONTAINMENT_AUTHORITY
    # Refuse an unknown flag HERE, before a whole run is decided against it.
    efc.containment_origin(authority)
    views = telling_views(
        claims, manifest=manifest, era_memberships=era_memberships,
        entity_index=entity_index,
        participation_kinds=lp.participation_kinds_by_telling(landmark_entries),
        placed_windows=placed_windows,
        landmark_entries=landmark_entries,
    )
    units = candidates(views, episode_records=episode_records)
    records = ef.normalize_episode_records(episode_records)
    active = efc.active_binding_index(records["bindings"])
    entailed = efc.entailed_not_same(records["bindings"])

    result = BinderPlan(views=views, containment_authority=authority)
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

    # --- v333: the R2 family, AFTER R1 and before the pairs collapse -------
    # After R1 on purpose. R1's own binds are the narrow, scored ones and they
    # are accepted first; the exact rungs then run over the SAME views and the
    # same active bindings, and a member R1 just moved is already inside the
    # unit these rungs expand to — so the two families cannot file two creates
    # for one telling. A component that overlaps a member R1 accepted this run
    # is skipped rather than merged, because R1's envelope already named that
    # member and a second create would supersede a binding written in the same
    # breath (:data:`EXACT_IDENTITY_RULE_TEXT`).
    result.exact_links = exact_identity_links(views, entity_index=entity_index)
    result.exact_refused = []
    result.exact_groups = [
        group for group in exact_identity_groups(
            result.exact_links, views, units, active=active, entailed=entailed,
            refused=result.exact_refused,
            not_theirs=births_dated_elsewhere(views, entity_index),
        )
        if not (set(group["members"]) & {ref for members in accepted for ref in members})
    ]
    for group in result.exact_groups:
        result.exact_envelopes.append(
            group_envelope(group, views=views, active=active, now=now))

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

    # --- I2b: the containment rung (§12b rulings 2 and 5) -----------------
    # AFTER the binds are accepted, and skipping every unit this run is about
    # to change (:data:`episode_containers.CONTAINER_SKIPPED_WHILE_BINDING`):
    # a container's id is minted from what it IS, so filing containment against
    # a unit whose identity moves in the same run would orphan the records the
    # same run wrote.
    moving = {ref for members in accepted for ref in members}
    # v333: and every telling the R2 family is about to move, for the same
    # reason — a container id minted from a unit whose identity moves in the
    # same run would orphan the records this run wrote.
    moving |= {ref for group in result.exact_groups for ref in group["members"]}
    result.containers = ec.containers(views, units, excluded_refs=moving,
                                      entity_index=entity_index)
    result.containment_ambiguities = []
    result.containment_negatives = []
    containment = ec.containment_rows(
        views, result.containers, question_contexts=question_contexts,
        ambiguities=result.containment_ambiguities,
        # §4.1 condition 6 (E-L2b / H5): a pair a person has decided is the
        # rung's own refusal, read from the durable records rather than left
        # to the I3c filter below — which drops a pair for a different reason
        # (it already carries a binding) and would keep dropping it only for
        # as long as that reason happens to coincide with this one.
        decided_pairs=ec.human_decided_pairs(records["bindings"]),
        negatives=result.containment_negatives,
    )
    # I3c: a telling this run already carries ANY active binding for (event
    # identity's own docstring: "never placed inside a container it is
    # already a member of" — but the ORIGINAL filter only excluded a
    # container's own opened-by/key telling, not an arbitrary EXISTING
    # decision). Read from `active` — the same properly-collapsed view R1
    # itself reads, never a raw scan — so a telling a person already
    # confirmed `same` (or `part_of`, `related`, `not_same`) to this EXACT
    # episode never gets a second, disagreeing containment proposal minted
    # on top of it. Without this, a SECOND `bind-episodes --apply` after a
    # confirmed answer re-proposes `part_of` over the person's own `same`
    # and the next fold refuses: `identity_conflict`.
    #
    # The filtered rows are KEPT, not discarded: exactly one of them is not a
    # disagreeing second proposal but THIS rung's own record from an earlier
    # run, filed at the other authority under the same `identity_id`
    # (`episode_containers.containment_authority_moves`). Telling those two
    # apart is what makes `--containment-authority applied` mean something on a
    # vault that already ran at `proposed`; every other filtered row is
    # filtered exactly as I3c filtered it.
    fresh, already_bound = [], []
    for row in containment:
        episodes = {b.get("episode_id") for b in active.get(row["telling_ref"], ())}
        (already_bound if row["episode_id"] in episodes else fresh).append(row)
    containment = fresh
    result.containment_diagnostics = ec.unresolved_question_contexts(
        views, result.containers, question_contexts=question_contexts,
    )
    result.containments = ec.group_by_container(
        containment, result.containers, authority=authority,
    )
    # ONE record per pair. The rung and I2's language rung share an
    # `identity_id` by construction, so the merge is a decision made once and
    # in the open rather than by whichever writer ran first.
    result.proposals = ec.merge_containment_records([
        *result.proposals,
        *[ec.containment_record(row, result.containers[row["container_key"]],
                                views[row["telling_ref"]], authority=authority, now=now)
          for row in containment],
    ])
    # The authority flag's own two lists. A record this run is about to FILE is
    # never also a record it is about to upgrade — the language rung deliberately
    # mints `proposed` whatever the flag says (:func:`part_of_proposal`), and
    # upgrading its record here would overrule that with a flag it does not read.
    filing = {row["identity_id"] for row in result.proposals}
    upgrades, kept_stronger = ec.containment_authority_moves(
        already_bound, result.containers, views,
        active=active, authority=authority, now=now,
    )
    result.containment_upgrades = [row for row in upgrades
                                   if row["identity_id"] not in filing]
    result.containment_kept_stronger = [row for row in kept_stronger
                                        if row not in filing]

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


def exact_identity_counts(result: BinderPlan) -> dict:
    """The R2 family's own tally: links per rung, components, tellings, refusals."""
    by_rule: dict[str, int] = {rule: 0 for rule in EXACT_IDENTITY_RULE_IDS}
    for link in result.exact_links:
        by_rule[link.rule_id] = by_rule.get(link.rule_id, 0) + 1
    groups_by_rule: dict[str, int] = {rule: 0 for rule in EXACT_IDENTITY_RULE_IDS}
    for group in result.exact_groups:
        for rule in group["rule_ids"]:
            groups_by_rule[rule] = groups_by_rule.get(rule, 0) + 1
    return {
        "links_by_rule": by_rule,
        "groups": len(result.exact_groups),
        "groups_by_rule": groups_by_rule,
        "tellings": sum(len(group["members"]) for group in result.exact_groups),
        "episodes": len(result.exact_envelopes),
        "refused": len(result.exact_refused),
        "largest_group": max((len(group["members"]) for group in result.exact_groups),
                             default=0),
    }


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
        # I2b. Named for what each one COUNTS, the same discipline #300 forced
        # on `proposal_pairs`: how many stretches the person's own words open
        # and this run could name, how many placements the rung made, how many
        # tellings that is, and how many stamps named nothing.
        "containers": len(result.containers),
        "containment_members": sum(int(block["member_count"])
                                   for block in result.containments),
        "containment_tellings": len({
            member["telling_ref"] for block in result.containments
            for member in block["members"]
        }),
        "containment_by_rule": {
            name: sum(1 for block in result.containments
                      for member in block["members"] if member["rule_id"] == name)
            for name in ec.DETERMINISTIC_CONTAINMENT_RULE_IDS
        },
        "containment_authority": result.containment_authority,
        # The authority flag's own two numbers. `containment_members` counts
        # what the rung PLACED this run; these count what an earlier run
        # placed and this flag re-routes — or declines to.
        "containment_upgrades": len(result.containment_upgrades),
        "containment_kept_stronger": len(result.containment_kept_stronger),
        "unresolved_question_contexts": len(result.containment_diagnostics),
        "containment_ambiguities": len(result.containment_ambiguities),
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
        # v333: the R2 family's own tally, kept apart from R1's so "which
        # family bound this" is answerable off the summary alone.
        "exact_identity": exact_identity_counts(result),
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
    lines.extend(ec.describe_containments(
        result.containments, authority=result.containment_authority,
    ))
    for row in result.containment_diagnostics:
        lines.append(f"  ⚠ {row['finding']}: {row['telling_ref']} → {row['stamp']}")
    # The authority flag's own two lists, printed rather than left to the
    # counts: "0 members placed" over a vault whose containments were all
    # filed last week is the sentence this whole path exists to stop being
    # the only thing a run says.
    for row in result.containment_upgrades:
        lines.append(f"  ↑ upgrade to deterministic: {row['identity_id']} "
                     f"({row['telling_ref']} ⊂ {row['episode_id']})")
    for identity_id in result.containment_kept_stronger:
        lines.append(f"  = kept at deterministic (this run is `proposed`): {identity_id}")
    lines.append("")
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
                "when_items_that_would_disappear",
                "containers", "containment_members", "containment_tellings",
                "containment_authority", "containment_upgrades",
                "containment_kept_stronger", "unresolved_question_contexts"):
        lines.append(f"  {key}: {counts.get(key)}")
    lines.append("  containment_by_rule: " + ", ".join(
        f"{name}={counts.get('containment_by_rule', {}).get(name, 0)}"
        for name in ec.DETERMINISTIC_CONTAINMENT_RULE_IDS
    ))
    exact = counts.get("exact_identity") or {}
    lines.append("  exact_identity links: " + ", ".join(
        f"{name}={(exact.get('links_by_rule') or {}).get(name, 0)}"
        for name in EXACT_IDENTITY_RULE_IDS
    ))
    lines.append(f"  exact_identity groups: {exact.get('groups', 0)} over "
                 f"{exact.get('tellings', 0)} tellings "
                 f"(largest {exact.get('largest_group', 0)}, "
                 f"refused {exact.get('refused', 0)})")
    for group in result.exact_groups:
        lines.append("  + one episode by " + "/".join(group["rule_ids"]) + ": "
                     + ", ".join(group["members"]))
        for reason in group["reasons"]:
            lines.append(f"      because {reason}")
    for row in result.exact_refused:
        lines.append(f"  - {row['rule_id']} declined {', '.join(row['members'])}: "
                     f"{row['refused']}")
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


# --------------------------------------------------------------------------
# v348 — nothing to bind costs nothing
# --------------------------------------------------------------------------

#: `read_vault_inputs`' one `fold_derivation` plus `plan()`'s R1/R2 candidate
#: search over every telling is the honest cost of BINDING something
#: (`FRAMES_COME_FROM_THE_FOLD`). It is not the honest cost of confirming
#: there is nothing to bind. On the owner's vault (~2000 claims, ~1190
#: nodes) that confirmation ALONE — `bind-episodes --apply` immediately
#: after a full sweep had already applied everything — measured 187s wall on
#: a fast Mac and 300-450s on the hosted 2-vCPU worker (2026-09-24). Every
#: timeline answer rides a file-claims job that runs this binder, so ten
#: answers cost ten full derivations serialized through one vault lease.
#:
#: THE RULE: a pass whose CHEAP signature — the telling manifest's own
#: digest, the bindings store's own digest, the landmark sources' own digest
#: (measured on the rig: `go-dig-import --apply` files a landmark record
#: WITHOUT touching a claim, a binding, the active index or the telling
#: manifest, so a signature without it would fast-path past a landmark that
#: really did change what a telling's containment rung would decide), this
#: module's `RULE_VERSION` and `temporal_timeline.CALCULATION_RULE_VERSION`
#: — matches the receipt left by the last successful `--apply` does NO
#: derivation at all: no `fold_derivation`, no `plan()`. It returns that
#: apply's own summary, read back, with `applied: False, reason:
#: "nothing_new"`. Any difference — a new or changed telling, a changed
#: binding, a changed landmark record, a moved rule version, or no receipt
#: at all — is the full pass, exactly as before it existed.
#:
#: Deliberately NOT built here: restricting the R2a-R2d candidate search to
#: only the NEW tellings and reusing a cached fold derivation for everything
#: else. That would need the fold's own candidate retrieval
#: (:func:`retrieve`, :func:`independent_signals`, the containment rung) to
#: be provably indifferent to which OTHER tellings are in scope when it
#: judges one pair — a claim this module is not in a position to prove for
#: every rung without risking exactly the silent-loss class v340 and v342
#: exist to refuse. The full pass is the honest fallback for anything short
#: of "nothing changed at all", and it is what a NEW telling still gets.
NOTHING_TO_BIND_COSTS_NOTHING = (
    "a binder pass whose cheap signature (the telling manifest's digest, the "
    "bindings store's digest, the landmark sources' digest, RULE_VERSION and "
    "temporal_timeline.CALCULATION_RULE_VERSION) matches the receipt left by "
    "the last successful --apply does no derivation at all — no "
    "fold_derivation, no plan() — and returns that apply's own summary with "
    "applied: False, reason: \"nothing_new\"; any difference (a new or "
    "changed telling, a changed binding, a changed landmark record, a moved "
    "rule version, or no receipt) is the full pass, exactly as before"
)

#: `state/temporal_claims/binder_receipt.json` — beside the bindings store
#: and `event_identity.TELLING_MANIFEST_FILE`. A PROJECTION of the last
#: successful `--apply`, never evidence: delete it and the next pass simply
#: pays the full cost once, the same as a vault that has never applied.
BINDER_RECEIPT_FILE = f"{ei.TEMPORAL_STATE_DIR}/binder_receipt.json"

#: Bumped only if the receipt's own SHAPE changes in a way an old reader
#: could misread as a match (a field renamed or repurposed). Adding a new
#: informational field is not such a change.
BINDER_RECEIPT_SCHEMA_VERSION = 1

#: The four directories `event_identity.apply_plan` files through, both
#: authorities. Read here to build :func:`_bindings_store_digest`, never to
#: build the records themselves — `event_identity.load_event_identities`
#: does that, and it pays for the parse and the validation this digest is
#: built to avoid paying for twice.
_BINDING_STORE_DIRECTORIES = (
    ei.HUMAN_BINDINGS_DIR, ei.STATE_BINDINGS_DIR,
    ei.HUMAN_OPERATIONS_DIR, ei.STATE_OPERATIONS_DIR,
)


def _framework_version() -> int | None:
    """`system/version.json`'s own `version`, read beside this module.

    Cheap by construction: one small file next to `episode_binder.py`
    itself, never a vault walk. `None` when it cannot be read, which simply
    means the receipt records nothing for this field and can never match it.
    """
    try:
        payload = json.loads((SYSTEM_DIR / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("version") if isinstance(payload, dict) else None
    return value if isinstance(value, int) else None


def _vault_head(vault_root: str | Path) -> str | None:
    """The vault's own git HEAD, if it has one. INFORMATIONAL ONLY — never a
    gate (:func:`_signature_matches` never reads it): most vaults are not
    the framework's own git history, and a vault with no git repo simply has
    no head to report."""
    try:
        root = store.store_path(vault_root, ".")
    except store.TemporalStoreError:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, ValueError):
        return None
    text = completed.stdout.strip()
    return text if completed.returncode == 0 and text else None


def _telling_digest(manifest: Mapping) -> str:
    """The manifest's own tellings, digested — claim ids, active claim ids,
    revisions and status, per telling ref.

    Cheap by construction: the manifest is already on disk
    (`event_identity.read_telling_manifest`), so this reads no receipt and
    derives no fold — exactly :data:`NOTHING_TO_BIND_COSTS_NOTHING`'s
    "not by deriving the fold". A telling's `bound_identity_ids` are
    deliberately NOT part of this digest; that half of the manifest is only
    as fresh as the last rebuild (classify and resolve rebuild it, `--apply`
    does not), so the BINDINGS half of the signature is
    :func:`_bindings_store_digest`'s own, read straight off the store this
    module writes through.
    """
    rows = sorted(
        (
            {
                "telling_ref": collapsed_text(row.get("telling_ref")),
                "status": collapsed_text(row.get("status")),
                "claim_ids": sorted(collapsed_text(v) for v in (row.get("claim_ids") or ())),
                "active_claim_ids": sorted(
                    collapsed_text(v) for v in (row.get("active_claim_ids") or ())
                ),
                "extraction_revisions": sorted(
                    collapsed_text(v) for v in (row.get("extraction_revisions") or ())
                ),
                "document_revision": collapsed_text(row.get("document_revision")),
                "superseded_by": collapsed_text(row.get("superseded_by")),
            }
            for row in (manifest.get("tellings") or ())
            if isinstance(row, dict)
        ),
        key=lambda row: row["telling_ref"],
    )
    return digest_id("bindertelling", rows)


def _bindings_store_digest(vault_root: str | Path) -> str:
    """A content digest of every filed binding and operation, both
    authorities.

    Cheap by construction relative to what a full pass already pays:
    `event_identity.load_event_identities` parses and validates every
    binding into a record; this reads the same files' RAW bytes and hashes
    them, which is the one thing that has to happen for a digest to mean
    anything and the only thing it does. A file this function cannot read
    is skipped rather than raising, the same as a full pass's own readers —
    an unreadable binding is that pass's problem, not this signature's.
    """
    root = store.store_path(vault_root, ".")
    entries: list[list[str]] = []
    for directory in _BINDING_STORE_DIRECTORIES:
        base = store.store_path(root, directory)
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                content = path.read_bytes()
            except OSError:
                continue
            entries.append([f"{directory}/{path.name}", hashlib.sha256(content).hexdigest()])
    return digest_id("binderbindings", sorted(entries))


def _landmark_sources_digest(vault_root: str | Path) -> str:
    """A content digest of every promoted landmark record
    (`landmark_projection.LANDMARK_SOURCES_DIR`).

    Measured, not assumed: a landmark import (`go-dig-import --apply`, the
    Add Landmark interaction) files `sources/landmarks/entry-*.md` and
    `state/landmarks.json` WITHOUT filing a receipt or touching the active
    index or the telling manifest at all — confirmed on the owner's own
    vault via the rig, where a fresh `go-dig-import --apply` left
    `state/temporal_claims/active_index.json`'s claim count and the telling
    manifest both byte-for-byte unchanged. `plan()` reads landmark entries
    for `participation_kinds_by_telling` and
    :data:`A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT` — a stay's dates widening,
    or a participant added, can change what an EXISTING telling's containment
    rung decides without any claim or binding moving at all. Cheap the same
    way :func:`_bindings_store_digest` is cheap: raw bytes, sha256, no
    frontmatter parse — a vault the size this release is about holds this in
    the low hundreds of files, not the thousands its claims and bindings do.
    """
    base = store.store_path(vault_root, lp.LANDMARK_SOURCES_DIR)
    if not base.is_dir():
        return digest_id("binderlandmarks", [])
    entries: list[list[str]] = []
    for path in sorted(base.glob("entry-*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        entries.append([path.name, hashlib.sha256(content).hexdigest()])
    return digest_id("binderlandmarks", sorted(entries))


def _cheap_pass_signature(vault_root: str | Path) -> dict | None:
    """The vault's cheap signature, or `None` when it cannot be read cheaply.

    `None` when the telling manifest has never been built — the ordinary
    state of a vault the classifier has never rebuilt one for — and the full
    pass is therefore the only honest answer; a missing manifest is not
    "nothing new", it is "unknown". NEVER derives the fold.
    """
    manifest = ei.read_telling_manifest(vault_root)
    if manifest is None:
        return None
    return {
        "telling_digest": _telling_digest(manifest),
        "bindings_digest": _bindings_store_digest(vault_root),
        "landmark_digest": _landmark_sources_digest(vault_root),
        "rule_version": RULE_VERSION,
        "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
        "framework_version": _framework_version(),
    }


#: The six fields a receipt and a fresh signature must agree on for a pass
#: to be `nothing_new`. Named once so :func:`_signature_matches` and a test
#: that wants to prove "this field alone gates the fast path" read the same
#: list.
BINDER_RECEIPT_SIGNATURE_FIELDS = (
    "telling_digest", "bindings_digest", "landmark_digest", "rule_version",
    "calculation_rule_version", "framework_version",
)


def _signature_matches(receipt: Mapping | None, signature: Mapping | None) -> bool:
    if not receipt or not signature:
        return False
    if receipt.get("schema_version") != BINDER_RECEIPT_SCHEMA_VERSION:
        return False
    return all(
        receipt.get(key) == signature.get(key) for key in BINDER_RECEIPT_SIGNATURE_FIELDS
    )


def read_binder_receipt(vault_root: str | Path) -> dict | None:
    """The last successful `--apply`'s receipt, or `None` when there is none
    yet (a vault that has never applied, or one where it was deleted —
    :data:`BINDER_RECEIPT_FILE` is a projection and deleting it is always
    safe, the next pass just pays the full cost once)."""
    text = store.read_store_text(vault_root, BINDER_RECEIPT_FILE)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_binder_receipt(vault_root: str | Path, receipt: Mapping) -> Path:
    """Publish the receipt atomically, the same way `write_telling_manifest`
    publishes the manifest beside it."""
    root = store.store_path(vault_root, ".")
    path = store.store_path(root, BINDER_RECEIPT_FILE)
    text = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    atomic_write_vault_text(path, text, vault_root=root)
    return path


def _compact_report_summary(report: Sequence[str]) -> list[str]:
    """The `Summary` tail of a `describe()` report, never the per-pair
    narrative in front of it.

    `describe()`'s own report is O(candidate pairs judged) — thousands of
    lines on a vault the size the whole point of this release is about — and
    a RECEIPT meant to stay small has no business holding a copy of it. The
    aggregate counts a person actually wants back on a `nothing_new` run are
    all after the line literally spelled ``"Summary"`` (:func:`describe`
    appends it verbatim); a report shaped some other way is returned whole
    rather than guessed at.
    """
    rows = list(report)
    try:
        index = rows.index("Summary")
    except ValueError:
        return rows
    return rows[max(index - 1, 0):]


def _write_receipt_after_apply(vault_root: str | Path, *, result: BinderPlan,
                               report: Sequence[str], filed: Mapping,
                               frames: int, entities: int,
                               question_contexts: int) -> None:
    """The receipt :data:`NOTHING_TO_BIND_COSTS_NOTHING` reads back.

    Computed AFTER `apply_plan` has written, so the bindings digest reflects
    what THIS run just filed — the next pass's own cheap signature is
    measured against what is on disk now, not against what was on disk
    before this apply ran. A vault with no telling manifest yet writes no
    receipt: there is nothing safe to compare a future signature against.
    """
    signature = _cheap_pass_signature(vault_root)
    if signature is None:
        return
    receipt = dict(signature)
    receipt["schema_version"] = BINDER_RECEIPT_SCHEMA_VERSION
    receipt["rule"] = "episode_binder.NOTHING_TO_BIND_COSTS_NOTHING"
    receipt["vault_head"] = _vault_head(vault_root)
    receipt["summary"] = {
        "report": _compact_report_summary(report),
        "counts": dict(result.counts),
        "filed": dict(filed),
        "frames": frames,
        "entities": entities,
        "question_contexts": question_contexts,
    }
    write_binder_receipt(vault_root, receipt)


def _fast_path_outcome(receipt: Mapping) -> dict:
    """`bind_episodes`'s return shape for a `nothing_new` pass — everything a
    caller (the CLI, `binder_step`) reads off a normal outcome, `plan` and
    `filed` both `None` because neither was derived."""
    summary = receipt.get("summary") or {}
    report = [
        *(summary.get("report") or []),
        "",
        ("nothing to bind: no new telling or binding since the last apply "
         "(episode_binder.NOTHING_TO_BIND_COSTS_NOTHING)"),
    ]
    return {
        "plan": None,
        "report": report,
        "applied": False,
        "reason": "nothing_new",
        "filed": None,
        "frames": summary.get("frames", 0),
        "entities": summary.get("entities", 0),
        "question_contexts": summary.get("question_contexts", 0),
        "last_summary": summary,
        "fast_path": True,
    }


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

    v340 adds one more read and no more derivations: the PUBLISHED generation,
    for the placements the bare fold cannot compute
    (:data:`PLACEMENTS_COME_FROM_THE_PUBLISHED_GENERATION`). A vault that has
    never published simply has the fold's own answer, which is what it had.
    """
    index = store.fold_active_index(vault_root)
    claims = [row for row in (index.get("claims") or ()) if isinstance(row, dict)]
    records = ef.load_episode_records(vault_root)
    # v340: ONE derivation, read twice — the frames and the placements — and
    # the PUBLISHED generation over the top
    # (:data:`PLACEMENTS_COME_FROM_THE_PUBLISHED_GENERATION`).
    derivation = fold_derivation(claims, episode_records=records, now=now)
    import temporal_publication as pub  # noqa: PLC0415
    published = pub.read_projection(vault_root) or {}
    windows = fold_placed_windows(claims, derivation=derivation)
    windows.update(placed_windows_of(
        published.get("nodes") or (), claims,
        aliases=published.get("node_aliases"),
    ))
    return {
        "claims": claims,
        "episode_records": records,
        "frames": tuple(derivation.age_frames) if derivation is not None else (),
        "placed_windows": windows,
        # `episode_containers.A_BARE_NAME_IN_THE_BINDER_IS_WHO_HE_CALLS_BY_IT`:
        # the census of what he calls people, read from the same words the fold reads.
        "entity_index": ec.load_entity_index(vault_root, texts=tt.telling_texts(claims)),
        "question_contexts": read_question_contexts(vault_root, claims),
        "landmark_entries": lp.load_landmark_sources(vault_root),
    }


#: The seam §12b ruling 5 needs, named where a platform engineer will look for
#: it. *"The session RECORDS which container its question targeted (the
#: work-item/era Play target), so 'this answer was given to an Etherfuse
#: question' is a fact, not an inference."* Nothing in `TemporalClaim` carries
#: it and §9 froze that schema, so the stamp rides the SOURCE — the additive
#: `question_context` frontmatter key `temporal_store.promote_conversational_source`
#: understands — and a telling inherits it from the source its claims cite.
#: The platform supplies the value when it opens the session; a vault whose
#: sources carry none simply has no `question_context` rung, which is an
#: absence and not a failure.
QUESTION_CONTEXT_SEAM = (
    "the recorder's stamp is `question_context` in the promoted source's own "
    "frontmatter; a telling inherits it from the source its claims cite, and "
    "the value names the container as an episode id, a container key or the "
    "telling ref of the telling that opened it"
)


def read_question_contexts(vault_root: str | Path, claims: object) -> dict:
    """``{telling_ref: the container that telling's question targeted}``.

    Reads each cited source's frontmatter ONCE — the same
    `temporal_store.split_frontmatter` every other reader uses — and never the
    body. A source that carries no stamp contributes nothing; a source that
    cannot be read contributes nothing and raises nothing, because a missing
    file is a vault the fold already reports on and not this rung's outage.
    """
    paths: dict[str, str] = {}
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        ref = row.get("source_ref") if isinstance(row.get("source_ref"), dict) else {}
        relative = collapsed_text(ref.get("source_path"))
        if not relative:
            continue
        try:
            telling_ref = ei.telling_ref_for_claim(row)
        except TemporalContractError:
            continue
        paths.setdefault(telling_ref, relative)

    by_path: dict[str, str] = {}
    found: dict[str, str] = {}
    for telling_ref in sorted(paths):
        relative = paths[telling_ref]
        if relative not in by_path:
            stamp = ""
            text = store.read_store_text(vault_root, relative)
            if text:
                metadata, _body = store.split_frontmatter(text)
                stamp = collapsed_text((metadata or {}).get("question_context"))
            by_path[relative] = stamp
        if by_path[relative]:
            found[telling_ref] = by_path[relative]
    return found


def fold_derivation(claims: object, *, episode_records: object = (),
                    now: object = None) -> object:
    """The `CalculatedTimeline` THE FOLD derives for these claims. Pure.

    ONE derivation per binder run (:data:`FRAMES_COME_FROM_THE_FOLD`), read by
    both the frames and the placements, so v340's second reader costs nothing
    and the two can never disagree about which projection they are reading.
    ``None`` when there is nothing to derive.
    """
    import temporal_timeline as tt  # noqa: PLC0415

    rows = [dict(row) for row in (claims or ()) if isinstance(row, dict)]
    if not rows:
        return None
    return tt.derive_calculated_timeline(
        {"version": store.INDEX_VERSION, "claims": rows},
        episode_records=episode_records, now=now,
    )


def fold_age_frames(claims: object, *, episode_records: object = (),
                    now: object = None) -> tuple:
    """The age frames THE FOLD calculated for these claims. Pure.

    Exposed so a test can prove the binder's frames are the fold's own, and so
    a host that already holds a `CalculatedTimeline` can hand over
    ``result.age_frames`` instead of paying for a second pass.
    """
    result = fold_derivation(claims, episode_records=episode_records, now=now)
    return tuple(result.age_frames) if result is not None else ()


def placed_windows_of(nodes: object, claims: object, *,
                     aliases: object = None, manifest: object = None) -> dict:
    """``{telling_ref: the interval these NODES put that telling at}``. Pure.

    The other half of :data:`A_MERGE_NEVER_MOVES_A_DATED_MOMENT`, and it is the
    projection's own answer rather than a second one. A telling reaches its node
    two ways and both are read, because on the owner's vault the two do not
    agree about which claims a node lists:

    * the node whose ``input_claim_refs`` name one of the telling's claims;
    * **the node a claim NAMES as its own event** (``event_ref``) — the fold's
      own answer to "which event is this claim about", which is the same field
      :data:`RULE_ID_DERIVED_READING` reads. This is the half the Yucaipa
      incident needed: both "Family moved to Yucaipa" tellings declare their
      node in every claim, and the published node lists only ONE of the
      telling's claims, so a reader that went by the node's list alone found no
      window for either side and the guard never fired.

    The claim→telling map is `episode_fold.claim_telling_index`, the same one
    :func:`telling_views` buckets by, so the keys here and the views' keys are
    the same keys. ``aliases`` is the projection's own ``node_aliases``, so a
    claim still naming a node id an earlier bind re-keyed reaches the node it
    became (Law 5). A telling whose nodes disagree keeps nothing, for exactly
    :func:`_bounds_of`'s reason: a contradiction inside one telling is not this
    module's to settle.
    """
    rows = [row for row in (claims or ()) if isinstance(row, dict)]
    telling_of = ef.claim_telling_index(rows, manifest)
    alias_map = {collapsed_text(key): collapsed_text(value)
                 for key, value in dict(aliases or {}).items()}

    def canonical(node_id: object) -> str:
        found = collapsed_text(node_id)
        for _ in range(8):
            nxt = alias_map.get(found)
            if not nxt or nxt == found:
                break
            found = nxt
        return found

    window_of_node: dict[str, object] = {}
    claim_home: dict[str, str] = {}
    for node in nodes or ():
        row = node if isinstance(node, dict) else {}
        node_id = collapsed_text(row.get("node_id"))
        record = chrono.from_dict(row.get("best_temporal_value"))
        if not node_id:
            continue
        for claim_id in (row.get("input_claim_refs") or ()):
            claim_home[collapsed_text(claim_id)] = node_id
        if record is not None:
            window_of_node[node_id] = record

    found: dict[str, dict] = {}
    for row in rows:
        claim_id = collapsed_text(row.get("claim_id"))
        telling_ref = collapsed_text(telling_of.get(claim_id))
        if not telling_ref:
            continue
        reached = {claim_home.get(claim_id, "")}
        if collapsed_text(row.get("event_ref")).startswith("node:"):
            reached.add(canonical(row.get("event_ref")))
        for node_id in reached:
            record = window_of_node.get(node_id)
            if record is not None:
                found.setdefault(telling_ref, {})[node_id] = record

    windows: dict[str, object] = {}
    for telling_ref in sorted(found):
        records = [found[telling_ref][node_id] for node_id in sorted(found[telling_ref])]
        window = records[0] if len(records) == 1 else chrono.intersect(*records)
        if window is not None:
            windows[telling_ref] = window
    return windows


def fold_placed_windows(claims: object, *, episode_records: object = (),
                        now: object = None, derivation: object = None) -> dict:
    """:func:`placed_windows_of` over the fold's OWN derivation. Pure.

    ``derivation`` lets a caller that already paid for one hand it over.
    """
    result = derivation if derivation is not None else fold_derivation(
        claims, episode_records=episode_records, now=now
    )
    if result is None:
        return {}
    return placed_windows_of(result.nodes, claims, aliases=result.node_aliases)


#: v340, and it is the reason :func:`read_vault_inputs` reads the PUBLISHED
#: projection beside the fold's own. The window that matters is where a moment
#: SITS — and the placements that come from containment inside a stay, from a
#: resolver answer, from an era's span or from a landmark entry are computed
#: from inputs `temporal_publication.load_derivation_inputs` supplies and this
#: module's one-argument derivation does not have. On the owner's vault that is
#: the whole Yucaipa incident: the childhood move's 1981-07-11/1982-07 is
#: `basis: "anchor", confidence: "inferred"` with no provenance of its own, so
#: the binder's bare fold leaves it UNPLACED and a guard reading only that fold
#: sees two undated retellings again. The published generation is what a reader
#: could see, it is what the apply is about to contradict, and it is therefore
#: what the rule is measured against; the bare fold fills in a telling filed
#: since that generation, so the two together are never less than either.
PLACEMENTS_COME_FROM_THE_PUBLISHED_GENERATION = (
    "a merge is measured against the placements a reader can already see — the "
    "published projection — with the binder's own fold filling in whatever has "
    "been filed since, because a containment, a resolver answer or an era span "
    "places a moment through inputs only the publisher holds"
)


def apply_plan(vault_root: str | Path, result: BinderPlan) -> dict:
    """File a plan through `event_identity`'s ORDINARY writers. Replay is a no-op.

    Nothing is written by hand: every envelope goes through
    `file_operation_envelope` (bindings first, operation last, so a crash
    leaves inert records rather than an operation promising records the vault
    does not hold) and every containment proposal through
    `file_event_identity`'s create-or-keep. Applying the same plan twice
    creates nothing the second time, by digest arithmetic.

    The ONE exception is the plan's ``containment_upgrades``, which go through
    `refile_event_identity` — the door that may move an ``origin`` in place,
    and only when the filed bytes differ by nothing else
    (`episode_fold_contract.CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT`). It is
    idempotent for the same reason everything else here is: the second run
    finds ``deterministic`` already on disk and reports ``kept``.

    There is deliberately no ``now`` here: every record already carries the
    clock the PLAN stamped, and a writer that re-stamped it would make "when
    was this decided" a property of when it was filed.
    """
    _require(isinstance(result, BinderPlan), "binder_apply_needs_a_plan",
             "apply files a BinderPlan; run `plan()` first")
    filed = {"envelopes": [], "exact_envelopes": [row["operation"]["operation_id"]
                                                 for row in result.exact_envelopes],
             "proposals": [], "upgraded": [],
             "kept_stronger": list(result.containment_kept_stronger),
             "not_upgraded": [], "created": 0}
    for row in (*result.envelopes, *result.exact_envelopes):
        outcome = ei.file_operation_envelope(
            vault_root, operation=row["operation"], bindings=row["bindings"],
        )
        filed["envelopes"].append(outcome["operation"]["operation_id"])
        filed["created"] += 1 if outcome["created"] else 0
    for record in result.proposals:
        _row, created = ei.file_event_identity(vault_root, **dict(record))
        filed["proposals"].append(record["identity_id"])
        filed["created"] += 1 if created else 0
    for record in result.containment_upgrades:
        _row, outcome = ei.refile_event_identity(vault_root, **dict(record))
        if outcome == "upgraded":
            filed["upgraded"].append(record["identity_id"])
        elif outcome == "kept_stronger":
            filed["kept_stronger"].append(record["identity_id"])
        elif outcome != "kept":
            # The plan matched on `identity_id` and the ORIGINS; the writer is
            # the one that read the bytes. A candidate the bytes refuse is
            # reported by name rather than filed anyway or silently dropped.
            filed["not_upgraded"].append({"identity_id": record["identity_id"],
                                          "outcome": outcome})
    return filed


def bind_episodes(vault_root: str | Path, *, apply: bool = False,
                  question_cap: int = GLOBAL_QUESTION_CAP,
                  trigger: str = "maintenance_sweep",
                  era_memberships: object = None,
                  containment_authority: object = None, now: object = None) -> dict:
    """`bind-episodes`, as a function. ``apply=False`` writes NOTHING.

    Returns ``{"plan", "report", "applied", "filed"}`` — the plan for a
    caller, the lines for a terminal, and what was filed when anything was.

    v348 (:data:`NOTHING_TO_BIND_COSTS_NOTHING`): the FIRST thing every pass
    does, dry run or apply, is compare the vault's cheap signature against
    the receipt the last successful `--apply` left. A match means nothing
    the fold would decide has moved, so nothing is derived — ``"plan"`` and
    ``"filed"`` come back `None`, ``"applied"`` is `False` even when the
    caller asked for `apply=True`, because nothing WAS applied this run, and
    ``"reason"`` is ``"nothing_new"``. Anything else — a new or changed
    telling, a changed binding, a moved rule version, or no receipt at all —
    runs the full pass exactly as before, and a successful `--apply` writes
    a fresh receipt afterward so the NEXT pass can be the fast one.
    """
    signature = _cheap_pass_signature(vault_root)
    receipt = read_binder_receipt(vault_root) if signature is not None else None
    if _signature_matches(receipt, signature):
        return _fast_path_outcome(receipt)

    inputs = read_vault_inputs(vault_root, now=now)
    result = plan(
        inputs["claims"], episode_records=inputs["episode_records"],
        frames=inputs["frames"], era_memberships=era_memberships,
        entity_index=inputs["entity_index"],
        question_contexts=inputs["question_contexts"],
        landmark_entries=inputs["landmark_entries"],
        placed_windows=inputs["placed_windows"],
        containment_authority=containment_authority,
        question_cap=question_cap, trigger=trigger, now=now,
    )
    filed = apply_plan(vault_root, result) if apply else None
    report = describe(result, applied=bool(apply))
    frames = len(inputs["frames"])
    entities = inputs["entity_index"].size()
    question_contexts = len(inputs["question_contexts"])
    if apply and filed is not None:
        _write_receipt_after_apply(
            vault_root, result=result, report=report, filed=filed,
            frames=frames, entities=entities, question_contexts=question_contexts,
        )
    return {
        "plan": result,
        "report": report,
        "applied": bool(apply),
        "reason": None,
        "filed": filed,
        "frames": frames,
        "entities": entities,
        "question_contexts": question_contexts,
        "fast_path": False,
    }


def binder_step(vault_root: str | Path, *, now: object = None,
                era_memberships: object = None,
                containment_authority: object = None,
                question_cap: int = GLOBAL_QUESTION_CAP) -> dict:
    """The maintenance seam: run the binder after recording, WRITE NOTHING.

    :data:`MAINTENANCE_STEP_IS_A_DRY_RUN` is the whole contract. The weekly
    loop calls this; the owner calls `bind-episodes --apply` once, after
    reviewing the dry run, and only once I3 exists.
    """
    outcome = bind_episodes(vault_root, apply=False, question_cap=question_cap,
                            era_memberships=era_memberships, now=now,
                            containment_authority=containment_authority,
                            trigger="maintenance_sweep")
    result = outcome["plan"]
    if result is None:
        # v348 fast path (:data:`NOTHING_TO_BIND_COSTS_NOTHING`): nothing
        # changed since the last apply, so there is nothing this dry run
        # would decide that the last apply's own receipt does not already
        # say. The step is still a dry run either way
        # (:data:`MAINTENANCE_STEP_IS_A_DRY_RUN`) — reading nothing costs
        # nothing, so it reports the last summary's counts rather than
        # deriving a plan only to discard it.
        last = outcome.get("last_summary") or {}
        authority = containment_authority or ec.DEFAULT_CONTAINMENT_AUTHORITY
        block_name = "containments" if authority == "applied" else "containment_proposals"
        return {
            "counts": dict(last.get("counts") or {}),
            "report": outcome["report"],
            "questions": [],
            "overmerges": [],
            block_name: [],
            "containment_diagnostics": [],
            "containment_ambiguities": [],
            "containment_upgrades": [],
            "containment_kept_stronger": [],
            "wrote": False,
            "reason": "nothing_new",
        }
    return {
        "counts": dict(result.counts),
        "report": outcome["report"],
        "questions": list(result.questions),
        "overmerges": list(result.overmerges),
        # I2b: the containment rung runs in the weekly seam exactly as it runs
        # in an operator run — the SAME `plan()` — and the step reports it
        # under the name the authority flag earns.
        result.containment_block_name: list(result.containments),
        "containment_diagnostics": list(result.containment_diagnostics),
        "containment_ambiguities": list(result.containment_ambiguities),
        # The dry run says what an `--apply` at this authority WOULD move, so
        # the owner-reviewed dry run the rollout gate requires can be reviewed
        # for the upgrade too, not only for new placements.
        "containment_upgrades": list(result.containment_upgrades),
        "containment_kept_stronger": list(result.containment_kept_stronger),
        "wrote": False,
    }


__all__ = [
    "QUESTION_CONTEXT_SEAM",
    "ENTITY_SIGNAL",
    "DEFAULT_CONTAINMENT_AUTHORITY",
    "CONTAINMENT_AUTHORITIES",
    "BINDER_ERROR_CODES",
    "BINDER_OUTPUT_FILE",
    "BINDER_RECEIPT_FILE",
    "BINDER_RECEIPT_SCHEMA_VERSION",
    "BINDER_RECEIPT_SIGNATURE_FIELDS",
    "NOTHING_TO_BIND_COSTS_NOTHING",
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
    "A_MERGE_NEVER_MOVES_A_DATED_MOMENT",
    "A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE",
    "A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE",
    "A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE",
    "A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS",
    "births_dated_elsewhere",
    "A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT",
    "A_COUPLE_IS_TWO_PEOPLE",
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
    "DERIVED_READING_SOURCE_KIND",
    "EXACT_IDENTITY_RULE_IDS",
    "EXACT_IDENTITY_RULE_TEXT",
    "MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER",
    "MILESTONE_OF_EVENT_KIND",
    "MILESTONE_OF_EVENT_NOUN",
    "MILESTONE_OF_VERB_STEM",
    "PERSON_ENTITY_PREFIX",
    "RESTATEMENT_BUCKET_CAP",
    "RESTATEMENT_MIN_TOKENS",
    "RESTATEMENT_SHARED_TOKENS",
    "RULE_ID_DERIVED_READING",
    "RULE_ID_EXACT",
    "RULE_ID_MILESTONE",
    "RULE_ID_RESTATEMENT",
    "RULE_ID_SAME_LABEL",
    "BinderPlan",
    "Candidate",
    "Condition",
    "ExactLink",
    "derived_reading_links",
    "exact_identity_counts",
    "exact_identity_groups",
    "exact_identity_links",
    "group_envelope",
    "link_refusal",
    "milestone_links",
    "milestone_of",
    "person_tokens",
    "reads_node",
    "restatement_links",
    "same_label_links",
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
    "fold_derivation",
    "fold_placed_windows",
    "placed_windows_of",
    "PLACEMENTS_COME_FROM_THE_PUBLISHED_GENERATION",
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
    "read_binder_receipt",
    "read_question_contexts",
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
    "write_binder_receipt",
]
