---
name: compile
description: "Compile the private Lifehug wiki from answers and story sources — synthesize each page into prose with derived related links and backlinks, then optionally view it. Use when the user says /compile, 'compile the wiki', 'rebuild the wiki', 'update my wiki', 'regenerate the wiki', or wants their answers turned into wiki pages."
---

# Lifehug Wiki Compiler

Compiles `answers/` and `sources/manual/` into the private, owner-only wiki under `wiki/`. Each page is synthesized into flowing prose with content-derived `related:` links, plus auto-derived **backlinks** and shared-source "see also" edges, so the wiki is a navigable graph. This skill is script-first: drive `system/lifehug.py compile`; never hand-edit pages under `wiki/` (they are regenerated).

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check `~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run all commands from the workspace root.

## Compile

Default — synthesize pages with an LLM (OpenClaw gateway if running, else `ANTHROPIC_API_KEY`); falls back to deterministic excerpts per page if no LLM is available:

```bash
python3 system/lifehug.py compile
```

Useful variations:

```bash
python3 system/lifehug.py compile --dry-run   # preview which pages would change, write nothing
python3 system/lifehug.py compile --no-ai      # deterministic excerpts only (no API/tokens)
python3 system/lifehug.py compile --model <id> # override the synthesis model
```

Notes:
- Re-compiles are **idempotent and cached** (`state/wiki_synthesis_cache.json`) — only pages whose source material changed are re-synthesized, so running it again is cheap and reports `0 page updates` when nothing changed.
- If you only want to confirm what would change first, run `--dry-run`, then run for real.
- Before a real (non-`--no-ai`) compile, make sure `config.yaml` has `name:` set — otherwise relationship pages compile as `me-and-*` instead of `<name>-and-*`.

After it runs, tell the user how many pages updated (from the `✓ Wiki compile complete: N page updates` line).

## View the result

Offer to open the local viewer so they can click through the graph:

```bash
python3 system/lifehug.py serve   # serves the owner-only wiki at http://127.0.0.1:8765
```

`[[wikilinks]]` resolve to real pages; unresolved ones fall back to search.

## Notes
- Commit only if the user asks, or when operating a daily/cron workflow.
- No answers or sources are ever modified — compile only writes under `wiki/` and the synthesis cache in `state/`.
