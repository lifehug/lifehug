---
name: focus
description: "Guided Lifehug Focus manager — add a new Focus (a person, book, blog, theme, or life's work) end-to-end, show the roadmap and progress toward deliverables, mark a Focus as finishing, or tune one. Use when the user says /focus, 'add a focus', 'new focus', 'what am I working toward', 'show my roadmap', or wants to manage what their Lifehug is building toward."
---

# Lifehug Focus Manager

A **Focus** is anything the user is building toward — a person, a book, a blog, a theme, their life's work. Each has an objective and a tier (`basic` ≈ blog/~8 answers, `standard` ≈ essay/chapter/a person/~20, `extreme` ≈ book/life's work/~50+). This skill is script-first: drive `system/lifehug.py`; never hand-edit `state/roadmap.json` or `system/question-bank.md`.

## Find the workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check `~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run all commands from the workspace root.

## Pick the action

If the user already said what they want (e.g. "add a focus on my faith"), skip the menu and go. Otherwise ask:

> What would you like to do?
> 1. **Add** a new focus
> 2. **Show** my roadmap / progress
> 3. **Finish** — mark a focus as finishing (push it to done)
> 4. **Tune** a focus (tier, target, objective)

## 1. Add a focus (the interview)

Ask these one at a time, conversationally — don't dump all four at once:

1. **What do you want to build toward?** → the label + objective + deliverable.
   (e.g. "a letter to my daughter" → label "Letter to Maya", deliverable `letter`.)
2. **How big is it?** → tier: a quick post is `basic`, an essay/chapter or a single person is `standard`, a whole book or your life's work is `extreme`.
3. **What kind of thing is it?** → type: `person`, `relationship`, `project`, `theme`, `place`, `period`, `event`, `lifes_work`, or `self` (self-knowledge).
   - For a person you already spotlight, or to deepen a relationship, prefer `relationship`.
   - For "understanding myself" topics, use `self`.

Then create it in one command:

```bash
python3 system/lifehug.py focus-new "<label>" \
  --type <type> --tier <tier> \
  --objective "<objective>" --deliverable <book|chapter|essay|letter|post>
```

`focus-new` scaffolds a new question-bank category, registers the Focus on the roadmap, and **auto-generates ~8–12 starter questions** toward the objective. Generation uses the OpenClaw gateway when it's running (cron path — no API key needed), or `ANTHROPIC_API_KEY` as a fallback. If neither is available — the usual case on the desktop — the Focus is still created and you generate the questions yourself (next section). It never touches existing answers.

After it runs, confirm what happened and show the result:

```bash
python3 system/lifehug.py progress
```

Tell the user the Focus is on the roadmap and (once questions exist) will start surfacing in their daily questions. Commit only if the user asks, or when operating a daily/cron workflow.

### Generate the questions on the desktop (keyless — you are the model)

On the desktop there's usually no gateway or key, so `focus-new` scaffolds the Focus but generation doesn't run. Do it yourself — the script emits the prompt, you write the questions, the script deposits them. No key needed.

`<research-type>` maps period→time_period and lifes_work→project; other types match the focus type. `<slug>` is the label slugified (e.g. "My Faith" → `my-faith`).

1. **Get the prompt** (no model call):
   ```bash
   python3 system/research_expand.py --prompt --topic "<label>" --type <research-type> --output <deliverable> > /tmp/focus_prompt.txt
   ```
2. **Write the questions.** Read `/tmp/focus_prompt.txt` and follow it: produce the questions as the JSON object it specifies (`{"questions": [...]}` with `text`, `story_function`, `priority`, `reason` per item). Write just that JSON to `/tmp/focus_resp.json`.
3. **Deposit** (no model call):
   ```bash
   python3 system/research_expand.py --topic "<label>" --type <research-type> --output <deliverable> --from-response /tmp/focus_resp.json
   ```
4. **Promote into the question bank:**
   ```bash
   python3 system/lifehug.py candidates-promote-neighborhood --neighborhood nbhd-<slug> --category <letter>
   ```

Then show `python3 system/lifehug.py progress` and confirm warmly.

## 2. Show roadmap / progress

```bash
python3 system/lifehug.py roadmap     # every Focus, tier, saturation
python3 system/lifehug.py progress    # readiness + the compose command for anything ready to draft
```

Summarize warmly: what's well-covered, what's thin, what's ready to turn into a deliverable.

## 3. Finish a focus

When the user wants to push a deliverable to done, lift its variety cap so it gets more of each week:

```bash
python3 system/lifehug.py focus-finish <focus-id>
```

Find the id from `roadmap` (it's the slug, e.g. `etherfuse`). Remind them it relaxes back to maintenance once the work is answered.

## 4. Tune a focus

```bash
python3 system/lifehug.py focus-set <focus-id> --tier <tier> --target <N> --objective "<...>" --deliverable <...>
```

Use this to change scale (tier/target), re-point the objective, or set `--phase maintenance` to back off a Focus without deleting it.

## Notes
- Don't create a Focus from a weak signal — confirm the objective with the user first.
- A Focus over **existing** categories doesn't need `focus-new`; use `focus-add … --category X`.
- Deleting a Focus is manual for now (remove it from `state/roadmap.json` and the category from `question-bank.md`); offer to do it carefully if asked.