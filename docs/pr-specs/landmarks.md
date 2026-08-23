# Contract — landmarks: the always-present dating question set (v199)

**Research:** `system/research/landmarks.md` (v198, PR lifehug/lifehug#202, merged).
**Builds on:** ADR 0024 (chronology with basis), v195's `timeline`
Interaction, v196's whispers and keystone questions.
**Owner rulings:** 2026-08-23 (below, §A).

---

## A. Why this exists

**We built the arithmetic before the inputs.**

v195 shipped `chronology.from_age`, `from_anchor`, `intersect` and
`reconcile`. v196 shipped `keystones()` and the two rails that ask for the
highest-leverage anchor. But as of v196:

1. `birth_date` is a parameter of `timeline.timeline_data`,
   `timeline.anchor_index`, `timeline.resolve_event_dates` and
   `timeline_interaction.anchors_for_person`, and **no production caller ever
   passed it.** `profile.yaml` had no birth-date field. So
   `chronology.from_age` — the highest-yield rule in the system, because "I
   was about five" is the commonest way people volunteer time — was
   unreachable in production.
2. Residences reached `anchor_index` only as wiki entities of `type: place`
   that happened to carry a date. Nothing ever *asked* for a residence chain.
3. `PLAYBOOK_STEPS` rungs 5 (`sequence`) and 6 (`landmark`) are marked
   `needs_anchor: True`. Over a near-empty anchor index, the two cheapest and
   best rungs in the sourced playbook could never fire.
4. `keystones()` is the right mechanism aimed at an empty stock.

This contract fills the index.

### Owner rulings (2026-08-23)

1. **Onboarding asks in generalities.** "Do you remember where you lived?
   Where was that?", "Which schools?" — answer or skip.
2. **Always-open on the Timeline, never in the queue.** Every landmark that is
   unanswered *or below target specificity* stays on the Timeline page as an
   always-present answerable item. No reminders, no nagging. The person fills
   it when they can — from memory, from a relative, or from a records lookup.
3. **A specificity ladder per domain, not a boolean.** Residence: city →
   address → span → household. School: name → place → grades → span. A vague
   answer is *answered*; it stays open only because more would unlock more.
4. **A landmark with no stories is itself a gap** — new information the system
   could not see without the landmark, and a better question than any generic
   prompt because the person supplied the noun.
5. **The keystone star moves with the leverage.** A landmark that holds the
   highest-leverage anchor is marked `keystone: true` in its row. Implemented
   in `timeline.landmark_rows_for` by mapping the *derived* keystone back to
   the landmark domain that would supply it: **no birth date filed → ★
   `birth`** (unarguable — with no axis `from_age` cannot fire at all); a
   `period:` or a place `entity:` keystone → ★ `residences` (an era's bounds
   and a place's span are the same question in the sourced playbook). Nothing
   else is starred; the set is never starred for the sake of it.
6. **The name: Landmarks** (owner-set, 2026-08-23). **Landmarks** is the
   product and user-facing word — in the glossary, the handbook, the docs and
   any surface copy — and it is also what the package, module and CLI are
   called, so there is exactly one name from the UI down to the file on disk.

   **`anchor` is the CODE term for a different thing**: the *derived* index a
   landmark's date becomes once it can bound something (`timeline.anchor_index`,
   `basis: "anchor"`, `chronology.from_anchor`,
   `timeline_interaction.anchors_for_person`). A landmark is the question and
   the answer; an anchor is what the answer turns into. The research surveyed
   *Anchors* as a candidate product word (`landmarks.md` §4); the owner's
   ruling settles it the other way, and this is the better split — reusing
   `anchor` for the question set would have given one identifier two meanings,
   which the recurring-defect doctrine forbids.

   The join between the two is `landmarks_interaction.anchors_from_landmarks`.

---

## B. The question set is data

`interactions/landmarks/questions.yaml`, flat-scalar subset
(`lifehug_core._parse_simple_yaml`), same convention as `interaction.yaml`.

Eight domains, in order: **birth · residences · schools · partnerships ·
children · work · military · losses.** Birth is first because it is the axis
(every fielded instrument takes it first — SHARELIFE ST006/ST007, NLSY97's
"month the respondent turned 14"). Residences and schools follow because they
are the two **closed lists**: enumerable, finite, tiling, verifiable,
finishable, and the only two a living relative can supply
(`landmarks.md` §2.7).

Per domain: `order`, `onboarding`, `ask` (the general question), `ladder`,
`complete_at`, `precision`, `unlocks`, `chain`, `sensitive`, `why` (the
sourced reason).

Read through `landmarks_interaction.load_questions()`, `domain_row(domain)`,
`onboarding_domains()`. An unknown domain **raises**; the set is closed.

---

## C. The specificity ladder

- `rung_reached(entry, row)` — the finest rung an entry satisfies. The walk
  **stops at the first hole**: a span with no address is still at `city`,
  because a ladder is a ladder.
- `status_for_domain(entries, row)` → `open | partial | complete`. A chain
  domain is never `complete` until the person says the list is finished
  (`chain_complete`).
- `next_rung(entries, row)` → `{domain, rung, subject, text, cost}` — the one
  thing to ask, with the question already written. `RUNG_TEXTS` holds every
  `(domain, rung)` pair; `CHAIN_MORE_TEXTS` holds "and where did you go after
  that?".

---

## D. The one additive turn-output field

`TurnShape.landmark_stage` (`"open" | "ask" | "close"`, default `None`) gates
one optional `landmark` key in the output contract, exactly as
`timeline_stage` gates `placed`.

**Required test:** `test_output_contract_block_byte_identical_without_landmark_stage`
— with the stage `None` the appendix does not move by one byte, so the passive
daily question is untouched.

Two validation layers, as always:

1. `conversation_delivery._parse_landmark` — structural. A closed key set, short
   strings, an optional date, an optional `{start, end}` span. Anything else
   degrades to `None`, never an error.
2. `landmarks_interaction.validate_landmark` — semantic. Checks the **domain**
   against the question set (the structural layer cannot see it), keeps only
   the rungs that domain declares, and **normalizes every date through
   `chronology.parse_edtf`** so `earliest`/`latest` are filled — a record with
   bare `best` renders as an empty string and dates nothing.

---

## E. The stage and the stop rules

`landmark_stage_for_session(session, *, user_leaving, all_settled, skip_streak)`.
`MAX_ASKS = 4`, `STOP_AFTER_SKIPS = 2`, pinned equal to
`knob.max_asks` / `knob.stop_after_skips` by
`test_stop_rule_knobs_match_the_module_constants`. A landmark pass is never an
interrogation.

---

## F. The five lints

`landmark_gates.no_year_demand` · `accepts_vague` · `no_form_voice` ·
`one_domain_per_turn` · `never_presses_sensitive`.

`no_year_demand` **suspends for `birth`** — the one legitimate date opener
(`landmarks.md` §2.1). `never_presses_sensitive` applies only to a sensitive
domain: the parent Conversation contract already owns pressure in general, and
a second definition of it is the defect the recurring-defect doctrine forbids.

Findings share `conversation_lints.lint_turn`'s shape (`lint` / `detail` /
`span`) so one caller merges both sets uniformly.

