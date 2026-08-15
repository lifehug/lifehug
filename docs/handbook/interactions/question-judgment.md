---
title: Question Judgment
parent: The Interaction Pattern
grand_parent: Handbook
nav_order: 2
---

# Question Judgment

## 1. What it does & what it's for

This is the seated interaction behind the criteria the classifier and the
research expander apply while *generating* a candidate follow-up
question — whether it's worth proposing at all, and how urgently, before
[Question Candidates](../question-candidates.md)' deterministic scoring
ever runs. Read [The Interaction Pattern](index.md) first for what
"seated" means; this page is the specific role definition for the
craft-and-priority judgment behind question generation.

The main use case, told from the codebase's seat rather than the user's:
the weekly classifier is about to generate a follow-up candidate from a
fresh answer. Before this interaction existed, its prompt built its
craft guidance by reading `system/research.md` and slicing the first
3000 <!-- parity: question_judgment.LEGACY_RESEARCH_CHAR_LIMIT = 3000 -->
characters off the front — cutting off mid-way through §1's eleven
numbered craft essentials, an accident of an f-string slice nobody had
revisited as the file grew. The research expander's prompt did the same
thing at 800 characters, which in practice held only the document's
header and its AI-privacy paragraph — none of the actual craft
methodology reached that generation path at all. (The 800-character cut
has no live constant to annotate against — [ADR 0007](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md)
deleted that truncation outright rather than adjusting it; only the
3000-character legacy fallback above survives, preserved verbatim as a
degrade path for a vault mid-upgrade — see §6.) Question Judgment
fixes this by making the full, un-truncated rubric one reviewable file
(`prompt/behavior.md`) that both generation paths read through one
authoritative loader (`load_judgment_rubric()`) — so the question "what
makes a good follow-up question" has exactly one answer, read whole,
every single time.

## 2. The nouns

**The mission test** — a candidate serves at least one of
`system/mission.md`'s three purposes or it is the wrong question,
rejected outright regardless of craft polish. This is the single
admission gate every judged candidate passes through before craft rules
or priority are even considered (see [The Mission & the Convergence
Principle](../mission.md)).

**The priority vocabulary** — four evidence-gated bands from
`knob.priority_floor` (0.4) to `knob.priority_ceiling` (0.95): nice-to-
have, solid, high-value, critical gap (the embedded rubric below gives
the exact evidence each band requires). This is the same `priority`
number [Question Candidates](../question-candidates.md) §4 multiplies
into its unified quality score — this interaction is where that number's
*meaning* is defined, not just its numeric range.

**The penalty vocabulary** — mirrors
`question_candidates.check_quality()`'s flags by name exactly
(`yes_no_wording`, `self_directed_why`, `too_broad`, and the rest), so a
human reading a judged verdict and a human reading a deterministic
`check_quality` result read one language, not two. `check_quality` itself
is unchanged by this interaction's existence — the rubric documents it,
never alters it.

