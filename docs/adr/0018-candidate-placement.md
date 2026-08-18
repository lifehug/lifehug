# ADR 0018: Candidate placement is a closed-roster Conversation step

Date: 2026-08-18
Status: proposed

## Context

Issue #170 enables an AI-first Answer Now path for an exact question
candidate. Before the user can answer, the candidate must have one canonical
question-bank category. Requiring a picker first would make repository
structure the user's problem; allowing a model to invent a category, path, or
promotion result would make untrusted model output an authorization boundary.

The Conversation Interaction already owns the exchange with the user. This
placement judgment belongs immediately before that exchange, but it must not
change the ordinary Chat or Conversation prompt, create a third mode, or write
candidate, question-bank, session, vault, or Git state. The hosted platform's
issue #469 coordinator is the first full consumer.

## Decision

Candidate placement is the additive `candidate_placement` **step** in the
Conversation Interaction. Its modes remain exactly `chat|conversation`.
Candidate-only definition and example files are loaded only by
`system/candidate_placement.py`; ordinary turn, close, router, and arc builders
do not load them and retain their v180 bytes.

The runtime supplies an exact `CandidateAnchor` and a complete, ordered,
closed `CategoryRoster`. The roster has 1–64 entries and is never truncated.
The model receives those values only in an explicitly untrusted JSON data
block, gets no tools, and may propose only one exact roster `category_id`.
Candidate text, user text, category labels, and revisions are data, never
instructions. The stdlib runtime rejects unknown keys, malformed values,
duplicate or oversized rosters, forged revisions, fuzzy/case-folded matches,
and out-of-roster categories.

At confidence `>= 0.8`, a valid exact category resolves silently. Below the
threshold, the runtime clears the proposed category and accepts only one
natural clarification question that passes the existing Conversation lints
and reveals neither a category id nor a choice menu. A hallucinated category
invalidates placement only: an independently valid `turn_kind`
(`placement_only|answer|mixed`) survives, and every caller retains the exact
original user turn independently of that routing metadata. The model never
authorizes retention, deletion, promotion, or a write.

Canonical revisions are lowercase SHA-256 over UTF-8 canonical JSON. A
resolved `placement_revision` binds the candidate revision, selected category
id, and that category's revision—not the whole roster revision. Removing,
renaming, or focus-remapping the selected category invalidates the placement;
an unrelated roster addition does not. A changed candidate or selected
category returns typed invalid/stale state and is never silently substituted
or rerun.

Candidate promotion is deliberately separate. PR B of issue #170 will own
question-id allocation, question-bank/candidate writes, idempotency,
provenance, Git commits, and a structured promotion receipt. No field produced
by this PR claims that a promotion occurred.

## Consequences

- Existing callers that never invoke candidate placement keep ordinary
  Conversation behavior and rendered prompt bytes.
- Platform #469 must consume the exported builders, canonical hashes, strict
  decision schema, and gate results; it must not recreate looser schema or
  roster logic.
- A roster outside 1–64 entries fails closed instead of producing a partial
  prompt. Callers must repair the authoritative category source.
- Placement can require one extra conversational turn, but that turn may also
  contain an answer; `turn_kind` ensures a coordinator retains it instead of
  treating clarification as disposable UI state.
- This release is an intermediate upstream contract. The platform pin waits
  for PR B's final release, then reconciles both PRs together.

## Platform pin-bump reconciliation surfaces

- New module and CLI: `system/candidate_placement.py` and
  `conversation-candidate-placement-prompt`.
- Definition files: `prompt/candidate-placement.md` and
  `prompt/candidate-placement-examples.md`.
- Manifest fields: `steps`,
  `knob.candidate_placement_confidence_threshold`,
  `knob.candidate_placement_roster_max`, and
  `budget.candidate_placement`.
- Exact input, proposal, and normalized-decision schemas; phase, turn-kind,
  status, and resolution vocabularies; canonical revision recipes.
- Fixture and sample-prediction shapes plus the five `placement_gates.*`
  keys.
- v180 ordinary turn/router prompt byte hashes and untouched general
  Conversation definition files.

🤖 Generated with GPT-5.6-Sol via Codex
