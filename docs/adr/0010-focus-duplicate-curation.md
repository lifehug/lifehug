# ADR 0010: Focus Duplicate Curation — the three-layer dedupe

Date: 2026-08-14
Status: Accepted (owner-directed, 2026-08-14)

## Context

The owner's live vault carries duplicate focuses and duplicate pending
ideas: exact-name-modulo-case pairs (a "fear"/"Fear" class — two
question-bank categories, scaffolded separately, that `slugify` alone
doesn't collapse when a leading "the " differs, and that
`derive_focuses`'s per-category loop had no cross-category collision check
for at all) and token-variant pairs ("Betty Jo" vs "Betty Jo Taylor" — the
same person, referred to two ways, before either name accumulates enough
evidence on its own to look obviously redundant).

Three independent gaps let this happen. Idea extraction
(`recommend_focuses._build_entity_stats`) is regex-based with distinct raw
keys per surface-text variant it finds. Idea-level dedupe
(`recommend_focuses.recommend`) checks only exact slug/alias against
*existing* focuses — two *pending* ideas never compare against each other,
so "Betty Jo" and "Betty Jo Taylor" can both sit in
`state/focus_recommendations.json` indefinitely. No creation door
(`roadmap.focus_new`, the `roadmap` CLI's `add`, `derive_focuses` itself)
checked normalized-name collisions before this PR, so two
separately-scaffolded question-bank categories could yield two focuses
with the same identity under different id casing. Meanwhile the roster's
existing alias intelligence (`entity_roster.py`'s monthly AI curation,
`apply_previous_decisions`'s settled merges) was never consulted by the
recommendation path at all — a roster that already knows "Karen" and "Mom"
are one person did nothing to stop `recommend()` from proposing a "Mom"
Focus recommendation independently.

## Decision

Three layers, applied in order, each catching what the layer before it
structurally cannot:

**1. Door guards (deterministic, kills the case/prefix class).** One
authoritative `normalized_focus_key(label)` — lowercase, slugify, strip a
leading "the " — lives in `system/lifehug_core.py` beside `slugify`, the
one place every module that needs Focus-identity normalization already
imports from. `entity_roster.py`'s existing `_entity_keys()` (the roster's
own alias-matching key set) is refactored to build on this shared function
rather than re-deriving its own lowercase/slugify/"the "-strip logic inline
(recurring-defect doctrine, `docs/BUILDING.md` §8). Every focus-creation
door — `roadmap.focus_new`, the `roadmap` CLI's `add` subcommand, and
`recommend_focuses.approve_recommendation`'s scaffold path (which delegates
to `focus_new`) — now refuses to create a focus whose
`normalized_focus_key` collides with an *existing* focus under a different
id, raising/printing a message that names the existing focus instead of
materializing a twin. `derive_focuses` (the pure question-bank-to-focus
derivation `roadmap.rebuild_roadmap` runs on every refresh) instead *folds*
same-key focuses it derives from separate categories into one entry,
attaching the later category to the first-seen focus — the automatic,
no-human-required path, since a rebuild has no one to refuse to.

**2. Roster fold (deterministic, catches settled variants).** Before
scoring, `recommend_focuses._build_entity_stats`'s raw stats are folded
through each entity type's settled roster alias map
(`recommend_focuses._fold_stats_through_roster`, reusing
`entity_roster._entity_keys` and `entity_roster.load_roster` — never a
second alias-matching implementation): stats for keys the roster already
resolved to one canonical entity merge — evidence unioned, counts summed —
before `recommend()` ever computes a score or a `rec-<slug>` id. Two
pending ideas whose keys fold into the same roster entity emerge as ONE
recommendation. Existing duplicate *pending* records (from before this fix
existed) converge on the next `recommend()` run — the regenerate-and-expire
machinery `save_recommendations`/`apply_recommendation_expiry` already had
replaces pending state wholesale each run, so nothing extra was needed to
make stale duplicates drop out once their key folds.

