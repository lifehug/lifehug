# Contract — the Family landmark: siblings as anchors, elders as witnesses (v202)

**Research:** `system/research/landmarks.md` (v198 → amended here, §2.9 "The
family constellation"), `system/research/go-deep.md` §7 (the *witness*
vocabulary).
**Builds on:** `docs/pr-specs/landmarks.md` (v199, the eight-domain set),
`docs/pr-specs/place-no-stories-arcs.md` (v200), ADR 0013 (entity owner
verdicts and the two identity facts), ADR 0024 (chronology with basis).
**Owner approval:** 2026-08-24 (§A).
**Version:** `system/version.json` 201 → **202**.

---

## A. Why this exists

The v199 set has eight domains and **no row for the family you came from**.
Partnerships and children are the family you *made*; residences and schools are
where you were. Nothing in the set asks who was in the house with you.

### Owner's reasoning (2026-08-24, encoded here as the ruling)

1. **Siblings' birth years are among the strongest anchors we can get.**
   "Before or after your brother was born" is *already* the probe style the
   timeline interaction uses (`timeline_interaction.KIND_OPENERS["moment"]`'s
   anchored form is literally `"{label} — was that before or after
   {anchor}?"`). Today that probe has almost nothing to point at, because the
   only person-shaped anchors the set can mint are the person's own children
   and partnerships — late-life events that bound the wrong half of the
   timeline. A sibling's birth year bounds *childhood*, which is exactly the
   stretch where "I was about five" is the only thing anyone can offer.
2. **Parents and grandparents are the witnesses of the ask-the-living
   thread.** `landmarks.md` §2.7 claim 2 already says it: "A parent can recite
   the addresses and the schools; nobody but you can supply your turning
   points… this is the only place in the instrument where the answer exists in
   someone else's head, complete — and where that head is a depleting
   resource." v200 gave `place_no_stories` a `witnesses` field sourced from the
   residence `household` rung. That is a thin seam: it only knows about people
   who were named while talking about a *house*. The family constellation is
   where witnesses actually come from.
3. **Genealogy intake asks the family constellation first.** Amended into the
   research as §2.9, with citations. The convergent finding is that
   practitioner intake forms ask the constellation immediately after the
   subject's own birth and *before* schooling and work.

### Owner rulings added 2026-08-24 (the "unknowns are concrete" pair)

4. **Per-item incompleteness gets SUBJECT-NAMED follow-ups.** When a family
   member exists without a birth year, the domain row's `next` names them —
   "What year was Jackie born?" — never a generic re-ask of the domain. Same
   for any partially-answered enumeration rung: a residence named without a
   span asks "When did you move into Bell Avenue, and when did you leave?".
   **And each incomplete subject is also emitted as its own concrete
   unknown** (kind `landmark_subject`, labelled with the person or place), so
   it flows into the unknowns page, the arc planner's whispers, and the plan
   ordering like any other answerable thing.
5. **A hole in the residence history is a concrete unknown.** When two
   consecutive residence spans leave a gap — Mesa ends ~1992, Yucaipa starts
   ~1995 — emit an unknown that asks the hole by name: "Where did you live
   between Mesa and Yucaipa, around 1992–1995?" (kind `residence_gap`). A
   partial answer is accepted whole ("five of the seven"); the remaining holes
   persist as unknowns; **nothing nags**.

Rulings 4 and 5 are the owner's *Unknowns are concrete* principle (v196)
applied to the landmark set, which until now produced exactly one offerable
question per domain no matter how many subjects sat half-filled inside it.

---

## B. The ninth domain

`interactions/landmarks/questions.yaml` gains `family` at **order 2** —
immediately after `birth`, ahead of the residence and school chains. Every
later domain's `order` shifts by one (residences 3, schools 4, partnerships 5,
children 6, work 7, military 8, losses 9).

| field | value |
|---|---|
| `order` | 2 |
| `onboarding` | true |
| `ask` | `Who was in your family growing up — brothers and sisters?` |
| `ladder` | `who \| relation \| birth \| living` |
| `complete_at` | `birth` |
| `precision` | `year` |
| `unlocks` | `sibling_interval \| span_containment \| witness_supply` |
| `chain` | true |
| `sensitive` | false |
| `why` | A third closed list, and the only one made of people: siblings date childhood, elders are the witnesses. |

**Why order 2 and not later.** Three arguments, all in the research:

