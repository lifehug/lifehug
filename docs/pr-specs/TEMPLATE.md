A bug fix with a regression test does not need a contract — go straight to
the PR. Use this template for anything that adds a new user-facing
capability, changes a durable-data contract, or touches more than one
subsystem.

---

# Contract: <slug>

## Why
One paragraph. The problem, cited issue number(s), why now.

## Binding facts
Everything the implementer must NOT re-derive or guess — exact file paths,
exact function signatures being touched, exact schema/contract fields (e.g.
system/vault_contract.json entries), version number this lands as.
State facts as of the commit this contract ships in, not as of the issue.

## Scope
What's in. What's explicitly out (link a follow-up issue if something
adjacent is deliberately deferred).

## Implementation notes
Pointers to the actual code seams (file:function), not prescriptive step-by-
step — the contract pins WHAT and the binding facts, not HOW to write the
diff.

## Test plan
Which existing test files change, which new test file is added, and the
exact `python3 -m unittest ...` invocation that proves it (subtests named
explicitly if the change is state-machine-shaped, following the v130/v131
regression-test precedent).

## Launch-and-verify
Only required for PRs touching `serve_wiki.py`'s visible surface. A runnable
walkthrough spec, not prose — the literal `make walkthrough-<slug>` (or, pre-
harness-generalization, `python3 tests/walkthrough_<slug>.py --artifacts
artifacts/walkthroughs/<slug>`) invocation, what states it captures, and
what "pass" looks like (exact screenshot count/dimensions, like
v119_job_pill_evidence.py's own assertions). This section is not a
description of testing that happened — it is the exact command a reviewer
(or CI) can re-run to reproduce the evidence from scratch.

## Definition of done
- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] system/version.json bumped (version, released, changelog,
      framework_files if new distributable files were added)
- [ ] AGENTS.md/CLAUDE.md updated if described behavior changed
- [ ] ADR written/updated if this PR makes a decision future work must
      honor (most PRs: no) — `docs/adr/TEMPLATE.md`
- [ ] Covering GitHub issue commented with verification results / closed
- [ ] Launch-and-verify run and evidence embedded in a PR comment
      (SHA-pinned blob URLs), if this PR touches the viewer
