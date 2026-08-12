# Contract: doc-trueing (issue #121)

Status: Draft implementation contract — contract stage only.

> This commit defines the work for issue #121. Do not merge it as spec-only.
>
> **HARD IMPLEMENTATION GATE — this contract can only be implemented after
> waves 1–3 of the Conversation Interaction build are merged**: all OSS
> wave-1/2 PRs (interactions/ scaffold; session store + builders; turn
> engine; story→conversation; arc planner; batching/close/mirror/engagement),
> the eval harness (#120), and the platform wave-3 PRs (twin #418 trues that
> repo). This is wave 4, the closer. Documentation can only be trued against
> SHIPPED code — trueing against contracts would re-create the drift this PR
> exists to kill. Verify live merge state with `gh pr list --state merged` /
> `gh issue list` before starting; if any prior-wave PR is still open, stop.

## Why

Owner-required completion criterion (owner-set 2026-08-11, and the owner's
MOST IMPORTANT requirement for this build): at the end of the conversation
build, both repos' READMEs and documentation — including the loop
descriptions and every diagram — are edited to match the shipped design and
**proved** up to date via a doc-audit pass. The effort is not done until
this PR merges. The conversation build changes what the README's diagrams
show at their core: the daily exchange becomes a Chat (arc-carded mini-arc
with receipt + payout + cued follow-up), story ingest becomes a Conversation
with an immediate substantive turn, the weekly loop plans arcs, commits
batch per session close. A README that still shows "warm ack · optional
follow-up" describes a product that no longer exists. Issue #121; platform
twin lifehug/lifehug-platform#418.

## Binding facts

- The audited surfaces and their anchors as of this contract's commit
  (line numbers WILL have shifted by implementation time — re-locate by
  heading/content, and treat any drift as expected):
  - `README.md` `## Nomenclature` (~line 9): must define **Interaction**,
    **Chat**, **Conversation**, **Arc card**, **Session** alongside the
    existing node/edge/Focus vocabulary, exactly per the ratified
    definitions in `interactions/conversation/README.md` (wave 1 committed
    them; the README section may already exist in draft — true it, don't
    fork it).
  - `README.md` mermaid diagrams — **all nine**, each gets an audit row;
    redraw every one the conversation flow changes:
    1. Big-picture flowchart (`## The big picture`): the daily subgraph's
       `process-answer … warm ack · optional follow-up` node is stale —
       show the conversation turn engine (receipt + payout + cued
       follow-up), the session document, and extracted-outputs flow
       (facts/entities/candidate_ideas/mirror_responses → their named
       consumers). **Redraw required.**
    2. Daily-loop sequence diagram (`## The daily loop`): stale — the
       question now carries the arc card's opening framing; the answer
       opens a chat session; the reply is one combined receipt+payout+cued
       follow-up turn; close files takeaway + batched commit.
       **Redraw required.**
    3. Planner flowchart (`## How the planner decides…`): audit; add the
       arc-card attach point and engagement-signal input if shipped
       behavior includes them.
    4–6. Arc-template diagrams (memoir/self/relationship): audit — likely
       unchanged (research arcs, not chat arcs) but must be walked.
    7. Candidate lifecycle flowchart: audit — conversation provenance
       (`conversation` candidate source) appears if shipped.
    8. Wiki compile flowchart: audit — likely unchanged.
    9. Three-clocks diagram (`## The three clocks`): stale — WEEKLY gains
       the arc-planning step; ON ANSWER becomes the conversation turn
       (session-open/turn/close, compile coalesced per close, one commit
       per close). **Redraw required.**
  - `README.md` core-concepts table (`## Core concepts`): add rows for
    Chat, Conversation, Arc card (`state/arc_cards.json`), Session
    (`state/conversations/<session_id>.json`).
  - `README.md` script tables (`## Every script, holistically`): add
    `conversation.py` + `conversation_delivery.py`; true the
    `process_answer.py`, `ingest_story.py`, `ask.py`,
    `weekly_maintenance.sh`, `daily_question.sh`, `jobs.py` rows (post-
    answer pipeline, story response, arc attach, `conversation-close` job
    kind). True `## Key commands` (conversation-* subcommands, route,
    conversation-evals) and the batching description under the three
    clocks.
  - `README.template.md`: the template's `## Nomenclature`, `## Schedule`,
    `## The Loop` sections get the same trueing so new vaults are born
    current.
  - `CLAUDE.md` / `AGENTS.md`: "Recognizing Answers" / "Answer Detection"
    prose must describe the five-intent router contract
    ({answer, new_story, command, continue_session, out_of_scope}) +
    deflection + the `lifehug.py route` delegation path, as shipped.
  - `skills/` (the checked-in skill contracts, e.g. the Claude Code skill
    SKILL.md): must carry the conversation contract as wave 2 shipped it —
    audit and true, don't redesign.
  - `system/research.md`: the pointer section to
    `interactions/conversation/README.md` (wave 1 added §11 or
    equivalent) — verify it exists, is accurate, and is discoverable from
    the `## Methodology` chain.
  - `docs/adr/`: no new ADR expected; audit that the conversation ADR(s)
    from waves 1–2 are indexed and their Consequences match shipped
    reality (a mismatch is a defect row → fix the ADR's Consequences or
    escalate, never silently).