* The intake forms that ask a constellation ask it *there* — Montana's Oral
  History Biographical Data Sheet runs name at birth → date of birth → place
  of birth → mother → father → maternal grandparents → paternal grandparents →
  siblings → spouse → children → schools → jobs, and the North Dakota VHP
  guide's Segment 1 is "1. Full name… 2. When/where born **3. Parents' names
  and occupations 4. Where/when were parents born**" (research §1.8, both
  already cited; §2.9 adds the reading).
* **It is a third closed list.** §2.7's whole argument for residences and
  schools — enumerable, finite, ordered, verifiable, *finishable* — holds for
  siblings exactly, and holds harder for parents and grandparents, which are
  finite by biology. §2.9 records the one way it differs: this list is made of
  *people*, so it joins the roster rather than the place index.
* **It is the cheapest anchor per question in the whole set.** One sibling
  answered yields one dated point in childhood. Residences need two rungs
  (city, then span) before they yield anything datable at all.

**One entry per PERSON.** `timeline.save_landmark` merges by label, so
`(domain, label)` is a landmark's identity and the label is the person's name.
The rungs:

* **`who`** — the name. Already a ladder rung in three domains and already a
  CLI flag; reused deliberately rather than minting `name` twice.
* **`relation`** — `sibling` / `parent` / `grandparent`, **closed against
  `focus_candidate.FOCUS_RELATIONSHIPS`**, because this value becomes a roster
  fact and the roster's relationship vocabulary is already closed (§D).
* **`birth`** — their birth date, at year grain or finer. Satisfied by the
  entry's own `date` record (§F, the lifehug#207 fix).
* **`living`** — past `complete_at`, exactly as `household` is for residences.
  It is never *demanded*; it is recorded when stated, and it is what makes a
  family member a witness. **`living` is unknown unless stated** — the tri-state
  is real, and `None` never means "dead".

`birth_order` ("two years older", "the middle of five") is stored as a
free-text field alongside `label`/`place`/`subject`, not as a ladder rung: an
unstated birth order must never block the ladder from reaching `birth`.

### The direct year question, permitted for a sibling

`RUNG_TEXTS[("family", "birth")]` is **"What year was {label} born?"** — the
banned move, deliberately permitted, exactly as it is for `birth`.

The research's rule (§2.1) is not "never say the words *what year*"; it is
*never ask for the year of a memory being dated*, because a reconstructed date
invites a rounded, telescoped guess (Friedman 1993; Huttenlocher et al. 1990).
A birth date "is not recalled by reconstruction; it is overlearned semantic
knowledge". **That argument is about the KIND of fact, not about whose fact it
is.** A sibling's birth year is overlearned semantic knowledge in exactly the
same way. §2.9 extends the §2.1 carve-out's citation accordingly.

So the carve-out stops being a hardcoded `!= "birth"` and becomes a named set:

```python
YEAR_OPENER_DOMAINS = frozenset({"birth", "family", "children"})
```

**`children` is included, and that is a bundled fix, not scope creep.**
`RUNG_TEXTS[("children", "year")]` has read `"What year was {label} born?"`
since v199 — the domain's own question already violated the domain's own lint.
It was invisible only because no golden asks a `children` rung. The same
overlearned-semantics argument covers it; leaving it out would leave the module
in contradiction with itself. Declared as deviation 1 (§K).

`landmarks_evals._applicable` mirrors the same set — one definition, two
readers, per the recurring-defect doctrine.

### Walking the constellation

`family` is a `chain`, so `next_rung` walks it forward with
`CHAIN_MORE_TEXTS`. A single fixed "and who else?" would be wrong here: the
chain has **tiers**, and the tier that is missing decides the question.
`CHAIN_MORE_TEXTS["family"]` therefore resolves against the relations already
filed:

| filed so far | the chain-more question |
|---|---|
| nothing | `Who was in your family growing up — brothers and sisters?` |
| siblings only | `And your parents — what were their names?` |
| siblings + parents | `What about your grandparents — do you know their names?` |
| all three tiers | `Anyone else in the family who belongs on this?` |

Implemented as `FAMILY_TIER_TEXTS` consulted by `next_rung` (which is the only
function that holds both the entries and the row); `_rung` stays a pure
formatter.

---

## C. Anchors

`ANCHOR_KINDS["family"] = "landmark"` — a dated point, like `partnerships` and
`children`, and a kind `timeline.anchor_index` already understands.

