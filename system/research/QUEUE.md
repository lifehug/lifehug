# Research queue

The backlog of primary sources to ingest into `system/research/` (raw where
obtainable) once a topic's literature review is added to
`system/research.md`. Each entry names the source, why it matters to the
design, and what it is the direct grounding for. Nothing in this file is
implemented — ingestion means adding the raw or excerpted source under
`system/research/<topic>/`, not shipping code.

Items are worked in priority order within a topic; a later topic's queue is
appended below its own heading rather than interleaved, so priority order
stays legible per topic.

## Chronology (from `system/research/chronology.md`, v194)

1. **Belli 1998, *Memory* 6(4):383–406** — the theoretical bridge from memory structure to interview design; the direct source for sequential/parallel cueing.
2. **Freedman et al. 1988, *Sociological Methodology* 18:37–68** — the LHC's original design decisions (time units, domains, recording) and its validation data.
3. **Huttenlocher, Hedges & Bradburn 1990** — supplies the *shape* of dating error; tells us what precision to offer and how to bin coarse answers honestly.
4. **Loftus & Marburger 1983** — the canonical landmark-bounding result, including that self-supplied landmarks work; grounds playbook step 4.
5. **Friedman 1993, *Psych Bulletin*** — the review that justifies "never ask for a year first."
6. **Conway & Pleydell-Pearce 2000** — the era/period/event ontology the timeline data model should mirror.
7. **Glasner & van der Vaart 2009 review + van der Vaart & Glasner 2011** — the honest effect sizes; the source that corrected the unverified "42%→68%" claim previously in `research.md`.
8. **Brown, Rips & Shevell 1985, *Cognitive Psychology* 17:139–177** — the original demonstration that dating is inference from context.
9. **Brown et al., transition theory / living-in-history papers (2009–2021)** — when public-event cues help and when they are noise; gates the public-event probe.
10. **Portelli, *What Makes Oral History Different*** — the doctrinal source for treating contradictions as data, not defects; underwrites the no-silent-overwrite rule.
11. **OHA *Principles and Best Practices* (2018 PDF suite)** — consent, documentation, and contextualization standards for an AI that interviews.
12. **Kline & Perdue, *Guide to Documentary Editing* (chs. 3 & 5)** — conventions for conjectural dates and editorial apparatus; the model for how the wiki should *display* an inferred date.

Status: queued, none ingested yet (v194).

## Landmarks (from `system/research/landmarks.md`, v198)

The owner's 2026-08-23 question — "is there a primary set of dating questions
that always sits under the timeline, that a person can Play, and that makes
everything else placeable by arithmetic?" — is answered in
`system/research/landmarks.md`. That review also closes the "Full EHC
onboarding survey deferred" note in `system/research.md` §4a: the answer is
not a large upfront survey, it is a fifteen-question anchor set of which seven
are asked at onboarding (landmarks.md §5).

**Ingested (fetched, quoted, and cited in landmarks.md):**

1. **Freedman et al. 1988** — DONE. Full text obtained; the domain list, the
   administration order, the verbatim residence opener, and the 1980-vs-1985
   reliability numbers are all quoted in landmarks.md §1.1 and §2.4. This
   also discharges Chronology queue item 2.
2. **Add Health, Wave III Data Documentation** — DONE (§1.4). The persistent,
   editable, age-annotated calendar; Appendix D's pre-loaded public events.
3. **NLSY97 Codebook Supplement, Appendix 6** — DONE (§1.3). Five event-history
   arrays, per-domain grain, the age-14 origin.
4. **Quality principles of retrospective LHC data, 2022 (PMC9612623)** — DONE
   (§2.2, §2.3). Residence and education as the highest-accuracy domains;
   the quarterly-grid/academic-year conflict.
5. **Allen 1983, CACM 26(11)** — DONE (§3.6). The correct formal name for what
   the owner called "a binary tree": constraint propagation over interval
   relations, with "reference intervals" as the coarse containers.
6. **NCES kindergarten entrance requirements, 2018** — DONE (§2.3). The
   grade↔age↔year arithmetic and its ±1 band.
