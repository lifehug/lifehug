# What a life portrait holds: the target table

*Research note and decision (v377, 2026-09-29). Every claim is sourced or
marked as the owner's ruling; what could not be obtained says so. Builds on
`system/research/graph-vis.md` (branch `research-graph-vis`, PR #435, not
merged — cited here by section and design-consequence number) and
[issue #434](https://github.com/lifehug/lifehug/issues/434).*

---

## 0. The question

The graph draws each entity as a filled circle (what has been told) inside a
ring (what a well-told life holds for that entity). v376 made every entity
reach its page and every relationship reach its two ends. What it did not
decide is **the ring**: how big should the target be for a parent, a sister,
a home, a job, a theme?

The owner's rulings (2026-09-29) fix the frame:

> "The ring means TARGET: every entity gets a target size; research what each
> entity type/relation contributes to a life story, decide the table,
> DOCUMENT it (so it can be revisited), and execute."
> — owner, 2026-09-29, relayed with the task for this note

> "I'm sure we're going to adjust all these as we go, so design them in a way
> that they're adjustable, more configurable, as we discover how this works."
> — owner, 2026-09-29

And graph-vis already constrains the answer:

- **D4.** Ideal radii are an owner table by type and relation — not learned
  from citation counts (graph-vis §4.2, §9).
- **D5.** Compare a node with peers of its type (graph-vis §4.3, via
  chronology-vis §4.3 and Wikidata Recoin).
- **D7.** There is no cross-type balance metric, and the graph must not
  invent one by summing radii (graph-vis §4.5).

The owner's only examples on record are in issue #434 §2 (quoted in
graph-vis §4.2): *sisters equal to each other, and large; parents larger
still; grandparents slightly smaller than parents; jobs smaller.*

This note asks what biography, oral-history, life-story and life-review
practice say about who and what belongs in a well-told life and in what
proportion (§1–§3), maps that onto the vault's own vocabulary (§4), and
**decides the table** (§5), the credit relevance gate (§6), and how an owner
changes a number (§7).

---

## 1. Relationship-centred evidence

### 1.1 The cultural life script: marriage and children dominate

Berntsen & Rubin (2004) asked people to name the seven most important
events likely in the life of a newborn — the *cultural life script*.
Janssen & Rubin (2011, full text obtained) describe the method:

> "Berntsen and Rubin (2004) examined the cultural life script by asking
> undergraduates to imagine an ordinary infant and to name the seven most
> important events that were likely to take place in the life of this
> prototypical newborn baby." (p. 291)

Zaragoza Scherman (2013, accepted manuscript, full text obtained) tabulates
Berntsen & Rubin 2004 beside six replications (N = 1,172 in all):

> "The three most popular events are: having children, getting married, and
> beginning school."

| Event (combined across 7 studies) | % of participants naming it |
|---|---|
| Having children | 76.28 |
| Getting married | 64.16 |
| Beginning school | 62.29 |
| Fall in love | 37.63 |
| College | 32.34 |
| Parents' death | 31.06 |
| First job | 29.27 |
| Retirement | 17.58 |
| Leave home | 15.87 |
| Grandchildren | 9.90 |
| Meeting spouse | 8.45 |
| Siblings | 7.51 |
| Grandparents' death | 5.46 (one study) |

*Source: Zaragoza Scherman 2013, Table 1, last column. Berntsen & Rubin
2004 itself was **not obtained**; these figures are its replications'
reanalysis.*

Two cautions come with the table, from the same authors:

> "Life scripts do not represent an average life, but represent an
> idealized life from which many common and some important events are left
> out." … "Life scripts are distorted from actual lives to favour positive
> events." (Janssen & Rubin 2011, p. 291–292)

> "There is a large overlap between the life scripts and life stories of
> young adults … and there is an even larger overlap between the life
> scripts and life stories of older adults." (Janssen & Rubin 2011, p. 292)

So the script counts **events expected in anyone's life**, not narrative
space in one person's story — but its authors report that told life stories
overlap with it, more so with age.

### 1.2 Close relations first

Atkinson's chapter on the life story interview (2002, full text obtained)
singles out two relations as the exemplary close ones:

> "…how meaningful it has been for them to have done particular interviews,
> especially those with individuals they were already close to, such as
> parents or spouses." (p. 127)

