# ADR 0019: Git-tree candidate promotion receipts

Date: 2026-08-18
Status: proposed

## Context

Issue #170 needs the hosted Answer Now flow to learn the canonical question id
and durable Git commit after a Question Candidate answer is ready. The legacy
manual, weekly-auto, and neighborhood paths each allocated and rendered a bank
question independently. A crash or projection lag could therefore leave a
durable question with no trustworthy response for the caller, and retrying
could insert another question.

The candidate store is a mutable projection. It cannot prove whether a write
committed or pushed. Text matching is also insufficient: an equal legacy
question does not prove which candidate or placement decision created it.

## Decision

`system/candidate_promotion.py` is the sole candidate-to-question mutation
authority. Every request binds the candidate source/anchor, category, and
placement revisions, plus optional exact proposal and validated-decision
hashes. The authority revalidates fresh facts under the vault writer lease,
inserts one question plus a closed canonical-base64 provenance marker, updates
the candidate projection, and commits only those two paths.

The marker in the canonical Git tree and the commit that introduced it are the
receipt authority. A replay reconstructs `{candidate_id, category_id,
question_id, changed:false, commit_sha, candidate_provenance}` from Git history
without depending on projection freshness. An exact uncommitted marker left by
a crash is completed after candidate/question validation. Conflicting bytes or
revisions fail closed. Existing equal text without the structured marker is
never adopted.

One commit per promotion won over a separate receipt ledger because it makes
the durable content and proof indivisible and avoids another projection.
Embedding raw proposal/decision content lost to hash-only binding because the
bank must not copy private conversation text. Guessing legacy provenance lost
because it cannot be made safe or auditable.

## Consequences

- Manual, weekly-auto, neighborhood, viewer/job, and future hosted callers use
  the same authority; recurring-defect tests reject renderer/write bypasses.
- `candidate-promote` is safely retryable. A crash after bank write,
  projection write, commit, or push converges on one question and one receipt.
- The stable `candidates-promotion-receipt ... --json` door requires the
  caller-held candidate/category/placement revisions and returns the canonical
  question id and commit SHA needed by downstream filing.
- Starting Question Candidate Play still never promotes. A caller invokes this
  mutation only after its own lifecycle authorization.
- Conversation and the v181 Question Candidate Interaction remain unchanged;
  no model receives Git or vault-write authority.
- If the vault stops using Git as durable content authority, this ADR must be
  superseded together with the receipt/adoption protocol.

🤖 Generated with GPT-5.6-Sol via Codex
