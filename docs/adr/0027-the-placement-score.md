# ADR 0027: The placement score — the level and its margin, one arithmetic

Date: 2026-08-24
Status: proposed

## Context

The owner asked for two numbers and they turned out to be one.

The first is the **level**: *how placed is this life, 0 → 1*. The second he
already has — the **margin**, the star's *"one answer would place 53 things"*
(`keystones`, v196; delivered for real since ADR 0026). Issue #637's finding is
that these are not two features. `timeline.unknown_width` has ranked the
Reading Room's plan on **interval width** since v204, precisely because a
threshold count is not submodular and a width-sum is
(`system/research/go-deep.md` §8.4, warning 3). The level is that same width
sum, normalised. Building them apart would repeat the promise/delivery drift
the dating-dataflow audit found once already, where `dependency_index` counted
what an anchor *touched* and no pass could deliver any of it.

The research review that grounds this is `system/research/chronology-vis.md`
(v206), and it is unusually blunt about how a score like this goes wrong. A
completion meter — *does this field have a value?* — is an **improper scoring
rule** in Gneiting & Raftery's precise sense: it is maximised by writing
anything down at all, true or not (§4.6). Marginal interval-width sums
**overestimate** disorder wherever ordering constraints exist, by 3× in
Mountakis, Klos & Witteveen's worked case (§4.4). And surrogation is a measured
finding, not an adage: people treat a single measure as the construct itself,
and the effect is *weaker* when several measures are shown together (Choi,
Hecht & Tayler, §4.5).

So the decision is not "add a percentage." It is: which arithmetic, stated
with which caveats, in which places, so that the number cannot lie and cannot
be gamed.

## Decision

**One derivation-time function, `timeline.placement_score(data)`, computes the
level; the margin comes out of the same call.** Pure, stateless, recomputed on
every read, additive-with-default, and wrapped in the guarded try every derived
block in `timeline_data()` already uses — a scoring problem must never take the
timeline down. **No visual ships with it.** The number is a payload field and
hosts render it.

### 1. Score the width, never the presence

`score = 1 − Σwᵢ / (n · L)` over every **thing** the timeline holds — placed
moments, unplaced moments, eras, and the place spans inside the bands (one
enumeration, `_scored_things`, shared with the tests so "what is scored" can
never become two lists). `wᵢ` is the width **in years** of the interval that
thing currently occupies: its own where it is dated, `unknown_years`' where it
is not. `L` is the life span; `n` is the thing count.

This is **Goodhart-safe by construction**. The elicitation ladder stores a
hedge as a *wider* interval with a weaker confidence (`chronology.from_age`,
`widen_for_elapsed`, and the never-propose-a-date lint above them), so
guessing does not pay — the guess is not stored as a point. A presence meter
would be maximised by filling the field; a width score is maximised only by
knowing more.

Rejected: counting how many things carry a date (improper, §4.6), and
scoring per-era completeness (needs a denominator that does not exist, §4.2).

### 2. The number is a FLOOR, and the copy says so

`caveat_floor` is `True` and stays `True`. A marginal width sum measures the
smallest hypercube containing the feasible region, so a well-ordered but
loosely-bounded life reads as more disorganised than it is (§4.4). The field
name and every rendering of it must say *at least this organised*, never
*exactly*. The concurrent-flexibility correction (Mountakis et al.'s
bipartite-matching reduction, O(n³)) is known, is not free, and is **not this
change**; it stays the named follow-up in `system/research/QUEUE.md`.

### 3. Stated and derived are a pair

`score_stated` recomputes the same sum with every **derived** record read as
undated — the marker being `date_derived` and nothing else (ADR 0026). This is
Bayliss's italic convention (§1.5) expressed as two numbers, and it is the
Goodhart guard's display half: the pass cannot flatter the person's own work.

**The pass moves `score` and cannot move `score_stated` — pinned by test.**
Making that true required two things beyond the obvious one. First, on the
stated basis anything the person did not state is *unplaced*, so an **undated**
thing is read against the stated view too — otherwise an undated moment
inherits the era span the pass just derived. Second, a band place's envelope
span (`_place_span` → `cross_dating.span_from_dated`) now carries the
`date_derived` marker it always should have carried; without it the pair reads
an envelope the pass produced as something the person stated.

### 4. Words: placement, and only ever placement

Never "completeness", never "accuracy", never a verdict on the life.
Completeness is contextual rather than intrinsic (§4.1) and the denominator
does not exist (§4.2); the score is scoped to *what the timeline can order and
place*, and to nothing else. A model can be wrong and green (§1.5) — sharpness
subject to calibration is all we can measure, and we can only measure the
sharpness half.

### 5. Band it; never render a bare percentage

`band` is `1..5` on fixed thresholds (`PLACEMENT_BANDS = 0.2/0.4/0.6/0.8`),
Recoin-style: arbitrary but **stable**, documented as such, and never
peer-relative — there are no peers in a private vault (§4.3). The surrogation
result (§4.5) is why the chip is banded and sits beside other readings rather
than becoming the timeline's headline.

