# Chronology: the domain knowledge behind Lifehug's timeline

*Research-only literature review (v194). Every claim is sourced; nothing
here is implemented yet — it feeds `system/research.md` §4a and the
research queue (`system/research/QUEUE.md`), and seeds a future `timeline`
child interaction (see `interactions/README.md`).*

## 1. How historians and biographers establish chronology

**Source criticism splits in two.** *External* criticism establishes that a source is genuine — its date, place, authorship, and material — while *internal* criticism assesses credibility: the author's ability, willingness, and bias, and whether the account is corroborated by independent accounts ([Sapiens Methodology, "Historical method"](https://metodologiasapiens.com/en/metodos/mas-informacion-metodo-historico/)). Lifehug's analogue: a memory has *provenance* (which answer, which session, which date it was captured) separate from its *credibility as a dating claim*.

**Bounding before pinning.** The workhorse instruments are *terminus post quem* (earliest possible date — "the limit after which") and *terminus ante quem* (latest possible). These yield a **relative chronology**: an interval, not a point, and the interval is itself a finding, not a failure ([Wikipedia, *Terminus post quem*](https://en.wikipedia.org/wiki/Terminus_post_quem); [Academia, *Dating in Archaeology*](https://www.academia.edu/106664648/Dating_in_Archaeology_Terminus_post_quem_and_terminus_ante_quem)). Absolute dating (a calendar date from an independent instrument) is a different and rarer thing.

**Dating undated documents.** Archivists date an undated letter from internal and physical evidence: handwriting form places it before a date, a watermark proves it cannot be *earlier* than a date, and a reference to a datable person or event yields a range ([University of Nottingham, *Undated Documents*](https://www.nottingham.ac.uk/manuscriptsandspecialcollections/researchguidance/datingdocuments/undated.aspx)). Documentary editors treat the artifact's unique physical characteristics as evidentiary, and paper, ink, and typewriter ribbon as clues to time and place ([*Guide to Documentary Editing*, ch. 3](https://gde.upress.virginia.edu/03-gde.html)). Editorial convention marks inferred dates as **conjectural** — visibly distinguished from dates the document asserts. This is exactly the precision/confidence flag Lifehug needs.

**Chronology first, narrative second.** Biographers build the timeline before the book. Hermione Lee, who organized her Woolf by theme and scene rather than straight sequence, is explicit that the chronology still has to exist underneath: "You have to have chronology, or your readers will be totally confused" ([Paris Review, *The Art of Biography No. 4*](https://www.theparisreview.org/interviews/6231/the-art-of-biography-no-4-hermione-lee)). Caro's method is exhaustive collection ("turn every page") followed by outlining as a distinct stage ([Every.to, *Note-taking Lessons From America's Greatest Biographer*](https://every.to/p/note-taking-lessons-from-america-s-greatest-biographer-8b1ebaa9-ddb0-4bd1-be42-b67f82e631f8)).

## 2. Oral history method

The Oral History Association's Best Practices ask interviewers to research the person and historical context in primary and secondary sources beforehand, to prepare "an open-ended guide or outline of the themes to be covered," to ask "follow-up questions, seeking additional clarification, elaboration, and reflection," and to **document their preparation and methods** for the record ([OHA, *Best Practices*, 2018](https://oralhistory.org/best-practices/)). Interpretation must contextualize the narrative rather than take excerpts at face value.

**The life history calendar (LHC).** Freedman, Thornton, Camburn, Alwin & Young-DeMarco (1988) designed a grid — time units across, life domains down — to collect nine years of retrospective life-course data; validated against the same respondents' 1980 contemporaneous reports, agreement on work, school, marriage, and children was high and only four calendars had any missing month ([Freedman et al., 1988](https://pubmed.ncbi.nlm.nih.gov/12282712/)).

**Why it works.** Belli (1998) argued that the calendar's power is structural: it represents the past *both thematically and temporally*, mirroring the hierarchy of autobiographical knowledge, so its cells afford retrieval cues. He named two retrieval strategies the instrument enables: **sequential** (within one domain — which employer came before which) and **parallel** (across domains — what job did you have when you lived there) ([Belli, 1998, *Memory*](https://pubmed.ncbi.nlm.nih.gov/9829098/); [Belli, EHC conference paper](https://psidonline.isr.umich.edu/Publications/Workshops/ehc-07papers/Belli_Census_EHC_Conference_final.pdf)).

**Landmarks inside calendars — a calibrated claim.** Reviews find calendar instruments generally outperform conventional questionnaires ([Glasner & van der Vaart, 2009, *Quality & Quantity* 43:333–349](https://www.researchgate.net/publication/40834894_Glasner_T_Van_der_Vaart_WApplications_of_calendar_instruments_in_social_surveys_a_review_Qual_Quant_43_333-349)). But the *landmark* component specifically produced only **weak positive effects** on accuracy, with landmarks most effective when they are important, domain-related, and personal — and the authors recommend standardizing the landmark procedure ([van der Vaart & Glasner, 2011, *Field Methods*](https://journals.sagepub.com/doi/10.1177/1525822X10384367)). Landmark availability also varies cross-culturally ([Glasner, van der Vaart & Belli, 2012](https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1653&context=psychfacpub)). **Correction for `research.md` §4a's predecessor claim:** the "42% → 68%" figure previously attributed to "Zwartz 2013" could not be located in the primary literature and has been replaced — the sourced literature shows *modest* landmark gains and *larger* whole-calendar gains.

## 3. The psychology of dating autobiographical memories

**Memory has no timestamp.** Friedman (1993) concluded that temporal memory is not a chronological store but is reconstructed by integrating episodic traces with general knowledge of time patterns and conventional time locations ([Friedman, 1993, *Psychological Bulletin* 113:44–66](https://www.researchgate.net/publication/232482132_Memory_for_the_time_of_past_events)). People *infer* dates. Brown, Rips & Shevell (1985) showed dating is reconstructive inference from accessible context, not readout (*Cognitive Psychology* 17:139–177; [related: *Reconstructive memory in the dating of personal and public news events*](https://link.springer.com/article/10.3758/BF03200929)).

**Telescoping.** Events are systematically reported as more recent than they were. Loftus & Marburger (1983) reduced forward telescoping across five experiments (1,694 subjects) by bounding the question with a landmark — "Since the eruption of Mt. St. Helens, has anyone beaten you up?" Respondents' **own personal landmarks worked comparably**, and even New Year's Day helped substantially; part but not all of the benefit came from the landmark's precise datedness ([Loftus & Marburger, 1983, *Memory & Cognition*](https://link.springer.com/article/10.3758/BF03213465)). Huttenlocher, Hedges & Bradburn (1990) modeled the bias as arising in *report construction*, not storage: people code elapsed time coarsely ("about a year ago"), the grain coarsens with distance, and **rounding plus boundary effects** generate the forward shift ([JEP:LMC 16:196–213](https://pubmed.ncbi.nlm.nih.gov/2137861/)).

**Hierarchy.** Conway & Pleydell-Pearce (2000) organize autobiographical knowledge as *lifetime periods* → *general events* → *event-specific knowledge* ([*Psychological Review* 107:261–288](https://www.researchgate.net/publication/12528554_The_Construction_of_Autobiographical_Memories_in_the_Self-Memory_System)). Lifetime periods are the natural container for Lifehug's "eras," and they are typically indexed by place, role, and relationship — which is why "when we lived in X" is a better probe than "what year."

**Transitions and living-in-history.** Transition theory holds that memory is organized around events producing high material and psychological change — changes to the people, places, things, and activities of daily life — which end one period of stability and begin another. Where a public event causes such change, people date personal memories against it (the living-in-history effect). In one study 32% of memories were publicly dated overall, but 58% among war veterans versus 28% among non-veterans — the effect scales with *personal* disruption, not with the event's fame ([*Living-in-history effect in the dating of important autobiographical memories*, 2021](https://ncbi.nlm.nih.gov/pmc/articles/PMC8631255); [Bohn & Berntsen, *Living in history and living by the cultural life script*](http://www.self-definingmemories.com/Living_in_history_and_by.pdf)).

**Distribution.** Adults over 40 recall disproportionately from ages ~10–30 — the reminiscence bump (Rubin, Wetzler & Nebes, 1986); the cultural life script explains the bump for *important, positive* memories, because scripted transitions cluster in those decades, but not for word-cued memories ([systematic review, PLOS One 2018](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0208595); [Berntsen & Rubin, cultural life scripts](https://www.semanticscholar.org/paper/Cultural-life-scripts-structure-recall-from-memory-Berntsen-Rubin/1f3b5b44fe1bb746ea18a2f3ff8f7277128bede0)).

**Design consequences:** never ask for a year first; bound with a landmark the person supplied; expect dates to drift *later*; expect grain to be coarse and to coarsen with age of the memory; and expect the 10–30 window to be dense and script-shaped, so distinctive detail there needs cueing away from the script.

## 4. When accounts disagree

Historians corroborate: compare accounts across multiple sources, prefer convergence from *independent* origins (consilience), and treat isolated or unsupported claims as weaker ([History Making, *Corroborate*](https://historymaking.org/textbook/exhibits/show/skills/evidence/corroborate); [Wikipedia, *Consilience*](https://en.wikipedia.org/wiki/Consilience)). Conflicting evidence is examined for what the conflict itself reveals about bias and perspective, not resolved by deletion. Triangulation across heterogeneous sources is the standard strategy where records are partial ([Minding the gaps, 2025](https://www.tandfonline.com/doi/full/10.1080/00076791.2025.2598410)).

Oral history goes further. Portelli's argument is that oral sources have a *different* credibility, and that discrepancies are historically significant data in their own right: "the distortions introduced by the narrator" are a subject, and attending to where memory departs from event shows how the person has made meaning of their past ([Portelli, *What Makes Oral History Different*](https://www.academia.edu/59004168/What_Makes_Oral_History_Different)). He also notes the interview itself changes what is recalled.

This is precisely Lifehug's stated principle — **memory is never silently overwritten**. The sourced form of it: a contradiction produces a *second dated claim with its own provenance*, both retained; the reconciliation conversation adds a third record (what the person said when shown both); the timeline renders the currently best-supported interval and links the alternates. Never a destructive edit, and never an AI-side silent pick.

## 5. Chronology as understanding

Narrative identity is "a person's internalized and evolving life story, integrating the reconstructed past and imagined future to provide life with some degree of unity and purpose" ([McAdams & McLean, 2013, *Current Directions*](https://journals.sagepub.com/doi/10.1177/0963721413475622)). The empirical instrument is the Life Story Interview, whose first task is **life chapters** — the book metaphor, with titles and the transitions between them. Chapters are how people already segment their own time; sequence is not bookkeeping, it is the unit of self-understanding. Lee's craft testimony (§1) confirms §2a's hybrid claim from the other direction: thematic chapters ride on a chronological spine that must exist even when it isn't the surface order.

## 6. An elicitation playbook for an AI that places memories

Ordered; stop as soon as the precision is adequate for the timeline slot.

1. **Never open with "what year."** Dating is inference (Friedman 1993); a year prompt invites a rounded, telescoped guess.
2. **Anchor to residence/role first** — "where were you living then?", "what work were you doing?" Lifetime periods are indexed this way (Conway & Pleydell-Pearce), and residence changes are prototypical transitions.
3. **Bound before pinning** — elicit a *terminus post quem* and *ante quem*: "was this before or after the move to X?", "had [child] been born?" Two bounds beat one guess and are directly storable as an interval.
4. **Prefer personal landmarks to public ones**; use public events only where they disrupted this person's daily life (transition theory; Loftus & Marburger showed personal landmarks perform comparably).
5. **Parallel-domain cue** when a domain stalls: job ↔ home ↔ relationship ↔ health (Belli's parallel retrieval).
6. **Sequential cue within a domain**: "which came first, that job or that one?" Relative order is often recoverable when dates are not — and is first-class data.
7. **Precision ladder, ascending only while cheap**: era → year-range → year → season → month. Stop at the first rung the person can hold without hedging; a hedged month is worse than a confident season (rounding/bounding, Huttenlocher et al.).
8. **Span vs point**: ask explicitly whether this was a moment or a stretch. Periods and events are different timeline objects.
9. **Capture confidence and basis, always** — `certain | inferred | conjectural`, plus the anchor used. Mark inferred dates conjecturally, as editors do.
10. **Stop rules**: stop when bounds are tight enough to place the item in its era and order it against neighbors; stop when two probes in a row return no new bound; stop on any distress signal — dating is never worth the relationship.
11. **Record provenance per claim** — session, answer id, anchor, timestamp — so the wiki can show *why* the timeline believes a date, and a later contradiction adds rather than replaces (§4; OHA's "document their preparation and methods").

This playbook is the seed for a future `timeline` child interaction (see
`interactions/README.md`); no interaction files exist yet.

---

## Sources

- Sapiens Methodology, *Historical method* — https://metodologiasapiens.com/en/metodos/mas-informacion-metodo-historico/
- Wikipedia, *Terminus post quem* — https://en.wikipedia.org/wiki/Terminus_post_quem
- University of Nottingham, *Undated Documents* — https://www.nottingham.ac.uk/manuscriptsandspecialcollections/researchguidance/datingdocuments/undated.aspx
- Kline & Perdue, *Guide to Documentary Editing*, ch. 3 — https://gde.upress.virginia.edu/03-gde.html
- Lee, H., *The Art of Biography No. 4*, Paris Review — https://www.theparisreview.org/interviews/6231/the-art-of-biography-no-4-hermione-lee
- Every.to, *Note-taking Lessons From America's Greatest Biographer* (Caro) — https://every.to/p/note-taking-lessons-from-america-s-greatest-biographer-8b1ebaa9-ddb0-4bd1-be42-b67f82e631f8
- Oral History Association, 2018, *Best Practices* — https://oralhistory.org/best-practices/
- Portelli, A., *What Makes Oral History Different* — https://www.academia.edu/59004168/What_Makes_Oral_History_Different
- Freedman, Thornton, Camburn, Alwin & Young-DeMarco, 1988, *The life history calendar* — https://pubmed.ncbi.nlm.nih.gov/12282712/
- Belli, R. F., 1998, *The structure of autobiographical memory and the event history calendar* — https://pubmed.ncbi.nlm.nih.gov/9829098/
- Glasner & van der Vaart, 2009, *Applications of calendar instruments in social surveys* — https://www.researchgate.net/publication/40834894_Glasner_T_Van_der_Vaart_WApplications_of_calendar_instruments_in_social_surveys_a_review_Qual_Quant_43_333-349
- van der Vaart & Glasner, 2011, *Personal Landmarks as Recall Aids* — https://journals.sagepub.com/doi/10.1177/1525822X10384367
- Glasner, van der Vaart & Belli, 2012, *Calendar Interviewing and the Use of Landmark Events* — https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1653&context=psychfacpub
- Loftus & Marburger, 1983, *Since the eruption of Mt. St. Helens…* — https://link.springer.com/article/10.3758/BF03213465
- Brown, Rips & Shevell, 1985/1990, *Reconstructive memory in the dating of personal and public news events* — https://link.springer.com/article/10.3758/BF03200929
- Huttenlocher, Hedges & Bradburn, 1990, *Reports of elapsed time: bounding and rounding* — https://pubmed.ncbi.nlm.nih.gov/2137861/
- Friedman, W. J., 1993, *Memory for the time of past events* — https://www.researchgate.net/publication/232482132_Memory_for_the_time_of_past_events
- Conway & Pleydell-Pearce, 2000, *The construction of autobiographical memories in the self-memory system* — https://www.researchgate.net/publication/12528554_The_Construction_of_Autobiographical_Memories_in_the_Self-Memory_System
- *Living-in-history effect in the dating of important autobiographical memories*, 2021 — https://ncbi.nlm.nih.gov/pmc/articles/PMC8631255
- Bohn & Berntsen, *Living in history and living by the cultural life script* — http://www.self-definingmemories.com/Living_in_history_and_by.pdf
- *Understanding the reminiscence bump: A systematic review*, PLOS One 2018 — https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0208595
- McAdams & McLean, 2013, *Narrative Identity* — https://journals.sagepub.com/doi/10.1177/0963721413475622
- History Making, *Corroborate* — https://historymaking.org/textbook/exhibits/show/skills/evidence/corroborate
- Wikipedia, *Consilience* — https://en.wikipedia.org/wiki/Consilience

## Research queue

Tracked as backlog, in priority order, with ingestion status: see
`system/research/QUEUE.md`.