The key is relation-qualified so two Jameses in different tiers cannot
collide, and so the key reads as what it is:

```
family:sibling-james:birth
```

The owner's sketch wrote `family:brother-james:birth`. **The key says
`sibling`, not `brother`**, because `relation` is closed against
`FOCUS_RELATIONSHIPS` (§B) and `brother` is not a member of that vocabulary —
a second, spoken relationship vocabulary living only in anchor keys is exactly
the duplicate definition the recurring-defect doctrine forbids. Deviation 2.

`_anchor_label("family", label)` → **`"{label} was born"`**, so the anchored
probe renders as the owner's own probe style:

> Bell Avenue — was that before or after James was born?

Keystone leverage counts a family anchor like any other: it enters
`anchor_index` through the same merge, ahead of anything the compiler derived
from a page, and `dependency_index`/`keystones` see it with no change at all.

---

## D. The roster join — one store, existing verbs

**Rule: a person named in the family landmark set reaches the roster as a
PERSON entity carrying the relationship fact. There is no parallel family
store.**

The roster already has the shape for this. `_SETTLED_IDENTITY_FIELDS =
("relationship", "living")` (v190/ADR 0013) are precisely "the settled facts a
roster entry can carry that are NOT re-derivable from a refresh", and
`_has_settled_identity` makes an entry carrying either survive a refresh that
would otherwise drop it. `entity_verdict.apply_verdict(..., relationship=,
living=)` is the verb that writes them.

Two pieces close the gap:

1. **`landmarks_interaction.family_roster_invocations(landmarks)`** — pure,
   package-side, the same "the package names it; the host writes it" split as
   `landmark_invocation`. Returns the `entity-verdict person <slug> clear
   --relationship <r> [--living|--not-living] --ensure` argv for every filed
   family member, deterministic and ordered.

2. **`entity_verdict.apply_verdict(..., ensure=False)`** and CLI `--ensure`.
   Today the verb *raises* when the slug is not on the roster — correct for an
   owner override typed by hand, wrong for a person the landmark set just
   learned about, who by construction may have zero mentions yet. With
   `ensure`, an absent slug is **created** as:

   ```python
   {"name": name, "slug": slug, "aliases": [], "qualifies": False,
    "score": 0.0, "unique_answers": 0, "page_eligible": False,
    "source": "landmark:family"}
   ```

   **`qualifies` and `page_eligible` are False on purpose.** ADR 0013 put a
   ≥1-mention floor on graduated pages; a brother named once in an intake
   answer has not earned a wiki page and must not get one. The entry exists to
   hold the identity facts durably from day one, and
   `entity_roster.apply_previous_decisions` folds it into the real entry by
   name/alias the moment the person is actually mentioned in answers. Nothing
   about page eligibility changes.

   `ensure` is idempotent: re-running the identical invocation converges to
   identical roster bytes, which is the property `apply_verdict` already
   guarantees.

### Witnesses

`landmarks_interaction.witness_candidates(landmarks)` → the family members
whose `living` is **explicitly `True`**, as
`{slug, name, relation, can_supply}` rows.