Gates in `interactions/landmarks/evals/lints.yaml`, all at 1.0, scored by
`system/landmarks_evals.py` over eight goldens:

| Golden | What it pins |
|---|---|
| `landmarks-open-birthday` | the one direct date question, and what it unlocks |
| `landmarks-residence-chain` | the ladder walked town → street → span |
| `landmarks-vague-is-an-answer` | a coarse answer received, not sharpened |
| `landmarks-skip-is-final` | a decline ends the domain, and is never retried |
| `landmarks-school-grades-not-years` | grades asked, years derived |
| `landmarks-losses-offered-never-pressed` | the sensitive domain |
| `landmarks-one-domain-per-turn` | one domain per turn |
| `landmarks-never-invents-a-domain` | an invented domain is dropped, not stored |

---

## G. The store and the write path

`state/landmarks.json` (`vault_contract.json` data path `landmarks`, contract
revision `vault-contract-v7`). Readers and writer live with the placements in
`system/timeline.py`:

- `timeline.load_landmarks()` → `{domain: [entry, ...]}`, degrading to `{}`
  rather than raising.
- `timeline.save_landmark(domain, record)` — **merges by label**, because the
  ladder revisits the same subject: a city today, an address next week, a span
  after that, all on the same entry.
- `timeline.landmark_birth_date(landmarks=None)` — the birthday as a
  `DateRecord`. This is the function that gives `birth_date` a source.

CLI: `lifehug.py landmark-record <domain> [--label] [--date] [--start] [--end]
[--city] [--address] [--grades] … [--complete]` (writer lock, like
`timeline-place`). `landmarks_interaction.landmark_invocation(record)` names
the argv; the host runs it.

---

## H. What the rest of the system gets

1. **`anchor_index` fills up.** `landmarks_interaction.anchors_from_landmarks`
   turns the store into `{key: {label, date, kind}}` with the kinds
   `anchor_index` already understands. `timeline.anchor_index(...,
   landmarks=…)` merges them **first**, so a landmark the person stated
   outright wins over anything derived from a page.
2. **`birth_date` has a source.** `timeline_data()` reads the store once and
   defaults `birth_date` from it. `chronology.from_age` is reachable.
3. **`anchors_for_person(landmarks=…)`** accepts either the raw store or the
   derived index, so the two `needs_anchor` playbook rungs can fire.
4. **`timeline_data()["landmarks"]`** — every domain with `status`, `count`,
   `keystone` and its `next` question, so a host renders only the open ones
   (ruling 2). `timeline.landmark_rows_for(data)` applies the ★ from the live
   keystones (ruling 5).