> "Life themes also highlight important influences and relationships."
> (p. 127)

The Smithsonian's folklife interviewing guide (full text obtained) opens its
practice with the nearest relation: "If possible, try to conduct your first
interview with someone with whom you feel very comfortable, such as a
relative or a neighbor." (p. 4)

### 1.3 Convoys and layers (secondary only)

Kahn & Antonucci's (1980) *convoy* model places a person inside three
concentric circles: an inner circle of the closest, most permanent ties
(spouse, children), a middle circle (close friends, some relatives), an outer
circle of role-based ties (colleagues, neighbours). Dunbar's layers (~5, ~15,
~50, ~150 people, with depth falling at each ring) have the same shape.
**Neither primary text was obtained**; both are described here from later
summaries and carry no quotation. They are cited only as a structural
pattern: a small inner circle carries most of the weight.

### 1.4 Where the life-story interview puts people

McAdams' Life Story Interview II (2007, full protocol obtained) organises a
life into "between about 2 and 7" chapters, eight key scenes (high point, low
point, turning point, positive and negative childhood memories, a vivid adult
memory, a spiritual experience, a wisdom event), challenges including "the
loss of important people in your life", a future script, and a central
theme:

> "I will ask you to focus on a few key things in your life – a few key
> scenes, characters, and ideas."

It has **no separate roster of significant people**: people enter through
scenes. This matters for §6 — telling about a person is telling *in which
that person is a subject*.

---

## 2. Domain-centred evidence

A second tradition spreads the weight across a few co-equal domains rather
than concentrating it on a few people.

- **Guided Autobiography** (Birren & Deutchman 1991): the themes are
  branching points, family, money, work and career, health and body,
  sexual identity, death and dying, spiritual life, goals — family and work
  as two themes among eight or nine. **The book was not obtained**; the list
  is reconstructed from two secondary pages that disagree on the exact count.
- **Haight's Life Review and Experiencing Form**: sections for childhood,
  adolescence, family and home, adulthood and a closing summary, with the
  summary the largest section. **Not obtained**; the section list and item
  counts (13 / 14 / 8 / 11 / 17) come from a secondary summary and are
  approximate. Read as reported, nearly half the form is childhood and
  adolescence, and a quarter is evaluation — life review weights the early
  years and the meaning, not the adult decades by length.
- **Oral-history practice** treats a place, an era, an organisation or an
  occupation as a legitimate focus in its own right. Baylor's workshop manual
  (full text obtained): "A topical focus highlights a single subject of
  historical interest, such as an event, a time era, an issue or idea, an
  organization, a place, a skill or occupation." (p. 8) The Smithsonian guide
  places memory "in families, neighborhoods, workplaces, and schools" (p. 2).
- **Popular question lists** (StoryCorps "Great Questions", full page
  obtained) are grouped by relation and domain — parents, grandparents,
  growing up, marriage and partnerships, working, family heritage — with no
  proportion attached.

---

## 3. What no source says

- **No obtained source gives a numeric proportion** for how much of a told
  life a parent, a sibling, a home or a job should hold. The closest
  quantitative proxy is §1.1, and it counts expected events, not narrative
  space.
- The field's own quality criterion is **coherence, not cast**: Habermas &
  Bluck (2000; abstract only) define the life story by "4 types of global
  coherence (temporal, biographical, causal, and thematic)". A weight table
  is an organising device for the graph, not the literature's definition of
  a well-told life.
- The two traditions (§1 people-centred, §2 domain-centred) are only partly
  reconcilable. The vault already has both: people and relationships on one
  side, periods, places, projects and themes on the other. D5 keeps them
  apart — each type is compared with itself.
