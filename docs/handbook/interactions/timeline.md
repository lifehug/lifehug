---
title: Timeline
parent: The Interaction Pattern
nav_order: 7
---

# Timeline Interaction

## 1. What it does

Timeline is the conversation you get when you press Play on a hole in your
timeline — a stretch with nothing placed in it, a moment that floats free, an
era with no order. It is the fifth child of Conversation, and its one goal is
**placing a memory in time without ever demanding a year** (v195,
`docs/pr-specs/timeline-chronology.md`; platform design brief `#581`).

It never opens with "what year was that". Dating a memory is reconstruction,
not recall: people work out *when* from what else was true then — where they
were living, what work they were doing, who was around. So the conversation
asks about those, and the date falls out. If you say you were about five and
the system already knows your birthday, it does the arithmetic and says the
answer back as an inference you can correct.

A **bounded interval is a real answer.** "Sometime between the move and the
baby" is a finding, not a failure, and it is stored as one. The ladder climbs
era → year-range → year → season → month only while it stays cheap, and stops
at the first rung you hold without hedging — a hedged month is worse than a
confident season.

**"I'll find out" is a real state.** Say you will ask your mother and the
unknown goes quiet: it keeps its star and its leverage, it is never counted as
outstanding, and nothing raises it again.

**Passive users are untouched.** The daily single question works exactly as it
did; this Interaction runs only when an unknown is Played. Mechanically the
gate is `TurnShape.timeline_stage`, which defaults to `None`, and with it
`None` the turn's output contract is byte-identical to v194.

## 2. The behavior authority

The contract below is the file the runtime sends to the model, verbatim — not a
description of it (see [the Interaction Pattern](index.md) §3).

<!-- embed: interactions/timeline/prompt/behavior.md -->
# Behavior contract — Timeline extension

The inherited Conversation contract governs every visible reply. These rules
add the Timeline responsibility.

1. **Never open with a year.** Not "what year was that", not "roughly what
   year", not "can you give me a decade". Dating is reconstructive inference,
   so a year prompt buys a rounded guess that drifts later than the truth.
   Open with the moment itself, then with where they were living or what work
   they were doing — the things a life is actually indexed by.
2. **One question per reply.** Receive what they said first; ask the next
   thing second. Two questions turns placing a memory into an interrogation.
3. **Bound before you pin.** Two bounds beat one guess. "Was that before or
   after you moved?" and "had she been born yet?" give an interval, and an
   interval is storable, honest, and often all there ever was.
4. **Offer bounds; never demand a point.** "Spring 1998 — or is 'sometime
   97–99' more honest?" lets them choose the precision they can actually
   hold. Asking them to pick a month they do not have is asking them to make
   one up.
5. **Prefer their landmarks to the world's.** A move, a wedding, a birth, a
   job — their own turning points work at least as well as public events, and
   a public event only helps when it actually disrupted *their* daily life.
6. **Climb only while it is cheap.** Era → year-range → year → season →
   month, and stop at the first rung they hold without hedging. A hedged
   month is worse than a confident season. Stop when two probes in a row add
   no new bound. Stop instantly on any distress: dating is never worth the
   relationship.
7. **"I'll find out" is a real answer.** When they say they will ask their
   mother, or check a photo, receive it warmly, say it will keep, and ask
   nothing further about it. It is not a decline and it is not a debt, and
   you never raise it again in this episode.
8. **Never invent a date.** Every year you say out loud must be one they gave
   you or one that is already on their own timeline. If the arithmetic gives
   you a year — their age against their birthday, a landmark and a
   before/after — say it back as an inference and let them correct it.
9. **Both accounts survive.** If what they say now disagrees with something
   the timeline already holds, say so plainly, keep both, and ask which they
   trust — never overwrite, never quietly pick one, and never treat the
   disagreement as a mistake. What they remember differently is itself worth
   knowing.

## Placement doctrine

A timeline is how a person sees the shape of their own life, not a database
to complete. So a placement episode is short, it ends the moment the memory
is placed well enough for its slot, and nothing is ever "still missing". The
holes are interesting; they are not failures, and they are never described as
falling behind.

## Never propose a date

You may say what the arithmetic gives you — "you were twelve then, so that
puts it around 1986" states a derivation and shows its working. You may never
name a date and ask them to agree with it. "Was it 1984?", "shall we say
1986?", "does that sound right?" — all forbidden.

True photographs plus suggestive interviewing produced false memories in about
two thirds of participants, the highest rate in any published study, and a
dating probe backed by the person's own evidence is precisely that
configuration. You elicit readings and do the arithmetic; they supply
evidence, never confirmations.

## A card conversation's answer ends the card, not a story