7. **SHARELIFE (SHARE wave 3) Methodology volume** — DONE (§1.5). The only
   source that states its module-order rationale outright ("ordered according
   to what is usually most important to the respondent and thus remembered
   most accurately"), the five-row calendar with the age axis, the
   six-month residence threshold, and the decade-midpoint fallback.
8. **ELSA wave 3 Life History user guide** — DONE (§1.5). The *lifegrid*,
   its module order, and per-domain grain.
9. **NEPS SC6 Data Manual + IAB FDZ-Methodenreport 05/2010 (ALWA)** — DONE
   (§1.6). Modularized collection, residences first and complete since birth,
   and the stated cost (whole-life chronology is lost) with its fix (replay
   earlier answers into later question text) — which is our `{anchors}` block.
10. **UCL CLS: NCDS age 42 and BCS70 age 42 questionnaires** — DONE (§1.7).
    Current-state-then-backwards, and the mid-season month convention
    (Winter=Feb, Spring=May, Summer=Aug, Autumn=Nov).
11. **Oral-history and genealogy intake instruments** — DONE (§1.8). LOC
    Veterans History Project Biographical Data Form, the North Dakota VHP
    question guide, the Smithsonian interviewing guide, the Montana State
    Library data sheet (sent home in advance — homework, already standard
    practice), StoryCorps *Great Questions* and Baylor's manual as the
    deliberate counter-tradition.
12. **Shum 1998, Allen 1983, Giroux 2003 (BCG), the AIA glossary** — DONE
    (§4.1, §3.2, §3.6, §2.8).

**Still queued, in priority order:**

13. **PSID Event History Calendar documentation** (`psidonline.isr.umich.edu`,
   Technical Series Papers 2007-02 and 2017-03) — the landmark-events-first
   domain hierarchy and the respondent-uncertainty findings. The PDFs sit
   behind a bot challenge; landmarks.md §1.2 cites them at indexed-text level
   only. Obtain properly.
14. **Belli, *Event History Calendar*, Encyclopedia of Survey Research
   Methods** — the "query the most easily remembered domains first" rule is
   quoted from the publisher's indexed abstract; the full entry is paywalled.
   Get the real text before this rule is treated as settled.
15. **Glasner, van der Vaart & Belli 2012** — cited at abstract level only
   (landmarks.md §5.2). The actual landmark categories and their
   Dutch-vs-American distributions are what the edge-case list needs.
   Supersedes Chronology queue item 7's second half.
16. **Next Steps and the Millennium Cohort Study** (UCL CLS) and the
    **NEPS SC6 chapter** (Drasch, Kleinert, Matthes & Ruland, *Why Do We
    Collect Data on Educational Histories Over the Life Course the Way We
    Do?*, paywalled — abstract only). The remaining instruments; also the
    only place a *causal* statement about residences-first is likely to be
    written down.
17. **Genealogical intake forms proper** — FamilySearch, Ancestry, NGS,
    StoryWorth. Not obtained; §1.8 covers the archival and oral-history
    side only.
18. **Huttenlocher, Hedges & Bradburn 1990** (Chronology queue item 3, still
    open) — landmarks.md §5.1 leans on the rounding result for "a coarse
    answer is the honest one." Ingest before the precision ladder's bin
    boundaries are fixed in code.

**Follow-ups this review opens (design, not reading):**

- **`profile.yaml` has no birth date, and no caller passes `birth_date`.**
  `chronology.from_age` is unreachable in production (landmarks.md §3.7).
  This is a live defect, not a research gap.
- **`PLAYBOOK_STEPS` rungs 5 and 6 are unreachable** for the same reason —
  they are marked `needs_anchor` and the anchor index is nearly always empty.
- **Reconcile with issue #69** ("Incremental EHC"), whose contract says to
  *replace* a large upfront chronology survey and requires an owner decision.
  landmarks.md §6.5 argues the two are compatible; the owner still decides.
- **Naming — SETTLED (owner, 2026-08-23).** landmarks.md §4.3 recommended
  *Anchors*; the owner ruled **Landmarks**, and §4.4 records why the ruling is
  better: a landmark is the question and the answer, an anchor is the derived
  index the answer becomes, and they are two things rather than two names for
  one. Shipped in v199.
- **The grade↔year rule needs a suppression condition**, not just a ±1 band
  (landmarks.md §5.2, non-linear schooling).
- **Specificity ladders per landmark** (landmarks.md §5.3, owner ruling): a
  landmark answered vaguely is *answered*, and stays open only because more
  would unlock more. Needs a data shape, not a boolean.
- **A new gap kind, `place_no_stories`** (landmarks.md §5.3): v196 made
  unknowns concrete and `place_span` already asks *when* you lived somewhere.
  Nothing yet expresses a place whose span is known and which has **no stories
  in it** — a story gap, not a dating gap, and one that only exists once a
  landmark set has named the place. Needs its own kind, `KIND_OPENERS` entry,
  and a line into the arc planner and the Mirror's gap finders.
- **Adopt the fielded coarse-answer conventions**: SHARELIFE's "ask for the
  decade and enter the mid year" and the CLS mid-season month mapping
  (landmarks.md §5.1) — both already expressible in `DateRecord`.

Status: items 1–12 ingested (v198); 13–18 queued.

## Chronological certainty, visualized (from `system/research/chronology-vis.md`, v206)

Priority order within this topic. Nothing here is implemented; ingestion means
adding the raw or excerpted source under `system/research/<topic>/`.

1. **Gschwandtner, Bögl, Federico & Miksch 2016, *TVCG* 22(1):539–548** —
   "Visual Encodings of Temporal Uncertainty: A Comparative User Study." The
   single most on-topic empirical paper for the whole design and the ONLY one
   that compares temporal-uncertainty glyphs head to head. Closed access; no OA
   copy found in the v206 session ([doi](https://doi.org/10.1109/TVCG.2015.2467752)).
   **Acquire first, through a library if necessary** — every ranking in
   `chronology-vis.md` §3.4 is currently argued from adjacent literature.
2. **Tversky, Morrison & Bétrancourt 2002, *IJHCS* 57(4)** — "Animation: can it
   facilitate?" The field's principal negative result on animation, quoted in
   §5 only through Heer & Robertson's verbatim secondary. The design consequence
   that the settle animation is presentation and not analysis rests on it.
3. **Bayliss 2015, *World Archaeology* 47(4):677–700** — "Quality in Bayesian
   chronological models in archaeology." Cited by Hamilton & Krus as the field's
   quality survey; the best single source for §1.5's pitfalls. Unreachable in
   the v206 session. Historic England's *Radiocarbon Dating and Chronological
   Modelling: Guidelines and Best Practice* is the practitioner twin and was
   likewise unreachable.
4. **Dye 2016, *JAS* 71:1–9** — the tempo plot's own paper. §1.4 cites Philippe
   & Vibet's formalisation instead, which is the safer source for the
   mathematics but not for the *argument* about what the plot is for.
5. **Ratcliffe 2002, *J. Quantitative Criminology* 18(1):23–43** — the
   "aoristic signature" paper, and the citation the software itself uses.
   Paywalled; §2 characterises it from the 1998 and 2000 papers and from
   Ashby & Bowers.
6. **Crema 2012, *JAMT* 19(3):440–461** — the Monte Carlo alternative to
   aoristic summation, and the direct ancestor of §3.3's discrete-outcome idea
   in a different field. Paywalled; characterised via Crema 2024.
7. **Priestley 1764, *A Description of a Chart of Biography*** — the full text
   IS reachable and is quoted in §3.4, but only the uncertainty passage was
   read. The rest of the pamphlet is the earliest known design rationale for a
   life timeline and deserves a full excerpt under `system/research/`.
8. **Gneiting & Raftery 2007's interval score, worked** — §4.6 names it as the
   principled scoring function for an interval estimate but does not derive its
   form. Ingest the definition and work an example against a `DateRecord`, so
   the "sharpness subject to calibration" slogan has arithmetic under it.
9. **Mountakis, Klos & Witteveen 2015 concurrent flexibility** — **THE named
   follow-up.** Already queued under Go Deep (item 6) for the PLAN; §4.4 shows
   the same correction applies to the SCORE, which raises its priority. One
   ingestion serves both. The placement score SHIPPED in v208 (ADR 0027)
   without it, which is exactly why `caveat_floor` is `True` and the copy says
   *at least this organised*: a marginal width sum overestimates disorder
   wherever ordering constraints exist, by 3× in the worked case. Ingesting
   this item and building the bipartite-matching correction is what would let
   that caveat come off — and nothing else would.
10. **A citable source, either way, on product completion meters and data
    quality** — §4.5 records that none was found. Until one exists the Goodhart
    argument stands on surrogation (Choi, Hecht & Tayler) and must say so.
11. **ISO/IEC 25012** — the data-quality model's own text, unreachable in the
    v206 session; §4.1 relies on Wang & Strong instead.
12. **Rosenberg & Grafton, *Cartographies of Time* (2010)** — the history of
    timeline forms. Lending-restricted; §3.4 uses Priestley's own words instead,
    which is stronger, but the survey would place him.

Status: queued, none ingested yet (v206). **The score itself is DONE** —
v208 (ADR 0027) implements §6 design consequences 2, 3, 5, 7, 8, 16 and 17 as
`timeline.placement_score`, and consequence 1's cloud/mark pair and 13's
per-end grading as `unknowns[].years` and `event_lineup[…][].prior_span`. What
remains on this topic is READING, not building, with item 9 the one item that
would change the arithmetic.