- On siblings and grandparents the evidence and the owner disagree: the life
  script ranks them low (siblings 7.5%, grandparents' death 5.5%), the owner
  says sisters are "large" and grandparents "slightly smaller than parents".
  **D4 makes the owner's word the table**; this note records the
  disagreement so a later revision can weigh it.

---

## 4. The vault's vocabulary

The graph compares entities by **type** (the wiki folder) and by **kind**
within a type. Each kind must be something the vault already records —
nothing here asks the owner a new question.

| Type (wiki folder) | Kind, and where it is read from |
|---|---|
| person (`people/`) | the relation, in order: the Focus's `relationship` (roadmap, `focus-set --relationship`); the roster entry's `relationship` (`entity-verdict --relationship`); the classifier's relation words for that person across current classifications, mapped through `roster_relations.roster_relationship_for` (mother → parent, wife → spouse, brother → sibling, …) by majority. The vocabulary is `focus_candidate.FOCUS_RELATIONSHIPS`: parent, grandparent, child, sibling, spouse, partner, friend, colleague, mentor, other; `unknown` when nothing says. The owner's own person page is `owner`. |
| relationship (`relationships/`) | the relation of its non-owner end, as above |
| place (`places/`) | `residence` when a landmark residence (`state/landmarks.json`) or the roster's `place_kind` names it; `school` / `workplace` when a landmark school or job names it; else the roster `place_kind`, else the classifier's place `type` by majority (city, building, region, country, neighborhood, other) |
| period (`periods/`) | `age_frame` for the calculated frames (Childhood, My Teens, My 20s …, ADR 0030); `job` when a landmark job names it; else `era` (a named era: College, the Mission) |
| project (`projects/`), life's work (`lifes_work/`) | one kind each |
| life (`life/`) | `hub` (the owner's self-portrait, v376 `A_PRIMARY_FOCUS_IS_THE_HUB`) or `arc` (an A–E chapter page) |
| theme, object, self | one kind each |

The Focus **tier** (`basic` / `standard` / `extreme`, roadmap) is the owner's
statement that an entity deserves more depth; an entity that is not a Focus
has tier `none`.

---

## 5. Decision: the target table

**Status: decided, owner rulings of 2026-09-29 applied. Implemented in the
next release (v378) as `system/portrait_targets.json`.**

### 5.1 How a target is built

For every entity *e* of type *T*:

```
target(e) = weight(T, kind(e)) × tier_multiplier(tier(e)) × scale(T)
told(e)   = credit(e)                         (§6)
gap(e)    = max(0, 1 − told(e) / target(e))
```

`scale(T)` puts the table on the credit scale, per type (D5): it is the
`calibration.quantile` of `credit / (weight × tier)` over the type's credited
members, so at quantile 1.0 **the best-told member of each type sits exactly
on its target** and the rest are measured against it. A type with fewer than
`calibration.min_peers` credited members borrows the median scale of the
types that have enough. The owner's own person page is not calibrated on (it
duplicates the hub and would set every person's scale). Nothing is summed
across types (D7); the ring and the fill share one radius scale so a
parent's ring and a home's ring can be read on one canvas, which is the table
(D4), not a balance metric.

Weights compare only within a type: a theme at 1.0 and a parent at 1.0 are
not "equal", they are each the top of their own type.

*Amended 2026-09-30 (v380): calibration is now ONE scale for the whole
portrait, anchored on people, with a `type_scale` per type — see "Amendment
2026-09-30 — one scale" below. Per-type calibration is `calibration.mode:
per_type`.*

### 5.2 People and relationships

| Kind | Weight | Rationale |
|---|---|---|
| spouse | 1.0 | Marriage is the second most-named life-script event (64%, §1.1); Atkinson's exemplary close relation (§1.2). |
| partner | 1.0 | The same bond without the word; the life script's "fall in love" (38%). |
| parent | 1.0 | Owner: parents are "larger still" than siblings (#434 §2). Atkinson's other exemplary relation; "parents' death" 31% (§1.1). |
| child | 1.0 | "Having children" is the most-named life-script event (76%, §1.1); the convoy's inner circle (§1.3). |
| grandparent | 0.85 | Owner: "slightly smaller than parents". The life script would put it far lower (5.5%, §3); owner's word governs (D4). |
| sibling | 0.8 | Owner: "equal to each other, and large", below parents. Life script: 7.5% (§3). |
| friend | 0.5 | The convoy's middle circle (§1.3). |
| mentor | 0.45 | A middle-circle tie with a named role; just under a friend because it is often bounded to one period. |
| colleague | 0.3 | The convoy's outer, role-based circle (§1.3); the owner's "jobs are smaller". |
| other | 0.25 | Aunts, cousins, in-laws — the owner's ruling puts them outside immediate family (`axis_membership.DISTANT_RELATIONSHIPS`). |
| unknown | 0.3 | No relation recorded yet: a little above `other`, because an unrecorded relation is as often close as distant. |
| owner (person page only) | 1.0 | The owner's own person page; excluded from calibration (§5.1). |

A relationship edge uses the same weights for the relation of its other end
(no `owner` row).

### 5.3 Places

| Kind | Weight | Rationale |
|---|---|---|
| residence | 1.0 | Homes are the landmark skeleton (`interactions/landmarks`); life review's "family and home" section (§2). |
| school | 0.8 | "Beginning school" 62% and "college" 32% in the life script (§1.1); schools are a named oral-history setting (§2). |
| workplace | 0.7 | "First job" 29% (§1.1); owner: jobs are smaller than family. |
| city | 0.6 | A place lived in or through, but not a home by itself. |
| neighborhood, building | 0.5 | Settings of scenes; smaller than the city they sit in. |
| region, other | 0.4 | Broad or unclassified settings. |
| country | 0.3 | The widest frame; usually background. |

### 5.4 Periods, projects, life, themes, objects, self

| Type · kind | Weight | Rationale |
|---|---|---|
| period · era | 1.0 | A named era is one the owner chose to name (ADR 0030) — McAdams' "chapters" (§1.4). |
| period · age_frame | 0.8 | Calculated frames every life has; life review weights the early ones heavily (§2), but they are a grid, not the owner's own chapters. |
| period · job | 0.6 | Owner: jobs are smaller. |
| project · project | 1.0 | One kind: projects compare among themselves. |
| lifes_work · lifes_work | 1.0 | One kind. |
| life · hub | 1.0 | The self-portrait. |
| life · arc | 0.6 | An A–E chapter: part of the hub's story, so smaller than the hub it feeds. |
| theme, object, self | 1.0 | One kind each: each compares only with its own type. |

### 5.5 Tier multipliers

| Tier | Multiplier | Rationale |
|---|---|---|
| none | 1.0 | Not a Focus: the table alone. |
| basic | 1.25 | A Focus says "tell me more" — a quarter more. |
| standard | 1.5 | Half again. |
| extreme | 2.0 | The primary life story and book-sized Focuses: double. |

The multipliers are deliberately gentler than `roadmap.TIER_TARGETS`
(8 / 20 / 50 answers): those are question counts for the planner, this is a
radius on a canvas; a 6× ring would swamp every non-Focus node.

### 5.6 Per-entity override

The owner may set `portrait_weight` (a number ≥ 0) on a roadmap Focus or on a
roster entry. It **replaces the table weight** for that entity; the tier
multiplier and calibration still apply. `portrait_weight: 0` removes the
entity's target.

---

## 6. Decision: the credit relevance gate

**Status: owner ruling 2026-09-29.** "Conversation/email telling COUNTS when
the source is valid content about the entity."

**Rule — A_SOURCE_TELLS_ONLY_ITS_SUBJECTS.** A source earns telling credit
for an entity only when:

1. it is an **answer** (`answers/*.md`) listed on the entity's page — the
   answer was asked about that category or names the entity, and the 1/n
   split (ratified) keeps a many-page answer from counting many times; or
2. it is any **other source** (conversation, email, manual, landmark
   entry) whose **current** classification (`classify_story.
   current_classification_files`) tags the entity as a subject in `people`,
   `places`, `themes`, `time_periods` or `projects`, the tag resolving to
   the entity's page by exact name, title, roster name or alias — **never a
   bare name occurrence in the text**; and the source file still exists.

An **unclassified** source earns nothing, however often it names the entity
(bulk imports). A **stale** classification earns nothing until it is re-read.
Each credited source gives `1/n` to each of the `n` entities that hold it.

Consistent with §1.4: people enter a life story through scenes in which they
are subjects, not through being named.

---

## 7. How to change a number

Every number in §5–§6 lives in **one file the framework ships**,
`system/portrait_targets.json` (sections `targets`, `tiers`, `calibration`,
`credit`, `kinds`, `drawing`). To change one for your vault:

1. Create `state/portrait_targets.json` in the vault with only the keys you
   want to change, in the same shape — e.g.
   `{"targets": {"person": {"sibling": 0.9}}, "calibration": {"quantile": 0.9}}`.
   A new kind may be added to any `targets` table
   (`{"targets": {"person": {"aunt": 0.4}}}`).
2. Run `python3 system/lifehug.py doctor`. It prints every effective value
   with its origin (`<- vault state/portrait_targets.json` or
   `<- framework system/portrait_targets.json`). An invalid override —
   unknown key, wrong type, negative number, a word outside a closed
   vocabulary — is rejected **whole**, and doctor says why.
3. To change the framework default for everyone, edit
   `system/portrait_targets.json` and this section's table in the same PR,
   with the rationale line updated.

For one entity, set `portrait_weight` (§5.6) instead.

---

## 8. Consequences

Numbered so a contract can cite them.

1. **T1. Every entity has a target**, from the table, even with no Focus (§5).
2. **T2. The table is the owner's**, informed by §1–§2, not learned from
   citations (D4). Where the owner and the evidence disagree, the owner wins
   and §3 records it.
3. **T3. Calibration is per type** (D5): the best-told member of a type sits
   on its target; nothing is summed across types (D7).
   *Amended 2026-09-30: one scale anchored on people, `type_scale` per type;
   per type is `calibration.mode: per_type`.*
4. **T4. told is credit**, through the relevance gate (§6), split 1/n.
5. **T5. gap = max(0, 1 − told/target)** is the one number a planner or the
   platform reads; percentile ranking is dropped as the size signal.
6. **T6. Every number is in one declarative file with a validated vault
   override**, and doctor prints the effective values (§7).
7. **T7. A relationship edge uses the same definition** as a person, with
   its other end's relation.
8. **T8. The graph remains a companion view**: the gap is emitted for later
   readers; nothing here changes which question is asked.

---

## 9. Honest gaps

- **No numeric proportion was found in the literature** (§3). Every weight is
  a synthesis of rank orders (§1.1), structure (§1.3–§2) and the owner's four
  examples; the rationale column says which.
- **Berntsen & Rubin 2004 was not obtained**; its figures come from two
  obtained reanalyses (Janssen & Rubin 2011; Zaragoza Scherman 2013).
- **Kahn & Antonucci 1980, Dunbar, Butler 1963, Haight's LREF, Birren &
  Deutchman 1991, Habermas & Bluck 2000 (full text), Lois Daniel's guide,
  the UK Oral History Society pages and the Library of Congress Veterans
  History Project kit were not obtained** as primary text; §1.3 and §2 flag
  each use as secondary.
- **No study counting named people in autobiographies was located.**
- **The life script counts expected events, not narrative space**; its own
  authors say it is idealised and positive-skewed (§1.1).
- **Calibration at quantile 1.0 makes one outlier set a type's scale** — a
  theme tagged in most sources pushes every other theme's gap near 1. The
  knob is `calibration.quantile`; 0.9 is the obvious next setting to try.
- **Kinds depend on what the vault records.** On the owner's vault only 4 of
  13 roster people carry a `relationship`; the classifier's relation words
  fill most of the rest, and a person nobody has described is `unknown`.
- **Age-frame detection is a slug pattern** (`kinds.age_frame_pattern`), not
  a read of the eras store.

---

## Amendment 2026-09-30 — one scale

**Status: decided (owner observation 2026-09-30), implemented in v380 as
`ONE_SCALE_FOR_THE_WHOLE_PORTRAIT`. Amends §5.1 and T3; everything else
stands.**

The owner, looking at v378 on his own vault: *"the intended surface for
Nostalgia is three times the radius of Anthon James Taylor … the biggest
things would be my dad and my mom, to tell a story about myself … why is
Forgiveness two or three times the size of Katie?"*

**Cause.** §5.1 calibrated per type: at `calibration.quantile` 1.0 the
best-told member of each type sits on its target. The best-told theme is
"Family", tagged in nearly every source, so every theme's target became 80
while people's were about 21 — a theme's ring outsized a parent's. That kept
the within-type half of the owner table (graph-vis D4: ideal radii by type
AND relation) and discarded the cross-type half. D7 still holds: nothing is
summed across types; one scale only lets two rings be compared by eye, which
is what the owner did.

**Decision.** One calibration scale for the whole graph, anchored on people:

```
anchor    = quantile(anchor.quantile) of credit / (weight × tier × type_scale[T])
            over the credited anchor members (type person, kind parent | spouse | partner;
            never an exclude_kinds kind such as owner)
target(e) = weight(T, kind(e)) × tier(e) × type_scale[T] × anchor
over(e)   = max(0, told(e) / target(e) − 1)
```

At quantile 1.0 the best-told parent, spouse or partner sits on its target
and every other entity is measured against that same unit. With no credited
anchor member the anchor falls back to the same quantile over every credited
entity. v378's per-type calibration stays one config line away:
`{"calibration": {"mode": "per_type"}}`.

**`type_scale`** — the owner's provisional numbers, fractions of a parent's
target, revisitable like every other number here:

| Type | type_scale | Rationale |
|---|---|---|
| person | 1.0 | The anchor: "the biggest things would be my dad and my mom". |
| life | 1.0 | The hub is the self-portrait, as large as a parent; an A–E arc keeps its 0.6 table weight (§5.4), so a chapter is 0.6 of a parent. |
| place | 0.6 | A home is where the story happens, not who it is about — a step below the people. |
| period | 0.6 | A named era is a chapter (McAdams, §1.4): the same step down as a place. |
| project | 0.5 | "Jobs are smaller" than family (#434 §2); work sits a half-step below settings and chapters. |
| lifes_work | 0.6 | The strand a life's work runs through is chapter-sized, above one project. |
| object | 0.3 | An object is a prop in a scene. |
| theme | 0.3 | A theme runs through the story rather than being told on its own: "why is Forgiveness two or three times the size of Katie?" |
| relationship | 1.0 | *Builder's choice, not in the owner's list:* a bond is measured on its person's own scale. |
| self | 0.6 | *Builder's choice, not in the owner's list:* a reflection page sits with the chapters, not the people. |

**Told can exceed target.** On one scale a tag applied to almost everything
is told far past its target (Family: over 17.8). The fill is drawn capped at
the ring with a second, thinner ring marking the excess; `over` is emitted on
every node and relationship edge; `doctor` lists the ten most over-told per
type beside the ten largest gaps. That list is the honest signal that a tag
is doing too much work.

**Measured on a scratch copy of the owner's vault** (v378 → v380; ring px on
the shipped 6 + 30·√(value / largest target) scale):

| Entity | kind | told | v378 target | v378 gap | v378 ring px | v380 target | v380 gap | v380 over | v380 ring px |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dad | parent | 17.8 | 17.8 | 0.00 | 20 | 17.8 | 0.00 | 0.00 | 30 |
| Katie | spouse | 9.8 | 21.3 | 0.54 | 21 | 21.3 | 0.54 | 0.00 | 32 |
| Mom | parent | 5.7 | 21.3 | 0.73 | 21 | 21.3 | 0.73 | 0.00 | 32 |
| sibling (Anthon) | sibling | 7.3 | 17.0 | 0.57 | 20 | 17.0 | 0.57 | 0.00 | 29 |
| Family | theme | 80.1 | 80.1 | 0.00 | 36 | 4.3 | 0.00 | 17.80 | 18 |
| Nostalgia | theme | 8.0 | 80.1 | 0.90 | 36 | 4.3 | 0.00 | 0.89 | 18 |
| Forgiveness | theme | 1.2 | 80.1 | 0.98 | 36 | 4.3 | 0.71 | 0.00 | 18 |

Dad anchors the scale (14.21 per unit of weight × tier — the same number v378
found for people, so no person's target moved); every theme's target fell
from 80.1 to 4.3. The most over-told themes: Family, Rootlessness, Education,
Hunger, Faith, Financial Instability, Belonging, Etherfuse, Friendship,
Nostalgia — ten themes told past a theme's target, which says the theme tags
are applied broadly, not that those themes are finished.

**Same day — A_FOCUS_WEARS_GOLD.** The owner: *"I wanted it to be a little
clearer which things are the focus, like a golden orb around the intended
size. The entities that have been picked to be focuses or projects should be
distinct."* v372's ring marked a Focus; v378 gave every entity a ring and the
mark was lost. v380 draws a static gold halo just outside the target ring of
every active Focus and a second-colour halo around every project
(`drawing.focus_halo`, `drawing.project_halo`); nodes carry `focus` and
`project` flags.

## Sources

**Obtained (full text)**

- Janssen, S. M. J. & Rubin, D. C., 2011, *Age effects in cultural life scripts*, Applied Cognitive Psychology 25(2):291–298 — Duke open-access PDF *(obtained)*
- Zaragoza Scherman, A., 2013, *Cultural life script theory and the reminiscence bump*, Nordic Psychology 65(2):103–119 — author's accepted manuscript, pure.au.dk *(obtained)*
- Atkinson, R., 2002, *The life story interview*, in Gubrium & Holstein (eds.), Handbook of Interview Research, Sage, pp. 121–140 — https://marcuse.faculty.history.ucsb.edu/projects/oralhistory/2002AtkinsonLifeStoryInterview.pdf *(obtained)*
- McAdams, D. P., 2007, *The Life Story Interview – II*, Foley Center for the Study of Lives, Northwestern University — https://cpb-us-e1.wpmucdn.com/sites.northwestern.edu/dist/4/3901/files/2020/11/The-Life-Story-Interview-II-2007.pdf *(obtained)*
- Baylor University Institute for Oral History, 2016, *Introduction to Oral History* — https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/intro_manual_2016.pdf *(obtained)*
- Smithsonian Center for Folklife and Cultural Heritage, *The Smithsonian Folklife and Oral History Interviewing Guide* — https://museumonmainstreet.org/sites/default/files/Smithsonian%20oral%20history%20guide.pdf *(obtained)*
- StoryCorps, *Great Questions* — storycorps.org *(obtained)*

**Not obtained, or secondary only**

- Berntsen, D. & Rubin, D. C., 2004, *Cultural life scripts structure recall from autobiographical memory*, Memory & Cognition 32(3):427–442 *(not obtained; via the two reanalyses above)*
- Habermas, T. & Bluck, S., 2000, *Getting a life: the emergence of the life story in adolescence*, Psychological Bulletin 126(5):748–769 *(abstract only)*
- Kahn, R. L. & Antonucci, T. C., 1980, *Convoys over the life course*, Life-Span Development and Behavior 3:253–286 *(not obtained; secondary descriptions)*
- Dunbar, R. I. M., social layers *(not obtained; secondary descriptions)*
- Butler, R. N., 1963, *The life review*, Psychiatry 26(1):65–76 *(not obtained; secondary paraphrase)*
- Haight, B. K., *Life Review and Experiencing Form* *(not obtained; secondary summary)*
- Birren, J. E. & Deutchman, D. E., 1991, *Guiding Autobiography Groups for Older Adults*, Johns Hopkins *(not obtained; secondary theme lists)*
- Daniel, L., *How to Write Your Own Life Story* *(not obtained; chapter list only)*
- Oral History Society (UK) guidance; Library of Congress Veterans History Project field kit *(not obtained)*

**This repository**

- `system/research/graph-vis.md` (branch `research-graph-vis`, #435) §4.2–§4.5 and D3–D7
- `system/research/chronology-vis.md` §4.3 (peer-relative completeness, Recoin)
- `system/focus_candidate.py` `FOCUS_RELATIONSHIPS`; `system/roster_relations.py` `roster_relationship_for`; `system/axis_membership.py` `DISTANT_RELATIONSHIPS`; `system/roadmap.py` `TIER_TARGETS`; `docs/adr/0030-eras.md`
- [lifehug/lifehug#434](https://github.com/lifehug/lifehug/issues/434) §2 (the owner's examples)

## Research queue

1. **Obtain Berntsen & Rubin 2004 and Kahn & Antonucci 1980** and re-check §1.1 and §1.3 against the primary text.
2. **Find a study that counts named people in told life stories** (not scripts), to test §5.2's order against narrative space.
3. **Revisit siblings and grandparents** after a year of the owner's own telling: does the table's gap for them match what he chooses to tell?
4. **Try `calibration.quantile` 0.9** on the owner's vault and compare the largest gaps.
5. **Read age frames from the eras store** instead of a slug pattern.
6. **Decide whether the planner reads `gap`** (graph-vis §5, the loop pulse) — out of scope here (T8).
