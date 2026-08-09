# The lifehug (OSS) delivery method

How this repo ships changes: a right-sized version of the hosted platform's
method (lifehug-platform's `docs/BUILDING.md`), scoped to a single-owner,
low-WIP OSS repo with no multi-service monorepo and no worktree-orchestration
scale. Where the platform doc's shape doesn't transplant, this doc says so
rather than pretending it applies. Designed and adopted in issue #85 (v132).

## 1. Contracts before code

Non-trivial work gets a written contract in `docs/pr-specs/` before code,
using `docs/pr-specs/TEMPLATE.md`. A contract ends **executable, testable,
viewable**: a command that runs, tests that pass, and — for anything
touching `serve_wiki.py`'s visible surface — a runnable walkthrough. There
is no label-lifecycle choreography here (no `needs-implementation` /
`awaiting-owner-review` dance, no interface pins for parallel-agent-wave
sibling implementations) — this repo has one owner and no wave to
coordinate. **Right-sizing**: a bug fix with a regression test skips the
contract and goes straight to a PR; use the template for anything adding a
new user-facing capability, changing a durable-data contract (e.g.
`system/vault_contract.json`), or touching more than one subsystem.

## 2. Tiered agent waves — not adopted

The platform runs parallel, model-tiered agent waves because it has a
multi-service monorepo and enough concurrent work to need worktree
orchestration. This repo doesn't have that scale — the owner works
low-WIP, one contract at a time. Its absence here is a scale mismatch, not
a gap to fill later.

## 3. CI — the keystone

`.github/workflows/ci.yml` is the one thing every PR and every push to
`main` runs: the `test` matrix (`python3 -m unittest discover -s tests -p
"test_*.py"`, Python 3.11 and 3.14, no `pip install` — this repo is
deliberately dependency-free at runtime, and keeping CI dependency-free
too is itself worth protecting), the `framework-manifest` check (every
path in `system/version.json`'s `framework_files` exists on disk — see
`scripts/ci/check_framework_files.py`), and, on pull requests, the
`version-bump` check (`scripts/ci/check_version_bump.py`). Branch
protection requires all three. `.github/workflows/tag-on-merge.yml`
auto-tags `system/version.json`'s version on every push to `main`
(`scripts/ci/tag_on_merge.py`), with a drift-check safety net appended to
`framework-manifest` on `main` so a failed tagging run goes red instead of
silently lapsing (see §6 and issue #84). Playwright/walkthrough evidence is
deliberately **not** part of this workflow — it needs a browser download
and `ffmpeg`, and it's PR-specific evidence, not a pass/fail gate; it stays
a manually-invoked `make walkthrough-<slug>` step (§4).

## 4. Evidence for the viewer

Any PR touching `serve_wiki.py`'s visible surface ships a runnable
walkthrough with screenshots embedded in a PR comment, SHA-pinned
(`?raw=true` blob URLs), and a GIF for any interaction sequence (click →
state change → result), the raw `.webm` committed alongside — same
mechanism as the platform, copied in spirit. The dual-viewport convention
(1440x900 + 390x844) inherited from `tests/v119_job_pill_evidence.py` stays
the default, not a newly-imposed hard requirement. Build a walkthrough on
`tests/walkthrough_lib.py`'s `WalkthroughHarness` (disposable synthetic
vault → live viewer → Playwright, teardown always runs) and wire it up as
`tests/walkthrough_<slug>.py` + `make walkthrough-<slug>` (the root
`Makefile`'s `walkthrough-%` pattern rule). See `docs/pr-specs/TEMPLATE.md`'s
Launch-and-verify section for what "pass" has to mean.

## 5. Owner closeout

A PR awaiting review carries a self-contained **Owner closeout** comment:
**Look** (exact steps/URLs for anything the walkthrough screenshots can't
convey live), **Judge** (explicit yes/no judgment items — a new user-facing
default, a tone call, a version-bump size call, or an ADR ratification when
the PR pins `docs/adr/TEMPLATE.md`'s Decision as binding), **Done when**
(what approving triggers: merge, anything the owner still has to run
after). Clicking through a happy path the walkthrough already proved is
not owner work.

## 6. Release discipline

Most of this was already a rule (AGENTS.md's Definition of Done); CI adds
teeth. **Version bump: no exemption.** Every PR bumps `system/version.json`
— including doc-only and CI-only PRs. This was an explicit open question
in the design (a check-only gate for CI's own introduction PR would need a
carve-out to pass its own gate) and the owner resolved it against an
exemption: this very PR (v132) bumps and is checked by the gate it adds,
proving the rule against its own introduction rather than special-casing
around it. **Tag-on-merge is now automated**, not a manual step — see §3
and `.github/workflows/tag-on-merge.yml`. Changelog quality is already
practiced via `version.json`'s `changelog` field, sized to user impact.

## 7. Merge train

Rebase onto `main` before merge; this repo runs low-WIP by owner
preference, so a growing merge train is a batching smell, not a process to
invest in.

## 8. Doctrines

**Recurring-defect doctrine**: when the same defect class shows up more
than once, stop patching instances — extract one authoritative definition,
rewire every call site to it, add a guard test against re-introduction of
the known-bad form, and add a parity test when the fact is really a
contract with an external source. This repo's own exemplars:
`system/vault_paths.py` (single authoritative vault-root/contract
resolution, replacing scattered path-guessing) and
`system/format_frameworks.py` (single source of truth for framework
question/id shapes).

**Machine-authorship attribution**: already practiced informally in commit
messages; the rule is written down in `AGENTS.md`.

**Cross-medium parity**: already written down in `AGENTS.md` §"Cross-Medium
Parity" — this doc doesn't duplicate that prose, it just points there so
only one copy needs to stay current.

**Architectural decisions get an ADR** (owner reversal of the design's
default, 2026-08-09, ratified as ADR 0001): a changelog entry or a closed
issue records that a decision happened, but it doesn't index it — as this
repo gains outside contributors, "where was that decided" needs one
findable answer. A decision future work must honor (not every PR — see
`docs/pr-specs/TEMPLATE.md`'s Definition of done) gets a lightweight ADR in
`docs/adr/` (`docs/adr/TEMPLATE.md`): Context, Decision, Consequences. The
index is the point, not the ceremony.

Not adopted here: owner-run exit demos on real infrastructure (no
staging/production infra in a local-companion repo) and the platform's
`product-parity.yaml` tooling (platform-specific).

## Where things live

- `AGENTS.md` / `CLAUDE.md` — model-neutral operating rules
- `docs/pr-specs/` — contracts
- `docs/adr/` — ratified decisions
- `docs/BUILDING.md` — this method
- `.github/workflows/` — the keystone
- Roadmap: GitHub issues · evidence: PR comments
