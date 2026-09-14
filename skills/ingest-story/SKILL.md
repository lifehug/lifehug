---
name: ingest-story
description: >-
  Capture an unprompted life story, family fact dump, opinion, or witness
  account into a Lifehug vault via the CLI — never hand-edit wiki pages. Use
  when the user says /ingest-story, shares a memory that is not an answer to
  the pending daily question, states an opinion:, or the router returns
  new_story.
---

# Lifehug ingest-story

Script-first capture of material that is **not** an answer to the pending daily question. Writes owner-only source under `sources/manual/`; the wiki grows via compile/classify. Never hand-edit `wiki/people/` or rewrite existing sources.

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check `~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run commands from the workspace root Lifehug expects (`--vault-root` / `LIFEHUG_VAULT_ROOT` when the framework is installed separately).

## Classify first

If the user already named the intent (e.g. `/ingest-story`, `opinion:`), skip the menu and go. Otherwise pick:

| Situation | Command |
|---|---|
| Reply to pending daily question | `process-answer <QID>` — **not** ingest-story |
| Unprompted memory / story / family facts | `ingest-story` |
| Stated opinion / life lens | `ingest-story --kind opinion` |
| Someone else's words | `ingest-story --witness "Name"` |

Delegate when unsure:

```bash
printf '%s' "$MSG" | python3 system/lifehug.py route
```

Act on `ingest_story` / `new_story`; never treat an `answer` as ingest-story.

## Capture

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story \
  --source "<channel>" \
  --title "<short title>"
```

Useful flags:

- `--kind opinion` — Socratic follow-ups; then optional essay via `artifact new --format essay --seed …`
- `--witness "Mom"` — second-voice / witness source (cannot combine with `--kind opinion`)
- `--sensitivity private|family|friends|public` — defaults to private

## After ingest

```bash
python3 system/lifehug.py compile
```

Weekly maintenance will classify unclassified sources. Do not promote candidates or invent wiki pages by hand.

## Corrections

Never rewrite the original source. Use:

```bash
printf '%s\n' "$CORRECTION" | python3 system/lifehug.py correct-source <path> --kind factual
printf '%s\n' "$REFLECTION" | python3 system/lifehug.py reflect-source <path>
python3 system/lifehug.py fix <path> --wrong "..." --right "..."
```

## Family / program bots

Operational trackers (e.g. birthdays) may live outside the vault. When the same facts should enter the life-story vault, ingest them with this skill as a titled story — do not patch wiki pages directly.

## Hard rules

1. Never force unprompted material into `answers/{qid}.md`.
2. Never hand-edit compiled wiki pages for facts that belong in sources.
3. Prefer the CLI over reimplementing ingest logic.
