---
name: intake
description: "Here is evidence — file a story, another person's words, or a third-party document (a letter, an itinerary, a proposal from the family-letters archive) into the Lifehug vault from the terminal, read it for landmarks, ASK before any landmark is revised, then classify, compile, push, and hand back a local viewer link. Keyless: you are the model at every model step. Use when the user says /intake, 'intake this', 'here's a letter from Dad', 'file this as evidence', 'this corrects my timeline', or pastes material that should update a landmark or cornerstone."
---

# Lifehug Intake

A story is the owner talking; **intake is "here is evidence."** This skill is
script-first: `python3 system/lifehug.py intake …` owns the eight phases —
capture, read, ask, file, classify, compile, push, report — and prints one
line per phase. You narrate those lines, answer the model prompts it hands
you, and ask the owner the one question that matters: *file this?* Never
reimplement a phase by hand; never write `state/landmarks.json`; never file a
revision or a conflict without an explicit yes.

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check
`~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run from the root.

## What kind of evidence is it?

Decide once, before `start`. It fixes the source type and the date basis
every bound will carry (v397, `landmark-offer --evidence`):

| The text is… | Flag | Filed as | Dates carry |
|---|---|---|---|
| the owner's own words | `--story` | `unprompted_story` | `stated` (when the text carries the year) |
| another person's words (Mom's letter, Dad's text, a sibling's account) | `--witness "Dad"` | `witness_account`, attributed by `witness_slug` | `relative` (5.5 — sits just under the owner's own memory; files as an alternate when the owner's date stands) |
| a third-party document (an itinerary, a bishop's letter, a proposal file from the family-letters archive) | `--record <ref>` | `external_record`, `authority: third_party_record` | `document` (7.0 — outranks a remembered date; the memory stays as an alternate) |

`<ref>` names the document, e.g. `family-letters:dave-mission-2001/travel-itinerary`.
When unsure whether something is a witness or a record, ask the owner one
line: *"Is this Dad's own account, or a document?"*

## Run it

```bash
# the text on stdin (an agent driving) …
printf '%s\n' "$TEXT" | python3 system/lifehug.py intake start --witness "Dad" --title "Dad's letter of 7 June 2002"
# … or from a file (a person at the keyboard gets y/n prompts per card)
python3 system/lifehug.py intake start --record family-letters:dave-mission-2001/travel-itinerary --file letter.md
# read and ask, file nothing:
python3 system/lifehug.py intake start --witness "Dad" --plan < letter.md
```

Every phase prints `intake: <phase> …` then `intake: <phase> done (…)`.
Relay them in the same words. With a ready provider (`ai-status` exit 0)
the verb runs the whole way. **Keyless — the usual desktop case — it stops at
each model step** and prints what it needs and the exact `continue` command:

```
intake: reading needs the reading completion — state/intake/<id>/reading.completion.json
next: python3 system/lifehug.py intake continue <id> --completions state/intake/<id>/reading.completion.json
```

### You are the model (keyless)

1. **Reading.** Read `state/intake/<id>/reading.prompt.md` — it is Add
   Landmark's own reading prompt (ADR 0033) over the whole text with the
   vault's filed entries, roster and age frames in view. Write the ONE
   completion it asks for, as `{"reading": <completion>}`, to
   `reading.completion.json`. Rules that are not negotiable: every unit and
   event quotes words that occur in the text; never a year the text does not
   carry; a date you inferred is not a date you read. Then run the `next:`
   line.
2. **Asking.** The verb prints one card per unit — `[new]`, `[revision]`,
   `[conflict]` — and one summary line for duplicates. A revision card says
   what is filed, what this says, and *which would be shown* (the other stays
   as an alternate). **Ask the owner** with your question tool, one card at a
   time or as one multi-select, in the card's own words. Then:
   ```bash
   python3 system/lifehug.py intake continue <id> --units <id,id>   # exactly what they said yes to
   python3 system/lifehug.py intake continue <id> --all-new         # every new card, no revisions
   python3 system/lifehug.py intake continue <id> --none            # file no landmark
   ```
   `--yes` on `start` is the owner's standing "file what is new"; it never
   files a revision or a conflict.
3. **Classifying.** Read `classify.prompt.md`, write the classification JSON
   it asks for to `classify.response.json` (only facts in the source; echo
   `_classification_snapshot` unchanged), run the `next:` line.
4. **Compiling.** The verb emits synthesis tasks scoped to pages THIS source
   touched, capped at 6 (`--cap`), and lists each `draft <slug> → <path>`.
   Write each page's prose to its `narrative_path` exactly as the compile
   skill's Mode 1 says (only facts in that task's sources; witness accounts
   attributed by name, never merged), then run `intake continue <id>`.
   Pages beyond the cap keep their prior prose until the next compile:
   the closing compile is `compile --no-ai`, model-free, so one story never
   sends the vault's whole uncached backlog to its `wiki_model`.

Pushing and the report need nothing from you. The report ends with the
source page, the timeline, the pages touched, the receipt id and the undo
line:

```
intake: done
  source     sources/manual/2026-10-06-dad-s-letter.md   http://127.0.0.1:8765/source-actions?ref=…
  landmarks  1 revised, 0 new, 1 already known      receipt lmr:…  undo: python3 system/lifehug.py landmark-offer --retract lmr:…
  timeline   http://127.0.0.1:8765/views/timeline
  wiki       people/dad · periods/switzerland-mission
  loop       classified · compiled · pushed (Lifehug Cloud will see this at its next touch.)
