# Temporary GitHub Issue Drafts

Delete this file after these are created as GitHub issues on `lifehug/lifehug`.

Status legend:
- Shipped: implemented in the current codebase; create only if we want historical tracking.
- Partial: keep as an issue because the first slice exists but important work remains.
- Open: not implemented yet.

Current status:
- Shipped: 1, 2, 7.
- Partial: 3, 4, 5.
- Open: 6, 8, 9, 10.

## 1. Add Unprompted Story Ingest

Status: Shipped in `6f37dcc`.

Build a first-class path for saving a story that was not prompted by a daily question.

Acceptance criteria:
- Add `system/ingest_story.py`.
- Accept story text from stdin and optional `--source`, `--title`, and `--captured-at` flags.
- Save owner-only source files under `sources/manual/`.
- Include metadata for source, title, captured time, visibility, status, related pages, and candidate questions.
- Do not mutate the daily question queue yet.

## 2. Compile Ingested Sources Into The Private Wiki

Status: Shipped in `6f37dcc`.

Extend the wiki compiler so Lifehug wiki pages can cite both answered prompts and unprompted story sources.

Acceptance criteria:
- `system/wiki_compile.py` reads `answers/` and `sources/manual/`.
- Answer files remain primary source material.
- Ingested stories appear as supporting source material on relevant wiki pages.
- Generated pages preserve source citations.
- Wiki compile remains idempotent.

## 3. Add Question Candidate Store

Status: Partial. Keep this issue.

Why this matters:
Lifehug needs a buffer between raw insight and daily delivery. AI, wiki compile, source ingest, and future external imports will generate many possible questions. Those should be reviewable, attributable, and prioritizable before they become part of the question bank. This prevents a single story or ingested corpus from hijacking the author's broader life-story arc.

Shipped:
- `state/question_candidates.json` exists.
- `ingest-story` writes deterministic candidate records with source path, kind, priority, reason, status, and timestamp.
- Candidates do not become daily prompts automatically.

Remaining:
- Add a review/list/promote command for candidates.
- Support candidate status transitions such as accepted, rejected, promoted, deferred.
- Let reviewed candidates become question-bank entries with source citations.
- Preserve candidate provenance when a candidate is promoted into `system/question-bank.md`.
- Add filtering by source path, target wiki page, kind, status, priority, and created date.
- Add tests that promotion cannot duplicate an existing question ID or silently mutate answered questions.

Suggested commands:
- `python3 system/lifehug.py candidates-list`
- `python3 system/lifehug.py candidates-review`
- `python3 system/lifehug.py candidates-promote <candidate-id> --category A`
- `python3 system/lifehug.py candidates-update <candidate-id> --status rejected`

Create a parking lot for possible follow-up questions produced by ingested stories or wiki analysis.

Acceptance criteria:
- Add `state/question_candidates.json`.
- Candidate records include text, source path, target wiki page, kind, priority, reason, status, and created timestamp.
- Ingest can add candidates without making them immediately eligible for the daily prompt.
- Add a review/list command for candidates.

## 4. Add Planner Report

Status: Partial. Keep this issue.

Why this matters:
The planner report should be the operator's dashboard for whether Lifehug is building a complete story. It should answer: what is thin, what is overrepresented, what has gone stale, what new material is waiting, and what the next few questions should accomplish. It should remain read-only so we can trust it before giving the planner more control.

Shipped:
- `system/question_planner.py --report` exists.
- Reports coverage by group, low-coverage categories, open candidates, active queue, and unanswered count.

Remaining:
- Add stale-area detection.
- Add overrepresented-area detection.
- Add recent-ingest and theme balance.
- Show clearer "what the planner would prioritize next" reasoning without changing state.
- Report story-function balance, not just category balance: foundation, scene, tension, turning point, relationship, meaning, contradiction, output gap.
- Identify categories with many answers but weak narrative coverage, such as many reflections but few concrete scenes.
- Include "recommended next queue" output that is preview-only and explains each choice.
- Make the report useful in Dave's real repo without requiring hosted infrastructure.

Guardrails:
- `planner-report` must not write or mutate state.
- It should treat candidates as suggestions, not queue items.
- It should make large-source imbalance visible instead of amplifying it.

Build a read-only planner report before giving the planner control over daily questions.

