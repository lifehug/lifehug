# Conversation turn engine — synthetic interaction evidence

Deterministic transcript for issue #116 (PR #122). Synthetic names, synthetic
memories, synthetic vault. No real Telegram bot, private vault, model
endpoint, or API key was used or claimed — and nothing here reads from
`~/Workspace/dave`.

Every row names the subtest that proves it. Reproduce all of it with:

```
python3 -m unittest tests.test_conversation_delivery -v
```

The transcript is the human-readable projection of those assertions, not
extra claims.

## Before → after, in one glance

| | The author answers "What did the farm smell like?" |
|---|---|
| **Before (v152)** | **Message 1:** "Thank you for sharing that. Diesel and cut hay make the memory feel close."<br>**Message 2:** "📖 Lifehug — since you're on a roll<br>B1: What's a decision you'd make differently?<br>(Totally optional — tomorrow's question comes either way)" |
| **After (v153)** | **One message:** "Diesel and cut hay — and your grandfather's hands carrying both at once. Tell me about \"the north field\"." |

The second message's question was picked by rotation and is about something
else entirely. The turn's question is about what the author just said, in the
author's own words, and it is filed as `A14a` in the bank so the next inbound
answer lands on the right question.

## 1. Confirmed chat — the happy path

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | `answer:A14` is filed, registered, scored, and (when requested) committed locally | — | (inherited `finalize_answer_delivery` ordering) |
| 2 | A chat session opens at the FIRST ANSWER (`conv-…`), the answer is recorded as a `user` turn | — | `test_confirmed_turn_is_one_message` |
| 3 | Provider ready → turn generated → lints pass → ONE Telegram message sent → ledger `turn:{sid}:1 = confirmed` | "Diesel and cut hay — and your grandfather's hands carrying both at once. Tell me about \"the north field\"." | `test_confirmed_turn_is_one_message` |
| 4 | The cued follow-up is minted as `A14a` (suffix chain, bank-visible), rotation retargets to it, coverage rebuilds | — | `test_confirmed_turn_is_one_message` |
| 5 | Exchange 2: the author answers `A14a`; a second turn receives it and cues `A14b` | "The north field in August — he baled it himself. Tell me about \"the barn\"." | `test_third_exchange_exit_shape_and_cap` |
| 6 | Exchange 3 is the exit-friendly door: the turn receives and pays out but asks NOTHING — stopping here is a good place to rest | "A baler kept alive with parts he made himself. That is a whole portrait of him in one sentence." | `test_third_exchange_exit_shape_and_cap` |
| 7 | The author keeps going anyway; we keep receiving and never hard-stop, still without spending question initiative | "Listening for the belt — that is the kind of knowing you only get by standing next to someone." | `test_third_exchange_exit_shape_and_cap` |
| 8 | Close (≥2 user turns → the session earned a takeaway): generated, linted, sent, ledgered under `close:{sid}` | "What stays with me is that his hands carried the work and the harvest at the same time. Thank you for putting me in that barn. Next time we can pick up the baler he kept alive." | `test_completed_chat_closing_takeaway` |
| 9 | Close block records `reason`, `takeaway`, `takeaway_delivered`, `insight_receipts_count`, `filed`; engagement lands on each filed question's score record; candidate ideas file with `provenance: conversation` | — | `test_engagement_appended_to_answer_scores`, `test_candidate_ideas_filed_with_conversation_provenance` |

A replay of the same answer performs neither a second model call nor a second
send (`test_confirmed_replay_is_noop`). A closing that ends with a trailing
question is never sent — behavior rule 8 (`test_closing_with_a_trailing_question_is_never_sent`).

## 2. Fallback path — byte-shape identical to v152

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | `answer:A14` is filed normally | — | — |
| 2 | Provider reports not-ready (`agent-task` → `no_unattended_provider`, otherwise `provider_unavailable`); ledger records `skipped`; NO turn is sent | — | `test_provider_unavailable_falls_back_to_todays_behavior`, `test_keyless_provider_reports_no_unattended_provider` |
| 3 | Same invocation degrades to v152: the canonical warm acknowledgment, told honestly that a follow-up is pending | "Thank you for sharing that. Diesel and cut hay make the memory feel close." | `test_provider_unavailable_falls_back_to_todays_behavior` |
| 4 | Then the separate adaptive follow-up, with its original header/footer framing | "📖 Lifehug — since you're on a roll … (Totally optional — tomorrow's question comes either way)" | `test_provider_unavailable_falls_back_to_todays_behavior` |

