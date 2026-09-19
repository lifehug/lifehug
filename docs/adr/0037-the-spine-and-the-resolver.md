# ADR 0037: The spine and the resolver — how the timeline places itself

Date: 2026-09-19
Status: accepted (owner ruling, 2026-09-18/19)
Extends: ADR 0024 (chronology with basis), ADR 0026 (cross-dating),
ADR 0028 (the landmark recorder), ADR 0031 (event identity)
Shipped: v314 (`system/resolver.py`, lifehug#362); v315 amends the shape rule;
v316 adds the two legs for hosts

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

## Amendment (v316): two legs, so a host can run the same loop

Decision 5 said where the resolver runs, and both seats assumed one process
holding a key. A hosted vault has neither: the platform runs this package
keyless through an extraction seam, buys the completion itself, and may
deliver the same answer twice. So the same work is expressed as two pure legs
with the vault in between, and the local run becomes those legs composed.

6. **A plan is read-only.** `resolver.plan_items` (`resolve --plan --out
   <path>`) answers *which moments are still unplaced, and what exactly would
   be asked about them*: one item per story, each with the full prompt and an
   identity stamp — the story's bytes (`source_sha256`), the spine
   (`spine_digest`) and the moments with the raw handles they would retire
   (`targets_digest`). It touches nothing under the vault: no ledger, no
   filing, no publish, no response cache, and an `--out` inside the vault root
   is refused rather than written. The ordering is the story the person just
   told (`--source`) first, then the longest-waiting, then the never-seen, so
   a host that plans one item at a time and loops converges on the whole
   vault. `complete` says when that loop is done. Bare age handles are never
   planned — they are counted and answered by arithmetic.
7. **An envelope is filed against the vault as it is now.** `file_envelope`
   (`resolve --from-response <envelope.json>`) re-retrieves the passages a
   citation is checked against rather than trusting any that travelled with
   the answer, so a host stores no evidence and can send none that is stale.
   An item whose story changed under the plan is refused (`stale_source`); one
   whose moments are no longer the moments it was planned for is refused
   (`stale_targets`), which is also what makes filing the same envelope twice
   file nothing the second time — the property a host's replay relies on. A
   moved spine is recorded as `spine_changed` on the ledger entry and is not a
   refusal: the citations are verified against the current text either way.
8. **Twice, then stop asking.** A ledger entry counts its `attempts`. The
   second round — the moments a model came back silent about, re-asked in
   chunks of four — used to be a loop inside one call; it is now a re-entrant
   consequence of the ledger, so a host gets it from planning again. A moment
   that returns nothing twice is not bought a third time without
   `--retry-failed`.
9. **The card asks the resolver's question.** When the ledger holds a
   `question` for a node, `temporal_publication.publish` puts it on that
   node's work item as `prompt_intent`, with `question_source: "resolver"`,
   instead of the generic sentence composed from a label. The ledger is read,
   never folded: it is the resolver's memory of what it asked, not a claim
   about the person's life, so `CALCULATION_RULE_VERSION` does not move for a
   better sentence.

`resolve --execute` and `classification_refresh.run_batch` are unchanged in
behaviour: they are leg A → the completer → leg C, composed in memory with the
same response cache. No prompt text change, no rule-version change, no schema
change.

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
  hosted classify path gained the placement, tenure and owner-name fixes but
  the hosted worker still could not call the resolver, which needs a
  model-router purpose and a filing mutation of its own. v316's two legs are
  the package's half of that: the platform's `resolve` purpose plans with leg
  A, buys the completion, and files with leg C as the classify successor.
- Complexity budget: the intended shape is *spine + model + verification +
  ledger*. New placement rules should improve the spine or the verifier, not
  add joins in front of the model.
