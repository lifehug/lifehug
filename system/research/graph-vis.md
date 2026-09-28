# The graph as a life-portrait target

*Research-only literature review (v369). Every claim is sourced; nothing here
is implemented. Builds on `chronology-vis.md` §4–§5 and
[issue #434](https://github.com/lifehug/lifehug/issues/434).*

---

## 0. The graph as a living target

The graph page should show two things at once: the life story as it stands,
and the limit the daily question loop is aiming at. Given unlimited time, that
loop converges on a well-balanced portrait across entity types — people,
places, periods, themes, jobs, and the rest — rather than on whichever page
happens to have collected the most citations.

That reading is the owner's, and it is already on the record. The brief that
opened the chronology-visualization review says, of this page specifically:

> "The graph page visualizes the algorithm's goal (balance — a small sibling
> node means ask more there); the timeline needs its twin: a score of how
> UNORGANIZED the data is versus the goal of a straight line and a 1."
> — owner, 2026-08-24, quoted in `system/research/chronology-vis.md` §0
> (lines 26–27 of the paragraph at lines 21–30)

The timeline's twin was the subject of that review. This one is the graph's
own half: current size against ideal size, so a small sibling is visible as a
place to ask more. [Issue #434](https://github.com/lifehug/lifehug/issues/434)
is the planning note. Its findings comment
([#issuecomment-5862355205](https://github.com/lifehug/lifehug/issues/434#issuecomment-5862355205))
is the code reading this review checks, corrects where the line numbers or the
simulation drifted, and does not re-implement.

Nothing below is a shipped behavior. Design consequences are numbered in §8
so a later contract can cite them.

---

## 1. What exists today

### 1.1 `graph_data()` builds `{nodes, edges}`

`system/serve_wiki.py` `graph_data()` (lines 2253–2303) walks compiled wiki
pages, skipping the top-level index, log, and schema (`p.parent == WIKI_DIR`,
line 2272). Each node is `{id, label, type, sources}` where `type` is the
parent folder name (`people`, `places`, …) and `sources` is the integer read
from frontmatter `sources_count` (lines 2277–2281). If the page's path is a
Focus `wiki_node`, the node also gets `sat`, the focus saturation from
`roadmap.focus_fill` (lines 2257–2264, 2282–2284).

The page is served two ways. `view_graph()` (lines 2403–2404) returns the
hand-written HTML below. `GET /views/graph.json` (lines 4104–4111) returns
`json.dumps(graph_data())`.

### 1.2 The layout is hand-written SVG and plain JS

`_GRAPH_HTML` (lines 2306–2400) is a `<script>` in the page. It imports no
graph library. After `fetch('/views/graph.json')` (line 2325) it:

1. Sets each node's radius to `7 + Math.sqrt(n.sources || 0) * 4` (line 2332).
2. Seeds positions on a ring: centre of the measured SVG, plus
   `Math.cos(i) * 180` and `Math.sin(i) * 180`, plus a small index jitter
   `(i % 7) * 12` and `(i % 5) * 12` (lines 2328–2334). `i` is the node index
   in radians, not `2π i / n`. There is no `Math.random`.
3. Runs a force simulation for 320 steps (line 2372) **before anything is
   drawn**. Each step (`tick`, lines 2343–2370) is all-pairs repulsion,
   springs along edges, and a pull toward the canvas centre, then damping and
   a clamp to the frame. The constants (line 2342) are `K_REP = 5200`,
   `K_SPRING = 0.02`, `LINK_LEN = 90`, `CENTER = 0.015`, `DAMP = 0.86`.
4. Draws an undirected `<line>` per edge at `stroke-width: Math.min(6, e.weight)`
   (lines 2380–2383) and a circle plus a label per node (lines 2385–2395).

The SVG's size comes from `getBoundingClientRect()` (line 2328), with a
fallback of 900×600. The same node order on two different viewports is not the
same picture. The CSS (`#graph`, line 552) only sets width, height, border,
and background. It does not add a `viewBox`, a zoom, or a pan.

The only interaction on a node is a click that navigates to `/page/` + the
node id (line 2393). The legend (lines 2307–2311) says the same thing: "Click
a node to open its page." There is no zoom, pan, drag, hover, or filter in
this script.

### 1.3 Bug: the fullest pages can draw at the minimum radius

`sources_count` is read by `page_field()` (lines 111–120), which scans only
the first 1024 characters:

```114:115:system/serve_wiki.py
        head = read_text(path, errors="replace")[:1024]
        m = re.search(rf'^{re.escape(key)}:\s*"?(.+?)"?\s*$', head, re.MULTILINE)
```

A miss returns `""` (line 120). `graph_data` then does `int(... or 0)` (line
2278), so a miss is `sources: 0`, and the radius formula draws 7.

`wiki_compile.frontmatter()` writes that key **after** the full `sources:`
list (lines 429–436):

```429:436:system/wiki_compile.py
    lines += [
        f"created: {today}",
        f"last_updated: {today}",
        "sources:",
    ]
    for source in sources:
        lines.append(f'  - "{source}"')
    lines.append(f"sources_count: {len(sources)}")
```

Optional keys (`section`, `chrono`, `date`, `born`, `died`) are written
**before** `sources:` (lines 411–428), so they only make the window smaller.

**What was verified.** This session called `frontmatter()` for a minimal
person page (title `"Mom"`, no section, no dates, `related` of two slugs) and
applied `page_field`'s slice and regex to the string it returned. No compiled
vault was used. This checkout has no wiki pages with a real `sources_count`
beyond the schema example in `wiki/SCHEMA.md`.

| Source path shape | Last count still read | First count read as missing |
|---|---|---|
| `answers/K12.md` (14 characters, repeated) | 39 | 40 |
| `answers/A{n}.md` (13 characters) | 40 | 41 |
| `sources/conversations/msg-<24 hex>.md` | 13 | 14 |

The 24-hex conversation filename is what the code writes
(`temporal_store.FILENAME_DIGEST_LENGTH = 24` at line 217;
`conversation_source_relative_path` at lines 313–325). Issue #434's findings
comment said "roughly 40" for short `answers/K12.md` paths and "roughly 17"
for `msg-<hex>` paths. The short-answer figure matches this re-simulation.
The conversation figure does not: with the 24-hex paths the tree actually
uses, the key falls out of the window at 14 sources, not 17. A shorter hex
would fail later. Either way the failure mode is the same, and a page that
fails draws at radius 7 — the minimum — so the fullest pages draw smallest.

The graph test does not catch this. `tests/test_wiki_views.py`
`test_graph_nodes_edges_and_weight` (line 811) builds a page whose
`sources_count: 3` sits on a one-item `sources:` list (fixture at line 266),
well inside 1024 characters, and asserts `sources == 3` (line 818). The
fixture also writes `sources_count` *before* `related`, and the scalar `3`
does not equal the length of the `sources:` list. It never builds a page the
way `frontmatter()` does.

**What the bug does not touch.** Edge weight uses `_fm_list` on the whole
frontmatter block (`_frontmatter_block`, lines 2232–2234; `_fm_list`, lines
2237–2250; the intersection at line 2301). A page whose `sources_count` reads
as 0 can still contribute its real source list to edge weight.

### 1.4 Edges are undirected `related:` links

`graph_data` draws an edge only from frontmatter `related:` (lines 2288,
2292–2302). Each pair is keyed by `tuple(sorted([nid, tgt]))` (line 2297), so
the edge is undirected and a mutual link is stored once. Weight is
`1 + |sources(a) ∩ sources(b)|` (line 2302), drawn at width `min(6, weight)`
(line 2383).

`related:` is filled by `wiki_compile.compute_crosslinks()` (lines 1482–1527).
Shared-source counts rank neighbours (lines 1486–1495, 1507). The list keeps
LLM and seed links first, then up to `MAX_SHARED` shared-source neighbours
(line 1510), and the whole list is cut at `MAX_RELATED` (line 1515). Those
caps are `MAX_RELATED = 12` and `MAX_SHARED = 8` (lines 111–112). The shared
count is not stored on the page. The graph recomputes it from the two
`sources:` lists at read time.

There is no clustering pass. Node colour is focus saturation when `sat` is
present — green at ≥ 0.7, amber at ≥ 0.3, otherwise red (`satColor`, line
2321) — and otherwise a colour from the folder name (`TYPE_COLORS`, lines
2316–2319).

### 1.5 The platform port

lifehug-platform, read at `9a607f54` on 2026-09-28, has a zero-dependency port
of the same simulation in `apps/web/lib/graph-layout.ts`. Its module comment
says it keeps the OSS constants and the repulsion, spring, and centering
forces, and that it imports no graph library. Edges there carry a `kind` of
`"relationship"` or `"link"` (`GraphEdge` in `apps/web/lib/reflect.ts`, lines
130–135) instead of a shared-source weight. `GraphClient.tsx`
(`apps/web/app/(product)/graph/GraphClient.tsx`) adds hover highlighting: the
hovered node, its neighbours, and their edges stay bright and the rest dims.
That hover is not in the OSS script.

Two divergences matter later. The platform's default tick count is 80
(`DEFAULT_TICKS`), with an optional warm start from the previous layout in the
browser tab; a cold OSS-faithful run is still available as `options.ticks`.
And `GraphNode` (`reflect.ts`, lines 120–128) carries `section: string`. The
renderer read for this review colours and groups by `entity_type` and does
not read `section`. This was a reading of `GraphClient.tsx` and `reflect.ts`,
not a search of every platform file.

---

## 2. Layout research

This section takes `chronology-vis.md` §5.2 (lines 960–1005) as the constraint
on motion, and asks what that leaves for the drag, rotate, and pan that
issue #434 asks for.

### 2.1 Force-directed layout is a heuristic

Fruchterman & Reingold, obtained this session
([*Graph drawing by force-directed placement*, Software: Practice and
Experience 21(11):1129–1164, 1991](https://reingold.co/force-directed.pdf);
[doi:10.1002/spe.4380211102](https://doi.org/10.1002/spe.4380211102)):

> "Our heuristic strives for uniform edge lengths, and we develop it in
> analogy to forces in natural systems, for a simple, elegant, conceptually
> intuitive, and efficient algorithm."

And, on the aesthetic criteria (even spacing, few crossings, uniform lengths,
symmetry, fitting the frame): "Our algorithm does not explicitly strive for
these goals, but does well at distributing vertices evenly, making edge
lengths uniform, and reflecting symmetry." The picture is a simplified
physical simulation whose authors wanted speed and simplicity. Eades's
metaphor, which they quote, is steel rings and springs released from an
initial layout toward a low-energy state.

`chronology-vis.md` §5.2 (lines 992–997) draws the consequence for the
settling animation: it is an artifact of iterative relaxation, and "was never
designed to communicate anything." That sentence is the review's, not a
quotation from Fruchterman & Reingold. It fits what the paper does say. The
OSS graph runs that relaxation for a fixed 320 steps and then paints once
(§1.2). The motion the owner would add is not this settling, and it should
not be asked to mean what the settling never meant.

### 2.2 Small multiples beat animation, and the mental map barely helps

Three results in `chronology-vis.md` §5.2 bound any animation on this page.
The papers behind the second and third were **not re-obtained** this session;
the quotations below are the ones that review already prints, and §9 lists
them as gaps.

**Animation is the weakest form for analysis.** `chronology-vis.md` lines
972–979 quote Robertson, Fernandez, Fisher, Lee & Stasko, 2008, *IEEE TVCG*:
trend animation "is the fastest technique for presentation and participants
find it enjoyable and exciting," and it "does lead to many participant
errors. **Animation is the least effective form for analysis**; both static
depictions of trends are significantly faster than animation, and the small
multiples display is more accurate."

**Preserving the mental map barely helps.** Lines 982–990 quote Archambault
& Purchase, 2011, *IEEE TVCG*: "small multiples gave significantly faster
performance than animation overall and for each of our five graph
comprehension tasks," and "Preserving the mental map under either the
animation or the small multiples condition had little influence in terms of
error rate and response time." The mental-map idea is attributed there to
Misue, Eades, Lai & Sugiyama, 1995, *Journal of Visual Languages & Computing*
([doi:10.1006/jvlc.1995.1010](https://doi.org/10.1006/jvlc.1995.1010)). Misue
et al. was **not obtained**. This review does not add a finding of theirs
beyond the attribution chronology-vis already makes.

**Heer & Robertson, re-opened.** The 2007 InfoVis paper was fetched
([PDF](https://idl.cs.washington.edu/files/2007-AnimatedTransitions-InfoVis.pdf)).
The abstract's claim matches what chronology-vis relies on: two controlled
experiments "finding that animated transitions can significantly improve
graphical perception." The introduction, which this session did read, is the
part that constrains a graph page:

> "Animation's ability to grab attention can be a powerful force for
> distraction. … incorrect interpretations of causality may mislead more than
> inform. … animation is ephemeral, complicating comparison of items in flux."

They also record Tversky, Morrison & Bétrancourt's skepticism — "finding no
benefit for communicating the workings of complex systems" — and quote the
Congruence and Apprehension principles through that paper. Tversky et al.
2002 was **not obtained** here, as it was not obtained for chronology-vis
(§5.2, lines 999–1005; Sources, "not obtained"). The experiment's F statistic
and the 1.25 s / 2 s durations are chronology-vis §5.1's (lines 939–958), not
re-checked against the PDF this session.

What chronology-vis §5.3 keeps is a short, un-staggered transition of a few
marks, where every frame is still a legible chart, and where the animation is
presentation rather than the only way to see what changed. A force-layout
"watch it settle" is the case they say is not supported.

### 2.3 Manipulation is for orientation, not for analysis

Issue #434 §5 asks for drag on nodes, and for rotate or pan of the view.
That request survives the skepticism in §2.2 only under a narrow reading,
and the reading is a **design argument**, not a result from those papers.

Heer's obtained warning is that motion is perceived as causality. A node that
glides because the simulation is still running, or because a drag was stored
back into the layout, will be read as the life changing. Robertson's result,
via chronology-vis, says that kind of motion is the worst channel for
analysis. So analysis stays in the static marks of §4–§6: radius, outline,
colour, cluster, a pulse that does not move.

What drag, rotate, and pan are then for is exploration and orientation. The
reader turns the picture to see a neighbourhood. The layout itself stays a
function of the vault: the deterministic seed and the 320-step simulation of
§1.2, given node order and canvas size. The gesture is a camera. It is not
written back, and it does not re-seed the next layout.

The platform warm start (§1.5) already breaks a strict version of that rule
inside one browser tab: a later visit can start from the previous positions
rather than from the ring. That is a performance cache, documented as such,
and it is not a stored claim about the life. An OSS drag must not become more
than that. If a dragged position is saved, the picture stops being a function
of the sources and starts being a second, unstated edit.

---

## 3. Clusters

### 3.1 There is no community detection today

`graph_data` (§1.1) does not partition nodes. Colour is saturation or folder
type. Nothing in `_GRAPH_HTML` draws a hull, a region, or a labeled group.

### 3.2 Prefer keys the vault already has

Four keys already name groups. A computed community would throw them away.

**Page `section`.** `wiki_compile.project_label()` (lines 592–597) turns a
category qualifier such as `(Etherfuse Story)` into the label `Etherfuse`.
`plan_projects` stores that label as the descriptor's `section` (lines
1042 and 1054), and `frontmatter()` writes `section: "..."` when it is
non-empty (lines 427–428). The sidebar already groups on it:
`nav_html`'s `items_html` (lines 157–168) splits items that have `section:`
under a subgroup heading. The comment at line 157 gives Etherfuse as the
example. The platform's `GraphNode.section` (§1.5) is this field, carried
and not read by the renderer this review opened.

**Era membership.** `system/era_memberships.py` (module doc, lines 1–18)
stores immutable receipts at `sources/eras/memberships/<hex>.md`
(`MEMBERSHIP_SOURCES_DIR`, line 78): "this thing is inside that era,"
identified by member, era, relation, and source. A display receipt is a
separate decision and "never chronology." Membership is a person-made
containment, not a cluster inferred from `related:` edges.

**Entity type.** The folder (`people`, `places`, `periods`, …) is already
`node.type` (§1.1) and already has a colour. It is the coarsest honest
grouping, and it is the one the sidebar uses when `section` is absent.

**Roadmap focus categories.** A Focus carries `categories` (the question-bank
letters it owns) and, when it has one, `wiki_node`. `derive_roadmap` sets
`wiki_node` for person and project focuses (`roadmap.py` lines 249–252 and
271–274; the primary life-story focus is `wiki_node: None` at line 218).
`graph_data` already joins on `wiki_node` to paint saturation (§1.1). The
categories are a group of pages the owner asked to build, which is a
different fact from "these pages share sources."

### 3.3 Louvain and Leiden, only as a fallback

If a picture still needs a partition after those keys, the modularity
literature is the usual next step. Both papers below were obtained this
session. Neither is a reason to cluster the life graph before the keys in
§3.2 have been drawn.

**Louvain.** Blondel, Guillaume, Lambiotte & Lefebvre, 2008, *Fast unfolding
of communities in large networks*, Journal of Statistical Mechanics P10008
([arXiv:0803.0476](https://arxiv.org/pdf/0803.0476)):

> "We propose a simple method to extract the community structure of large
> networks. Our method is a heuristic method that is based on modularity
> optimization."

Modularity, in their equation (1), compares the weight of edges inside a
community with the weight expected from the nodes' strengths. The algorithm
is a local move that greedily improves that quantity, then aggregates
communities and repeats. They note that the output depends on the order in
which nodes are considered. A life graph whose edges are a 12-link cap on
`related:` (§1.4) is a poor input to that objective: the missing edges are
mostly the cap, not an absence of shared life.

**Leiden.** Traag, Waltman & van Eck, 2019, *From Louvain to Leiden:
guaranteeing well-connected communities*, Scientific Reports
([arXiv:1810.08473](https://arxiv.org/pdf/1810.08473)):

> "We show that this algorithm has a major defect that largely went unnoticed
> until now: the Louvain algorithm may yield arbitrarily badly connected
> communities. In the worst case, communities may even be disconnected,
> especially when running the algorithm iteratively. In our experimental
> analysis, we observe that up to 25% of the communities are badly connected
> and up to 16% are disconnected."

Leiden adds a refinement phase and proves communities are connected. That is
the reason to prefer it over Louvain **if** a computed partition is used at
all. It does not make the partition a substitute for `section`, an era
receipt, a folder, or a focus. Those are decisions the person or the compiler
already recorded. A modularity partition is a heuristic on whatever edges the
cap left behind.

### 3.4 Drawing a region

Issue #434 does not specify how a cluster is painted. Two standard devices
are a convex hull around the member points, and Bubble Sets (Collins, Penn &
Carpendale, 2009, *Bubble Sets: Revealing Set Relations with Isocontours over
Existing Visualizations*, IEEE TVCG 15(6)). **Collins et al. was not
obtained** this session (the usual PDF URL returned 503). This review does
not state what that study found. The design consequence in §8 is only that a
region, if one is drawn, is drawn around a key from §3.2, and that the hull
algorithm is unchosen until the paper is read.

### 3.5 Neighborhoods are not clusters of pages

A neighborhood is not a blob of wiki pages. `docs/handbook/neighborhoods.md`
§2 (lines 38–45) defines it as a cluster of 6–12 question slots about one
topic, stored in `state/neighborhoods.json`, laid out on a narrative arc, and
aimed at one `target_output`. Its `source` is "the wiki page, answer file, or
bare topic string it was opened from" — one opener, not a set of pages.
`system/research_expand.py` line 4 says "clusters of 6-12 questions"; the
generator prompt asks for 8–12 (line 770). The handbook's opening paragraph
(line 19) also says 8–12. The noun section's 6–12 is the range this review
uses, and the prompt's 8–12 is what a run actually requests.

They are arcs of questions pointing at one topic (often one page, not
always). They are not clusters of pages, and they must not be drawn as if
they were.

---

## 4. Fill and balance

### 4.1 Current size against ideal size

Issue #434 §2 and §5: each node shows how much of its story has been told,
and how much it should hold relative to its peers. The suggested mark is a
filled circle for the current size inside a ring or ghost outline for the
target. Both states stay on the page.

That is the same static overlay `chronology-vis.md` §1.1 already argued for
dates: OxCal draws the unmodelled likelihood in outline and the modelled
posterior solid, so the effect of the model can be seen without an animation
(Bronk Ramsey 2009, quoted there; **not re-obtained** for this review). Here
the outline is an ideal radius and the fill is the current one. The analogy
is the overlay, not the statistics. A life-graph radius is not a posterior.

### 4.2 Ideal weights are per type and relation

The owner's examples, from issue #434 §2, are the spec until a table exists:

- Sisters are equal to each other, and large.
- Parents are larger still.
- Grandparents are slightly smaller than parents.
- Jobs are smaller.

Nothing in the codebase stores an ideal radius, an archetype table, or a
learned weight. `graph_data` has only `sources` and, sometimes, `sat`. This
review does not invent the rest of the table. How the weights are defined —
fixed archetype, learned from the life, or an archetype the owner can
override — is issue #434's second open question, and it is still open (§10).

### 4.3 A single completeness meter is an improper scoring rule

`chronology-vis.md` §4 (lines 733–933) is the argument this page has to
reuse, not replace.

§4.6 (lines 904–927): a scoring rule is proper when the forecaster's best
move is to report what they actually believe (Gneiting & Raftery 2007; **not
re-obtained**). A completeness meter — *does this field have a value?* — is
improper, because any value at all maximises it. The chronology review's
conclusion, which this one adopts for node size: compare like with like, and
do not reward a count that goes up whenever an answer is mentioned.

§4.3 (lines 784–805): Wikidata's Recoin is the precedent for showing
completeness **against similar items**, in a few coarse bands, with the
missing pieces named beside the mark. "Peer-relative, never absolute."

Applied here: a node's current size is its standing among nodes of the same
entity type, not a fraction of an unknown total of memories, and not a raw
source count compared across types. Sisters are compared with sisters. A job
is not "behind" a parent because the parent page cites more files. The ideal
radius of §4.2 is what makes two types comparable on the same canvas without
pretending their source counts live on one scale.

### 4.4 Three candidate signals for current size

All three are proposals. None is what the graph reads today. The order is
the one in issue #434's findings comment. This review does not promote one
of them to a decision; §8 records that the choice is still open.

**(a) Distinct answers, as a percentile within the type.** Count distinct
`answers/*.md` paths on the node, or read the roster's `unique_answers`, and
rank the node against other nodes of the same `type`. The roster copies
`unique_answers` onto `state/entity_rosters/<type>.json`
(`entity_roster.py` lines 9 and 719–723). Reading the full `sources:` list
through `_fm_list` (§1.3) also fixes the 1024-character bug for this signal,
because the list is already parsed in full for edge weight.

**(b) The focus-recommender score, divided by the type's median.**
`recommend_focuses._score` (lines 620–630) is:

```620:630:system/recommend_focuses.py
def _score(s: dict) -> float:
    mention_count = s["mention_count"]
    unique_answers = len(s["answers"])
    cross_categories = len(s["categories"])
    emotional_weight = s["emotional_weight"]
    return (
        mention_count * 1.0
        + unique_answers * 2.0
        + cross_categories * 3.0
        + emotional_weight * 1.5
    )
```

The inputs are built in `_build_entity_stats` (lines 447–558) from answer
text, other sources, and classifications, then folded through roster aliases
before scoring (lines 592–617). Results land in `state/focus_recommendations.json`.
The same `score` and `unique_answers` are what the roster entry stores (line
722). Normalising by the median **of that entity type** is the peer comparison
§4.3 requires. It is not implemented.

**(c) Scene-slot depth, with focus saturation where a focus exists.** The
classifier prompt asks for five `scene_slots` booleans — what happened, when
and where, who was there, thought and felt, what it says about the author
(`classify_story.py` lines 1007–1013) — and the saved classification keeps
that object (line 1299) under `state/classifications/<stem>.json`. Focus
saturation is `answered / target_depth` (`roadmap.focus_fill`, lines
376–394). Tier defaults are basic 8, standard 20, extreme 50
(`TIER_TARGETS`, line 46). `book.compute_chapter` already turns scene slots
into a `scene_ratio` for a category (lines 262–280). A node-level combination
— saturation times mean scene-slot fill for a focused node, scene-slot fill
alone otherwise — is the findings comment's quality check. It is not a field
on the graph.

**What questions do not carry.** A bank question is `{id, category, text,
answered}` (`lifehug_core.parse_questions`, lines 778–791). `category` is
`qid[0]`, a letter, not an entity. A queue entry is `{question_id, category,
group, focus, story_function, objective, status, reason, ...}`
(`question_planner.py` lines 903–914). `focus` is a Focus id. Per-answer
entity tags live on the classification: `people`, `places`, `time_periods`,
`themes`, `projects` (lines 979–991). Any "answered questions per entity"
signal has to go through those tags or through the page's `sources:` list.
The bank and the queue do not have it.

### 4.5 There is no cross-type balance metric

`graph_data` sizes by one scalar and colours by one saturation.
`focus_fill` is one Focus's answered/target ratio. Category coverage is
answered/total inside one letter (`lifehug_core`, the ratios that feed
`coverage.json`). `placement_score` is how tightly the timeline can place
what it holds, and its docstring says it is not completeness (§6). None of
these compares people with places with jobs. The word "balance" in the
research corpus, for this purpose, is the owner's sentence in
`chronology-vis.md` line 26. That is a goal, not a metric.

---

## 5. Loop pulse

Issue #434 §3: the graph should show the work the daily loop is doing. Nodes
the loop is actively asking about glow, and the glow fades as each reaches
its target.

The files that can ground that, today:

- `state/question_queue.json`, written by the planner (`question_planner.py`
  line 2511). Each entry has a `focus` (§4.4), not an entity id.
- The roadmap Focus's `wiki_node`, which `graph_data` already joins (§1.1).
- That Focus's saturation from `focus_fill` (§4.4). A saturation of 1 means
  `answered >= target_depth` (lines 385–392).

So a pulse can be attached to the `wiki_node` of any Focus that owns a
still-queued entry, and dropped when that Focus is saturated. Focuses with
`wiki_node: None` — the primary life story is one (line 218) — have nothing
to pulse until some other join exists. Queue entries that are not a Focus
cannot pulse a node at all.

**The risk from §2.** A glow that animates is motion, and motion is read as
meaning (Heer, §2.2). chronology-vis §5.2's presentation-versus-analysis
split says the analysis has to remain visible when nothing is moving. Static
alternatives that carry the same fact: a stroke on the node, a second ring
that is either there or not, or a small multiples panel of "in this week's
queue" beside the graph. Fading can be a smaller static mark at higher
saturation, not a tween. §8 prefers the static mark.

---

## 6. Gap bridging

`research_expand.detect_gaps` (lines 547–603) flags a time period or a theme
as thin when the fraction of answers whose body hits that topic's keyword
list is under `GAP_COVERAGE_THRESHOLD = 0.30` (line 269). The report is
printed (`--gaps`, lines 1419 and following in the same file). It is not
stored as graph state. The findings comment on #434 is right that this is a
printout, not a file the graph reads.

A thin period is a different object from a timeline gap. `timeline.placement_score`
(lines 3016–3051) is "how placed this life is." The docstring's last rule
(lines 3050–3051):

> It is not a verdict on the life. It is scoped to what the timeline can
> order and place — placement, never "completeness" or "accuracy".

Using `placement_score` as a node radius, or as the thin-period signal, would
repeat the improper-meter mistake of §4.3 on a different quantity. The score
measures sharpness of dates. The gap report measures keyword coverage of
answers. Neither is "how much of this person's story is told."

The bridge issue #434 implies, and this review treats as a design proposal
rather than an existing control: a thin-period mark on the graph, whose
click opens the timeline view (`/views/timeline`) at that period. The click
target is the timeline, not another wiki page. There is no such link in
`_GRAPH_HTML` today (§1.2). Timeline placement data — which moments sit in
which period — is the evidence the timeline already has for *where* a thin
stretch is. It is not a second completeness number.

---

## 7. Alternatives to one hairball

A force layout of every page and every `related:` link is one picture, and
§2.1 says that picture was built to spread vertices and even out edges, not
to explain a life. Three alternatives sit beside it. They are design
options. This session did not obtain a user study that ranks them for a
biographical graph; that absence is a gap in §9.

**Ego.** The subgraph of one node and its neighbours. The platform already
does the visual half on hover (§1.5): neighbours stay bright, everything else
dims. OSS has no hover. Issue #434 §5 asks for the same highlight on click.
That is a viewing filter over the existing edges. It does not require a new
layout, and it does not store a position.

**Small multiples by type or by era.** One frame per folder, or per era
membership (§3.2), each with its own nodes. This is the form Archambault &
Purchase found faster for graph comprehension, in the quotation chronology-vis
§5.2 already carries (§2.2; paper not re-obtained). It also matches §4.3:
peers of one type share a frame, so a percentile is a position in that frame
rather than a radius fighting every other type for space.

**Focus mode.** The roadmap's active focuses, their `wiki_node`s, and the
categories those focuses own (§3.2), drawn alone. The week's queue (§5) is
the natural default filter: show the nodes the loop is asking about, and
offer the full graph as the other mode. Focus mode is not a new community
algorithm. It is the keys §3.2 already has, used as a filter.

The full graph can stay. §2.2's result is that it should not be the only
view, and that it should not be the one that moves.

---

## 8. Design consequences

Numbered so a contract can cite them. Each one points at the section that
forced it. None of them is implemented.

1. **D1. Read the source count from the whole frontmatter.** `page_field`'s
   1024-character window drops `sources_count` once the `sources:` list is
   long enough, and the page then draws at radius 7 (§1.3). `_fm_list`
   already parses the full list for edge weight. The radius must use that
   list, or a `sources_count` read from the whole file. Not from the first
   1024 characters.
2. **D2. Do not size a node by raw `sources_count`.** One answer can sit on
   many pages (§1.3, and issue #434's findings comment). A count that rises
   whenever a field is filled is an improper scoring rule (chronology-vis
   §4.6, adopted in §4.3).
3. **D3. Draw current and ideal together, and keep both on the page.** A
   filled circle inside a ghost ring (§4.1). The precedent is OxCal's
   outline-under-solid (chronology-vis §1.1), applied to radius. Not an
   animation, and not a number that appears only on hover.
4. **D4. Ideal radii are an owner table by type and relation.** Sisters
   equal and large, parents larger, grandparents slightly smaller, jobs
   smaller (issue #434 §2). No such table exists (§4.2). Do not learn one
   from citation counts.
5. **D5. Compare a node with peers of its type.** Recoin's rule, via
   chronology-vis §4.3 (§4.3). A job is not scored on a parent's scale.
6. **D6. The current-size signal is undecided, and the candidates are the
   three in §4.4.** Distinct-answer percentile within the type; the
   recommender score over the type median; scene-slot depth, times focus
   saturation when the node is a `wiki_node`. A later contract picks one.
   This review does not.
7. **D7. There is no cross-type balance metric, and the graph must not
   invent one by summing radii** (§4.5).
8. **D8. Cluster by recorded keys before any community algorithm.**
   `section`, era membership, entity type, focus categories (§3.2). Louvain
   can return disconnected communities (Traag et al. 2019, §3.3). Leiden is
   the fallback if a computed partition is ever required, and it is not
   required by anything in §3.2.
9. **D9. Do not draw a neighborhood as a cluster of pages** (§3.5).
10. **D10. The layout stays a function of the vault.** Deterministic seed,
    fixed step count, no stored drag (§2.3). A drag, rotate, or pan is a
    camera. It is not written into the next simulation. The platform's
    in-tab warm start is a cache, not a precedent for saving positions.
11. **D11. Manipulation is orientation. Analysis stays in the static marks.**
    Motion is read as causality (Heer & Robertson, §2.2). Robertson and
    Archambault, via chronology-vis §5.2, put animation last for analysis
    and small multiples first.
12. **D12. The loop pulse is a static mark on a queued Focus's `wiki_node`,
    absent once saturation reaches 1** (§5). It does not glow by animation.
    A Focus with no `wiki_node` does not pulse.
13. **D13. A thin period links to the timeline. It is not `placement_score`.**
    Keyword coverage under 30% is the gap report (§6). Placement score is
    sharpness of dates, and its own docstring refuses completeness.
14. **D14. Keep a way out of the hairball.** Ego highlight, small multiples
    by type or era, and a focus mode are filters over existing keys (§7).
    The force layout of every `related:` link is not the only view.

---

## 9. Honest gaps in this review

Stated so a later reader does not mistake silence for support.

- **The `sources_count` bug was simulated, not reproduced on a vault.** The
  simulation is `frontmatter()` plus `page_field`'s slice, on synthetic
  paths (§1.3). This checkout has no compiled pages to confirm it against.
  The findings comment's "roughly 17" for conversation paths does not match
  the 24-hex filename the code writes; this session's figure is 14. Both
  agree the failure exists and that it shrinks the fullest pages.
- **Robertson et al. 2008, Archambault & Purchase 2011, and Misue et al.
  1995 were not obtained.** §2.2 quotes them only through `chronology-vis.md`
  §5.2. Tversky, Morrison & Bétrancourt 2002 was not obtained either; Heer &
  Robertson quote it, and chronology-vis already flags that.
- **Heer & Robertson's F statistic and the 1.25 s / 2 s durations were not
  re-checked** against the PDF this session. The abstract and the
  introduction's warning about false causality were.
- **Collins, Penn & Carpendale 2009 (Bubble Sets) was not obtained.** §3.4
  names the paper and does not report its findings. No paper on convex-hull
  set rendering was obtained either. Region drawing is unchosen.
- **Ideal weights are the owner's examples, not a measured scale.** Nothing
  sourced here says a parent should be larger than a grandparent by any
  particular factor (§4.2).
- **No user study of this graph, or of a biographical node-link diagram,
  was obtained.** §7's three alternatives are options, not a ranking.
- **The claim that `GraphNode.section` is unused is a reading of
  `GraphClient.tsx` and `reflect.ts`**, not a whole-repository search (§1.5).
- **"Glow" has no study behind it.** The static mark in D12 is an
  application of Heer and of chronology-vis §5.2, not an experiment on
  pulses.
- **Deduplicating a source that cites several pages is untested.** Issue
  #434 asks whether one answer should count once, fractionally, or once per
  page. This review states that raw counts double-count (§4.4, D2) and does
  not pick a scheme.
- **Neighborhood `source` is not always a wiki page.** It may be an answer
  file or a bare topic string (§3.5). "One source page" would overstate the
  handbook.
- **Absence of a cross-type balance metric** is a reading of `graph_data`,
  `focus_fill`, category coverage, and `placement_score` (§4.5), plus the
  owner's sentence in chronology-vis. It is not a proof that no module
  anywhere computes one.

---

## Sources

**This repository and the planning issue**

- `system/research/chronology-vis.md` §0 (lines 21–30), §1.1, §4 (lines 733–933), §5.1–§5.3 (lines 937–1024) — the owner's balance sentence, the outline-under-solid overlay, the improper-meter argument, and the animation constraints this review adopts
- [lifehug/lifehug#434](https://github.com/lifehug/lifehug/issues/434) — planning issue, including the findings comment [#issuecomment-5862355205](https://github.com/lifehug/lifehug/issues/434#issuecomment-5862355205)
- lifehug-platform `9a607f54` (read 2026-09-28): `apps/web/lib/graph-layout.ts`, `apps/web/lib/reflect.ts` (`GraphNode`, `GraphEdge`), `apps/web/app/(product)/graph/GraphClient.tsx`

**Layout and animation**

- Fruchterman, T. M. J. & Reingold, E. M., 1991, *Graph drawing by force-directed placement*, Software: Practice and Experience 21(11):1129–1164 — https://reingold.co/force-directed.pdf — https://doi.org/10.1002/spe.4380211102 *(obtained)*
- Heer, J. & Robertson, G., 2007, *Animated transitions in statistical data graphics*, InfoVis — https://idl.cs.washington.edu/files/2007-AnimatedTransitions-InfoVis.pdf *(abstract and introduction re-read; experimental statistics carried from chronology-vis §5.1)*
- Robertson, G., Fernandez, R., Fisher, D., Lee, B. & Stasko, J., 2008, *Effectiveness of animation in trend visualization*, IEEE TVCG — http://www.cc.gatech.edu/~john.stasko/papers/infovis08-anim.pdf *(not obtained; quoted via chronology-vis §5.2)*
- Archambault, D. & Purchase, H., 2011, *Animation, small multiples, and the effect of mental map preservation in dynamic graphs*, IEEE TVCG — https://doi.org/10.1109/tvcg.2010.78 *(not obtained; quoted via chronology-vis §5.2)*
- Misue, K., Eades, P., Lai, W. & Sugiyama, K., 1995, *Layout adjustment and the mental map*, Journal of Visual Languages & Computing — https://doi.org/10.1006/jvlc.1995.1010 *(not obtained)*
- Tversky, B., Morrison, J. B. & Bétrancourt, M., 2002, *Animation: can it facilitate?*, International Journal of Human-Computer Studies 57(4) — https://doi.org/10.1006/ijhc.2002.1017 *(not obtained; quoted via Heer & Robertson and chronology-vis §5.2)*

**Communities and regions**

- Blondel, V. D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E., 2008, *Fast unfolding of communities in large networks*, Journal of Statistical Mechanics P10008 — https://arxiv.org/pdf/0803.0476 *(obtained)*
- Traag, V. A., Waltman, L. & van Eck, N. J., 2019, *From Louvain to Leiden: guaranteeing well-connected communities*, Scientific Reports — https://arxiv.org/pdf/1810.08473 *(obtained)*
- Collins, C., Penn, G. & Carpendale, S., 2009, *Bubble Sets: Revealing Set Relations with Isocontours over Existing Visualizations*, IEEE TVCG 15(6) — https://doi.org/10.1109/TVCG.2009.122 *(not obtained)*

**Completeness, carried from chronology-vis §4 and not re-obtained**

- Gneiting, T. & Raftery, A. E., 2007, *Strictly proper scoring rules, prediction, and estimation*, JASA 102(477):359–378 — cited at chronology-vis.md lines 904–918
- Wikidata:Recoin — cited at chronology-vis.md lines 784–805
- Bronk Ramsey, C., 2009, *Bayesian analysis of radiocarbon dates*, Radiocarbon 51(1):337–360 — the outline-under-solid overlay, chronology-vis.md §1.1

## Research queue

Written here, not in `system/research/QUEUE.md`. That file was not edited.

1. **Which signal is current size** (issue #434, open question 1). Distinct answers per entity, normalised within type; the recommender score; scene-slot depth; raw source count; or a mix. §4.4 lists the first three and rejects the fourth as the radius (D2, D6).
2. **How ideal weights are defined** (issue #434, open question 2). A fixed archetype by type and relation, weights learned from the life, or an archetype the owner can override. The only examples on record are sisters, parents, grandparents, and jobs (§4.2, D4).
3. **How to render current against target without clutter** (issue #434, open question 3). Ghost ring, fill percentage, hover-only, or small multiples. D3 picks the static ring as the proposal to test, and does not test it.
4. **Whether to deduplicate cross-referenced sources** (issue #434, open question 4). One answer on five pages currently counts five times. Fractional weight is undesigned (§9).
5. **Reproduce the 1024-character bug on a compiled vault** with both short answer paths and `msg-<24 hex>` conversation paths, and record the real radii (§1.3).
6. **Obtain the unread layout papers** before a contract leans on them: Robertson et al. 2008, Archambault & Purchase 2011, Misue et al. 1995, Tversky et al. 2002, Collins et al. 2009.
7. **Decide whether era memberships are hulls, filters, or edges.** They are receipts (`era_memberships.py`), not `related:` links (§3.2). Nothing says which picture they should become.
8. **Decide whether a saved layout is allowed at all.** D10 forbids it. The platform warm start shows the pressure to cache positions. A contract should say which of those wins before anyone stores a drag.
