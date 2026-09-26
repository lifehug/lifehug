# ADR 0037: The spine and the resolver — how the timeline places itself

Date: 2026-09-19
Status: accepted (owner ruling, 2026-09-18/19)
Extends: ADR 0024 (chronology with basis), ADR 0026 (cross-dating),
ADR 0028 (the landmark recorder), ADR 0031 (event identity)
Shipped: v314 (`system/resolver.py`, lifehug#362); v315 amends the shape rule;
v316 adds the two legs for hosts; v317 adds the not-a-landmark and
not-an-event rules (lifehug#365); v325 revisits, aims and estimates; v326
salvages a failed resolution and the CLI path; v339 (amended v341) makes the
`birth` landmark the owner's own; v346 makes a dated birthday a birth and
measures every age from its own subject's birth; v347 narrows an introduction to
one person in one clause; v349 stops a stated entry being retired by shape and
adds `landmark-reinstate`; v350 fixes the couple key, the identity re-key's
alias and the card that showed a node id; v352 makes an answer to a card place
the moment that card is about; v354 stops that answer's receipt retiring the
listener's reading of the same message.

Every amendment below carries the version that shipped it in its own heading.
The CLI verb is `resolve`; `resolver` is the module (`system/resolver.py`) and
the concept.

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
   hand as `lifehug.py resolve --execute`. The resolver never dates a residence
   episode — two stays that look alike are an identity problem for the roster,
   not a dating problem. Three operator flags live on the module's own
   entrypoint and are deliberately not forwarded by the `lifehug.py` wrapper:
   `python3 system/resolver.py --vault-root <root> --eval <file>` answers
   known-answer questions without filing, and `--estimate-missing` and
   `--bind-restatements` are the two one-time backfills named below.

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

## Amendment (v317): what is not a landmark, and what is not an event

Decisions 1 and 2 say the spine is filled by landmarks and read by a model.
Neither said what happens to a record that cannot fill it, or to a "moment"
that never happened — and on the owner's own vault at v316 both drew cards
(lifehug#365). The spine's own definition answers both.

10. **A record that cannot improve the spine draws nothing.** A landmark
    record has one job. A `none` terminal ("I never served") and a skip are
    complete answers ABOUT the ladder, not stretches of a life; a `work` or
    `schools` record with no organization named is not a tenure, because a
    tenure is a tenure *at* someone. All three still FILE — they are what the
    person said, and the domain goes on reading complete — and none of them
    becomes an episode node, a stay slot or a work item.
    `landmark_projection.not_a_landmark` is the one definition, read twice:
    the recorder refuses an unnamed organization at filing with a typed
    finding, and the fold skips all three at draw time, so a vault that
    already holds one heals on its next redraw with no migration. A residence
    stub that duplicates a dated stay is deliberately NOT here: two stays that
    look alike are an identity problem, and attaching the stub to the stay it
    repeats is a different fix.
11. **An anchor that asks nothing and places nothing is not a question.** A
    `missing_anchor` whose sentence was withheld, or one with no node of its
    own that would place no moment, is dropped before publication
    (`temporal_work_items.dangling_anchor_reason`). The birth origin is
    exempt by O-E6: the birthday is the coordinate system, so it is asked
    whatever its reach. This is work-item composition, not placement, so
    `CALCULATION_RULE_VERSION` does not move.
12. **Not every moment is an event, and the resolver may say so.** Beside a
    date, a range and a question, an answer may carry
    `{"not_an_event": {"kind": "future" | "meta" | "fact_statement" |
    "duplicate", "reason": "..."}}` — an anticipated or hypothetical
    milestone, a conversation about the data itself, a bare fact rather than
    something that happened, or a restatement of a moment already dated
    (whose id the reason cites). The set is closed and verification is the
    usual mechanical kind: accepted only when the answer is null and the kind
    is in the set. A verdict is filed as a dated RETRACTION of the node's own
    occurrence, relation and date claims through the ordinary correction path
    (`temporal_store.retract_claims`, scope `resolver_not_an_event`) — never a
    delete, and never the entry's identity claim, which is the person's own
    answer. The ledger records `status: "not_an_event"` with the kind and the
    reason, the node leaves the projection on the republish that already
    follows filing, and the moment is as settled as a dated one: `--plan`
    never re-plans it, `--refile` skips it, and it is not an open question.
    Both legs reach this through the same absorb, so a host gets it for free.

## Amendment (v325, 2026-09-22): the resolver revisits, aims, and estimates

**What happened.** On 2026-09-21 the owner answered "When was grandpa's
death?" on staging with the exact dates of both grandfathers' deaths. Four of
his six turns parked on the hosted lease (a platform defect, fixed there), but
the two that filed exposed three gaps in THIS design, none of which a
re-press would have closed:

1. The hosted resolver plans the story just filed and nothing else, and an
   `unknown` in `state/resolver/resolutions.json` was terminal (the retry set
   was `unverified` / `no_answer_returned` / `file_error`). A fact that
   answered an OLD question helped only if it happened to become a new dated
   event — which it did, as "Both grandfathers die within a month", leaving
   the existing "Grandpa James Edwin Taylor Sr.'s death" node undated and the
   Orderville dream home unplaced beside it.
2. An anchor handle ("grandpa's death") binds to a node only on an exact key
   match of words (`_anchor_index`, the uniqueness gate is right and stays).
   Nothing let the answer SAY which node the handle named.
3. The resolver never guesses, by design — a range needs a citation that
   entails it — so the page had nothing to draw for the 35 open questions
   but the whole life.

**Decision.** Three additions to the pass the resolver already runs; no new
module, no new model call, no stored dependency graph.

* **Revisits.** A newly filed story re-opens the settled unknowns it bears
  on, computed on the fly from what the vault holds: the moment the promoted
  message's own conversation was answering (`session_ref` →
  `cand:work_item:` → its node, or every moment whose unresolved handle IS
  that `anchor:` item), and every unknown whose own retrieval query now
  returns a passage of the new story. Once per story (`revisited_by`), at
  most `MAX_REVISITS` by retrieval per plan, the new story's passages first
  in the re-opened moment's prompt, and the re-opened stories ordered right
  after the one just told. The plan item carries `include_paths`, `trigger`
  and `revisits` (additive, empty for a v316-shaped item) so leg C verifies
  against the passages that were planned without a second argument.
* **Aim.** The story's own prompt lists the open questions it may bear on.
  An answer may return `handle_binds`: "this moment's unresolved handle
  names THAT node". Verified mechanically (the handle is the target's own,
  the node exists, and is not the target), it files a `relative_order`
  claim whose anchor is the node id — `_anchor_index` seeds every node id as
  its own key, so the edge resolves without a word match — and retires the
  raw handle with a supersession correction. The fold places the moment
  through an ordinary edge; the `missing_anchor` card leaves because nothing
  is missing. Durable, cited on the story that answered it, correctable like
  a date.
* **Estimates.** Whenever `answer` is null and there is no `not_an_event`,
  the answer carries an `estimate`: a bounded stretch with the lines it
  rests on (`residence` · `tenure` · `life_stage` · `related_moment` ·
  `story` · `spine` · `other`). Verified mechanically — parseable, ordered,
  closed at both ends, never wholly before the birth (that is family
  history) — kept in the ledger beside the question, and published on the
  node and its work item as `probable_window` by `temporal_publication`,
  under the same "read, never folded" rule as the question itself. It is
  NEVER a claim: the score, the strip and the derivation do not read it,
  `calculation_rule_version` does not move, and only the person's answer
  moves the dot to the line. The page floats the dot over its window and
  draws its height as the window's width.

  **v333 amendment (owner ruling 2, 2026-09-23).** Two things follow from
  "never a placement". An estimate is not drawn on a node that IS placed —
  once the substrate can place the moment for real, a window beside a stated
  interval is two answers to one question, and the ledger row simply stops
  being drawn rather than being rewritten. And the window, once known, is
  enough to decide whether the card it rides on is worth drawing:
  `temporal_publication._without_stakeless_date_cards` applies
  `temporal_work_items.date_card_changes_something` — the ruling's own
  predicate — and retires a date card on a freestanding anecdote whose window
  is already inside about a year with nothing waiting on it. That is a
  display decision at the same seam and under the same rule; the ledger is
  still read, never folded, and `calculation_rule_version` does not move.
* **Refine, and the backfill.** A moment the resolver itself dated to a
  WIDE range (`REFINE_MIN_YEARS` or more) stays reachable: a new story that
  bears on it re-asks it once, and only a narrower verified answer replaces
  the standing one — a refine can never downgrade a placed moment to a
  question (`kept_resolved`). The person's own stated dates are never
  re-asked. `python3 system/resolver.py --vault-root <root>
  --estimate-missing` asks every settled unknown that has no estimate yet for
  one, once — the one-time backfill that gives the page its first windows. It
  is on the module's entrypoint, not on `lifehug.py resolve`.

**What this deliberately is not.** Not an incremental recompute (the fold
recomputes everything in seconds and is correct because it starts over), not
a stored graph of affected items (three signals computed per filing cannot
go stale), and not person-anchored event identity (the three grandfather
nodes are three tellings of two deaths; merging them by person is its own
version).

## Amendment (v326, 2026-09-22): a resolution is bookkeeping, and the CLI salvages too

**What happened.** The same evening the owner pasted two FamilySearch cards
(Name / Birth / Death / Burial lines about each grandfather) and one bare
correction ("That was my grandma and Grandpa Jim, not me — I just visited")
into a Timeline conversation. All three promoted messages were refused by
`classify-story --classify`, three times out of three, with
`failure=ClassifierContextError status=context_resolution_invalid`: no event
and no claim was filed, and the exact death dates the owner had just supplied
reached the vault only where v325's revisit happened to re-open a question
that named the man. The code is raised when
`timeline_evidence.normalize_resolution` rejects an event's
`timeline_resolution` — the model's ACCOUNT of its link decision — for
contradicting the coverage the validator computed (`incomplete` for a
complete context, which is what a model says when the vault does not know
Apple Valley), for echoing a `candidate_ids` list that is not the validator's
own recomputed event-local set, for a reason past its length or a stray key.
Two gaps let that refuse a whole reading: the v323 salvage was never asked
for on the single-source CLI path (`classify_file` called
`prepare_classification` without `salvage`), and a resolution failure was not
in the salvageable set on any path.

**Decision.**

13. **A resolution that fails its own contract is salvaged like a bad
    relation.** Under salvage the validator rebuilds the account from what it
    verified itself (`classifier_context._salvaged_resolution`): a relation
    that already passed `_validate_relation` is kept and reported `linked`; a
    model's own non-link status stands when it agrees with coverage; and the
    coverage rule decides when it does not (`incomplete` for a truncated
    context, `missing_evidence` for a complete one). The event, its `subject`,
    its stated date and its `places` are filed exactly as the source wrote
    them — an unresolved place stays text, and nothing here resolves a place
    or invents a candidate. The downgrade is recorded on the classification
    (`validation_downgrades`, field `timeline_resolution`, the
    `timeline_evidence` code) and named on the CLI summary (`kept : N
    event(s) filed without the model's link or proof`), so a dropped link is
    something the person can read rather than a reading that vanished.
14. **Every filing path salvages.** `classify_file` — `classify-story
    --classify` and `--from-response` — now takes the v323 default
    (`salvage=True`); `salvage=False` keeps the strict verdict for a caller
    that asks. Structural failures (not a mapping, a stale snapshot, events
    not a list, a tampered event key) refuse either way, before any write.
15. **The prompt names the two shapes that tripped it,** without moving
    `PROMPT_VERSION` (a wording repair, as the diagnostics spec ruled): an
    unfamiliar place is still the event's place and never makes a complete
    context `incomplete`; a pasted record about a named person is one event
    per dated line with that person as `subject`; a message that only
    corrects whose an already-told moment was narrates no new moment and
    leaves `events` empty. If the model does read a moment out of such a
    correction, the words carry the subject (`timeline-rules:9` reads "my
    grandma" as somebody else) and the reading files as theirs; a durable
    re-scope of the EARLIER story's node from a later correction message is a
    separate, not-yet-built seam.

**Considered and deferred.** Routing a vital-record-shaped paste to the
people/landmark recorder so `born`/`died` land on the roster person directly
would give the record a home beside the person rather than a `moment` node
with an other-person subject. It is the better destination for a record, but
it is a router in front of the model — the shape this ADR's complexity budget
says to avoid — and the general fix above already files the dates; it stays
a possible refinement.

## Amendment (v339, 2026-09-23): the `birth` landmark is the owner's own birth

**What happened.** The v326 amendment above closes with a deferral: *routing a
vital-record-shaped paste to the people/landmark recorder so `born`/`died` land
on the roster person directly*. Two days later something routed one there
anyway. The same two FamilySearch cards — James Edwin Taylor Sr, born
17 October 1930, and Darvin Burrows Beauchamp, born 30 September 1929 — reached
a landmark-record filing (`maintenance:reflect:…:landmark-record`, owner's vault
`fd04e792` and `b6982658`) and were filed as **`birth`** landmark records.

`birth` is the one domain with no identity rung: `questions.yaml` declares
`birth.identity_kind:` empty and `birth.collection: singleton`, because a birth
landmark is the owner's own birthday and there is nobody else in it. So both
records keyed on the same empty `entry_key` as the owner's own stated
1981-07-11 and folded into ONE entry. `merge_landmark_entry`'s `{**prior,
**incoming}` let the later record's raw grains overwrite his, so the drawing
read `30 September 1929` beside a `date` of `1981-07-11`; `_attach_dates`
reconciled all three claims onto his entry, so both grandfathers' births became
his own `date_alternates`; and because `entry_subject_mention` mints
`OWNER_BIRTH_MENTION` for this domain *unconditionally*, the fold filed three
`self` birth claims and asked him *"Two dates are claimed for your birth — 11
July 1981 and 30 September 1929. Which is right?"*.

**Decision.** Item 10's rule gains a fourth reason, and it is a statement about
a domain rather than about a record's completeness:

16. **A `birth` landmark record is the owner's own birth.** A record that names
    somebody who is not the owner, or that carries a year at least fifteen from
    the year the owner STATED, is a relative's birth: it belongs to `family`,
    which has a `who` rung for exactly this, and it never touches the owner's
    entry. `landmark_projection.birth_landmark_not_owner` is the one
    definition, returning `birth_landmark_not_owner`
    (`NOT_A_LANDMARK_REASONS`), and it is read at the same two seats item 10
    already uses: REFUSED AT FILING by `timeline.save_landmark`, which routes a
    NAMED relative's birth to `family` and raises the typed
    `BirthLandmarkNotOwner` for an unnamed one — a refusal the host can read is
    a question the host can ask (*"whose birth is that?"*), and a silent merge
    is the one outcome the rule exists to make impossible — and SKIPPED AT DRAW
    by `project_landmark_entries`, before the group exists, so a vault that
    already holds the records heals on its next redraw. Un-drawing a record is
    not retracting it: the claims stay in the substrate and are superseded by a
    correction, which is the only thing that can make a standing claim stop
    standing.

    **Amended v341.** "Names somebody who is not the owner" excludes the
    domain's OWN vocabulary. A `birth` record whose subject field holds `Born`,
    `birthday`, `date of birth`, `my birth` or `I was born` names NOBODY — it
    says which domain this is, not whose birth it is — and the hosts file the
    owner's own birthday under exactly that display label, so v339 refused the
    owner's own birth landmark and the draw seat dropped it without a word.
    `landmark_projection.BIRTH_DOMAIN_WORDS` (with `is_birth_domain_word`) is
    the one definition, compared WHOLE and casefolded rather than as a
    substring so a real name containing one of the words still refuses, and it
    is read by both seats that ask the question — this item's
    `third_party_birth_subject` and the projection's own age-anchor test,
    `temporal_timeline._birth_names_only_the_owner`, which held a second
    single-word list until v341.

    The year bound needs a stated birth to measure against
    (`owner_stated_birth` — the first `basis: "stated"` birth claim in filing
    order), so a vault whose owner has not said when he was born still records
    a birth on a name alone. Fifteen years is under the shortest plausible
    generation gap and far over any correction a person makes to their own
    birthday; the real records were 52 and 51 years out.

17. **A weaker-basis claim never respells the winner's date grains.** For every
    domain, not just this one: `year`/`month`/`day` are the entry's date in the
    ladder's own words, so a claim that lost the reconciliation *on basis*
    (`chronology.BASIS_WEIGHT` — stated 6.0 over anchor 4.0) does not get to
    rewrite them (`landmarks_interaction._keep_grains_of_the_better_supported_claim`).
    Two claims of EQUAL basis merge exactly as they did before, so "actually I
    was born on the 12th" still moves the grain, and v222's rule is untouched —
    the losing claim is still kept as an alternate to be asked about.

**Considered and not built.** Making the FOLD ignore a `self` birth claim that
already stands would have healed an affected vault without a correction, and it
is the wrong direction: a standing claim is retracted by a correction, not by a
reader. An affected vault therefore needs `temporal_store.supersede_claims`
beside the redraw, which is what the owner's vault got.

## Amendment (v346, 2026-09-24): a birthday is a birth, and an age is measured from its own subject's birth

*Authored on a branch numbered 344 and referred to as "v344" in the text below
and in `temporal_timeline`'s own notes. v344 and v345 were taken by other
releases while it was open, so it shipped as **v346** on `timeline-rules:15`.*

**What happened.** The two amendments above are both about which birth is the
OWNER'S. The owner's review of staging on 2026-09-24 was about the other
direction: whose birth a birth is when it is not his, and what a vault owes a
person whose birthday it has been told.

He had filed his mother's birthday as a manual source on 2026-09-14 —
*"Desiree Taylor (Dave's mom, also called Desi) — birthday June 19, 1955."* —
and the classifier read it exactly right (`claim:da4f59afb2d774e0b9ebef87`, a
`date` claim, 1955-06-19 certain/stated, `event_mention: "Desiree Taylor's
birthday"`). Three things went wrong on the node it drew. Its `event_kind` was
`moment`, because a claim extractor can say WHEN and cannot say what KIND of
event a birthday is, so `temporal_timeline`'s births — read off birth-kinded
nodes — never saw it. Its subject resolved to nobody, because the person roster
held a collective `parents` row and no mother. And it published
`axis_membership: owner / lived`, twenty-six years before his own birth, because
`_owner_relevance`'s zero-candidate fallback reads a name the roster cannot
place as the ordinary shape of the owner's own life.

The cards were the consequence: *"When did Mom married dad at 21 happen?"*
stayed `age_without_birth_anchor` with her birthday in the same vault, and
*"Two dates are claimed for your birth — 11 October 2021 and 2020"* was asked
about his SON's birthday, because the eleven tellings of Harvey's birth that the
binder's `R2b` folded into one node resolved to the owner: two of them carry
`subject_mention: "self"` because he is the subject of the TURNING POINT and the
birth is only what turned it.

**Decision.** Items 16 and 17 gain three siblings, each one definition.

18. **A dated birthday of a named person is that person's birth.** A `date`
    claim whose event mention is `<Name>'s birthday|birth date|birth|born`, at
    day, month or year grain, with a named non-owner subject, IS that person's
    `birth`. `landmark_projection.BIRTH_EVENT_NOUNS` and `birth_event_subject`
    are the one definition — a SUBSET of item 16's `BIRTH_DOMAIN_WORDS`, asked
    forwards ("whose birth does this name?") where item 16 asks it backwards
    ("does this name nobody?"), compared whole and never as a substring, so
    v341's *"Mary Born"* and *"Bornstein"* still name people and not events. It
    is applied as a READING at FOLD time (`temporal_timeline
    .A_DATED_BIRTHDAY_IS_A_BIRTH`, `reads_as_a_birth`/`_read_event_kind`), never
    written back onto the receipt, so a vault that already holds the claim heals
    on its next redraw and the extractor's own words are untouched — the same
    posture item 16's draw seat already takes. The owner's own birth is excluded
    by construction: an owner `subject_ref`, an owner-only mention and a bare
    birth domain word all refuse, so items 16 and 17 keep governing it alone.

19. **A person a source introduces EXISTS.** A named subject the roster has
    never heard of, introduced in its own source by a relationship phrase the
    owner used — *"Dave's mom"*, *"my mother"*, *"(wife)"*, *"(brother)"* — gets
    a roster row carrying that `relationship`
    (`roster_relations.A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON`). The
    possessive must be the OWNER's, because *"Katie's mom"* is not his mother;
    the relationship is derived from `identity_resolution
    .RELATIONSHIP_MENTION_WORDS` crossed with `focus_candidate
    .FOCUS_RELATIONSHIPS`, so mother and father land in the `parent` tier of
    `axis_membership`'s immediate-family set and an in-law lands in `other`; and
    an alias more than one introduced person claims is dropped from every row
    before anything is written, which is the shared-alias rule stated over the
    whole batch rather than decided by file order. The write is
    `entity_roster.ensure_introduced_relatives` through
    `entity_verdict.apply_verdict(..., ensure=True)` — the `source:
    "landmark:family"` door — reached by `entity-roster --ensure-introduced`:
    deterministic, additive, idempotent, no AI, and never a hand-edit.

20. **Anyone's age is measured from their own birth.** `_births_by_subject`
    reads `BIRTH_ANCHOR_TIERS` in order — a birth-kinded node whose resolved
    subject is that person, else the roster row's `born`, else a
    `family`/`children` landmark entry's own date, those two being the domains
    whose ladder declares `date_semantics: ["birth"]` — and the first tier that
    answers for a person answers for every key that person goes by, so a lower
    tier can add a birth nobody has drawn and can never contradict one already
    on the page. A key several roster people bear is never one of those keys.
    `_record_for_age_claim` and `chronology.from_age_band` stay
    subject-agnostic; the only thing that changed is which birth a group is
    handed, so `age_without_birth_anchor` now means what it says.

    Two corollaries. A birth group naming exactly one non-owner person is that
    person's birth whatever else it mentions
    (`A_BIRTH_BELONGS_TO_THE_PERSON_BORN`, which is item 16's rule read
    forwards): the owner's `self` mentions on such a group are the turning point
    he lived, and two named people on one birth group decide nothing and are
    left to v340's `owner_birth_anchor_ambiguous`. And a node wholly before the
    owner's birth is `pre_birth` whoever it turns out to be about — rule 4 of
    the axis ruling moved above the evidence relations — with v334's exception
    kept exactly: an occurrence whose subject IS the owner stays `owner`/`lived`
    before his birth, because that is a contradiction Mirror owns and hiding it
    off the axis would delete the question.

**Considered and not built.** Rewriting the classifier to emit `event_kind:
"birth"` for a birthday would fix new vaults and heal none, which is why this is
a reading and not an extractor change. And a roster row created by item 19 can
re-key a node whose subject newly resolves and whose claims carry no
`event_ref`, because a node id is derived from its subject; v342's
`node_aliases` covers a BINDER re-key and not an identity one, and closing that
is the binder's seam rather than the fold's.

## Amendment (v347, 2026-09-24): an introduction names one person in one clause

**What happened.** Item 19 shipped and was run against the owner's vault the
same day. `entity-roster --ensure-introduced --dry-run` proposed four people,
and one of them was his paternal GRANDFATHER filed as a second father:

```
desiree-taylor:         Desiree Taylor — parent (from "mom", born 1955-06-19)
james-edwin-taylor-sr:  James Edwin Taylor Sr. — parent (from "dad")
james-taylor:           James Taylor — parent (from "dad")
katie-taylor:           Katie Taylor — spouse (from "wife", born 1987-05-15)
```

The resolver had filed one claim whose evidence quote reads *"story: my grandpa
James Edwin Taylor Sr., my dad's dad, died of a heart attack"*. Item 19's
appositive shape — `<Name>, <possessive> <word>` — matched the name against the
"dad" of *my dad's* dad: a relationship word that POSSESSES the next noun,
read as though it were the name's own relation. The clause says the opposite of
what was read out of it, twice over: *grandpa* is the word actually in
apposition with the name, and *dad's* is a possessor.

Then item 19's own shared-alias rule made the damage worse in exactly the way
it was designed to prevent a different damage. Two people now claimed "dad", so
dad / my dad / father / my father were dropped from BOTH rows — and the owner's
real father, James Edwin Taylor, d. 2019, whose own introduction is *"the
biggest loss of my life so far is my dad, James Edwin Taylor"*, ended up with no
relationship words at all. Measured on a scratch clone of the owner's vault:
fourteen nodes whose subject mention is "dad", "Dad", "father" or "Father" went
on naming nobody, eleven of them drawn as the owner's own life rather than as his
family's, and *"Dad wins pet snake at fair"* had no birth to measure its age
from although his father's birthday was in the same vault.

The vault had already said who Sr was, twice, and neither statement was asked.
The correction `correction:temporal-4eb9abe8c4ca47089ae83a56` says *"these are
the owner's grandfathers' births, not his: … James Edwin Taylor Sr (born
1930-10-17) and Darvin Burrows Beauchamp (born 1929-09-30)"*. And the man's own
name carries the answer in its last token.

**Decision.** Item 19 gains three restrictions and one addition. It is narrowed,
never widened: every shape it read before it still reads, and the rule now
refuses three ways of looking like an introduction without being one.

21. **An introduction names one person in one clause**
    (`roster_relations.AN_INTRODUCTION_NAMES_ONE_PERSON_IN_ONE_CLAUSE`). The
    relationship phrase and the name it introduces must sit in the SAME clause
    (`introduction_clauses` — newline, `|`, `;`, `:`, a dash, and a sentence end
    that is not an abbreviation's full stop, so `Sr.` and `A.J.` are not two
    clauses). Inside that clause a relationship word carrying a possessive `'s`
    is a POSSESSOR and not the name's relation, so *"my dad's dad"* introduces
    nobody as a father; a clause that gives one name two different
    relationships states neither, and the next clause is read instead; and the
    in-law reading (`axis_membership.IN_LAW_RE`) is taken over that clause
    rather than over every text in the source. A name that a pasted vital
    record merely LISTS — the genealogy-app shape `Name • N Sources` / `Birth •
    …`, read through `landmark_projection.BIRTH_NAME_LINE_RE`, which is already
    the one definition of it — is introduced by nothing: a relationship word in
    the surrounding conversation may not reach into somebody else's document.

22. **A relation the vault records outranks one a phrase would file**
    (`A_RECORDED_RELATION_OUTRANKS_AN_INTRODUCED_ONE`). Before writing,
    `recorded_relation` asks `RECORDED_RELATION_TIERS` in order — a temporal
    correction's own words, a `family` landmark entry's `relation`, a roster
    row's `relationship` — what the vault already says about that spelling. A
    recorded relation that AGREES confirms the row; one that CONTRADICTS it
    refuses the whole row and returns a finding naming both, because a vault
    that has already placed somebody is not corrected by a sentence that reads
    them differently. The correction tier counts a text only when it names the
    person and states EXACTLY ONE relationship, and only when the texts that
    qualify agree: this reading exists to confirm or refuse an introduction,
    never to invent one, and the owner's *"1990-03-20 is AJ's birthday, not
    James's … the owner's brother Anthon James 'AJ' Taylor"* correction is
    exactly the mixed text it has to decline to read.

23. **A generational suffix is a generation.** When the vault holds both
    `<Name>` and `<Name> Sr.`/`Senior`/`I`, the suffixed one is one generation
    UP; `<Name> Jr.`/`Junior` is one generation down
    (`GENERATIONAL_SUFFIX_STEPS` stepping along `GENERATION_TIERS`, gated on
    `focus_candidate.FOCUS_RELATIONSHIPS` so a step onto a seat the roster does
    not have refuses instead of inventing one). A shifted row drops the
    relationship aliases the old word licensed, since a word of the wrong
    generation must not bind to the person it was the wrong generation for. The
    base name is compared WHOLE: "James Taylor" and "James Edwin Taylor" are two
    spellings this rule deliberately does not join, because four people on the
    owner's roster bear the token *James*.

24. **A birthday said with the word is said with the name.** `_introduced_birth`
    reads item 18's `birth_event_subject` first and then v345's
    `landmark_projection.names_a_birth` against any spelling the introduction
    itself licensed, inside the one source that introduced the person. The
    owner typed *"James Taylor my dad was born on June 4th 1954"* and the
    extractor filed the event as *"Dad's birthdate recorded"*; one clause, one
    person, and the word is the name.

**Considered and not built.** The father's death is in the vault — *"not Dad
James Edwin d.2019"* — but under a different spelling and in a different source
(the family-birthdays roster, which is Katie's introduction, not his). Filing it
as his `died` would be the cross-source, cross-spelling identity guess this
amendment exists to refuse, so the row ships without one. And the appositive
`<possessive> <word>, <Name>` shape — *"my dad, James Edwin Taylor"* — is still
not read, deliberately: reading it would introduce the owner's father a THIRD
time, under a third spelling, and hand "dad" back to nobody.

## Amendment (v349, 2026-09-24): a stated entry is never retired by shape

**What happened.** Staging, 19:18:10 UTC, hosted package pinned to v347
(`48ddabdf`). The owner answered a `residences` landmark card. The job filed
one source whose whole body is

```json
{"address":"701 North Williams","domain":"residences","label":"701 North Williams"}
```

and commit `398b85df` "Landmark: residences (Lifehug Cloud)" retired **all 30**
existing residence entries with it. `state/landmarks.json` residences went
30 → 1. Twenty-nine `sources/corrections/temporal-*.md` were filed, each
*"Supersede N temporal claim(s) … superseded by a later residences answer
(landmarks_interaction.entry_superseded_by)"*, `correction_scope:
landmarks/residences`, 89 claims in all. The published projection went
generation 152 → 153: nodes 1190 → 1161, unplaced 35 → 117, open work items
45 → 154. Every moment those stays had placed by containment — "Attended
Longfellow Elementary", "Fell on a nail", "Marriage to Katie", "Job at Boeing",
"Graduation from MIT", the whole childhood-moves sequence — fell to unplaced and
minted a card. Later residence answers ("dad's house", "Fiegers' house") filed
normally, so the wipe happened once: on the first substantive answer after the
pin. `work` at 19:03 and `partnerships` at 19:39 did not wipe their domains.

**What it was, and it is not what it looked like.** Nothing in v343–v347 broke.
Running `unreadable_fields` over the 30 real entries and the residences row at
v278, v342, v343, v345, v346, v347 and v348 returns the identical answer every
time, and `entry_superseded_by` returns `True` for 30 of 30 at every one of
them. The defect is **v278** (`8030d26`, E-L2c) meeting **v214** (`eb50e89`,
the cross-entry rule). Before E-L2c, `validate_landmark` on a rich residence
emitted `{address, city, domain, label, span}` and `unreadable_fields` returned
`()`. After it, the same value emits `{…, link, nickname, ongoing, place_ref}`
— five new descriptors, declared to `NON_RUNG_FIELDS` not at all — and
`unreadable_fields` returns four. v214's rule 3 read those four as the signature
of *"a machine that had many entries and filed one"* for sixty-four releases,
waiting only for a residences record lean enough to have none of them itself.
The 09-15 place-enriched import armed it; the 19:18 bare answer fired it.
`work` and `partnerships` were spared only because no entry of theirs carried a
descriptor, so `unreadable_fields` was `()` on both sides and the rule could
not fire at all.

The ladder-consistency guard exists to catch exactly this and did not, because
its probe (`tests/test_landmarks.py`, leg 4) is a hand-written `everything`
dict that E-L2c never joined. The guard never asked about the five fields, its
pinned `UNREAD` set stayed at six `(domain, field)` pairs, and CI was green
throughout. That is the recurring-defect doctrine's own failure mode: a
centralized definition (`unreadable_fields`, promoted onto the module by v214)
whose *inputs* are still a hand list.

**The rule.** `landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE`.
`entry_superseded_by` becomes a yes/no reading of `supersession_reason`, which
names which of the three legs fired (`SUPERSEDED_BY_NONE`,
`SUPERSEDED_AS_TERMINAL`, `SUPERSEDED_AS_COLLAPSED`) — because the two SPOKEN
legs are things the person said and carry no further guard, and the SHAPE leg
is the one that needs them.

1. **Only a demonstrable aggregate.** `collapsed_aggregate_fields` replaces
   `unreadable_fields` at rule 3. A field is evidence of a collapse only when
   it is one the domain's own writer never emits, or a `span` the domain has no
   rung for whose bounds straddle a stretch — which is v214's live instance
   exactly, the founder's four children as one row with a span across all four
   birthdays, and which a single child's own single-date span is not. The
   readable set is DERIVED: `writer_stored_fields` runs `validate_landmark`
   itself over `_writer_probe_value`, built from `_TEXT_CAPS`,
   `WRITER_DESCRIPTOR_FIELDS` and the row's ladder and from no hand list at
   all, and `validate_landmark` now drops any field not in that same
   declaration, so the writer and the store cannot drift apart again. The
   pinned six-pair slack is unchanged, and is now reproduced from the derived
   probe — which is the proof that the two probes agree.
2. **Provenance outranks shape.** An entry with a promoted source of its own is
   never retired by rule 3, whatever its fields look like. Every one of the
   thirty still had its `sources/landmarks/entry-*.md` on disk while the rule
   was deciding a machine had written it. The guard lives in
   `timeline.save_landmark`, the seat that can see the sources.
3. **One answer is one entry.** A single substantive record whose shape rule
   would retire more than one prior entry retires **nothing**, and the refusal
   is spoken: `supersession_findings` returns a finding in
   `lint_landmark_reply`'s shape naming the count
   (`SUPERSESSION_FAN_OUT_LINT`), which `save_landmark` appends to an optional
   `findings` list. A count is the only part of this incident a log could have
   shown anybody. A `none` is exempt and always will be — retiring the whole
   domain is what "I never served" means, so its fan-out is the point rather
   than a symptom. The record itself always files: a rule that cannot decide
   what it retires is no reason to drop what the person said.

**The repair, as a package verb.** `lifehug.py landmark-reinstate --domain
<domain> [--since <ts>] [--until <ts>] --apply`
(`landmark_projection.reinstate_domain`). Undo is a **statement**, never a
delete, exactly as it is for a move: it files ONE `retract` correction scoped
to `temporal_store.CORRECTION_CORRECTION_SCOPE` naming every supersession that
stops standing, and the fold resolves reinstatement as a SET before any mark is
laid, so it stays order-independent. The superseded corrections keep every byte
and every reason. The claims go active again. **Nothing writes an entry** — the
entries come back because `state/landmarks.json` is a drawing and the sources
behind it were never touched, which is the invariant this ADR's flip
established. It writes `sources/corrections/` and `state/` and nothing else, it
is deterministic (targets selected and sorted by content, never by mtime), and
it is idempotent twice over: the correction's id is a digest of what it says,
and `domain_supersessions` excludes what a previous run already reinstated, so
a second `--apply` reports nothing to do. A bare run writes nothing and prints
the plan. The `--since` window is what keeps it surgical — a domain may hold
perfectly good supersessions from other days, and a verb that reinstated those
would be the same class of defect it exists to undo.

**Measured** on a copy of the owner's staging vault: residences drawn 3 → 33
(the 30 restored plus the three later answers, all kept), residence stays
carrying a usable interval 0 → 30, containment placements
(`participation_span_applied`) 31 → 61, unplaced 51 → 32, open work items
76 → 48, nodes 1203 → 1233, projection generation 164 → 165, one file written
under `sources/corrections/`.

**Not this release's defect, and named so it is not mistaken for one.** The
`landmark_flip: … parked=6 codes=invalid_landmark_identity_kind` line on every
hosted job is a separate, stable, pre-existing condition and is unrelated to
the wipe. It is `temporal_claims._validated_landmark_identity_kind` refusing
six records whose `landmark_identity_kind` annotation (attached by
`landmark_projection.entry_claims` when a place's name ENUMERATES — a label
with commas, which most residences have) does not carry the deterministic
import provenance ADR 0033 requires. Those six never acquired claims at all,
which is the likeliest reason 29 corrections covered 30 entries. The wipe was
rule 3 and nothing else; the parked records are their own issue.

## Amendment (v350, 2026-09-24): one couple, one alias, one label

Three defects on the owner's own vault, all visible in the same sweep and all
three a READING the substrate makes of words somebody wrote. The sweep itself was
ordinary — `entity-roster --ensure-introduced`, `bind-episodes --apply`,
`publish` — and the roster introduction is what armed all three.

**1. A couple is two people, not one relationship word.**
`node:b8681112f7eed9342e7e4d56` *"Wedding reception in mother-in-law's
backyard"* — the OWNER's reception, subject `self`, his own anniversary
2007-01-11 — was folded into `node:536bdbed274f9512cc6c0378` at **1976-06-25**,
his PARENTS' wedding, beside `claim:34c92ccbf218e122a181ca5f` (*"Mom married dad
at 21"*) and `claim:e331cefd22c5a2c5670d861b` (*"Parents' wedding date"*). It
surfaced as a contradiction card, so v340 held; the merge was still wrong.

The path was not v345's couple key. The introduction filed `mother` as an alias
of `person/desiree-taylor`, `episode_containers.resolve_entities` matches a
contiguous TOKEN RUN, and `mother-in-law` tokenizes to `(mother, in, law)` — so
the word inside the compound resolved to the owner's mother, the reception's
person tokens became `{desiree, taylor}`, and `R2b`'s **per-person** milestone
bucket read the reception and the age telling as two tellings of one marriage.

Two legs, one seat each (`episode_binder.A_COUPLE_IS_TWO_PEOPLE`):

1. **A compound relationship word is never the simple word inside it**
   (`identity_resolution.A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`,
   `_not_a_simple_relation` — the analogue of v347's `_NOT_A_POSSESSOR`). A run
   that is one relationship word is refused when the words around it make it a
   different relationship: an in-law suffix behind it, read through the ONE
   `IN_LAW_RE` (moved from `axis_membership` to sit beside the vocabulary it
   reads, and re-exported there so `roster_relations` still finds it), or a
   `COMPOUND_RELATION_PREFIXES` word in front of it — step, grand, great, half,
   god, foster, adoptive, ex, former, late. It sits in `resolve_entities`, the
   seat that resolved the wrong person, so every rung reading a roster match is
   fixed once rather than `R2b` alone. A LONGER key is the compound itself and
   still matches: a roster that knows a mother-in-law by that phrase resolves her
   by it.
2. **A couple key is read from the telling's own SUBJECTS**
   (`identity_resolution.couple_key`, now handed
   `episode_binder.TellingView.subject_mentions`). The subjects are what a
   telling is ABOUT; a word in a backyard is not. The owner's own subject
   (`self`, `me`, `narrator`, and the first-person plural `we`/`our`) names the
   OWNER's couple, so a telling of *"our wedding"* belongs to his couple and can
   never reach his parents'. v345's vocabulary is unchanged and its pinned pair
   still meets across two vocabularies — and under a resolved roster the
   subject-side reading RESTORES it, because the introduction had already turned
   the age telling's person tokens into `{desiree, taylor}` and the old
   people-side key had stopped finding the couple it was written for.

**2. An identity re-key publishes an alias.** v346 documented the seam; this
closes it, as the fifth way a node id moves (ADR 0031's fold contract carries the
full amendment). A node id is derived from its subject, so *"Dad graduated"*
resolving to `person/james-taylor` moved `node:1bdbc9ecc7305d5a90c6e4a4` (1987)
to `node:2156ca1018344c8248882c44` (1987) for the identical claim
`claim:cd8e993b6bf95a5f4c80c862`, with no redirect — a lost placement to the
v340/v342 audit, and a broken URL to anybody holding the old id.
`temporal_timeline._identity_rekeys` derives the map from the mention the claim
still carries (resolution is data ABOUT a claim, never an edit of one), so the
former id is arithmetic rather than a cache and nothing is read off the previous
publication. Both of v342's dispositions apply unchanged: a key nothing publishes
any more becomes a redirect, reported `identity_subject_rekeyed`; a key some
claim still publishes is not redirected and that claim is CARRIED onto the new
id. The carry is what the duplicate undated *"Mom babysat Kodi and Acey Nixon"*
node needed — the resolver reading of that stay froze the old id into its own
`event_ref`, so the derived key moved out from under it and one fact was drawn
twice, the undated copy carrying a *"when?"* card the node beside it answers.

**3. A card never shows a node id as its label.** v343's *"a card is asked only
when a person could answer it"*, reaching the one rung that had escaped it.
`question_planner` minted `missing_anchor` items whose whole question was *"When
was node:0809d05e26d18f128fd83126?"* — 28 `missing_anchor` cards on the hosted
head, 22 of them with an id in the prompt, 13 and 10 after the sweep — because a
cross-dating anchor may be a NODE REF and the composer asked about whatever text
it was handed. Two seats
(`temporal_timeline.A_CARD_NEVER_SHOWS_A_NODE_ID_AS_ITS_LABEL`). The rung mints
nothing for a handle that names an internal id
(`conversation_lints.names_an_internal_id`), reporting
`anchor_without_a_human_label` with the nodes that were waiting — and dropping
the card loses nothing, because every one of those nodes already carries a card
of its own (48 of 48 on the head this was measured on). And the LINT refuses any
composed sentence carrying one, so no template in any composer can emit an id
even by accident. The shape is DERIVED from the minter — `temporal_claims.ID_RE`'s
`<prefix>:<digest>` — rather than from a list of prefixes, because v349's lesson
is that a centralized definition whose inputs are a hand list is not
centralized. The genuine anchors are kept, and one grammar rule joins them: a
phrase that LEADS with a verb is a bare predicate whatever its length
(`_leads_with_a_verb`, `_is_gerund_phrase`'s mirror, sharing its
`_ING_EVENT_NOUNS` vocabulary), so *"left Kristen"* is quoted back the way
*"moved in with dad"* already was instead of becoming *"When was left Kristen?"*.

`CALCULATION_RULE_VERSION` moves to `timeline-rules:17`: nodes, aliases and cards
all change for a vault nobody edited.

**Measured** on a scratch clone of the owner's vault (`/private/tmp/lifehug-rig-v350`,
head `cf3d996a`; the original was never written to), repaired first with
`landmark-reinstate --domain residences --since 2026-09-24T19:17:00Z --apply`
(29 supersessions, 89 claims, 33 entries drawn) and then swept:
`entity-roster --ensure-introduced` (4 rows), `bind-episodes --apply`
(7 envelopes, 338 proposals), `publish`. The wedding reception stays
`node:b8681112f7eed9342e7e4d56` at 2007-01-11, subject `self`, conflict state
`none`, before and after the sweep. Nine node ids moved across the sweep and all
nine carry an alias; the lost-placement audit is empty in all three legs (lost,
moved, drawn-at-an-alias). Zero of the 57 open cards carry `node:` in their
prompt; the five `missing_anchor` cards read *"When was 701 North Williams
foreclosure?"*, *"When was Dad's death?"*, *"You mentioned earning Eagle Scout in
Arizona — when was that?"*, *"You mentioned moved in with dad — when was that?"*
and *"You mentioned left Kristen — when was that?"*. Nineteen anchor handles were
refused as `anchor_without_a_human_label` and five subjects re-keyed. On a
separate copy of the already-swept vault the three readings take open cards
76 → 65, `missing_anchor` 13 → 3, cards carrying an id 10 → 0, and the
*"Mom babysat"* nodes 4 → 3 with the date carried onto the surviving one.

## Amendment (v352, 2026-09-25): answering a card places its moment

The owner hit this three times in two days, and each time the card stayed open as
if he had never answered.

1. `sources/conversations/msg-a2a65da9bda477a98f67f20c.md` — *"This was mostly
   last month and he's stopped mostly now"*, captured 2026-09-24T01:09:30Z,
   `session_ref: conversation:cand:work_item:work:577ecc4639edf0f8ead752ca`,
   answering **"When did Harvey's love of cussing happen?"**
   (`node:3380558928426602253447c7`, subject `person/harvey`). Its classification
   holds `time_periods: [{era: "last month", approximate_dates: "2026-08"}]` and
   `events: []` — the TIME was read and no event was — so `classifier_claims` had
   nothing to hang it on, the listener heard nothing, and nothing at all was
   filed.
2. `msg-fc9845c47f8dc2b5099724a5.md` — *"19-21 years old"*, answering the card
   about his father's mission. The general listener filed
   `claim:65573521952535272873944a`: `claim_type: age`, 19–21, `subject_mention:
   "they"`, `event_kind: span`, **no `event_mention`**, `confidence: 0.0`. That
   minted a node labelled *they* and a card *"When was they?"*. v343 suppresses
   the bogus node; the ANSWER still never reached the moment it was about.
3. `msg-57c728860e184aaf2146b021.md` — *"He only really started talking when he
   was 4"*. `claim:bf9f8a7a0faeb8bbb1ab77f1`: `claim_type: age`, 4,
   `subject_mention: "he"`, `event_mention: null`. The same shape — a time with
   no event.

**One cause, and it is not a careless model. The reply carries the WHEN and the
card carries the WHAT, and nothing joined them.** Every extractor that reads a
promoted answer is shown the MESSAGE ALONE: the classify prompt
(`classifier_context`, `contextual-timeline:3`) names no work item and
`general_listener.build_listener_prompt` takes an answer and a reply and no
question. Asked to find an event in *"19-21 years old"* there is none, so an
honest extractor either files nothing or files the time against whatever pronoun
the sentence happens to carry. And the join was already on the wire:
`session_ref: conversation:cand:work_item:<id>` is on the frontmatter of every
promoted message, the platform writes it on the listener road, and the published
`state/temporal_claims/work-items.json` carries that work item's `node_ref`,
`subject_ref` and its own question. Nobody read it.

**THE RULE** (`answer_placement.ANSWERING_A_CARD_PLACES_ITS_MOMENT`). A reply
promoted with a `session_ref` naming a work item is read as an answer to THAT
work item:

- the TIME it carries — a date, a range, an age, or a recency expression
  resolved against the message's own capture date — becomes a claim on the node
  the card is about, with the reply as its source and the record's basis
  `stated`, because the person is the one saying it;
- the SUBJECT comes from the NODE, never from a pronoun in the reply. This is the
  other half of v343's suppression: suppressing the bogus `they` node was right,
  and the answer must still land somewhere;
- a reply that carries NO time at all still files as a TELLING of that node — an
  `occurrence`, which asserts that it happened and says nothing about when — so
  the card stays open with the owner's words visible on it and never silently
  nothing.

**Nothing here is a second parser.** The rungs are `chronology`'s own
(`parse_stated_date`, `parse_age`, `from_recency` and its `RECENCY_RUNGS`), in
the same order `classifier_claims.temporal_reading` reads them, and the
confidences are that module's own constants. The one addition is
`AGE_PHRASE_RES`, a CLOSED vocabulary of age phrasings, because
`chronology.parse_age` is a FIELD parser and over prose it reads *"March 1998"*
as age 8 — `classifier_claims._age_band_text`'s own year trap, reused rather
than re-decided. A bare number behind *"at"* is refused outright: ADR 0026 ranks
a miss above a wrong join, and *"at 19 Elm Street"* is already a named negative
of the listener's own prescreen.

**Five named refusals**, so a report says WHY rather than showing a smaller
number: a card nobody published, a card that is not `open` (something else
already settled it), a `node_ref` the projection does not draw, a card whose
subject is `unresolved:` (Timeline Fix 01 P0b — when nobody knows WHICH James the
row is about, no sentence can settle it), and a reply with no words. A
day-scoped session (`…:work:<hex>:<YYYY-MM-DD>`, which the platform opens when a
card's plain session has closed) names the SAME card: a second conversation about
one question is not a second question.

**Two seats, one derivation.** `landmark_recorder.file_claims`, which already
received the `session_ref` for idempotency, now AIMS every draft at the card
before binding it (`event_ref` becomes the card's node, a bare pronoun subject
becomes the node's own, an absent `event_mention` becomes the node's label) and,
when the drafts assert no time at all — including the message that produced no
drafts — files the deterministic reading of the reply itself. And
`classifier_claims.migrate_classifier_moments`, the vault's one deterministic
claim-filing sweep, gains a second rung that walks every promoted answer with a
card whether or not any extractor heard anything in it; `place-answers` is the
same rung on its own verb. A name the person actually used is never overwritten,
and `event_kind` is left exactly as it was heard: the card tells a draft what it
could not know, and nothing more.

`CALCULATION_RULE_VERSION` does **not** move. This release adds CLAIMS and
changes no derivation, so a vault nobody answered draws exactly what it drew.

MEASURED on a scratch clone of the owner's vault (`/private/tmp/lifehug-rig-answer`,
reset to the generation whose cards he was answering — `1daaeba3`, generation 118,
where all three cards were open and all three nodes unplaced — with the three real
promoted answers restored from the head and the v352 framework overlaid; the
original was never written to). `place-answers` read 19 promoted answers carrying a
card, placed 3 and filed 3 as tellings, and refused 13 as `card_not_published`.
Open cards went 48 → 43 (`precision_gap` 43 → 37, `contradiction` 5 → 6), placed
nodes 1188 → 1193, node count unchanged at 1233. *Harvey's love of cussing* is
2026-07-24/2026-09-24, basis `stated`, rendering *"24 July 2026–24 September 2026
— you said last month, told 2026-09-24"*. *Harvey's late talking start* is `2026~`
basis `age`, measured from Harvey's own birth as the vault holds it. The v340/v342
lost-placement audit is EMPTY — nothing lost, nothing moved to an incompatible
date, nothing drawn at a redirected id.

**One thing the rule cannot finish, and it reports it by name.** *"19-21 years
old"* now lands on `node:b69a5be503b14977a6ba0077` *"Father's mission to New
Zealand"* as an `age` claim with the node's own subject — the answer reaches its
moment, which it never did before — and the fold cannot do the arithmetic,
because that node's subject is the raw mention `James Edwin Taylor` and the
owner's roster holds four people bearing the token *James* (`James Taylor` the
father, born 1954-06-04; `James Edwin Taylor Sr.` the grandfather; `James` the
brother; and the owner's own). v335's shared-name rule refuses an ambiguous key
and is right to: the fold reports `age_without_birth_anchor` on the claim and the
projection raises *"Which James or James Edwin Taylor Sr. or James Taylor is
'James' here?"* as an `identity_uncertain` card. Placing that span is an IDENTITY
question, not a dating one, and it is the next defect rather than this one.

## Amendment (v354, 2026-09-25): a reading is only superseded by the same reader

v352 finished its own verification with a gap it named rather than swallowed
(lifehug#409, filed by v353's fresh-clone run): the v340/v342 placement audit over
`place-answers` + `publish` on the owner's vault was **not** empty.

```
{"drawn_at_an_alias": [], "lost": ["node:091ec8a898daa8548afaf104"], "moved": []}
```

**THE CAUSE is in the fold, not in the writer.** `temporal_store._fold` step 1
grouped receipts by `(source_id, revision)`, elected the latest by
`receipt_sort_key` as the group's winner, and marked every other receipt's claims
`superseded / reextracted` — *"a previous interpretation of the same words"*. That
rule was written for one extractor re-running over one document and is right for
that. But `answer_placement.file_answer` writes its receipt on the promoted reply
ITSELF, at that reply's own revision, so on a message the `general_listener` had
already read the answer's receipt was simply newer and won. Two of the owner's
answered messages were in that state, and the loss is one-sided in the worst way:
`place-answers` files at most ONE claim per message, so a listener reading that
found a date was replaced by one `occurrence`.

- `conversation:msg-99efe6688bbd9e4f752438e0` — *"She graduated in 2006"*.
  `receipt:537be58a3848123630f24b32` (`general_listener`) retired by
  `receipt:d9a21bab13bbd169561adc7e` (`answer-placement`), taking
  `claim:36bae1eb0bbfd2120274471d` — a `date`/`graduation`, 2006, subject mention
  `Katie Ann Merrill` — and with it `node:091ec8a898daa8548afaf104`, **placed at
  2006**, and the card that named it.
- `conversation:msg-c9d84f13e02d1c9547bafaa6` — `claim:257f9e5681424bdd8539c76a`,
  a `relative_order` after *"left Kristen"*, and the undated
  `node:3d1065f366b17440103c9a25`.

**THE RULE** (`temporal_store.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`).
The election unit is `(source_id, revision, extractor identity)`: a receipt
supersedes another only when the SAME READER re-read the same revision of the same
document. Two extractors reading one message are two readings of it, both
legitimate, and neither retires the other — which `answer_placement`'s own receipt
has said in prose since v352 and which `temporal_claims.CLAIM_IDENTITY_KEYS`
already made true of their CLAIMS. Only the group key was missing it.

WHO a reader is, is the **name** at the head of its extractor version
(`temporal_claims.extractor_identity`,
`temporal_claims.AN_EXTRACTORS_NAME_IS_WHO_READ_IT`); everything after the name
says which VERSION of that reader did the reading. Both spellings this vault files
are handled: `name/schema:…/prompt:…/model:…` and the older `name:N`
(`classifier_context.EXTRACTOR_VERSION`).

**Why not the whole `extractor_version`, which the issue suggested first.**
`temporal_claims.receipt_relative_path` already writes one receipt file per
`(source, revision, extractor_version)`, so two receipts in one group ALWAYS
differ in that string — keying on it would make every group a singleton and
supersession-by-re-extraction dead code. And re-extraction in this vault IS a
version bump: a prompt edit is a new `prompt_version`
(`general_listener.PROMPT_VERSION_LENGTH`), a better reading of the same bytes is
a new rule version (`timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION`'s own
`"4" -> "5"`). The version therefore stays out of the key and the name goes in.

**It is general, not a special case for `answer_placement`.** Every pair of
readers that can meet on one source revision now coexists: `general_listener` and
`landmark_recorder` on one message (`landmark_recorder.file_claims` files both
roads in one call and its own docstring already called that *corroboration, not
duplication*), `classifier-claims` and `resolver`, `landmark-record` and
`legacy-entry-import` on one landmark entry — that pair being the SAME rule under
two names, whose flip is gated on `landmark_projection.already_substrate_backed`
rather than on one retiring the other. The resolver never depended on the election
at all: it retires an earlier reading with an explicit `supersede` correction,
*"the new receipt stands beside it, never over it"*, which is the behaviour the
whole fold now has.

`CALCULATION_RULE_VERSION` does **not** move. It describes what the same claims
CALCULATE to; v354 changes which claims are ACTIVE, and only on a source revision
two readers have both read. The arithmetic over an active set is untouched, and
the fold is re-run in full on every publish, so no vault carries a stale index
across this change. PROVED rather than argued: two fresh clones of the owner's
vault at one head, one per framework, publish byte-identical
`calculated-timeline.json` and `work-items.json`. The index's own shape gains two
fields (`extractor_identity` on a source row, `readings` in the counts) and moves
nothing an older reader looked at, so `INDEX_VERSION` stays 1.

MEASURED on two fresh scratch clones of the owner's vault at one head
(generation 188, 1265 nodes, 69 work items), one with v353's bytes and one with
v354's; the original was never written to. `place-answers` reads the same 28
answers on both and files the same 8 receipts (1 placed from the recency reading,
7 `telling_only`, 20 refused `card_not_published`, no errors). Then they diverge,
and only here:

| after `place-answers` + `publish` | v353 | v354 |
|---|---|---|
| placement audit | `lost: [node:091ec8a898daa8548afaf104]` | **empty** |
| claims retired `reextracted` | 2 | **0** |
| nodes | 1265 → 1263 | 1265 → **1265** |
| placed nodes | 1215 → 1215 | 1215 → **1216** |
| open cards | 69 → 66 | 69 → **68** |

The two nodes v353 loses and v354 keeps are `node:091ec8a898daa8548afaf104`
*"Katie Ann Merrill"* at **2006** and the episode `node:3d1065f366b17440103c9a25`
*"moving in with dad"*. Re-measured on a clone taken at a LATER head
(generation 190 → 191), so the result is not head-specific: the audit is empty
again, no claim's status changes over the act, and the same two source revisions
are the only ones read by two readers each.

**The cards that come back with them** are `work:89892041c9cdd3d80b0675ef` and
`work:ba396d81db81f8c59a630129` — a node retired out of the drawing takes its
question with it, which is the second half of why this was worth its own release:
the vault stops asking about a moment it has lost.

GUARD: `tests/test_v354_a_reading_is_only_superseded_by_the_same_reader.py` — 32
tests whose part-1 ids are the owner's own, minted rather than copied, because his
reply's bytes promote to the same source revision and therefore to the same claim
and receipt ids. Run against v353's bytes the file fails 21 tests, and the
synthetic whole-act audit fails with HIS node id in `lost`.

## Consequences

- The classifier's validator is no longer the place where placement is won or
  lost. v313 made per-event salvage available so one bad relation does not
  refuse a whole batch; v315 made that the local loop's explicit choice
  (`file_batch_response(salvage=True)` from `run_batch` only), because a host
  that files envelopes without a resolver still needed the refusal its own
  repair loop re-asks the model about. v323 makes salvage the default for
  every filing path: hosts have run the resolver since v316, and the
  whole-reading refusal was measured throwing away a story with several
  moments whenever any one moment tripped a per-event check (staging,
  2026-09-20: 55 of 98 refresh readings refused, 79 accepted on replay with
  salvage, 25 fully validated placements recovered, no bad link filed). The
  repair loop keeps its job for what salvage cannot mend — structural
  failures and snapshot mismatches.
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
- A question the resolver closes has to stop being asked. Because the resolver
  places a moment rather than answering a bank row, a `tl:`/`lo:` question
  minted from an earlier projection can outlive its work item; v319 therefore
  retires every pending minted row whose identity the current projection no
  longer carries — annotated (`retired: placed by the resolver (work item gone
  from the projection)`), never deleted — on every `timeline_candidates` build
  and at the end of any publication that moves the work-item set (lifehug#368).
- Complexity budget: the intended shape is *spine + model + verification +
  ledger*. New placement rules should improve the spine or the verifier, not
  add joins in front of the model.

## Amendment (v357, 2026-09-25): a full name outranks a shared first name

*"Father's mission to New Zealand"* (`node:80f419115b858c37a7b051f3`) was
published with the raw subject `James Edwin Taylor` — the owner's father's full
name — and so were four more of his father's moments. The roster spells his
father `James Taylor` (`person/james-taylor`, born 1954-06-04) and holds four
other rows bearing *James*: `james-edwin-taylor-sr` (his grandfather, differing
only by the suffix), `james-everett-taylor` (his son), `anthon-james-taylor`
(his brother, alias `James`) and `james` — an alias row, `maps_to_focus:
anthon-james-taylor`. No exact key matched and the only rung that read inside a
name was v335's census, which is about ONE bare word, so the full name fell to
`no_candidate` and no birth could reach the moment.

Three rules, one seat each, all in `identity_resolution` (pure, and so the one
module every reader can import):

1. **A full name outranks a shared first name**
   (`A_FULL_NAME_OUTRANKS_A_SHARED_FIRST_NAME`, `full_name_candidates`, reason
   `full_name`). A mention binds the one roster person whose own spelling it
   carries: given name and surname both anchored, every word of the roster's
   spelling present in order, optionally with a middle name the roster does not
   spell. The spellings are the roster's own (`RosterIndex.full_names`); a
   mention never reaches INTO a longer roster name, a relationship word is only
   a veto, and two people carrying the same spelling are a standoff. It is
   consulted before the relationship rung, because that rung needs every name
   word borne by the candidate — and *Edwin* is borne only by the grandfather.
2. **A generational suffix is one generation, not a tie**
   (`A_GENERATIONAL_SUFFIX_IS_ONE_GENERATION`). A spelling's generation is part
   of it, so `James Edwin Taylor` is never `James Edwin Taylor Sr.`. The table is
   v347's `GENERATIONAL_SUFFIX_STEPS`, moved here from `roster_relations` (which
   re-exports the same object — the v350 `IN_LAW_RE` precedent) and grown by
   `snr`, `jnr`, `ii` and `iii` for both readers at once.
3. **An alias row is never a candidate anywhere**
   (`AN_ALIAS_ROW_IS_NEVER_A_CANDIDATE`, `is_alias_row`). v343 took it out of
   `roster_index`; the fold's binding indexes read the raw rows through
   `axis_membership.roster_person_rows`, which now drops it too.

v335's protection is kept, and needed one repair to stay kept: the alias row
disagreeing with the brother about the key `james` was the only thing keeping
that bare word out of `_person_key_index`, so a key several people answer to as
a given name is now ambiguous there by the census itself
(`shared_name_token_refs`).

**Should alias rows exist?** They carry real information — curation's
statement that a spelling IS an existing Focus, which the wiki routes by — so
the roster writer may keep minting them. What they must never be is a person,
and after this release no identity reader treats them as one. Folding such a
spelling into its target's `aliases` instead of minting a row would be the
cleaner store, but it is a writer migration with its own blast radius
(`focus_merge`, `entity_verdict`, wiki routing), and the reader-side predicate is
the smaller fix.

Measured on a scratch clone of the owner's vault, one deterministic publish per
framework: 5 nodes changed subject (all to `person/james-taylor`, none
re-keyed), `age_without_birth_anchor` 13 → 12, the one `identity_uncertain`
card unchanged, `lost` and `drawn_at_an_alias` empty. The `moved` leg names one
node, *"Father's four years bedridden"*, whose `age` claim `22, 23` is the
NARRATOR's age (`when_hint: when I was just off my mission`) filed against his
father against the classifier's own contract; the resolver's 2003-07/2009-07
is kept as the alternate and a contradiction card asks. That is an extraction
defect this release unmasks (lifehug#415).
`CALCULATION_RULE_VERSION` → `timeline-rules:18`.

## Amendment (v359, 2026-09-25): an answer outlives its card

The owner answered his father's mission card *"19-21 years old"*
(`msg-fc9845c47f8dc2b5099724a5`, session
`…work_item:work:b7525efb7ce0bb69be2d7129`). Before the answer was placed, the
2026-09-23 run of this resolver dated that node from its own reading, and v350's
identity re-key moved it (`node:b69a5be503b14977a6ba0077` →
`node:80f419115b858c37a7b051f3`). The card left the published generation, and
v352's `place-answers` refused the answer `card_not_published` — as it refused
**20 of the 28** card answers on a clone of his vault. The resolver dating a
moment is exactly what it is for; what was wrong is that its doing so first
made the person's own answer count for nothing, and said so only as a number.

**THE RULE** (`answer_placement.AN_ANSWER_OUTLIVES_ITS_CARD`): an answer to a card
the person was shown counts however the card has closed since. The card is not
remembered — it is RE-DERIVED. A work id is `derive_work_item_id` over (kind,
subject, node, field), so `closed_cards` mints the ids every node the vault still
holds could have been asked under: every drawn node, with its resolved subjects
and the raw `subject_mention` of every claim it folds (resolution is data about a
claim); every id `node_aliases` redirects; and every node a filed claim's
`event_ref` names. The node is followed through `node_aliases` to where it is
drawn now, and the answer is placed there under the node's own subject, exactly
as v352 places an answer to an open card. It is refused only when no node could
have asked the card (`card_not_published`) or when that node is no longer drawn
(`card_node_not_drawn`), and every refused answer is listed on the report. What
v352's refusals protected is kept: a row a host marked settled is still
`card_not_open`, an `unresolved:` subject is still refused, one answer is still
one receipt keyed on the reply's revision.

**This resolver's retirements are now visible from the other side.** Three of
the owner's answers were to moments this resolver retracted as not an event (two
`duplicate`, one `fact_statement`); the answers are refused `card_node_not_drawn`
and listed with the node they asked about. A `duplicate` verdict names the node
it duplicates only in its prose reason, so an answer to the retired moment is not
followed onto the surviving one; a structured `duplicate_of` on the verdict
would let it be, and is left for the resolver's own release.

**A first-person age is the narrator's** (`answer_placement.NARRATOR_AGE_RE`).
*"probably when I was 4 or 5"*, answering a card about his father, is filed under
`self` on the card's node and measured from the owner's own birth — lifehug#415's
first gap, in this seat. The classifier's half of #415 stays filed.

The father's mission now carries the answer's own `age` claim, measured
1973-06-04/1976-06-03 from 1954-06-04 and joined to the placement's provenance
(`age_corroborates_placement`); the drawn window stays this resolver's
month-grained 1973-06/1976-06, because v345's ruling makes an agreeing age
evidence on a dated moment, never its rival. `CALCULATION_RULE_VERSION` does
**not** move.
