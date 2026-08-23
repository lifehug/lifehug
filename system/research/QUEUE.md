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

## Go Deep (from `system/research/go-deep.md`, v197)

Priority order within this topic. Nothing here is implemented; ingestion means
adding the raw or excerpted source under `system/research/<topic>/`.

1. **Vansina, *Oral Tradition as History* (Wisconsin, 1985)** — the **floating
   gap**: the hollow that opens between living memory and origin story as
   generations pass. Cited but NOT verified in the v197 session, and it is the
   single concept most directly grounding the owner's "once my mom dies who
   knows?" — **verify first, with page numbers.**
2. **Belli, Miller, Al Baghal & Soh 2016, *JOS* 32(3):579–600** — the
   behavior-coding result that interviewer PARALLEL probes hurt while TIMING
   and DURATION probes help. It amends `chronology.md` §6 rung 5 and should be
   held as the direct source, not a summary.
3. **BCG, *Genealogy Standards* 2nd ed. rev. (2021)** — the 90 numbered
   standards. Chapter 3 ("Planning Research," standards 9–18) is the template
   for a dig plan; print-only, so excerpt what the design cites.
4. **Mills, *Evidence Explained*, 4th ed. (2024), ch. 1** — the glossary
   distinguishing negative *evidence* from a negative *finding*. Print only;
   the QuickLessons are the reachable proxy.
5. **Krause & Guestrin 2009, *JAIR* 35:557–591** — Proposition 9
   (non-submodularity of value of information) is the reason a threshold metric
   must not be the ranking objective. Ingest the proof sketch.
6. **Mountakis, Klos & Witteveen 2015, ICAPS** — the concurrent flexibility
   metric and its bipartite-matching reduction; the correction to the naive
   interval-width sum.
7. **Dechter, Meiri & Pearl 1991, *AI* 49(1–3):61–95** — the STP results and,
   equally important, the NP-hardness boundary at disjunction. Full text is
   openly hosted; ingest it.
8. **Harris, Barnier, Sutton & Savage 2018, *Topics in Cognitive Science*
   11(4)** — the coded behaviors separating successful from unsuccessful joint
   remembering (cue-and-respond vs. correction). It is what any guidance we
   give a person taking questions to a relative must be built on.
9. **Lindsay, Hagen, Read, Wade & Garry 2004, *Psychological Science*
   15(3):149–154** — genuine photographs plus suggestive interviewing produced
   the highest false-memory rate then published. The mandatory constraint on
   how a dig may ask.
10. **Golovin & Krause, adaptive submodularity, *JAIR* 42 (2011):427–486** —
    the framework that would restore a (1−1/e) guarantee for the ADAPTIVE
    greedy a dig actually runs. Unverified in the v197 session; check the
    citation before relying on it.
11. **Schober & Conrad 1997, *POQ* 61(4):576–602** — the original conversational
    interviewing experiment. Its own figures could not be retrieved; v197 uses
    the Conrad et al. 2015 replication instead. Obtain the primary.
12. **A citable key for photofinisher date stamps, paper backprint codes and
    film edge date codes** — no institutional source could be found (Kodak's
    own pages are gone). Until one exists the probe stays descriptive rather
    than interpretive (`go-deep.md` §5.1).

Status: queued, none ingested yet (v197).
