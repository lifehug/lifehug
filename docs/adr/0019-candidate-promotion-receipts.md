# ADR 0019: Git-tree candidate promotion receipts

Date: 2026-08-18
Amended: 2026-08-20 (v187, issue #179)
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
hashes. A non-null interaction hash is accepted only alongside the full exact
object whose canonical hash it claims; the stable CLI receives those objects
through a bounded closed JSON stdin envelope, never free-floating argv
metadata. The authority revalidates fresh facts under the vault writer lease,
inserts one question plus a closed canonical-base64 provenance marker, updates
the candidate projection, and commits only those two paths.

The marker in the canonical Git tree and the commit that introduced it are the
receipt authority. A replay reconstructs `{candidate_id, category_id,
question_id, changed:false, commit_sha, candidate_provenance}` from Git history
without depending on projection freshness. An exact uncommitted marker left by
a crash is completed after candidate/question validation. Conflicting bytes or
revisions fail closed. Existing equal text without the structured marker is
never adopted.

Marker replay accepts both lifecycle-valid question rows: the original
unchecked `- [ ] QID: text` insertion and the canonical checked
`- [x] QID: text` row, including the answer annotation produced when an answer
is filed. Replay checks the full checked text first, then may strip only a
terminal, valid ISO `*(YYYY-MM-DD)*` answer annotation and check the revision
again. Thus arbitrary italic suffixes remain question text, while the canonical
checkbox and answer-date annotation are lifecycle metadata rather than question
identity. Any other checkbox state, malformed date-like suffix, changed id, or
changed text fails closed. This keeps an older answered promotion from
invalidating the global marker scan for every later promotion.

`system/exact_file_git.py` is the one public, reusable Git transaction/adoption
adapter beneath promotion. It accepts a closed set of exact relative paths and
immutable-snapshot decision/validation callbacks; the returned plan cannot add
paths. The adapter alone owns the root-aware writer lease, pull-before-decision,
atomic exact-file replacements, `commit --only`, first-marker commit lookup,
push retry, and post-rebase validation. Candidate promotion uses this adapter
rather than retaining a private writer. After any rejected push and rebase,
the candidate validator re-proves exact marker adjacency, question bytes and
revision, all request provenance/hashes, and the intended record before a
retry or adoption. Marker presence by itself is never sufficient.

One commit per promotion won over a separate receipt ledger because it makes
the durable content and proof indivisible and avoids another projection.
Embedding raw proposal/decision content lost to hash-only binding because the
bank must not copy private conversation text. Guessing legacy provenance lost
because it cannot be made safe or auditable.

## Consequences

- Manual, weekly-auto, neighborhood, viewer/job, and future hosted callers use
  the same authority; recurring-defect tests reject renderer/write bypasses.
- Future exact-file lifecycle mutations may reuse the narrow adapter, but must
  supply their own closed domain validator; it cannot write undeclared paths.
- `candidate-promote` is safely retryable. A crash after bank write,
  projection write, commit, or push converges on one question and one receipt.
- Answering a promoted question preserves its receipt, so later promotions can
  revalidate the entire bank after the canonical unchecked-to-checked change.
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
