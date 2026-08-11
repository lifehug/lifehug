---
name: compile
description: "Compile the private Lifehug wiki from answers and story sources — synthesize each page into prose with derived related links and backlinks, then optionally view it. Use when the user says /compile, 'compile the wiki', 'rebuild the wiki', 'update my wiki', 'regenerate the wiki', or wants their answers turned into wiki pages."
---

# Lifehug Wiki Compiler

Compiles `answers/` and `sources/manual/` into the private, owner-only wiki under `wiki/`. Each page becomes synthesized prose with content-derived `related:` links, auto-derived **backlinks**, and shared-source "see also" edges — a navigable graph, not an excerpt dump. This skill is script-first: `system/wiki_compile.py` (via `system/lifehug.py compile`) owns the structure, citations, cross-linking, and index. Never hand-edit pages under `wiki/` — they are regenerated.

A real `lifehug.py compile` is a typed durable job and shares the vault-wide
writer lock; `--dry-run` remains direct. Repeating an identical manual compile
creates a fresh job, while an explicit schedule identity deduplicates scheduler
retries. Do not call `wiki_compile.py` directly for a real write.

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check `~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run all commands from the workspace root.

## Where the prose comes from

A page's prose can be written four ways. The script picks the first available, per page:

1. **Cached** — a prior synthesis for unchanged source material (`state/wiki_synthesis_cache.json`). This cache is **committed to the repo**, so prose synthesized on one machine (the compile machine) travels to every other machine. A page is only re-synthesized when its inputs change.
2. **Agent draft** — prose you (Claude) wrote to `state/synthesis/<slug>.md` (the keyless desktop path — see Mode 1).
3. **Gateway/API** — `call_ai` via the OpenClaw gateway (keyless, if running) or `ANTHROPIC_API_KEY` (the cron path — Mode 2).
4. **Excerpt fallback** — deterministic source excerpts, **only for a page that was never synthesized**. Compile will **never** downgrade an already-synthesized page (frontmatter `synthesized: true`) to excerpts — it preserves the last good prose and logs `↻ preserved <slug>`. So a bare `compile` on a keyless machine is safe; at worst a changed page keeps its prior prose until a real synthesis runs.

The Anthropic SDK is optional. If it is absent, `ai-status` reports keyless and
this agent-draft path remains available; do not install the SDK just to compile
through an agent.

## Mode 1 — Desktop through Claude Code (keyless; YOU synthesize)

On the desktop there is usually no API key and no OpenClaw gateway. That's fine: **you are the model.** Do the synthesis yourself, then let the script assemble the graph.

1. **Emit tasks** (no model call):
   ```bash
   python3 system/lifehug.py compile --emit-tasks /tmp/wiki_tasks.json
   ```
   This writes one task per page that still needs prose. Each task has: `slug`, `type`, `title`, `narrative_path`, `sources` (the cited material — the only facts you may use), and `related_candidates` (the other pages, by slug).

2. **Write each page's prose.** Read `/tmp/wiki_tasks.json`. For every task, write 2–4 short paragraphs of faithful, encyclopedia-style prose about that `title` to its `narrative_path` (`state/synthesis/<slug>.md`). Rules:
   - Use **only** facts present in that task's `sources`. Never invent names, dates, or events.
   - Weave in `[[slug]]` links to genuinely related pages drawn from `related_candidates` — these become the page's related links and resolve in the viewer.
   - Optionally start the file with one line `Related: slug-a, slug-b` to set related links explicitly; otherwise they're inferred from the `[[links]]` in your prose.
   - Don't add the title as a heading or a sources/backlinks list — the script adds those.
   - Many pages: write them in batches; you can skip a page by leaving its file unwritten (it falls back to excerpts).

3. **Assemble** (consumes your drafts into the cache, builds the graph, writes pages):
   ```bash
   python3 system/lifehug.py compile
   ```
   Report the `✓ Wiki compile complete: N page updates` count.

Because results are cached, a later `--emit-tasks` only re-asks for pages whose source material changed — you won't redo work.

## Mode 2 — Cron / OpenClaw (unattended)

When run by cron with the OpenClaw gateway up (or `ANTHROPIC_API_KEY` set), a single command synthesizes everything programmatically — no agent in the loop:
```bash
python3 system/lifehug.py compile
```
This is what `system/daily_question.sh` / the cron job invokes. Same script, same output shape as Mode 1.

## Offline / preview

```bash
python3 system/lifehug.py compile --no-ai     # deterministic excerpts only (no prose, still builds the graph)
python3 system/lifehug.py compile --dry-run    # preview which pages would change, write nothing
python3 system/lifehug.py compile --model <id> # override the synthesis model (gateway/API path)
```

## View the result

Offer to open the local viewer so the user can click through the graph:
```bash
python3 system/lifehug.py serve   # owner-only wiki at http://127.0.0.1:8765
```
`[[wikilinks]]` resolve to real pages; unresolved ones fall back to search.
Source Integrity opens manifested raw sources read-only and links them to the
existing additive reflection, correction, and retraction actions.

## Notes
- Re-compiles are **idempotent**: unchanged pages report `0 page updates`.
- Before a real compile, make sure `config.yaml` has `name:` set, or relationship pages compile as `me-and-*` instead of `<name>-and-*`.
- Compile only writes under `wiki/` and the cache/drafts in `state/` — answers and sources are never modified.
- Commit only if the user asks, or when operating a daily/cron workflow.
