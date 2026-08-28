---
title: Eras — Age Frames & Named Eras
parent: Handbook
nav_order: 12
---

# Eras — Age Frames & Named Eras

## 1. What it does & what it's for

The founder's own Timeline once read College 1990–1991 *before* High School,
and "My Teens" spanned 2007–2027. Not a display bug — the eras themselves
were dated from whatever moments keyword placement happened to put inside
them, so one long answer cited on one era page gave that era every moment's
date, and the spine sorted on the resulting nonsense. Fixing the sort order
would have fixed nothing; the dates were never real.

Eras answers a different, permanent question than Timeline's original one.
Timeline asks "when did this happen?" one moment at a time. Eras asks "what
is the *shape* of a life" — and a life has two different kinds of period at
once. It has an age you were, which nobody chooses and everybody has, the
same for every person who has ever lived past thirteen. And it has the
periods that *meant* something to you — College, the Mission, "Building
Etherfuse" — which overlap, which nest inside the first kind, and which only
you can name.

So the system now keeps both, as two separate facts instead of one hybrid
guess. **Age frames** — Childhood, Teen years, My 20s, My 30s, … — are
*calculated*: give the system a birthday and it can hand you the whole
skeleton with no further conversation, the same arithmetic for every person.
They are permanent and always visible; nothing you say can misplace one.
**Named eras** are *interpreted*: nobody can calculate that a stretch of your
life was "the Mission" or "Building Etherfuse" — you have to say so, and
having said so, that era is not up for the system to re-litigate. It may
overlap another era, and it is dated only by what you actually said about it
— never by which moments happen to be filed inside it, never by a page's own
frontmatter.

