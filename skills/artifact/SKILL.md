---
name: artifact
description: "Create Lifehug artifacts — letters, posts, captions, chapters, essays, speeches — from accumulated story material or a stated opinion, then optionally promote the final work and context pack into immutable Lifehug sources. Use when the user says /artifact, artifact:, opinion:, write/create/draft a letter/post/caption/chapter/essay, states a philosophical position they want developed, or wants an occasion output like Mother's Day, birthday, anniversary, memorial, or milestone."
---

# Lifehug Artifact Creator

Artifacts (the Studio calls them **pieces**) are what Lifehug is
ultimately trying to help the author make: letters, posts, captions, chapters,
speeches, and other authored outputs. This skill is script-first. Use
`system/lifehug.py artifact ...`; do not hand-create metadata or source
files.

Artifact mutations are typed durable jobs and share the vault-wide writer
with answers, schedules, compiles, and viewer actions. Private drafts,
feedback, reactions, and notes cross the worker boundary through stdin/private
sidecars, never process argv or job metadata. A failed/ambiguous artifact job
is not blindly replayed; report its id for owner review.

## Find The Workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check
`~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run commands from the
workspace root.

## Trigger / Keyword

Explicit triggers:
- `/artifact`
- `artifact:`
- `opinion:` — the author is stating a position/lens they want developed (essay lane)
- "write/create/draft a letter/post/caption/chapter/essay/speech"
- occasion language such as Mother's Day, birthday, anniversary, memorial, or milestone

On Telegram/OpenClaw, treat those messages as artifact requests, not daily
answers. If the user sends a long story without asking for an output, use
`ingest-story` instead. If they state an opinion without asking for an output,
use `ingest-story --kind opinion` and offer the essay.

## Workflow

Ask only for missing essentials:
- subject/person/topic
- occasion
- format: `letter`, `tweet`, `instagram`, `post`, `chapter`, `essay` (develops a stated opinion/position — usually seeded, see below), `unsent_letter` (therapeutic, owner-only, NEVER suggested for sharing — for the deceased or estranged, 'hello again' framing), or `legacy_letter` (ethical-will: values → lessons → gratitude → hopes → forgiveness, pre-populated from the author's material)
- date, if relevant
- audience/privacy, if relevant

Create the artifact task and context pack:

```bash
python3 system/lifehug.py artifact new \
  --subject "<subject>" \
  --occasion "<occasion>" \
  --format <letter|tweet|instagram|post|essay|chapter|unsent_letter|legacy_letter> \
  --date <YYYY-MM-DD>
```

### Essay from a stated opinion (v95)

When the author states a philosophical position (message starts with `opinion:`
or plainly voices a lens on life and wants it developed), ingest FIRST, then
seed the essay from the source file:

```bash
printf '%s\n' "$OPINION_TEXT" | python3 system/lifehug.py ingest-story --kind opinion \
  --source "<telegram|manual>" --title "<short title>"
python3 system/lifehug.py artifact new --format essay --seed sources/manual/<opinion-file>.md
```

The seed is injected verbatim at the top of the context pack — it IS the thesis
and needs no corroboration. Add `--categories`/`--subject` only when supporting
life material should ground the argument. Subject/occasion are NOT required for
essays. Iterate with `artifact save --feedback` until the author says done;
"done" means `artifact final` + `promote-source --kind all` + `compile`, which
turns the essay into source material that influences the wiki (theme pages, the
author hub). Always pass `--feedback` on revisions — it becomes the revision
note shown in the Studio's revision footer (v98), where every version is
linked (★ = final) and Δ shows a word-level diff of what changed.

Print the generation prompt:

```bash
python3 system/lifehug.py artifact prompt outputs/<artifact>
```

You are the model on desktop. In Telegram/OpenClaw, the agent is the model.
Write only the artifact text, following the prompt.

Save the draft:

```bash
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
```

If the user wants revisions, edit from the saved draft and context, then save a
new version:

```bash
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> \
  --feedback "<what changed>" --final
```

When the user approves it as final, promote it into the source layer:

```bash
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
python3 system/lifehug.py compile
```

`--kind all` stores both:
- `artifact_context`: the derived context pack that shaped the work
- `authored_artifact`: the final letter/post/chapter itself

## Source Contract

The final artifact is authoritative as the author's expression at that moment.
It is not independent proof of every underlying event. The context pack is
derived working material. The wiki compiler treats both as supporting,
attributed sources so the system learns from produced work without circularly
turning generated text into primary evidence.

Never rewrite promoted artifact source bodies. If the user changes their mind
later, create a new version or add a correction/reflection source.
