# Planned Questions Before Re-engagement

Generated with Codex.

## Context And Decision

The owner authorized fixing a daily Telegram question that was a short bank
label while the hosted Today page showed a complete planned question, and
merging on green. Read-only operational diagnosis confirmed a fresh queue
existed before delivery. Thirteen days without an answer triggered the quiet
re-engagement override ahead of that queue; its shortest-text tie-break chose
an unfinished bank entry. The bank parser and Telegram renderer were faithful.

Amend the selection policy deliberately: an available planned question takes
precedence over re-engagement rotation. Silence changes fallback selection
only when the planned queue cannot supply an unanswered queued question.
This supersedes the healthy-queue silence override retained in PR332.
The planned ordering can now include a serious subject after a quiet stretch;
the planner's ordering is authoritative. Existing fallback fairness remains.

## Implementation

Change the canonical `system/ask.py` selector once: planned queue, then quiet
re-engagement, then ordinary rotation. Do not introduce a second selector,
model call, scoring authority, minimum length, punctuation rule, blacklist,
bank mutation or history rewrite. Keep eligibility, queue expiry/status
handling, delivery counts, unanswered status and four-day threshold intact.

This repairs selection, not every possible bad bank entry. A stub placed in
the queue or a sole fallback stub remains eligible under the existing policy.
Approved short prompts remain eligible; delivery is never an answer.

Update affected methodology and current documentation, including the
appropriate indexed ADR for this binding precedence decision. Bump the next
available package version (base v299, expected v300), release date and user-
impact changelog; maintain the framework manifest. No unrelated cleanup.

## Verification

- A synthetic fresh queue after thirteen silent days wins over a less-
  delivered one-word bank entry. Explicitly replace the contrary old test.
- Sent, answered, missing, expired and exhausted queue handling is unchanged.
- No usable queue retains quiet and ordinary rotation fairness.
- Legitimate brief and sole prompts remain eligible; selection writes nothing.
- Run focused selector/queue/quality tests, documentation parity and manifest
  gates. All four OSS CI jobs must pass for the exact PR head before merge.
- Viewable executable: the synthetic selector regression and hosted Today
  integration in the linked platform repair. No viewer UI change here.

## Delivery

Implementation is delegated to a lower-tier Codex model at the owner's
request, in this isolated branch. Push only this branch and post evidence;
the parent owns review, CI watching and normal green merge. The platform
consumes the verified immutable package revision; no independent vendored
implementation. Post-merge verify release tagging and source equivalence.
