# Go Deep: evidence-driven dating sessions

**Removed 2026-09-03 (owner ruling R4a, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`):** the Reading Room / Go Deep leaves the product together with Go Dig; this file is deleted in Cut 2c. Add Landmark (an `offer` mode of `landmarks`, Cut 6a) replaces this line of work. Kept as history until then.

*Research-only literature review (v197). Every claim is sourced; nothing here
is implemented. It extends `system/research/chronology.md` — the domain
knowledge behind the timeline — toward two questions that document does not
answer: what happens when a person **sits down on purpose** with their photo
albums and their documents and works at their own chronology, and what happens
when the answer is not in their memory at all but in a living relative's.
Companion: `system/research/landmarks.md` (the universal dating question set;
written in parallel, referenced here, never duplicated). It also **amends
`chronology.md` §6** — see §2.3.*

## 0. The idea

> "An open session… non-inspirational, non-reflective: archaeology on my past.
> Back and forth to find dates for things like 'I don't know where or when
> first grade was.' If I tell you my birthdate and I know where I was in
> kindergarten, through dialogue we could discover dates by me placing things.
> If I'm sitting at my desk with my photo albums, I could say 'Go deep — what
> do you need to know?' and come away with homework to ask my mom. Maybe
> monthly a model evaluates where the gaps are and what finding a specific
> date would unlock… I don't want to answer a question like that every day."

And, sharpening it:

> "I don't remember half the schools I went to but if I asked around I could
> figure it out. There are mysteries to my past that are relevant now but once
> my mom dies who knows? There are mysteries about Grandma I could resolve if
> I asked my uncle, who is still living, today. Maybe this isn't even going
> deep — it's capturing and asking people who are alive now."

Three claims are embedded there. (1) A deliberate, artifact-assisted,
back-and-forth session is a real and effective way to establish a personal
chronology. (2) Its natural output is **homework** — questions carried to
another person — rather than a resolved date. (3) The system can say in
advance which unknown is worth the work.

**The short answers.** The first is not merely known practice; it is the
*dominant* professional practice in three separate fields — survey
methodology, oral history, and genealogy — which converge on almost the same
session shape from three unrelated starting points. The second is known
practice too, codified in one field (genealogy's research log) and conspicuously
absent from the field you would expect to own it (oral history). The third is
the weakest: nobody in these fields computes it, and the closest formal
machinery comes from temporal constraint reasoning and experimental design.

Two structural findings run through everything below and are worth stating
before the evidence:

* **The method is interval intersection, not date estimation.** Almost nothing
  yields a date; nearly everything yields a bound or a window. The high-yield
  questions are the ones that produce *closed* intervals cheaply — "when did
  you buy that car and when did you sell it", "when did you move in and out",
  "what's the passport's issue date", "what year did you graduate". An **empty**
  intersection is a finding, not something to average away.
* **The precision hierarchy inverts what people expect.** The photograph is
  usually the *least* precisely datable object in the box — a decade at worst,
  three to six years at best. The unglamorous paper *around* it is exact to the
  day. The session should lead with what is **near** the photo, not what is in
  it.

---

## 1. Three traditions, one session shape

**Survey methodology** builds the *instrument*: a grid with time across the top
and life domains down the side, worked conversationally by an interviewer who
holds objectives rather than a script. **Oral history** supplies the *ethics
and the conduct*: consent, the narrator's right to refuse, the etiquette of
contradiction, and the three-phase research cycle that puts verification
*between* sessions. **Genealogy** supplies the *epistemology*: a focused
research question, direct/indirect/negative evidence, a log that records what
was searched and found nothing, and a written argument when no record answers
the question directly.

None of the three is a match on its own. The design this document supports is
**genealogy's question shape and evidence discipline, conducted under oral
history's ethics, over survey methodology's calendar** — and §9 argues that
this hybrid is exactly why it needs its own name.

---

## 2. The interviewer-led chronology session

### 2.1 What the instrument is, and what the interviewer does

The event history calendar (EHC) / life history calendar (LHC) is not a
questionnaire. Belli, Miller, Al Baghal & Soh describe it exactly:

> "In calendar interviews, **instead of having questions written in advance as
> in conventional standardized interviewing, interviewers develop queries to
> satisfy questionnaire objectives that are largely visually displayed by
> timelines within various domains.** Each timeline is constructed with a
> specified unit of analysis (e.g., week, month, or year) and reference period…
> Within each timeline, queries by interviewers will seek to get respondents to
> report **periods of stability and points of transition**."
> ([Belli et al., 2016, *Journal of Official Statistics* 32(3):579–600](https://doi.org/10.1515/jos-2016-0030))

The theoretical case is Belli's: autobiographical memory is a hierarchical
network permitting retrieval "top-down in the hierarchy, **sequentially** within
life themes… and **in parallel** across life themes," while traditional survey
questions "tend to **segment related aspects of autobiographical events from one
another**" ([Belli, 1998, *Memory* 6(4):383–406](https://doi.org/10.1080/741942610)).
That claim is already in `chronology.md` §2.

### 2.2 It works, it is cheap, and the gains are uneven

The randomized evidence is genuinely good and genuinely mixed.

* **Belli, Shay & Stafford (2001)** randomized 616 PSID respondents and 20
  interviewers between an EHC and a state-of-the-art question list, validating
  against the same respondents' reports collected a year earlier: "the EHC
  condition led to better-quality retrospective reports on moves, income, weeks
  unemployed, and weeks missing work… For reports of household members entering
  the residence, and number of jobs, **the EHC led to significantly more
  overreporting**" ([*POQ* 65(1):45–74](https://doi.org/10.1086/320037)).
  Where the calendar fails, it fails by **inflating counts**.
* **Belli, Smith, Andreski & Agrawal (2007)** ran it over a **30-year**
  reference period, n=626: EHC better for cohabitation, employment,
  unemployment and smoking; the conventional questionnaire better for marriage;
  "**what variable was being measured, instead of which method was being used,
  had the biggest impact**." And the cost: "**Both EHC and CQ interviews lasted
  on average around one hour, with the EHC interviews being on average 10
  percent longer.**"
  ([*POQ* 71(4):603–622](https://doi.org/10.1093/poq/nfm045))
* The flexibility is not free: it produces "a **modest increase in interviewer
  variance**" while remaining "the preferred method"
  ([Sayles, Belli & Serrano, 2010, *POQ* 74(1):140–153](https://doi.org/10.1093/poq/nfp089)).

**Roughly one hour, ten percent longer than a rigid instrument, for materially
better retrospective data.** That is the price of the session.

### 2.3 The finding that amends our own playbook

`chronology.md` §6 rung 5 says: "**Parallel-domain cue** when a domain stalls:
job ↔ home ↔ relationship ↔ health (Belli's parallel retrieval)." The behavior-
coding evidence says the opposite about the *interviewer's* use of it.

Belli et al. (2016) coded 165 PSID calendar interviews (313 respondents aged
45+, 35,291 respondent turns, 30 interviewer and 29 respondent verbal
behaviors) against validated panel ground truth:

> "**Interviewers' use of parallel probes is associated with poorer data
> quality, whereas interviewers' use of timing and duration probes, especially
> in tandem, is associated with better data quality.** Respondents' use of
> timing and duration strategies is also associated with better data quality
> and both strategies are facilitated by interviewer timing probes."

> "**Whereas interviewer timing probes are to be encouraged, interviewer
> parallel probes are to be discouraged.** As for interviewer duration probes,
> they appear to be effective only when used **in combination with** interviewer
> timing probes… interviewer duration probes should not be administered alone."

Their explanation is that cross-domain probing "may divert respondents from
more beneficial within-domain" retrieval. The distinction is between the
*instrument* affording parallel retrieval — which is Belli 1998's claim, and it
stands — and the *interviewer* forcing it, which is a different act.

**Amendment to `chronology.md` §6, rung 5.** The rung should read: *cue with
timing and duration — "when did that start?", "when did it stop?", "how long
did that last?" — and let the person cross domains on their own.* A parallel
cue is a legitimate move only when the person has already volunteered the other
domain in this session. Note the authors' own restraint — this is
behavior-coding with a validation sample, not an experiment, and they flag
"the concern with making causal inferences" — but it is the only direct
evidence we have on the question and it points against our current rung.

A second caution from the same paper: heightened probing helps "when the
retrieval task is difficult" but produces "**poorer data quality when the
retrieval task… is relatively easy**." Over-probing an easy placement makes it
worse.

### 2.4 Conversational interviewing: pay for the hard cases only

The tradeoff between rigid and flexible interviewing has been measured
precisely, using the Schober & Conrad materials, by Conrad et al. (2015),
n=73:

> "virtual interviewers with high dialog capability led to significantly greater
> response accuracy (**74.3%**) than… low dialog capability (**60.2%**)… This was
> **entirely driven by the effect… for complicated mapping scenarios (50.9% vs
> 25.9%); in contrast, for straightforward mappings there was no effect.**"

> "a substantial increase in interview duration; **high-dialog-capability
> interviews took 7.26 min on average… compared with 5.53 min**."
> ([*Frontiers in Psychology* 6:1578](https://doi.org/10.3389/fpsyg.2015.01578))

**+14 points of accuracy overall, +25 on the hard cases, zero on the easy ones,
for +31% time.** Independently characterized: "**Respondents answer accurately
about typical situations, whether or not interviewers are licensed to clarify…
when they answer about atypical situations, their accuracy depends on whether
or not they are able to get clarification.**"
([Bell, Fahmy & Gordon, 2016, *Quality & Quantity* 50(1):193–212](https://doi.org/10.1007/s11135-014-0144-2))

The shape matters more than the magnitude, and it is the whole argument for
this being a **session** rather than a daily question: in a dating session,
*every case is a hard case*. Flexibility earns nothing on questions a person can
already answer; it earns everything on the ones they cannot.

### 2.5 A fully described session

Schatz, Knight, Belli & Mojola (2020) give the richest published account of what
one of these actually looks like — a two-hour, fold-out-grid life history
calendar with older South Africans
([*PLoS ONE* 15(1):e0226024](https://doi.org/10.1371/journal.pone.0226024)):

> "The TRHC is formatted as a **fold-out grid**, with **months across the top of
> the page and sociodemographic details and life domains down the left side**."

> "**we printed three public reference points on the TRHC**… **At the beginning
> of the interview, respondents added salient personal reference points to the
> calendar** (e.g., birth of grandchildren, the death of family members,
> retirement, moving)."

> "Throughout, **interviewers moved back and forth between domains to correct
> the timing of events**… For example, an interviewer might say, **'You said your
> husband died in March of 2015, and you also said you had an HIV test in April
> of 2015. Was your HIV test in the month after your husband died?'** The
> interviewer would then **correct the date on the calendar**."

> "**Each interview lasted approximately two hours.**"

And the honest statement of what a calendar actually buys:

> "**Respondents situate events over time in relation to one another, which
> makes it more likely that the order of events is correct, even if actual
> dates are not exact.**"

The register is worth naming: "less structured and more informal than a
standard survey interview, **but not as free form as a qualitative in-depth
interview**." That is the register a dig should hit.

### 2.6 Landmarks, calibrated

`chronology.md` §2 already records this and it is worth restating because it
bounds expectations: landmarks help, weakly. "landmarks are most effective as a
recall aid if they are **important, domain-related, and personal**… **Weak
positive effects of landmarks on recall accuracy** were also found"
([van der Vaart & Glasner, 2011, *Field Methods* 23(1):37–56](https://doi.org/10.1177/1525822X10384367)).
The whole-calendar gains are large; the landmark component's are modest.

---

## 3. Oral history: the ethics, the etiquette, and the honest gap

### 3.1 What the standard says — and what it does not

The Oral History Association's current *Best Practices* (adopted 2018) requires
research "in primary and secondary sources" beforehand, "an **open-ended guide
or outline** of the themes," advance agreement on "the approximate length of
each interview session," and that the interviewer "organize and preserve
related material for each interview—**photographs, documents, or other
records**—in corresponding interview files"
([OHA, 2018](https://oralhistory.org/best-practices/)).

**The load-bearing negative finding: the 2018 Best Practices nowhere instruct
the interviewer to bring documents or photographs into the room as elicitation
devices.** Photographs and documents appear exactly twice — as inputs to the
interviewer's *prior* research, and as material filed *afterward*. Verification
of factual claims is assigned to the *user* of the interview, not to the
interviewer in session. **An evidence-driven dating session is an extension of
practitioner convention, not an application of the OHA standard.** This
document says so rather than eliding it.

The 2018 revision also **deleted** the famous "about two hours" figure that the
superseded 2009 text carried; anyone citing it as *the* OHA standard is citing
a withdrawn document
([OHA, 2009, superseded](https://oralhistory.org/about/principles-and-practices-revised-2009/)).

### 3.2 The stronger negative: life-history practice avoids asking for dates

The Southern Oral History Program's guide is explicit:

> "**Specific dates (month, day, year of own birth or children's birth) are less
> important than a sense of chronology; avoid embarrassing the narrator by
> asking them to recall dates.**"
> ([SOHP, *A Practical Guide to Oral History*, rev. Nov 2023](https://sohp.org/wp-content/uploads/2023/11/Revised_2023_A-Practical-Guide-to-Oral-History_November2023.docx.pdf))

Mainstream life-history practice treats pressing a narrator for dates as a
**technique hazard** — it risks shame and ruptures rapport — and substitutes
sequence for calendar precision. A dig deliberately inverts this, and the
inversion is only defensible because of how it is done: **the artifact carries
the burden of the date, so the person does not have to.** "What does the back of
the print say?" is not a memory test. That single move is what makes the
inversion ethical rather than merely useful.

### 3.3 The etiquette of contradiction

Baylor's manual states the discipline's precise formulation:

> "**Challenge accounts that you think may be inaccurate, but do not question
> the narrator's memory or honesty. If you feel you must, refer to other
> accounts or interpretations you know, asking the narrator for a response or
> clarification.**"
> ([Baylor University Institute for Oral History, *Introduction to Oral History*](https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/intro_manual_2016.pdf))

SOHP gives the same move: "try approaching the topic from another angle,
**indicating contradictory information that you have obtained from other
sources**." **Attribute the challenge to the source, never to doubt about the
person.** This is directly transferable to the case where a postmark and a
memory disagree, and it is the conversational form of `chronology.md` §4's
no-silent-overwrite rule.

### 3.4 Verification belongs *between* sessions

Baylor schedules research in three phases, verbatim under the heading "When?":

> "**Before an interview (to prepare) / Between interviews (to clarify and
> verify) / After an interview (for validity and accuracy)**"

Why: "To uncover details previously undocumented, contradictory, or forgotten…
**To clarify names of people and places mentioned in an interview.**" Where:
"**Public records: deeds, probate records, map collections, military records** ·
**Private collections, including photographs and mementos** · **Newspapers;
chronologies of the time**."

**This is the discipline's own name for homework, and it puts it exactly where
the owner put it: between sittings.** Baylor even codifies the small version —
rather than interrupt for a spelling, "**jot down a phonetic spelling and a clue
to its place in the story, then after the interview ask for the correct
spelling.**"

The one thing the OHA does *not* codify is narrator-facing homework: the only
formalized handoff runs the other way, narrator → interviewer, in the
pre-interview.

### 3.5 Session logistics, converged

| Source | Session length | Sessions per narrator |
|---|---|---|
| OHA 2009 (superseded) | "most interviews last about two hours" | — |
| **OHA 2018 (current)** | **no number** — agree in advance, be flexible | — |
| SOHP 2023 | "no more than 90 minutes"; set aside two hours | "separate sessions if needed" |
| Baylor | "sixty to ninety minutes is a good average" | "over several recording sessions" |
| Oral History Society (UK) | — | "two or three sessions" |
| Schatz et al. 2020 (calendar) | "approximately two hours" | one |

**Ninety minutes of work inside a two-hour sitting, two to three sittings for a
life.** That is practitioner convention converging across independent centers —
not a disciplinary standard, since the current OHA deliberately sets no number.

### 3.6 Where testimony sits among evidence types

Relaying William W. Moss's five-way classification, Charlton notes that
transactional records — "deeds, treaties, wills, contracts, laws" — "**may be
accepted at face value**… **An oral history is not a transactional record**,"
and that photographs are *selective* records, contemporaneous but partial, of
which "**An oral history fails the test**"
([Charlton, "The Heart of Oral History: How to Interview"](https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/OHFT_Chapter3_secure.pdf)).

That is the theoretical warrant for the whole design: a certificate is
transactional (face value for its date), a photograph is selective, testimony
is recollection — weakest for calendar facts and strongest for meaning. A dig
pairs a strong-for-dates source with a strong-for-meaning one. Charlton's
symmetry caution belongs with it: documents "are not always free from bias or
error. **Indeed, sometimes they are no more reliable than tape-recorded oral
memoirs.**"

---

## 4. What objects in the room actually do

This is where the popular story and the evidence part company, and getting it
right matters because the design leans on objects.

### 4.1 The famous claim is an argument, not a finding

Harper's photo-elicitation paper argues that "photo elicitation **produces a
different kind of information**… evokes information, feelings, and memories that
are due to the photograph's particular form of representation," and that
"**Images evoke deeper elements of human consciousness than do words**"
([Harper, 2002, *Visual Studies* 17(1):13–26](https://doi.org/10.1080/14725860220137345), p. 13).

It is a methodological argument with no experiment, no control and no
measurement, and its evolutionary premise carries no citation to neuroscience.
Its empirical floor is a **1957 two-case field comparison**
([Collier, 1957, *American Anthropologist* 59(5):843–859](https://doi.org/10.1525/aa.1957.59.5.02a00100)).
Nearly four thousand citations rest on that.

### 4.2 The controlled test says the modality is not the mechanism

Koutstaal, Schacter, Johnson, Angell & Gross ran the head-to-head with older and
younger adults on videotaped everyday events, reviewed by photographs, by brief
verbal descriptions, or not at all. Both groups recalled more with review than
without — and:

> "**Verbal descriptions enhanced later recall to the same degree as reviewing
> photographs.**"
> ([*Psychology and Aging* 13(2):277–296](https://doi.org/10.1037/0882-7974.13.2.277))

**The benefit is from review and cueing, not from the image.** That is good news
for a text conversation, and it means a dig does not need the person to send a
photograph — describing it does the same work.

### 4.3 The hazard is real and it is our exact configuration

Lindsay, Hagen, Read, Wade & Garry gave half their participants **genuine**
school class photos while trying to remember two true events and one
pseudo-event:

> "the rate of false-memory reports was **dramatically higher in the photo
> condition**… **substantially higher than the rate in any previously published
> study**."
> ([*Psychological Science* 15(3):149–154](https://doi.org/10.1111/j.0956-7976.2004.01503002.x))

Corroborated by the doctored-photo line: 50% false memory
([Wade et al., 2002](https://doi.org/10.3758/BF03196318)), replicated at 40%
([Johnson et al., 2023, *Memory* 31(8)](https://doi.org/10.1080/09658211.2023.2200595)).

**Genuine photographs plus suggestive interviewing is precisely the
configuration of a dig.** This is a mandatory constraint, not an aside: the
session must never *propose* a date and ask for agreement. It elicits the
evidence and does the arithmetic; the person supplies readings, not
confirmations.

### 4.4 Memorabilia reminiscence is about wellbeing, not dates

The Cochrane review of reminiscence therapy — 22 RCTs, 1,972 participants,
intervention defined as discussion "with the aid of **tangible prompts (e.g.
photographs, household and other familiar items from the past…)**" — reports
cognition SMD 0.11 (0.00–0.23, high certainty), MMSE +1.87 points, quality of
life SMD 0.11 (n.s.), depressed mood SMD −0.03, and concludes: "**The effects of
reminiscence interventions are inconsistent, often small in size**"
([Woods, O'Philbin, Farrell, Spector & Orrell, 2018, *Cochrane* CD001120](https://doi.org/10.1002/14651858.CD001120.pub3)).

**It reports no outcome for temporal orientation, autobiographical specificity,
or dating accuracy.**

### 4.5 The honest gap, and why the design survives it

**No study was found that measures whether objects improve DATE recall
specifically.** The SenseCam literature measures episodic detail on events whose
dates the camera already timestamped — the inverse problem. That gap is real and
should be stated.

The design does not depend on closing it, because the mechanism it relies on is
different and well supported. Dating is not retrieval; it is reconstruction:

> "adults usually do this by **reconstructing when the time of an event must
> have been, given the general contextual information that is remembered**"
> ([Curran & Friedman, 2003, *Psychonomic Bulletin & Review*](https://doi.org/10.3758/BF03196536); the review is [Friedman, 1993, *Psychological Bulletin* 113(1):44–66](https://doi.org/10.1037/0033-2909.113.1.44))

> "respondents resort to **inferences** that use partial information from memory
> to construct a numeric answer"
> ([Bradburn, Rips & Shevell, 1987, *Science* 236:157–161](https://doi.org/10.1126/science.3563494))

**So an object with datable content is not a memory jog. It is evidence supplied
to an inferential process.** A print's border, a postmark, a VIN — these do not
help someone remember a date. They let the system *compute* one. That reframing
is what licenses the genealogical apparatus (§7) as the right model rather than
the memory-cueing literature.

Two arithmetic facts bound how much the session should trust unaided memory.
Telescoping is not bias but growing error: the model "**assumes no systematic
errors in dating**," with "errors in dating, though unbiased, **increas[ing]
linearly with the time since the dated event**," measured at **0.4 days per day
of delay**, directed "toward the middle of the interval"
([Rubin & Baddeley, 1989, *Memory & Cognition* 17(6):653–661](https://doi.org/10.3758/BF03202626)).
And format matters: "events dated in the **absolute** time format were more
accurate than those dated in the **relative** time format," with a large forward
telescope for remote events
([Janssen, Chessa & Murre, 2006, *Memory & Cognition* 34(1):138–147](https://doi.org/10.3758/BF03193393)).
**Always elicit absolute dates; never let "about N years ago" be the convenient
path.**

---

## 5. How you actually date a thing

The methods below are what a dig runs on. Each is reported with its honest
precision, because the whole method is interval intersection and an
over-claimed interval poisons every intersection it enters.

### 5.1 Photographs — the coarse layer

Process identification places a print in a 20–40 year window: albumen "from
1850… the most common type of print for the next 40 years"; gelatin-silver
"developed in the 1870's… by 1895 had generally replaced albumen"; platinum
1873 to the 1920s; autochrome from 1904
([V&A, *Photographic Processes*](https://www.vam.ac.uk/articles/photographic-processes);
identification authorities per [Library of Congress](https://www.loc.gov/preservation/care/photo.html)).
**Precision: decade.** It is a floor method.

Card-mounted portraits do much better, because their features are independent
and intersect. Carte de visite (2⅜ × 4¼", 1859–1882): square corners are
pre-1870, rounded 1870+; image under ¾" is 1860–64, filling the card 1874+;
border style moves from none (1860–62) through thin double lines to very thick
(1874–80). Cabinet card (6½ × 4¼", 1866–1900): dark maroon/black/green mounts
are 1885–95; scalloped edges 1886–1900; ornate cursive front imprints 1882–1900
([Clark, PhotoTree](http://www.phototree.com/ID_CDV.htm), from a corpus of ~1,000
dated examples). **A single feature gives 3–8 years; intersecting three or four
typically lands within 2–4.** This is the canonical demonstration of the method.

The sharpest single observation in nineteenth-century photo dating is a tax
stamp: "From August 1864 to August 1866 photographs were taxed… **If stamp is
present, picture is from 1864 – 1866.**" **A 24-month window from one binary
question** — though absence proves nothing, since stamps fall off.

Real photo postcards carry a stamp box whose design is a crowd-sourced dating
key: AZO with diamonds in the corners is 1907–1909 (a ~3-year window); AZO with
four triangles pointing up 1904–1918; "KODAK" is 1950–present, i.e. nothing
([Playle's *Real Photo Postcard Stamp Box Dating Guide*](https://www.playle.com/realphoto/)).
**State the width, never the bare range.**

**Sharp step functions are the best value on any printed ephemera**, and they
generalize far past postcards — to letterhead, invitations, business cards,
envelopes: two-digit postal zones ("Des Moines **17**, Iowa") from **1943**;
five-digit ZIP from **January 1963**; ZIP+4 from **October 1983**
([Playle's, *How To Date U.S. Postcards*](https://www.playle.com/datingpostcards.php)).
A printed ZIP+4 means *not before Oct 1983*, full stop.

Negatives carry manufacturer-dated transitions. Kodak sold nitrate flexible
negatives from **August 1889**, discontinuing by format — 35mm roll **1938**,
portrait/commercial sheet **1939**, film packs **1949**, 616/620 roll **1950**;
16mm, regular 8 and super 8 were **always** safety base; a **"V" notch** on
pre-1949 Kodak sheet film indicates nitrate, a **"U" notch** acetate; cellulose
triacetate is **1945–present**
([Fischer, NEDCC Preservation Leaflet 5.1](https://www.nedcc.org/free-resources/preservation-leaflets/5.-photographs/5.1-a-short-guide-to-film-base-photographic-materials-identification,-care,-and-duplication)).
With the trap stated in the source: "**just because you see the words acetate or
safety does not guarantee your item is acetate**" — edge printing dates the
original, not necessarily the object in hand. **These give hard bounds, not
dates.**

Contextual dating gives **lower bounds only**, and cheaply: any car, television,
telephone, appliance, console, sign or branded product in frame means "not
before." Where the car was the family's, the VIN converts this to near-certainty
— position 10 of a 17-character VIN encodes the model year, "**irrespective of
the calendar year in which the vehicle was actually produced**"
([49 CFR §565.15, §565.12](https://www.law.cornell.edu/cfr/text/49/565.15); the
standard begins in 1981 per [NHTSA's decoder](https://vpic.nhtsa.dot.gov/decoder/)).
But the real prize is the **ownership bracket**: "when did you buy it, when did
you sell it" closes the interval on *every* photo the car appears in. Clothing
and hairstyle are a soft prior (roughly ±5 years within a known era, worse for
men, children, and rural or working-class subjects) and should never be
presented as more. Children's apparent ages are weak individually (±1–2 years)
but powerful **jointly**: several siblings of known birthdates in one frame
intersect to something much tighter, because the gaps are known exactly even
when the absolute ages are not.

**Not verified, and the document should say so:** photofinisher date stamps on
print borders and backs, Kodak/Fuji paper backprint codes, and film edge
date-symbol codes. These are genuinely useful — a border stamp is often an
exact month and year — but no citable institutional key could be found (Kodak's
own pages are gone). **The correct instruction to a dialogue system is
descriptive, not interpretive: "read me everything printed on the border and the
back, exactly as it appears," and let the person's reading stand as evidence.**

### 5.2 Digital metadata — mostly a trap

Three fields, three meanings, and the difference decides everything:

* **`DateTimeOriginal`** (0x9003) — "The date and time when the original image
  data was generated. For a DSC the date and time the picture was taken."
* **`DateTimeDigitized`** (0x9004, ExifTool's `CreateDate`) — "when the image was
  stored as digital data." **For a scanned print this is the scan date.** This
  is the single most important trap in the domain.
* **`ModifyDate`** (0x0132) — last edit. Filesystem mtime is not EXIF at all.
  ([CIPA DC-008-2012, Exif 2.3](https://www.cipa.jp/std/documents/e/DC-008-2012_E.pdf);
  [ExifTool EXIF tag names](https://exiftool.sourceforge.net/TagNames/EXIF.html))

**Timezones did not exist in the format until 2016.** Exif 2.3 (2012) contains no
offset tag of any kind; `OffsetTime` (0x9010), `OffsetTimeOriginal` (0x9011) and
`OffsetTimeDigitized` (0x9012) appear by Exif 2.32
([CIPA DC-X008-2019](https://www.cipa.jp/std/documents/e/DC-X008-Translation-2019-E.pdf)),
introduced in 2.31 of July 2016
([Library of Congress FDD000618](https://www.loc.gov/preservation/digital/formats/fdd/fdd000618.shtml)).
**Every photograph taken before mid-2016 carries a bare local wall-clock reading
with no recoverable zone.** And all of these tags are **optional** — a
conformant image may carry no capture date at all.

The one absolute anchor is satellite time: `GPSDateStamp` and `GPSTimeStamp`
record UTC from the fix, immune to clock drift, unset clocks and zone ambiguity.
Where present, that is ground truth.

Reliability ranking, highest to lowest: GPS date/time · `DateTimeOriginal` with
offset (post-2016) · `DateTimeOriginal` alone (day, fuzzy time) · **in-camera
file sequence number** (ordering is absolute even when every date is wrong) ·
`DateTimeDigitized` (only after establishing the image is born-digital) ·
`ModifyDate` · **filesystem mtime, which is worthless** — ExifTool "**set[s] all
filesystem times to the current date/time** when any 'real' tag is written"
([ExifTool FAQ 24](https://exiftool.org/faq.html)) and every copy resets it.
Anything routed through Facebook, Twitter, Instagram or LinkedIn should be
assumed stripped
([IPTC Photo Metadata social-media test](https://www.embeddedmetadata.org/social-media-test-results.php);
the published round is 2015, so directionally right and numerically stale).

The film analogue of the sequence number is exact and worth stating in the same
breath: **frame numbers on a negative strip impose the same total order**, and a
24- or 36-exposure roll is a bounded time container — often one trip or one
season — so a single dated frame constrains the whole roll.

### 5.3 School-year arithmetic — the highest-yield computation

Given birthdate *B*, cutoff *C*, calendar year *Y*:

```
K  = B.year + 5   if (B.month, B.day) ≤ C   else  B.year + 6     # kindergarten fall
grade in the school year beginning fall Y   =  Y − K             # 0 = kindergarten
on-time graduation                          =  spring of K + 13
inverse: graduated June G  →  K = G − 13  →  born in the 12 months ending at C of year K−5
```

Roughly 24 states use **Sept 1** and four more Aug 31 — about 60% of states
cluster there — but Aug 1 (AR, IN, KY, MO, ND), Sept 30 (DC, LA, NE, NV, VA),
Oct 1 (CO), Oct 15 (ME) and **district-set** (MA, NH, NJ, NY, PA, VT) are all
live, and the district-set states are the populous ones
([Education Commission of the States, *50-State Comparison: State K-3 Policies*, Sept 2020](https://reports.ecs.org/comparisons/state-k-3-policies-08);
cf. [NCES *State Education Reforms* Table 5.3](https://nces.ed.gov/programs/statereform/tab5_3.asp),
"entrance dates vary from July 31 to January 1"). **Ask for the city, not just
the state**, and apply the cutoff in force in the entry year, not today's.

The formula breaks for about one adult in five. Redshirting is **4–5%**,
declining to **3.5%** by 2012, and "**more than 70% of redshirted children were
summer-born**"
([Bassok & Reardon, 2013, *EEPA* 35(3)](https://eric.ed.gov/?id=EJ1015022);
[Huang, 2015, *AERA Open* 1(2)](https://eric.ed.gov/?id=EJ1194856)).
Retention is **2.1% annually** in 2022, 2.9% in 1994, peak 3.1% in 2001
([NCES *Digest* 2023, Table 225.90](https://nces.ed.gov/programs/digest/d23/tables/dt23_225.90.asp)),
clustered in K–1 and grade 9 — so on the order of 10–20% of US adults were held
back at least once. **The system must therefore never silently derive a
graduation year: derive it, state it, and ask.**

The school year itself is 180 instructional days in most states, starting after
Labor Day in MI/MN/VA, no earlier than the fourth Monday of August in TX, the
third Monday in SC
([NCES Table 5.14](https://nces.ed.gov/programs/statereform/tab5_14.asp)). So
"third grade" is a 9–10 month interval crossing a calendar boundary.

Records: yearbooks (the printed year is the *ending* calendar year), report
cards (to the quarter), class portraits (studio stamps often print "1988–89"
and the grade), diplomas and commencement programs (**exact day**), immunization
records (**exact day**, and school-entry and 7th-grade boosters anchor ages 5
and ~12), enrollment forms (day **plus the address on file**, which cross-keys
into §5.4). FERPA gives former students a right to inspect, with a response
"**within a reasonable period of time, but not more than 45 days**" and no fee
"**to search for or to retrieve**"
([34 CFR §§99.3, 99.10, 99.11](https://www.ecfr.gov/current/title-34/subtitle-A/part-99))
— but **FERPA sets no retention period**. State schedules do, and they split
sharply: Texas keeps grades 9–12 academic records **permanently** and Pre-K–8
cumulative records only **5 years after withdrawal**
([Texas Local Schedule SD](https://www.tsl.texas.gov/slrm/localretention/schedule_sd)).
**Ask the institution for high school; ask the person for K–8.**

### 5.4 The residence spine

Each residence is an interval `[move_in, move_out]`, and any artifact whose
*setting* is identifiable — the kitchen, the porch, the car in the driveway —
inherits it. This composes with §5.3's school intervals and §5.1's object
bounds, and in Genealogical Proof Standard terms it is **correlation** (§7).

What actually dates a residence:

| Source | Precision | Reach |
|---|---|---|
| Recorded deed | **day** of recording (±1–2 months for occupancy) | permanent; online indexes ~1980s+ |
| Lease / first utility bill | **day** | only what the person kept |
| Credit report "previous addresses" | month or year | reliable ~7–10 years, spotty beyond |
| USPS change of address | **day** | **4 years, full stop** |
| City directory | year, with a ~1-year publication lag | 1800s–~1995 |
| Federal census | decade snapshot | **72-year embargo**; 1950 released 2022, 1960 opens **April 2032** |
| Tax return / W-2 address | year | whatever the person kept |

Sources: [Texas Local Schedule CC](https://www.tsl.texas.gov/slrm/localretention/schedule_cc)
(deed records **PERMANENT**); [15 U.S.C. §1681j](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681j)
and [CFPB](https://www.consumerfinance.gov/ask-cfpb/what-is-a-credit-report-en-309/)
("Current and former addresses" — note addresses are not adverse items and have
no statutory purge date, so persistence tracks the tradelines that reported
them); [USPS SORN 800.000, 87 FR 59128](https://www.federalregister.gov/documents/2022/09/29/2022-21101/privacy-act-of-1974-system-of-records)
("**National change-of-address and mail forwarding records are retained 4 years
from the effective date**"); [FamilySearch, *United States Directories*](https://www.familysearch.org/en/wiki/United_States_Directories);
[U.S. Census Bureau, *Census Records*](https://www.census.gov/about/history/census-records-family-history/census-records.html).

Three calibrations that matter more than any of the sources: people remember the
**sequence** of homes far better than the years — build the ordered list first
and attach years afterward; moves **cluster in summer** because schools drive
them, which is a usable prior; and **transition artifacts** (moving day, the
empty rooms, the first night) are the highest-value photographs in any album, so
ask for them by name.

### 5.5 The paper around the photograph

This is where the precision inversion bites. In rough order of value:

**Postmarks.** "A postmark is a marking applied by the Postal Service… the
postmark displays the name or location of the processing facility and **the date
of the first automated-processing operation**" — with the caveats stated in the
same section: "the Postal Service **does not postmark all mail**," postmarks "**do
not necessarily represent either the place at which, or the date on which**" the
mail was accepted, and the date "may be **later**"; bulk precancels may show
"**the month and year** only"
([USPS DMM §608.11](https://pe.usps.com/text/dmm300/608.htm), [§604.3.4.6](https://pe.usps.com/text/dmm300/604.htm)).
**Exact day, upper-bounded lag — and the date is on the envelope, which is what
people throw away.** A handwritten letter date is composition; the postmark is
processing; the pair brackets.

**Passports.** An adult passport is "valid for **ten years** from date of issue,"
under-16 "**five years**" ([22 CFR §51.4](https://www.law.cornell.edu/cfr/text/22/51.4)).
The issue date therefore brackets **every stamp inside it** — a free, exact,
ten-year container. Worth flagging as a future loss: from 2026 the Schengen
Entry/Exit System replaces manual stamping, recording "**the date and place of
entry and exit**" in a database retained **three years**
([European Commission, EES](https://home-affairs.ec.europa.eu/policies/schengen/smart-borders/entry-exit-system_en);
[Regulation (EU) 2017/2226 Arts. 16, 34](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32017R2226)).
The durable personal record becomes the boarding pass, not the passport.

**Church registers — the longest-lived record a person can touch.** "Each parish
is to have parochial registers… of baptisms, marriages, deaths"; the baptismal
register is **annotated** with confirmation, marriage, adoption and holy orders;
"**Older parochial registers are also to be carefully protected**"
([*Code of Canon Law*, Can. 535](https://www.vatican.va/archive/cod-iuris-canonici/eng/documents/cic_lib2-cann460-572_en.html)).
**No retention cutoff exists — these are permanent by design**, and one baptismal
entry accumulates a whole life's sacramental dates in one place.

**Medical and immunization records.** Hospital records retained "**at least 5
years**" federally ([42 CFR §482.24(b)](https://www.law.cornell.edu/cfr/text/42/482.24)),
seven in California with a minority extension
([22 CCR §70751](https://www.law.cornell.edu/regulations/california/22-CCR-70751)),
with a HIPAA right of access acted on "**no later than 30 days**"
([45 CFR §164.524](https://www.law.cornell.edu/cfr/text/45/164.524)). **Exact
day** — which is exactly why §6.4's privacy line applies hardest here. State
immunization registries mostly date from the late 1990s: Michigan's says plainly
"**If you were born before 1994, the registry is unlikely to have your childhood
immunizations**" ([MCIR](https://mcir.org/public/)) — before that it is the paper
card in the baby book or nothing.

**Bank and phone records.** BSA records are retained "**for a period of five
years**" ([31 CFR §1010.430(d)](https://www.law.cornell.edu/cfr/text/31/1010.430));
Reg E requires "not less than two years." Carrier retention, from the best public
source and now sixteen years stale, ran roughly 1–7 years for call and text
*detail* and **days** for text *content*
([DOJ CCIPS, *Retention Periods of Major Cellular Service Providers*, Aug 2010](https://www.aclu.org/files/pdfs/freespeech/retention_periods_of_major_cellular_service_providers.pdf)).
**Exact day; posting date may lag the transaction.**

**Email — the richest modern spine and the most under-used.** Gmail supports
`after:2004/04/16`, `before:`, `older_than:1y`
([Gmail search operators](https://support.google.com/mail/answer/7190)); consumer
webmail is rarely purged, so early adopters hold a continuous 20-year record of
receipts, bookings, e-tickets and "photos from the weekend." Booking
confirmations are doubly valuable because they carry **both** the purchase date
and the future stay date — the bracketing structure the whole method wants.

**Social media, with a systematic trap.** Upload date ≠ event date, and "On This
Day" resurfaces the anniversary of the *post*. And a genuine loss worth naming:
Google Location History — for a decade the most precise passive life-dating
spine any consumer possessed — moved on-device with a **three-month** auto-delete
default in 2023 ([Google, Dec 2023](https://blog.google/products-and-platforms/products/maps/updates-to-location-history-and-new-controls-coming-soon-to-maps/)).
**An old `Location History.json` in someone's downloads folder is now a rare and
valuable artifact**, and the session should ask about it early.

**Tickets and stubs** print an exact date by design, but thermal stubs fade
within about a decade — which is why 1990s stubs are often blank rectangles. A
faded stub is still usable if the venue and act are legible, since setlist
databases index ~10.4M setlists with `eventDate` back to the 1960s
([setlist.fm](https://www.setlist.fm/), [API](https://api.setlist.fm/docs/1.0/json_Setlist.html)).

**Greeting-card manufacturer date codes are folklore.** No authoritative public
key exists. The reliable evidence on a card is human: a signed year, or the
envelope's postmark.

### 5.6 The privacy line

The distinction the design turns on is **derivation versus ingestion**, and it
falls straight out of data-protection first principles. GDPR Art. 5(1)(c)
requires data "**limited to what is necessary** in relation to the purposes,"
and Art. 25(2) makes it the default — "by default, only personal data which are
necessary for each specific purpose of the processing are processed," expressly
covering "the amount of personal data collected… the period of their storage and
their accessibility" ([GDPR Arts. 5, 25](https://gdpr-info.eu/art-5-gdpr/)). The
ICO's gloss is the operational test: "identify the **minimum amount** of personal
data you need to fulfil your purpose. You should hold that much information, but
no more… **You must not collect personal data on the off-chance that it might be
useful in the future**"
([ICO, *Data minimisation*](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/data-minimisation/)).

Most of §5.5's records are **Art. 9 special-category data** — health data,
religious belief (a baptismal register), biometric passport data — whose
processing "shall be prohibited" absent an exception
([GDPR Art. 9](https://gdpr-info.eu/art-9-gdpr/)). And the OHA adds a third-party
obligation: narrators need "consideration given to any **third parties discussed
within the recording**," with the 2025 revision introducing **rolling consent**,
"reestablish[ed] or change[d] as requested."

**The consequence is clean.** When the purpose is *pin a date*, the necessary
datum **is the date**. A person reading a document aloud — "the postmark says
Denver, March 3, 1987" — with the system storing only that derived fact
satisfies Art. 5(1)(c) and 25(2) **by construction**. Ingesting the document
image captures diagnoses, account numbers, third parties' names and biometrics
the purpose never required, converts ordinary data into Art. 9 data, and
triggers the third-party obligation. **Default to read-aloud. Ask for the date
first and the document type second** — which is, conveniently, also the shortest
exchange.

---

## 6. The unknown that is not yours to answer

> "There are mysteries to my past that are relevant now but once my mom dies who
> knows? There are mysteries about Grandma I could resolve if I asked my uncle,
> who is still living, today."

This is a different failure mode from every unknown the timeline models. Better
probing will never place it; one question to a relative will. It has a different
remedy and — uniquely in this whole document — a **clock**.

### 6.1 Is "ask the eldest first" codified?

**Once, and remarkably strongly: in US federal statute.** The Veterans' Oral
History Project Act finds that "of the some 6,000,000 veterans of World War II
alive today, **almost 1,500 die each day**," and then *orders age-based triage*:

> "**(c) Timing.**—As soon as practicable after the enactment of this Act, the
> Director shall begin collecting… and **shall attempt to collect the first such
> recordings from the oldest veterans**."
> ([Pub. L. 106-380, 20 U.S.C. §§2141–2144](https://www.govinfo.gov/content/pkg/PLAW-106publ380/html/PLAW-106publ380.htm))

The 1,500/day figure is a 2000-era congressional finding and should be cited as
such. Worth noting: the programme's present-day public description carries no
urgency framing at all — the argument lives in the founding statute.

Genealogy's version is blunt and institutional but **is not a standard**.
FamilySearch has a section literally headed "**Interview old people now. We
never know when they may die**" and "**Do what you can as soon as you can**"
([FamilySearch, *Speak with Your Family*](https://www.familysearch.org/en/wiki/Speak_with_Your_Family)),
and elsewhere: "**We recognized how critical it was to preserve the history
before the person passed away**"
([*Oral Genealogies*](https://www.familysearch.org/en/wiki/Oral_Genealogies)).

**The meaningful negatives.** The Board for Certification of Genealogists'
90 numbered standards contain **no standard about interviewing relatives or
sequencing by informant age** — standards 9–18 sequence *sources*, not *people*.
And the OHA gives exactly one narrator-selection criterion, and it is topical:
relevance of experience plus diversity of voices. **Age and health appear
nowhere in the OHA corpus as selection criteria.** So: statutory in one place,
folk wisdom everywhere else, and absent from both certifying bodies.

### 6.2 Does memory really have a horizon?

Three genuinely scholarly concepts converge on roughly the same depth by
completely unrelated routes: **structural amnesia**
([Goody & Watt, 1963, *Comparative Studies in Society and History* 5:304–345](https://doi.org/10.1017/S0010417500001730)),
Vansina's **floating gap** (*Oral Tradition as History*, Wisconsin, 1985 —
**cited but not verified in this session; verify before relying on it**), and
Assmann's **communicative memory**, bounded at roughly 80–100 years or three to
four generations
([Assmann & Czaplicka, 1995, *New German Critique* 65:125–133](https://doi.org/10.2307/488538)).

**That convergence is the real argument.** The popular "you'll be forgotten in
three generations" claim is a degraded restatement of it, and the consumer
surveys circulated by genealogy companies are marketing, not evidence — they
show the anxiety is widespread, nothing more.

### 6.3 What happens when you actually ask your mother

The literature here is more encouraging than its reputation, provided you ask
the right way.

**Collaborative inhibition is real but is not a threat to a targeted question.**
The meta-analysis (75 effect sizes, 64 studies) finds the effect "robust," and
enhanced "in **larger groups**… **uncategorized** content… **free-flowing and
free-order** procedures… [and] when **group members did not know one another**"
([Marion & Thorley, 2016, *Psychological Bulletin* 142(11):1141–1164](https://doi.org/10.1037/bul0000071);
originals: [Weldon & Bellinger, 1997](https://doi.org/10.1037/0278-7393.23.5.1160),
[Basden et al., 1997](https://doi.org/10.1037/0278-7393.23.5.1176)).
**Read the moderators backwards and you have a design spec**: inhibition is
weakest in dyads, on structured material, with imposed order, between people who
know each other well. Retrieval-strategy disruption is a claim about competing
*organizational schemes* during free recall; "what year did we move to the house
on Maple?" supplies the structure externally, so there is nothing to disrupt.

The same meta-analysis finds that "**collaborative remembering tends to benefit
later individual retrieval**," partly through re-exposure. So the open
reminiscing mode still pays — just on a delayed, individual ledger. **It is
priming for the next solo session, not a harvest.**

| | Reminiscing together | A specific dating question |
|---|---|---|
| Task shape | free-flowing, unordered | structured, single target |
| Predicted inhibition | **high** — the maximal condition | **near zero** |
| What you get | rich detail, poor coverage | the fact, if it is held |

**Personal relevance flips the sign.** Harris, Barnier, Sutton, Keil & Dixon
studied 19 couples (ages 69–86, married a mean 50.7 years) recalling shared
trips: collaboratively they recalled **16.79% fewer** items where alone they
gained 16.01% (F(1,17)=9.27, p=.007) — while **specific episodic details rose
from 3.27% to 13.36%**, and the two traded off directly, **r=.81, p=.005**. The
authors: "couples **abandon the relatively mundane task of creating a list for
the much more engaging and relationship-building task of reminiscing
together**," which "provided a **strong match between encoding and retrieval**…
that **could not be provided by an interviewer**"
([*Memory* 25(8):1148–1159](https://doi.org/10.1080/09658211.2016.1274405)).
A companion study of 39 couples found "**clear collaborative benefits**"
increasing with personal relevance — greatest on **names of mutual friends** —
and that collaborative success was "**extremely stable over time**… a stable
couple-level difference"
([Barnier, Harris, Morris & Savage, 2018, *Frontiers in Psychology* 9:2385](https://doi.org/10.3389/fpsyg.2018.02385)).

**And the behaviors that separate good from bad joint remembering are coded.**
Successful: **cuing each other, responding to cues, repeating each other**, plus
positive statements about memory performance and persistence. Unsuccessful:
**correcting each other, uneven expertise, strategy disagreements** — the
"monologue" style
([Harris, Barnier, Sutton & Savage, 2018, *Topics in Cognitive Science* 11(4)](https://doi.org/10.1111/tops.12350)).
If any guidance is offered to a person taking questions to a relative, it should
be *cue, don't correct*.

### 6.4 How much to trust what the relative says

**Discrete, witnessed, publicly-marked facts survive decades almost intact.**
Maternal recall at **30+ years**: birthweight r=0.91 (validity) / 0.94
(reproducibility), height r=0.90
([Tomeo et al., 1999, *Epidemiology* 10(6):774–777](https://doi.org/10.1097/00001648-199911000-00022)).

**Gradual, judgment-laden ones do not, and they drift LATER.** Against a
prospective 12-month criterion, correlations for "first steps" fell from 0.74
(3 yrs) to 0.41 (5 yrs), and for "first meaningful word" from 0.27 to **−0.11**;
**20% of parents were off by ≥6 months (mean error 9.4 months), and every one of
those errors was in the later direction**
([Majnemer & Rosenblatt, 1994, *Pediatric Neurology* 10(4):304–308](https://doi.org/10.1016/0887-8994(94)90126-0)).
The motor/language split replicates 17 years later — telescoping for language
milestones, "little evidence of consistent telescoping for age of first concern,
daytime bladder control, or independent walking"
([Hus, Taylor & Lord, 2011, *JCPP* 52(7):753–760](https://doi.org/10.1111/j.1469-7610.2011.02398.x)).

**Ask relatives about events, not about processes.** "What year did we move?" is
a discrete, witnessed, publicly-marked fact. "When did I start reading?" is not.

The study that is exactly this use case: 333 mother–daughter pairs, daughter
reporting her own childhood and mother reporting as proxy — birthweight ICC
0.86, weight at 18 ICC 0.71, but childhood socio-economic position κ=0.14–0.20,
concluding that proxy reports should be used **in conjunction with** the index
report, not as a replacement
([Straughen et al., 2013, *Paediatric and Perinatal Epidemiology*](https://doi.org/10.1111/ppe.12045)).
**That is a direct empirical warrant for "homework for your mother" over "ask
your mother instead."**

### 6.5 Who holds what — and an honest limit

Transactive memory theory supplies the abstraction: a group stores not facts but
**who holds which facts**, and retrieval is locate-then-query
([Wegner, Erber & Raymond, 1991, *JPSP* 61(6):923–929](https://doi.org/10.1037/0022-3514.61.6.923);
[Wegner, 1987](https://doi.org/10.1007/978-1-4612-4634-3_9)). A witness list is
that directory, made explicit and external.

Kinkeeping is well established as a gendered relational role
([Rosenthal, 1985, *JMF* 47(4):965](https://doi.org/10.2307/352340);
[Hornstra & Ivanova, 2023, *Sex Roles* 88(7–8), N≈2,700](https://doi.org/10.1007/s11199-023-01352-2)),
and mothers do more of the memory *talk*
([Fivush, 2011, *Annual Review of Psychology* 62:559–582](https://doi.org/10.1146/annurev.psych.121208.131702);
[Leaper, Anderson & Sanders, 1998, *Developmental Psychology* 34(1):3–27](https://doi.org/10.1037/0012-1649.34.1.3),
d≈.19–.26).

**But nobody has measured who holds accurate dates.** Kinkeeping is operationalized
as buying presents, organizing outings, relaying news; the reminiscing literature
measures *talk*, at small effect sizes with wide overlap. **"Mothers hold the
chronology" is a design assumption, not a finding, and must not inherit the
authority of a d=.26 about conversational style.**

On siblings the evidence is **absent** in both directions. The adjacent
literature points the other way: siblings raised in the same household
experience and report it differently
([Plomin & Daniels, 1987, *BBS* 10(1):1–16](https://doi.org/10.1017/S0140525X00055941)).
**A sibling is a witness to a different childhood, not a redundant copy of the
same one** — complementary testimony rather than corroborating. That reframing
is an inference, not a finding, but it is the right default.

### 6.6 The ethics of handing someone a question list

The OHA does not exempt family or amateur interviewers — it extends to them:
the association covers practitioners "**including many who might not label
themselves oral historians**," and "**First-time interviewers should seek
training**." Narrators "**voluntarily give their consent**… and understand that
they **can withdraw from the interview or refuse to answer a question at any
time**," and "**Interviewees hold the copyright to their interviews**."

**Stated bluntly: if a product hands someone a question list to take to their
mother, the OHA's position is that the person is an oral historian for that
purpose and the mother is a narrator with the full set of narrator rights.**

The one verified instance of narrator-facing "go find things" homework is the
Library of Congress's own DIY kit: "**Spark your memory by searching your home
for documents and photographs from your service days**," alongside "**meet with
the veteran in advance… help formulate interview questions that are
personalized**"
([LOC Veterans History Project Field Kit, 2013](http://web.archive.org/web/20140719005524if_/http://www.loc.gov/vets/pdf/fieldkit-2013.pdf)).
StoryCorps takes the same posture — "**Start by asking Great Questions**… use the
ones you like and **come up with your own**" ([Great Questions](https://storycorps.org/participate/great-questions/))
— and pointedly grounds its rationale in honour and relationship rather than
mortality, a deliberate tonal contrast with Pub. L. 106-380 worth copying.

**And the sharpest craft warning in the whole document**, from an institution
that has watched people get this wrong for decades:

> "**Don't send form letters. Don't send unfamiliar blank genealogical forms,
> especially with the first letter. Be reasonable. Don't ask for too much at
> once. Ask simple, straightforward questions.**"
> ([FamilySearch, *Gather Family Information*](https://www.familysearch.org/en/wiki/Gather_Family_Information))

That names the exact failure mode of an auto-generated homework list. The same
page closes with the rule that should govern the return path: "Ask the person
you interviewed to **read your notes and correct them. Give the person you
interviewed a copy.**"

### 6.7 The two question norms, and which to borrow

No source endorses closed factual questioning as an *oral history* mode, and the
OHA is actively hostile to it — oral history "seek[s] an **in-depth account of
personal experience and reflections**." But the LOC's own DIY kit opens with
"Where and when were you born?"; FamilySearch's family-interview set is
unembarrassedly date-seeking ("What year were they born?" · "Where did your
father and mother live, and when did they live there?"); and BCG **Standard 10 is
titled "Effective research questions."**

**The honest framing: two disciplines, two question norms, because two purposes.
"Always ask open questions" is oral history's rule for oral history's goal.
Evidence-driven dating borrows oral history's ETHICS — consent, refusal,
copyright, review — and its CONDUCT, and genealogy's QUESTION SHAPE.**

---

## 7. Genealogy's apparatus — the closest existing model

Genealogy is the discipline that has most rigorously formalized *how you
establish a date when there is no direct record*, and its machinery maps onto
this design almost one-to-one.

**The Genealogical Proof Standard**, verbatim: "1. **Reasonably exhaustive
research.** 2. **Complete and accurate source citations.** 3. **Thorough analysis
and correlation.** 4. **Resolution of conflicting evidence.** 5. **Soundly written
conclusion based on the strongest evidence.**"
([BCG, *Ethics & Standards*](https://bcgcertification.org/ethics-standards/),
citing *Genealogy Standards*, 2nd ed. rev., 2021). Component 4 is what
`chronology.records`' `reconcile` implements mechanically.

**Three classes of evidence, and the framing move that matters most:**

> "**direct evidence is information that directly addresses the issue at hand**…
> **It may not provide as complete an answer as we would like. It may not even
> provide an accurate answer.**"
> "Much of the information we find **does not provide an explicit answer**… **it
> carries no weight until and unless we combine it with other evidence.**"
> "**Whether any piece of information is evidence depends upon the research
> question we seek to answer.**"
> ([Mills, *QuickLesson 13: Classes of Evidence*](https://www.evidenceexplained.com/content/quicklesson-13-classes-evidence%E2%80%94direct-indirect-negative))

**Negative evidence** is "the absence of what *should* happen under a given set
of circumstances" — and it is load-bearing only when the record set is
established as extant, complete, and of a type that would have recorded the
item. A failed search is a *negative finding*, which proves nothing on its own
([Russell, BCG, 2016](https://bcgcertification.org/bcg-offers-free-webinar-no-no-nanette-what-negative-evidence-is-and-isnt-by-judy-g-russell-jd-cg-cgl/)).

**A worked example of dating with no date**, from Leary's Hemings analysis as
reproduced in QuickLesson 13 — four censuses converted to birth windows
(1820 bracket 26–45 → 8 Aug 1775–7 Aug 1794; 1850 age 66 → 2 Jun 1783–1 Jun
1784; 1860 age 75 → 2 Jun 1784–1 Jun 1785; 1870 age 80 → 2 Jun 1789–1 Jun 1790),
of which the first three are "**compatible direct evidence, from which one can
conclude that the birth likely occurred about the middle of 1784**," the
one-year disagreement explained by known enumeration mechanics, and the fourth
resolved as **conflicting** by an internal-consistency test on the enumerator,
who "**rounded off**" the whole household. **Every move there is available to a
dig**: intervals from age statements, intersection, conflict surfaced rather
than averaged, and a mechanical explanation preferred to a memory dispute.

**The research log is the artifact this design needs**, and it already exists:

> "A research log is a comprehensive list of sources you already searched, **or
> plan to search**… **notations showing sources searched where you found
> nothing**… Research logs show **negative evidence**. NO other tool does this
> nearly as well. And logs **save time by helping avoid repetitive searches after
> a research pause**."
> "If the search results are negative, put **nil or Ø** in the document number
> field… **Blank results means you have not yet done a search in that source.**"
> ([FamilySearch, *Research Logs*](https://www.familysearch.org/en/wiki/Research_Logs))

Three properties to copy exactly: it holds **planned alongside done**; it records
**negative results explicitly**, visually distinct from *not yet asked* — which
is a data-model requirement, not a note-taking habit; and it is designed to
**survive a pause and be handed on**.

**The output form scales with difficulty.** A **proof statement** is used "when at
least two citations demonstrate that a conclusion's accuracy requires no
explanation"; a **proof summary** rests on direct evidence with minor, easily
explained conflicts; a **proof argument** addresses "cases where **evidence
conflicts or where direct evidence is absent**" and "often include[s] tables,
charts, or maps" — "**It's a continuum**"
([Fox, BCG, *Proof Summaries and Arguments 1*](https://bcgcertification.org/ten-minute-methodology-proof-summaries-and-arguments-1/)).
**A date reached in a dig is by definition a proof argument**, and the discipline
expects it to show its work. That is exactly what `DateRecord`'s `basis`,
`confidence`, `anchors` and provenance already do.

**Research questions must identify and specify:** "A good research question does
two things. First, it **identifies a unique individual**… Second, it **specifies
what we want to learn**"
([Henderson, BCG](https://bcgcertification.org/ten-minute-methodology-how-to-ask-good-research-questions/)).
This is the same ruling `timeline-whispers-and-keystones` reached from the
owner's side — *unknowns are concrete* — arrived at independently.

---

## 8. What resolving an unknown is worth

### 8.1 The graph the package already has

`timeline.dependency_index(data)` returns `{anchor_key: {unknown_key, …}}` — for
each candidate anchor (an era's bounds, a dated landmark moment, a person's or
place's arrival), the set of unknowns that placing that anchor would also place.
`timeline.leverage()` is that set's size and `timeline.keystones(data, n=2)` stars
the top two. As of v196, **leverage is a set size**. It is the right primitive
and the wrong plan.

### 8.2 Two facts, demonstrated on a synthetic vault

Running the real v196 code over a small synthetic vault — eight undated moments,
two undated eras, one place with no span, one dated hole between the eras;
twelve concrete unknowns:

| anchor | leverage |
| --- | --- |
| `period:childhood-yucaipa` | 8 |
| `entity:mom` | 7 |
| `entity:yucaipa` | 7 |
| `period:mesa` | 4 |
| `entity:uncle-ray` | 3 |

**Leverage is a marginal quantity and the keystone list does not treat it as
one.** `keystones()` stars the first two — 8 and 7 — which reads like fifteen
unknowns of value. It is eight: `entity:mom`'s resolve set is a strict **subset**
of `period:childhood-yucaipa`'s, so **the second star's marginal gain is exactly
zero**. Ordering independently by leverage stars the same neighbourhood twice.

**A plan is a sequence over the residual graph.** Greedy set cover — take the
anchor with the largest gain against what is *still* unknown, remove it, repeat:

| # | ask | places | of |
| --- | --- | --- | --- |
| 1 | `period:childhood-yucaipa` | 8 | 12 still open |
| 2 | `period:mesa` | 3 | 4 still open |

**Two questions, 11 of 12 unknowns placed, against the keystone list's 8.** And
the greedy plan surfaces what leverage ordering hides: one unknown
(`moment::funeral`) that **no anchor in the graph reaches at all** — no era, no
place, no shared source. No amount of asking *this person* better will place it.
It is the archetype of §6's case.

### 8.3 The metric to propose

Let `U` be the open unknowns and `R(a) ⊆ U` what anchor `a` resolves. A **dig
plan** of length `k`:

```
S ← ∅                                  # already covered
for i in 1..k:
    aᵢ    ← argmax_a |R(a) \ S|        # marginal gain, not leverage
    gainᵢ ← |R(aᵢ) \ S|
    S     ← S ∪ R(aᵢ)
```

`gainᵢ` is the number stated to the person — *"if we can place this, `gainᵢ`
other things fall into place"* — with no transformation, which is exactly the
sentence the owner asked for. The coverage objective `f(A) = |⋃_{a∈A} R(a)|` is
monotone submodular, so greedy is within `(1 − 1/e) ≈ 63%` of optimal for a
`k`-set ([Nemhauser, Wolsey & Fisher, 1978, *Mathematical Programming* 14(1):265–294](https://doi.org/10.1007/BF01588971)).
At `k ≈ 3` nothing better is worth building.

**Witness weighting.** Where an unknown has a witness (§6), run the greedy
*inside* each witness's partition rather than across all anchors, because the
unit a person acts on is "the five things to ask Mom," not "the highest-leverage
question in my life." Order the partitions by the witness's generation.
Unknowns with no witness stay in the in-session plan.

### 8.4 The formal frame, and three warnings

The right model for interval bounds that propagate is the **Simple Temporal
Problem**: variables are time points, each constraint a single interval
`aᵢⱼ ≤ Xⱼ − Xᵢ ≤ bᵢⱼ`, with a designated origin. The results are exactly as
assumed: a consistent STP's minimal network is `Mᵢⱼ = [−d_ji, dᵢⱼ]` from
all-pairs shortest paths; the feasible domain of `Xᵢ` is `[−dᵢ₀, d₀ᵢ]`; and

> "The d-graph of an STP can be constructed by applying **Floyd–Warshall's
> all-pairs-shortest-paths algorithm**… The algorithm runs in time **O(n³)**, and
> **detects negative cycles simply by examining the sign of the diagonal
> elements**."
> ([Dechter, Meiri & Pearl, 1991, *Artificial Intelligence* 49(1–3):61–95](https://doi.org/10.1016/0004-3702(91)90006-6);
> [full text](https://ftp.cs.ucla.edu/pub/stat_ser/r113-reprint.pdf))

**Warning 1 — stay inside the STP fragment.** The *general* temporal CSP, which
allows more than one interval per pair ("either before the war or after the
divorce"), is **NP-hard**. Single intervals buy O(n³) exactness; the first
disjunctive constraint costs it. Handle disjunction by enumerating a few
labelings, never by generalizing the solver.

**Warning 2 — the naive flexibility sum overestimates, and the fix is cheap.**
Summing marginal interval widths `Σᵢ (lst(tᵢ) − est(tᵢ))` measures "the
**smallest hypercube containing** [the solution] polytope," so "if the polytope
itself is not a hypercube… **flex(S) will overestimate**." Their worked case is
ours exactly: three events each in [0,50] give flex 150; adding `t₁ ≤ t₂ ≤ t₃` —
*the kind of constraint our graph is made of* — leaves the marginals unchanged
at 150 while true joint flexibility is **50, a 3× overestimate**. The
**concurrent flexibility metric** takes the largest *inner* box instead and
reduces to a minimum-weight bipartite matching, computable in **O(n³)** — the
same order as the Floyd–Warshall already being run
([Mountakis, Klos & Witteveen, 2015, *ICAPS*](https://doi.org/10.1609/icaps.v25i1.13720);
[Wilson, Klos, Witteveen & Huisman, 2014, *AIJ* 214:26–44](https://doi.org/10.1016/j.artint.2014.05.003)).

**Warning 3 — do not rank on a threshold metric.** "Count of events that become
month-precise" is intuitive and is exactly the pathological shape: decision-
theoretic value of information "**is not submodular, even in Naive Bayes
models**," and can be non-submodular "**if we need to make several observations in
order to 'convince' ourselves that we need to change our action**"
([Krause & Guestrin, 2009, *JAIR* 35:557–591](https://doi.org/10.1613/jair.2737)).
Two questions that each halve an interval may *jointly* cross the
month-precision line while *individually* scoring zero, so greedy stalls.
**Rank on the continuous width-sum; keep the count as a display number.**

**Not proposed, and why.** Expected information gain — `EIG(ξ) =
E_{p(y|ξ)}[H[p(θ)] − H[p(θ|y,ξ)]]`, the mutual information between observation
and parameter ([Lindley, 1956, *Ann. Math. Statist.* 27(4):986–1005](https://doi.org/10.1214/aoms/1177728069);
[Chaloner & Verdinelli, 1995, *Statistical Science* 10(3):273–304](https://doi.org/10.1214/ss/1177009939);
modern treatment and notation: [Rainforth et al., 2024, *Statistical Science* 39(1)](https://arxiv.org/abs/2302.14545))
— is the principled objective and the wrong one to start with: it needs a prior
over each unknown's interval that the vault does not have. Its greedy form is
"**subtly sub-optimal because it makes greedy, myopic decisions**," though the
chain rule of mutual information means adaptive greedy does not *leak*
information, only mis-sequence it. For a session of three to eight questions
that is a tolerable, documented defect.

**Betweenness centrality is worth naming and not worth building.** After
Floyd–Warshall the constraint graph is *complete*, so betweenness on it is
degenerate; computed on the original sparse graph it measures how the person
happened to phrase things. It also ignores interval widths entirely. The exact
quantity is available for the same cost. **Articulation points** on the sparse
graph are the defensible structural fallback for *explaining* a ranking, since
removing one provably disconnects propagation, and they are O(V+E). The right
literature for "which variable to resolve next" is CSP variable ordering —
minimum-remaining-values, the degree heuristic, and impact-based search, which
"measures exactly how much assigning a variable reduces the remaining search
space" ([Refalo, 2004, *CP 2004*, LNCS 3258:557–571](https://doi.org/10.1007/978-3-540-30201-8_41))
— and impact is a *measured*, not structural, quantity.

---

## 9. Naming

The owner asked whether the traditions this document surveys already have a word
for it. They do — several — and surveying them properly changes the answer.

The names must sit inside a set that already works: **landmarks** are the
universal skeleton, **keystones** are the per-person gaps that skeleton leaves,
**whispers** are how the loop asks inside an ordinary conversation. Those are
load-bearing structural nouns, each saying what the thing *does*. And each
candidate has to be judged against the owner's three senses: **(i)** evidence-
driven dating, **(ii)** asking living sources while you can, **(iii)** self-chosen
homework.

### 9.1 The terms of art, and what they actually mean

| Term | Field | Its real meaning | (i) | (ii) | (iii) | Beside landmark/keystone |
|---|---|---|:--:|:--:|:--:|---|
| **dig** / excavation | archaeology | the controlled removal of deposits to recover a stratified sequence | ●● | — | ○ | stone-and-structure register; sits perfectly |
| **sounding** / sondage | archaeology + nautical + idiom | an exploratory test pit sunk to read the sequence before a full dig; also *to sound someone out* | ●● | ●● | ○ | fits, but reads nautical to most people |
| **cross-dating** | archaeology, dendrochronology | dating an undated sequence by matching it against an already-dated one | ●●● | — | — | precise; a *mechanic*, not a session |
| **corroboration** | historical method, oral history | confirming a claim from an independent source | ●● | ● | — | Latinate, cold; a step not a sitting |
| **terminus** post/ante quem | chronology | the bounds an interval is built from | ●●● | — | — | already ours (`chronology.md` §1) |
| **fixed point** | chronology | a securely dated event that anchors a relative sequence | ●● | — | — | beautiful, but it names a *thing* we already call an anchor |
| **floating gap** | oral tradition (Vansina) | the hollow that opens between living memory and origin story as generations pass | ● | ●●● | — | names the *urgency*; unusable as a label |
| **research log** / research plan | genealogy | the artifact carrying planned-and-done searches across a pause | — | ● | ●●● | names the *homework*, and see §7 |
| **brick wall** | genealogy | an ancestor problem no available record resolves | ●● | ● | — | names a *hard unknown*, not a session |
| **proof argument** | genealogy | the written form a conclusion takes when direct evidence is absent or conflicting | ●●● | — | — | names the *output*; heavy |
| **evidence mining** | genealogy (BCG Std. 40) | extracting all usable evidence from a source | ●● | — | — | wrong register entirely |
| **elicitation** | ethnography | drawing out an account using a stimulus | ●● | — | — | academic; also already ours |
| **witness** | law, oral history (Moss) | a source who was present | ● | ●●● | ● | warm, honest, and free of collisions |
| **kinkeeper** | family sociology (Rosenthal) | the relative who does the family's connective work | — | ●● | — | names a *role*, and the evidence is about relational work, not dates |

### 9.2 Ranked, for the session's name

1. **Dig** — recommended. It is the excavation the owner's own metaphor is
   already reaching for; it is one syllable; it sits in the same
   stone-and-structure register as landmark and keystone without repeating
   either; and — decisively — it yields every derived name the design needs for
   free: the **dig plan** (monthly artifact) and the **dig list** (per-witness
   homework). It carries sense (i) strongly by metaphor, (iii) weakly, (ii) not
   at all, and §9.3 handles (ii) separately.
2. **Sounding** — runner-up, and the most interesting near-miss. In archaeology
   a sondage is precisely an exploratory cut made to read the sequence before
   committing to a full excavation, which is *exactly* what a first session is;
   and "to sound someone out" independently carries sense (ii). It is the only
   candidate that carries two of the three senses in one word. It loses because
   most readers hear depth-of-water, and a control labelled "Sounding" needs a
   footnote — which a control must never need.
3. **Cross-dating** — the most *accurate* term here for what the session
   mechanically does. It should be adopted as the name of the **mechanic** in
   docs and code comments, and it is not a product noun.
4. **Corroboration session** — carries (i) and (ii), but names a verification
   step rather than a sitting, and its register is wrong for a life story.
5. **Excavation** — same metaphor as *dig*, strictly worse: too long for a row,
   too grand for the act, and "excavate" is not a verb anyone says aloud.
6. **Research session** — accurate, inert, and it collides with
   `research_expand`'s existing meaning in this codebase.
7. **Archaeology** — a discipline, not a session. It is what the thing *is like*,
   which is why it belongs in the first paragraph of the docs and not on a row.
8. **Detective mode** — no term of art behind it, the product has no modes, and
   the register is wrong.

**"Go Deep" is not in this list because it is not competing.** It is the **verb**,
and the owner's own — what a person says out loud, short enough for a row, and a
Play control needs a verb, not a noun. **Recommendation: keep "Go Deep" as the
button; make "a dig" the noun.**

### 9.3 The urgency, and the person

**"Ask now while you can"** is the best *sentence* in the set and the worst
*noun*. It names the one thing no structural noun can — that the clock is on the
source, not the subject — and §6.1 shows the professional traditions reaching for
exactly that framing, up to and including federal statute. But a row that reads
"Ask now while you can" *every time* the Timeline opens is a memento mori, not a
control, and StoryCorps' deliberate choice to ground its rationale in honour
rather than mortality is a live counter-example from the field.

**Recommendation: deploy it as a sentence, once, with the person named** — the
dig plan's own line when its top witness is grandparent-generation ("Uncle Ray is
the only one who can answer four of these") — and never as a label. Urgency
stated once about a specific living person is true and moving; worn as a title it
is wallpaper.

**The field name is `witness`.** It is the historian's and the oral historian's
own word for a source who was present; it renders warmly ("Mom · 7 things only
she can place"); it claims exactly what the evidence supports — presence, not
authority; and it does not collide with `source`, which in `system/timeline.py`
already means the story file a moment came from. Rejected: *informant* and
*proxy* (survey-methods words, cold), *keeper* (claims more than presence),
*kinkeeper* (a real term of art, but §6.5 shows it measures relational work, not
custody of dates), and **mysteries** — the owner's own alternative, which is the
right word in *prose* and the wrong word in code, because every unknown is a
mystery, so it partitions nothing and says nothing about what to do next.

**The homework artifact is a `dig list`**, built to the research log's three
properties (§7): planned alongside done, negative results explicit and visually
distinct from not-yet-asked, and designed to survive a pause.

---

## 10. What a dig looks like

Design consequence, not a build order.

**It opens by asking what is in the room.** Not "what do you want to talk about"
— *"what do you have in front of you?"* §5 is the reason: what the person can
physically look at determines which questions are cheap, and §5.5's inversion
means the right follow-up is "what's **near** the photo?" A shoebox of prints, a
report card, a passport, and nothing at all are four different sessions.

**It arrives with a plan and says so, once** — the `arc_walk` opener shape. The
dig plan (§8.3) is the agenda, each item stated as what it would unlock.

**The loop is evidence → record → recompute → next.** The person reads something
out; the turn produces a `placed` record with a basis; it files through
`timeline-place`; and the *next* question is chosen against the graph as it now
stands. **Recomputing mid-session is the one structural difference from every
existing interaction**, and it is why a dig is a session rather than a question.

**It never proposes a date and asks for agreement** (§4.3). It elicits readings
and does the arithmetic.

**It probes with timing and duration, not across domains** (§2.3) — and it never
asks for a year first, and never accepts "about N years ago" when an absolute
date is available (§4.5).

**When evidence and memory disagree, it attributes the challenge to the source**
(§3.3) and keeps both claims (`chronology.md` §4).

**Three new bases.** `chronology.BASES` is `stated | age | anchor | order |
public_event | connector`. A dig produces dates whose warrant is none of those:
`document` (a printed date read off paper — near-certain, often exact to the
day), `photo` (a contextual date — a *window*, by §5.1, and an interval by
default), and `relative` (the person relaying someone else's memory —
second-hand, and honestly weaker than `stated`, but by §6.4 often *stronger* for
childhood facts than the person's own dating). Weights follow §6.4's evidence,
not intuition.

**It closes by writing homework as an ordinary note** — a dig list per witness,
short, plain, and never a form (§6.6's warning). No deferral machine: v196
deleted one deliberately, and the rule stands.

**The answers come back as ordinary conversation.** "I asked my mom — we moved in
'84" files as a date record with `basis: relative` and the witness in
provenance. No inbox, no outstanding-item state.

**The first homework is two lists**, and §5 says why they dominate everything
else: **every address ever lived at** and **every school attended**. Both are
landmark questions; both convert into intervals by arithmetic; both then bound
everything that happened inside them; and both are exactly what a parent can
produce in one sitting.

**Worked example.** Birthday 1976-04-11, and one fact from Mom: "you started
kindergarten at Wildwood." Wildwood's district cutoff (§5.3) puts an
April-born child into kindergarten the September after turning five → K =
1981-09/1982-06 → **first grade = 1982-09/1983-06**. Every moment the person ever
described as "in first grade" becomes a `range`-granularity `DateRecord`,
`basis: age`, `confidence: inferred`, anchors `[birth, school:wildwood]` — placed
without anyone ever being asked what year it was. And because ~1 adult in 5 was
redshirted, retained or skipped, the system **states the derivation and asks**
rather than filing it silently.

---

## 11. Design consequences

Numbered so a contract can cite them.

1. **A dig is a session, not a question.** Everything in §§2–5 describes a
   sitting of tens of minutes with artifacts to hand. §2.4 is the reason it
   cannot be a daily send: flexibility earns nothing on easy cases and
   everything on hard ones, and every case here is hard. The owner's rule — "I
   don't want to answer a question like that every day" — is also the
   methodological one.
2. **In-app, opt-in, chosen.** No notification, no nudge, no streak. The person
   is choosing to give themselves homework.
3. **The opening move is inventory, not memory** (§5, §10).
4. **Probe with timing and duration; let the person cross domains** (§2.3).
   This **amends `chronology.md` §6 rung 5**.
5. **Never propose a date for confirmation** (§4.3, Lindsay 2004).
6. **Elicit absolute dates; never offer "about N years ago" as the easy path**
   (§4.5, Janssen 2006).
7. **Three new bases — `document`, `photo`, `relative`** — with `photo` defaulting
   to an interval (§5.1) and `relative` weighted from §6.4, not intuition.
8. **The plan is greedy over the residual graph, recomputed after every
   placement** — not a top-N leverage list (§8.2's zero-marginal-gain result).
9. **Rank on continuous width reduction; display counts** (§8.4, warning 3).
10. **Stay inside the STP fragment** (§8.4, warning 1).
11. **Every unknown may carry a `witness`**, derived from roster facts the person
    already gave (`relationship`, `living`) plus joins `dependency_index` already
    walks. **No new state.**
12. **Urgency is an ordering by the witness's generation, stated once with the
    person named** (§6.1, §9.3) — never a permanent label.
13. **Homework is an ordinary vault note, re-derived**, built to the research
    log's three properties (§7). No deferral state, no inbox.
14. **The homework list is short and plain, never a form** (§6.6). Ask for
    little; ask simply.
15. **Ask relatives about events, not processes** (§6.4). Discrete, witnessed,
    publicly-marked facts survive thirty years; gradual ones do not.
16. **A sibling is a witness to a different childhood** (§6.5) — complementary
    testimony, not a redundant copy.
17. **The first two homework questions are landmark questions**: every address,
    every school (§5.3, §5.4, §10).
18. **Monthly is the right cadence** and the existing monthly loop
    (`system/monthly_research.sh`, beside `research-expand` and
    `recommend-focuses`) is the right home. Weekly is the queue's cadence and
    would churn faster than a person can act.
19. **Nothing is ingested.** The person reads the document aloud; the system
    records the derived date. This satisfies GDPR Art. 5(1)(c) and 25(2) **by
    construction** (§5.6). Holding documents is the connectors question (#580),
    and the two stay apart.
20. **Ask for the date first and the document type second** — privacy-correct and
    also the shortest exchange (§5.6).
21. **State the honest gaps in the product, not just here** (§11's neighbours
    below): a photo's contextual date is a window, and the system should say so
    on the record it writes.

## 12. What this is not

* **Not reflective and not inspirational.** A dig asks for facts and says so. The
  conversation interaction's warmth is appropriate; its meaning-making is not
  the point here.
* **Not a daily question, not a whisper, not a keystone.** Whispers and keystone
  questions are the *ambient* ways the loop asks; a dig is the *deliberate* way
  the person asks themselves. Making a dig ambient turns it into the
  interrogation whispers exist to avoid.
* **Not a genealogy product.** It never leaves the vault, never searches records,
  never contacts a relative. The person does all three, if they choose.
* **Not a task manager.** A dig list is a page, not a queue.

## 13. Honest gaps in this review

Stated so a later reader does not mistake silence for support.

* **No study measures whether objects improve DATE recall specifically** (§4.5).
  The design does not depend on one, because it treats objects as evidence
  rather than as cues — but the gap is real.
* **The OHA standard does not sanction in-session artifact corroboration**
  (§3.1), and life-history practice explicitly warns against pressing narrators
  for dates (§3.2). The departure is deliberate and justified by §3.2's
  mechanism, not by precedent.
* **Vansina's floating gap is cited but unverified** in this session (§6.2). It
  is the concept most directly supporting the owner's framing and the first
  thing to verify.
* **"Mothers hold the chronology" is a design assumption, not a finding** (§6.5).
* **Older siblings as sources for one's own early life: no evidence either way**
  (§6.5).
* **Schober & Conrad (1997)'s own percentages could not be retrieved**; §2.4 uses
  the verified replication on the same materials instead.
* **Photofinisher date stamps, paper backprint codes and film edge date codes
  have no citable key** (§5.1) — hence the descriptive, non-interpretive probe.
* **Greeting-card manufacturer date codes are folklore** (§5.5).
* Carrier retention figures (§5.5) are from a 2010 law-enforcement document and
  are sixteen years stale; the IPTC social-media stripping results are from 2015.

---

## Sources

**Calendar and conversational interviewing**
- Belli, R. F., 1998, *The structure of autobiographical memory and the event history calendar*, Memory 6(4):383–406 — https://doi.org/10.1080/741942610
- Belli, R. F., Miller, L. D., Al Baghal, T. & Soh, L.-K., 2016, *Using Data Mining to Predict the Occurrence of Respondent Retrieval Strategies in Calendar Interviewing*, JOS 32(3):579–600 — https://doi.org/10.1515/jos-2016-0030
- Belli, R. F., Shay, W. L. & Stafford, F. P., 2001, *Event history calendars and question list surveys*, POQ 65(1):45–74 — https://doi.org/10.1086/320037
- Belli, R. F., Smith, L. M., Andreski, P. M. & Agrawal, S., 2007, *Methodological comparisons between CATI event history calendar and standardized conventional questionnaire instruments*, POQ 71(4):603–622 — https://doi.org/10.1093/poq/nfm045
- Belli, R. F., Bilgen, I. & Al Baghal, T., 2013, *Memory, communication, and data quality in calendar interviews*, POQ 77(S1):194–219 — https://doi.org/10.1093/poq/nfs099
- Sayles, H., Belli, R. F. & Serrano, E., 2010, *Interviewer variance between event history calendar and conventional questionnaire interviews*, POQ 74(1):140–153 — https://doi.org/10.1093/poq/nfp089
- Schatz, E., Knight, L., Belli, R. F. & Mojola, S. A., 2020, *Assessing the feasibility of a life history calendar to measure HIV risk and health in older South Africans*, PLoS ONE 15(1):e0226024 — https://doi.org/10.1371/journal.pone.0226024
- Conrad, F. G., Schober, M. F., Jans, M., Orlowski, R. A., Nielsen, D. & Levenstein, R., 2015, *Comprehension and engagement in survey interviews with virtual agents*, Frontiers in Psychology 6:1578 — https://doi.org/10.3389/fpsyg.2015.01578
- Conrad, F. G. & Schober, M. F., 2000, *Clarifying question meaning in a household telephone survey*, POQ 64(1):1–28 — https://doi.org/10.1086/316757
- Bell, K., Fahmy, E. & Gordon, D., 2016, *Quantitative conversations*, Quality & Quantity 50(1):193–212 — https://doi.org/10.1007/s11135-014-0144-2
- van der Vaart, W. & Glasner, T., 2011, *Personal landmarks as recall aids in survey interviews*, Field Methods 23(1):37–56 — https://doi.org/10.1177/1525822X10384367

**Oral history**
- Oral History Association, 2018, *Best Practices* — https://oralhistory.org/best-practices/
- Oral History Association, 2009 (superseded), *Principles and Best Practices* — https://oralhistory.org/about/principles-and-practices-revised-2009/
- Oral History Association, *For Participants in Oral History Interviews* — https://oralhistory.org/for-participants-in-oral-history-interviews/
- Southern Oral History Program, 2023, *A Practical Guide to Oral History* — https://sohp.org/wp-content/uploads/2023/11/Revised_2023_A-Practical-Guide-to-Oral-History_November2023.docx.pdf
- Baylor University Institute for Oral History, *Introduction to Oral History* — https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/intro_manual_2016.pdf
- Charlton, T. L., *The Heart of Oral History: How to Interview* — https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/OHFT_Chapter3_secure.pdf
- Oral History Society (UK), *For Beginners* — https://ohs.org.uk/for-beginners/
- Library of Congress Veterans History Project, 2013, *Field Kit* — http://web.archive.org/web/20140719005524if_/http://www.loc.gov/vets/pdf/fieldkit-2013.pdf
- StoryCorps, *Great Questions* — https://storycorps.org/participate/great-questions/
- Veterans' Oral History Project Act, Pub. L. 106-380 — https://www.govinfo.gov/content/pkg/PLAW-106publ380/html/PLAW-106publ380.htm

**Objects, elicitation, and the false-memory hazard**
- Harper, D., 2002, *Talking about pictures: a case for photo elicitation*, Visual Studies 17(1):13–26 — https://doi.org/10.1080/14725860220137345
- Collier, J., 1957, *Photography in anthropology*, American Anthropologist 59(5):843–859 — https://doi.org/10.1525/aa.1957.59.5.02a00100
- Koutstaal, W., Schacter, D. L., Johnson, M. K., Angell, K. E. & Gross, M. S., 1998, *Post-event review in older and younger adults*, Psychology and Aging 13(2):277–296 — https://doi.org/10.1037/0882-7974.13.2.277
- Lindsay, D. S., Hagen, L., Read, J. D., Wade, K. A. & Garry, M., 2004, *True photographs and false memories*, Psychological Science 15(3):149–154 — https://doi.org/10.1111/j.0956-7976.2004.01503002.x
- Wade, K. A., Garry, M., Read, J. D. & Lindsay, D. S., 2002, *A picture is worth a thousand lies*, Psychonomic Bulletin & Review 9(3):597–603 — https://doi.org/10.3758/BF03196318
- Johnson et al., 2023, Memory 31(8):1011–1018 — https://doi.org/10.1080/09658211.2023.2200595
- Woods, B., O'Philbin, L., Farrell, E. M., Spector, A. E. & Orrell, M., 2018, *Reminiscence therapy for dementia*, Cochrane CD001120 — https://doi.org/10.1002/14651858.CD001120.pub3

**Dating as inference**
- Friedman, W. J., 1993, *Memory for the time of past events*, Psychological Bulletin 113(1):44–66 — https://doi.org/10.1037/0033-2909.113.1.44
- Curran, T. & Friedman, W. J., 2003, Psychonomic Bulletin & Review — https://doi.org/10.3758/BF03196536
- Bradburn, N. M., Rips, L. J. & Shevell, S. K., 1987, *Answering autobiographical questions*, Science 236:157–161 — https://doi.org/10.1126/science.3563494
- Rubin, D. C. & Baddeley, A. D., 1989, *Telescoping is not time compression*, Memory & Cognition 17(6):653–661 — https://doi.org/10.3758/BF03202626
- Janssen, S. M. J., Chessa, A. G. & Murre, J. M. J., 2006, *Memory for time: how people date events*, Memory & Cognition 34(1):138–147 — https://doi.org/10.3758/BF03193393

**Evidence: photographs, metadata, schools, residence, records**
- Victoria & Albert Museum, *Photographic Processes* — https://www.vam.ac.uk/articles/photographic-processes
- Library of Congress, *Care, Handling, and Storage of Photographs* — https://www.loc.gov/preservation/care/photo.html
- Fischer, M., NEDCC Preservation Leaflet 5.1, *A Short Guide to Film Base Photographic Materials* — https://www.nedcc.org/free-resources/preservation-leaflets/5.-photographs/5.1-a-short-guide-to-film-base-photographic-materials-identification,-care,-and-duplication
- Clark, G. W., PhotoTree, *Dating CDVs* / *Dating Cabinet Cards* — http://www.phototree.com/ID_CDV.htm · http://www.phototree.com/ID_Cab.htm
- Playle's, *Real Photo Postcard Stamp Box Dating Guide* — https://www.playle.com/realphoto/
- Playle's, *How To Date U.S. Postcards by Postage Amount* — https://www.playle.com/datingpostcards.php
- CIPA DC-008-2012 (Exif 2.3) — https://www.cipa.jp/std/documents/e/DC-008-2012_E.pdf
- CIPA DC-X008-2019 (Exif 2.32) — https://www.cipa.jp/std/documents/e/DC-X008-Translation-2019-E.pdf
- Library of Congress, *Exif Format Description* FDD000618 — https://www.loc.gov/preservation/digital/formats/fdd/fdd000618.shtml
- ExifTool, *EXIF Tags* and *FAQ* — https://exiftool.sourceforge.net/TagNames/EXIF.html · https://exiftool.org/faq.html
- IPTC Photo Metadata, *Social Media Sites Photo Metadata Test Results* — https://www.embeddedmetadata.org/social-media-test-results.php
- Education Commission of the States, 2020, *50-State Comparison: State K-3 Policies* — https://reports.ecs.org/comparisons/state-k-3-policies-08
- NCES, *State Education Reforms* Tables 5.3, 5.14 — https://nces.ed.gov/programs/statereform/tab5_3.asp · https://nces.ed.gov/programs/statereform/tab5_14.asp
- NCES, *Digest of Education Statistics 2023*, Table 225.90 — https://nces.ed.gov/programs/digest/d23/tables/dt23_225.90.asp
- Bassok, D. & Reardon, S. F., 2013, *Academic Redshirting in Kindergarten*, EEPA 35(3):283–297 — https://eric.ed.gov/?id=EJ1015022
- Huang, F. L., 2015, AERA Open 1(2) — https://eric.ed.gov/?id=EJ1194856
- FERPA regulations, 34 CFR Part 99 — https://www.ecfr.gov/current/title-34/subtitle-A/part-99
- Texas State Library, Local Schedules SD and CC — https://www.tsl.texas.gov/slrm/localretention/schedule_sd · https://www.tsl.texas.gov/slrm/localretention/schedule_cc
- U.S. Census Bureau, *Census Records* — https://www.census.gov/about/history/census-records-family-history/census-records.html
- USPS, System of Records 800.000, 87 FR 59128 — https://www.federalregister.gov/documents/2022/09/29/2022-21101/privacy-act-of-1974-system-of-records
- USPS Domestic Mail Manual §608.11 — https://pe.usps.com/text/dmm300/608.htm
- 15 U.S.C. §1681j — https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681j
- CFPB, *What is a credit report?* — https://www.consumerfinance.gov/ask-cfpb/what-is-a-credit-report-en-309/
- 49 CFR §565.15 — https://www.law.cornell.edu/cfr/text/49/565.15 · NHTSA VIN decoder — https://vpic.nhtsa.dot.gov/decoder/
- 22 CFR §51.4 (passport validity) — https://www.law.cornell.edu/cfr/text/22/51.4
- European Commission, *Entry/Exit System* — https://home-affairs.ec.europa.eu/policies/schengen/smart-borders/entry-exit-system_en · Regulation (EU) 2017/2226 — https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32017R2226
- *Code of Canon Law*, Can. 535 — https://www.vatican.va/archive/cod-iuris-canonici/eng/documents/cic_lib2-cann460-572_en.html
- 42 CFR §482.24 · 22 CCR §70751 · 45 CFR §164.524 — https://www.law.cornell.edu/cfr/text/42/482.24 · https://www.law.cornell.edu/regulations/california/22-CCR-70751 · https://www.law.cornell.edu/cfr/text/45/164.524
- 31 CFR §1010.430 — https://www.law.cornell.edu/cfr/text/31/1010.430
- DOJ CCIPS, 2010, *Retention Periods of Major Cellular Service Providers* — https://www.aclu.org/files/pdfs/freespeech/retention_periods_of_major_cellular_service_providers.pdf
- Michigan Care Improvement Registry — https://mcir.org/public/
- Google, 2023, *Updates to Location History* — https://blog.google/products-and-platforms/products/maps/updates-to-location-history-and-new-controls-coming-soon-to-maps/
- Gmail search operators — https://support.google.com/mail/answer/7190
- setlist.fm and its API — https://www.setlist.fm/ · https://api.setlist.fm/docs/1.0/json_Setlist.html
- GDPR Arts. 5, 9, 25 — https://gdpr-info.eu/art-5-gdpr/ · https://gdpr-info.eu/art-9-gdpr/ · https://gdpr-info.eu/art-25-gdpr/
- ICO, *Data minimisation* — https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/data-minimisation/
- Society of American Archivists, *Core Values Statement and Code of Ethics* — https://www2.archivists.org/statements/saa-core-values-statement-and-code-of-ethics

**Delegated recall and the living source**
- Marion, S. B. & Thorley, C., 2016, *A meta-analytic review of collaborative inhibition and postcollaborative memory*, Psychological Bulletin 142(11):1141–1164 — https://doi.org/10.1037/bul0000071
- Weldon, M. S. & Bellinger, K. D., 1997, JEP:LMC 23(5):1160–1175 — https://doi.org/10.1037/0278-7393.23.5.1160
- Basden, B. H., Basden, D. R., Bryner, S. & Thomas, R. L., 1997, JEP:LMC 23(5):1176–1189 — https://doi.org/10.1037/0278-7393.23.5.1176
- Rajaram, S. & Pereira-Pasarin, L. P., 2010, Perspectives on Psychological Science 5(6):649–663 — https://doi.org/10.1177/1745691610388763
- Harris, C. B., Barnier, A. J., Sutton, J., Keil, P. G. & Dixon, R. A., 2017, *"Going episodic"*, Memory 25(8):1148–1159 — https://doi.org/10.1080/09658211.2016.1274405
- Barnier, A. J., Harris, C. B., Morris, T. & Savage, G., 2018, *Collaborative facilitation in older couples*, Frontiers in Psychology 9:2385 — https://doi.org/10.3389/fpsyg.2018.02385
- Harris, C. B., Barnier, A. J., Sutton, J. & Savage, G., 2018, *Features of successful and unsuccessful collaborative memory conversations*, Topics in Cognitive Science 11(4) — https://doi.org/10.1111/tops.12350
- Wegner, D. M., Erber, R. & Raymond, P., 1991, *Transactive memory in close relationships*, JPSP 61(6):923–929 — https://doi.org/10.1037/0022-3514.61.6.923
- Rosenthal, C. J., 1985, *Kinkeeping in the familial division of labor*, JMF 47(4):965 — https://doi.org/10.2307/352340
- Hornstra, M. & Ivanova, K., 2023, *Kinkeeping across families*, Sex Roles 88(7–8):367–382 — https://doi.org/10.1007/s11199-023-01352-2
- Fivush, R., 2011, *The development of autobiographical memory*, Annual Review of Psychology 62:559–582 — https://doi.org/10.1146/annurev.psych.121208.131702
- Leaper, C., Anderson, K. J. & Sanders, P., 1998, Developmental Psychology 34(1):3–27 — https://doi.org/10.1037/0012-1649.34.1.3
- Plomin, R. & Daniels, D., 1987, Behavioral and Brain Sciences 10(1):1–16 — https://doi.org/10.1017/S0140525X00055941
- Majnemer, A. & Rosenblatt, B., 1994, *Reliability of parental recall of developmental milestones*, Pediatric Neurology 10(4):304–308 — https://doi.org/10.1016/0887-8994(94)90126-0
- Hus, V., Taylor, A. & Lord, C., 2011, *Telescoping of caregiver report on the ADI-R*, JCPP 52(7):753–760 — https://doi.org/10.1111/j.1469-7610.2011.02398.x
- Tomeo, C. A. et al., 1999, *Reproducibility and validity of maternal recall of pregnancy-related events*, Epidemiology 10(6):774–777 — https://doi.org/10.1097/00001648-199911000-00022
- Straughen, J. K. et al., 2013, *Direct and proxy recall of childhood socio-economic position and health*, Paediatric and Perinatal Epidemiology — https://doi.org/10.1111/ppe.12045
- Goody, J. & Watt, I., 1963, *The consequences of literacy*, CSSH 5:304–345 — https://doi.org/10.1017/S0010417500001730
- Assmann, J. & Czaplicka, J., 1995, *Collective memory and cultural identity*, New German Critique 65:125–133 — https://doi.org/10.2307/488538
- Vansina, J., 1985, *Oral Tradition as History*, University of Wisconsin Press — **cited, not verified**
- FamilySearch, *Speak with Your Family* · *Oral Genealogies* · *Gather Family Information* — https://www.familysearch.org/en/wiki/Speak_with_Your_Family · https://www.familysearch.org/en/wiki/Oral_Genealogies · https://www.familysearch.org/en/wiki/Gather_Family_Information

**Genealogy's apparatus**
- Board for Certification of Genealogists, *Ethics & Standards* (the Genealogical Proof Standard) — https://bcgcertification.org/ethics-standards/
- BCG, *Genealogy Standards* 2021 ↔ 2014 standard-number cross-reference — https://bcgcertification.org/images/files/Standards-Manual-2021v2014StdNumbers.pdf
- Mills, E. S., *QuickLesson 13: Classes of Evidence* — https://www.evidenceexplained.com/content/quicklesson-13-classes-evidence%E2%80%94direct-indirect-negative
- Mills, E. S., *QuickLesson 17: The Evidence Analysis Process Map* — https://www.evidenceexplained.com/content/quicklesson-17-evidence-analysis-process-map
- Mills, E. S., *QuickLesson 27: Verifying Historical "Facts"* — https://www.evidenceexplained.com/content/quicklesson-27-verifying-historical-facts-a-blueprint
- Fox, J. K., BCG, *Proof Summaries and Arguments 1* — https://bcgcertification.org/ten-minute-methodology-proof-summaries-and-arguments-1/
- Fox, J. K., BCG, *What is "Reasonably Exhaustive" Research?* — https://bcgcertification.org/ten-minute-methodology-what-is-reasonably-exhaustive-research/
- Henderson, H., BCG, *How to Ask Good Research Questions* — https://bcgcertification.org/ten-minute-methodology-how-to-ask-good-research-questions/
- Russell, J. G., BCG, *What negative evidence is … and isn't* — https://bcgcertification.org/bcg-offers-free-webinar-no-no-nanette-what-negative-evidence-is-and-isnt-by-judy-g-russell-jd-cg-cgl/
- FamilySearch, *Research Logs* — https://www.familysearch.org/en/wiki/Research_Logs
- FamilySearch, *United States Directories* — https://www.familysearch.org/en/wiki/United_States_Directories
- Zinck, J., CG, 2020, *Parents of Clara Cowles of Suffield, Connecticut* (sample research report) — https://bcgcertification.org/images/files/samples/Zinck_ResearchReport2020.pdf

**The value math**
- Dechter, R., Meiri, I. & Pearl, J., 1991, *Temporal constraint networks*, Artificial Intelligence 49(1–3):61–95 — https://doi.org/10.1016/0004-3702(91)90006-6 · full text https://ftp.cs.ucla.edu/pub/stat_ser/r113-reprint.pdf
- Wilson, M., Klos, T., Witteveen, C. & Huisman, B., 2014, *Flexibility and decoupling in Simple Temporal Networks*, AIJ 214:26–44 — https://doi.org/10.1016/j.artint.2014.05.003
- Mountakis, S., Klos, T. & Witteveen, C., 2015, *Temporal flexibility revisited*, ICAPS 2015 — https://doi.org/10.1609/icaps.v25i1.13720
- Nemhauser, G. L., Wolsey, L. A. & Fisher, M. L., 1978, Mathematical Programming 14(1):265–294 — https://doi.org/10.1007/BF01588971
- Krause, A. & Guestrin, C., 2009, *Optimal value of information in graphical models*, JAIR 35:557–591 — https://doi.org/10.1613/jair.2737
- Lindley, D. V., 1956, Annals of Mathematical Statistics 27(4):986–1005 — https://doi.org/10.1214/aoms/1177728069
- Chaloner, K. & Verdinelli, I., 1995, *Bayesian experimental design: a review*, Statistical Science 10(3):273–304 — https://doi.org/10.1214/ss/1177009939
- Rainforth, T., Foster, A., Ivanova, D. R. & Bickford Smith, F., 2024, *Modern Bayesian experimental design*, Statistical Science 39(1) — https://arxiv.org/abs/2302.14545
- Refalo, P., 2004, *Impact-based search strategies for constraint programming*, CP 2004, LNCS 3258:557–571 — https://doi.org/10.1007/978-3-540-30201-8_41
- Freeman, L. C., 1977, *A set of measures of centrality based on betweenness*, Sociometry 40(1):35–41 — https://doi.org/10.2307/3033543

## Research queue

Tracked as backlog, in priority order, with ingestion status: see
`system/research/QUEUE.md`.