5. **`timeline_data()["place_no_stories"]`** — ruling 4. v196's `place_span`
   asks *when* you lived somewhere; this asks *what happened there*, and only
   exists once a landmark names the place. Deliberately **not** added to
   `timeline.UNKNOWN_KINDS`: it is a story gap, not a dating gap, and folding
   it into the dating kinds would put it on the wrong ladder.
6. **`lifehug.py arc-plan-target --landmarks [--json]`** walks the open rows
   as an episode, keystone first, then by ladder cost.

---

## I. Placement (ruling 1 and 2)

| Where | What |
|---|---|
| Onboarding | the five `onboarding: true` domains, asked in generalities, skippable without comment |
| The Timeline page | every row whose status is not `complete`, always present, openable by Play or fillable inline |
| The daily queue | **never.** The only exception is v196's existing keystone path — a whisper or one minted bank question |

---

## J. Deviations from the research

1. **The name** — see §A.6. The research surveyed *Anchors* as the product
   word; the owner's ruling is **Landmarks** everywhere, with `anchor` kept
   for the derived index it already names in code.
2. **Fifteen questions became eight domains with ladders.** The research's
   numbered list mixed domains with rungs (items 3, 4 and 4b are all the
   residence chain). Collapsing to eight domains × a ladder is the same set
   with the owner's ruling-3 shape, and it makes the "below target
   specificity" state expressible, which a flat list cannot do.
3. **`profile.yaml` did not gain a `birth_date` field.** The research proposed
   one; the store carries it instead, so there is one writer and one read path
   rather than two. `timeline.landmark_birth_date()` is the accessor.
4. **`place_no_stories` is not a `timeline.UNKNOWN_KINDS` member** — see §H.5.

---

## K. Folded in from `system/research/go-deep.md` (v197)

Three findings from the sibling corpus land here rather than waiting for the
dig session, because they change code this contract already touches.

1. **The keystone plan is greedy over the RESIDUAL graph** (§8.2/§8.3).
   `timeline.keystones()` ranked independently by leverage and double-counted:
   on real vault data one star's resolve set was a strict SUBSET of the
   other's, so the second star's marginal gain was **zero** — two questions
   placing exactly what one question places. It now takes the anchor with the
   largest gain against what is *still* unknown, removes what it covers, and
   repeats. The coverage objective is monotone submodular, so greedy is within
   `(1 − 1/e) ≈ 63%` of optimal ([Nemhauser, Wolsey & Fisher, 1978](https://doi.org/10.1007/BF01588971)).
   Each row keeps `leverage` (the total, which is the number the person is
   shown) and gains `gain` (the marginal contribution that earned its place).
   **A plan is never padded to the cap**: when nothing left adds anything, the
   shorter plan is the honest one. Five tests in `tests/test_landmarks.py`
   (`GreedyKeystoneTests`), including the subset case from the analysis.

2. **Nothing may propose a date for confirmation** (§4.3). True photographs
   plus suggestive interviewing produced false memories in 65–66% of
   participants, "substantially higher than the rate in any previously
   published study" ([Lindsay et al., 2004](https://doi.org/10.1111/j.0956-7976.2004.01503002.x)).
   A dating probe backed by the person's own evidence is that configuration
   exactly. New lint class `never_proposes_a_date`, shared: ONE definition
   (`timeline_interaction.proposes_a_date`) run by BOTH lanes, gated at 1.0 in
   both `lints.yaml` files, unconditional in both harnesses — there is no
   stage, no rung, and no domain (**not even `birth`**) where naming a date and
   inviting a yes is correct. Reporting the arithmetic is *not* proposing:
   "you were twelve, so that puts it around 1986" states a derivation and shows
   its working; "was it 1986?" asks for a confirmation. Golden
   `landmarks-reports-the-arithmetic-never-asks-agreement` pins the line, and
   the rule is written into both `prompt/behavior.md` files.

3. **Vocabulary** (§7). **Cross-dating** is adopted as the name of the
   *mechanic* — dating an undated sequence by matching it against an
   already-dated one — in docstrings and docs, never as a product noun.
   **Witness** is adopted for a living person who was there: it comes from the
   residence ladder's own `household` rung, so **no new state**, and it rides
   on every `place_no_stories` row, because the people who were in the house
   are exactly the people who can answer about it.

4. **The timeline stays up.** `timeline_data()`'s landmark reads are guarded:
   a missing question set or an unreadable store degrades to "nothing filed",
   never to an exception. Found the honest way — the external data-only vault
   subprocess test failed its compile, because `timeline_data()` now reads a
   store and a question set a minimal vault need not have.

---

## L. Gates

- `python3 -m pytest tests/` — full suite, including
  `tests/test_landmarks.py` (57 tests).
- `python3 system/lifehug.py landmarks-evals --json` — the recorded seat.
- `python3 system/lifehug.py timeline-evals --json` — unchanged.
- `python3 scripts/ci/check_framework_files.py`.
- `python3 -m pytest tests/test_handbook_parity.py`.
- `system/version.json` 196 → 197.
