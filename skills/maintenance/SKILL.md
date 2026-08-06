---
name: maintenance
description: "Run Lifehug weekly maintenance or monthly research on any machine — ready provider (direct local model, gateway, API key) or keyless (you act as the model via emit-task/from-response paths). Use when the user says /maintenance, 'run weekly maintenance', 'run monthly research', or when state/agent_tasks/ holds tasks a keyless cron run emitted."
---

# Lifehug Maintenance Runner

Runs the weekly and monthly learning loops from any machine. This skill is
script-first: `system/weekly_maintenance.sh` and `system/monthly_research.sh`
own the flow — your job is only to supply the AI steps when the machine is
keyless. Never reimplement classification, promotion, or queue planning by hand.

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check
`~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run all commands from
the workspace root.

## Step 0 — Which mode?

```bash
python3 system/lifehug.py ai-status
```

- **Exit 0** (`AI readiness: ready`) → unattended mode. Just run the
  script; done:
  ```bash
  python3 system/lifehug.py weekly-maintenance    # or: monthly-research
  ```
- **Exit 1** (`AI readiness: not ready`, then `keyless`) → agent mode. **You are the model.** Follow Mode 1. A configured local route intentionally stays here when its server is offline; do not substitute a cloud provider unless the owner changes `ai_provider`.

The Anthropic SDK is optional. If it is absent, provider discovery also stays
in this clean agent-task path; do not install it merely to run Mode 1.

## Mode 1 — Keyless desktop (YOU are the model)

**Pre-complete the AI work BEFORE running the script.** Ordering matters:
quality-update, candidate promotion, and the planner queue all consume
classifications — classify first so this week's queue sees this week's answers.

### Weekly

1. **Classify pending sources.** Emit prompts in one shot:
   ```bash
   python3 system/lifehug.py classify-story --classify-all --unclassified \
       --emit-prompts state/agent_tasks/classify
   ```
   Read `state/agent_tasks/classify/manifest.json`. For each item: read its
   `prompt` file, write the classification JSON it asks for to the `response`
   file in the same directory, then ingest:
   ```bash
   python3 system/lifehug.py classify-story \
       --from-response state/agent_tasks/classify/<response> --source <source>
   ```
   Use only facts present in the source — never invent people, dates, or
   events. (If `manifest.json` says 0 items, nothing is pending — skip ahead.)

   "Unclassified" includes **stale** classifications (v103): filing a
   correction marks its target's classification `stale: true`, so corrected
   sources re-enter this batch automatically. Their prompts carry a LATER
   CORRECTIONS block — those override the story text; never extract the
   corrected-away version.

2. **Synthesize the Mirror** (v100) — the weekly introspection edition built
   from classifier contradictions/insights/positions:
   ```bash
   python3 system/lifehug.py mirror-compile --emit-task state/agent_tasks/mirror
   ```
   Read `state/agent_tasks/mirror/mirror.prompt.md`, write the markdown BODY
   it asks for (the four-section contract: Tensions / What I seem to know /
   Stated positions / Sit with — every claim cited, "and" never "but", no
   trait verdicts) to `state/agent_tasks/mirror/mirror.response.md`, then:
   ```bash
   python3 system/lifehug.py mirror-compile --from-response state/agent_tasks/mirror/mirror.response.md
   ```
   Validation rejects a body that misses a section or exceeds 3 Sit-with items.

3. **Run the script:**
   ```bash
   python3 system/lifehug.py weekly-maintenance
   ```
   The classify step finds nothing pending and passes; the mirror step emits
   its task only when the page work above wasn't done. Everything downstream
   (quality profile, wiki harvest, auto-promotion, planner queue, doctor,
   report, commit) is deterministic and runs normally.

4. **Report** the counts-first summary to the user; the full report is at
   `state/reports/weekly-YYYY-MM-DD.md` (and `/views/reports` in the viewer).

### Monthly

1. **Classify pending sources** (same loop as weekly step 1).
2. **Refresh entity rosters** — for each type, emit → resolve → ingest:
   ```bash
   python3 system/lifehug.py entity-roster --type person --emit-task state/agent_tasks/roster/person.json
   # read the task file, write the resolved roster JSON it asks for, then:
   python3 system/lifehug.py entity-roster --type person --from-response <your-response.json>
   ```
   Repeat for `place`, `period`, `object`, `theme`. **Never leave the
   deterministic fallback roster in place** — it stateless-refreshes junk (the
   v90 lesson); if a roster refresh went wrong, restore via git and re-resolve.
   The `theme` roster (v97) additionally asks you for `keywords` per theme —
   the surface phrases the compiler matches sources with; a page-eligible
   theme entry is what lets a new theme page (e.g. Parenting) graduate.
3. **Synthesize wiki prose if needed** — keyless compile is non-destructive,
   but new/changed pages only get real prose if you write it. Follow the
   **compile** skill's Mode 1 (`compile --emit-tasks` → write drafts →
   `compile`).
4. **Run the script:**
   ```bash
   python3 system/lifehug.py monthly-research
   ```
   Keyless, it emits any remaining AI work (research-expansion prompts) to
   `state/agent_tasks/research/` instead of failing. Complete each one:
   ```bash
   # read the emitted .prompt.md, write the questions JSON, then:
   python3 system/research_expand.py --topic "<topic>" --type <type> --output <output> \
       --from-response <your-response.json>
   ```
   (The emitted message includes the exact completion command per topic.)

## Mode 2 — Completing tasks a keyless cron left behind

If a keyless scheduled run already executed, it emitted its AI work to
`state/agent_tasks/` (`classify/manifest.json`, `roster/<type>.json`,
`research/*.prompt.md`) and reported "⏸ keyless — tasks emitted". Complete each
task via its `--from-response` command as above, then re-run the script so the
downstream learning steps see the results.

## Notes

- `state/agent_tasks/` is transient and gitignored — completed tasks can be
  deleted; the next emission rewrites the directory.
- Without a Telegram token the summary send degrades gracefully; the report
  still lands in `state/reports/` and is committed.
- Dry-run previews work keylessly everywhere:
  `LIFEHUG_WEEKLY_DRY_RUN=1 system/weekly_maintenance.sh`,
  `LIFEHUG_MONTHLY_DRY_RUN=1 system/monthly_research.sh`.
- Everything you ingest flows through the same validation as the keyed path
  (`--from-response` is the same pipeline `call_ai` results use).