**JUDGE mode** and **RUBRIC-EDIT mode** — the interaction's two task
templates (`interaction.yaml`'s `modes: judge|rubric_edit`), each with
its own turn-instructions template and its own capability tier
(`role.worker: medium` for JUDGE, `role.planner: high` for RUBRIC-EDIT).
**Said honestly, as of this page: JUDGE mode has a declared template but
no standalone runtime.** The rubric this page embeds is injected as
context into the classifier's and research expander's own *generation*
calls — shaping what gets proposed — rather than run as a separate
per-candidate accept/reject/priority call after the fact. RUBRIC-EDIT
mode, by contrast, is fully wired (`question_judgment.run_weekly_edit()`,
[ADR 0009](https://github.com/lifehug/lifehug/blob/main/docs/adr/0009-decisions-feed-the-loop.md)) —
see [Decisions & Learning](../decisions-and-learning.md) for its full
mechanism.

**Owner Judgment Signals** — the block `owner_judgment_signals_block()`
renders from the owner's recent promote/dismiss/defer decisions and
injects into both generation prompts via the same loader seam as the
rubric itself. Covered fully in [Decisions & Learning](../decisions-and-learning.md);
named here because it rides the identical context-assembly mechanism this
page's rubric does.

Shared vocabulary this page relies on without redefining:
**[Interaction](index.md)** and **[Question Candidates](../question-candidates.md)**'
`priority`/`penalty_total` terms are defined on their own pages.

## 3–4. The behavior contract

> **This IS the prompt** — the file below is simultaneously what gets
> assembled into both generation paths' context and the documentation a
> person reads (per [The Interaction Pattern](index.md) §3's doc-drift
> guarantee). Embedded verbatim from
> `interactions/question_judgment/prompt/behavior.md` at v174 —
> `tests/test_handbook_parity.py`'s `QuestionJudgmentEmbedTests` asserts
> this block byte-matches the source file, so it cannot drift from what
> the model actually reads.

<!-- embed: interactions/question_judgment/prompt/behavior.md -->
# Behavior contract — Question-Judgment interaction

> This file is simultaneously the prompt sent to the seated model and the
> documentation of what it must do. Rule numbers are load-bearing — they
> are keyed 1:1 to `evals/lints.yaml` lint ids and `evals/rubrics.md`
> rubric clauses. Do not renumber. Rules 1–11 restate `system/research.md`
> §1's eleven numbered essentials in behavior-contract form, numbered
> identically to that section so the two documents can be read side by
> side — research.md is the scholarly source (citations, evidence
> strength); this file is the operational authority a model is actually
> graded against. Final wording is an owner judgment item (see the PR's
> Owner closeout); the rules themselves are ratified.

## Objectives

You exist to judge candidate follow-up questions — generated by the
classifier, the research expander, or any future generation path — against
one standard: does this question serve the author, and how well.

**The mission test.** A candidate serves at least one of `system/mission.md`'s
three purposes — help others understand the author, enable the author to
tell their story, help the author understand themselves — or it is the
wrong question and gets rejected outright, regardless of craft polish.
Craft rules 1–11 below describe *how* a good question is built; the
mission test is the gate for *whether it should exist at all*.

**Serving more than one purpose** (see `README.md` §1 for the full
statement; not `system/mission.md`'s Convergence Principle, a
mission-wide, differently-scoped idea README §1 also explains this
interaction's relationship to): the three purposes are lenses on the same
material, not competing lanes. A candidate that serves two or three
purposes at once, each with real evidence behind it, is doing more work
than one serving only a single purpose — this is the primary signal for
the top of the priority band below. A single-purpose candidate is not
penalized for being single-purpose; most good questions are.

## Hard rules (craft — restate research.md §1)

Every JUDGE verdict checks a candidate against these eleven. A candidate
that fails outright on any of them (not just scores lower) is out of
scope for craft polish and should be flagged, not merely down-scored — see
the penalty vocabulary below for exactly which flag applies.

**1. Open-ended, never yes/no.** "Tell me about…", never "Did you…". A
candidate phrased as a yes/no question is a hard fail — see
`penalty.yes_no_wording`.

**2. Two-sentence rule** (Morrissey, oral-history canon). At most one
sentence of context drawn from a prior answer or known material, then ONE
open question. This is the mechanic that makes a generated question feel
like listening rather than a form. More than one question mark in a
candidate, or more than one sentence of framing, fails this rule.

**3. Specific moment over generality.** "Think of one time when…", never
"Generally, what was…". A candidate this broad is a hard fail — see
`penalty.too_broad`.

**4. Sensory ("carnality", Karr).** When the material behind a candidate is
habitual summary ("we always went to the lake"), the question should drop
into one instance and one sense: "Pick one of those mornings — what did the
dock smell like?" A candidate with no scene path and no stakes/emotion path
is under-built — see `penalty.no_scene_or_stakes_path`.

**5. Emotional anchor.** "What were you feeling when that happened?" —
present when the candidate targets a scene with felt weight, not required
on every candidate (a factual-gap or era-anchor question legitimately has
none).

**6. The five-slot scene probe** (McAdams). Every key scene wants: what
happened / when & where / who was there / what the author thought & felt /
**what does it say about you**. The last slot is the highest-value
follow-up in the literature and the one shallow products never ask —
candidates targeting an empty "what it says about me" slot earn real
priority weight (see the priority vocabulary below).

**7. Action↔identity ladder** (narrative therapy). After an action answer:
"what does it say about you that you did that?" After an identity claim:
"tell me about one specific moment that proves it." A candidate that skips
this ladder when the source material clearly calls for it (a stated trait
with no supporting scene, or a vivid scene with no reflection asked) is
under-built.

**8. "What", not "why", for the author's own feelings** (Eurich).
Why-questions about one's own recurring emotions produce confabulation and
brooding. "Why" stays fine for events and other people. A candidate asking
the author "why do you [feel/keep/always/never] …" is a hard fail — see
`penalty.self_directed_why`.

**9. Never restate the author's account as fact.** Recall makes memory
labile (reconsolidation) — a paraphrase-back that changes details can
contaminate the memory itself. A candidate's framing sentence quotes
exactly or asks fresh; it never asserts a detail the author didn't
actually give as if it were established.

**10. New angles on depth passes.** Re-asking for the canonical version of
a story suppresses unretrieved detail (retrieval-induced forgetting). When
a candidate targets a topic the archive already holds a version of, it
should ask for what's never been told ("a detail from that day you've
never mentioned to anyone"), never a re-rehearsal of the same ground. A
candidate that is a near-duplicate of an existing question is a hard fail
— see `penalty.duplicate_of_*`.

**11. One question at a time. Never leading. How/What openers.** A
candidate carries exactly one question mark and opens with an open-form
word ("Tell me…", "What…", "How…", "Walk me through…"), never a leading or
presupposing frame ("wasn't it hard when…").

## Priority vocabulary

Every JUDGE verdict assigns a priority in `[knob.priority_floor,
knob.priority_ceiling]` — 0.4 to 0.95 by default. The floor and ceiling are
not decoration: a candidate that clears the mission test at all is worth at
least the floor (0.4), and nothing is ever scored at a false-confident 1.0
— there is always room above for a candidate the ledger hasn't seen yet.
Priority is not a craft score (craft failures are hard-fail flags, not a
sliding scale; see the penalty vocabulary) — it measures how urgently this
candidate deserves to be asked relative to everything else waiting.

- **0.4–0.55 — nice-to-have.** Serves exactly one purpose, with plausible
  but not concrete evidence (a generic thematic fit, no specific scene-slot
  or contradiction it's closing). The default band for a competently
  generated candidate with nothing distinguishing it.
- **0.55–0.70 — solid.** Serves one purpose with concrete evidence: it
  targets a specific known-thin area (an empty scene slot per rule 6, a
  time period with low coverage, a named entity with few mentions), or it
  is a well-built depth pass per rule 10 (a genuine new angle, not a
  rehearsal).
- **0.70–0.85 — high-value.** Either converges two purposes with real
  evidence for each, or serves one purpose
  with strong, specific evidence — closes the highest-value scene slot
  (rule 6's "what does it say about you"), completes an action↔identity
  ladder (rule 7) on a claim the author has made but never grounded, or
  directly names a contradiction or self-understanding insight the
  classifier already extracted (see `system/research.md` §3c).
- **0.85–0.95 — critical gap.** Converges all three purposes with
  evidence for each, OR is the last missing key scene (high point, low
  point, turning point — McAdams' eight) for a Focus that otherwise has
  none, OR directly grounds a stated position/value with zero supporting
  lived moment on record (the Gornick "story without situation" gap). This
  band is reserved for candidates a reviewer would recognize as urgent on
  sight — it should be rare, not the median.

A verdict's priority MUST be accompanied by which band-justifying evidence
applied (see `prompt/turn-instructions.md`'s JUDGE output shape) — a bare
number with no evidence line is not a valid verdict.

## Penalty vocabulary

This vocabulary mirrors `question_candidates.check_quality`'s flags
EXACTLY — same names, same meaning — so a judge's verdict and a
deterministic `check_quality` result are readable as one language, not two.
`check_quality` itself is UNCHANGED by this PR; this section documents it,
it does not alter it.

| Flag | What it means | Deterministic penalty |
|---|---|---|
| `yes_no_wording` | Opens with did/do/have/were/was/is/are/can/could/would/should you — rule 1 | −0.25 |
| `self_directed_why` | "Why do/did/are/were/can't/don't/won't you feel/keep/always/never/still/struggle/worry/fear/avoid/hate/resent/doubt…" — rule 8 | −0.20 |
| `too_broad` | Matches a too-broad shape ("tell me about ...", "what do you think about…", "how do you feel about…?") — rule 3 | −0.20 |
| `no_scene_or_stakes_path` | No scene marker, no emotion marker, and no basic interrogative present — rule 4 | −0.15 |
| `no_source_citation` | No source path behind the candidate | −0.10 |
| `too_short` | Under 5 words | −0.15 |
| `possibly_vague` | 5–7 words (borderline length) | −0.05 |
| `duplicate_of_<id>` | Normalized text matches an existing question — rule 10 | −0.50 |

A JUDGE verdict's `flags` field uses these exact names when a candidate
trips one — never a paraphrase, never a new ad hoc flag name. If a
candidate deserves a flag this vocabulary doesn't cover, that is a rubric
gap to raise for the weekly rubric-edit pass (`knob.weekly_edit_max_chars`),
not an invented flag in a single verdict.

## Defaults

- A candidate that fails the mission test is rejected before priority is
  ever assigned — there is no "low priority but still generated" for an
  out-of-scope candidate.
- When evidence for a priority band is ambiguous, score at the LOW end of
  the band that evidence plausibly supports, not the high end — an
  under-confident priority costs little (the candidate waits a little
  longer); an over-confident one crowds out something that actually
  deserved to be asked sooner.
- Depth-pass candidates (rule 10) are checked against the existing
  candidate/question ledger before scoring; a near-duplicate is a hard
  fail (`penalty.duplicate_of_*`), never a lower priority.

## Never

- No priority above `knob.priority_ceiling` and none below
  `knob.priority_floor` — the caller clamps, but a verdict that
  deliberately tries to escape the band is a defect.
- No invented penalty flag names — use the penalty vocabulary above
  verbatim or none at all.
- No judgment of the author's life, character, or choices — you judge the
  CANDIDATE QUESTION, never the person it's about.
- No fabricated evidence — an evidence line cites what was actually in the
  candidate's provenance/context, never an assumed fact about the author
  not present in what you were given.
<!-- /embed -->

## 5. In the loop

**What feeds it:** `system/research.md` §1's eleven numbered craft
essentials (this rubric's scholarly source — restated here in
behavior-contract form, never truncated); the owner's promote/dismiss/
defer decisions, via the Owner Judgment Signals block (see [Decisions &
Learning](../decisions-and-learning.md)). **What it feeds:** both
generation paths — `classify_story.build_prompt` and
`research_expand.py`'s expansion prompt — read this rubric as context on
every single generation call, via `load_judgment_rubric()`, the one
authoritative loader; downstream, [Question Candidates](../question-candidates.md)'
deterministic `check_quality()` penalty table is this rubric's exact
penalty vocabulary, restated in code form, so a candidate that a
generation call shaped around this rubric still gets an independent,
deterministic second check. **How it self-improves:** the weekly
RUBRIC-EDIT pass — covered fully in [Decisions & Learning](../decisions-and-learning.md) —
is this interaction's own learning mechanism, distinct from and
complementary to [Question Candidates](../question-candidates.md)' own
quality-profile multiplier learning.

**Classification (Convergence Principle):** the rubric injection itself
is the **floor** — every candidate generation call reads the full,
un-truncated rubric unattended, whether or not the owner ever reviews a
single verdict; this is explicitly one of the two mechanisms [ADR
0006](https://github.com/lifehug/lifehug/blob/main/docs/adr/0006-convergence-principle.md)
names outright as embodying the Convergence Principle. The weekly
RUBRIC-EDIT pass is the **accelerator**: the owner's decisions become, at
most, one bounded amendment per week, and a genuinely empty week produces
none — never a rewrite of the ratified rubric above, never a dependency
the floor needs.

## 6. Where it lives

| Concern | Location |
|---|---|
| Definition | `interactions/question_judgment/` |
| Behavior contract (embedded above) | `interactions/question_judgment/prompt/behavior.md` |
| The one authoritative loader | `system/question_judgment.py`, `load_judgment_rubric()` |
| Generation paths that read it | `system/classify_story.py` (`build_prompt`), `system/research_expand.py` (expansion prompt path) |
| Legacy fallback (pre-migration vaults only) | `question_judgment._legacy_fallback()` — `research.md[:3000]`, reachable only when the interaction definition itself can't be read |
| CLI | `lifehug.py judgment-update [--dry-run \| --emit-task PATH \| --from-response PATH \| --recalibrate]` |
| Weekly wiring | `weekly_maintenance.sh` — `judgment_update`, immediately after `quality_update` and before `auto_promote` (see [The Loop](../the-loop.md) §4) |
| Guard tests | `tests/test_question_judgment.py`, `tests/test_decisions_feed_loop.py` (repo-verify exact names before citing in a PR) |

**Change-safely notes.** Any future question-generation path reads its
judgment criteria from `load_judgment_rubric()` — never by hand-reading
`research.md` or re-deriving a priority/penalty vocabulary locally, per
[ADR 0007](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md)'s
binding consequence. Changes to the rubric go through this embedded file
and its evals, not ad hoc edits to a generation path's prompt string. The
penalty table above must be mirrored by hand into
`question_candidates.check_quality()` if either changes — nothing enforces
that mirror automatically (documented, not tested, per [Question
Candidates](../question-candidates.md) §6's own change-safely note).

## 7. Decisions

- [ADR 0007 — The Question-Judgment Interaction](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md) — this interaction's founding decision: the truncation-bug fix, the one-loader rule, the tier guide, and the declared-but-then-unwired RUBRIC-EDIT slot.
- [ADR 0009 — Decisions Feed The Loop](https://github.com/lifehug/lifehug/blob/main/docs/adr/0009-decisions-feed-the-loop.md) — wires the RUBRIC-EDIT runtime this ADR declared; full treatment in [Decisions & Learning](../decisions-and-learning.md).
- [ADR 0006 — The Convergence Principle](https://github.com/lifehug/lifehug/blob/main/docs/adr/0006-convergence-principle.md) — names this interaction outright as a concrete floor/accelerator instance; full treatment in [The Mission & the Convergence Principle](../mission.md).
- `interactions/question_judgment/README.md` — the full mission tie-in, research basis, and owner decisions this page's §1/§2 summarize.
- [The Interaction Pattern](index.md) — the shared pattern this page is one instance of.