- **The proof mechanism is part of the contract**: a doc-audit evidence
  table posted as a PR comment. One row per diagram element-group and per
  substantive claim in every touched section:
  `| # | Doc statement (file + anchor) | Code path (file:symbol) | Verdict |`
  with verdict ∈ {`VERIFIED` (was already true), `FIXED` (was stale,
  corrected in this PR — link the diff hunk)}. A row may not merge as
  `STALE`. The table must cover all nine mermaid diagrams (even
  "unchanged" ones get a `VERIFIED` row citing the code that still backs
  them) and every changed prose section. Minimum coverage bar: every node
  and edge label of the three redrawn diagrams appears in some row.
- Version: bumps `system/version.json` per the no-exemption rule
  (doc-only PRs bump too); changelog entry is user-facing ("README and
  docs describe the conversation flow").

## Scope

**In:** everything under Binding facts; fixing any stale statement the
audit finds in the touched files, including statements unrelated to the
conversation build (a stale claim found during the walk is a defect — fix
it and record the row). **Out:** `interactions/conversation/README.md`
itself (wave 1 owns it; it is the SOURCE this PR trues against, and
behavior.md doubles as prompt and doc by design — drift there is
structurally impossible); platform docs (twin #418); mission.md content
(owner-approved text shipped in wave 1/2 — audit its README references
only); any behavior change whatsoever (if the audit finds a CODE bug
rather than a doc bug, file an issue, add the row pointing at it, and true
the doc to intended-and-tracked behavior only if the fix is merged first —
otherwise the doc states shipped behavior).

## Implementation notes

- Work order that makes the proof honest: (1) inventory every claim in the
  touched sections into the table skeleton FIRST, verdict column empty;
  (2) walk each against code (`system/*.py`, `interactions/`, shell
  entrypoints) recording the code path; (3) fix stale rows; (4) redraw the
  three required diagrams + any others the walk flagged; (5) re-walk only
  the rewritten statements. The table is built during the audit, not
  reconstructed after.
- Mermaid: keep the existing visual grammar (subgraph styles, emoji
  headers, node label conventions) — this is trueing, not a redesign.
- `update_readme.py` regenerates the coverage section — do not hand-edit
  generated regions; confirm the generator's own template strings if they
  reference the old ack/follow-up language.

## Test plan

No new test files. The gates are:

```
python3 -m unittest discover -s tests -p "test_*.py"   # must stay green (no code changes expected)
python3 scripts/ci/check_framework_files.py             # manifest still true
```

plus a mermaid syntax check for every edited diagram (render locally or via
any mermaid CLI/preview; a diagram that fails to render is a defect).

## Launch-and-verify

Not a `serve_wiki.py` surface change — no walkthrough. The reviewable
artifact IS the doc-audit table on the PR plus the rendered README on the
branch (GitHub renders mermaid — the evidence comment links each redrawn
diagram's blob URL pinned to the commit SHA). Reviewer reproduction: open
the table, spot-check any row by following its code path.

## Definition of done

- [ ] All prior-wave PRs verified merged before implementation started
      (list them in the evidence comment with merge SHAs)
- [ ] Every surface in Binding facts audited; doc-audit table posted on
      the PR with zero unfixed rows; all nine README diagrams covered
- [ ] The three required diagrams redrawn; every edited diagram renders
- [ ] `system/version.json` bumped (no-exemption rule)
- [ ] `python3 -m unittest discover -s tests` green;
      `check_framework_files.py` green
- [ ] Issue #121 commented with results; owner told this closes the
      wave-4 completion criterion for the OSS side (platform side: #418)

🤖 Generated with Claude Fable 5 via Claude Code
