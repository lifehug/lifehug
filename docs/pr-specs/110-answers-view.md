# Contract: the Answers view (issue #110)

Parity twin of lifehug-platform#368, owner-directed 2026-08-10. The local
medium's ledger of everything answered — question, date, size, and the door
to act on each.

## Deliverables

1. `view_answers()` in `system/serve_wiki.py`, registered as
   `("answers", "Answers", view_answers)` in `VIEWS`, claimed by the
   **System** group in `VIEW_GROUPS` next to `sources` (the neighborhood
   decision matches the hosted dropdown: what you gave / what it was
   compiled from / machinery).
2. The view lists every `answers/*.md`, newest first by `answered_date`
   frontmatter (files without it sort last, dated "unknown"): question
   text (`question_text`, falling back to `title`), `category_name`
   (falling back to `category`), the date, and an approximate word count
   of the body (frontmatter excluded).
3. Each row links to the existing act-on-source surface:
   `/source-actions?ref=answers/<filename>` — reflect / correct / retract
   is this medium's "act on it"; filing is synchronous here so there is no
   in-flight/parked status column by design (say so in the view's own
   header line so the twin's absence is explained, one quiet sentence).
4. A summary line at the top: N answers · first date → last date.
5. Empty state: calm, one sentence, no guilt.
6. Walkthrough: `tests/walkthrough_answers.py` runnable via
   `make walkthrough-answers` (the pattern rule exists) — boots the viewer
   against a synthetic vault fixture (NEVER ~/Workspace/dave), asserts the
   menu shows Answers under System, the rows render question text + date +
   word count newest-first, a row's action link targets
   /source-actions?ref=..., and the empty state renders when no answers
   exist. Screenshots via walkthrough_lib's conventions.
7. `system/version.json`: bump version (user-visible view → normal bump),
   and confirm `framework_files` needs no change (serve_wiki.py is already
   manifest-owned).

## Non-goals

No capture/status pipeline (hosted-only concept), no new frontmatter, no
changes to source-actions itself.

## Gates

Repo test suite for touched areas (`python3 -m pytest tests/ -k
"serve or wiki or answers" -q` or the repo's normal scoped invocation),
the new walkthrough green, and no references to ~/Workspace/dave anywhere
in test code (hard boundary).
