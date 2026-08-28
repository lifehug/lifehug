# AGENTS.md — Lifehug Workspace

This is a Lifehug workspace. Read `CLAUDE.md` for the full operating instructions.

## Quick Start

**On every session**, check the state through the script wrapper:

```bash
python3 system/lifehug.py doctor
python3 system/lifehug.py status
```

The `system/` scripts are canonical. Skills, agents, and cron jobs should call scripts instead of duplicating workflow logic.

Use **the Loop** as the canonical operating term: capture source → compile wiki → lint/repair source truth → classify/score signals → promote candidates and plan the queue → ask a better question → create artifacts → feed final artifacts back as source. When auditing or designing, classify features as:
- **In the Loop**: reached by daily, weekly, monthly, or artifact flows and able to affect future questions, wiki pages, relationship understanding, or artifacts.
- **Loop-adjacent**: manual, dry-run, inspection, setup, or repair support that only changes future behavior when promoted into a Loop surface.
- **Out of the Loop**: code/data that exists but is not called by Loop entrypoints and is not read downstream. Mission-critical features should not remain here.

Use **Node** and **Edge** when reasoning about graph shape. A Node is a durable life subject that usually compiles into one wiki page; an Edge is a meaningful connection between nodes. Keep `Entity` and `Entity Type` as the current product/code and frontmatter terms: most entity types are node types, while `relationship` remains the compatibility page type for a **Relationship Edge**. `wiki/relationships/` describes the bond between two nodes, not a generic node page.

## Definition of Done (framework changes)

A code change is not done until its paper trail ships **in the same pass**:

1. **Docs** — update anything whose described behavior changed: `CLAUDE.md`,
   `system/research.md` (the central methodology guide — its opening feeds AI
   prompts, so staleness degrades the product), `README`/`README.template.md`,
   and `skills/*/SKILL.md`.
2. **GitHub issues** — comment progress on the covering issue with verification
   results; close it when delivered. If work surfaced a new gap, file it.
3. **Tests + version bump** — tests for new behavior, and **every PR bumps
   `system/version.json`** (owner rule, 2026-08-04): increment `version`,
   set `released`, write the changelog entry sized to user impact — a
   feature that changes behavior for the user gets a full changelog
   paragraph naming what they'll notice; a small fix gets a one-liner.
   Any new file the upgrade path should distribute goes into
   `framework_files` in the same bump (that manifest is what
   `system/update.py` ships to existing installs — a file missing from it
   never reaches upgraders). No PR ships without a bump.
4. **CI & release discipline** — every PR runs CI
   (`.github/workflows/ci.yml`) green before merge; branch protection
   requires it. The `test` job is the unit suite on the Python matrix, the
   `framework-manifest` job proves every `framework_files` entry exists on
   disk, and the `version-bump` job proves rule 3's bump actually happened
   — no exemption, including doc/CI-only PRs. On merge to `main`, the
   version in `system/version.json` is tagged automatically
   (`.github/workflows/tag-on-merge.yml`, `scripts/ci/tag_on_merge.py`); if
   a push to `main` is not tagged within a few minutes, that is a
   CI-visible failure (the drift check in `framework-manifest`), not a
   silent one — see issue #84, where the manual equivalent of this step
   lapsed for eleven releases before anyone noticed. Full method:
   `docs/BUILDING.md`.

"Done" = code + tests + docs + issue state — never code alone. The owner should
never have to ask whether the docs match the code.

## Current paradigms (v188–v191) — read before touching an interaction

- **Six Interactions; three are CHILDREN of Conversation**, each adding
  exactly ONE goal: `question_candidate` (placement, v188, ADR 0018),
  `focus_candidate` (onboarding, v189, ADR 0021), `entity_candidate`
  (identity, v190, ADR 0022). Arc walking is **proposed, not built**
  (platform issue #570 §3). The paradigm — one goal, exact-version
  composition, a stage-keyed `prompt/turn-instructions.md` leaf, ONE
  additive output field, lints + goldens + an evals harness — is written
  once in `interactions/README.md` § "The child-interaction paradigm".
  Read it there; do not re-derive it from one child.
- **Play = approve + start.** Play approves the row (promote / scaffold /
  graduate) in the host's background job and opens the conversation
  immediately. The model writes nothing and claims nothing; it states the
  act once as an aside and takes a correction as a *move*. "Play is
  read-only" / "Play never promotes" is retired vocabulary (platform ADR
  0020 amended ADRs 0018/0021/0022 in place) — if you find it, it is stale.
