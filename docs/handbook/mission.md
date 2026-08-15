---
title: The Mission & the Convergence Principle
parent: Handbook
nav_order: 3
---

# The Mission & the Convergence Principle

## 1. What it does & what it's for

Every other page in this handbook describes a mechanism — a scoring
formula, a lifecycle, a weekly step. This page describes the thing every
one of those mechanisms is *for*, and the rule that binds all of them
together so that none of them can quietly stop working.

Concretely: `system/mission.md` is the file every generation prompt in
the system is built against. When the weekly classifier reads a fresh
answer and decides whether a candidate question is worth proposing, when
the monthly research expander decides whether a new neighborhood is worth
opening, when the question-judgment rubric decides whether a candidate
clears the bar — all three are checking the same thing first: does this
serve the mission. And separately, `system/mission.md` states a rule
about *how* the whole system is allowed to be built, not just what it's
for: the Convergence Principle. It says every autonomous stage must work
for a user who never opens a review screen, and every manual decision
that user *could* make must be real, consumed signal if they do. This
page is where both live, together, because in practice they're one
document and one governing idea.

The main use case: a contributor is about to design or review a new
autonomous stage (an ADR, a PR contract, a new interaction). Before
writing a line of code, they check this page's classification table.
Does the new stage have a floor — a path that converges without any
human touching it? Does it have an accelerator — a way for an engaged
owner's decisions to speed the same convergence up, never to unlock a
different behavior? If either answer is no, the design isn't done yet;
per ADR 0006, that gap is a defect, not a stage to fix later.

## 2. The nouns

The **mission** is `system/mission.md`'s three stated purposes (below).
It is not a slogan file — `classify_story.py`, `research_expand.py`, and
`interactions/question_judgment/prompt/behavior.md` all read from it, and
the question-judgment rubric's **mission test** (see the
[Interaction Pattern](interactions/) and its
[Question-Judgment page](interactions/question-judgment.md)) makes it the
literal admission gate a candidate question must clear before craft or
priority are even considered.

**For AI Prompts** is `system/mission.md`'s own name for its most
concrete section: a direct instruction that every prompt, classification,
neighborhood, and planner decision should serve at least one of the three
purposes, plus the conversation-starter methodologies (oral history,
vulnerability games, philosophical self-examination, escalating intimacy,
therapy frameworks, faith/spirituality prompts) the system draws its
question craft from. In practice this section is the mission's own test
for itself: read literally, "if a question doesn't help someone
understand the author, help the author tell their story, or help the
author understand themselves — it's the wrong question" is the one-line
version of everything else on this page.

The **Convergence Principle** (ADR 0006, owner-ratified 2026-08-14) is
the rule binding every autonomous Loop stage, stated as two tiers of one
mechanism:

- The **floor** — answering alone must converge. Every autonomous stage
  (candidate promotion, Focus creation, entity graduation, queue
  planning) has a no-human path; a stage that silently requires manual
  input to make progress is a defect against this principle, not a
  design choice.
- The **accelerator** — manual signals are optional and multiplicative.
  An engaged owner who promotes, dismisses, gives reasons, or chooses
  Focuses does not unlock different behavior; they speed up the same
  convergence. Every manual affordance is an accelerant, never a
  dependency, and every explicit decision is signal the loop must
  actually consume.

