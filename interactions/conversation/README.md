# The Conversation Interaction — why it's built this way

This is the owner's most-important file in this PR. It is the orientation
doc for both people and models: what Chat and Conversation are, why they
work the way they do, and where every decision came from. Read
`interactions/README.md` first for the Interaction pattern itself; this
file is the "why" for one specific interaction.

## 1. Mission tie-in

This interaction's objectives derive from `system/mission.md`'s three
purposes — help others understand me, enable me to tell my story, help me
understand myself — plus the owner's mission direction (owner's words,
2026-08-11):

> "honor and increase the value of your life and your relationships — hold
> them up, cherish them, realize how impactful they are in your life."

Every hard rule in `prompt/behavior.md` traces back to one of these: a
question that doesn't help someone understand the author, help the author
tell their story, help the author understand themselves, or honor the
value of their life and relationships is the wrong question to ask, and a
response that doesn't demonstrate understanding of what was just shared is
the wrong response to give.

## 2. What Chat and Conversation are

This is the ratified nomenclature (owner-approved design, 2026-08-11; also
added to the top-level `README.md` Nomenclature section):

- **Chat** — the short exchange around the daily question: system-initiated,
  ~3 exchanges, arc-carded, a graceful third-turn exit, a closing takeaway.
- **Conversation** — a long user-initiated session (a story, "something on
  my mind", or a thread the system offered); runs the full interviewer arc;
  closes with a narrative takeaway.
- **Arc card** — the pre-planned skeleton for a chat or conversation:
  opening framing plus 2–4 follow-up *intents* (not scripted text), planned
  by the loops ahead of time, executed live per turn by the seated model.
- **Session** — one bounded run: open → turns → close; the durable record
  is the session document (`state/conversations/`, registered in PR 2).
- **Candidate placement** — an additive pre-conversation step for Answer Now:
  silently place an exact candidate from a complete closed category roster at
  high confidence, or ask one natural clarification. It is a step, not a third
  mode; ordinary Chat and Conversation prompts do not load it.

## 3. The research basis

Four research phases (compiled 2026-08-11, committed in full under
`research/`) built this interaction. Read the phase files for the evidence
— this section is a map, not a substitute.

- **Phase 1 — [what makes conversations great](research/phase1-conversation-research.md).**
  Perceived-partner-responsiveness as the engine of felt intimacy; respond
  before you ask; how professional listening changes the speaker; closings
  that land at the peak; register switching between celebration and hard
  stories. The OARS mix (open questions, affirmations, reflections,
  summaries) and the "respond before ask" discipline both come from here.
- **Phase 2 — [the payout turn](research/phase2-payout-research.md).** What
  a person must actually GET from an exchange to feel rewarded: receipt →
  register → one contribution → declinable door. Felt understanding is a
  reward-circuit event and misunderstanding is a pain-circuit event
  (asymmetric — one bad move costs more than one good move gains);
  co-witnessing (seeing what the user reveals matters, out loud, with their
  own evidence); insight claims that cite receipts across entries rather
  than asserting a pattern from nowhere.
- **Phase 3 — [elicitation craft](research/phase3-elicitation-research.md).**
  How the highest-stakes professional interviewers (ORBIT/UK
  counter-terrorism research) get people to talk: rapport and autonomy
  support, not question cleverness, set the ceiling on yield; TED-form
  question grammar (tell/explain/describe) over closed or option-posing
  questions; zero-pressure moves as a hard prohibition, not a norm; a
  do-not-use list of moves that measurably collapse yield.
- **Phase 4 — [the interaction architecture](research/phase4-architecture-research.md).**
  How to build a conversational AI as files a platform loads:
  definition/runtime/seat, three-layer conversation state (verbatim recent
  turns, rolling summary, structured durable facts), a cheap router in
  front of an expensive worker, evals as the gate on which models may run
  a role, and arcs planned ahead of time by the weekly/monthly loops so the
  daily loop can stay AI-free.

## 4. Owner decisions

The 2026-08-11 decision log ratified specific calls across the four
phases. These bind this interaction; they are not implementer discretion.

**Phase 1 (A–D):**
- **A** — the ~3-exchange chat target governs OUR initiative only; never
  hard-stop a user who keeps going.
- **B** — never name the depth ramp (concrete → narrative → meaning) to
  the user.
- **C** — the AI has no content of its own, but insight *observations*
  about the user's own material (a connection, a pattern, a continuity
  thread) are prized, not withheld out of false modesty.
- **D** — never label or discuss being an AI; compensate for the absence
  of a shared life with specificity and memory, not disclaimers.