- **Every output-contract field is additive, and a host must thread it on
  its prompt stand-in.** Fields are gated on `TurnShape` flags
  (`placement_stage` · `focus_stage` · `entity_stage`, default `None`) so
  `conversation_delivery._output_contract_block()` stays byte-identical
  for every other caller — a required test per child. The landmine the
  hosted platform hit on every pin: it REPLAYs a *vendored stand-in* of
  the turn prompt rather than calling ours, so an unthreaded field is
  silently absent in production while our suite is green. Name every new
  field explicitly in the `system/version.json` changelog.
- **A message points at a place; a printer prints a command** (v191).
  `book.format_chapter_offer` (the chapter-ready Telegram nudge) points at
  Studio and must never embed a CLI command; `progress.py`'s
  Ready-to-create block and `book.print_book_offers` /
  `print_book_chapter` keep printing `artifact new`, because terminal
  output is the local medium's own instruction.
- **Handbook parity is a CI gate.** `tests/test_handbook_parity.py`
  fails on a drifted `<!-- parity: module.CONST = value -->` annotation or
  a `<!-- embed: … behavior.md -->` block that no longer byte-matches its
  source. Edit a `behavior.md`, edit its handbook page in the same commit.

## Landed 2026-08-27→28 — THE ERAS PROGRAM (in progress)

