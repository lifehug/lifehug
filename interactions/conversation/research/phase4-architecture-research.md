# Phase 4 Research: Architecting the Conversation Interaction — Model-Agnostic, Self-Documenting, Copyable

Compiled 2026-08-11. How to build a conversational AI "interaction" as files a platform loads, portable across Anthropic/OpenAI/Kimi/Qwen, self-documenting, and copyable to other surfaces.

---

## Area 1 — Conversation/dialogue architecture

- **Three-layer conversation state is the converged production shape**: (1) recent turns verbatim, (2) older turns compacted into a rolling summary, (3) durable facts extracted into STRUCTURED session state (goal, active entities, open questions) rather than buried in transcript. (Anthropic context-engineering guidance; Maxim; General Compute.)
- **Multi-turn is measurably harder**: ~39% average performance drop multi-turn vs single-turn (Microsoft/Salesforce "LLMs get lost in conversation") — fix: re-assert established facts each turn as structured state instead of trusting transcript re-derivation.
- **Compaction + note-taking** are Anthropic's named long-horizon levers; MemGPT/Letta is the reference OSS memory hierarchy (core/recall/archival — blocks are plain data owned by the app, not the vendor).
- **Async channels**: Temporal's pattern — conversation as long-lived workflow; idle timeout → auto-summarize → persist → close cleanly; resumption re-hydrates from summary + structured state, never raw replay.
- **Model-swap survival**: state stored as app-owned data (JSON session doc + summary + message log) serialized into the prompt each turn — never provider-side conversation objects (lock-in).
- *Unsettled*: exact compaction trigger; agent-managed vs harness-managed memory (for a 3-turn chat, harness-managed is obvious).

## Area 2 — Router + worker patterns

- **"Small model routes, big model talks" is converged mainstream**: ~0.5–2B classifiers reach ~90% routing accuracy; documented deployments report up to 85% cost reduction at ~95% retained quality.
- Three tiers: embedding routing (~100ms, cheapest, weak on conversational nuance) < small-LLM few-shot with structured output (200–500ms — right for "is this an answer to the pending question or a new story?") < fine-tuned small model (only at volume).
- **Failure handling**: confidence-thresholded routing with safe-default fallback. For Lifehug: unsure → treat as answer-to-pending if one exists, else ask.
- **Scope enforcement**: NeMo Guardrails' four layers (general instructions, input rails, dialog rails, output rails); OpenAI Agents SDK "input guardrails" (cheap agent classifies, tripwire blocks the expensive agent). **Key insight: the router and the scope rail are the same call** — intent classes {answer, new_story, command, out_of_scope} ARE the topical rail; out_of_scope short-circuits to a deflection template and never bills the strong model. Defense in depth: contract restates scope; evals check deflection.
- *Unsettled*: output rails rarely earn their latency in low-risk domains — practitioners rely on evals.

## Area 3 — Context engineering for per-turn assembly

- **Anthropic doctrine**: context is finite; curate "the smallest set of high-signal tokens"; distinct labeled sections; right altitude between hardcoded logic and vague guidance; diverse canonical examples over exhaustive edge lists.
- **Preload vs retrieval: hybrid** — per-user context for a chat turn (timeline slice, relevant entities, pending question, recent answers) is known-relevant/small/curated = preload; just-in-time retrieval matters for long conversations referencing arbitrary past material.
- **Lost-in-the-middle is real**: U-shaped attention; mitigations = few relevant items (top 3–5), high-value at start AND end. Layout: stable identity/contract first (primacy), background middle, current turn state + instructions LAST (recency).
- **Structured labeled blocks over prose** (`<user_timeline>`, `<pending_question>`) — better model reliability and human audit; generic delimiters for portability.
- **Provenance IDs on every block** (`[answer A14b, 2026-03-14]`) so the model can quote receipts and code can verify citations.
- **Prompt caching shapes order**: exact-prefix caching; stable content first, variable last; one unstable token (timestamp!) near the top invalidates everything after. Cache-optimal order = the same order lost-in-the-middle suggests. Settled and convenient.

## Area 4 — Prompt-as-versioned-artifact / behavior contracts

