# ADR 0037: The spine and the resolver — how the timeline places itself

Date: 2026-09-19
Status: accepted (owner ruling, 2026-09-18/19)
Extends: ADR 0024 (chronology with basis), ADR 0026 (cross-dating),
ADR 0028 (the landmark recorder), ADR 0031 (event identity)
Shipped: v314 (`system/resolver.py`, lifehug#362); v315 amends the shape rule

## Context

By v311 a date reached a moment through joins: the classifier's own claim, an
explicit `timeline-place`, cross-dating, and a candidate list the classifier
context built by keyword rules and validated behind a closed vocabulary of
failure codes. Every join that failed became a question for the owner. On the
owner's own vault that produced cards like *"the founding of the company —
could be 1981–2031"* and *"When was 18?"* while the vault plainly held the
founding month and the birthday.

The owner's reading of that page settled the design:

> If you can answer this from the repo, so should the system. Once a question
> is answered it is sorted and never asked again. When I add new information
> the model should look at it and do the same thing. I don't care about
> gates — the design should just work.

And, once it worked: *the loop is a model resolving and calculating placement
against a spine. The spine is built off a lifetime timeline, generic at first;
the user adds keystones and landmarks to improve it.*

## Decision

1. **The spine is the frame.** `resolver.spine` gathers, from the published
   projection, the dated facts every question is read against: birth and the
   age table it implies (`resolver.age_table`, every age → a date range, for
   any birthday, leap days included), stays, tenures and schooling as
   intervals, dated points (births, deaths, weddings, graduations, foundings),
   and the people around the owner. It is generic first — any lifetime has
   this shape and a birthday alone fills the age table — and the person's
   landmarks and keystone answers make it specific. Nothing in it is invented.
2. **The model answers; the machine verifies.** One story at a time, the model
   sees the story, the spine, the passages a full-text index (SQLite FTS5 over
   every source, answer, landmark and fact, rebuilt per run) returns for that
   story's events, and the events still without a date. It answers each with a
   date or range, a basis (`stated` / `derived` / `inferred`), a confidence,
   citations, and — only when the vault cannot tell — the one question that
   would settle it. Verification is mechanical and total: cited quotes must
   occur in the cited passage, dates must parse, ranges must be ordered, a
   derived answer must cite the spine fact it came from. Bare age handles
   never reach the model; the age table answers them deterministically.
3. **A resolution is a claim.** A verified answer is filed as a `date` claim
   on the moment's existing node under extractor `resolver/rule:3`, declared
   on the same telling as the classifier's reading, with the citations as
   evidence; the raw handle it replaces is superseded by a correction. The
   fold, the projection, the page and every later correction treat it like
   any other claim. Basis maps `stated → stated`, `derived → age`,
   `inferred → anchor`; confidence never exceeds `inferred`.
4. **Ask once.** `state/resolver/resolutions.json` records every outcome —
   resolved, unverified, unknown with its proposed question — and raw model
   responses are cached under `state/resolver/responses/`. A settled moment is
   never re-asked; a refused or unknown one is never re-bought automatically.
   New information (a correction, a landmark, a story) re-opens a question; a
   clock never does.
5. **Where it runs.** After every accepted batch in
   `classification_refresh.run_batch` (`LIFEHUG_RESOLVER=0` skips it), and by
   hand as `lifehug resolve --execute`; `--eval` answers known-answer
   questions without filing. The resolver never dates a residence episode —
   two stays that look alike are an identity problem for the roster, not a
   dating problem.

## Consequences

- The classifier's validator is no longer the place where placement is won or
  lost. v313 made per-event salvage available so one bad relation does not
  refuse a whole batch; v315 made that the local loop's explicit choice
  (`file_batch_response(salvage=True)` from `run_batch` only), because a host
  that files envelopes without a resolver still needs the refusal its own
  repair loop re-asks the model about.
- Shape follows the role, never the precision (v315): only weddings, births,
  deaths and graduations are points; a founding dated to the day still has a
  week inside it, so `within` it is a legitimate relation.
- On the owner's vault the first full run moved placed moments from 503 to
  1,164 and open work items from 859 to 70; the remaining questions are the
  ones only the owner can answer.
- The hosted platform adopts the framework by pin. At the v314/v315 pin the
  hosted classify path gains the placement, tenure and owner-name fixes; the
  hosted worker does not yet call the resolver, which needs a model-router
  purpose and a filing mutation of its own (catalogued `defer`).
- Complexity budget: the intended shape is *spine + model + verification +
  ledger*. New placement rules should improve the spine or the verifier, not
  add joins in front of the model.