The main use case: "the timeline shows the ages of my life *and* the eras I
gave it meaning through, and Play always knows the single most valuable next
question for the era or frame I'm looking at." Controlling design:
`docs/adr/0030-eras.md` (this repo's half); the platform's half is
`lifehug-platform` `docs/design/eras.md` (tracking lifehug-platform#686).

**A worked example**, used throughout this page. A person is born 1981-07-11.
Age frames need nothing more: Childhood 1981–1994, Teen years 1994–2001, My
20s 2001–2011, My 30s 2011–2021, My 40s 2021–present — five frames, computed,
never asked for. Separately, they say in conversation: *"College was in my
20s."* That is a `within` relation — a partial date, basis `calculated`,
never a bound on the frame. Later they say: *"I graduated in 2011, during
College."* That is **one date claim** (`graduated`, dated 2011) **plus one
membership assertion** (this graduation belongs to College) — two different
facts, because a date and a membership answer two different questions and
neither implies the other. The era half of this example is real today: `era
-record` (merged, O-E3, lifehug#261) creates College's identity, binds the
2011 claim to it through a deterministic resolution record, and files the
`within` relation. The membership half is design, not yet wired — no
membership writer exists on `main` yet, and `era-record` refuses a payload
that asks for one rather than silently filing five-sixths of the act.

## 2. The nouns

- **Age frame** — a calculated period node, permanent and always visible:
  Childhood `[0,13)`, Teen years `[13,20)`, then every reached decade with no
  maximum. Identity `age:self:<band>`. Never model-authored, never dated by
  anything you say — only by your birthday and the calendar. Excluded from
  the placement score, because being a particular age is not something you
  achieved. `system/cross_dating.py` (`age_frames`, `age_frame_ladder`).
- **Named era** — a meaningful, possibly overlapping interpretation of a
  stretch of your life: College, the Mission, "Building Etherfuse". Opaque,
  immutable `era_id`, seeded from the operation that created it — never from
  its label, so renaming an era can never mint a second one. `era_kind` is
  either **stretch** (a bounded interval — "the two years I lived in
  Redlands") or **thread** (a recurring presence with no natural end — "my
  photography", named for someone or something rather than a span); threads
  never get a begin/end question. Created by you in conversation, or
  migrated once from the legacy roster with no roster date imported as
  authority. **Merged** — O-E3, lifehug#261, v239: the atomic `era-record`
  writer, the deterministic event binder, and the `era` Play stage.
  Membership and display are a separate, not-yet-wired step (see below).
- **Chapter** — your own chapters-exercise narrative. Unchanged by this
  program: it renders as an overlay label on the age frames it covers, never
  replacing them (a 2026-08-22 ruling reversed: age frames are the
  permanent frame; chapters sit on top).
- **`era_id`** — the opaque, content-addressed identity every named era has
  from the moment it is created: `digest("era", creation_operation_id)`,
  where the operation id is the session/turn (or migration batch) that made
  it. Label, alias, and `era_kind` live as *separate* decision records on
  that same id, so a rename or a stretch↔thread flip never mints a new
  identity, never loses a membership, and never orphans an open session.
  **Merged** — O-E3, lifehug#261, v239 (`system/era_identity.py`).
- **Membership assertion** — one independent receipt saying "this event
  belongs to that era": `assertion_id = digest(member, era, relation,
  source_ref)`, one per piece of evidence. Two people separately telling the
  system the same graduation was "during College" produce **two** receipts
  and **one** calculated membership carrying both as evidence; retracting
  one leaves the membership standing on the other. Never derived from date
  overlap alone — the era's own bounds and an event's own date living in the
  same year proves nothing about membership. **Not yet built** — no writer
  is wired on `main`; `era-record` calls this the "O-E2 seam" and refuses a
  payload that asks for one rather than silently filing five-sixths of the
  act (`era_record.membership_writer`, error `era_membership_unwired`). No
  PR is open for it yet.
- **Display decision** — a separate receipt answering "where does this event
  *render*", never "when did it happen" or "does it belong". An event that
  belongs to three eras still needs exactly one primary location on the
  page; the display decision picks it, and picking it never touches
  chronology. **Not yet built**, same seam as membership assertion above.
- **Event resolution** — the record that binds a claim (a date you stated)
  to the era it was said about, written by a deterministic **binder**, never
  by the model: exact, case-folded, whole-label match against the era the
  conversation was already about, else every era's active label and alias.
  Two eras sharing one alias bind nothing — the claim stays unbound with a
  named `identity_uncertain` work item rather than guessing. A second active
  resolution for the same claim with no `supersedes` link is a loud refusal,
  never a silent overwrite. **Merged** — O-E3, lifehug#261, v239
  (`system/event_binding.py`).
- **Correction role** — the difference between "this document said the wrong
  thing" (a **content** correction, which rightly makes its classification
  stale until it's re-read) and "I accept what the source says, I'm just
  dating *when* it happened" (a **placement**, which must not). Filing your
  own date for a moment is not evidence the classifier's reading of the
  source was wrong, and a system that treated it as such would make the act
  of dating something the reason it vanished from your Timeline. Closed
  vocabulary `("content", "placement")`, default `content`.
  **(proposed — the O-C2 fix on `feat/eras-o-c-stale-first`, folding into
  lifehug#256)**
- **`is_current`** — the one reader gate every derived reader uses to
  exclude a classification marked stale, immediately, before any
  reclassification happens. **(proposed — O-C, lifehug#256)**
- **Occurrence subject scope** and **owner timeline relation** — two
  separate facts every event on your Timeline will carry: *who it happened
  to* (`owner`, `other_person`, `unresolved`) and *why it belongs on your
  own axis at all* (`participated`, `lived_effect`, `contextual_only`,
  `none`, `unresolved`), each with its own evidence. A stated relationship —
  a landmark `who`/`relation` answer, a roster edge — establishes *who*
  someone is to you; it is never by itself evidence that *this* event of
  theirs belongs on your Timeline. A child's birth does; an unrelated event
  in that child's life years later does not. **(design decided, not yet
  built — design §2.5/§2.6, ADR 0030 decision 7)**
- **`life_view`** — the reading a node gets once it is placed against the
  life clip: lived history inside the clip, `contradictory` when it falls
  wholly before the supported birth interval (with a Mirror row citing the
  birth claim), `future_plan` after `as_of`, or `subject_uncertain` when the
  subject itself is unresolved. Never a censorship of what was claimed —
  only how it reads. **Merged** (`system/temporal_timeline.py::_life_view`,
  OSS v238/lifehug#259).
- **`reached_frame_epoch`** — the `(count of reached frames, current band)`
  pair that the publisher's own signature covers instead of the wall clock:
  crossing a birthday boundary publishes exactly once, and re-publishing
  inside the same epoch is a semantic no-op — no new generation, no write.
  **Merged** (`system/temporal_publication.py::reached_frame_epoch`, OSS
  v238/lifehug#259).
- **`work_item_aliases`** — the derived map from legacy `temporal_anchor`
  work-item ids to their canonical form, so a bank marker or an open session
  minted before this program still resolves to the one work item Timeline,
  Mirror, and the daily queue all now share. **(proposed — O-E6,
  lifehug#262)**
- **`placement_reason`** — the additive field on every legacy-pass row
  answering "why is this here": which rung placed it, what evidence, which
  frame or era, whether a subject check ran, whether a stale classification
  was excluded. Rendered as one sentence in the existing expanded card.
  **(design decided, not yet built — design §5.3)**

## 3. How it works

**Age frames are arithmetic, not a decision.** One definition,
`cross_dating.age_frames(birth, *, as_of, death=None)`, generates every band
whose floor is at or below the person's current age — Childhood, Teen years,
then `20s`, `30s`, … with no upper row to remember to add when someone turns
100 (`age_frame_ladder` builds the ladder rather than tabulating it). A
day-grain birthday gives half-open day boundaries: an event on 2001-07-11
lands in My 20s, the same date ten years later lands in My 30s. A year-only
birthday gives plain year ranges, and an event in the boundary year overlaps
*both* adjacent frames rather than guessing which one — the system would
rather show you two honest possibilities than one confident wrong one. A
February 29 birthday clamps to February 28 in non-leap target years, and
that clamp is itself recorded in provenance
(`chronology.AGE_FRAME_CLAMP_RULE`) rather than silently applied.

**The current frame is finite, on purpose.** "My 40s" persists a real,
finite span (`2021–2031` for a 1981 birthday) with `life_clip_end:
"present"` — a view token, not a date — so the *value* never has to change
just because the calendar turned over. `present` resolves only at read
time, with an explicit `as_of` and timezone; it is never written to disk.
The publisher's own rebuild signature tracks the **reached-frame epoch**
(how many frames have been reached, and which one is current) instead of
watching the clock directly, so two publishes inside the same epoch are a
true no-op — no new generation, no write — and crossing a birthday boundary
publishes exactly once. Age frames never enter the placement score: being
forty-five is not an achievement the score should reward or withhold.

**Named eras are never dated by their contents.** This is the whole fix.
Before this program, an era's displayed span was the envelope of whatever
moments a placement pass happened to file under it — so a single long
answer cited from one era's page could pull every sentence's moments into
that era's date range, and "My Teens" could read 2007–2027 because a moment
from decades later got filed there by accident. Now an era is dated *only*
by: (1) ordinary date claims — `period_started` / `period_ended` — bound to
it through a separate **event resolution** record, never by an event's own
claim quietly becoming the era's bound; and (2) a `within` relation ("College
was in my 20s"), which yields a `possible_temporal_value` with basis
`calculated` and is never treated as a bound either. Nothing about which
moments got filed under an era, and nothing on a wiki page's frontmatter, is
ever read as a date.

**Binding a claim to an era is a deterministic act, never a model guess.**
When you say "I graduated in 2011, during College," the listener emits the
date claim and an `event_mention` — the literal words naming the era — and
the claim is filed immediately, immutably, on its own. A separate binder
then does exact, case-folded, whole-label matching against the era the
conversation was already about, then every era's active label and alias
records. If your vocabulary is ambiguous — two eras share one alias — the
binder does not guess; it leaves the claim unbound and mints a named
`identity_uncertain` work item citing both eras. A claim can never end up
resolved to two different eras at once: resolution is its own superseding
record, the fold always takes the newest active one, and a second active
resolution appearing without a `supersedes` link is a loud refusal rather
than a silent pick.

**Membership will be evidence, not overlap — once its writer exists.** The
design is settled and the atomic writer already reserves the step: an event
belonging to an era is meant to be a separate fact from the event having a
date that happens to fall inside the era's span, with two independent
membership assertions for the same event/era/relation collapsing into
**one** calculated membership carrying both as evidence, and a display
decision as a third, still-separate fact for *where* an event renders. None
of that is wired yet — `era-record` refuses the whole act, loudly, if a
payload asks for a membership it has no writer for, rather than filing the
identity and claims while quietly dropping the membership (the ADR 0021
shape: fail loud, never silently do less).

**One atomic writer, replay-safe.** Every named-era write that *is* wired
today — creating the identity, filing a label or kind decision, binding and
filing claims, and filing a `within` constraint — happens inside **one**
vault-mutation job, `era-record`, ending in a publish. Every step is
idempotent: replaying the same operation mints no second identity and no
duplicate claim. A job that dies partway through is retried under the same
mutation id and finishes clean, because identity is content-addressed at
every layer down to the operation that created it.

**Classification is finally live on the hosted platform, and it degrades
honestly.** A newly ingested or corrected source is queued as a targeted
classify job; compile stays zero-model and proceeds without it; success
writes a classification and triggers the next compile/publish; a correction
marks a classification `stale` and every derived reader excludes it
*immediately*, through the single reader gate `is_current`, never waiting
for reclassification; a model outage parks the job and never restores a
known-stale reading just because nothing else is coming. And **a placement is
not a content correction**: dating a moment you accept is not the same act
as telling the system a source got something wrong, so a `timeline-place`
correction carries `correction_role="placement"` and, alone among
corrections, does not mark its source's classification stale — otherwise
the act of dating a moment would be the reason it disappeared from view.

## 4. The algorithm

**The age-frame ladder** (`age_frame_ladder`, `system/cross_dating.py`):

| Band | Low age | High age (exclusive) |
|---|---|---|
| Childhood | 0 | 13 |
| Teen years | 13 | 20 |
| My 20s | 20 | 30 |
| My 30s | 30 | 40 |
| My *k*0s | 10*k* | 10*k*+10, every reached *k* ≥ 2 |

<!-- parity: cross_dating.AGE_FRAME_DECADE_FLOOR = 20 -->
<!-- parity: cross_dating.AGE_FRAME_DECADE = 10 -->
The two fixed bands (Childhood, Teen years) end where the decade ladder
begins at 20 and repeats every 10 years thereafter, generated rather than
listed so there is no maximum age to forget. `start_k = add_years(birth,
low)`, `end_k = add_years(birth, high)`, exclusive — `chronology.add_years`
preserves the birthday's own grain and applies the Feb-29 clamp under rule
<!-- parity: chronology.AGE_FRAME_CLAMP_RULE = age-frame:1 -->
`AGE_FRAME_CLAMP_RULE`. A frame is *reached* the instant its start is at or
before `as_of` (or before an owner's own death claim, which clips the clock
early and mints no frame after it).

**The era-record ladder** (merged, O-E3, lifehug#261, v239): one JSON payload
— `{era_id?, label?, aliases?, era_kind?, claims, within?, memberships?,
session_ref, turn_ref, message_text}` — walks, inside one vault-mutation job:
ensure identity → label/kind decision records → bind and file claims → file
the `within` constraint → *(memberships, when a writer exists — today the
whole act is refused if any are asked for)* → publish. Every step's identity
is content-addressed over its own inputs, so a partial failure retried under
the same mutation id converges without duplicates at any layer.

**Event binding, in order:** (1) exact case-folded whole-label match against
the era the session already has open; (2) failing that, exact match against
every era's active label/alias records; (3) an alias shared by two eras
binds nothing and mints `identity_uncertain`, naming both. A claim's
resolution is a record separate from the claim itself, so a later
reprocessing pass can supersede a binding — it can never silently create a
second, conflicting one.

**The schema (additive, v2).** `CalculatedTimelineNode` gains
<!-- parity: temporal_projection.PROJECTION_SCHEMA_VERSION = 2 -->
`node_kind: "period"` for both age frames and named eras, plus
`temporal_state`, `definition_span`, `life_clip_end`, `observed_envelope`,
`possible_temporal_value`, `occurrence_subject_scope`,
`owner_timeline_relation`, `origin_basis`, and `legacy_refs`.
`CalculatedMembership` is a new top-level key carrying `relation`
(`within | overlaps | starts_in | associated_with`), `basis`, `confidence`,
`evidence_refs`, and `display_role` — populated by O-E2's fold: frame
arithmetic (`cross_dating.frames_touching`) for age frames, the union of
active `era_membership` receipts for named eras, and one `display_role`
decided over both.
The calculation rule version moves to
<!-- parity: temporal_timeline.CALCULATION_RULE_VERSION = timeline-rules:3 -->
`timeline-rules:3` so a reader can tell, from the payload alone, whether it
is looking at the pre-Eras, age-frames-only, or membership-and-relevance
shape.

**Legacy identity, never legacy authority.** A roster row whose name is a
canonical band spelling (`My 20s`, `Childhood`, …) contributes *aliases*
only — `timeline.legacy_period_ref(ref)` is the one map from a legacy slug
(`period:my-20s`, `tl:my-20s`, `band:my-20s`) to the frame's node id, read by
every `?play=` deep link, zoom key, session plan, and pin. No roster
`chrono`, `approximate_dates`, or source is ever imported as an age frame's
authority; the frame's dates come only from arithmetic on the birthday.

## 5. In the loop

Per answer: a birth claim, an age statement, or an era-scoped date claim
files exactly where every other landmark and timeline claim files — through
the ordinary durable path, immutable, immediately. The fold recomputes on
every read: correct a birthday and every age frame re-derives with it, with
nothing to migrate and no repair job, because nothing about a frame is ever
stored except the receipts that produced it.

**Play moves from the moment to the era.** Where Play used to offer one
question per undated moment, it now offers one ▸ per era and one per age
frame, each asking the single most valuable question for that period right
now: first its own bounds (if it's a stretch and still unbounded), then the
residence chain inside it, then the highest-leverage still-undated moment
inside it, and precision only while it stays cheap. Per-moment Play rows
retire from the page over one version. A moment with no era still keeps its
own direct correction path — its card, drag, and "Talk about this" — and is
never auto-guessed into an era just because Play no longer offers it its own
row.

**Weekly**, the classify step finally runs for real on the hosted platform:
a newly ingested or corrected source is queued as its own targeted job
rather than silently skipped, and the founder's own 255 unclassified
sources are the first workload once that path exists — a separate,
progress-tracked gate from Eras certification itself, never folded into it.

## 6. Where it lives

| Concern | Location |
|---|---|
| The age-frame arithmetic | `system/cross_dating.py` (`age_frames`, `age_frame_ladder`, `age_frame_legacy_slugs`) |
| The birth-origin seeding | `system/temporal_timeline.py` (the fold's subject grouping for `birth`/`self`) |
| The publication signature and epoch | `system/temporal_publication.py` (`reached_frame_epoch`, `publish`) |
| The calculated schema | `system/temporal_projection.py` (`CalculatedTimelineNode`, `PROJECTION_SCHEMA_VERSION`) |
| The legacy alias map | `system/timeline.py` (`legacy_period_ref`) |
| The era identity + label/kind records | `system/era_identity.py` — merged, O-E3, lifehug#261 |
| The event binder | `system/event_binding.py` — merged, O-E3, lifehug#261 |
| The atomic era writer | `lifehug.py era-record` → `system/era_record.py` — merged, O-E3, lifehug#261 |
| The era Play stage | `system/timeline_interaction.py` (`ERA_STAGE`, `VALID_TIMELINE_STAGES`) — merged, O-E3, lifehug#261 |
| Membership / display writers (**not yet built**) | `era_record.membership_writer` names the seam (`era_membership`, `era-member`, `era-display`); no PR open |
| The classification reader gate (in flight) | `system/classify_story.py` (`is_current`) — O-C, lifehug#256 |
| The correction-role vocabulary (in flight) | `system/lifehug_core.py` (`CORRECTION_ROLES`, `correction_role_marks_stale`) — folded into lifehug#256 |
| `work_item_aliases` (in flight) | O-E6, lifehug#262 |
| Durable era records | `sources/eras/era-<24hex>.md`, `sources/eras/era-<24hex>/labels/`, `.../kind/`; membership/display paths reserved, not yet written |
| Controlling design | `docs/adr/0030-eras.md`; platform `docs/design/eras.md` (tracking lifehug-platform#686) |
| Guard tests | `tests/test_eras_e0.py`, `tests/test_eras_e0a.py`, `tests/test_eras_e1.py`, `tests/test_eras_e3.py`, `tests/test_timeline_work_item.py` |

## 7. Decisions

- [ADR 0030 — Eras](../adr/0030-eras.md) — age frames as the permanent
  coordinate system, named eras as immutable interpretations, membership and
  display as separate durable inputs, and the Timeline as user-centric
  through stated relationship plus owner-relevant occurrence.
- [ADR 0024 — Chronology with basis](../adr/0024-chronology-with-basis.md) —
  dates as intervals with a basis; unchanged and inherited.
- [ADR 0026 — Cross-dating](../adr/0026-cross-dating.md) — the containment
  join that a named era's `within` relation and its membership both build
  on.
- [ADR 0027 — The placement score](../adr/0027-the-placement-score.md) — why
  age frames, which cost nothing to know, are excluded from it.
- [ADR 0028 — The landmark recorder](../adr/0028-the-landmark-recorder.md) and
  [ADR 0029 — The general listener](../adr/0029-the-general-listener.md) —
  the same recorder loop the era recorder reuses (purpose `date_record`, no
  new purpose minted for eras).
- [The Timeline & Chronology](timeline.md) — the page and the pass this
  program's model sits on top of.
