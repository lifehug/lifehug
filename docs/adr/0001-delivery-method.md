# ADR 0001: The right-sized delivery method

Date: 2026-08-09
Status: ratified (owner, 2026-08-09)

## Context

This repo had no CI, no written delivery method, and no index of past
architectural decisions before issue #85. Two concrete failures made the
gap costly rather than theoretical: v120's regressions sat red for 8 days
because no machine ever ran the test suite on push — local stash-comparison
kept misdiagnosing them, and nothing else was watching (fixed and pinned in
v130/v131) — and `system/version.json`'s versions v118 through v128
shipped without a matching git tag, silently breaking `update.py`'s
tag-based delivery to every existing vault for ten releases before anyone
noticed (issue #84). Both were the same underlying shape: a manual step
that only works if a human remembers to run it, and nothing watching for
the case where they don't.

Issue #85's design (the "OSS Delivery-Method Adoption Design" comment)
proposed adopting the hosted platform's delivery method, right-sized for a
single-owner, low-WIP OSS repo with no multi-service monorepo. The design's
default was to drop the ADR concept entirely — no `docs/adr/` existed here,
and the design didn't want to invent one unasked. The owner reversed that
default on review of the resulting PR: changelogs and issue threads record
*that* a decision happened, but they don't *index* it — as the repo gains
outside contributors, "where was that decided" needs one findable answer,
not an archaeology dig through `version.json` changelog entries.

## Decision

Adopt the method described in `docs/BUILDING.md`, this PR ratifying it as
ADR 0001: CI is the keystone (unit suite matrix + framework-manifest check
+ version-bump check, all required by branch protection); non-trivial work
gets a contract (`docs/pr-specs/TEMPLATE.md`) before code; PRs touching the
viewer ship runnable walkthrough evidence; releases auto-tag on merge with
a drift-check safety net; the merge train shrinks to one sentence (rebase
before merge, low WIP by preference); and — reversing the design's default
— this repo **does** adopt a lightweight ADR practice
(`docs/adr/TEMPLATE.md`), scoped down from the platform's fuller
Context/Decision/Alternatives-considered/Consequences shape to just
Context/Decision/Consequences. No version-bump exemption: every PR bumps
`system/version.json`, including doc-only and CI-only ones — this PR bumps
to v132 and is gated by the version-bump check it introduces.

## Consequences

- Future PRs that make a decision future work must honor (a policy an
  agent or contributor would otherwise have to reverse-engineer from a
  changelog entry or a closed issue) write an ADR — `docs/pr-specs/
  TEMPLATE.md`'s Definition of done asks the question on every contract.
  Most PRs answer no; a PR that changes a durable-data contract, drops an
  existing guarantee, or picks between real architectural alternatives
  answers yes.
- `docs/adr/` is now the one place "where was that decided" resolves to —
  new ADRs get the next sequential number and cite the PR/issue that
  ratified them, mirroring this one.
- This forecloses treating `system/version.json`'s `changelog` field as the
  durable record of *why* a cross-cutting decision was made — changelog
  entries stay sized to user impact (what changed), ADRs carry the
  reasoning (why it was decided this way and what it forecloses).
- No delete-when condition: the method itself is expected to evolve (the
  merge-train section is explicitly provisional on WIP staying low), but
  the *practice* of indexing binding decisions in `docs/adr/` doesn't have
  a natural expiry the way a specific mechanism might.
