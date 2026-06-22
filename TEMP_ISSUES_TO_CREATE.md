# Temporary GitHub Issue Drafts

Delete this file after these are created as GitHub issues on `lifehug/lifehug`.

## 1. Add Unprompted Story Ingest

Build a first-class path for saving a story that was not prompted by a daily question.

Acceptance criteria:
- Add `system/ingest_story.py`.
- Accept story text from stdin and optional `--source`, `--title`, and `--captured-at` flags.
- Save owner-only source files under `sources/manual/`.
- Include metadata for source, title, captured time, visibility, status, related pages, and candidate questions.
- Do not mutate the daily question queue yet.

## 2. Compile Ingested Sources Into The Private Wiki

Extend the wiki compiler so Lifehug wiki pages can cite both answered prompts and unprompted story sources.

Acceptance criteria:
- `system/wiki_compile.py` reads `answers/` and `sources/manual/`.
- Answer files remain primary source material.
- Ingested stories appear as supporting source material on relevant wiki pages.
- Generated pages preserve source citations.
- Wiki compile remains idempotent.

## 3. Add Question Candidate Store

Create a parking lot for possible follow-up questions produced by ingested stories or wiki analysis.

Acceptance criteria:
- Add `state/question_candidates.json`.
- Candidate records include text, source path, target wiki page, kind, priority, reason, status, and created timestamp.
- Ingest can add candidates without making them immediately eligible for the daily prompt.
- Add a review/list command for candidates.

## 4. Add Planner Report

Build a read-only planner report before giving the planner control over daily questions.

Acceptance criteria:
- Add `system/question_planner.py --report`.
- Report coverage across memoir, project, spotlight, theme, recent ingest, and open candidates.
- Surface gaps, stale areas, and overrepresented areas.
- Show what the planner would prioritize next without changing state.

## 5. Design Planner-Driven Daily Queue With Caps And Continuity Arcs

Add a strategy layer that balances foundational story work, depth, active spotlights, projects, themes, and recent ingest.

Acceptance criteria:
- Define planner state in `state/planner_state.json`.
- Support short continuity arcs without locking onto one topic indefinitely.
- Enforce caps so large ingests, such as Twitter or email, cannot dominate future questions.
- Preserve broad life-story coverage as the primary mission.
- Keep `ask.py` fallback behavior stable if planner state is missing or invalid.

## 6. Add AI Classification And Synthesis For Ingested Sources

Use AI to classify ingested stories and suggest links, wiki updates, and candidate questions.

Acceptance criteria:
- AI classification identifies people, places, periods, projects, themes, and possible new spotlights.
- Classification output is stored as metadata, not silently trusted.
- Suggested wiki changes cite source files.
- Suggested questions go to the candidate store first.
- No external ingested corpus should bypass owner-only privacy defaults.

## 7. Prepare Future Privacy And Access Tiers Without Building Them Yet

Keep the first product simple and owner-only, but avoid painting the architecture into a corner.

Acceptance criteria:
- Preserve `visibility`, `sensitivity`, and source metadata on wiki/source records.
- Document that all current content is owner-only.
- Do not implement granular sharing/access tiers in this phase.
- Ensure future public/shared output generation can be built from reviewed outputs, not raw private wiki exposure.

## 8. Generate Deep Research-Style Question Neighborhoods

Create a way for Lifehug to generate new neighborhoods of questions from a story, theme, person, period, project, or wiki page.

Acceptance criteria:
- Add a research-style question expansion mode that starts from a target page or source.
- Generate clustered question neighborhoods, not just one-off follow-ups.
- Support different neighborhood types such as foundation, chronology, sensory detail, relationships, conflict, meaning, contradiction, and output-oriented questions.
- Store generated questions as candidates first, with source citations and reasons.
- Ensure deep neighborhoods do not dominate the daily queue unless explicitly selected as an active objective.

## 9. Recommend New Spotlights From Stories And Wiki Development

Use accumulated stories and wiki changes to recommend new spotlights worth developing.

Acceptance criteria:
- Analyze answers, ingested sources, candidate questions, and wiki pages for recurring people, places, periods, projects, objects, or themes.
- Recommend spotlight candidates with evidence, source links, and a short reason.
- Distinguish between strong recommendations and weak signals.
- Do not automatically create spotlights without user approval.
- Feed approved spotlight recommendations into the question candidate system and planner.

## 10. Make Lifehug Script-First And Skill-Driven

Adopt the EKB-style operating model: scripts are the source of truth, skills are operator wrappers, and cron/manual/agent workflows all run the same commands.

Acceptance criteria:
- Treat `system/` scripts as canonical behavior for compile, ingest, answer processing, planning, and wiki serving.
- Update `skill/SKILL.md` so Codex/Claude can run Lifehug workflows manually and safely.
- Document workflows for `lifehug compile`, `lifehug ingest story`, `lifehug planner report`, `lifehug serve wiki`, `lifehug process answer`, and `lifehug recommend spotlights`.
- Ensure every workflow can run locally on any cloned/downloaded machine without requiring hosted infrastructure.
- Ensure cron jobs use the same scripts as manual and AI-agent workflows.
- Keep local-first wiki viewing as the default deployment model.
