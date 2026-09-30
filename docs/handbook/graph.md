---
title: The Graph — a Portrait and its Target
parent: Handbook
nav_order: 14
---

# The Graph — a Portrait and its Target

## 1. What it does & what it's for

The Graph view (Reflect → Graph, `/views/graph`) draws the compiled wiki as a
picture of a life: every entity page is a node, every relationship page is
an edge between the two lives it joins, and each node's size says how much
of the telling is that entity's, compared with others of its kind. A Focus
draws a ring for the target it is trying to reach. It is a companion view for
now: it reads the vault and changes nothing.

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
- **Credit** — how much of the telling an entity holds: each credited source
  gives `1/n` to each of the `n` pages that cite it (owner ruling,
  2026-09-29).
- **Percentile** — a node's credit ranked among nodes of its own type
  (graph-vis D5). **Not ranked**: zero credit, or the only member of its
  type — both draw at the minimum size.
- **Ring** — a Focus's target, drawn around the page the Focus compiles to.
- **Portrait config** — every number above, in one file (§6).

## 3. How it works

1. `wiki_compile.py` writes pages. Where a question-bank category goes is
   decided by ONE rule, `system/focus_pages.py`:
   - a `## Focuses` category (`K: Focus — Mom`) → `wiki/people/<slug>.md`
     (whatever the Focus's type) and, when there is enough material,
     `wiki/relationships/<slug(name)>-and-<slug>.md`;
   - a `## Project Categories` category → `wiki/projects/<slug(category)>.md`,
     one page per category — a grouped project Focus ("Etherfuse", five
     categories) is five pages, and its ring is drawn on each;
   - an A–E arc → `wiki/life/<slug(category)>.md`; the primary Focus → the hub.
2. The roadmap's `wiki_node` is refreshed from the same rule on every
   `roadmap-rebuild` and `focus-new`, so it names the page that exists.
3. `graph_data()` resolves every Focus through the rule
   (`graph_focus_joins`), sizes nodes from credit, and joins relationship
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

**Size.** Fill radius = `radius_min + percentile × radius_span` when ranked,
else `radius_min`.
<!-- parity: portrait_targets.RADIUS_MIN = 8 -->
<!-- parity: portrait_targets.RADIUS_SPAN = 16 -->
<!-- parity: portrait_targets.CREDIT_SPLIT = equal -->
The shipped values: minimum 8 px, span 16 px, credit split `equal` (1/n), a
one-member type not ranked, zero credit not ranked. Only `answers/*.md`
earn credit today (`credit.source_prefixes`).

**A broken roadmap is loud.** If the roadmap or bank cannot be read, the graph
logs a warning on `lifehug.graph`, lists it in `warnings`, and the page shows
"graph warning(s)" above the canvas.

Measured on the owner's vault (86 nodes, 2026-09-29): relationship edges that
join the owner and the right person went from 0 of 8 to 8 of 8; Focuses that
resolve to an existing page went from 8 of 10 to 10 of 10 (the primary Focus
and the Etherfuse group).

## 5. In the loop

Loop-adjacent. The graph reads compiled pages, the roadmap, and the portrait
config; it writes nothing. `doctor` reports its joins.

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
`{"drawing": {"radius_min": 6}}`, then run `lifehug doctor` and check the line
reads `<- vault state/portrait_targets.json`.

## 7. Decisions

- graph-vis D3 (current and ideal on one page), D4 (ideal radii are an owner
  table), D5 (peers within type), D7 (no cross-type sum).
- Owner rulings 2026-09-29: the 1/n split; every entity gets a target; the
  graph is a companion view; every knob adjustable in one config.
- Issue #434.