Owner ruling, 2026-09-25 (v360 review): he answered a `work_item`-stage
card with "son" and got the inherited Conversation contract's own default —
*"That's worth sitting with for a second. What led you to bring that up
today?"* — rule 2's receipt and rule 3's cued invitation, exactly as written,
applied to the one place they read wrong. **"When it comes from the timeline,
your goal is to just give an answer. I don't know that a full conversation is
needed."**

This overrides rules 2 and 3 for exactly one reply — the one that lands right
after they answer the thing this conversation was opened to ask — and for
nothing else; every other Timeline reply (`open`, `place`, `close`, `era`, and
the `work_item` stage's own disagreement-probing turns before an answer)
keeps the inherited contract untouched.

- **Say what was placed or filed, in one short line, and stop.** "Placed",
  "filed" or "noted" — one of those words, or its plain sense — naming the
  thing itself ("Placed — Thunderhead, June 1989 to June 1990.", "Noted —
  Harvey is your son."). Never the reflection-heavy receipt rule 2 asks for
  elsewhere, never rule 3's cued invitation to say more, never "worth sitting
  with", never a question about why they brought it up.
- **One more question, only while the leaf hands you a grounded one.** The
  `work_item` stage's own rule below says exactly when that is — a specific
  related moment named in `{work_item}` itself, never an invented one. With
  nothing named there, or once they say "I don't know" / change the subject /
  the register cools, this reply asks nothing and the episode is done.
- **This is the framework's seat for the rule, not a copy of it.** A host
  that wires its own play surface around this package (Timeline row, Mirror,
  a deep link) reads this leaf rather than re-deciding when a card's answer
  should stop being a card conversation — the same one-definition contract
  `compose_question` already keeps for wording (ADR 0021).
<!-- /embed -->

## 2b. The question writer — sentences, not templates

A work item is only useful if the question it carries is a sentence a person
would actually say. Until v262 three composers printed `{node label} — {event
kind}` into a template and the founder's own Timeline asked *"When did
speaker's mission — transition — happen?"* — the extractor's third-person
handle for him, plus an internal node kind, inside a frame.

| The thing | Where |
|---|---|
| The one composer | `temporal_timeline.compose_question(item_kind, event_kind, who=…, what=…, target=…, readings=…, is_owner=…, is_place=…)` — pure, deterministic, no model call. `None` means WITHHELD |
| The words | `temporal_timeline.KIND_SENTENCES` (one row per event kind: the node's title and the sentence each work-item kind asks) and `OWNER_REFERENCE_REWRITES` ("speaker's" → "your", "I" → "you") |
| The node's title | `temporal_timeline._node_label` reads the SAME table, so a title and the question about it can never describe one node two ways |
| Free-text anchor handles | `temporal_timeline.compose_anchor_question` — a noun phrase is asked directly; a clause is quoted back ("You mentioned your dad graduated from college — when was that?") rather than conjugated |
| The refusal | `conversation_lints.lint_question(text)` — an internal kind after an em dash, a third-person owner handle, a bare-pronoun subject, an empty subject slot. `_mint_work_item` calls it on EVERY intent and, on any finding, mints `prompt_intent=None` with a `withheld_reason` and a `question_withheld` diagnostic |

Four rules travel with the composer and none of them is a preference:

- **`event_kind` is never printed to a person.** `_event_words` survives for
  diagnostics and node ids only.
- **The birth is the floor and never an anchor.** `timeline.anchor_index`
  types every row whose interval IS the birth record as `kind: "birth"`
  (whatever minted it), and `anchor_for_probe` excludes birth for every
  unknown kind — reversing v236's "a moment may sort against the birthday"
  carve-out on the owner's ruling. An era's or a residence's anchor must
  also be RELEVANT (`anchor_is_relevant`): another era or residence, or a
  landmark that shares its era, place or a content word — never one picked
  by adjacency in a sorted list. A bare moment is deliberately exempt:
  ordering one memory against another is how people date them.
- **One node, one question.** `WORK_ITEM_PRECEDENCE` = identity_uncertain →
  contradiction → missing_anchor → precision_gap; the survivor absorbs the
  other's evidence and records it in `superseded_kinds`.
- **An age frame is never asked about.** Childhood, Teen years and every
  reached decade are arithmetic off the birthday (ADR 0030) — the coordinate
  system itself. `UNASKABLE_EVENT_KINDS` blocks the composer and
  `timeline.unknowns` skips any legacy period slug `legacy_period_ref`
  recognises as a frame.
- **A card is asked only when a person could answer it** (v343,
  `timeline-rules:13`). A claim whose only label is a pronoun/placeholder
  (`landmarks_interaction.EMPTY_SUBJECT_LABELS`) AND whose `confidence` is
  exactly `0.0` mints no node at all (`temporal_timeline._claim_is_empty`,
  read from `_group_claims`) — the owner's *"When was they?"* card came from a
  `confidence: 0.0` claim with no `event_mention` and a bare pronoun
  `subject_mention`. A bare gerund/participle `{what}` ("Harvey arriving")
  reads `"When was {what}?"` (`temporal_timeline._is_gerund_phrase`) rather
  than the ungrammatical `"When did {what} happen?"`. And an
  `identity_uncertain` candidate set is filtered — roster rows with
  `maps_to_focus` set and collective/role rows (`entity_roster.ROLE_WORDS`)
  are excluded by `identity_resolution.roster_index` before a mention is even
  resolved, and the OWNER's own roster row is dropped from the running by
  `identity_resolution.identity_work_item`'s `owner_refs` — so a card mints
  only when at least two DISTINCT people remain to ask about.
- **A card never shows a node id as its label** (v350, `timeline-rules:17`,
  `temporal_timeline.A_CARD_NEVER_SHOWS_A_NODE_ID_AS_ITS_LABEL`). A
  cross-dating anchor may be a NODE REF, and the anchor rung asked about
  whatever text it was handed — *"When was node:0809d05e26d18f128fd83126?"*, 28
  `missing_anchor` cards on the owner's hosted head. An anchor handle that
  names an internal id now mints NOTHING, reported
  `anchor_without_a_human_label` with the nodes that were waiting on it (each
  of which already carries a card of its own), and `conversation_lints
  .lint_question` refuses any composed sentence carrying one — the shape read
  off the minter's own `temporal_claims.ID_RE` rather than a list of prefixes.
  One grammar rule joins v343's: a phrase that LEADS with a verb is a bare
  predicate whatever its length (`temporal_timeline._leads_with_a_verb`,
  `_is_gerund_phrase`'s mirror on the same `_ING_EVENT_NOUNS` vocabulary), so
  *"left Kristen"* is quoted back the way *"moved in with dad"* already was.
- **A full name outranks a shared first name** (v357, `timeline-rules:18`,
  `identity_resolution.A_FULL_NAME_OUTRANKS_A_SHARED_FIRST_NAME`). A card
  about *"James Edwin Taylor"* is a card about the owner's father, because that
  mention carries his roster spelling `James Taylor` given name through
  surname — so an age said about it (*"19-21 years old"*) is measured from
  HIS 1954 birth instead of having no birth to count from. `<Name> Sr.` is a different person,
  never a tie (`A_GENERATIONAL_SUFFIX_IS_ONE_GENERATION`), and a roster alias
  row is never offered, counted or bound (`AN_ALIAS_ROW_IS_NEVER_A_CANDIDATE`).
  A bare *"James"* on a roster where four people answer to it still asks
  *which James*, naming the real people and never the pointer row.

## 3. The playbook, the anchors, and the stage

| Concern | Where |
|---|---|
| What a Play points at | `timeline.unknowns(data)` → `{kind, key, label, probe, deferred, ...}`; kinds are `timeline.UNKNOWN_KINDS` — `era_gap` plus the seven `compute_gaps` already emitted |
| The person's landmarks | `timeline_interaction.anchors_for_person(birth_date=…, periods=…, places=…, events=…)`, rendered into `{anchors}` by `render_anchors`. Birthday, residences with spans, eras with spans, dated landmark moments — the life-history calendar as text, and the ONLY dates the model may repeat |
| The next question | `timeline_interaction.choose_probe(unknown, anchors=…, precision_so_far=…, asked_steps=…)` walks `PLAYBOOK_STEPS`: content → residence → role → parallel domain → sequence → landmark → season → bounds → convergence → defer. Rungs needing a landmark are skipped when there is none |
| When the ladder stops | `TARGET_GRANULARITY` per unknown kind — a gap between eras needs a year, a thin lineup only needs an era. At or finer than target, the probe becomes `convergence` |
| Which stage this turn is in | `timeline_interaction.timeline_stage_for_session(session, user_leaving=…, placement_settled=…, no_new_bound_streak=…, work_item=…)` → `open` before the first assistant turn, `close` on a departure, a settled placement, two unproductive probes, or the probe ceiling; `work_item` for a conversation the person opened on a Play target; `place` otherwise <!-- parity: timeline_interaction.STOP_AFTER_UNPRODUCTIVE_PROBES = 2 --> <!-- parity: timeline_interaction.MAX_PROBES = 4 --> |
| What the filing just placed (v207) | `cross_dating.gain_sentence_for_record(record, timeline_payload)` → `cross_dating.render_filing_gain(sentence)` fills `{filing_gain}` on the turn that FILED — *"Got it — that dates nine moments and your Childhood years."* The count is the cross-dating pass run over the current payload with the new record folded in, so the reply can only claim what the next derivation delivers. Empty on every other turn, and the prompt is then byte-identical |
| The prompt the caller replays verbatim | `interactions/timeline/prompt/turn-instructions.md`, substituting `{timeline_stage}`, `{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}`, `{filing_gain}` |
| The five lints | `timeline_interaction.lint_timeline_reply` → `timeline_gates.*`: never open by asking for a year; at most one question; offer bounds rather than demand a point; accept a deferral without pressing; never assert a year nobody supplied |

"Never pressure" is deliberately absent from that list: the parent
Conversation contract and `arc_walk`'s `no_pressure` already own it, and a
second definition of one rule is the defect the recurring-defect doctrine
forbids.

## 4. Filing: what does a placement write?

One additive output field, `placed`, carries either a date record, or
`{"deferred": true}`, or null. Two layers validate it, exactly as every other
child's field is validated: `conversation_delivery._parse_placed` owns shape
and no vocabulary and never raises;
`timeline_interaction.validate_placed(value, anchors=…)` owns the three closed
vocabularies, EDTF parseability, and **exact** membership of every anchor key
in the anchors this episode actually offered — an invented anchor drops the
whole record rather than filing something wrong.

The package names the date; the host writes it.
`timeline_interaction.place_invocation` builds the exact call for the write
path that already existed: `lifehug.py timeline-place <source> --period <slug>
[--date <edtf>] [--basis <basis>] [--anchor <key>]…`, which files a `--kind
date` correction source (the durable half) and saves the display pin (which
auto-retires once classification catches up).

The call is a `PlaceInvocation` — `argv` AND `stdin_text` — because the command
reads the moment's description on **stdin** and exits 1 without it. The host
runs both halves: `subprocess.run([…, *inv.argv], input=inv.stdin_text)`. They
travel together for a reason: while they were two values,
`conversation_delivery._file_placement` ran the argv with no `input=` and every
date a person named in conversation exited 1 into a silent `place_failed`
(lifehug#223, fixed in v213 — `tests/test_timeline_place_filing.py` now
executes the filing against a real temp vault).

The call also carries the moment's **identity**. A placement is keyed by
`sha1(source + "\n" + description)` and joined by the same recipe, but an
unknown row is *named* by the moment's title — so v213's filing minted from
the title against a join expecting the description, and every conversational
date landed in `stale_placements`, unrendered, at exit 0 (lifehug#228, fixed in
v215). `place_invocation(..., placement_key=…)` now passes the row's own
`timeline.placement_key` through as `--placement-key`, which the CLI stores
verbatim; `timeline.resolve_placements` re-joins the records the old recipe
orphaned at read time, and anything still unjoined is counted at
`timeline_data()["counts"]["stale_placements"]` rather than being silent.

## 5. Where it lives

| Concern | Location |
|---|---|
| Registration | `interactions/registry.json` (`timeline`) |
| Definition | `interactions/timeline/` |
| Runtime authority | `system/timeline_interaction.py` |
| The date primitive | `system/chronology.py` |
| Unknowns, leverage, keystones, deferred | `system/timeline.py` |
| Plan a timeline Play (read-only) | `lifehug.py arc-plan-target --timeline [--era <slug>] [--json]` |
| The write path | `lifehug.py timeline-place ... [--date] [--basis] [--anchor] [--placement-key]` |
| Placement identity (mint, join, repair) | `system/timeline.py` (`placement_key`, `legacy_title_key`, `resolve_placements`) |
| Goldens | `interactions/timeline/evals/goldens/timeline_*.json` |
| Independent evals | `lifehug.py timeline-evals --json` |
| Guard tests | `tests/test_chronology.py`, `tests/test_timeline_dates.py`, `tests/test_timeline_unknowns.py`, `tests/test_timeline_interaction.py`, `tests/test_timeline_evals.py`, `tests/test_timeline_place_filing.py` |

The package declares role tiers but no default concrete seat. The five
`timeline_gates.*` compliance classes require perfect scores over ten recorded
goldens — including the **skeleton episode** (birthday, then the places lived
by age, which dates most of a timeline by inference) and a contradiction case
where both accounts survive. They score with or without a live provider; an
unavailable provider skips loudly and never seats by default.

## 6. Decisions

- [ADR 0024 — Chronology with basis: dates as intervals, asking anchor-first](../../adr/0024-chronology-with-basis.md) — the split doctrine, the closed vocabularies, contradictions that keep both claims, derived order, keystones, and the deferred memory.
- [ADR 0018](../../adr/0018-candidate-placement.md), fifth amendment — `placed` as the fifth instance of the additive-field discipline.
- [ADR 0023](../../adr/0023-arc-walking.md) — the sibling whose stage/caller-fact shape this child copies line for line.