A **"never without you" posture** is the specific anti-pattern the
principle names: a feature description or a piece of UI copy stating
that something can only happen if a human acts (Focus creation was
exactly this before [ADR 0011](https://github.com/lifehug/lifehug/blob/main/docs/adr/0011-focus-autopilot.md)).
ADR 0006's corollary reclassifies every one of these as an **override
default** — the system may act autonomously within stated policy, and
the owner's explicit decision always wins, but the posture itself is
never allowed to be a hard gate.

**Parked-for-a-human work** is the principle's other named failure mode:
something sitting in a queue with no autonomous path forward and no real
affordance for a human to act on it either — stranded on both sides. The
corollary requires it to either resurface autonomously or be reachable by
a genuine affordance; it may never simply strand. The
[Question Candidates](question-candidates.md) page's structural-vs-score
park distinction (§3 there) is the clearest worked example of this
corollary in the code: a structurally-parked candidate waits in the
viewer's Review lane (a real affordance), never in a spot nobody can
reach.

Shared vocabulary this page relies on without redefining: **[The
Loop](glossary.md)**, **[In the Loop](glossary.md)**, and
**[Interaction](glossary.md)** are defined once in the
[Glossary](glossary.md).

## 3. How it works

This page adapts the template: there is no lifecycle, clock, or file
format to walk through the way a feature page would — the mission is a
static document read by prompts, and the Convergence Principle is a
constraint checked at design time, not a runtime process. What replaces
"how it works" here is **how the principle is actually verified**,
because a governing rule that nothing checks is just a good intention.

The verification is per-stage, not automated as one suite: each ADR that
introduces or amends an autonomous stage states its own floor and
accelerator explicitly, and this page's §4 table is the cross-stage
summary. There is no single test that walks every Loop stage and asserts
"this one has a floor" — the closest thing is the Loop-audit acceptance
criterion ADR 0006 itself names (`lifehug-platform#410`, on the hosted
platform, a sibling repo this page cross-links but does not own): for
each stage, does it close without a human? Within this repo, the
discipline is textual — an ADR's Decision section, and this handbook's
classification table, are where a reviewer checks the claim.

**Status note, said honestly.** `system/mission.md` itself is still
marked a draft as of this page (awaiting full ratification, tracked in
lifehug#126, which shipped the draft text in Wave 1 of the Conversation
Interaction and has since merged — but merging the file that says "draft"
is not the same as the draft status being lifted). The Convergence
Principle section specifically is **not** waiting on that: ADR 0006
itself carries `Status: Accepted (owner-ratified in design session,
2026-08-14)`, independent of the surrounding file's overall status. This
page treats the Principle as binding and the rest of `mission.md` as
draft-but-in-force (every generation prompt already reads it) — the
distinction that matters for a contributor is that the three purposes and
the Convergence Principle can be cited today; the file's remaining prose
may still change wording before final ratification.

## 4. The algorithm

There is no formula here — this section is the one place in the
handbook's template that doesn't transplant, and rather than pad it with
a formula that doesn't exist, this page says so and gives the actual
governing artifact instead: the classification table every other feature
page's own §5 cites back to.

### The floor/accelerator classification, by feature

| Feature | Floor (no human required) | Accelerator (owner signal, never a dependency) |
|---|---|---|
| [Question Candidates](question-candidates.md) | Weekly **auto-promotion** — every eligible candidate is re-scored and the highest scorers cross the auto-promote bar unattended, every week, under a dynamic cap. | The owner's **promote / dismiss / defer / park review verbs** (`candidates-review` / the viewer's Review lane) — plus, via [Decisions & Learning](decisions-and-learning.md), those decisions becoming an Owner Judgment Signals block in generation prompts and a bounded weekly rubric amendment. |
| [Focuses & the Autopilot](focuses.md) | Monthly **`focus_autopilot()`** — approves the single highest-scoring pending idea itself, through the same `approve_recommendation()` path a human uses, whenever the developing set is thinner than target. | The owner's **approve / dismiss / `focus-merge`** — manual approval works identically and unlimited, any time; a dismissal is a permanent veto the autopilot can never override; `focus-merge` (ADR 0012) heals existing duplicates the autopilot has no reason to touch. |
| Entities & graduation *(page not yet written — see [index](index.md))* | Automatic **entity graduation** — an AI-curated roster resolves mentions into entities and compile graduates each page-eligible, unmapped one into a node page past its real-mention bar, unattended. | The owner's **`entity-verdict graduate\|never\|clear`** ([ADR 0013](https://github.com/lifehug/lifehug/blob/main/docs/adr/0013-entity-owner-verdicts.md)) — a settled verdict on the roster record that forces eligibility true or false permanently, surviving every future refresh including one that omits the entity entirely. |
| [The Interaction Pattern](interactions/) → [Question-Judgment](interactions/question-judgment.md) | The judgment **rubric itself** — `load_judgment_rubric()` injects the full, never-truncated craft rubric into both generation prompts unattended, every time a candidate is generated, whether or not anyone ever reviews anything. | The weekly **RUBRIC-EDIT** pass ([Decisions & Learning](decisions-and-learning.md)) — the owner's decisions become, at most, one bounded, evidence-cited amendment to `learned.md` per week; a genuinely empty week produces no amendment, by design. |

Reading the table as one shape: every row's floor is a scheduled or
per-event process that needs zero owner attention to keep the wiki, the
question bank, and the Focus roster growing correctly. Every row's
accelerator is real, consumed, and bounded — never a rewrite of the
underlying mechanism, never a dependency the floor secretly needs. A
vault where the owner never opens a review surface still converges,
row by row, to the same place a vault whose owner reviews everything
converges to — just more slowly on the rows where a human's judgment
would have sped things up.

### Worked example: reading one row against the principle's own test

Take the Focuses row. Before [ADR 0011](https://github.com/lifehug/lifehug/blob/main/docs/adr/0011-focus-autopilot.md),
Focus creation was approval-only — exactly the "never without you"
posture ADR 0006 named as the principle's motivating gap. Applying the
test: does a passive user, who only ever answers questions, ever get a
new Focus? Before ADR 0011: no — floor absent, a genuine defect.
After ADR 0011 (and its 2026-08-15 monthly-cadence amendment): yes, at a
gentle one-per-month pace, gated only by a target count and a score
floor — floor present. Does an engaged owner's manual approval still
work, identically, any time, unlimited? Yes — accelerator present, and a
dismissal remains a permanent veto the autopilot can never override, so
the accelerator never became a dependency either. Both halves of the test
pass, which is why [ADR 0011's Consequences](https://github.com/lifehug/lifehug/blob/main/docs/adr/0011-focus-autopilot.md)
describe it as retiring the gap ADR 0006 named, rather than merely
mitigating it.

## 5. In the loop

This section, too, adapts: this page doesn't have a place *in* the Loop
the way a feature does — it's the standard every Loop stage is checked
against, not a stage itself. What feeds it is every ADR that introduces
or amends an autonomous mechanism; what it feeds is every one of those
ADRs' own Decision sections, which must state a floor and an accelerator
or explain why one doesn't apply. Its own self-improvement is textual: an
ADR that gets the classification wrong is a design defect caught in
review, not a runtime bug caught in production.

**Classification:** this page does not classify itself as floor or
accelerator — it is the definition those two words come from. The
closest true statement is that the mission's three purposes are
inspected on every single candidate, every week, by the deterministic
craft checker and the generation prompts alike (a floor-level check with
no human in the path), while the Convergence Principle's actual
enforcement — did this ADR's stage get a floor — is itself an
accelerator: a design-time human judgment (the reviewer, the owner) that
speeds up getting the classification right, never a requirement for the
mission text to exist or be read.

## 6. Where it lives

| Concern | Location |
|---|---|
| The mission document (three purposes, Convergence Principle, For AI Prompts) | `system/mission.md` |
| Convergence Principle ADR | [`docs/adr/0006-convergence-principle.md`](https://github.com/lifehug/lifehug/blob/main/docs/adr/0006-convergence-principle.md) |
| Mission test applied to candidate judgment | `interactions/question_judgment/prompt/behavior.md` (Objectives section) — see [Question-Judgment](interactions/question-judgment.md) |
| Generation prompts that read the mission | `system/classify_story.py`, `system/research_expand.py` |
| Per-stage floor implementations cited in §4's table | `question_candidates.auto_promote_candidates()`, `recommend_focuses.focus_autopilot()`, `entity_roster.normalize()` / `wiki_compile.plan_entities`, `question_judgment.load_judgment_rubric()` |
| Per-stage accelerator implementations cited in §4's table | `question_candidates.update_candidate()` (`decision_reason`), `recommend_focuses.approve_recommendation()` / `dismiss_recommendation()` / `focus_merge.py`, `entity_verdict.py`, `question_judgment.run_weekly_edit()` |
| The platform-side Loop-audit acceptance criterion ADR 0006 names | `lifehug-platform#410` (external repo — the platform orchestrates this package, never forks it) |

**Change-safely notes.** A new autonomous stage's ADR must state its
floor and accelerator explicitly in the Decision section — this page's
§4 table is a summary of those statements, not an independent source; if
a future ADR's classification and this table ever disagree, the ADR is
the authority (per the [home page](../)'s "raw record" rule) and this
table has drifted and needs a follow-up edit. There is no parity test
for this table (it quotes no live numeric constant — the "1 per run" /
"8.0 floor" style numbers already live, annotated, on each feature's own
page), so keeping it current is a review discipline, not a CI gate.

## 7. Decisions

- [ADR 0006 — The Convergence Principle](https://github.com/lifehug/lifehug/blob/main/docs/adr/0006-convergence-principle.md) — this page's central artifact: the floor/accelerator mechanism, the "never without you" corollary, and the parked-work corollary.
- [ADR 0011 — Focus Autopilot](https://github.com/lifehug/lifehug/blob/main/docs/adr/0011-focus-autopilot.md) — §4's worked example: the first stage ADR 0006 names by name as retiring a floor gap.
- [ADR 0013 — Entity owner verdicts](https://github.com/lifehug/lifehug/blob/main/docs/adr/0013-entity-owner-verdicts.md) — the entities row of §4's table: the accelerator/veto pairing for graduation, explicitly modeled on the same principle.
- [ADR 0007 — The Question-Judgment Interaction](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md) and [ADR 0009 — Decisions Feed The Loop](https://github.com/lifehug/lifehug/blob/main/docs/adr/0009-decisions-feed-the-loop.md) — named outright in ADR 0006 as concrete instances of the principle; covered fully in [Decisions & Learning](decisions-and-learning.md).
- lifehug#126 — the Wave 1 PR that shipped `system/mission.md`'s current draft text; full ratification of the file's remaining prose is still open, per §3's status note.