```

Hand the owner the links. The viewer is started in `preflight` when port
8765 is closed (`--no-serve` to skip); the push converges with the hosted
platform at its next touch — say so, it is not a failure.

## Doctrine

- The offer road is the only landmark writer intake uses. It is
  interval-aware: two stays at one address stay two entries.
- A revision or a conflict is never auto-filed, even under `--yes`.
- `--plan` writes nothing beyond the durable proposal; a second `--plan` over
  the same text and the same vault generation changes nothing.
- Undo is `landmark-offer --retract <receipt>`; evidence and receipt remain.
- `intake list` / `intake status <id>` show where every intake stands;
  records live under `state/intake/` (gitignored).
- `~/Desktop/lifehug-updates/`-style proposal files are `--record` intakes;
  the whole file is the source body, not only its quotes. Run the folder
  with `--from-updates` (below), never file by file by hand.

## A folder of family-letters updates (`--from-updates`, v399)

```bash
python3 system/lifehug.py intake start --from-updates ~/Desktop/lifehug-updates --plan   # cards only
python3 system/lifehug.py intake start --from-updates ~/Desktop/lifehug-updates          # file
```

Every proposal file in the folder (not `index.md`, not `applied/`) becomes
its own intake: `--record family-letters:<letter ids> --evidence document`,
the WHOLE file as the source body, sensitivity `family`. The batch prints one
`intake: updates [n/N] <file> (<kind>)` line per file and a closing summary
(`N landmark card(s) in F file(s) · flag-only · record-only · waiting ·
applied`).

1. **Readings.** Each waiting file names its `reading.completion.json`; write
   each one exactly as in step 1 above (a file that proposes no landmark of
   the owner's own — a namesake, a bishop, a friend's mission, an uncle's
   family — reads as zero units with the title as a story).
2. **Re-run the same command.** A re-run CONTINUES each file's intake and
   picks up every hand-off file you wrote; it never files a source twice.
3. **Ask, per file.** A file with a `[revision]` or `[conflict]` waits even
   under `--yes`; put each card to the owner, then `intake continue <id>
   --units …` (or `--none`). Do not file a `[new]` card that is really an
   existing entry the reading could not match (a start-only school telling
   beside a graded school reads as new) — say so instead.
4. **Classify and draft**, as in steps 3–4, then re-run once more. Each
   finished file moves to `applied/<file>` with its receipt and undo
   appended. The flag file (`**Proposed value:** no change …`, or `kind:
   flag` front matter) writes nothing and prints its question every run —
   ask the owner that question.
5. A final re-run changes nothing: no commit, no move; only the flag
   question prints.

Kinds come from structure only: optional front matter (`kind:
landmark|record|flag`, `letters:`, `question:`) — the family-letters answer
pass will emit it — else the `**Proposed value:**` field and backticked
`group/letter` ids.