`can_supply` is `("residences", "schools")` for every tier — the two closed
lists §2.7 argues a second person can supply completely. That claim is flagged
in the research as **a design premise, not a finding** ("is *not* measured
anywhere we have found"), and this contract does not upgrade it.

Surfaced as `timeline_data()["witnesses"]`. The v200 `place_no_stories`
`witnesses` field, sourced from the `household` rung, is **left exactly as
is** — it names who was in *that house*, which is a narrower and better claim
than "a living relative"; folding the two would lose that.

---

## E. Rulings 4 and 5 — concrete unknowns from the landmark set

Two new unknown kinds. `UNKNOWN_KINDS` becomes:

```
moment · period_bound · place_span · era_gap · date_contradiction
      · landmark_subject · residence_gap
```

### `landmark_subject` (ruling 4)

`landmarks_interaction.incomplete_subjects(landmarks)` → one row per filed
entry that is **below its domain's `complete_at`**, in every **enumeration
domain**.

*Enumeration domain* is defined as **`chain: true`** — family, residences,
schools, work — rather than a hand-written list of three. A hand-written list
is the second definition of "which domains enumerate", and `chain` already
means exactly that.

```python
{"kind": "landmark_subject",
 "key": "landmark_subject:family:jackie",
 "label": "Jackie",
 "domain": "family",
 "rung": "birth",
 "landmark": {"domain": "family", "label": "Jackie"},
 "probe": {"step": "landmark", "cost": <LADDER_COST[rung]>,
           "text": "What year was Jackie born?"}}
```

The `text` is `next_rung`'s own subject-named rendering for that entry — one
definition of "the next question for this subject", read by both the domain
row's `next` and by the unknown.

### `residence_gap` (ruling 5)

`landmarks_interaction.residence_gaps(landmarks)` → one row per **interior**
hole between two consecutive dated residence spans:

```python
{"kind": "residence_gap",
 "key": "residence_gap:mesa:yucaipa",
 "label": "between Mesa and Yucaipa",
 "between": ["Mesa", "Yucaipa"],
 "years": ["1992", "1995"],
 "probe": {"step": "residence", "cost": 2,
           "text": "Where did you live between Mesa and Yucaipa, "
                   "around 1992–1995?"}}
```

Rules:

* **Interior only.** No gap is minted before the first residence or after the
  last one. A trailing "and since 2019?" is a nag, and a leading one asks
  about infancy.
* **A hole needs a whole year in it.** Two spans that abut, overlap, or are
  one year apart mint nothing — `end_year + 1 >= start_year` is not a hole.
* **The years are REPORTED, not proposed.** The text states the interval the
  person's own spans imply and asks what filled it; it never names a date and
  invites agreement (`timeline_interaction.proposes_a_date` scores every
  golden, unconditionally).
* **It is not `era_gap`.** `era_gap` is a hole between two dated wiki
  *periods*; this is a hole in the residence *chain*, from the landmark store,
  and the chain is the thing that is supposed to tile (§2.7 consequence 1).
  Both may surface for the same years; they are different questions with
  different answers and neither is derivable from the other.

### Wiring, and the one-line guard that makes it possible

`timeline.unknowns(data, landmarks=None)` gains the optional store, passed by
`timeline_data` (which already reads it once, before the `unknowns()` call).
Guarded — a landmark problem never takes the timeline down.

`unknowns()` ends with `for row in rows: row["probe"] =
choose_probe(row, ...)`, which would overwrite the exact, subject-named
question these rows arrive with. The guard:

```python
for row in rows:
    probe = row.get("probe")
    if isinstance(probe, dict) and str(probe.get("text") or "").strip():
        continue          # the row brought its own exact question
    row["probe"] = timeline_interaction.choose_probe(row, anchors=anchors)
```

Byte-identical for every pre-existing row (none of them carried a probe
before this line ran), and it is what lets a landmark-derived unknown keep the
ladder's own wording instead of a generic opener. It also means
`KIND_OPENERS` needs no entry for either new kind — one mechanism, not two.

**Calibration, stated plainly.** A `landmark_subject` has **leverage 0** in
`dependency_index`, and that is honest rather than a gap: it is an unknown that
is *itself a future anchor*. Its leverage is realized the moment it is
answered, when `anchors_from_landmarks` mints the anchor and every dependent
unknown's count moves. On the page and in the plan these rows therefore order
by probe cost — the cheapest ladder rung first — which is the ordering
`open_landmarks` already uses for landmarks. No fabricated resolve set is
invented to make the number look better.

---

## F. lifehug#207, fixed here because it is trivial and load-bearing

`rung_reached` counts a rung only under that rung's own key, with a single
`date` fallback for `span`. So `{"domain": "birth", "date": {…day…}}` — which
is what the package's own CLI and turn writers produce — leaves `birth`
`partial` with `next = year` forever (found live on the platform,
lifehug-platform#613).

The family domain hits the identical wall: its `birth` rung is satisfied by
the entry's `date`, not by a `birth` key. Fixing it is ~8 lines and the family
ladder does not work without it, so it lands here — **as its own commit**, and
it closes lifehug#207.

```python
#: Rungs a DateRecord satisfies directly, and the granularity each needs.
_DATE_GRAIN_RUNGS = {"birth": 1, "year": 1, "month": 2, "day": 3}
_GRAIN_RANK = {"year": 1, "month": 2, "day": 3}
```

A rung in `_DATE_GRAIN_RUNGS` with no key of its own is satisfied when the
entry's `date` resolves at least that grain. Season, range and era
granularities rank 0 and fill nothing — a coarse date is still an answer, it
just does not claim a month. `partnerships`/`children`'s `year`/`month` rungs
get the same fix for free, which is the point.

The platform's read-side stopgap (`BOUND_DATA_NORMALIZERS`,
lifehug-platform#613) comes out at the pin that carries this.

---

## G. Behavior, lints, goldens

`interactions/landmarks/prompt/behavior.md` gains **"The family you came
from"** (and its verbatim handbook embed moves with it —
`tests/test_handbook_parity.py::EmbedParityTests`):

* the constellation is people, and people get named, not counted;
* a sibling's birth year may be asked outright — the one place besides the
  person's own birthday where that is true;
* an elder who has died is received, and the conversation does not turn into
  condolence or into a dating opportunity;
* `living` is never *asked as a status question*. It arrives in what they say.

No new lint class. The five `landmark_gates.*` plus `never_proposes_a_date`
already cover everything the family domain can do wrong, and the sixth would be
a second definition of pressure. `no_year_demand`'s carve-out widens per §B.

**Goldens** — six new, `landmarks-evals` gates unchanged at 1.0:

| Golden | What it pins |
|---|---|
| `landmarks-family-opening` | the generality opener; brothers and sisters, not a form |
| `landmarks-family-sibling-interval` | "he's two years older" → the arithmetic REPORTED from their own birth year, never offered for agreement |
| `landmarks-family-elder-gently` | a grandparent who has died: received, `living: false`, not pressed |
| `landmarks-family-decline-respected` | "I'd rather not" ends the domain and is never retried |
| `landmarks-family-named-follow-up` | "four or five, I don't remember when Jackie was born" → accepted whole, and Jackie's year becomes a NAMED unknown (ruling 4) |
| `landmarks-residence-gap-is-a-question` | five of seven addresses accepted; the holes become `residence_gap` questions, nothing nags (ruling 5) |

---

## H. Test plan (`tests/test_landmarks.py`)

* **QuestionSet** — nine domains in order; `family` is second, a chain, and
  onboarding; every `(family, rung)` pair has a question; the existing order
  assertions move by one.
* **Ladder** — a sibling with a name only sits at `who`; `relation` then
  `birth`; the `next` for a half-filled entry NAMES it; the tier walk
  siblings → parents → grandparents.
* **Anchors** — `family:sibling-james:birth` minted from a filed sibling;
  the anchor label reads "James was born"; a family anchor reaches
  `anchor_index` and a keystone count moves.
* **Roster join** — `family_roster_invocations` argv; `apply_verdict(...,
  ensure=True)` creates a non-eligible entry with the identity facts, is
  idempotent, and still raises without `ensure`; `_has_settled_identity` is
  true for the created row.
* **Witnesses** — only explicit `living: True` qualifies; `living: None` is
  not a witness and not a non-witness.
* **Ruling 4** — `incomplete_subjects` over family + residences + schools;
  one row per incomplete subject; the probe text equals `next_rung`'s;
  complete subjects mint nothing.
* **Ruling 5** — `residence_gaps` over a 5-of-7 chain; abutting and
  one-year-apart spans mint nothing; no leading/trailing gap; the text
  reports and does not propose (scored through `proposes_a_date`).
* **Wiring** — both kinds appear in `timeline_data()["unknowns"]`; their
  probes survive `choose_probe`; every other row's probe is unchanged.
* **lifehug#207** — a day-grain `date` satisfies `year`/`month`/`day`; a
  year-grain date satisfies `year` and stops; a season/era date fills none.
* **Contract byte-identity** — the v199 test that the output-contract
  appendix does not move without `landmark_stage` still passes untouched.

---

## I. Gates

* `python3 -m pytest tests/` — full suite.
* `python3 system/lifehug.py landmarks-evals --json` — all six lint seats.
* `python3 system/lifehug.py timeline-evals --json` — unchanged.
* `python3 -m pytest tests/test_handbook_parity.py` — embeds + parity numbers.
* `python3 scripts/ci/check_framework_files.py`.
* `system/version.json` 201 → 202.

## J. Docs

`system/research/landmarks.md` §2.9 (new) + §2.1 amendment + §1.9 table row +
Sources · `docs/handbook/glossary.md` (Family under Landmarks) ·
`docs/handbook/timeline.md` · `docs/handbook/interactions/landmarks.md`
(domain table, behavior embed, the two new unknown kinds) · `README.md`
nomenclature line · the Platform-twin table below.

---

## K. Deviations

1. **`children` joins the year-opener carve-out** alongside `family`. The
   owner authorized extending the exception to siblings; `children`'s own
   v199 rung text already asked "What year was {label} born?" and therefore
   already violated its own lint. Same argument, same fix, declared here.
2. **The anchor key says `sibling`, not `brother`** — see §C.
3. **lifehug#207 is fixed in this PR**, in its own commit, because the family
   `birth` rung does not function without it (§F). The task allowed this only
   if trivial; it is ~8 lines and one table.
4. **Enumeration domains are `chain: true`**, not the literal list "family,
   residences, schools" the ruling named — `work` is a chain too and behaves
   identically, and a second hand-maintained list of enumerating domains is
   the duplicate definition the recurring-defect doctrine forbids.
5. **`landmark_subject` rows carry leverage 0** rather than a synthesized
   resolve set (§E, calibration).
6. **Two more rung texts were rewritten sideways.** Auditing §B's carve-out
   surfaced the same defect twice more: `("partnerships", "year")` read
   *"Roughly what year did that begin?"* and `("losses", "year")` read *"What
   year was that?"* — both demanding a year for a **reconstructed memory**,
   which is the move the lint exists to stop, in a domain with no carve-out.
   They are now *"Roughly when did that begin?"* and *"Roughly when was that?"*.
   Three instances of one defect class is exactly what the recurring-defect
   doctrine says to stop patching one at a time, so the invariant is now a test:
   `test_every_domains_own_rung_text_survives_its_own_lints` renders every
   `RUNG_TEXTS` entry and scores it through that domain's own lints.
7. **`DOMAIN_RUNG_COST`.** `who` costs 2 as a *follow-up* rung (partnerships,
   children, losses) but it is `family`'s *opener*, and every other domain's
   opener costs 1. Without a one-entry override the family row sorts behind the
   residence chain in `open_landmarks` and `build_landmarks_plan`, which
   inverts §A.1 — the reason the domain exists is that it is the cheapest
   anchor per question in the set.

---

## L. Platform twin (lifehug/lifehug-platform)

**Verified against the platform checkout, not assumed.**

**The landmark ROW rendering needs zero changes**, as the task asked me to
check. `services/api/app/reflect/derive.py` takes
`landmarks=_list_of_objects(timeline.get("landmarks"))` — untyped objects,
whole; `reflect/models.py:landmarks` is `tuple[JsonObject, ...]`;
`apps/web/lib/reflect-view.ts` passes `data.landmarks` straight through; and
`TimelineClient.tsx` iterates `rows(data.landmarks)` reading only `status`,
`next.text`, `keystone` and `leverage`. A ninth domain row is data, and it
renders on arrival. The projection-compat rule holds too: the row gains no
required field.

What *does* need platform work at the pin bump:

| Package change | Kind | Host action |
| --- | --- | --- |
| `landmark-record --relation`, `--birth-order`, `--living` / `--not-living` | **new flags** | `_LANDMARK_FIELDS` in `services/api/app/vault_mutation/review_action.py` is a CLOSED allowlist and `landmark_fields_from_invocation` RAISES on an unknown flag **by design** ("a pin that grows a flag has to fail here rather than in the vault"). Add the three; `--living`/`--not-living` is a bool pair, so it needs the `_LANDMARK_COMPLETE`-style branch, not the value-pair branch |
| `UNKNOWN_KINDS` += `landmark_subject`, `residence_gap` | **new vocabulary** | the Unknowns lane renders them like any other subject row; both arrive with their own `probe.text` |
| `timeline_data()["witnesses"]` | **new projected key** | additive-with-default in the reflect envelope (the #463/#467 rule: a REQUIRED field added to a stored envelope 500s live) |
| `entity_verdict --ensure` | **new flag** | only needed when the platform runs the roster join; the Review lane's existing entity-verdict transport is unaffected |
| `rung_reached` date-grain fix (lifehug#207) | **behavior fix** | **remove** `BOUND_DATA_NORMALIZERS` (lifehug-platform#613's read-side stopgap) at this pin |
| `family` domain in `questions.yaml` | **vendored data** | `services/worker/vendor/lifehug_pkg/` refresh; no new module file, so `image_paths.py`'s classified-file guard is untouched |
