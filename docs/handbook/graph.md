---
title: The Graph — a Portrait and its Target
parent: Handbook
nav_order: 14
---

# The Graph — a Portrait and its Target

## 1. What it does & what it's for

The Graph view (Reflect → Graph, `/views/graph`) draws the compiled wiki as a
picture of a life: every entity page is a node, every relationship page is
an edge between the two lives it joins. Each node is a filled circle — what
has been told about it — inside a ring — what a well-told life holds for that
kind of entity (its **target**). The distance between them is the **gap**. It
is a companion view for now: it reads the vault and changes nothing; the gap
is emitted for the planner and the platform to read later.

The research behind it is `system/research/graph-vis.md` (issue #434). This
page describes what is built.

## 2. The nouns

- **Node** — one compiled entity page (`wiki/<type>/<slug>.md`), any type
  except `relationships`.
- **Relationship edge** — a `wiki/relationships/` page, drawn as a thick line
  between its two ends, not as a node.
- **Life hub** — the owner's self-portrait page, `wiki/life/<slug(full_name)>.md`.
  The owner appears on the graph as the hub, never as a person page that
  shares his name.
- **Credit / told** — how much of the telling an entity holds: each credited
  source gives `1/n` to each of the `n` entities that hold it (owner ruling,
  2026-09-29). An answer is held by the pages that list it; any other source
  only by the entities its current classification tags
  (`A_SOURCE_TELLS_ONLY_ITS_SUBJECTS`, §4).
- **Kind** — what an entity is within its type: a person's relation (parent,
  spouse, sibling …), a place's kind (residence, school, city …), a period's
  (era, age frame, job).
- **Target** — table weight for (type, kind) × Focus tier multiplier × the
  type's calibration scale, on the credit scale.
- **Gap** — `max(0, 1 − told/target)`.
- **Ring** — the target, drawn on the same radius scale as the fill; its
  colour is the gap (red large, green small).
- **Portrait config** — every number above, in one file (§6).

## 3. How it works

