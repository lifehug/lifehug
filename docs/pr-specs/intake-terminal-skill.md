# Intake: the terminal front door for stories, witnessed material and landmark revisions

Status: design, 2026-10-06. Owner: Dave Taylor. Not yet an issue; file one before the first PR.

## What the owner asked for

A skill that runs on the Claude Code subscription (no API key), gives the same
capabilities the hosted platform has, and is a first-class terminal and
browser experience:

- ingest a story, or witnessed material from the family letters, from the
  terminal;
- when that material carries better landmark or cornerstone data than the
  vault holds, ask in the terminal first ("this is new information, update
  it?"), file only on yes;
- then kick off the loop: classify, compile, push, and show status lines
  ("filing", "compiling") ending with a link to the local viewer;
- later, answer the daily question the same way.

The two Williams stays (before and after the mission) are both real and must
stay two entries.

## What already exists, verified on the founder's vault (v324)

| Need | Existing mechanism | Keyless? |
|---|---|---|
| File the owner's own words | `ingest-story` → immutable `sources/manual/` source, manifest, template candidates, optional `--commit` | yes |
| File another person's words | `ingest-story --witness "Dad"` → `witness_account` attributed by `witness_slug`; the compiler renders it beside the author's account and never merges | yes |
| Read a text for landmarks against the store | `landmark-offer --propose --prompts` prints ONE reading prompt; `--completions reading.json` writes the proposal (ADR 0033, Cut 6f host-run protocol) | yes, the agent answers the prompt |
| Know what the vault already holds | every proposal unit is annotated by `landmark_offer.annotate_against_known`: `duplicates` (same stay already filed), `conflicts` (overlaps a different identity, or contradicts a filed "never"), `entity_candidates` | pure |
| Keep two stays apart | `landmarks_interaction.same_landmark_stay`: two stated stretches further apart than the abut window are TWO entries. The 1997 and 2002 Williams stays are separate on this road. | pure |
| File confirmed units | `landmark-offer --apply <proposal> --units a,b` → `timeline.save_landmark`, the one landmark writer; one timeline publication per apply (v298); receipt id; `--retract <receipt>` undoes | yes |
| Classify the source | `classify-story --prompt <source>` → agent → `--from-response` | yes |
| Compile the wiki | `compile` preserves synthesized prose; `compile --emit-tasks` → agent drafts → compile (compile skill Mode 1) | yes |
| Converge with the platform | push to `origin/main`; the platform clones HEAD at its next touch (platform ADR 0011). No code enforces `state/hosted.json` against local CLI mutators. | n/a |
| Local viewer | `lifehug.py serve` → http://127.0.0.1:8765; routes `/views/timeline`, `/views/sources`, `/source-actions?ref=…` | n/a |

Three things are missing, and they are small.

1. **No `revises` annotation.** A unit that is the SAME stay as a filed entry
   but with a different bound is flagged `duplicates` ("filing adds
   nothing"), which is wrong for a date refinement. The merge road would
   reconcile the two claims correctly, but nothing tells the terminal to
   ask. This is the "new information" signal the owner wants.
2. **No evidence basis on the offer road.** `landmark_offer.date_evidence`
   is a bytes test: a year present in the submitted text makes the bound
   `basis: stated`. A letter quote carries its own years, so a date from the
   Church Travel Office itinerary would be filed as something Dave stated.
   The vocabulary already has `document` (weight 7.0) and `relative` (5.5)
   beside `stated` (6.0); the offer road just cannot declare them.
3. **No orchestrator.** Capture, read, ask, file, classify, compile, push,
   report are eight commands today. Nothing prints phase lines or a link.

## Design

One new verb, `lifehug.py intake`, in `system/intake.py`, and one skill,
`skills/intake/SKILL.md`, that drives it from Claude Code. The verb is the
contract; the skill is the voice. A plain shell gets the same phases and the
same link, with y/n prompts instead of the agent's question card.

```
lifehug.py intake --story   [--title T] [--source telegram|cli|...] < text
lifehug.py intake --witness "Dad" [--title T] < text
lifehug.py intake --record <ref> --evidence document < text      # third-party document, see §Evidence
lifehug.py intake --file path.md [--witness NAME | --record REF]
lifehug.py intake --plan ...        # read and ask, file nothing (dry run)
lifehug.py intake --yes             # non-interactive: file every unit the ask would have shown as new; never revisions or conflicts
lifehug.py intake --answer <QID> < text   # phase 2 (not this PR): the daily question through the same road
```

### Phases and what each one prints

Every phase prints one line `intake: <phase> …` before it starts and
`intake: <phase> done (<counts>)` after, so a terminal and the skill show the
same progress and a transcript reads as a log.

| Phase | What happens | Writes |
|---|---|---|
| `preflight` | `git pull --rebase --autostash` (non-fatal); `ai-status` (keyless expected); start `serve` in the background if port 8765 is closed | none |
| `filing` | `ingest-story` (owner / `--witness` / `--record`). The story-conversation hook degrades silently without a provider, which is right: in the terminal the agent IS the conversation. | source file, manifest, candidates, commit |
| `reading` | `landmark-offer --propose --prompts --from-file <filed source>`; the agent answers the one reading prompt; `--completions` writes the proposal | proposal under `state/landmarks/offers/` (durable evidence, R3) |
| `asking` | One card per proposal group, in text order. New unit: file? Revision: current → proposed, basis and confidence of each, which claim wins and that the loser stays as an alternate. Conflict: shown with the entry it overlaps, never auto-filed. Duplicate: one summary line, not a card. The agent uses its question tool; a plain shell prompts y/n/skip. | none |
| `landmarks` | `landmark-offer --apply <proposal> --units <confirmed> --reason "intake <source_id>"`. Prints the receipt id and the undo command. Skipped when nothing was confirmed. | landmark sources, store redraw, one timeline publication |
| `classifying` | `classify-story --prompt <source>` → agent → `--from-response` | `state/classifications/`, candidates |
| `compiling` | `compile`; pages whose inputs changed and have no cached prose are emitted as synthesis tasks scoped to this source, the agent drafts them, compile runs again. Capped (default 6 pages) so one story cannot trigger fifty drafts. | `wiki/`, cache |
| `pushing` | commit, push; on non-fast-forward: pull --rebase, retry once. Prints "Lifehug Cloud will see this at its next touch." | git |
| `report` | counts and links: the source page, the timeline, each wiki page touched, the receipt id | none |

Report shape:

```
intake: done
  source     sources/manual/2026-10-06-dad-s-letter-of-7-june-2002.md   http://127.0.0.1:8765/source-actions?ref=manual:2026-10-06-dad-s-letter-of-7-june-2002
  landmarks  1 revised (Wetzikon, Switzerland · end 6 Jun 2002 → 5 Jul 2002), 0 new, 1 duplicate      receipt 7c1e…  undo: lifehug.py landmark-offer --retract 7c1e…
  timeline   http://127.0.0.1:8765/views/timeline
  wiki       people/dad · periods/switzerland-mission
  loop       3 candidates filed · compiled · pushed (Lifehug Cloud converges at its next touch)
```

### Evidence: who said it, and on what basis

The filing kind and the date basis are decided once, at `filing`, and carried
through `reading` and `landmarks`:

| Flag | Source type | Date basis on every bound | Provenance entry |
|---|---|---|---|
| `--story` | `unprompted_story` (owner) | as today: `stated` when the bytes carry the year, else inferred | none |
| `--witness NAME` | `witness_account` | `relative` | `chronology.witness_provenance(slug, name, said_at, claim)` |
| `--record REF --evidence document` | `external_record` (new general verb, same frontmatter as `sources/gmail/`) | `document` | `{"source": REF, "claim": <quote>, "basis": "document"}` |

`landmark-offer --propose|--apply` gain `--evidence relative|document` and
`--evidence-source <source_id>`; `date_evidence` stays the bytes test and
decides stated-versus-inferred ONLY for `--story`. The reconcile weights do
the rest: a letter's date outranks a memory, a relative's date sits just
under the owner's own, and every losing claim remains an alternate on the
entry. Nothing is deleted.

### The `revises` annotation

`annotate_against_known` gains a third list beside `duplicates` and
`conflicts`:

```json
"revises": [{"entry_id": "residences/wetzikon, switzerland",
             "bound": "end",
             "current": {"best": "2002-06-06", "basis": "stated", "confidence": "certain"},
             "proposed": {"best": "2002-07-05", "basis": "document", "confidence": "certain"},
             "winner": "proposed"}]
```

Computed by running `chronology.reconcile` on the existing bound and the
unit's bound and reporting which wins. `same_landmark_stay` true and all
bounds equal stays a duplicate. `auto_file_eligible` is false for any unit
with a revision: a revision is always asked, never auto-filed, even under
`--yes`.

### Why the offer road and not `landmark-record`

`landmark-record --label` keys on the label alone and would merge a second
Williams stay into the first. The offer road is interval-aware
(`same_landmark_stay`), promotes the submitted text as the citation for every
unit, writes a receipt, and has an undo. R3a: a confirmed offer and an
answered question are indistinguishable downstream. Intake adds no extractor,
no parser, and no second writer.

### `~/Desktop/lifehug-updates/` becomes one intake mode

`intake --from-updates <dir>` reads `index.md` and runs each file as
`--record family-letters:<letter-ids> --evidence document`. **The submitted
text is the WHOLE proposal file** (title, current and proposed values,
confidence, the prose reasoning, and the verbatim quotes with letter ids),
not the quotes alone. It is filed as an immutable `external_record` source
(`authority: third_party_record`), manifested, committed and pushed, so it is
classified, citable by the compiler on the pages it touches, and named in the
provenance of every bound it changes. The Desktop file becomes a receipt; the
vault copy is the durable one. Applied files move to `<dir>/applied/` with
the receipt id appended.

What this mode does NOT store: the letters themselves. The update files cite
letter ids; the transcripts stay in the family-letters repo. Selected full
letters enter the vault through the `letters` connector, a separate design.

No separate "vault-updates" consumer; the updates work within the balance of
the system, as the owner put it.

### Terminal and browser

- The verb prints phase lines; the skill narrates them in the same words and
  asks with its question tool.
- `preflight` starts `serve` if it is not running and every link in the
  report is live.
- The viewer's home hub gets one calm card, "Filed today", listing the
  source, the receipt, and the pages touched (later PR; reads
  `state/landmarks/offers/receipts/` and the manifest, no new state).

### Hosted handoff

`state/hosted.json` marks the platform as writer-of-record and stands local
SCHEDULED loops down. Owner-driven CLI writes are legitimate under platform
ADR 0011 ("everyone asks, answer anywhere") and intake follows the four
shared-vault disciplines. Scheduled loops stay down.

## What is NOT in scope

No new extractor. No deterministic grammar. No bulk import of the letters
archive (that is the `letters` connector, a separate design). No filing of a
revision or a conflict without an explicit yes. No hand edits to
`state/landmarks.json`. No change to the reading prompt, schema or validator
versions.

## PRs, in order (each: version bump, tests, docs, handbook parity per AGENTS.md)

1. **`revises` + `--evidence`** in `landmark_offer.py` and `chronology`
   glue. Pure, fixture-tested: Figers House Aug 1982 → Jun/Jul 1982 from a
   witness letter; Wetzikon end from an itinerary with `document` winning;
   the two Williams stays staying two; a year inside a letter quote filed as
   `document`, never `stated`. Extend `landmarks-evals`.
2. **`intake.py` + `lifehug.py intake` + `skills/intake/SKILL.md`** with
   `--story`, `--witness`, `--file`, `--plan`, `--yes`, phase lines, report,
   scoped compile. The general `--record` external-record verb ships here if
   small, else as its own PR before `--from-updates`.
3. **`--from-updates`** mode plus the family-letters change: the answer pass
   emits a YAML block per proposal file (kind, domain, label, bound, EDTF
   value, evidence source ids) so intake needs no prose parsing.
4. **Phase 2, next session: `intake --answer <QID>` and `intake --next`**,
   wrapping `process-answer` with the same read/ask/file/loop, so the daily
   question can be answered from the terminal with the same experience.
5. **Home card "Filed today"** in the viewer.

## Decisions taken (2026-10-06)

1. Name: `intake`. A story is the owner talking; intake is "here is evidence".
2. Push automatically after the owner's yes.
3. The whole update file is stored in the vault as a source (see
   `--from-updates` above).

## Open question for the owner

- Synthesis cap per intake (proposed 6 pages); the rest wait for the next
  compile.