Controlling design: platform `docs/design/eras.md` (tracking
lifehug-platform#686); this repo's half is **ADR 0030**
(`docs/adr/0030-eras.md`). The founder's own Timeline read College 1990–1991
before High School because eras were dated from whatever moments keyword
placement happened to put inside them — full diagnosis in the ADR's
Context. Fix: age frames (Childhood, Teen years, every reached decade) are
the permanent, calculated coordinate system; named eras (College, the
Mission) are immutable, person-created interpretations dated only by what
the person said; membership and display are separate durable receipts;
every event carries who it happened to and why it belongs on the owner's
own axis.

**Merged, v235→v239**: **v235** ADR 0030 itself, and it keeps v234's own
promise — the `mirror_item` read alias is deleted (lifehug#257) · **v236**
O-E0 immediate defects — honest probes by relationship rather than
`anchor_rows[0]`, the owner's birth claim binds to subject `self`
(lifehug#255 contract, lifehug#258 implementation: `period_bound` is
refused with a typed reason rather than misfiled onto an unrelated moment)
· **v238** O-E1 — age frames as one pure arithmetic definition
(`cross_dating.age_frames`), the calculated projection's additive schema v2
(`node_kind: "period"`, `CALCULATION_RULE_VERSION` →
`timeline-rules:2`), publication as a semantic no-op inside one
reached-frame epoch, the one legacy alias map `timeline.legacy_period_ref`
(lifehug#259) · **v239** O-E3 — an era is an identity: the opaque
content-addressed `era_id`, label/kind as separate decision records, the
deterministic event binder (`event_resolution`), the atomic `era-record`
writer, and the `era` Play stage (lifehug#261). Membership/display filing
is a DELIBERATELY separate, not-yet-wired seam — `era-record` refuses a
whole payload that asks for a membership rather than filing the rest and
dropping it silently. **v243** (this PR) is docs-only: the handbook page
and glossary section, zero executable diff — rebased once mid-flight when
v239 landed while it was open, so it describes era-record as merged rather
than in flight.

**Open / in flight**: **O-C** (lifehug#256) — the `is_current` reader gate,
`--stale-first` + a durable cursor, corrections are never classification
targets themselves; its stacked fix **O-C2** decides that a `timeline-place`
correction is a date DECISION, not a content refutation, and must not mark
its own source's classification stale (`correction_role`) · **O-E1b**
(lifehug#263) — the view block serves memberships/labels/overlays/
`life_view` from what the file actually publishes · **O-E6** (lifehug#262)
— the missing-birthday work item's v2 score and the `work_item_aliases`
map · **O-BO** (lifehug#264) — a provisional birth origin intersected from
what the person said, never averaged. Version slots go by readiness, not
by branch order, and can legitimately collide (two branches both claimed
v240 this session) or leave a hole (the v228 precedent) — resolved at
merge time, not at branch time.

**Operational lessons, additive to this file's existing ones:**

- **A shared `git stash` across worktrees loses another worktree's staged
  work.** Multiple agents working parallel Eras branches out of sibling
  worktrees must commit often instead — `git stash` is repo-global state,
  not worktree-scoped, and a stash popped in the wrong worktree silently
  discards what looked like someone else's uncommitted change.
- **`TMPDIR=/private/tmp` is required for this repo's own suite on macOS**,
  not only for platform walkthroughs — the same symlinked-`/var` vault-root
  guard trips inside `tests/` here too.
- **`system/vault_contract.json` carries an identity digest that must be
  re-stamped after any edit that changes what it certifies** — a stale
  digest reads as a valid contract for the wrong content, which is worse
  than a missing one.
- **OSS CI requires a version bump per PR, and that is what keeps a
  contract-only draft honestly red.** A PR that lands only a contract
  (`needs-implementation`) is *supposed* to fail the "version bump present"
  gate until its implementation PR actually bumps `system/version.json` —
  treating that failure as a bug to silence would delete the signal that
  separates a plan from a shipped behavior.
- **An Opus rate limit mid-session is a continuation, not a stall**: the
  remaining Eras waves continued on Sonnet with honest attribution
  (`🤖 Generated with Claude Sonnet 5 via Claude Code` where Sonnet actually
  wrote the final text) rather than blocking on Opus availability.

Then decide:

1. **Fresh install?** → If `system/question-bank.md` has no project categories (only A-E), run the First Session setup flow from CLAUDE.md.
2. **Setup done but no cron?** → If `config.yaml` exists but no daily question delivery is configured, help the user set up their cron job.
3. **Normal session?** → Check if there's a pending question or incoming answer to process. Prefer `python3 system/lifehug.py process-answer` for answer saves.

### Machine-authorship attribution

Every newly machine-authored commit message, PR/issue body, and substantive
comment identifies the model that authored its final text and the surface
when both are verified: `🤖 Generated with MODEL via SURFACE`. The
implementing agent identifies its own artifact. If the exact model is
unavailable, name only the verified surface (for example, `🤖 Generated with
Codex`) and never guess. For mixed artifacts, identify the model
responsible for the final authored text. Never add a false `Co-Authored-By`
identity. Keep honest historical Claude, Kimi, Codex, and other attribution
unchanged.

### Recurring-defect doctrine

Same defect class twice = stop patching instances. Extract one authoritative
definition (a single importable module), rewire every call site to it, add a
guard test that fails on inline re-introductions of the known-bad form, and
— when the fact is really a contract with an external source — add a parity
test derived from that source so upstream drift fails the build instead of
production. Exemplars already in this repo: `system/vault_paths.py` (single
authoritative vault-root/contract resolution, replacing scattered
path-guessing that used to be hand-rolled per call site) and
`system/format_frameworks.py` (single source of truth for framework
question/id shapes, instead of every module guessing the alphabet).
Per-instance regression tests stop regressions; only a centralized
definition stops the next module from guessing wrong.

## Cross-Medium Parity (owner-set, 2026-08-05)

Lifehug is one product in multiple mediums: this local companion, the hosted
platform (lifehug/lifehug-platform), future mobile apps. Mediums differ in
HOW, never in WHAT — user-facing capabilities stay feature-equivalent,
adapted to each medium. The rule is bidirectional: **any session building a
user-facing feature here files the twin issue on lifehug-platform in the
same pass (and vice versa), or records in the PR why the feature doesn't
translate to the other medium.** Hosted infrastructure (sessions, invite
gates, durable stores) is not a feature and needs no twin. Design/theming
parity is deliberately deferred until the platform's design settles
(lifehug-platform#236 tracks the future shared design library).
First backfill wave from the platform's UI build: issues #51–#54 here.

## Git Conflict Resolution — State File Safety

**This section is the UPGRADE case**: pulling framework changes from the
upstream template, where remote is newer framework and local is the only copy
of this author's state. If instead you are pulling **the author's own vault**
shared across several machines or a hosted environment, the answer inverts —
remote is another operator's legitimate state and wins. See CLAUDE.md →
"Shared Vault: One Vault, Many Machines". Check which pull you are in first.

Lifehug state files track delivery history, coverage, and the question queue. During `git pull --rebase` or merge conflicts, **never blindly accept remote for state files** — doing so erases the record of what was asked, answered, and delivered, causing duplicate questions and lost answers.

### State files (keep LOCAL on conflict)
- `system/rotation.json` — delivery counts, last question sent, send-today tracking
- `system/coverage.json` — per-category answer counts
- `state/question_queue.json` — planned queue with sent/queued status
- `state/source_manifest.json` — answer and source registry
- `state/answer_acknowledgments.json` — metadata-only acknowledgment delivery/dedupe ledger (the v153 fallback path)
- `state/conversation_deliveries.json` — metadata-only conversation-turn delivery/dedupe ledger
- `state/conversations/` — one document per conversation session (turns, extraction, close)
- `system/question-bank.md` — checked-off questions

### Framework files (accept REMOTE on conflict)
- `system/version.json`, `system/lifehug.py`, `system/*.sh` — upstream upgrades
- `wiki/` pages — recompiled from source on next answer filing

### Safe rebase procedure
```bash
# Back up state before pulling
cp system/rotation.json /tmp/rotation-backup.json
cp state/question_queue.json /tmp/queue-backup.json

# Pull
git pull --rebase origin main

# On conflict: keep local state, accept remote framework.
# DURING A REBASE THE LABELS ARE INVERTED: your commits are replayed onto the
# remote, so --theirs is YOUR local side and --ours is the REMOTE side.
git checkout --theirs system/rotation.json system/coverage.json state/question_queue.json  # local state
git checkout --ours system/version.json  # remote framework, if conflicted
git add -A && GIT_EDITOR=true git rebase --continue

# Verify delivery state survived
python3 -c "import json; print(json.load(open('system/rotation.json')).get('delivery_counts'))"
```

### If a rebase is stuck (started but never finished)
```bash
git rebase --abort    # get back to a clean state
git pull --rebase origin main   # try again cleanly
```

Never leave a rebase in progress overnight — it blocks all subsequent git operations including answer filing.

## Detecting State

```
No config.yaml           → Brand new. Start setup.
config.yaml exists       → Setup done. Check for pending work.
  + no cron configured   → Help set up daily delivery.
  + cron active          → System running. Process answers, check coverage.
```

## First Session: Setup

When someone opens this workspace for the first time:

1. Read `CLAUDE.md` Section "First Session: Setup" — follow Steps 1-7
2. After generating their question bank, create `config.yaml` from their answers:

```yaml
# Lifehug — Your Configuration
name: ""                    # Your first name
timezone: "America/New_York"  # Your timezone (for question delivery)
question_time: "09:00"      # When to receive your daily question
channel: "telegram"         # telegram | whatsapp | signal | discord | email | cli
```

3. Set up the daily question cron job (see "Cron Setup" below)
4. Ask the first question

## Cron Setup

After setup, create a cron job for daily question delivery. The cron task should:

1. Run `system/daily_question.sh`
2. Let that script pick, send, pin when supported, and mark sent only after delivery succeeds
3. Avoid custom state mutation outside the script

The delivered message body is the day's pre-planned arc card when one is live
(v154, issue #118): after the id parse, the script reads `lifehug.py arc-card
<QID> --daily-text` — a pure file read, no AI on the daily path — and uses the
card's framing plus the question when it prints something, today's format when
it prints nothing (reengagement picks, an expired queue, an uncarded question).
The `[QID]` marker is unchanged in either case.

Real runs of the daily, weekly, and monthly scripts enqueue into the durable
single-writer worker under `state/jobs/`; dry-runs remain direct and
non-mutating. On macOS, install the persistent worker plus canonical schedules
from `examples/launchd/README.md`. The fallback worker makes scripts usable
before launchd is loaded, but a persistent worker is the normal setup.

Never set a fake `LIFEHUG_JOB_RUNNER_TOKEN`. Re-entry is valid only while that
unguessable token matches the live kernel-locked writer owner for this vault.
For a failed job, inspect only metadata with `python3 system/jobs.py show
<job-id>`; use `retry` only when the record says it is safe, or `purge` to
delete retained private payload/receipts while keeping the audit metadata.

### OpenClaw Cron

Tell the user to run this (or do it for them if you have access):

```
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "<MIN> <HOUR> * * *" \
  --tz "<TIMEZONE>" \
  --task "cd <WORKSPACE_PATH> && system/daily_question.sh" \
  --announce \
  --channel <CHANNEL>
```

Replace:
- `<MIN> <HOUR>` with their preferred time (e.g., `0 9` for 9:00 AM)
- `<TIMEZONE>` with their timezone
- `<WORKSPACE_PATH>` with the absolute path to this repo
- `<CHANNEL>` with their delivery channel

### Other Platforms

For non-OpenClaw setups, the user needs to configure their own scheduler (cron, systemd timer, etc.) to:
1. Run `system/daily_question.sh`
2. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, or config values supported by that script
3. Use `LIFEHUG_DAILY_DRY_RUN=1 system/daily_question.sh` to test without sending

## Processing Answers

When the user replies to a daily question (via any channel):

1. **Identify the question** — Match to the last asked question from `system/rotation.json` (`last_question_id`)
2. **Follow the "Processing an Answer" flow** in CLAUDE.md:
   - Clean up the response
   - Generate 1-3 follow-up questions when useful
   - Pipe the answer through `python3 system/lifehug.py process-answer {question_id}`
   - Let `process-answer` compile the private wiki automatically unless there is a clear repair reason to pass `--no-compile-wiki` — UNLESS the answer belongs to an open conversation session (v156, issue #119), in which case the default flips: compile skips, the compile-needed sentinel is touched, and the session's eventual close is the batch boundary. `--compile-wiki` forces a compile anyway; explicit flags always win over the session-derived default.
   - Commit and push if requested or part of the configured daily workflow — inside an open session these still only run when explicitly requested; the close's own single commit is what lands by default.
3. **Answer with a conversation turn** — `process-answer` does this automatically once the answer is durable (v153, issue #116). It sends ONE message that receives what was said, pays it back, and cues the next question in the user's own words, per `interactions/conversation/prompt/behavior.md`; the cued follow-up is filed as a suffix-chain bank question (A14 → A14b) and rotation targets it. Do not send a second hand-written acknowledgment or a second question. Any definitive failure degrades in the same run to the previous pair — warm acknowledgment, then the separate adaptive follow-up — so this path is never silent and never worse than before. Inspect metadata-only status with `python3 system/lifehug.py conversation-status` (the fallback acknowledgment keeps its own `answer-ack-status`).
4. **Closing a conversation** — `lifehug.py conversation-close <session_id>` (v156, issue #119) runs the full close: PR3's takeaway-or-silence rule, then files the session's Mirror inbound responses and engagement timing, compiles the wiki ONCE, and lands ONE commit ("Conversation close `<session_id>`") — non-fatal and learning-failure-recorded on any git error. `conversation-close --expired` is the deterministic, AI-free idle-sweep: it finds every open session past its idle timeout and enqueues one durable `conversation-close` job per session (`jobs.py`, identity `conversation-close:<session_id>`) rather than closing inline; `compile_and_commit.sh` runs it as an hourly pre-step so an otherwise-idle vault with only an expired session still closes it.

## Unprompted Story Ingest

If the user shares a life story that is not an answer to the current daily question, save it as source material instead of forcing it into an answer file:

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story --source "telegram" --title "<short title>"
python3 system/lifehug.py compile
python3 system/lifehug.py planner-report
```

This stores the raw story under `sources/manual/` and parks suggested template follow-up questions in `state/question_candidates.json`. The story also (issue #117) opens or continues a Conversation and gets one immediate turn — the same turn engine that pays out daily answers: a receipt quoting the user's own words, register matched to the source, at most one cued follow-up invitation. Best-effort and never blocking; on any definitive failure or with no unattended provider, behavior is exactly the filed template candidates above, no session created. At the session's close, classifier-grade candidates supersede the templates rather than duplicating them. Candidates should inform planning and future question-bank edits; they should not automatically dominate daily delivery.

If the user states an **opinion** — a philosophical position or lens on life, not an event account (messages starting `opinion:` are explicit) — ingest it with `--kind opinion` and offer to develop it as an essay artifact:

```bash
printf '%s\n' "$OPINION_TEXT" | python3 system/lifehug.py ingest-story --kind opinion --source "telegram" --title "<short title>"
python3 system/lifehug.py artifact new --format essay --seed sources/manual/<opinion-file>.md
```

Opinion ingest generates Socratic follow-up candidates (origin, counterexample, evolution, dissent, stakes) instead of scene prompts. The `--seed` puts the opinion verbatim at the top of the essay's context pack; iterate with `artifact save --feedback` until the author says done, then promote.

## Source Integrity

Treat `answers/` and `sources/` as raw source-of-truth. Do not rewrite old answers or stories to improve history. If a memory was wrong, add a correction source; if understanding changed, add a reflection source:

```bash
python3 system/lifehug.py source-lint
python3 system/lifehug.py source-lint --fix
printf '%s\n' "$CORRECTION" | python3 system/lifehug.py correct-source answers/A1.md --kind factual
printf '%s\n' "$REFLECTION" | python3 system/lifehug.py reflect-source answers/A1.md
```

`source-lint --fix` is only for safe metadata and manifest repairs. Story meaning is repaired additively through `correct-source` or `reflect-source`. See `system/source_contract.md`.

Run the full weekly self-improvement loop with:

```bash
python3 system/lifehug.py weekly-maintenance
LIFEHUG_WEEKLY_DRY_RUN=1 system/weekly_maintenance.sh
```

The weekly Loop segment compiles offline, lints sources, applies safe source fixes only when lint finds them, classifies capped new sources, updates the quality profile, **runs the question-judgment RUBRIC-EDIT** (`judgment-update`, ADR 0009 — at most one bounded, evidence-cited amendment to `state/question_judgment/learned.md` from the week's owner decisions, immediately after the quality update and before candidate promotion), auto-promotes candidates under caps, writes the next planned queue, **plans one arc card per queued question**, scans gaps in dry-run mode, reports progress, and autocommits real changes. Focus-autopilot is a monthly step, not weekly (ADR 0011 amendment, v170).

**Classification currency (v237, O-C).** A classification has TWO questions asked of it and they are answered by two named predicates in `system/classify_story.py`, never a third: `is_classified(source)` — "does this source still need a RUN?", the batch's question, which a `stale: true` file answers YES — and `is_current(source)` — "is this reading safe to READ?", the ONE reader gate, which a stale file answers NO. Every derived reader goes through the single iterator `classify_story.current_classification_files(CLASSIFICATIONS_DIR)` (Timeline, Mirror, Book, progress, research, focus recommendations, the wiki, the weekly report), so a CONTENT correction excludes its target's stale interpretation from the whole product IMMEDIATELY; the file stays on disk as the batch's target and the person's history, compile proceeds without it, and a model outage never restores a known-stale reading. A test fails the build on any `CLASSIFICATIONS_DIR.glob` outside `classify_story.py`. The batch reaches those targets in bounded time with `--stale-first` (stale oldest-first, then never-classified newest-source-first) resuming after the durable cursor `state/classify_cursor.json` — derived operational memory: rebuildable, deletable, never authority, and a missing or malformed cursor simply means "start at the head". Correction documents are never classification TARGETS; `classify_target_for(correction)` returns the source it corrects, and `--classify <correction>` exits non-zero with `classify_target_is_correction`. **Not every correction marks its target stale (O-C2).** A correction declares its ROLE — `correction_role`, a closed vocabulary of `content` | `placement` in `lifehug_core`, asked through the one predicate `correction_role_marks_stale`. `content` (the default, and every correction filed before O-C2) marks stale, exactly as above. `placement` — what `timeline-place` files — does NOT: dating a moment is a decision ABOUT it, not a claim that the text it was read out of is wrong, and marking it stale withheld the very moment the person had just placed. The placement overlay `state/timeline_placements.json` is what moves the date on read. An unknown role is refused, never defaulted.

**Arc cards (v154, issue #118).** Directly after the queue is written, `lifehug.py arc-plan` plans one card per queued question — an opening framing quoted from the author's own record plus 2–4 typed follow-up intents (unfilled five-slot scene probes, neighborhood siblings, timeline gaps phrased as landmark anchors, studio format slots, a Mirror "sit with" line on self-arc questions, demonstrated-knowledge summaries). Deterministic cards are always computed first, so a model failure, invalid output, or a keyless machine never costs the week its plan; keyless runs additionally emit the prompt to `state/agent_tasks/arcs/` for `arc-plan --from-response`. Cards live in `state/arc_cards.json` and expire with the queue. **This shell step is the parity spec for the platform's `arc_plan` step** — a cap or gate the platform needs must appear here first.

Both loops run on any machine (v92/v123). Check `python3 system/lifehug.py ai-status` first: a ready direct local model, gateway, or keyed provider runs fully unattended; unavailable providers use agent-task mode — follow `skills/maintenance/SKILL.md` (pre-complete AI work via `--emit-prompts`/`--emit-task`/`--from-response` before the run; a keyless cron emits its AI work to `state/agent_tasks/` instead of failing). The direct local route is fail-closed: it never sends source material to another provider when its configured endpoint is offline or rejected. Local and OpenClaw loopback transports bypass proxies and refuse redirects; their errors expose metadata only. The Anthropic SDK is optional; if absent, status stays keyless instead of exiting.

Run the monthly growth loop with:

```bash
python3 system/lifehug.py monthly-research
LIFEHUG_MONTHLY_DRY_RUN=1 system/monthly_research.sh
```

The monthly Loop segment compiles, detects gaps, opens a small capped set of new research neighborhoods, refreshes the self-knowledge arc if needed, recommends Focuses, then **runs focus-autopilot** (ADR 0011 as amended 2026-08-15 — the cadence moved weekly → monthly; approves the single highest-scoring pending idea when the "developing" set is thinner than target, directly after the recommendations refresh and before the roster refresh, gentle by default at 1/run), refreshes entity rosters, **offers at most one conversation thread** from a neighborhood that has record to open from and somewhere left to go (never repeated within a quarter — v154), reports progress, and autocommits real changes.

Review candidate questions before they enter the daily flow:

```bash
python3 system/lifehug.py candidates-review --status candidate
python3 system/lifehug.py candidates-update <candidate-id> --status accepted --target-category A
python3 system/lifehug.py candidates-promote <candidate-id> --category A
```

Candidate promotion appends to `system/question-bank.md` and preserves source provenance. Do not manually copy candidate text into the question bank unless repairing a failed script run.

Use a planned queue only when the user asks for one or the workflow explicitly calls for it:

```bash
python3 system/lifehug.py planner-report --limit 10
python3 system/lifehug.py planner-objective-add "Prepare Mom letter" --category K --keyword mom
python3 system/lifehug.py planner-queue --limit 14 --arc-max 2 --expires-days 7
```

`planner-report` is read-only. `ask.py` uses `state/question_queue.json` only while it is valid and unexpired, then falls back to normal rotation logic.

## Studio: Piece Creation

If the user asks to write/create/draft a letter, post, caption, essay, chapter,
speech, or milestone deliverable, use the Studio piece workflow (code/CLI
term: **artifact**) instead of raw compose. Telegram/OpenClaw messages
beginning with `/artifact`, `artifact:`, or `opinion:` are explicit piece
requests, not daily answers.

```bash
python3 system/lifehug.py artifact new \
  --subject "<subject>" --occasion "<occasion>" --format <letter|tweet|instagram|post|essay|chapter>
python3 system/lifehug.py artifact prompt outputs/<artifact>
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
python3 system/lifehug.py compile
```

Promotion is opt-in and writes immutable sources under `sources/artifacts/`.
Final pieces are authored-expression sources (code term: artifacts); context
packs are derived context sources. Do not rewrite those source bodies later.

### Voice Messages

If the user sends a voice message as their answer:
- Transcribe it (use Whisper or platform transcription)
- Clean up transcription artifacts
- Process as normal text answer
- Note in the answer file that it was originally voice

## Answer Detection

When you receive a message in this workspace context, classify it into exactly one of five intents — the shared definition in `interactions/conversation/router/router.md` (issue #117); `system/lifehug.py route` implements the same contract, and this prose may never diverge from it:

- **`answer`** — a direct reply to the pending question (`system/rotation.json` → `last_question_id`). Process it (see above).
- **`new_story`** — unprompted, not a reply to a pending question. Ingest it — a story now opens or continues a Conversation and gets an immediate turn.
- **`command`** — an explicit instruction about the system itself ("show me coverage", "draft a chapter", "skip this question").
- **`continue_session`** — only makes sense as more of an already-open Conversation. This is the DEFAULT reading of free text whenever a session is open.
- **`out_of_scope`** — general assistant requests, factual lookups, unrelated chit-chat. The scope rule: chats and conversations build the vault, nothing else — send `interactions/conversation/router/deflection.md`'s template warmly, once per exchange, then stay quiet rather than deflect a third time.

Two things are handled BEFORE this classification runs, never as one of the five intents: a pass-transition reply (`awaiting_pass_transition: true` in rotation.json) and the prefix hatches (`/artifact`, `artifact:`, `opinion:`). A new setup conversation (config.yaml absent, or question-bank.md still only A-E) continues the setup flow instead.

Reply-after-close (issue #139, pure-chat wave): when no session is open but a session on that channel closed recently — same day or later — `route`'s output carries `reopen_session_id` and `action:"continue_session"`. That reply is about the subject that just closed, never an unrelated `new_story` — act on it by opening a FRESH session seeded from the closed session's subject (never append to a closed session; the store forbids it by design).

Delegate classification instead of judging by eye:

```bash
printf '%s' "$MSG" | python3 system/lifehug.py route
```

## Weekly/Monthly Rhythms

Follow the rhythms in CLAUDE.md:
- **Weekly**: Run `weekly-maintenance`; review any manual source findings, queue balance, and progress
- **Monthly**: Run `monthly-research`; review new candidates and Focus recommendations
- **Milestones**: Draft deliverables when categories hit GREEN

## File Paths

All paths are relative to this workspace root:
- Questions: `system/question-bank.md`
- Rotation state: `system/rotation.json`
- Coverage: `system/coverage.json`
- Story sources: `sources/manual/`
- Source corrections/reflections: `sources/corrections/`
- Source manifest: `state/source_manifest.json`
- Source lint findings: `state/source_lint_findings.json`
- Question candidates: `state/question_candidates.json`
- Connector state (ledger, cursor, date evidence, calibrated weights): `state/connectors/`
- Planned queue: `state/question_queue.json`
- Planner state: `state/planner_state.json`
- Answers: `answers/`
- Wiki: `wiki/`
- Outputs: `outputs/`
- Config: `config.yaml`