- **Git-as-registry suffices** at this scale (diffs, PR review, rollback); hosted registries only earn keep for non-engineer editing/AB tests.
- **Constitution-style specs are validated prior art**: OpenAI Model Spec's layering — **objectives (why) → hard rules (never/always) → defaults (overridable)** — doubles as an audit target; behavior can be tested against it clause by clause.
- **Cross-model portability**: reusing a prompt tuned for one model degrades on another (PromptBridge); well-structured plain-instruction prompts ≈80–90% cross-model compatible. What breaks: formatting-following fidelity (Claude RL-trained on XML; GPT/open-weight favor Markdown), system-prompt adherence strength (Kimi K2 IFEval 90.0 — strong; Qwen needs a good harness), structured-output mechanisms (OpenAI native strict JSON; Anthropic via tool-use; open-weight varies). **Portable strategy**: prompt for JSON with schema inline; native strict modes as per-provider ADAPTER optimizations; always validate + repair-retry in the harness.
- **Per-provider overlay files with only verified deltas**; canonical prompt in plain Markdown holds everything else. Hand-maintained overlays gated by evals (automated prompt transfer is research-grade).

## Area 5 — Evals for conversational behavior

- **Deterministic lints first**: banned-phrase scans, one-question-per-turn, length caps, question-grammar audits — exact, fast, free, run in CI AND at runtime; catch most prompt-change regressions before any judge runs.
- **LLM-as-judge works with mitigations**: known biases (position, verbosity, self-enhancement, inconsistency); mitigate via rubric anchors, randomized order, hidden identity, strong judge, periodic human calibration. **Rubrics test the behavior contract's clauses one at a time, binary** — not "rate 1–10."
- **Golden-transcript regression** is the converged unit: complete conversations + persona + expected PROPERTIES (not exact text); baseline locked; CI-gated.
- **Simulated users** (τ-bench lineage; persona-varied simulators) for coverage — terse users, ramblers, topic-switchers, off-scope probers — but NOT the sole gate: in τ-bench, 22% of analyzed conversations had the simulator violating its own instructions. Keep a hand-checked golden set as ground truth.
- **"Any model that passes the harness may serve"** is exactly how practitioners frame model swaps: same suite per candidate model; a model change is a PR that must go green.

## Area 6 — Preloaded vs dynamic planning + latency