Acceptance criteria:
- Add `system/question_planner.py --report`.
- Report coverage across memoir, project, spotlight, theme, recent ingest, and open candidates.
- Surface gaps, stale areas, and overrepresented areas.
- Show what the planner would prioritize next without changing state.

## 5. Design Planner-Driven Daily Queue With Caps And Continuity Arcs

Status: Partial. Keep this issue.

Why this matters:
Daily questions need both continuity and breadth. If every day jumps topics, the story feels random and shallow. If the system stays on one thread too long, Dave's whole life story narrows into whichever source or topic was most recent. The planner should create short arcs with explicit caps so Lifehug can deepen important areas while preserving the full life picture.

Shipped:
- `planner-queue` writes an opt-in `state/question_queue.json`.
- `ask.py` uses the planned queue only when it exists and contains valid unanswered question-bank items.
- The queue has simple group caps and per-category arc limits.

Remaining:
- Define richer planner state, likely `state/planner_state.json`.
- Support active objectives, continuity arcs, and planner explanations.
- Include reviewed candidates in the planning process.
- Add stronger guardrails against large ingests dominating the story.
- Model active objectives such as "prepare Mother's Day letter for Mom" or "strengthen Etherfuse founding chapter".
- Add queue metadata explaining why each question was chosen and when the queue should expire.
- Add caps across source type, project, spotlight, theme, and story function.
- Add stale-queue handling so old planned queues do not silently control daily delivery forever.

Add a strategy layer that balances foundational story work, depth, active spotlights, projects, themes, and recent ingest.

Acceptance criteria:
- Define planner state in `state/planner_state.json`.
- Support short continuity arcs without locking onto one topic indefinitely.
- Enforce caps so large ingests, such as Twitter or email, cannot dominate future questions.
- Preserve broad life-story coverage as the primary mission.
- Keep `ask.py` fallback behavior stable if planner state is missing or invalid.

## 6. Add AI Classification And Synthesis For Ingested Sources

Status: Open.

Why this matters:
Manual ingest currently stores a story and creates deterministic generic candidates. The next step is for AI to read the source and identify what the story is really about: people, places, time periods, themes, projects, unresolved contradictions, possible outputs, and new spotlight opportunities. This is the bridge from "source storage" to an evolving Lifehug wiki.

Use AI to classify ingested stories and suggest links, wiki updates, and candidate questions.

Implementation notes:
- Start with local/manual command flow before cron automation.
- Store AI output as reviewable metadata next to the source or in a derived state file; do not silently trust it as fact.
- Suggested wiki edits should cite the source file and show enough evidence for review.
- Suggested questions should enter `state/question_candidates.json`, not the daily queue.
- Classification should use owner-only defaults and should not introduce access tiers yet.

Acceptance criteria:
- AI classification identifies people, places, periods, projects, themes, and possible new spotlights.
- Classification output is stored as metadata, not silently trusted.
- Suggested wiki changes cite source files.
- Suggested questions go to the candidate store first.
- No external ingested corpus should bypass owner-only privacy defaults.
- Add tests or dry-run fixtures for at least one manually ingested story.

## 7. Prepare Future Privacy And Access Tiers Without Building Them Yet

Status: Shipped in `6f37dcc`.

Keep the first product simple and owner-only, but avoid painting the architecture into a corner.

Acceptance criteria:
- Preserve `visibility`, `sensitivity`, and source metadata on wiki/source records.
- Document that all current content is owner-only.
- Do not implement granular sharing/access tiers in this phase.
- Ensure future public/shared output generation can be built from reviewed outputs, not raw private wiki exposure.

## 8. Generate Deep Research-Style Question Neighborhoods

Status: Open.

Why this matters:
Some topics deserve more than a single follow-up. A person, place, childhood pattern, company chapter, or recurring theme can become a "neighborhood" of questions that explores foundation, chronology, scene, conflict, relationships, meaning, contradiction, and output needs. This is how Lifehug becomes more like a lifelong oral-history researcher instead of a random question generator.

Create a way for Lifehug to generate new neighborhoods of questions from a story, theme, person, period, project, or wiki page.