**Phase 2 (A–D):**
- **A** — cognitive-empathy register over emotional performance for hard
  stories: demonstrated understanding, not "I feel for you."
- **B** — deposit framing (explicitly naming what this exchange added to
  the user's record) is a tunable knob, off by default, not a fixed
  behavior.
- **C** — reconnection observations ("you mentioned this before") are
  welcome, but observation-only — never a claim the user hasn't licensed.
- **D** — nourishment over engagement: never A/B-test or tune toward raw
  engagement; the target is a nourishing exchange, and a nourishing
  exchange is sometimes a short one.

**Phase 3 (A–C):**
- **A** — demonstrated-knowledge openers ("here's what I hold about the
  Ghana years — what's missing?") are introduced gradually, starting from
  small summaries before full-era dossiers.
- **B** — reactive disclosure uses the "if a journal was a person" framing
  — the AI's first-person voice is licensed only in reaction to the user's
  own material, never as autobiography.
- **C** — confirmation claims are always good-faith tentative, and the
  timeline (`timeline.compute_gaps()`) feeds conversations rather than the
  reverse.

**Cross-cutting:**
- **"Drain is not negative"** — the dividing line between a thread worth
  continuing and one to back off from is nourishing-vs-harmful, not
  happy-vs-draining; hard, sad, even heavy threads can be nourishing. Only
  rumination (going in circles without new material or movement) backs
  off.
- **Autonomy-by-default** — arcs are auto-planned by thresholds; the user
  can steer at any point but never has to do anything to keep the system
  working.
- **Zero-friction measurement** — never ask "did you enjoy this?" or
  request a rating; behavior itself (what gets answered, how much, how
  often) is the only feedback signal, exactly as the top-level README's
  daily-loop section already states for the daily question.

## 5. How it's built

- **Behavior contract**: `prompt/behavior.md` — the load-bearing file,
  both the prompt sent to the model and its documentation.
- **Candidate-placement contract**: `prompt/candidate-placement.md` plus
  synthetic shapes in `prompt/candidate-placement-examples.md`, loaded only by
  `system/candidate_placement.py`. The model proposes; the runtime validates
  exact closed-roster membership and canonical revisions and performs no
  promotion or write (ADR 0018).
- **Context recipe**: `context/manifest.md` — the deterministic per-turn
  assembly order and token budgets.
- **Arc planning**: `plan/arc-templates.md` — how the weekly/monthly loops
  produce arc cards ahead of time so live turns execute a plan rather than
  improvising from nothing.
- **Durable state**: `state/conversations/` (session documents) and
  `state/arc_cards.json` — both registered in `system/vault_contract.json`
  by PR 2 (issue #115); not touched by this PR.
- **Runtimes**: the OSS single-user turn/session runtime is
  `system/conversation.py`; `system/candidate_placement.py` is its pure,
  stdlib-only placement authority. The hosted platform loads the same
  definition and schemas.

## 6. How to eval

`evals/` is the model contract: `lints.yaml` (deterministic structural
checks — one question per turn, banned phrases, question-grammar audit,
length caps, receipt-before-question, year-question detection, plus
`router_gates.*` per-class precision/recall thresholds), `goldens/`
(golden transcripts with property assertions, `router_fixtures.json` /
`router_sample_predictions.json` for the router scorer, and candidate-
placement fixtures/predictions for the five `placement_gates.*`), `rubrics.md` (a
binary yes/no judge question per hard rule, 1:1 with `prompt/behavior.md`'s
13 rules), and `personas/` (seven simulated users whose runs must
demonstrate specific properties — e.g. the `grief-fresh` persona's runs
must show deferral, the `ruminator` persona's runs must show mid-thread
back-off).

**The eval harness (issue #120)**: `python3 system/lifehug.py
conversation-evals` runs deterministic lints, router and candidate-placement
fixture scorers, golden-transcript properties, and model-backed,
keyless-skippable placement/judge/persona layers over this directory.
`--emit-tasks` writes judge/persona agent-task prompts to
`state/agent_tasks/evals/` when no provider is configured. See
`system/interaction_evals.py`'s module docstring for the full layer
breakdown.

The model roster for `role.router`, `role.worker`, and `role.planner` is
whatever passes this harness — not a fixed vendor choice, recorded in
`evals/roster.md` with run links. **Any PR touching
`interactions/conversation/**`, a `conversation_model`/`router_model`/
`judge_model` config default, or `overlays/*` must include a harness run in
its evidence** (a local live run, or a platform interaction-evals workflow
link) — model and prompt changes gate through this evals directory exactly
like code changes gate through CI. Full README trueing is issue #121's job,
not this harness's.
