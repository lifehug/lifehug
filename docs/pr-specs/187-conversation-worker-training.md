# Contract: conversation-worker-training

Issue: [#187](https://github.com/lifehug/lifehug/issues/187) (series index [#185](https://github.com/lifehug/lifehug/issues/185); GPU gate [#186](https://github.com/lifehug/lifehug/issues/186))

## Why

The Conversation worker is seated on a rented proprietary teacher today. The defensible pile is not the vendor: it is the behavior contract, the goldens, and the eval harness. This file is the in-repo authority for *how we grow that pile and later train a worker we own*. It does not add or renumber hard rules. `interactions/conversation/prompt/behavior.md` stays the behavior bible.

A future implementer (or bot) should be able to pick up [#185](https://github.com/lifehug/lifehug/issues/185) without the originating chat.

## Binding facts

- **Seat.** `interactions/conversation` · `role.worker` only. Router and planner are other seats.
- **Authority.** `prompt/behavior.md` (doc is the prompt). Hard rules 1–13 and `evals/lints.yaml` / `evals/rubrics.md` stay 1:1. This contract does not add rules.
- **Job.** Elicit the fullest, truest telling of this person's life that they are willing to give *right now*. Stay if they keep typing. Land if they are done. Never make a short answer feel small. Reply-is-consent (rule 8, issue #139): stopping is not-replying; continuing is typing again; reopen after a close is normal.
- **Objectives (from behavior.md).** (1) Elicit the fullest, truest telling. (2) Every exchange felt understood, valued, worth returning to. (3) Honor and magnify the value of their life and relationships. A turn that serves none of these is the wrong turn.
- **Speaker-state (training-only).** Closed enum: `still_offering` | `done` | `circling` | `heavy_defer` | `skip`. Labels live on goldens / export rows. **Not** a `vault_contract` session field and **not** shown to the user unless a later ADR says so. No ADR in this series unless durable live data is added (it should not be).
  - `still_offering` — new detail, unfinished, trailing openness, explicit "what else" → receive, then one declinable door. Stay.
  - `done` — settled, no new material → declarative close. No permission sentence. No "good place to rest."
  - `circling` — same ground, brooding → distancing lens or topic door (rule 13).
  - `heavy_defer` — fresh grief / upheaval in the deferral window → frame once, do not explore.
  - `skip` — declined the ask → file it, move on, never repeat.
- **What stays in code.** Context assembly (`context/manifest.md` budgets). File every user turn. Inbound router. Arc-card *intents* (not scripts). Grief-deferral, rumination cooldown, declined-question ids. Seat gate: `python3 system/lifehug.py conversation-evals`.
- **What we refuse to babysit once the seat is green.** Hard-stop at `knob.chat_target_exchanges` (already our-initiative-only). Exit-ceremony turns (already removed). Phrase-list detection for `user_invited_question` if the model can judge it semantically. A second eval product.
- **Exam.** Layers 1–4 already exist. Layer 1 lints, Layer 2 router (not this seat), Layer 3 goldens, Layer 4 rubrics + personas. A trained worker is seated only if Layers 1 and 3 stay green and Layer 4 does not regress vs the current teacher.
- **Teacher / student.** Teacher stays proprietary (Kimi or the current seat) until #194. Student, when we train, is Qwen 7B-class LoRA. Do not fine-tune Kimi-scale weights first. First GPU run rents 24GB; Mac Studio is for later inference.
- **Research.** Phases 1–4 under `interactions/conversation/research/` plus 2026-08-11/12 owner rulings are enough craft. Do not open a fifth research phase before a model sits. Missing *data* (not papers): speaker-state labels on real written turns; lint-clean teacher traces. Never commit dave vault text to OSS.
- **Series order (do not skip to GPU).**
  1. This contract (#187)
  2. Persona golden coverage (#188)
  3. Speaker-state labels on goldens (#189)
  4. Lint-clean JSONL export CLI (#190)
  5. Preference-pair fixtures (#191)
  6. Keyless training dry-run (#192)
  7. First Qwen 7B SFT + eval report, not seated (#193)
  8. Seat only if conversation-evals pass (#194)
- **Inflection for #193.** Path A (#187–#191) plus #192 done; ~50 lint-clean worker turns; seven personas covered; preference pairs for known fails; teacher evals green. Not an inflection: "we wrote a lot of prompt files."

## Scope

**In this PR (#187):** this contract file, so later steps have an in-repo authority.

**In the series, not this PR:**
- #188 — at least one passing golden per persona (`enthusiast`, `rambler`, `terse`, `ruminator`, `grief-fresh`, `topic-switcher`, `off-scope-prober`); roster in `evals/goldens/README.md`.
- #189 — speaker-state on those goldens; unknown labels fail a unit test.
- #190 — `lifehug.py conversation-train-export` (name may vary); CI; fail-loud on lint-dirty goldens; vault export local-only.
- #191 — chosen/rejected pairs for banned closes, question-first, length-shame. `closing-scaffold-leak-bad-01.json` is the first rejected.
- #192 — dry-run recipe, no GPU to merge, no weights in git.
- #193 — rented SFT, written eval report, adapter not the live default.
- #194 — `evals/roster.md` pin only if the harness says yes; closing not-planned is a valid outcome.

**Out of this seat forever in this series:** router, planner/arc generation, question_judgment, focus_curation, candidate placement. Same conversational spine later; different heads.

## Implementation notes

- Goldens: `interactions/conversation/evals/goldens/` — one session per file; every lifehug turn must pass Layer 1 (`evals/goldens/README.md`). Seed from: `chat-farmhouse-opener-receipt`, `chat-cabin-held-question-weave`, `chat-cabin-hatch-honored`, `chat-cabin-mid-story-uninvited`, `chat-cabin-empty-supply-honest`, `chat-garden-deflection`, `conversation-lake-house-no-new-topic`, `chat-porch-swing-closing`, `chat-seattle-ferry-closing`, `chat-witness-filing-close`, `chat-promotion-closing`. Do not SFT on `closing-scaffold-leak-bad-01.json`.
- Personas: `interactions/conversation/evals/personas/`.
- Exam entrypoint: `system/interaction_evals.py` via `python3 system/lifehug.py conversation-evals`.
- Delivery method: `docs/BUILDING.md` — contract → implementation → evidence → owner review. ADR 0002 is the Interaction pattern (definition / runtime / seat).

## Test plan

This PR is docs-only. Existing tests must stay green if anything they scan includes new files (they should not).

```
python3 -m unittest discover -s tests
```

Later steps name their own commands on their issues. The series exam remains:

```
python3 system/lifehug.py conversation-evals
```

## Launch-and-verify

Not required. This PR does not touch `serve_wiki.py`.

## Definition of done

- [x] Contract committed (this file)
- [ ] Owner review of Binding facts (especially speaker-state enum and "no live session field")
- [ ] Covering issue #187 closed or commented with this PR
- [ ] Next implementer starts at #188, not #193