Implementation notes:
- The output should be candidate questions first, grouped by neighborhood and story function.
- A neighborhood should cite the source page or wiki page that triggered it.
- The operator should be able to activate a neighborhood as an objective, but it should not dominate the daily queue by default.
- This should reuse the storytelling research rubric in `system/research.md`.

Acceptance criteria:
- Add a research-style question expansion mode that starts from a target page or source.
- Generate clustered question neighborhoods, not just one-off follow-ups.
- Support different neighborhood types such as foundation, chronology, sensory detail, relationships, conflict, meaning, contradiction, and output-oriented questions.
- Store generated questions as candidates first, with source citations and reasons.
- Ensure deep neighborhoods do not dominate the daily queue unless explicitly selected as an active objective.
- Add a planner report section showing open neighborhoods and whether any are active.

## 9. Recommend New Spotlights From Stories And Wiki Development

Status: Open.

Why this matters:
Lifehug should notice when a person, place, period, project, object, or theme has enough gravity to deserve its own arc. The user can always add spotlights manually, but the system should help surface "you keep mentioning this" moments with evidence. This is especially important once ingest brings in older stories, chats, emails, or social posts.

Use accumulated stories and wiki changes to recommend new spotlights worth developing.

Implementation notes:
- Recommendation should be evidence-backed and conservative.
- A weak signal might be one mention with high emotion; a strong signal might be repeated mentions across answers, ingested stories, and wiki pages.
- Recommendations should be reviewable and dismissible.
- Approved recommendations can create candidate questions first, then a question-bank spotlight only after user approval.

Acceptance criteria:
- Analyze answers, ingested sources, candidate questions, and wiki pages for recurring people, places, periods, projects, objects, or themes.
- Recommend spotlight candidates with evidence, source links, and a short reason.
- Distinguish between strong recommendations and weak signals.
- Do not automatically create spotlights without user approval.
- Feed approved spotlight recommendations into the question candidate system and planner.
- Add a report command or planner section for spotlight recommendations.

## 10. Operationalize The Storytelling Research Rubric

Status: Open.

Why this matters:
The original Lifehug research still exists in `system/research.md` and is visible in Dave's question bank: good questions ask for scenes, stakes, sensory detail, emotional truth, turning points, relationships, and reflection. But the system does not yet enforce that methodology across ingest, candidate generation, planner decisions, or AI-generated follow-ups. This issue turns the research from background documentation into a product primitive.

Problem:
- The current question bank contains strong research-shaped questions, but quality depends on the operator or AI prompt.
- `gen_followups.py` includes a depth-question rubric, but candidate generation and planner reports do not score questions against the same rubric.
- The planner balances broad groups like main/project/spotlight, but not story function.
- Future AI ingest could generate shallow, repetitive, or over-indexed questions unless the system can evaluate story purpose.

Build:
- Define a story-function taxonomy based on `system/research.md`, for example:
  - `foundation`: context the reader needs before the story works.
  - `scene`: concrete memory, place, sensory detail, dialogue.
  - `tension`: what was at stake, fear, obstacle, conflict.
  - `turning_point`: what changed and when.
  - `relationship`: who mattered and how the bond shifted.
  - `meaning`: what the author understands now.
  - `contradiction`: unresolved tension, surprising mismatch, or self-conflict.
  - `output_gap`: missing material needed for a letter, essay, chapter, or post.
- Add these fields to candidate records where appropriate:
  - `story_function`
  - `research_principles`
  - `target_output`
  - `quality_notes`
- Add a question-quality check that flags weak candidates:
  - yes/no wording
  - too broad or generic
  - no source citation
  - no concrete scene or emotional/stakes path
  - duplicate of an existing question
- Teach `planner-report` to show whether upcoming questions are balanced across story functions.
- Teach future AI synthesis prompts to use the rubric directly.

Acceptance criteria:
- `system/research.md` is referenced by at least one script or prompt path beyond static docs.
- Candidate questions can carry story-function metadata.
- Planner report shows story-function coverage or imbalance.
- Weak candidate questions can be flagged before promotion.
- Existing daily rotation continues working if this metadata is absent.
- Tests cover backward compatibility with old candidate records.

Guardrails:
- Do not make the system overly academic; the output should still feel like a human interviewer.
- The rubric should guide question quality, not block the user from capturing raw stories.
- Preserve the owner-only privacy model.
