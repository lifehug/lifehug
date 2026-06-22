---
name: lifehug
description: "Capture your life story through daily AI-guided questions. Use when: (1) setting up a new Lifehug workspace, (2) processing a reply that is an answer to a Lifehug daily question, (3) checking Lifehug coverage/status, (4) drafting chapters or essays from accumulated answers, (5) managing Lifehug spotlights for important people/episodes. Triggers: user mentions lifehug, life story, memoir questions, daily question, 'answer to my lifehug question', or the workspace contains AGENTS.md referencing Lifehug."
---

# Lifehug Skill

Lifehug captures life stories through one daily question. You are the interviewer.

## Workspace Detection

Find the Lifehug workspace. Check in order:
1. `~/Workspace/lifehug/`
2. `~/lifehug/`
3. Any directory with `system/question-bank.md` and `system/ask.py`

If not found, ask the user to clone it:
```
git clone https://github.com/lifehug/lifehug.git ~/Workspace/lifehug
```

## Setup (First Run)

Detect fresh install: `system/question-bank.md` has only categories A-E (no F-J).

1. Welcome — explain Lifehug simply
2. Ask what they want to write (memoir, founder story, family history, etc.)
3. Ask who matters (people to spotlight)
4. Ask about key episodes they already know they want to tell
5. Generate custom question bank — add categories F-J with 3-5 questions each
6. Write to `system/question-bank.md`
7. Create `config.yaml` with their name, timezone, channel, question time
8. Set up daily cron:

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "<MIN> <HOUR> * * *" \
  --tz "<TIMEZONE>" \
  --channel <CHANNEL> \
  --announce \
  --task "You are the Lifehug interviewer. cd <WORKSPACE> && python3 system/ask.py — send the question warmly. If rotation.json shows a pending unanswered question, gently remind them first. End with: 'Reply here whenever you're ready — voice or text.'"
```

9. Ask the first question

## Processing Answers

When a user's message looks like an answer to a Lifehug question (personal, reflective, about their life):

1. Check `system/rotation.json` → `last_question_id` for the pending question
2. Save to `answers/{question_id}.md`:

```markdown
# Question {ID}: {text}
**Category:** {letter} ({name}) | **Pass:** {pass}
**Asked:** {date} | **Answered:** {date}

---

{cleaned answer}

---

## Follow-up Questions Generated
- {ID}: "{follow-up}"
```

3. Generate 1-3 follow-up questions (sensory, emotional, specific, contrast)
4. Add follow-ups to `system/question-bank.md`
5. Run `python3 system/ask.py --mark-answered {ID}`
6. Commit: `Answer {ID}: {brief summary}`
7. Acknowledge warmly — reflect briefly on their answer

## Answer Detection

When receiving a message, check if it's a Lifehug answer:
- Is there a pending question in `rotation.json`?
- Does the message sound like a life story answer (personal, reflective, detailed)?
- Did the user reply to a Lifehug question message?

If yes → process as answer. If unclear → ask: "Is this your answer to the Lifehug question, or something else?"

## Commands

- "lifehug status" / "how's my story going" → Run `python3 system/ask.py --status`
- "skip this question" → Pick next question without marking answered
- "draft a chapter" → Read relevant answers, draft in user's voice, save to `drafts/`
- "add spotlight person [name]" → `spotlight.add(type=person)` — see **Spotlight: add** below
- "add spotlight time [event]" → `spotlight.add(type=time)` — coming soon
- "add spotlight place [location]" → `spotlight.add(type=place)` — coming soon

## Spotlight: add

Command: `spotlight.add(type, subject)`

A spotlight is a focused question set about an important person, time period, or place in the author's life. Each spotlight gets its own category (K, L, M, … next available letter) and follows a **baseline-first arc** — establish the subject before drilling into specific moments.

### Types

| Type | Subject | Example |
|------|---------|--------|
| `person` | An important person | "add spotlight person — my dad James" |
| `time` | A defining period or episode | "add spotlight time — the bankruptcy year" *(coming soon)* |
| `place` | A formative location | "add spotlight place — Yucaipa" *(coming soon)* |

---

## spotlight.add — type: person

A spotlight is a focused question set about an important person in the author's life. Each spotlight gets its own category (K, L, M, … next available letter) and follows a **baseline-first arc** — establish who the person is before drilling into specific moments.

### Step 1 — Find the next available category letter

```bash
grep "^## [A-Z]:" <workspace>/system/question-bank.md | tail -1
```

Take the letter after the last one found (e.g. if L is last, new spotlight is M).

### Step 2 — Scan existing answers for mentions of the person

```bash
grep -r -l -i "<name>" <workspace>/answers/*.md
```

For each matching file, read the relevant passages. Build a picture of:
- What the author has already said about this person
- Emotions, conflicts, and formative moments that have surfaced
- Appearance, personality, values, and role in the author's story
- Unresolved threads worth exploring

### Step 3 — Build the question arc

Questions must follow this **baseline-first order**. Do NOT jump to specific events in the first 4–5 questions.

#### Tier 1 — Foundational identity (questions 1–5)
Establish who the person IS before anything happened:
- Q1: "Tell me about [name]. Who were they as a person — not as [role], just as a human being?"
- Q2: Physical presence / how they carried themselves
- Q3: What they cared about — passions, interests, what lit them up
- Q4: Earliest memory of this person
- Q5: What the day-to-day relationship felt like

#### Tier 2 — Relationship dynamics (questions 6–8)
- The friction or complexity in the relationship (if any)
- A specific memory of their character in action
- A skill, gift, or quality the author watched and admired

#### Tier 3 — Turning points (questions 9–11)
- When the relationship shifted
- A defining episode (illness, loss, a hard conversation, a sacrifice)
- What the author wishes they'd said or asked

#### Tier 4 — Legacy and meaning (questions 12–13)
- How this person lives on (named child, inherited trait, lesson carried forward)
- The adult-to-adult question: if you met as strangers, who would they be?

### Step 4 — Write the category block

Append to `system/question-bank.md`:

```markdown

## {LETTER}: Spotlight — {Name}
*Discovered from {source_answers} — {2-3 word characterization}*
- [ ] {LETTER}1: Tell me about {first name}. Who were they as a person — not as your {role}, just as a human being?
- [ ] {LETTER}2: What did {first name} look like? How did they carry themselves?
- [ ] {LETTER}3: What did {first name} care about most — their passions, interests, what lit them up?
- [ ] {LETTER}4: What's your earliest memory of {first name}?
- [ ] {LETTER}5: How would you describe your relationship day to day?
... (continue through tiers 2–4, tailored to what the scan revealed)
```

### Step 5 — Verify and commit

```bash
cd <workspace>
python3 system/ask.py --status   # confirm new category appears
git add system/question-bank.md
git commit -m "Add spotlight {LETTER}: {Name}"
```

### Notes
- Keep 10–14 questions total per person spotlight
- Tier 1 questions are nearly universal; tiers 2–4 should be specific to what the scan revealed
- The scan step is critical — questions grounded in what's already been said feel personal, not generic
- If little has been said about the person yet, lean harder on Tier 1 open questions and fewer Tier 3/4 specifics

---

## spotlight.add — type: time

*(Coming soon — question arc for defining periods: what was happening, what it felt like, how it changed things, what it meant)*

---

## spotlight.add — type: place

*(Coming soon — question arc for formative locations: what it looked like, who was there, what happened, why it still matters)*

## Voice Messages

If the answer is a voice message: transcribe, clean up artifacts, process as text. Note `**Source:** voice (transcribed)` in the answer file.