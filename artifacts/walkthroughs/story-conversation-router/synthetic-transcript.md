# Story → Conversation + the inbound router — synthetic interaction evidence

Deterministic transcript for issue #117 (PR #123, Wave 2 PR 4 of the
Conversation Interaction build). Synthetic names, synthetic memories,
synthetic vault. No real Telegram bot, private vault, model endpoint, or
API key was used or claimed — and nothing here reads from `~/Workspace/dave`.

Every row names the subtest that proves it. Reproduce all of it with:

```
python3 -m unittest tests.test_conversation_router -v
python3 -m unittest tests.test_ingest_and_planner tests.test_conversation_delivery -v
```

The transcript is the human-readable projection of those assertions, not
extra claims.

## Before → after, in one glance

| | The author sends an unprompted story on Telegram: "Random memory just hit me — my grandfather's old blue truck, the summer we fixed it together." |
|---|---|
| **Before (v154)** | A CLI checkmark only (`✓ Ingested story: sources/manual/…`) and four filed template question candidates. The good response — `classify_story.py` — runs async, a week later, on the weekly pass. |
| **After (v155)** | The checkmark and the four template candidates still file (the immediate-value floor is unchanged) — AND a Conversation session opens and sends ONE immediate turn: "Diesel and hay — and the summer spent side by side under the hood. Tell me about the radio you found under the seat." |