The same degradation covers a provider error (`test_provider_error_falls_back`),
a definitive send rejection (`test_definitive_send_rejection_falls_back`), and
every lint/parse rejection below. Never silence; never worse than v152.

### Lint rejections that fall back

| Rejected generation | Ledger | Sent? | Proven by |
|---|---|---|---|
| Two questions in one message | `failed / malformed_generation` | nothing | `test_lint_reject_falls_back[two_questions]` |
| Over `cap.turn_chars` (1200, read from `evals/lints.yaml`) | `failed / malformed_generation` | nothing | `test_lint_reject_falls_back[overlong]` |
| Banned phrase ("that must have been") | `failed / malformed_generation` | nothing | `test_lint_reject_falls_back[banned_phrase]` |
| Unparseable output | `failed / malformed_generation` | nothing | `test_lint_reject_falls_back[unparseable]` |
| A question asked when the cadence gates are spent (curfew / 3-a-day cap / pass transition) | `failed / malformed_generation` + `question_not_permitted` | nothing | `test_curfew_and_cap_gates_transfer` |

Advisory findings (closed-question grammar, year questions) are counted in the
ledger and do NOT block a send — a false positive there would silently
downgrade a good turn (`test_advisory_lints_do_not_block_the_send`).

## 3. Ambiguous path — no auto-retry, and no fallback ack

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | The ledger records `ambiguous / send_in_progress` BEFORE the Telegram call (crash-safe replay position) | — | `test_pre_send_ambiguous_position_is_written_before_the_send` |
| 2 | The Telegram response is lost | The turn may or may not be present | `test_ambiguous_never_auto_retried_and_no_fallback_ack` |
| 3 | NO fallback acknowledgment runs — a second message would risk a duplicate voice for a turn that may already have arrived | Nothing further | `test_ambiguous_never_auto_retried_and_no_fallback_ack` |
| 4 | No follow-up is minted; rotation is untouched | — | `test_ambiguous_never_auto_retried_and_no_fallback_ack` |
| 5 | A later run reads `ambiguous_not_retried` and makes no model call | — | `test_ambiguous_never_auto_retried_and_no_fallback_ack` |

`conversation-status <session_id>` keeps it visible with
`operator_action: verify Telegram before retrying`. An operator who has
checked Telegram runs
`conversation-turn-retry <session_id> <turn_index> --confirm-not-sent`
(`test_turn_retry_requires_confirmation_for_ambiguous`).

## 4. Timeout path — a partial chat files silently

| # | Durable / system event | What the synthetic author sees | Proven by |
|---:|---|---|---|
| 1 | One answer is filed and receives its turn; the author walks away mid-exchange | (the turn from step 3 of path 1) | `test_idle_timeout_files_partial_chat_silently` |
| 2 | Two hours later (chat idle timeout from `interaction.yaml`, `knob.chat_idle_timeout_minutes: 120`) the lazy sweep closes the session | **Nothing. No closing message, no "you didn't finish", nothing.** | `test_idle_timeout_files_partial_chat_silently`, `test_idle_timeout_knobs_come_from_interaction_yaml` |
| 3 | The close block is still written (`reason: idle_timeout`, `takeaway: ""`, `takeaway_delivered: false`, `filed: [A14]`) | — | `test_idle_timeout_files_partial_chat_silently` |
| 4 | The answer stays durably filed with its richness score untouched | — | `test_idle_timeout_files_partial_chat_silently` |

A zero-turn session closes the same silent way
(`test_zero_turn_session_closes_silently`). The no-nag rule is
owner-confirmed: whatever was answered is already filed per turn, so there is
nothing to chase.

## 5. Concurrency and privacy

| Property | Behavior | Proven by |
|---|---|---|
| Single flight | A concurrent second entry for the same session mints no second turn and sends nothing at all — not even a fallback ack, because the winner's turn is the voice | `test_single_flight_mint` |
| Metadata-only ledger and diagnostics | No answer, question, prompt, or generated text in `state/conversation_deliveries.json` or in learning-failure records — only session ids, turn indices, question ids, fixed reason codes, lint ids, timestamps, attempt counts | `test_metadata_only_ledger_and_diagnostics` |
| Single source for the length cap | `system/conversation_delivery.py` contains no independent `1200`; the cap comes from `interactions/conversation/evals/lints.yaml` `cap.turn_chars` through the shared lint engine | `test_length_cap_is_sourced_from_lints_yaml_not_pinned_here` |