- **Hybrid (planned skeleton + dynamic turns) is the converged interview-system design** (GuideLLM — LLM-guided autobiography interviewing, Lifehug's exact domain): pure scripts disengage; pure dynamic loses direction. Pre-generate the mini-arc (opening question + follow-up INTENTS e.g. "probe sensory detail", "ask who else was there"); generate actual turn text live against the transcript.
- **Pre-generation kills first-message latency**: the daily chat is system-initiated — turn 1 generated in the nightly batch = zero perceived latency. Strongest latency lever, free.
- **Streaming dominates felt responsiveness**: perception gates on time-to-first-meaningful-token (180ms first token feels faster than 600ms complete; case study: 75% perceived-latency reduction from streaming alone). Telegram equivalent: instant typing indicator + short fast message (two-stage). Prompt caching cuts TTFT on every later turn.
- *Unsettled*: planned-vs-dynamic ratio — a product-tuning question for our evals, not research.

## Area 7 — The self-documenting agent-definition pattern

- **"Agent as a directory of files" is now a multi-vendor open standard**: AGENTS.md (60K+ repos, 30+ tools); Agent Skills standard (SKILL.md + scripts/references/assets, YAML frontmatter, progressive disclosure) across Claude Code, Codex, Cursor, 20+ others. The owner's requirement has public prior art.
- **Character cards** (chara_card_v2) prove persona-as-data transfers across models/frontends; lessons: include a canonical opener and EXAMPLE DIALOGUES — few-shot examples travel across models better than abstract personality prose.
- **What makes a definition complete for a context-free model**: (1) manifest with load order; (2) purpose/why before rules; (3) hard rules separated from defaults; (4) canonical good/bad examples; (5) explicit output format; (6) explicit scope boundary with deflection spelled out; (7) progressive disclosure. The manifest prevents "discoverable-by-convention-only" gaps.
- **Docs and runtime share source** (the SKILL.md lesson): one artifact, two audiences — the README is the rationale AND points at the exact files the loader assembles; zero doc drift.
- *Genuinely novel gap*: no standard covers runtime per-user context assembly — Lifehug defines its own `context manifest` convention.

---

## (a) Recommended reference architecture: the `interactions/` pattern

```
interactions/
  conversation/                      # long, user-initiated story session
    README.md                        # what we're attempting, research basis (phases 1-3),
                                     #   how it's built, how to eval — humans AND
                                     #   context-free models read this first
    interaction.yaml                 # manifest: load order, per-block token budgets,
                                     #   model ROLES by capability tier (router/worker),
                                     #   session lifecycle (idle timeout, max turns, close)
    prompt/
      identity.md                    # persona — "if a journal was a person"; voice, canonical opener
      behavior.md                    # THE BEHAVIOR CONTRACT (Model-Spec style):
                                     #   objectives → hard rules → defaults
      examples.md                    # canonical good/bad exchanges (most portable asset)
      turn-instructions.md           # per-turn task template (assembled LAST — recency)
    router/
      router.md                      # classifier prompt: {answer,new_story,command,out_of_scope},
                                     #   few-shot cases, JSON schema inline
      deflection.md                  # polite out-of-scope response template
    context/
      manifest.md                    # which per-user blocks assemble, order, budgets,
                                     #   provenance format (the novel file)
    overlays/
      anthropic.md openai.md moonshot.md qwen.md   # ONLY verified deltas; empty = fully portable
    evals/
      lints.yaml                     # one-question-per-turn, banned phrases, grammar audit
      goldens/*.json                 # golden transcripts w/ property assertions + router fixtures
      rubrics.md                     # per-clause binary judge rubrics keyed to behavior.md
      personas/*.md                  # simulated users incl. off-scope prober
  chat/                              # short daily exchange — same skeleton, plus:
    plan/arc-template.md             # nightly pre-generation: opening + follow-up intents
```

All Markdown/YAML/JSON in git, PR-reviewed, version-tagged; session records pin the interaction version. The runtime loader (thin platform code) parses the manifest, assembles the prompt, calls providers through per-provider adapters — the ONLY vendor-aware code.

## State schema (vendor-neutral session document, DB-owned)

```json
{
  "session_id": "…", "user_id": "…", "channel": "telegram|web",
  "interaction": "chat|conversation", "interaction_version": "1.4.0",
  "status": "open|idle|closed",
  "arc": {"question_id": "…", "opening_msg": "…", "followup_intents": ["sensory_detail","who_else"]},
  "turns": [{"role":"…","text":"…","ts":"…","router":{"intent":"…","confidence":0.94},"model":"provider/model@ver"}],
  "rolling_summary": "…",
  "extracted": {"facts": [], "entities": [], "open_threads": []},
  "close": {"reason":"idle_timeout|done","summary":"…","filed_to":["timeline","entity_graph"]}
}
```

Lifecycle: open → turns → idle timeout → summarize + extract + FILE into vault (timeline/entities) → close. Later inbound = fresh session rehydrated from summary + structures, never raw replay. Per-turn model attribution = cross-model forensics for free.

## Turn loop

1. Inbound → router (small model, JSON out; unsure → safe default; out_of_scope → deflection, worker never runs).
2. Context assembly (deterministic function per manifest): stable prefix (identity+behavior+examples, cached) → user profile → timeline/entity/answer blocks w/ provenance (middle) → summary + recent turns → arc card + turn instructions (last).
3. Worker turn (strong model via adapter): stream on web; typing indicator + short fast message on Telegram.
4. Post-turn: runtime lints on generated text; state update; compaction if over budget.

## Eval harness / model gate

Per candidate model in CI: (1) lints → (2) router fixture accuracy → (3) golden property assertions → (4) per-clause binary judge rubrics → (5) persona-simulator runs (coverage, not sole gate). **Roster = whatever passes.**

---

## (b) Ranked architecture principles

1. **The interaction is files; code is only the loader.**
2. **State the app owns, serialized every turn** — never provider-side conversation state.
3. **One canonical prompt; per-provider overlays hold only verified deltas.**
4. **The router and the scope rail are the same cheap call.**
5. **The eval harness IS the model contract** — any model that passes may serve.
6. **Behavior contract in Model-Spec form** (objectives → hard rules → defaults); rubric clauses map 1:1; doc, prompt, and test share source and cannot drift.
7. **Assembly order is doubly determined — exploit it** (cache-optimal = position-optimal; one deterministic assembly function, unit-tested for prefix stability).
8. **Pre-plan the arc, generate the turn** (nightly batch opening = zero felt latency; live turns against the real transcript).
9. **Sessions close explicitly and file their output** (idle-timeout → summarize → extract → close; re-assert facts as structured state each turn — the 39% multi-turn degradation fix).
10. **Provenance IDs on every context block** (quotable receipts, verifiable citations).
11. **Deterministic lints before model-graded anything** (CI and runtime).
12. **README and runtime share source** (one artifact, two audiences, zero drift).

**Settled**: router-in-front, three-layer state, streaming, golden-set CI gating, files-as-definition, stable-prefix assembly. **Unsettled** (hold loosely, let our evals decide): compaction triggers, simulator realism, judge sample counts, automated prompt transfer, context-manifest standards.