**3. The Focus-Curation interaction (AI, first-encounter variants only).**
`interactions/focus_curation/` (per `interactions/README.md`'s checklist:
README, `interaction.yaml` with `role.worker: medium` and no `router/`/
`plan/`, `identity`/`behavior`/`examples`/`turn-instructions`, an empty
`context/manifest.md`-specified assembly, empty per-provider overlays,
`evals/` with `lints.yaml`, `goldens/README.md` plus one committed golden,
`rubrics.md`, and a `personas/` README stub) judges the residue neither
deterministic layer can resolve: a near-name pair (one label's token set a
proper subset of another's — the "Betty Jo" shape) that has no settled
roster alias yet. Given the pending idea list, roster context, and existing
focuses, it emits ONLY a partition —
`{merge: [[ids]], map_to_focus: {id: slug}, keep: [ids]}` — never a reason
or evidence field (see "no reason context" below). `system/focus_curation.py`
is the runtime: `build_pending_idea_list` restricts input to genuine
first-encounter near-name pairs (via `focus_dupes.near_name_pairs`, the
same shared detector §Scope-3's report command uses) minus anything already
settled in a prior run; `apply_verdicts` deterministically applies a
validated verdict — merges dismiss the losing pending record(s) with
`dismissed_by: "curation"`, maps dismiss with a structured
`mapped_to_focus` fact, keeps are no-ops — and a malformed verdict (a
dropped id, an invented id/slug, an undersized merge group, a stray key)
applies *nothing at all*, never a partial application. The keyless
convention (`--emit-task`/`--from-response`, matching
`system/entity_roster.py` and `system/question_judgment.py`) applies here
too, with one deliberate difference from both of those: **there is no
deterministic merge fallback.** Absent AI, layer 2's roster fold is the
floor — a near-name pair simply sits apart correctly rather than being
merged on a guess.

**The shared key, restated once:** `normalized_focus_key` is the *only*
place "what counts as the same Focus name" is decided across all three
layers and the report command below. Every layer either calls it directly
or calls something (`entity_roster._entity_keys`,
`focus_dupes.near_name_pairs`) that itself calls it — never a second,
independently-typed definition.

**`focus-dupes --report`** (a thin `lifehug.py` wrapper over
`system/focus_dupes.py`) is the deterministic, zero-AI, zero-write damage
list the owner's own cleanup and the future F4 focus-merge verb consume:
(a) roadmap focuses whose normalized keys collide (certain duplicates —
what a stale `roadmap.json` written before this PR's door guards existed
can still carry), (b) near-name pairs across both focuses and pending
ideas (flagged for judgment, never auto-merged), (c) pending ideas that
fold into an existing focus or into each other (certain duplicates the
roster fold has no settled alias for yet). This PR only detects and
reports existing duplicates — merging them is explicitly out of scope (the
F4 focus-merge verb's job).

**No reason context, anywhere (owner decision).** The platform removed the
dismiss-reason field entirely; this interaction's JUDGE gets no reason
history to read, and its own verdict schema carries no reason/evidence/notes
field either — a verdict with a fourth key is malformed, not more thorough.
This mirrors, and is narrower than, ADR 0007/0009's "no reason capture"
posture for `question_judgment`'s learned-amendments file — here there is
no learning file at all, only a settled-decision ledger
(`state/focus_curation/settled.json`, registered in `vault_contract.json`
as vault data) recording which ids have already been curated (merge, map,
*or* keep) so a correctly-kept-apart pair isn't re-presented to the JUDGE
forever. This is a deliberate simplification: once an id is settled in any
bucket it is never re-presented, even if it would later form a genuinely
new near-name pair with a different idea — convergence over a theoretical
missed re-judgment.

**Conversational future.** The owner has separately directed (platform
issue lifehug-platform#469) that dismiss/decision reasons eventually
become part of an ordinary conversation rather than a form field — this
PR's "no reason capture" posture is consistent with that direction, not a
contradiction of it: nothing here builds a reason-text field that would
need to be un-built later.

## Consequences

- **Binds**: any future focus-creation path (the platform's own Focus
  creation surface included, when it ports this — cross-medium parity)
  checks `normalized_focus_key` collisions before creating; any future
  entity/alias-matching code reuses `entity_roster._entity_keys` /
  `lifehug_core.normalized_focus_key` rather than re-deriving
  lowercase/slugify/"the "-strip logic inline.
- **Forecloses**: a deterministic fallback that merges focuses or ideas on
  a guess when AI is unavailable — the roster fold is the only
  no-AI-required merge path, by design; any reason/evidence field on a
  focus-curation verdict or a dismissed pending-idea record.
- **Delete-when**: if a future PR builds the F4 focus-merge verb (merging
  *existing* duplicate focuses, not just detecting them), this ADR's
  Decision continues to hold — that PR consumes `focus-dupes --report`'s
  output, it doesn't supersede this dedupe design. If a future PR unifies
  `focus_curation` and `question_judgment` (or any other interaction) into
  one shared judgment primitive, this ADR's Decision would be superseded
  by whatever ADR ratifies that merge.

🤖 Generated with Claude Fable 5 via Claude Code