## 1. Story → Conversation, confirmed path

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | `ingest-story` durably files the source (`write_text` + `register_source`) and appends the four template candidates — unconditionally, in BOTH the confirmed and the fallback cases below | — | `test_generate_candidates_uses_source_path` |
| 2 | No open "conversation"-mode session for this channel → a session opens (`conv-…`, mode `conversation`, channel `telegram`); the story lands as the first `user` turn, tagged with its `source_path` | — | `test_story_opens_conversation_and_sends_turn` |
| 3 | Provider ready → the SAME turn engine as #116 (`conversation_delivery`) generates, lints, sends ONE Telegram message; ledger `turn:{sid}:1 = confirmed` | "Diesel and hay — and the summer spent side by side under the hood. Tell me about the radio you found under the seat." | `test_story_opens_conversation_and_sends_turn` |
| 4 | The cued follow-up is conversational only — it lives in the message and the session document, never bank-minted (unlike the answer-path's `A14 → A14a` suffix chain) | — | (contract, "Turn identity for story follow-ups"; `test_story_opens_conversation_and_sends_turn` asserts no bank id is produced) |
| 5 | A second, unprompted story arrives minutes later on the same channel — still within the idle window → it CONTINUES the same session as a further turn | "A radio under the seat — what a find." | `test_story_continues_open_session` |
| 6 | Witness accounts and opinions take the identical turn path; the source type reaches the prompt so the register matches (a witness account is another person's words; an opinion gets Socratic energy) | (register varies by source type; turn mechanics identical) | `test_witness_and_opinion_take_turn_path` |

## 2. No-session fallback — byte-identical to v154

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | Provider not ready (keyless CLI ingest, agent-task mode) | — | `test_keyless_provider_creates_no_session`, `test_keyless_ingest_is_byte_identical_to_today` |
| 2 | NO session is created at all — not even a one-turn orphan; the story-turn attempt is fully swallowed | — | `test_keyless_provider_creates_no_session` |
| 3 | Real CLI run against a synthetic vault, no API keys in the environment: stdout is EXACTLY the pre-#117 two lines, nothing else | `✓ Ingested story: sources/manual/2026-08-12-test-story.md`<br>`✓ Added candidates: cand-…` | `test_keyless_ingest_is_byte_identical_to_today` |
| 4 | A generation/lint failure while OPENING a brand-new session (no existing session yet) also creates no session — the same no-session guarantee, not just the keyless case | — | `test_definitive_failure_while_opening_creates_no_session` |
| 5 | A generation failure while CONTINUING an already-open session still records the user's story turn — only the lifehug reply is missing, per contract | — | `test_definitive_failure_while_continuing_leaves_session_without_a_reply` |
| 6 | `--dry-run` makes no provider calls and opens no session — the vault is byte-identical before and after | `would write sources/manual/…`<br>`would add 4 question candidate(s)` | `test_dry_run_makes_no_calls_and_no_session` |

`classify_story.py` still runs weekly as the deep pass, unchanged either way.

## 3. Session close — template candidates supersede

| # | Durable / system event | Status before → after | Proven by |
|---:|---|---|---|
| 1 | Four template candidates filed at ingest time, `status: candidate`, `source_path: S` | `candidate` | `test_close_supersedes_template_candidates` (setup) |
| 2 | The Conversation session closes; the turn's `extracted.candidate_ideas` (classifier-grade, `provenance: conversation`) file into the candidate store | new candidate filed, `status: candidate`, `provenance: conversation` | `test_close_supersedes_template_candidates` |
| 3 | Every template candidate whose `source_path == S` and whose status is still `candidate` flips to `superseded` — never deleted | `candidate` → `superseded` | `test_close_supersedes_template_candidates` |
| 4 | An already-PROMOTED candidate for the same source is untouched — promotion is a one-way door regardless of a later extraction | `promoted` → `promoted` | `test_already_promoted_template_is_untouched` |
| 5 | A session that closes with NO extracted candidate ideas leaves the templates live — they are still the immediate-value floor | `candidate` → `candidate` | `test_close_without_extraction_keeps_templates_live` |
| 6 | `superseded` candidates can never promote (`PROMOTABLE_STATUSES` unchanged) | — | `test_superseded_is_valid_but_never_promotable`, `test_promote_candidate_record_rejects_superseded` |

## 4. The router — `lifehug.py route`

Fixture messages, model-classified (confidence 0.95, above the
`knob.router_confidence_threshold: 0.7` default):

| Message | Intent | Confidence | Source | Action |
|---|---|---:|---|---|
| "Yeah, that was back in 2003, right after we moved to the coast." (pending question `A14`) | `answer` | 0.95 | `model` | `file_answer` |
| "Random memory just hit me — my grandmother's kitchen smell." | `new_story` | 0.95 | `model` | `ingest_story` |
| "show coverage" | `command` | 0.95 | `model` | `handle_command` |
| "Oh also, I forgot to mention —" (session open) | `continue_session` | 0.95 | `model` | `continue_session` |
| "what's the capital of Peru?" | `out_of_scope` | 0.95 | `model` | `deflect` |

Proven by `test_route_five_intents_from_model`, `test_action_mapping_is_fixed_per_intent`.

### Below-threshold and keyless — the deterministic default

| Scenario | Result | Proven by |
|---|---|---|
| Model confidence 0.4 (below 0.7), pending question `A14` exists | `source: default`, `intent: answer`, `action: file_answer` | `test_route_threshold_falls_to_default` |
| Keyless, pending question exists | `source: default`, `intent: answer`, `action: file_answer` — no model call | `test_route_keyless_deterministic_default` |
| Keyless, no pending question, a session is open | `source: default`, `intent: continue_session`, `action: continue_session` | `test_route_keyless_deterministic_default` |
| Keyless, neither pending nor open session | `source: default`, `intent: new_story`, `action: ask_user` — never guessed as one of the five without asking | `test_route_keyless_deterministic_default` |
| Malformed model output ("I am not JSON at all.") | Same default path; metadata-only diagnostic, message text never echoed | `test_route_malformed_model_output_defaults` |
| `route` called against a synthetic vault | rotation, session, and candidate files byte-identical before and after — `route` classifies, it never mutates | `test_route_mutates_nothing` |

### Live keyless smoke (anyone can run without keys)

```
$ printf 'what is the weather today?' | python3 system/lifehug.py route
{"intent": "new_story", "confidence": 0.0, "source": "default", "action": "ask_user", "pending_question_id": null, "open_session_id": null}
$ echo $?
0
```

### Deflection — classify, don't send

`route` returns `action: deflect`; the HOST sends
`interactions/conversation/router/deflection.md`'s canonical line, once:

> "That one's outside what I do — I'm here for your story. Speaking of
> which — is there anything on your mind today?"

A second consecutive off-scope message in the same exchange gets the
shorter variant, then silence — never a third deflection (behavior.md rule
4, zero-pressure). This is a prose/behavior-file rule, not code in
`route_message` itself (contract, Part B mechanics #5).

## 5. Prose-contract parity

| File | Section | Proven by |
|---|---|---|
| CLAUDE.md | "### Recognizing Answers" | `test_prose_contracts_name_five_intents`, `test_deflection_rule_named_in_all_three` |
| AGENTS.md | "## Answer Detection" | `test_prose_contracts_name_five_intents`, `test_deflection_rule_named_in_all_three` |
| skill/SKILL.md | "## Answer Processing" + "## Unprompted Story Ingest" | `test_prose_contracts_name_five_intents`, `test_deflection_rule_named_in_all_three` |

All three name the identical five intents and the `lifehug.py route`
delegation — divergence between them is a review defect, mechanically
caught rather than eyeballed.