1. `wiki_compile.py` writes pages. Where a question-bank category goes is
   decided by ONE rule, `system/focus_pages.py`:
   - a `## Focuses` category (`K: Focus — Mom`) → `wiki/people/<slug>.md`
     (whatever the Focus's type) and, when there is enough material,
     `wiki/relationships/<slug(name)>-and-<slug>.md`;
   - a `## Project Categories` category → `wiki/projects/<slug(category)>.md`,
     one page per category — a grouped project Focus ("Etherfuse", five
     categories) is five pages, each carrying the Focus's tier;
   - an A–E arc → `wiki/life/<slug(category)>.md`; the primary Focus → the hub.
2. The roadmap's `wiki_node` is refreshed from the same rule on every
   `roadmap-rebuild` and `focus-new`, so it names the page that exists.
3. `graph_data()` resolves every Focus through the rule
   (`graph_focus_joins`), credits each source through the relevance gate,
   reads each entity's kind, builds its target (§4), and joins relationship
   pages to their ends.

## 4. The algorithm

**A_FOCUS_KNOWS_ITS_OWN_PAGE.** A Focus resolves to the pages the compiler
writes for its categories; the stored `wiki_node` is only a fallback for a
Focus with no category. A resolved page that does not exist is listed in the
graph's `warnings` and in `lifehug doctor` ("graph focus pages") — never
silently dropped.

**A_PRIMARY_FOCUS_IS_THE_HUB.** The primary life-story Focus draws its ring on
the life hub.

**A_RELATIONSHIP_HAS_TWO_ENDS.** A relationship page's ends come from its
title first ("Dave & Mom"). A title part that is the owner's `name`,
`full_name`, or the hub's slug is the hub. `related:` is a fallback only —
it lists everything the page links to, and its second entry is usually a
theme or a period. One resolved end joins the hub.

**The target (v378, ADR 0039).** For every entity *e* of type *T*:

```
told(e)   = credit(e)
target(e) = weight(T, kind(e)) × tier(e) × scale(T)
gap(e)    = max(0, 1 − told(e) / target(e))
```

The weights, tier multipliers and their reasons are the owner's table in
`system/research/life-portrait-targets.md` §5, shipped in
`system/portrait_targets.json`. Parents, spouse and children weigh 1.0,
grandparents 0.85, siblings 0.8, friends 0.5; a home 1.0, a school 0.8, a
workplace 0.7; a named era 1.0, an age frame 0.8.
<!-- parity: portrait_targets.WEIGHT_PARENT = 1.0 -->
<!-- parity: portrait_targets.WEIGHT_GRANDPARENT = 0.85 -->
<!-- parity: portrait_targets.WEIGHT_SIBLING = 0.8 -->
<!-- parity: portrait_targets.WEIGHT_FRIEND = 0.5 -->
<!-- parity: portrait_targets.WEIGHT_RESIDENCE = 1.0 -->
<!-- parity: portrait_targets.WEIGHT_WORKPLACE = 0.7 -->
Tier multipliers: none 1.0, basic 1.25, standard 1.5, extreme 2.0.
<!-- parity: portrait_targets.TIER_NONE = 1.0 -->
<!-- parity: portrait_targets.TIER_BASIC = 1.25 -->
<!-- parity: portrait_targets.TIER_STANDARD = 1.5 -->
<!-- parity: portrait_targets.TIER_EXTREME = 2.0 -->

**Calibration.** `scale(T)` is the quantile (shipped: 1.0, the maximum) of
`credit / (weight × tier)` over the type's credited members, so the
best-told member of each type sits exactly on its target (graph-vis D5). A
type with fewer than 2 credited members borrows the median scale of the
others. The owner's own person page (kind `owner`) is not calibrated on.
Nothing is summed across types (D7).
<!-- parity: portrait_targets.CALIBRATION_QUANTILE = 1.0 -->
<!-- parity: portrait_targets.CALIBRATION_MIN_PEERS = 2 -->

**Kind.** A person's relation is the Focus's `relationship`, else the
roster's, else the classifier's relation words for that person by majority
(`roster_relations.roster_relationship_for`: mother → parent, wife →
spouse), else `unknown`. A place is a `residence`, `school` or `workplace`
when a landmark names it, else the roster `place_kind`, else the classifier's
place type. A period whose slug matches `kinds.age_frame_pattern` is an age
frame. The life hub is `hub`, the A–E pages `arc`.

**Override.** `portrait_weight` on a roadmap Focus or a roster entry replaces
the table weight for that entity.

**Drawing.** Fill and ring share one scale:
`radius = radius_min + radius_span × sqrt(value / largest value on the canvas)`
(shipped: 6 and 30 px), so area is proportional to credit and nothing told
draws at the minimum. The ring is drawn over the fill, so it shows even when
the telling has outgrown it. A relationship edge's width is
`edge_min + edge_span × min(1, told/target)`. Percentile ranking (v372–v376)
is gone.
<!-- parity: portrait_targets.RADIUS_MIN = 6 -->
<!-- parity: portrait_targets.RADIUS_SPAN = 30 -->
<!-- parity: portrait_targets.CREDIT_SPLIT = equal -->

**A_SOURCE_TELLS_ONLY_ITS_SUBJECTS.** An answer earns credit for the pages
that list it. A conversation, email, manual or landmark source earns credit
only for the entities its CURRENT classification tags in `people`, `places`,
`themes`, `time_periods` or `projects`, the tag matching a page's slug,
title, roster name or alias exactly (a trailing parenthetical and the first
comma segment are tried too: "Mesa, Arizona (Tippett house)" → "Mesa"). A
bare name in the text is not a tag. An unclassified source earns nothing; so
does a reading whose source file is gone.

**A broken roadmap is loud.** If the roadmap or bank cannot be read, the graph
logs a warning on `lifehug.graph`, lists it in `warnings`, and the page shows
"graph warning(s)" above the canvas.

Measured on the owner's vault (86 nodes, 2026-09-29): relationship edges that
join the owner and the right person went from 0 of 8 to 8 of 8; Focuses that
resolve to an existing page went from 8 of 10 to 10 of 10 (v376). With the
target model (v378), the median told/target is 0.65 for people, 0.54 for life
pages and projects, 0.23 for places, 0.21 for periods and 0.06 for themes —
one theme is tagged in most sources and sets the theme scale (see §7).

## 5. In the loop

Loop-adjacent. The graph reads compiled pages, the roadmap, the rosters,
current classifications, landmarks and the portrait config; it writes
nothing. `doctor` reports its joins, the effective config, and the largest
gaps per type (`doctor.gap_rows_per_type`, shipped 10). Each node carries
`told`, `target`, `gap` and `kind` for the planner and the platform to read
later; nothing reads them yet.

## 6. Where it lives

- `system/focus_pages.py` — the category→page rule (used by the compiler, the
  roadmap, the graph, and `doctor`).
- `system/portrait_targets.json` — the portrait config the framework ships.
  A vault overrides any subset in `state/portrait_targets.json` (same shape).
  The override is validated against the framework file: an unknown key, a
  wrong type, a negative number, or a value outside a closed vocabulary
  rejects the whole override, and `doctor` says why.
- `system/portrait_targets.py` — loads and validates it;
  `lifehug doctor` prints every effective value and where it came from.
- `system/serve_wiki.py` — `graph_data()`, `graph_focus_joins()`, `_GRAPH_HTML`.

To change a number: copy the key into `state/portrait_targets.json`, e.g.
`{"targets": {"person": {"sibling": 0.9, "aunt": 0.4}}, "calibration": {"quantile": 0.9}}`
(a new kind may be added to any `targets` table), then run `lifehug doctor`
and check the line reads `<- vault state/portrait_targets.json`. For one
entity, set `portrait_weight` on its Focus or roster entry. Every number's
rationale: `system/research/life-portrait-targets.md` §5–§7.

## 7. Decisions

- graph-vis D3 (current and ideal on one page), D4 (ideal radii are an owner
  table), D5 (peers within type), D7 (no cross-type sum).
- Owner rulings 2026-09-29: the 1/n split; every entity gets a target; the
  graph is a companion view; every knob adjustable in one config.
- ADR 0039 "The ring is a target" (ratified, owner 2026-09-29).
- The target table and the credit relevance gate, with sources and a
  rationale for every weight: `system/research/life-portrait-targets.md`
  (v377; implemented in v378).
- Issue #434.