### 6. The strip is aoristic, and it is what answers Crema

`per_year_band` gives one row per calendar year of the life. Each thing
contributes `min(1, 1/wᵢ)` to every year its interval covers, normalised by
how many things cover that year — Ratcliffe & McCullagh's aoristic weight with
a uniform prior (§2.1). A day-pinned thing contributes ~1 to its year; a
decade-wide thing ~0.1 to each of ten.

This is the half that answers **Crema's summation problem** (§2.2): five
moments smeared over five blocks and five moments pinned inside those blocks
produce the *identical* summed vector, and aoristic summation alone "does not
distinguish between the two scenarios." The strip does, and the golden that
pins it is the load-bearing test of this ADR.

An empty year emits `0` rather than being left out — a flat stretch means
nobody asked, which is coverage, not biography (§1.4, design consequence 16).

### 7. The level and the margin must share one arithmetic — standing rule

`next_gain` is the top row of the **existing** greedy plan (`keystones(data, 1)`),
re-expressed in score units: the level recomputed with that anchor's resolve
set collapsed to the anchor's own grain, minus the level now. It re-runs the
same `_level` over a copied population — the promise-equals-delivery discipline
`cross_dating.gain_sentence_for_record` (v207) already applies to the filing
sentence, applied here to the number.

**The anchor's grain is one year** (`ANCHOR_GRAIN_YEARS`). Every rung of the
ladder ends at a year-or-finer claim, and the year is the unit the score is
measured in, so a finer answer over-delivers and never under-delivers — which
keeps the margin a floor exactly as the level is one. `count` is the moments
the resolve set holds, because moments are what dating an anchor actually
dates; the star's own `leverage` is unchanged and remains the whole set.

`keystones()` itself is **untouched**. Its greedy-residual `gain` is a
different and already-correct number: row `leverage` is display reach, keystone
`gain` is marginal plan value.

### 8. No birth landmark, no score

`placement_score` returns `None` when no birth landmark exists, and the block
is simply absent from the payload. Without a birthday there is no `L`, no floor
for a thing nothing can bound, and no honest denominator. That is correct, and
it is why `birth` wears the ★.

### 9. The ghost is reconstructed, never stored

Every dated moment gains `prior_span` — what `unknown_years` would return for
it *absent its date* — stamped by the cross-dating pass's own walk, so stated
and derived moments alike carry it. It is omitted where the reconstruction is
not wider than the moment's own interval (nothing to ghost).

The honest note, which the handbook repeats: after an era's own dates improve,
old ghosts **tighten** on the next read. The ghost shows today's honest
reconstruction of *before*, not a historical screenshot. That is the stateless
trade (dating-dataflow rule 1: no state), and it is stated plainly rather than
fixed by storing history.

## Consequences

- **Binds:** the level and the margin share ONE arithmetic. A future
  "completion" number computed anywhere else, by any other rule, is this ADR's
  exact failure case.
- **Binds:** `unknown_years` is the ONE definition of the interval a thing
  occupies absent an answer, and it has three consumers — the score's
  per-thing width, the chart's cloud dot and tap-span, and the ghost's prior
  span. A host that draws a cloud dot from a different interval than the score
  counted has reintroduced the drift.
- **Binds:** the score is **downstream of the never-propose-a-date lint and
  does not police itself** (§4.6). It is honest only while
  `timeline_interaction.proposes_a_date` holds.
- **Forecloses:** a stored score, a score-repair job, a peer-relative band, and
  any rendering of a bare continuous percentage as a verdict.
- **Forecloses:** scoring presence. If a later change wants to reward "this
  field has a value", it must supersede this ADR and answer §4.6 first.
- **Open, deliberately:** the concurrent-flexibility correction (§4.4) is
  queued, not built; until it lands `caveat_floor` is `True` unconditionally.
  The glow's RANKING (rank-quantiles over `leverage`) is the host's job — the
  package supplies honest per-row numbers and does no ranking.

## Platform twin — additions

| payload field | new? | platform use |
|---|---|---|
| `placement` block | new | eye pane: chip (`band`), % (`score`), pair (`score_stated`), caveat copy; band strip (`per_year_band`) |
| `counts.placement_band` | new | nothing at v1 (future promotion) |
| `unknowns[].years` | new | cloud dot x + tap-span |
| `unknowns[].leverage` / `.resolves` | new | glow rank-quantiles; constellation highlight |
| `event_lineup[…][].prior_span` | new | the 4A ghost |
| `event_lineup[…][].date.{earliest,latest,granularity,basis}` + `date_derived` | existing | mark x, whisker, hue |
| `bands[].date` / `periods[].date` | existing | era zoom spans, band x-ranges |
| `keystones[0]` | existing | the ★ halo (rank-1 identity check) |

All new fields are additive; the platform's `TimelineData` gains `placement`
(default `{}`) only — every other addition rides existing `JsonObject` rows.
