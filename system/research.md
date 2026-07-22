# Life Hug — Research & Methodology (v2)

**Original research:** 2026-02-25 (StoryCorps, ghostwriting frameworks, memoir structure)
**Deep-research revision:** 2026-07-04 — verified against primary sources (McAdams, Pennebaker, Frattaroli meta-analysis, Aron, Bridges, Birren, Belli, Tversky & Marsh, Cochrane reviews) plus competitor post-mortems (StoryWorth, Remento, HereAfter AI). Implementation status is tagged per section: **[shipped]**, or the wave that lands it (v70–v73, issues lifehug/lifehug#27–#30).

---

## 1. Question Design — the essentials (read first; this section feeds AI prompts)

1. **Open-ended, never yes/no** — "Tell me about…" not "Did you…"
2. **Two-sentence rule** (Morrissey, oral-history canon): one sentence of context drawn from a prior answer, then ONE open question. This is the mechanic that makes a generated question feel like listening.
3. **Specific moment over generality** — "Think of one time when…" not "Generally, what was…"
4. **Sensory ("carnality", Karr)** — when an answer is habitual summary ("we always went to the lake"), drop into one instance and one sense ("Pick one of those mornings — what did the dock smell like?").
5. **Emotional anchor** — "What were you feeling when that happened?"
6. **The five-slot scene probe (McAdams)** — every key scene wants: what happened / when & where / who was there / what you thought & felt / **what does it say about you**. The last slot is the highest-value follow-up in the literature and the one shallow products never ask.
7. **Action↔identity ladder (narrative therapy)** — after an action answer: "what does it say about you that you did that?"; after an identity claim: "tell me about one specific moment that proves it."
8. **"What", not "why", for the author's own feelings** (Eurich) — why-questions about one's own recurring emotions produce confabulation and brooding. "Why" stays fine for events and other people.
9. **Never restate the author's account as fact** — recall makes memory labile (reconsolidation); a paraphrase-back that changes details can contaminate the memory itself. Quote exactly or ask fresh.
10. **New angles on depth passes** — re-asking for the canonical version suppresses unretrieved detail (retrieval-induced forgetting). Ask for what's NEVER been told: "a detail from that day you've never mentioned to anyone."
11. **One question at a time. Never leading. How/What openers.**

---

## 2. How People Write Life Stories

### 2a. Structure: hybrid thematic-chronological (unchanged from v1)
Pure chronology reads like a résumé; pure theme lacks drive. Chronological backbone, thematic chapters. Each chapter needs: a central scene, a tension, a turning point, a reflection. **[shipped v75/v76: book-status chapter map with readiness verdicts (scene-slot data), gap questions, milestone offers, planner chapter-gap boost]**

### 2b. McAdams — narrative identity (Life Story Interview II)
- **Life chapters exercise**: "think of your life as a book — 2–7 chapters, give each a title, and say how we get from one to the next." The transition clause forces boundary articulation. **[shipped v71: `lifehug.py chapters-exercise`, re-run yearly]**
- **Eight key scenes** (high point, low point, turning point, positive/negative childhood memory, vivid adult memory, spiritual experience, wisdom event), each probed with the five slots. A person- or period-Focus isn't deep until it holds at least a high point, low point, and turning point. **[shipped v70: classifier extracts `scene_slots`; follow-ups target empty slots]**
- **Redemption sequences** (bad→good) track well-being; contamination (good→bad) tracks distress. OFFER, never force, the reframe: "did anything grow out of that?" If a low-point question is refused, soften to "just a very bad experience of some kind." Note: redemption framing is culturally American — offer, don't impose.

### 2c. Guided Autobiography (Birren)
Weekly **theme** + a fan of sensitizing questions ("react to the ones that open windows — skip the rest"; a skip is signal, not failure), ~2-page story, witnessed reading. Nine themes: branching points, family, money, life work, health/body, sexual identity, death, spiritual life, goals. **Money, health/body, sexual identity, and death are high-yield domains most question banks under-cover.** Never open a heavy theme cold — one framing sentence first. **[shipped v70: GAB themes in gap detection; framing rules in prompts]**

### 2d. Memoir craft (Karr / Gornick)
- **Situation vs story** (Gornick): what happened vs "the thing one has come to say." Tag answers; situation-rich/story-empty answers get the meaning-making follow-up. Chapter drafting picks its "thing to say" FIRST, then selects scenes serving it.
- Memoir fails when **the narrator doesn't change** — track then-vs-now deltas; additive `reflect-source` is the right primitive. **[shipped v71: perennials — `lifehug.py perennial-add`, monthly `--generate-due`]**
- **Voice is the product.** "Your words, lightly cleaned, never rewritten." Never paraphrase into third person, never alter names. (Remento's AI rewrites — changed names, third-person rendering — are the canonical trust failure.)

### 2e. Competitor lessons (why people abandon these products)
- **StoryWorth**: #1 failure is silent abandonment — "a few get answered, then it quietly stops." No conversational follow-up; repetitive prompts. **The fix is conversation, not cadence** — immediate acknowledgment + one listening follow-up. **[shipped v68: adaptive 1–3/day + re-engagement question after silent days]**
- **Remento**: voice-first wins completion; AI rewriting bled trust (see 2d).
- **HereAfter AI**: shut down; users' recordings held behind a support email. Lifehug's git/markdown own-your-data model is the answer — never gate reading or export.
- **De-risk the book early**: interim artifacts (letters, posts) prevent the year-end quality shock where competitor complaints cluster.

---

## 3. How People Understand Themselves

### 3a. Expressive writing (Pennebaker) — what actually produces insight
Benefit tracks: **rising insight/causal words across sessions**, pronoun flexibility (perspective shifts), and coherence *development* — an already-fossilized story retold identically shows little gain. Effects are real but modest (Frattaroli 2006: 146 RCTs, d≈.15). Boundary conditions that are now design rules:
- **Fresh-upheaval deferral**: writing too soon after trauma (< ~1–2 months) is useless or harmful. Defer deep-processing follow-ups. **[shipped v70: classifier `defer` flag → 60-day hold]**
- **Invite, never force, framing**: over-constrained prompts (forced positivity, forced perspective-flips) underperform open ones. Offer lenses, don't mandate them. **[shipped v70: prompt rules]**

### 3b. Productive introspection vs rumination
Brooding (repetitive abstract negative self-focus) worsens outcomes; reflection helps. Design rules: the what-not-why lint (§1.8); a **rumination detector** — consecutive answers on a theme with no new events and no insight growth → rotate the theme out for weeks, return via a concrete-behavior or distancing lens. **Depth ≠ repetition.** **[shipped v70: rumination detector cools flagged categories in the planner]**
- **Distancing toolkit** for hot material (Kross): fly-on-the-wall retelling, temporal distancing ("when you're 80, what will this chapter mean?"). Use immersed "what did it feel like" prompts for neutral/positive scene capture — distancing is for processing, immersion is for texture.

### 3c. Longitudinal self-knowledge
- **Anniversary questions** (10Q model): 5–10 durable questions (success, fear, faith, marriage) re-asked yearly, delivered WITH last year's answer attached. The return-and-contrast moment is the product. **[shipped v71: perennials]**
- **Echo-style resurfacing**: reviewing one's own past entries measurably improved well-being (CHI 2013) — a monthly slot sends an old answer back verbatim + one reflection question. **[shipped v71: monthly resurfacing]**
- **Values through episodes, not lists** (ACT/Schwartz): "tell me about a decision where you gave up money or status for something else — what was the something?" Evidence-linked inferred values beat self-declared ones; the importance–consistency gap is the contradiction-question generator. *(values ledger deferred — see follow-up issue)*
- **Johari coverage**: Lifehug natively mines the Hidden quadrant; the Blind quadrant needs other-perspective prompts; Unknown maps to "a time you surprised yourself."
- Classifier-extracted **contradictions and self-understanding insights ground the self-arc prompts** — a question naming the author's actual tension cuts deeper than generic introspection. **[shipped v69]**

---

## 4. Time Periods & Life Chapters

The synthesized **period arc** (each stage maps to question types):
1. **Name & bound the chapter** (McAdams TOC) — title + how it began and ended
2. **Life-structure snapshot** (Levinson): "what were the pillars that period — work, relationships, home, a guiding Dream? Which was the keystone? What was neglected?" Track "the Dream" longitudinally: alive, modified, abandoned?
3. **Typical-day reconstruction + era anchors** (oral history): "walk me through a typical Tuesday — waking to sleeping"; what things cost, the car, the music, the house layout room by room. The highest-yield texture prompts that exist.
4. **Key scenes** via the five-slot probe
5. **The transition out, two layers** (Bridges): the change ("what happened?") AND the inner transition ("when did it end *inside* you? what did you let go of?") plus the **neutral zone** ("was there a stretch when the old life was gone but the new hadn't started? what did you do in the in-between?") — the richest under-captured memoir material.
6. **Later evaluative integration pass** (Butler's life review): "looking back at that chapter now, how do you make peace with it? what did it give you that you only see now?" Recall alone has weak evidence; the evaluative pass is what carries the meta-analytic support.
**[shipped: v71 PERIOD_ARC template for time_period neighborhoods; v70 question families in all generation prompts]**

### Memory science for capture
- **Cues**: odor > music > photos > words. Odor-cued memories peak at ages 6–10 — route smell/taste prompts at thin early-childhood coverage. Photo/song reply prompts are the deployable stand-ins. **[shipped v70: prompt families; media ingestion itself is v72+]**
- **Reminiscence bump**: authors over ~40 disproportionately recall ages 10–30 — weight there, but pair each life-script milestone with the off-script probe ("which milestone did NOT go the way the script says?").
- **Dating memories**: never ask "what year?" Landmark anchors ("before or after the move to X? was [child] born yet?") raise correct dating from ~42% to ~68% (Zwartz 2013). Belli's event-history calendar (parallel residence/work/relationship timelines) cross-cues chronology. Store relative order as a first-class relation; flag inferred dates low-confidence (telescoping). **[shipped v71: classifier extracts `events` with `when_hint`+`anchor` (never years); wiki/timeline.md compiles from them. Full EHC onboarding survey deferred — see follow-up issue]**
- **Anti-fossilization**: biased retelling biases the memory itself (Tversky & Marsh); confidence ≠ accuracy (flashbulb studies). Freeze the first telling (immutable sources — **[shipped, core architecture]**), flag high-retell memories, mine new angles on depth passes (§1.10).

---

## 5. Relationships & Connection

- **Aron (36 Questions)**: the mechanism is "sustained, escalating, reciprocal, personalistic self-disclosure" — the *escalating structure itself* does the work (verified nulls: goal-priming and expectation manipulations changed nothing). Design rules: enforce arc-slot ordering (never `tension`/`how_they_see_me` before earlier slots have answered sources); **mutual disclosure requires a second voice** — a bot that only extracts never creates closeness. **[Tiers 1–3 shipped v72: witness ingest, capped offers, on-demand interview packs. Tier 4 (direct guest questions) deferred — needs multi-recipient infra, see #32]**
- **Gottman love maps**: knowledge of the other's *current* inner world decays — when a living person's mentions go stale, prefer present-tense re-asks ("what is she most worried about right now?") over unasked history.
- **WNRS**: perception-gap questions ("what did they first assume about you that turned out wrong?") produce testable claims a guest answer can confirm; ration "dig deeper" follow-ups to keep them special (v68's adaptive follow-up covers this); **the Final Card move** — arc completion auto-offers the letter. **[shipped v72: progress offers letter + closing reflection on completed relational arcs]**
- **StoryCorps / family interviewing**: the unit is two people who know each other; questions organized by relationship type (parent, grandparent, mentor, co-founder, remembering a loved one). **Conflicting accounts across relatives are data to preserve, never errors to resolve** — paired immutable sources, never merged. **[shipped v72: witness_account source type + synthesis attribution rules]**
- **Unsent letters** (grief work, Neimeyer): for the deceased or estranged — "hello again," not goodbye; owner-only, never suggested for sharing. **Legacy letters** (ethical-will tradition): values → lessons → gratitude → hopes/blessings → forgiveness — the last two are the rarest question moves in any bank. Lifehug can pre-populate from existing sources; everyone else starts blank. **[shipped v72: unsent_letter + legacy_letter formats]**

---

## 6. Iteration Model: Fill → Deepen → Connect → Polish (updated)

Passes as before (skeleton → depth → connections → polish), with two research-grounded amendments:
- Multi-pass revisiting is effectively **spaced retrieval** — prefer even revisit intervals per era over one-burst exhaustion.
- Depth passes obey §1.10 (new angles, never re-rehearsal).

Coverage thresholds unchanged: RED 0–30%, YELLOW 30–70%, GREEN 70%+ (offer the chapter at GREEN — and actually offer it; see v73 book surface).

---

## 7. The Loop as learning system **[shipped v68–v72]**

The self-improving cycle only works when signal actually flows: candidates promote under backlog-aware caps with craft-quality gates and semantic dedup; scores attribute their story function (one shared vocabulary) and owning Focus; classifier extractions (focus opportunities, contradictions, insights, output ideas) all have consumers; failures are recorded and surfaced by a scheduled doctor. Silent abandonment is countered by adaptive cadence (same-day follow-up when warm, easy re-engagement question when quiet). v70/v71 additions: craft rules and question families live in every generation prompt (classifier, follow-ups, research); the why→what lint and quality gate park violations; the rumination detector cools brooding categories; perennials re-ask durable questions yearly with last year's answer attached; a monthly resurfacing slot returns an old answer with a reflection question; a weekly present-tense prompt captures the life being lived; compiled wiki open questions harvest back into candidates (synthesis→question); and classifier-extracted events compile into wiki/timeline.md with relative anchors. v73 phase 0 unlocked honest synthesis under an explicit owner-only privacy contract (sources never leave; audience surfaces are separate owner-reviewed builds; unlabeled = private) — see system/privacy_design.md.

---

## 7b. Opinions as source material **[shipped v95]**

Gornick's distinction (The Situation and the Story): an **opinion is story
without situation** — the author has the "story" (the insight, the lens) but
none of the lived situation on the page yet. The essay lane supplies the
situation from two directions: the seeded essay artifact grounds the position
in the author's archive material, and the Socratic follow-up candidates
(origin, counterexample, evolution, dissent, stakes — mapped to the planner's
self-knowledge story functions) capture the lived moments behind the belief as
future answers. Opinions are captured as immutable primary sources
(`type: opinion`); the finished essay is promoted as `authored_artifact`
(supporting, attributed — never circular proof). Design principle per the
author-centric model: artifacts influence the wiki as input sources; they never
directly create pages.

---

## 7c. External evidence connectors **[shipped v106]**

Email (Gmail first) joins the source layer as a **selective evidence and
discovery source** — not a bulk import, and not a per-item review queue. The
methodological commitment is the same one the source contract makes elsewhere:
trust is earned at the threshold, not at the capture.

- **The ledger is permanent; relevance is recomputed.** `fetch` appends
  metadata-only lines (no bodies) to `state/connectors/<name>_ledger.jsonl`;
  `excavate` re-scores the ENTIRE ledger against the CURRENT wiki, rosters,
  and sources on every run. Scores are never trusted beyond the run that
  computed them — a 2008 thread that is noise today becomes gold the day its
  correspondent gains a wiki page (the time-varying axes:
  `relationship_signal`, `discovery_signal`, `novelty`). Nothing is ever
  discarded from the ledger, so coverage is guaranteed by re-evaluation over
  time, not by getting scoring right once.
- **Threshold trust, signed off once.** Six deterministic axes (date_anchor,
  relationship_signal, discovery_signal, narrative_density, novelty,
  reciprocity) feed a weighted total; the owner calibrates weights and the
  promote threshold ONCE against a shadow run over real history
  (`connector-calibrate`), versioned in `state/connectors/weights.json`.
  Bands: `<0.15` noise (ledger only) · `0.15–0.45` evidence (metadata
  harvested, never read) · `0.45–threshold` near-band · `≥threshold`
  auto-promote. Below the threshold, mail stays metadata-only evidence.
- **Three missions, three products.** Corroborate: date evidence
  (`{date, entity, kind, message_id}`) harvested from institutional mail —
  the utility-bill rule, content ignored but date+address kept. Discover:
  unknown high-volume correspondents, untold narrative threads, and unknown
  institutions mined into `question_candidates.json` (provenance
  `connector-mined`) — email as a sensor for the Loop's thin spots. Source:
  the rare above-threshold thread becomes an immutable `sources/gmail/`
  source (`source_trust: external_record`, `authority: third_party_record`)
  — corroborating record, never first-person memory.
- **Bounded automation.** Per-run promotion cap (default 25), `--dry-run`,
  `connector-audit` listing, idempotency by message id, and the existing
  retraction/correction flow as the escape hatch. This is a rare excavation
  (quarterly/yearly), not a sync service.
- **Date evidence corroborates the timeline [shipped v110].** The harvested
  assertions line up against the timeline with the scorer's token-subset
  discipline — an entity matches a period whose roster name/slug/alias tokens
  it contains, and a moment whose own text (description, time words, era)
  contains it — yielding compact corroboration badges (`✉ asu ×1100 ·
  2010–2013`) on the timeline view and the `wiki/timeline.md` export. Evidence
  clustering AGAINST the story (email says 2003, the answer says 2004; or a
  period's stated `approximate_dates` disjoint from its records' span) becomes
  a `date_contradiction` gap entry plus a connector-mined question candidate
  on the next excavation — the Loop asks the owner which is right; memory is
  never silently overwritten. The timeline layer itself stays read-only and
  zero-AI, and repos without connectors render exactly as before.
- **Owner-declared VIPs are calibrated knowledge, not a heuristic
  [shipped v107].** Heuristics cannot know that `bigdaddy.jet@gmail.com` is
  Dad. `weights.json` accepts a `vip_correspondents` map (email → label) and a
  `vip_bonus`: declared VIPs pin `relationship_signal` to 1.0, add the bonus
  to the thread total, and are never mined as "unknown" discoveries. A VIP
  with no wiki page becomes a high-priority page candidate instead. The map is
  owner-edited and versioned like the threshold — declare family once, and
  every excavation honors it across all 20+ years of the ledger.
- **Roster email aliases bind the wiki to exact addresses [shipped v107].**
  Name-token matching is weak for mail (a "BigDaddy" display name shares no
  tokens with Dad's page). Roster entities may carry email addresses in
  `aliases`; correspondents then match by exact address in
  `relationship_signal`, `_discovery`, and discovery mining. This is the
  learning loop: VIP declaration → page candidate → page created with the
  email recorded as a roster alias → future excavations score from wiki state
  alone, no re-declaration. Importance marked in the wiki becomes the
  authority, exactly as it is everywhere else in the Loop.
- **AI dossiers auto-apply calibrated relationship knowledge [shipped v108].**
  Declaring every VIP by hand doesn't scale against 20+ years of mail, so the
  loop closes with the model instead of a review queue: top unclassified
  correspondents (not declared, not roster/wiki-known, above a volume floor,
  never automated senders) get 2–3 of their highest-narrative-density threads
  sampled and read NARROWLY for classification — one compact JSON verdict
  (`family|close_friend|colleague|service|unknown`, significance, suggested
  label, confidence). Only the classification persists
  (`state/connectors/gmail_dossiers.json`); the bodies themselves are cached
  committed under `state/connectors/gmail_body_cache/` (owner relaxed raw
  storage) so promotions and future passes never re-fetch. Verdicts of a
  configured class at/over the confidence floor auto-apply as VIPs during
  scoring — same pin, same bonus — with hand-declared VIPs always winning
  conflicts and a `vip_blocklist` in `weights.json` as the owner's veto. The
  excavation report lists dossier VIPs with their one-line significance, so
  the calibration stays auditable without becoming per-item approval.
- **Volume is era-bound; importance is not volume.** A college collaborator
  can out-mail a sibling 10:1 and matter less. Discovery candidates are weak
  signals by design — "not a good candidate" in the normal review flow is the
  intended rejection path, and each new connector (work mail, exports) re-
  balances the correspondent map. The VIP mechanism above is the corrective
  for people the volume understates.

---

## 8. Key References

**Narrative identity & memoir**: McAdams, *Life Story Interview II* (Foley Center); McAdams & McLean 2013; McAdams et al. 2001 (redemption/contamination, PSPB); Karr, *The Art of Memoir*; Gornick, *The Situation and the Story*; Birren, Guided Autobiography (nine themes).
**Introspection science**: Pennebaker & Chung (expressive writing protocol); Frattaroli 2006 meta-analysis; Campbell & Pennebaker 2003 (pronoun flexibility); Kross & Ayduk 2011 (self-distancing); Nolen-Hoeksema (rumination); Treynor (brooding vs reflection); Eurich (what-not-why).
**Transitions & life review**: Levinson, *Seasons of a Man's Life* (life structure — lens, not template); Bridges, *Transitions* (endings → neutral zone → beginnings); Butler/Westerhof 2019 (life review); Cochrane 2018 (reminiscence).
**Memory science**: Tversky & Marsh 2000 (retelling bias); Talarico & Rubin 2003 (flashbulb confidence); Roediger & Karpicke 2006 (testing effect); Willander & Larsson (odor cues); Janata (music-evoked memories); Zwartz 2013 (landmark dating); Belli (event history calendar); Koppel & Rubin (reminiscence bump).
**Relationships**: Aron et al. 1997 (36 Questions, PSPB); Gottman (love maps); StoryCorps Great Questions; Neimeyer (continuing bonds); Baines (ethical wills).
**Oral history practice**: Smithsonian Interviewing Guide; Moyer, Step-by-Step Guide; Morrissey (two-sentence rule); Oral History Association best practices.
**Structure reference memoirs** (unchanged from v1): *Educated*, *Open*, *Kitchen Confidential*, *Born a Crime*, *The Glass Castle*, *Shoe Dog*, *The Hard Thing About Hard Things*.
