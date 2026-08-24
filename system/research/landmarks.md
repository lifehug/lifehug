# Landmarks: the always-present dating question set

*Research-only literature review (v198). Every claim is sourced; nothing here
is implemented yet. This is the second corpus in the chronology topic — it
assumes `system/research/chronology.md` (v194) and does not re-derive it.
Where chronology.md answers "how do you place ONE memory in time," this
answers "what small set of facts, asked once, makes placing every OTHER
memory cheap." It feeds `system/research.md` §4a, closes the "full EHC
onboarding survey deferred" note there, and proposes a sixth child
interaction (§7). Its sibling corpus `system/research/go-deep.md` (v197)
covers the *evidence-driven* dating session; where the two touch — the greedy
plan over the residual dependency graph, and the rule that a session never
proposes a date for confirmation — go-deep.md is the authority and this
document defers to it. The owner's question, 2026-08-23: "is there a primary set
that always sits under the timeline — birth, marriage, graduation — that a
person can Play and answer, and does the rest by arithmetic?"*

---

## 1. The instrument as actually fielded

Every large retrospective study that has to date a life has converged on
nearly the same short list of domains — and, notably, *not* on the same order
(§1.9). The convergence on membership, and the single shared ordering
*principle* underneath the disagreement, are the findings; no one study is.

### 1.1 The life history calendar (Freedman et al. 1988)

The original LHC covered nine years at **one-month grain** and its rows were,
in the order printed on the calendar's vertical stub: *geographical
residence, marital and cohabitation statuses and transitions, fertility,
living arrangements, school enrollment, employment, military service, and
financial interchanges between respondents and their parents*
([Freedman et al., 1988, *Sociological Methodology* 18:37–68, p. 44–45](https://socialinquiry.wordpress.com/wp-content/uploads/2011/10/d-freedman-et-al_1988_the-life-history-calendar_-a-technique-for-collecting-retrospective-data.pdf)).

The order was not incidental and it was not left to the interviewer: "The
interviewer was instructed to **begin with questions about the first activity
line (the respondent's geographic residence)**, follow that over the total
time period, and then ask in turn the needed questions for each set of
activities listed in the stub of the calendar… Each activity line was
completely finished before the next line was started, and the entire calendar
was completed in the order shown in the vertical stub" (ibid.).

The residence questions are printed verbatim in the questionnaire and are the
single most useful three sentences in this literature for our purposes:

> "Let's begin by talking about where you lived during those years. **In what
> city and state were you living when you turned 15.**" … "Until what month
> and year did you live there?" … "Where did you live next?"

Note what that is: an **age-anchored opener** (not "what year"), followed by a
**chain** that walks forward until the whole period is covered. Only the
second question in the chain asks for a month and year, and by then the
person is inside a concrete place, not a bare calendar. This is
chronology.md §6 rules 1 and 2 as a fielded instrument, twenty-five years
before we wrote them down.

The stated rationale for putting residence, marriage and births first is
explicitly a *cueing* argument: "Events more readily remembered, such as
marriages, births, and changes in geographical residence, provide important
reference points for recalling less salient events, such as details of
employment and living arrangements" (ibid., §2).

### 1.2 The EHC's own design rule for domain order

The survey-methods statement of the rule is general: "The first domains that
should be queried are those whose events are **most easily remembered**, to
motivate responding and also to lay out a framework in which more easily
remembered events can be used as cues in the remembering of events that are
queried later in the interview. Requesting respondents to provide 'landmark
events'… can be an effective first domain when used in this fashion"
([Belli, *Event History Calendar*, in *Encyclopedia of Survey Research
Methods*](https://methods.sagepub.com/ency/edvol/encyclopedia-of-survey-research-methods/chpt/event-history-calendar) — entry text quoted from the publisher's
indexed abstract; the full entry is paywalled and was not fetched).

The PSID's CATI implementation instantiates it as an explicit first row: the
prototype "consists of hierarchically organized timeline domains, including
domains for **landmark events**, residence, employment, unemployment, and time
away from work," and the audio-taped interviews were analysed for interviewers'
use of top-down, sequential and **parallel** probes — the recorded failure
mode being an interviewer who "missed an opportunity to engage in parallel
probing between the residence and employment timelines"
([PSID EHC methods documentation](https://psidonline.isr.umich.edu/Data/documentation/ehc/PSIDcalendarMethodsStudy.html); the PSID PDFs behind
`psidonline.isr.umich.edu` are behind a bot challenge and were not fetched
directly — this is quoted from the publisher's indexed text).

### 1.3 NLSY97: the arrays that get built

The NLSY97 does not print a calendar; it *constructs* one. Five event-history
arrays are generated — **employment** (weekly), **marital/cohabitation status**
(monthly), **program participation** (monthly), **schooling** (monthly, plus
yearly for grade school), and **arrests/incarceration** (monthly) — each with
an explicit origin: "starting in the month when the respondent turned 14,"
with all dates converted "to an actual month number, using January 1980 as
month #1"
([NLSY97 Codebook Supplement, Appendix 6](https://nlsinfo.org/content/cohorts/nlsy97/other-documentation/codebook-supplement/appendix-6-event-history-creation-and-documentation)).

Two things to steal. First, **an age is the origin of the whole coordinate
system** ("the month the respondent turned 14") — the birthday is not one fact
among many, it is the axis. Second, **domains differ in grain by design**: jobs
are weekly because they churn; schooling is yearly at the bottom because the
school year is the natural unit.

### 1.4 Add Health Wave III: the calendar as a persistent surface

Add Health is the closest fielded thing to what the owner is describing,
because its calendar is not an instrument you fill in once — it is a **surface
that stays visible and grows**:

> "The EHC was organized into three domain columns: Public Events, where
> public landmark events were displayed; Personal Events, where personal
> landmark events were displayed; and Relationships… **The EHC displayed the
> respondent's age at the time of the public event**… As the respondent
> continued to add life events in the computer database, those events appeared
> in date order on the calendar. **From time to time, the respondent was asked
> to edit the calendar for accuracy.**"
> ([Add Health Wave III Data Documentation, p. 7](https://addhealth.cpc.unc.edu/wp-content/uploads/docs/faq/W3-DataDocumentation.pdf))

Three design facts fall straight out. (a) The calendar is **re-shown at every
dating question**, not administered once. (b) The system does the **age
arithmetic for the person and shows its work** — the pre-loaded public events
(Appendix D of the same document lists them by year and month) are annotated
with *your* age at the time, which is exactly `from_age` run backwards. (c) The
respondent can **correct it at any time**, which is chronology.md §4's
no-silent-overwrite rule expressed as a UI affordance. Add Health is explicit
that its EHC "was not designed to be used as a data collection instrument" —
it is a memory aid whose whole job is to make the *other* questions answerable.

### 1.5 SHARELIFE and ELSA: the European life-history interviews

SHARELIFE (SHARE wave 3) is the most explicit source in this literature about
*why* its modules are in the order they are:

> "There are several different modules to the SHARELIFE interview, which are
> **ordered according to what is usually most important to the respondent and
> thus remembered most accurately**. Although there is a default order, a
> flexible approach is allowed in the sense that the interviewer can change to
> any module at any point in time if necessary."
> ([SHARELIFE Methodology volume, 2011, ch. 2](https://share-eric.eu/fileadmin/user_upload/Methodology_Volumes/FRB-Methodology_feb2011_color-1.pdf))

The order is **Starting → Children → Partner → Accommodation → Childhood →
Employment → Financial → Health → …**, and the mechanism is stated outright:

> "The interview starts in default order with questions about the children…
> Immediately, this information appears in the calendar… The child section is
> followed by the module about the partner history… **The places of living are
> recorded in the following section, where the previously recorded life events
> prove to be very helpful: interviewers can prompt with that information, e.g.
> 'Did you live there after your second child was born?' or 'Were you still
> with X when you moved?'. This anchoring gives tremendous help to the
> respondent.**" (ibid.)

Its calendar carries five rows — "children, partners, accommodation, job, and
health" — and, exactly like Add Health, does the age arithmetic on screen:
"The top of the calendar section displays each year of the respondent's life
with **his/her corresponding age**, starting from the year the respondent was
born. (The respondent was asked for his/her date of birth at the beginning of
the interview.)" (ibid., ch. 3).

Two operational details worth copying verbatim. **Grain is the year**, not the
month — and when even that fails, the instrument takes a decade: "If cannot
estimate, ask for the decade and enter the mid year" (AC007). And the
residence chain opens at birth and filters by duration: "I'd like to ask you
about the residence you lived in when you were born" (AC004), then "When did
you start living in the [first/next] residence that you lived in **for six
months or more**?" (AC006).

ELSA wave 3 is SHARELIFE's model and uses the same shape under the name
*lifegrid*: "NatCen used a special method… called the 'Life History Calendar'
(or 'lifegrid')… This enables respondents to cross-reference certain
life-events with others (e.g. **'when I had my first child I was living in
house B'**). The calendar also shows important external events, for instance,
when JFK was assassinated"
([Ward et al., *ELSA Wave 3 Life History User Guide*, 2009](https://ifs.org.uk/sites/default/files/output_url_files/Wave_3_Life_History_User_Guide.pdf)).
Its module order is Children → Partners → Accommodation → Work → Health →
Other life events, with month+year for births and deaths and **year** for
partners, housing, jobs and events.

### 1.6 NEPS/ALWA: modular collection, residences first, and its stated cost

Germany's NEPS Starting Cohort 6 collects life histories **domain by domain**
rather than chronologically, and says why:

> "Modularized life course measurement means that longitudinal information on
> the respondent's biography is collected through customized self-reports
> within predefined domains of life… **Interviewee burden is reduced by
> pre-structuring life courses by separating them into life domains** and
> thereby giving interviewees (more) easily accessible stimuli that strengthen
> their mental recalling… In contrast to less structured calendar measurements
> that essentially ask what happened first, what next, what next, the
> modularized approach reduces the risk that respondents forget or omit
> episodes, for instance, overlapping, parallel, or unpleasant ones."
> ([NEPS SC6 Data Manual 17.0.0, §5.1](https://www.neps-data.de/Portals/0/NEPS/Datenzentrum/Forschungsdaten/SC6/17-0-0/NEPS_SC6_DataManual_17-0-0_en.pdf))

Its module order begins **Residence History → Vocational Training → Military →
Employment → Unemployment → Partnerships → Children**, and the residence
module's aim is total: "The aim is to collect all places (local communities) a
respondent resided in since birth" (§5.3.10). Within each module, "the
activities… are recorded, starting with the first activity and ending with the
current activities" — except partners, which run backwards from the current
one (§5.2).

The predecessor study ALWA states the **cost** of modular collection and its
fix, which is precisely our `{anchors}` block: modularization means "die
chronologische Reihenfolge des gesamten Lebensverlaufs geht verloren" (the
chronological order of the whole life course is lost), and during the
interview "already-available autobiographical statements by the target person
were drawn on and played back in the form of inserted text in the questions"
([IAB FDZ-Methodenreport 05/2010](https://doku.iab.de/fdz/reporte/2010/MR_05-10.pdf)).
**Feeding the person's own earlier answers back into later questions is not a
nicety; it is the repair for asking domain-by-domain at all.**

### 1.7 The UK cohorts: current state first, then walk backwards

NCDS and BCS70 do not use a calendar at all. They use domain modules that ask
the **current** state and then walk that domain's history backwards —
"Addresses were entered in reverse order — most recent address first," "Can I
start with the last person you lived with before your current partner"
([NCDS Age 42 questionnaire](https://cls.ucl.ac.uk/wp-content/uploads/2017/08/NCDS-Age-42-Questionnaire.pdf)).
BCS70's age-42 contents run **relationship history / children / household →
family → housing → employment → learning → health**
([BCS70 age-42 questionnaire](https://cls.ucl.ac.uk/wp-content/uploads/2017/07/BCS70_Mainstage_FULL_QUESTIONNAIRE_final.pdf)).

Their coarse-answer rule is the most directly implementable line in this whole
review: "COLLECT MONTH AND YEAR (ON SAME SCREEN). IF UNSURE OF EXACT MONTH,
**CODE MID-SEASON MONTH: Winter: Feb (2) Spring: May (5) Summer: August (8)
Autumn: Nov (11)**" (ibid.). Our `chronology.SEASON_MONTHS` already carries a
season→month mapping; this is an independent, fielded instrument arriving at
the same design, and the mid-season convention is worth adopting for the
*point* estimate while keeping our wider bounds.

### 1.8 Oral history and genealogy: the biographical block, filled in advance

Practitioner intake splits, and the split is instructive.

**The archival tradition front-loads vital statistics.** The Library of
Congress Veterans History Project requires a **Biographical Data Form** with
every submission, filled *before* recording: name, address, telephone, then
"**Place of Birth · Birth Date (month/day/year) · Death Date**", next of kin,
branch of service, "**Service dates: ___ to ___**", unit, locations, battles
([VHP Field Kit, 2017](https://www.winnebagopubliclibrary.org/wp-content/uploads/2024/09/vhp-2018-fieldkit-accessible.pdf) —
mirror; loc.gov's own PDFs 403). A state derivative of the LOC question set
opens "Segment 1: Basic Biographical Information: (key points every interview
should cover) 1. Full name… 2. When/where born 3. Parents' names and
occupations 4. Where/when were parents born…" with the rationale spelled out:
"Certain things should be asked for the record… **Many narrators (and
interviewers) will be a little nervous to begin, and personal biographical
questions provide a smooth start and necessary information**"
([North Dakota State Archives, VHP question guide](https://www.history.nd.gov/archives/vetQuestions.pdf)).
The Smithsonian's interviewing guide agrees on the tactic: "You might want to
begin with some basic biographical questions, such as 'Where were you born?'
'Where did you grow up?' … **These questions are easy to answer and can help
break the ice**," and its Biographical block is "What is your name? Where and
when were you born? Where did you grow up? **Where have you lived? What jobs
have you had?**"
([Smithsonian CFCH, *Folklife and Oral History Interviewing Guide*](https://www.nativeoralhistory.org/system/files/atoms/file/InterviewingGuide.pdf)).

**And it is sent home as homework.** The Montana State Library's Oral History
Biographical Data Sheet instructs: "**Ask the Interviewee to look over and
answer the questions several days before the scheduled interview**," and asks
for name at birth, date and place of birth, then parents' and grandparents'
names, places, and dates of birth and death, siblings, spouse, "Year and
location of your wedding"
([Montana State Library](https://docs.msl.mt.gov/mmpweb/Oralhistory/Oral-History-biographical-data.pdf)).
That is §5.4's affordance, already standard practice in the field.

**The narrative tradition refuses to open that way.** StoryCorps' *Great
Questions* opens with "Tell me about one of the most important people in your
life," "Who has been the kindest to you and why?", "Share some of your
earliest childhood memories" — dated facts appear only later, under Family
Heritage
([StoryCorps, *Great Questions*](https://storycorpsorg-staging.s3.amazonaws.com/uploads/TGTL2021_Great-Questions-6165ff5e77f76-6165ff5e77f77.pdf)).
Baylor's manual prescribes only a spoken *audio label* — "This is [your name].
Today is [month/day/year]. I am interviewing… [full name of narrator]…" — then
"Ask open-ended questions first, waiting to see what unfolds"
([Baylor Institute for Oral History, *Introduction to Oral History*, 2016](https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/intro_manual_2016.pdf)).
The OHA likewise prescribes a lead-in of names, full date and location, and
nothing about establishing the narrator's chronology
([OHA, *Best Practices*](https://oralhistory.org/best-practices/)).

**This is the tension our product actually has to resolve**, and the fielded
answer is already visible: the archival tradition puts the biographical block
on a *form, filled in advance*, precisely so the *recorded conversation* can
open the way StoryCorps and Baylor say it should. Lifehug's equivalent of "the
form you fill in beforehand" is the anchor set under the Timeline; the daily
question stays a conversation.

**Genealogy's canonical set is narrower and harder-edged**: vital records are
the civil registration of *birth, marriage, and death*
([FamilySearch, *United States Vital Records*](https://www.familysearch.org/en/wiki/United_States_Vital_Records);
[US National Archives, *Vital Records*](https://www.archives.gov/research/genealogy/start-research/faqs)).
Useful as an independent signal: the three life events societies bothered to
*write down with a date* are the three the LHC's own reliability data (§2.4)
shows people report most precisely. High datedness is not only a property of
memory; it is partly a property of events that came with paperwork.

### 1.9 The convergent list

**First, an honest correction to the obvious reading.** It would be neat to
say "everyone asks residences first." They do not. The LHC (§1.1) and
NEPS/ALWA (§1.6) open with residence; SHARELIFE and ELSA (§1.5) open with
**children, then partners, then residences**; the UK cohorts (§1.7) open with
relationships; the archival intake forms (§1.8) open with birth and parents.
What *is* settled across all of them is the **principle** — query the domains
"most important to the respondent and thus remembered most accurately" first,
so their answers can cue the rest — and the **membership** of the list.
Instantiation differs by population and purpose. Our own order is argued in
§2.7 on different grounds (which lists are closed and tiling), not by
appealing to a consensus that does not exist.

Pooling §1.1–1.8, the domains that appear in essentially every instrument:

| # | Domain | Appears in | Why it is early |
|---|--------|-----------|-----------------|
| 1 | Birth (date + place) | all; the origin of NLSY97's month scheme; genealogy's first vital record | turns every age statement into a year |
| 2 | Residences, with moves | LHC row 1; PSID; NEPS module 21 ("all places… since birth"); SHARELIFE AC; ELSA RA; BCS70 housing; Smithsonian "Where have you lived?" | bounded spans, high recall, cross-cues everything, and they tile |
| 2b | **Family constellation** (siblings, parents, grandparents) | Montana's data sheet (mother → father → grandparents → siblings, before schools or jobs); ND VHP Segment 1 items 3–4 (parents, straight after the narrator's own birth); BCS70's `family` module; Smithsonian's *Family Folklore* block | it is asked immediately after the subject's own birth, and it is the only domain whose answers are *people* (§2.9) |
| 3 | Partnerships (marriage/cohabitation, separations) | LHC rows 2–3; NLSY97 array 2; Add Health column 3; SHARELIFE RP; ELSA RP; NCDS "past relationships" | dated to the month in validation data |
| 4 | Children (births) | LHC "fertility"; NLSY97; SHARELIFE RC (**first module**); ELSA RC | dated to the month; also dates *other* people |
| 5 | Schooling, with start/end | LHC row 5; NLSY97 array 4; NEPS module 24; SHARELIFE RE002; the quality-principles study | grade↔age↔year arithmetic (§3.2) |
| 6 | Jobs, with start/end | LHC row 6; NLSY97 array 1 (weekly); NEPS 26; SHARELIFE RE; Smithsonian "What jobs have you had?" | dense but churny; least reliable of the set |
| 7 | Military service | LHC row 7; NEPS module 25; VHP's whole form | sharply bounded and institutionally dated |
| 8 | Deaths and losses | genealogy's third vital record; Montana's data sheet (parents'/grandparents' death dates); ELSA "other life events" | high salience, usually exact |
| 9 | Health ruptures | SHARELIFE HS; ELSA RH (asked by **age**, not year) | a real row in the European instruments; ours only on offer |
| 10 | Public events | Add Health column 1 (pre-loaded); ELSA's on-calendar events; SHARELIFE's per-country event search | secondary; conditional (§2.5) |

Notably absent from every fielded instrument: pets, vehicles, holidays as
*data*. Holidays appear only as a *prompt* for eliciting the person's own
landmarks, never as a row.

---

## 2. Which landmarks carry the placing power

### 2.1 Birth date is the origin, not an entry

Every other domain in §1.9 answers "when did X happen." The birthday answers
"what does *any* age statement mean." Once it is known, every "I was about
five" in the entire corpus becomes an interval, permanently and without asking
anything further. This is the one place where asking for a calendar date
directly is not a violation of chronology.md §6 rule 1 — the rule forbids
asking for the year *of a memory being dated*, because that invites a rounded,
telescoped guess (Friedman 1993; Huttenlocher et al. 1990, both in
chronology.md §3). A birth date is not recalled by reconstruction; it is
overlearned semantic knowledge, and it is the datum the fielded instruments
themselves use as the axis (NLSY97's "month the respondent turned 14," Add
Health's display of "the respondent's age at the time"). **A birth date is the legitimate
exception to the no-year-opener rule** — and the exception is about the *kind*
of fact, not about whose fact it is. §2.9 draws out the consequence the v198
pass missed: a *sibling's* birth year is overlearned semantic knowledge in
exactly the same way, and may be asked outright for exactly the same reason.

### 2.2 Residences are the primary chain

Residence is row 1 of the LHC, a first-class timeline in the PSID EHC, and one
of the two highest-accuracy domains in the most recent quality study, which
notes it "can be considered an essential and easy way to remember information"
with "continuity between places"
([*Quality principles of retrospective data collected through a life history
calendar*, 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9612623/)). The
mechanism is Belli's **parallel retrieval**: "the remembering of events across
timelines and domains that happened contemporaneously… Parallel retrieval is
particularly effective if the timing of one of the events is especially
memorable, as this memory will locate the timing of the other event as well"
(ibid.). Residence has three properties nothing else combines: it is
**exhaustive** (you lived somewhere every day of your life, so the chain has no
holes), it is **partitioning** (the spans tile the timeline without gaps or
overlaps, mostly), and it is **the index people already use** — lifetime periods
are indexed by place and role (Conway & Pleydell-Pearce 2000, chronology.md
§3). That is why "where were you living when that happened?" is playbook rung
2 and why answering it once, for the whole life, is worth more than any other
single answer.

Calibration, stated plainly. The quality-principles study reports that
residence and education showed the highest accuracy of the domains it tested,
but it did **not** test residence against a counterfactual instrument. And
residence is *not* universally asked first (§1.9): SHARELIFE and ELSA put
children and partners ahead of it, and SHARELIFE's own text has interviewers
using the child and partner answers to *cue* the residence answers — "Did you
live there after your second child was born?" — which is the exact opposite
direction of cueing. So the defensible claim is narrower than "residence is
the best anchor": **residence is the domain whose answers most often bound
other people's answers, because its spans tile the whole timeline**, and it is
one of the two closed lists (§2.7). Which domain is *asked* first is a
rapport-and-recall decision, not a placing-power one, and the fielded
instruments disagree about it.

### 2.3 Schooling is the second chain, because the calendar does the work

Schooling is the only domain with an **externally fixed grid**. In the US, state
law fixes a kindergarten entrance age with a cutoff date — September 1 is the
predominant one, and the requirement clusters at age 5
([NCES, *Types of state and district requirements for kindergarten entrance
and attendance, by state: 2018*](https://nces.ed.gov/programs/statereform/tab5_3.asp)).
That single regularity converts a grade into a year and back:

> `year_started_grade_g ≈ birth_year + 5 + g`, ±1 for cutoff position, holdback, or skip.

So "I was in fourth grade when we moved" is a dated statement even when the
person could not name the year — and, running the other way, a known school
start/end date is a *second, independent* estimate of the birth year, which is
consilience in chronology.md §4's sense. The LHC's own reliability data agrees
that schooling reports are stable: 87% of respondents gave identical answers
about 1980 school attendance five years apart, 91% when reduced to
attended/did-not (Freedman et al. 1988, §10.2). The authors' explanation is
the one that matters for design: "School attendance at age 18 represents a
long-term commitment, while gainful employment changes more frequently."
**Datedness follows from duration and institutional structure, not importance.**

Caveat, from the same literature: a **quarterly** calendar grid created
confusion "for academic years (as the reference period was in semesters)"
(PMC9612623). If we bin school spans, bin them by academic year, not by
calendar quarter.

### 2.4 The datedness ranking, from validation data

Freedman et al. compared 1985 retrospective reports against the same people's
1980 contemporaneous reports. Ranked by precision of the retrospective report:

| Domain | Result | Source |
|--------|--------|--------|
| Marriage | 26 of 28 gave the **same month and year**; the other two off by 1 and 3 months | §10.1 |
| Births | 9 of 10 matched month and year **exactly**; the tenth off by one month | §10.1 |
| School attendance | 87% identical answers; 91% on attended/not | §10.2 |
| Employment | 83% on worked/did-not; **72%** across the full hours spectrum, with directional bias — a third of those who said "not working" in 1980 said in 1985 that they had worked | §10.3 |

([Freedman et al. 1988](https://socialinquiry.wordpress.com/wp-content/uploads/2011/10/d-freedman-et-al_1988_the-life-history-calendar_-a-technique-for-collecting-retrospective-data.pdf).)
Two operational consequences: (a) marriages and births can be asked for
*directly at month grain* and believed; (b) jobs should be asked for at
**year** grain with an explicit "roughly" and stored `approximate` — asking a job
question at month grain manufactures false precision, and the bias is
directional, so it will not average out.

The whole-instrument quality signal is separate and strong: of ~900 calendars,
**four** had any month with no data at all, and interviewers reported that
"respondents saw the gaps and inconsistencies instantly" (ibid., §9, §10.4).
The calendar's biggest contribution is not accuracy per cell, it is
*completeness* and *self-correction* — which is an argument for showing the
person their own timeline, not for asking more questions.

### 2.5 Public events are secondary and conditional

Add Health pre-loads a list of public events and shows the respondent their
age at each (§1.4). But chronology.md §3 already establishes the gate: the
living-in-history effect scales with *personal* disruption, not fame — 58% of
war veterans' important memories were publicly dated versus 28% of
non-veterans'. And van der Vaart & Glasner (2011) found the landmark component
alone produces only weak positive effects, best when landmarks are
"important, domain-related, and personal." **Public events belong in the
instrument only as an optional last rung, and only where the person has
already told us a public event disrupted their life.** They are never a row of
the question set.

### 2.6 What we are claiming, honestly

Strongly supported: the *composition* of the domain list, the *order*
(easiest-recalled first, residence first), the month grain for
marriages/births, the year grain for jobs, and the fact that a persistent,
editable calendar improves completeness. Weakly supported: any specific
accuracy gain attributable to the landmark set as such — chronology.md §2
already corrected the record on this and it stays corrected. **We are not
claiming this instrument makes memories more accurate. We are claiming it
makes them cheaper to place**, by supplying the anchors that every later probe
in the playbook needs but currently does not have (§3.7).

### 2.7 Two of these are *lists*, and lists can be finished

Owner's framing, 2026-08-23: "It's valuable to get the addresses of every home
I've ever lived at — totally possible right now, harder when my mom is dead.
Also the exact schools I went to. Those locations can help us look back and
say 'when did first grade start?' — that gives us a date."

That names something the survey literature implies but never says outright.
Most landmark domains are *open* — there is no complete list of jobs, of
losses, of turning points, and no way to know you are done. **Residences and
schooling are closed lists.** They are enumerable, finite, ordered, and
verifiable, and a person can *finish* them. Three consequences:

1. **They tile the timeline.** You lived somewhere every day of your life and
   you were in some grade or none. Once the two chains are complete, every
   date in the life falls inside a named residence span and a named school
   year — which is Allen's "reference intervals" (§3.6), the coarse containers
   that make the fine-grained propagation cheap.
2. **They are the two domains a *second person* can supply.** A parent can
   recite the addresses and the schools; nobody but you can supply your
   turning points. This is the only place in the instrument where the answer
   exists in someone else's head, complete — and where that head is a
   depleting resource. Oral history has always known this; the OHA's practice
   of researching the narrator's context in primary and secondary sources
   *before* interviewing (chronology.md §2) is the same instinct, and Portelli's
   point that the interview itself changes what is recalled applies doubly to
   a relative reciting a list they have never been asked for.
3. **They are the two domains the person can verify without us.** Addresses
   appear in the paper trail people already have — deeds, leases, tax records,
   old mail, driver's licences — and schools are public institutions with
   published names, districts and calendars. Genealogy's whole practice is
   exactly this narrowing-by-documents (§3.2, Giroux 2003), and the vital
   records that anchor it — birth, marriage, death — are the same three events
   §2.4 finds most precisely recalled (§1.8). **No connector is required.** The
   product's part is to say which fact would help most and why; the person's
   part, if they choose it, is to go and find it.

Calibration: claims 1 and 3 are structural and safe. Claim 2 — that a living
relative can supply these lists more completely than the person can — is the
owner's observation, is consistent with everything in §2.2 about residence
recall, and is **not** measured anywhere we have found. State it as a design
premise, not a finding.

The product consequence is a distinct affordance: not a question, but
**homework the person chooses**. "Ask your mother for the addresses" is a task
with a definite end, a real payoff the system can quantify in advance ("this
would place 14 moments"), and a deadline nobody wants to name out loud. It
belongs with the parallel *Go Deep / ask the living* work, not inside the
conversation turn.

### 2.8 Do historians agree there is such a method?

Yes — it is the working method of several fields, under different names.
Archaeology's own glossary draws the distinction the owner is reaching for:
**absolute dating** is the "collective term for techniques that assign specific
dates or date ranges, in calendar years," while **relative dating** is "a system
of dating archaeological remains and strata in relation to each other," and the
bounding instruments are *terminus post quem*, "'date after which,' earliest
date at which something was constructed or deposited," and *terminus ante
quem*, "'date before which,' latest date by which something was constructed or
deposited"
([Archaeological Institute of America, *Introduction to Archaeology:
Glossary*](https://www.archaeological.org/programs/educators/introduction-to-archaeology/glossary/)).

Dendrochronology names the *state change* the owner is after even better. A
sequence with no known dates is a **floating chronology**, and the operation
that fixes it is anchoring: "A tree-ring history whose beginning- and end-dates
are not known is called a 'floating chronology'. It can be **anchored by
cross-matching** a section against another chronology (tree-ring history) whose
dates are known"
([Wikipedia, *Dendrochronology*](https://en.wikipedia.org/wiki/Dendrochronology)
— tertiary, quoted for the term). A life told without dates is a floating
chronology. The anchor set is the dated sequence you cross-match it against.

So the answer to "do historians agree there's a way to pinpoint specific
events that makes everything else easier" is: yes, and they would call it
establishing a few absolute dates and then dating everything else relatively
against them. The one correction to the owner's framing is the shape — see
§3.6, it is not a binary tree.

### 2.9 The family constellation

**Ruling (owner-set, 2026-08-24): the family you came from is a landmark
domain.** v198 kept the set to *self-facts* and left relationship facts to the
entity roster. That split was defensible — a roster is the right home for who
someone is — but it dropped a dating instrument on the floor, and it left the
ask-the-living thread with no source of witnesses. Both are fixed by asking
the constellation, filing the dates as landmarks, and sending the *people* to
the roster where they already belonged (contract:
`docs/pr-specs/family-landmark.md` §D).

**Practitioner intake asks the constellation, and asks it early.** The
citations are already in §1.8; what follows is the reading §1.8 did not draw
out. Montana's Oral History Biographical Data Sheet — sent home to be answered
"several days before the scheduled interview" — runs, in this order: *Name at
birth · Date of birth · Place of birth · **Mother's name, place and date of
birth & death** · **Father's name, place and date of birth & death** ·
**Maternal grandparents' names, places and dates of birth & death** ·
**Paternal grandparents' names, places and dates of birth & death** · **Your
siblings' names, dates and place of birth. Please indicate if they are alive or
deceased** · Your spouse's name · Year and location of your wedding · Names,
birth dates, and birth places of your children · Grade School · High School ·
College · jobs*
([Montana State Library, *Oral History Biographical Data Sheet*](https://docs.msl.mt.gov/mmpweb/Oralhistory/Oral-History-biographical-data.pdf)).
Three things in that single form:

1. **The constellation sits between the subject's own birth and everything
   else** — before schooling, before work, before the marriage.
2. **Sibling birth dates are asked outright**, in the same breath as the
   subject's own, on a form filled from memory and family papers.
3. **"Please indicate if they are alive or deceased"** is asked as an ordinary
   intake field, of siblings and of children. The *living* flag is not a
   delicate special case in the field's own practice; it is a column.

The North Dakota State Archives' VHP question guide independently puts parents
at items **3 and 4** of "Basic Biographical Information: (key points every
interview should cover)" — "1. Full name… 2. When/where born 3. Parents' names
and occupations 4. Where/when were parents born…" — with the rationale §1.8
already quotes: personal biographical questions "provide a smooth start and
necessary information"
([North Dakota State Archives](https://www.history.nd.gov/archives/vetQuestions.pdf)).
The Smithsonian's guide gives *Family Folklore* its own question block
immediately after *Biographical Questions* — "What stories have come down to
you about your parents and grandparents? More distant ancestors?"
([Smithsonian CFCH, *Folklife and Oral History Interviewing Guide*](https://www.nativeoralhistory.org/system/files/atoms/file/InterviewingGuide.pdf)).
And BCS70's age-42 contents run *relationship history / children / household →
**family** → housing → employment → learning → health* (§1.7), putting family
ahead of housing in a fielded instrument.

**Calibration.** What is *documented* is that these instruments ask the
constellation, ask it early, and ask sibling birth dates and living status
directly. What is **not** measured anywhere we have found is the claim that
sibling birth years are recalled *more* accurately than other landmarks — no
validation study we located reports datedness by kin. The datedness ranking in
§2.4 covers the subject's own events, not their relatives'. Treat "siblings are
strong anchors" as resting on two safe legs and one premise:

* *safe* — a sibling's birth is a **vital record** (§1.8: birth, marriage,
  death are the three events societies wrote down with a date), and vital
  records are the best-dated class in the whole set;
* *safe* — it is **overlearned semantic knowledge**, not a reconstruction: the
  §2.1 argument for the subject's own birthday is an argument about the kind of
  fact, and it transfers without modification;
* *premise* — that it lands in **childhood**, where §3.1's `from_age`
  arithmetic has the least to work with. That is the owner's observation and
  it is structurally obvious (siblings are born near you in time), but it is
  not a measured finding.

**Consequence for the no-year-opener rule.** §2.1's carve-out extends to any
person's birth *year*, asked as a fact about that person rather than as the
date of a memory being placed: "What year was Jackie born?" is legitimate;
"What year was that trip?" is not. This is not a loosening of chronology.md §6
rule 1 — that rule forbids demanding a year for a *reconstructed* memory, and
a birth year is not one. Nothing here touches the separate, unconditional rule
that **no date is ever proposed for agreement** (§`go-deep.md` 4.3; Lindsay et
al. 2004), which applies to a sibling's birth year exactly as to everything
else.

**A third closed list — of people.** §2.7 argues that residences and schools
are special because they are *closed lists*: enumerable, finite, ordered,
verifiable, and **finishable**. Siblings satisfy every one of those, and
parents and grandparents satisfy them by biology. So the family constellation
is a third closed list, and §2.7's three consequences apply with one
substitution each:

1. *They tile* — siblings do not tile the timeline the way residences do, but
   they **bracket childhood**, which is the stretch the residence chain covers
   worst (a child does not remember the year of a move; they remember who was
   already born).
2. *A second person can supply them* — and here the domain is not merely
   supplied by a witness, **it identifies the witnesses.** §2.7's depleting
   resource is exactly this list.
3. *Verifiable without us* — the same vital records, from the same registries.

The one way it differs, and it matters for implementation: this list is made of
**people**, so its members belong in the entity roster as PERSON entities with
relationship facts, not in a parallel family store. The landmark set files the
*dates*; the roster holds the *people*. `family_roster_invocations` is the
join, and `entity_verdict`'s existing `--relationship` / `--living` identity
facts (ADR 0013, v190) are the verbs — no new store, and no second
relationship vocabulary: `relation` is closed against
`focus_candidate.FOCUS_RELATIONSHIPS`.

---

---

## 3. The arithmetic: how a dozen answers generate bounds for everything

### 3.1 Age → year (from the birth date)

A person who was age *a* occupies `[birth_year + a, birth_year + a + 1]`; a
hedge ("about five") widens it a year each side. This is already
`chronology.from_age(birth_date, age_text)` and it is already correct. It is
the highest-yield rule in the system because age statements are the most
common way people volunteer time ("I was about five," "in my twenties") and
because it costs nothing after the birth date is known.

### 3.2 Grade → year (from schooling), worked

This is the owner's example and it deserves the arithmetic in full. Given a
birthday and the name of a school, the system can derive a school-year span
without asking a single "what year" question:

```
birthday                 1978-04-12
convention               first grade begins in the September AFTER the
                         child turns 6 (US; entrance age fixed by state law
                         with a cutoff date, most commonly September 1)
→ turns 6                1984-04-12
→ first grade starts     September 1984
→ grade g starts         September (1984 + g − 1)
→ "fourth grade"         Sept 1987 – June 1988
```

So "we moved when I was in fourth grade" becomes `1987-09/1988-06` — a
month-grain interval, from a fact the person volunteered as a grade. Running
it backwards, a remembered graduation year is an independent second estimate
of the birth year.

The convention's variance is real and bounded: US states fix a kindergarten
entrance age (clustered at 5) with a cutoff date, most commonly September 1,
but cutoffs range from late July to January and some states leave it to the
district
([NCES, *Types of state and district requirements for kindergarten entrance
and attendance, by state: 2018*](https://nces.ed.gov/programs/statereform/tab5_3.asp)).
Add held-back years, skipped years, mid-year moves and non-US systems and the
honest band is **±1 year**. So: implement as `from_age` with a grade table,
emit `basis: age`, `confidence: inferred`, and bake the ±1 in — never present
a grade-derived year as certain, and suppress the rule entirely when the
person has told us their schooling was non-standard (§5.2).

Genealogists do exactly this and say so plainly: "Collecting many documents
stating a person's age should narrow the range of dates because of the
overlaps of the ranges," and a calculated birth date is always shown as
"*about* 4 September 1851" or "*circa* 1814 to 1818"
([Giroux, *Date Calculations*, *OnBoard* 9 (2003), Board for Certification of
Genealogists](https://bcgcertification.org/skillbuilding-date-calculations)).
That is §3.5 and chronology.md §6 rule 9, arrived at independently by a field
that has been doing this for a century.

### 3.3 Span → containment (from residences, schools, jobs, marriages)

Any claim of the form "while we lived in X," "when I was at Y," "before the
divorce" resolves to the span of that landmark. This is
`chronology.from_anchor(anchor, "during")` and it is already correct. What is
missing is not the function but the **anchors**: `from_anchor` needs an anchor
index, and the index is currently built only from wiki entities that happen to
have dates (§3.7).

### 3.4 Ordering → one-sided bounds

"After we moved to Denver" is a *terminus post quem*; "before Dad died" is a
*terminus ante quem*. `chronology.from_anchor(anchor, "after"|"before")`
already emits the open intervals `1986/..` and `../1986`. Relative order is
first-class data even when no date exists at all (chronology.md §6 rule 6) —
and with a landmark set in hand, most order claims become bounds
automatically.

### 3.5 Intersection → the actual answer

The payoff is `chronology.intersect(*records)`: "after the Denver move
(1986/..)" ∩ "while I was at Lincoln High (1984/1988)" ∩ "I was about 16
(1985/1988)" = **1986–1988**, from three cheap answers none of which was a
year. Every additional landmark narrows every overlapping interval, for free,
forever. That is the whole thesis of the instrument.

### 3.6 It is not a binary tree — name it correctly

The owner's "binary tree from known dates to other dates" has the right
intuition (knowns generate knowns) and the wrong shape. A tree has one parent
per node and no cycles. Here, one unknown is constrained by *many* landmarks
at once (§3.5), landmarks constrain *each other* (a school span and a residence
span mutually bound), and the constraints are **intervals with relations**, not
points. The correct names, in ascending order of formality:

- **Relative chronology / cross-dating** — the historians' term (§2.7).
- **A constraint graph** — nodes are events and spans, edges are relations
  (`before`, `after`, `during`, `overlaps`), and solving is constraint
  propagation: assert a new bound, propagate, narrow.
- **Allen's interval algebra** — the formal treatment of exactly these
  relations between time intervals, and the standard algorithm for
  propagating them. Allen's abstract is a fair description of what we are
  building: "An interval-based temporal logic is introduced, together with a
  computationally effective reasoning algorithm **based on constraint
  propagation**… A notion of **reference intervals** is introduced which
  captures the temporal hierarchy implicit in many domains, and which can be
  used to precisely control the amount of deduction performed automatically."
  There are "a total of **thirteen** ways in which an ordered pair of
  intervals can be related"
  ([Allen, 1983, *Maintaining Knowledge about Temporal Intervals*, *CACM*
  26(11):832–843](https://cse.unl.edu/~choueiry/Documents/Allen-CACM1983.pdf),
  §3). Allen's "reference intervals" are, structurally, our residences and
  eras: the coarse containers that bound the fine-grained events inside them
  and keep the propagation from exploding.

Our current implementation is the sound, incomplete, cheap version of this:
`intersect` over `earliest`/`latest` is **bounds propagation on a partial
order**, not full interval-algebra inference. That is the right amount of
machinery for now, and it should be described accurately in the docs rather
than as a tree.

### 3.7 What v195 already has, and the one thing that is missing

Present and correct in `system/chronology.py`: `from_age`, `from_anchor`
(`before`/`after`/`during`), `intersect`, `widen_for_elapsed`, `reconcile`,
`record_from_claim(claim, birth_date=…, anchors=…)`. Present in
`system/timeline.py`: `anchor_index(periods, entities, events,
birth_date=None)`, whose own docstring says it is "the life-history calendar
as data (Freedman et al. 1988): the birthday, the residences with spans, the
eras with spans, and the dated landmark moments," and
`timeline_interaction.anchors_for_person(...)`, which orders birth →
residences → eras → landmarks.

**The gap is that nothing ever fills it.** Concretely, as of v195:

1. `birth_date` is a parameter of `timeline.timeline_data`,
   `timeline.anchor_index`, `timeline.resolve_event_dates` and
   `timeline_interaction.anchors_for_person` — and **no production caller ever
   passes it.** `serve_wiki.py:2484`, `wiki_compile.py:1423`,
   `arc_planner.py:252`, `connectors/base.py:282` and `timeline.py:1151` all
   call `timeline_data()` bare. `profile.yaml` has no birth-date field. So
   `from_age` — the highest-yield rule in §3.1 — **cannot fire in production.**
2. Residences reach `anchor_index` only as wiki entities of `type: place`
   that already carry a date. Nothing asks for a residence chain, so the
   spans that §2.2 identifies as the primary anchor exist only by accident of
   what the person happened to narrate.
3. `PLAYBOOK_STEPS` rungs 5 (`sequence`) and 6 (`landmark`) are marked
   `needs_anchor: True`. With an empty anchor index those two rungs are
   permanently unreachable, so the ladder degrades to
   content → residence → role → parallel → season → bounds. **The two rungs the
   research says are the cheapest and best are the two we cannot use.**
4. `keystones()` ranks anchors by leverage, capped at 2 (`KEYSTONE_CAP`), and
   v196 gave the winner two real rails — the timeline whisper and, above the
   `timeline_leverage_per_story` cutoff (6), a minted bank question. The
   mechanism is right and now fully built; the **stock** is the problem. With
   no landmark set, the highest-leverage missing fact is nearly always a
   landmark, and there is still no way to ask for one directly.

*(Re-verified against main at v196: every `timeline_data()` call site is still
bare, `profile.yaml.example` still has no birth field, and `PLAYBOOK_STEPS`
rungs 5–6 still carry `needs_anchor: True`.)*

This is the finding that justifies the whole proposal: **we built the
arithmetic before we built the inputs.**

---

## 4. Naming

### 4.1 What the literature calls it

| Term | Field | Verified use | Fit as a product word |
|------|-------|--------------|-----------------------|
| *landmark event*, *personal landmark* | survey methodology | Loftus & Marburger's title is the term: "*Since the eruption of Mt. St. Helens, has anyone beaten you up? Improving the accuracy of retrospective reports with landmark events*" ([PMID 6865744](https://europepmc.org/article/MED/6865744)); and van der Vaart & Glasner's "[Personal Landmarks as Recall Aids in Survey Interviews](https://journals.sagepub.com/doi/10.1177/1525822X10384367)" | the field's own word, but ordinary English hears *a building* or *a landmark ruling*, and neither says **dated** |
| *temporal landmark* | cognitive psych, now behavioural econ | the dating sense is Shum's: "temporal landmarks may play a critical role in this organization" of autobiographical memory, across "3 types of events that have usually been considered landmarks: flashbulb memories, 1st experiences, and reference points in personal histories," yielding "improvements in accuracy in dating" ([Shum 1998, *Psych Bulletin* 124(3):423–442, PMID 9849113](https://europepmc.org/article/MED/9849113)). But the term has **drifted**: nine of the ten most recent MEDLINE titles containing it are about motivation, consumer choice and risk-taking, not dating ([Europe PMC title query](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE%3A%22temporal%20landmarks%22%20AND%20SRC%3AMED&format=json&resultType=core&pageSize=10)) — the centre of gravity is now the "fresh start effect" ([Dai, Milkman & Riis 2014](https://doi.org/10.1287/mnsc.2014.1901)) | rule out: jargon, and the live connotation is *motivation*, the wrong axis |
| *anchor*, *temporal anchor point* | used throughout the EHC literature; already our code's word (`anchor_index`, `anchors_for_person`, basis `anchor`, `from_anchor`) | "Landmark events can be used as temporal anchor points to which respondents can relate other events" ([quality-principles study, 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9612623/)) | plain, physical, instantly understood; the anchoring-bias collision is specialist-only |
| *life grid* | UK health-inequalities research | the instrument's name in that literature (Berney & Blane 1997, *Soc Sci Med* 45(10):1519–1525); **bibliographic only — the body text was not obtained** | plainest of the instrument names, but names the *grid*, not the questions |
| *life history calendar*, *event history calendar* | the instruments | Freedman et al. 1988; Belli 1998 | names the artifact, not the act |
| *reference period*, *index date* | official statistics; epidemiology | standard usage in both fields; **no definition text was independently verified for this review** | bureaucratic; reads like a form field |
| *benchmark*, *baseline*, *datum* | surveying and geodesy | real terms of art, but **no authoritative definition was fetched for this review** — do not quote one | **poisoned regardless**: everyday business English has made *benchmark* and *baseline* mean "a standard to compare against," not "a known fixed point" |
| *milestone* | vernacular | — | means "notable," not "dated" — the wrong axis |
| *spine*, *skeleton*, *armature* | biography and memoir craft | **negative result**: none is a term of art. "Spine" *is* established, but in Stanislavskian theatre it means the through-line of dramatic **action**, not dates; "armature" does not appear in craft literature at all | avoid — "spine" carries a misleading established sense, and "skeleton" reads badly beside a question category called *losses* |
| *fixed point* | chronology | — | **could not be verified** as academic jargon; the only sources using it that way were not citable. Do not claim it. |

Two terms from adjacent fields are worth stealing for *explanatory copy* even
though neither should be the feature name:

- **Floating chronology → anchored** (dendrochronology) is the most exact
  description of our mechanism found in any field: "A tree-ring history whose
  beginning- and end-dates are not known is called a **'floating chronology'**.
  It can be **anchored by cross-matching** a section against another chronology
  (tree-ring history) whose dates are known"
  ([Wikipedia, *Dendrochronology*](https://en.wikipedia.org/wiki/Dendrochronology)
  — tertiary source, quoted for the term, not for a claim). An undated stretch
  of someone's life *is* a floating chronology; the anchor set is what it gets
  cross-matched against.
- **Dead reckoning** (navigation) is the most exact description of the
  arithmetic: a known past position plus elapsed change gives a present
  position, which is "you were twelve, so it was 1986" exactly.

### 4.2 Three candidates

1. **Anchors.** The set of always-present questions is "your anchors"; each
   answer is an anchor; the verb is *drop an anchor*. It is already the
   codebase's noun for exactly this data, it is literature-adjacent ("temporal
   anchor points"), and everyone understands instantly what an anchor does: it
   holds something in place.
2. **Landmarks.** The literature's own term, maximally defensible in a
   citation, and it reads well as a section heading. Cost: in ordinary English
   a landmark is a building, and the word does not imply *dated*.
3. **Waypoints.** Familiar from car navigation, evokes checkpoints along a
   route, warm and modern. Cost: it implies a *journey with a destination*,
   which is a claim about a life we should not be making, and it is weaker
   than "anchor" at conveying *fixed*.

### 4.3 Recommendation: **Anchors**

Recommended because it makes the product word and the data word the same
word. `timeline.anchor_index`'s docstring *already* describes this exact
instrument — "the life-history calendar as data (Freedman et al. 1988): the
birthday, the residences with spans, the eras with spans, and the dated
landmark moments" — so naming the question set anything else would create a
second vocabulary for one concept, which is precisely what the
recurring-defect doctrine says not to do. It also composes cleanly with the
two words we already have:

- **Anchors** — the dated facts we know, and the small question set that
  collects them. Always under the Timeline; always Play-able.
- **Keystone** — the *missing* anchor with the highest leverage: the one
  answer that would place the most. (`KEYSTONE_CAP = 2`.)
- **Whisper** — v196's owner-set term: information woven into a conversation
  that fits naturally and serves a second agenda; only where it fits, at most
  one per conversation, never penalized. A still-missing anchor comes back
  this way.

Read as a sentence: *"Your anchors hold the timeline. The keystone is the
anchor you haven't dropped yet. A whisper is how we ask for it."* The three
words do not overlap and each names a different thing — a known, an unknown,
and an act of asking. The metaphors do not collide either: an anchor is
nautical, a keystone architectural, a whisper human.

Keep **landmark** as the research word (it is what the citations say) and
**anchor** as the product and code word. This document's title uses the
research word deliberately.

### 4.4 The ruling: **Landmarks** (owner-set, 2026-08-23)

The owner decided the other way, and the decision is better than the
recommendation above. **Landmarks** is the product and user-facing word — and
also the package, module and CLI name, so there is exactly one name from the
surface down to the file on disk. **`anchor` keeps the meaning it already had
in code**: the *derived* index a landmark's date becomes once it can bound
something (`timeline.anchor_index`, `basis: "anchor"`,
`chronology.from_anchor`, `timeline_interaction.anchors_for_person`).

The split §4.3 missed is that these are two different things, not two names
for one. **A landmark is the question and the answer; an anchor is what the
answer turns into.** "Where did you live?" is a landmark; `1984/1990` sitting
in the index and bounding nine other memories is an anchor. Collapsing them
would have given one identifier two meanings — the defect the
recurring-defect doctrine forbids — which is the very argument §4.3 used *for*
collapsing them, pointed the wrong way.

The sentence therefore reads: *"Your **landmarks** become the **anchors** that
hold the timeline. The **keystone** is the landmark you haven't given yet. A
**whisper** is how we ask for it."*

The join in code is `landmarks_interaction.anchors_from_landmarks`. Shipped in
v199 (`docs/pr-specs/landmarks.md`).

---

## 5. The proposed instrument

Sixteen questions, ordered easiest-recalled first per §1.2, phrased
anchor-first per chronology.md §6. **O** = asked at onboarding; **L** = surfaces
later as a whisper or a keystone. Precision is what we *expect* and store, not
what we demand.

The birth date is item 1 because it is the axis (§2.1). **Items 3–5 are the two
chains — every address, in order, and every school, in order — and they are the
instrument's real payload** (§2.7). Everything from item 7 down is ordinary
landmark collection; the two chains are the part that tiles the whole timeline
and the part someone else can help finish.

| # | Question (phrasing) | Landmark | Unlocks | Precision | When |
|---|---|---|---|---|---|
| 1 | "What's your birthday?" | birth date | **every** age statement → a year (§3.1); the axis for grade arithmetic | day | **O** |
| 2 | "Where were you born?" | birthplace | the first residence's start; region for public-event relevance | place | **O** |
| 3 | "Where were you living when you started school?" | **residence chain, opened** | opens the chain at an age-anchored point, exactly as the LHC does | place + year | **O** |
| 4 | "Until when did you live there? … And where did you go next?" *(repeats to the present)* | **residence chain, walked** | span containment for every "while we lived in X" (§3.3); tiles the whole timeline | year, month if offered | **O** for the first two hops, **L** for the rest |
| 4b | "Who else was in that house?" *(per address)* | household composition | LHC rows 3–4; dates *other people* and gives the fallback anchor when addresses fail (§5.2) | names + span | **L** |
| 5 | "Which schools — every one, in order? Roughly which years at each?" | **school chain** | grade↔age↔year (§3.2); a second independent estimate of birth year; corroborable from public record | academic year | **O** |
| 6 | "Did you go on after that — college, training, an apprenticeship? When?" | post-secondary span | bounds the late-teens/early-twenties, the densest part of the reminiscence bump | year | **L** |
| 7 | "Have you ever been married or had a long partnership? When did that begin?" | partnership start | month-grain anchor (§2.4); also dates a person, not just a date | **month** | **O** |
| 8 | "Did that change at some point — separation, divorce, or losing them?" | partnership end | closes the span; a very common *terminus ante quem* | month | **L** |
| 9 | "Do you have children? What are their birthdays?" | children's births | month-grain anchors that also date the *other* person's whole timeline | **month** | **O** |
| 10 | "What work have you done? Roughly what years?" | job spans | parallel-domain cue (Belli); the "what were you doing for work then" rung | **year, hedged** — never month (§2.4) | **L** |
| 11 | "Did you serve in the military? When?" | service span | sharply bounded, institutionally dated | month | **L** |
| 12 | "Who have you lost, and when?" | deaths | high-salience *terminus ante quem*; usually exact | year, often month | **L** — never at onboarding |
| 13 | "Was there a move that changed everything — a country, a coast?" | major migration | a transition in Brown's sense; usually splits the life in two | year | **L** |
| 14 | "Was there a year that was hard — an illness, an accident, something that stopped things?" | health/rupture | the person's own strongest landmark, if they offer it | year | **L** — offered, never demanded |
| 15 | "Was there a public event that changed *your* daily life?" | public event | last rung only, gated on personal disruption (§2.5) | year | **L** |

Onboarding is items **1, 2, 3, 4 (two hops), 5, 7, 9** — seven questions, and
five of those are one-liners. Everything else lives under the Timeline
forever and comes up as whispers or keystones. This is deliberately *not* the
"large upfront chronology survey" that issue #69 rejects; see §6.5.

### 5.1 Low precision is not failure

"Mid-eighties" is a real answer and a useful one. `parse_edtf` already
normalizes `the 1980s` → `198X`, `around 1984` → `1984~`, and `1984–1990` →
`1984/1990`, all with `earliest`/`latest` set. A landmark stored as
`198X` still intersects: combined with "after we moved to Denver (1986/..)"
it yields 1986–1989. Huttenlocher et al.'s rounding result says the coarse
answer is the *honest* one — a hedged month is worse than a confident decade
(chronology.md §6 rule 7). The instrument must therefore accept a decade
without a follow-up, and store the hedge rather than resolving it.

Two fielded instruments encode exactly this, and we should copy both rules.
SHARELIFE's residence module instructs: "**If cannot estimate, ask for the
decade and enter the mid year**" (AC007) — a decade is a legal answer, and the
midpoint is the point estimate. And BCS70/NCDS coarsen *within* a year rather
than losing it: "IF UNSURE OF EXACT MONTH, **CODE MID-SEASON MONTH: Winter:
Feb (2) Spring: May (5) Summer: August (8) Autumn: Nov (11)**" (§1.7). Our
`DateRecord` already has the machinery for both — `198X` with `earliest`/
`latest`, and season codes — so this is a matter of adopting the conventions,
not building anything.

### 5.2 Edge cases the instrument must not break on

Glasner, van der Vaart & Belli found that the number, type and temporal
distribution of landmark events differ systematically between Dutch and
American respondents, and conclude "it is important for researchers to
examine how landmark events in calendar instruments translate in diverse
cultural contexts"
([Glasner, van der Vaart & Belli, 2012, *BMS* 115:45–52](https://digitalcommons.unl.edu/psychfacpub/653/) —
landing page verified; the full text is behind a repository block and was not
fetched, so this is cited at abstract level). Concretely, for us:

- **No fixed address.** Housing instability, itinerancy, refugee movement,
  military postings, foster care: the residence chain has no clean spans.
  Fall back to *who* rather than *where* — "who were you living with?" — which
  is LHC rows 3–4 ("living arrangements"), a separate row for exactly this
  reason.
- **Non-linear schooling.** Repeated years, skipped years, interrupted and
  resumed education, non-US systems with different entry ages, homeschooling,
  no schooling. The `+5+g` rule is a heuristic with a ±1 band; it must be
  **suppressed entirely** when the person's schooling is stated as non-standard,
  never silently applied.
- **Adoption and unknown origins.** A birth date may be assigned rather than
  known, and a birthplace may be unknown or contested. Both must be storable
  as `approximate`/`conjectural` without blocking the rest of the set, and
  the question must never imply there is a right answer being withheld.
- **Estrangement and loss.** Items 8, 12 and 14 touch the hardest material in
  a person's life. They are **never** onboarding questions, they are always
  offered rather than asked, and the playbook's stop rule already binds:
  "stop on any distress signal — dating is never worth the relationship"
  (chronology.md §6 rule 10).
- **Partnerships that were not marriages.** The LHC carries cohabitation as a
  row distinct from marriage precisely because the legal event and the life
  event differ. Item 7's phrasing must not assume a wedding.
- **Non-Gregorian and non-Western calendars.** A birth date may be recorded
  in a different calendar or as a season. `DateRecord` can hold `1954~` or a
  season code; the instrument must accept those rather than demanding a
  Gregorian day.

### 5.3 Per landmark: the general question, the ladder, the derivation, the gap

Owner rulings, 2026-08-23. Onboarding asks each landmark **in generalities** —
"do you remember where you lived? where was that?", "which schools?" — and the
person answers or skips. Every landmark that is unanswered **or answered below
target specificity** stays **open on the Timeline** as an always-present
answerable item. It is never in the daily question queue, never a reminder,
never a nag; it sits there and the person fills it when they can, from memory,
from a relative, or from a records lookup. And a landmark with **no stories
attached** — a house lived in with zero moments in the vault — is itself a gap
worth asking about, and one the system could not have seen at all without the
landmark.

So each landmark needs four things defined, not one:

| Landmark | Onboarding question (general) | Specificity ladder | Derivation it unlocks | The gap it reveals |
|---|---|---|---|---|
| **Birth** | "What's your birthday?" | year → month → day; place: country → city → address | age→year for the whole corpus (§3.1); the timeline's origin | — (the axis itself) |
| **Residences** | "Do you remember where you lived? Where was that?" | city → neighbourhood → **street address** → move-in/move-out **span** → who else lived there | span containment for every "while we lived in X" (§3.3); reference intervals (§3.6) | **a place with no stories** — "you lived on Bell Avenue for six years and there's nothing here from it" |
| **Schools** | "Which schools did you go to?" | name → town → **address/district** → **grades attended** → start/end years | grade↔age↔year (§3.2); second estimate of birth year | a school with no stories; a schooling span with no residence covering it |
| **Partnerships** | "Have you been married, or had a long partnership?" | that it happened → who → year began → **month** → year ended | month-grain anchors (§2.4); dates another person | a partnership span with no moments in it |
| **Children** | "Do you have children?" | names → birth years → **birth months** | month-grain anchors; dates the child's whole page | a child with no stories before a certain age |
| **Jobs** | "What work have you done?" | employer/trade → town → **years** (hedged) | parallel-domain cue (Belli); role probes | a working decade with nothing in it |
| **Military** | "Did you serve?" | that you did → branch → **service dates** → postings | sharply bounded span | postings with no stories |
| **Losses** | *(never at onboarding)* | that it happened → who → year → month | *terminus ante quem* for anything "before we lost them" | — |

Two rules follow that the rest of the design must respect.

**"Open" is a normal resting state, not a debt.** A landmark at city-level with
no address is *answered*. It contributes bounds already. The open item exists
because a *more specific* answer would unlock more — an address makes a
residence findable in public record and makes "the house on Bell" resolvable
to a place page — not because the person owes us anything. Progress is shown;
completion is never demanded. Note that v196 **deleted** the deferral
side-state entirely, on the ruling that "I'll find out" is an ordinary answer
that files nothing. An always-open anchor is the same discipline arrived at
*without* a side-state: the item is simply still there, and nothing chases it.
Nothing in this proposal revives a deferral store.

**A landmark with no stories is new information.** v196 made unknowns
concrete — `UNKNOWN_KINDS` is now `moment · period_bound · place_span ·
era_gap · date_contradiction`, each one subject with a human label, and the
old aggregate kinds (`no_events`, `unplaced_events`, …) became counts on
`unknown_ledger`. `place_span` already asks "When did you live in {label} —
moving in to moving out?" — which is the *dating* half.

The half nothing can express yet is a place whose span is **known** and which
has **nothing in it**. That is not a dating gap, it is a *story* gap, and it
only exists once a landmark set has told us the place is there. It wants its
own kind — `place_no_stories` — ranked by the same `leverage()`, opened by its
own `KIND_OPENERS` entry ("you lived in {label} from {start} to {end} and
there's nothing here from it — what happened in that house?"), and fed to the
arc planner and the Mirror's gap finders like every other kind.

This is the clearest argument in the document that the anchor set **pays for
itself twice**: once in arithmetic, and once in questions the loop could not
otherwise ask, because the person supplied the noun.

### 5.4 The two chains as homework the person chooses

Items 3–5 are the only part of the instrument that can be *finished*, and the
only part someone else can help with (§2.7). That earns a different
affordance from every other question in this document:

- **State the payoff before the ask, in numbers we already compute.**
  `timeline.leverage()` can say "the addresses would place 14 moments" before
  the person decides. That is the honest version of persuasion: the arithmetic,
  shown.
- **Offer it as a task with an end, not a question with an answer.** "Ask your
  mother for the addresses" is homework. It has a definite scope, it can be
  handed to a relative verbatim, and it comes back as a list rather than a
  turn of conversation.
- **Accept the list in whatever form it arrives** — pasted, dictated,
  half-remembered, out of order. Ordering is recoverable (chronology.md §6
  rule 6) and partial spans still bound (§5.1).
- **Never generate the urgency.** The reason to do this while a parent is
  alive is obvious to the person and does not need saying by us. The product
  offers the task; it does not invoke mortality to motivate it. That is a
  line, and it is the same line as chronology.md §6 rule 10.
- **No connector required.** Everything here is either in the person's head, a
  relative's head, or public record they can look up themselves (§2.7.3).
  The instrument must work with zero integrations, and the design should not
  quietly assume otherwise.

This connects to the parallel *Go Deep / ask the living* thread, which is
where the task affordance itself belongs; this document only claims that the
residence and school chains are its two highest-value instances.

---

## 6. Design consequences

1. **Ask for the birth date, once, plainly.** It is the single exception to
   "never ask for a year," it is defensible from the fielded instruments
   (§2.1), and without it `from_age` is dead code. It belongs in
   `profile.yaml` (committed, safe to share) alongside `name` and `timezone`,
   and every caller of `timeline_data()` must pass it.
2. **The two chains are the instrument.** Every address in order, and every
   school in order, are the only landmark domains that are *closed lists* —
   enumerable, finite, tiling, verifiable, and finishable (§2.7). Ask the
   residence chain the way the LHC does: age-anchored opener, then "until
   when," then "where next," walking forward, never opening with a year. Ask
   the school chain as a list, then derive the years (§3.2) instead of asking
   for them. Treat both as **completable**, show progress on them, and let the
   person do them as homework with a relative or the public record (§5.4).
3. **Grain is per-domain, by evidence, not uniform.** Month for marriages,
   births and deaths; academic year for schooling; hedged year for jobs;
   decade is an acceptable terminal answer anywhere (§5.1).
4. **The calendar is a persistent surface, not a form.** Add Health's EHC is
   re-shown at every dating question and is editable at any time (§1.4).
   Ours should sit under the Timeline permanently, show its own arithmetic
   ("you were 12 that year"), and accept corrections that *add* a claim rather
   than overwrite one (chronology.md §4).
5. **This does not reinstate the big upfront survey.** Issue #69's contract
   says "replace a large upfront chronology survey with incremental,
   evidence-backed landmark repair," and requires an owner decision before the
   product flow is complete. The proposal here is compatible with that and
   should be read as its input, not its reversal: seven onboarding questions,
   eight that only ever appear as whispers or keystones, and every one of them
   skippable. The passive user who answers nothing but the daily question is
   unaffected.
6. **Answered-but-vague is answered.** Every landmark needs a specificity
   ladder, not a boolean (§5.3). A city without an address still bounds; it
   stays open only because more would unlock more, and it must never read as
   an outstanding debt.
7. **A landmark with no stories is a question we could not otherwise ask.**
   v196's `place_span` asks *when* you lived somewhere; nothing asks what
   happened there. Add a landmark-scoped **story** gap, `place_no_stories`.
   This is the second payoff of the anchor set and arguably the larger one.
8. **Landmarks are consumed by the existing machinery, not new machinery.**
   `anchor_index` already has the right shape; `keystones()` already ranks by
   leverage; `PLAYBOOK_STEPS` rungs 5–6 already wait on anchors. The
   instrument's whole job is to fill the index that four existing systems
   already read.
9. **Describe the structure honestly.** It is bounds propagation over a
   constraint graph (Allen's interval relations), not a binary tree (§3.6).
   Docs and UI copy should say "anchors narrow the window," never imply a
   solved date where an interval is what we have.
10. **Do not claim accuracy gains.** Claim *placement* gains. The landmark
   component's measured effect on accuracy is weak (chronology.md §2); the
   whole-calendar effect on completeness is strong. Our benefit is that
   probes get cheaper and more memories become placeable — a coverage claim,
   which we can measure ourselves.

---

## 7. Proposal: `landmarks` as the sixth child interaction

*Design sketch, not a contract. Follows the child-interaction paradigm in
`interactions/README.md` and the shape of `timeline` (v195, ADR 0024).*

### 7.1 Shape

A child of Conversation, like `timeline`: the package owns the prompt,
output contract and lints; a stage is substituted; **one** additive output
field is recorded on the Turn. It is a *conversation*, not a form — the
questions in §5 are the planner's ordered supply, and the model weaves them
the way the asking-supply hatch already weaves held bank questions.

```
interactions/landmarks/
  interaction.yaml          # extends: conversation; modes: collect
  prompt/{identity,behavior,examples,turn-instructions}.md
  router/{router,deflection}.md
  context/manifest.md
  questions.yaml            # THE ORDERED SET — data, not prose
  evals/{lints.yaml,rubrics.md,goldens/…}
system/landmarks_interaction.py   # pure; no writes, no model calls
```

Stages: `open | collect | confirm | close`.

- `open` — orient without interrogating ("a handful of quick ones, and then
  everything else gets easier — skip any of them").
- `collect` — walk `questions.yaml` in order, one at a time, honouring the
  chain semantics of items 3–4.
- `confirm` — read the anchors back with the arithmetic shown ("so you were
  twelve when you moved to Denver — that puts it around 1986"), which is Add
  Health's editable-calendar affordance in conversational form.
- `close` — no takeaway, no hook; this is bookkeeping the person did us a
  favour by doing.

One additive output field on the Turn: `anchor` — a `DateRecord` plus the
landmark key, or `{"skipped": true}`, or `null`. Gated on
`TurnShape.landmarks_stage`, so with the stage `None` the output contract is
byte-identical for every other interaction (the same passive-user guarantee
v195 required).

### 7.2 `interactions/landmarks/questions.yaml` (sketch)

```yaml
# The always-present anchor set. Ordered easiest-recalled first
# (Freedman et al. 1988; Belli, Encyclopedia of Survey Research Methods).
# `grain` is what we EXPECT and store — never what we demand.
version: 1
questions:
  - key: birth
    kind: date
    onboarding: true
    grain: day
    text: "What's your birthday?"
    unlocks: [age_arithmetic]
    note: "The one legitimate 'what date' opener (landmarks.md §2.1)."
  - key: birthplace
    kind: place
    onboarding: true
    grain: place
    text: "And where were you born?"
  - key: residences
    kind: chain                   # a CLOSED list — completable (landmarks.md §2.7)
    onboarding: true
    grain: year
    anchor_opener: age            # never "what year"
    text: "Where were you living when you started school?"
    chain_next:
      - "Until when did you live there?"
      - "And where did you go next?"
    per_item:
      - key: household
        onboarding: false
        text: "Who else was in that house?"
    completable: true             # "6 addresses so far — is that all of them?"
    homework: "ask a relative for the addresses"
    unlocks: [span_containment, parallel_cue, reference_intervals]
  - key: schools
    kind: chain                   # the second closed list
    onboarding: true
    grain: academic_year
    text: "Which schools — every one, in order?"
    chain_next:
      - "Roughly which years were you at each?"
    derive: grade_year            # birthday + grade -> school year (§3.2), +/- 1
    completable: true
    homework: "school names are public record — district sites list them"
    unlocks: [grade_arithmetic, birth_year_corroboration]
  - key: partnership_start
    kind: date
    onboarding: true
    grain: month
    text: "Have you ever been married, or had a long partnership? When did that begin?"
    sensitive: false
  - key: children
    kind: date_list
    onboarding: true
    grain: month
    text: "Do you have children? What are their birthdays?"
    files_to: entity              # also dates another person's timeline
  - key: work
    kind: span_list
    onboarding: false
    grain: year
    hedged: true                  # §2.4 — 72% agreement; never ask at month grain
    text: "What work have you done? Roughly what years?"
  - key: military
    kind: span
    onboarding: false
    grain: month
  - key: losses
    kind: date_list
    onboarding: false
    grain: year
    sensitive: true               # offered, never demanded; stop rule binds
  - key: public_event
    kind: date
    onboarding: false
    grain: year
    gated_on: personal_disruption # §2.5
```

### 7.3 How answers file

Through the **existing** write path, not a new one. `timeline-place` already
takes `--date/--basis/--anchor` and files the rendered date into a durable
correction (v195). Landmarks file the same way, with `basis: stated`:

- `birth` → a new committed `profile.yaml` field (`birth_date`), which is the
  one fact that must be readable without loading the timeline, plus an
  `anchor_index` entry of kind `birth`.
- residences → `type: place` entities with spans — the shape
  `anchor_index` already reads for kind `residence`.
- schooling, work, military → spans on the person's profile page, surfaced to
  `anchor_index` as kind `period`.
- partnerships, children, losses → entity records with dates (kind
  `landmark`), which also date the *other* person's page.

No new store. `anchor_index` gets full instead of nearly empty.

### 7.4 How the rest of the system consumes them

- `timeline_interaction.anchors_for_person(...)` starts returning a real set,
  so `PLAYBOOK_STEPS` rungs 5 (`sequence`) and 6 (`landmark`) become
  reachable for the first time (§3.7).
- `chronology.record_from_claim(claim, birth_date=…, anchors=…)` starts
  resolving `age` and `anchor` bases instead of dropping them.
- `timeline.keystones()` keeps working unchanged but now ranks over a
  populated graph — and the natural keystone becomes "the anchor you haven't
  dropped yet," which is what the word should have meant all along.
- v196's keystone **minting** path needs no change: a keystone whose
  `leverage()` clears the `timeline_leverage_per_story` dial (6) becomes an
  ordinary bank row in the `timeline` group, capped at one a week by
  `GROUP_CAPS`. A populated anchor index simply gives that dial a real
  population to rank over. (v195's `leverage_boost` adjacency nudge and
  `keystone_slugs` are deleted; nothing here revives them.)
- Completed chains become Allen's **reference intervals** (§3.6): the
  residence spans and school years are the coarse containers every finer
  interval is propagated inside, which is what keeps the propagation cheap and
  what makes "6 of 6 addresses" a meaningful progress number rather than a
  vanity metric.

### 7.5 Placement

**Onboarding in generalities; always open on the Timeline; never in the
queue.** Three placements, and they are distinct (§5.3):

1. **Onboarding** asks the set in generalities — "do you remember where you
   lived? where was that?", "which schools?" — and takes a skip without
   comment. Issue #96's conversation-first onboarding is the right host.
2. **The Timeline page** carries every landmark that is unanswered *or below
   target specificity* as an always-present answerable item — a quiet band
   ("Anchors · 7 of 16"), each row openable by Play or fillable inline. Never
   a modal, never a wizard, never a reminder, never a nag. An open anchor is
   a normal resting state. The person fills it when they can, and the ladder
   in §5.3 defines what "more specific" means per domain.
3. **The daily question queue never carries them.** Anchors are bookkeeping
   the person chooses; the daily question is the conversation. Mixing them
   would spend the one asking-slot a passive user has on a form field. The
   only exception is the existing keystone path: when the arithmetic says one
   missing anchor would place the most, v196 already carries it either as a
   **timeline whisper** — raised inside a conversation only where it fits, at
   most one per conversation, never pressed, never opening with a year
   (`timeline_gates.one_per_conversation`) — or, above the
   `timeline_leverage_per_story` cutoff, as one minted bank question. Anchors
   ride those two rails and add no third.

And the new gap kind: a landmark with **no stories attached** becomes a
`place_no_stories` unknown alongside v196's concrete `UNKNOWN_KINDS` (`moment
· period_bound · place_span · era_gap · date_contradiction`), ranked by the
same `leverage()` and asked with the same stop rules. "You lived on Bell
Avenue for six years and there's nothing here from it" is a question only the
anchor set can ask.

---

## Sources

- Freedman, Thornton, Camburn, Alwin & Young-DeMarco, 1988, *The Life History Calendar: A Technique for Collecting Retrospective Data*, *Sociological Methodology* 18:37–68 — https://socialinquiry.wordpress.com/wp-content/uploads/2011/10/d-freedman-et-al_1988_the-life-history-calendar_-a-technique-for-collecting-retrospective-data.pdf
- Belli, R. F., *Event History Calendar*, in *Encyclopedia of Survey Research Methods* (entry text quoted from the publisher's indexed abstract; full entry paywalled) — https://methods.sagepub.com/ency/edvol/encyclopedia-of-survey-research-methods/chpt/event-history-calendar
- PSID, *Event History Calendar methods study* documentation — https://psidonline.isr.umich.edu/Data/documentation/ehc/PSIDcalendarMethodsStudy.html
- NLSY97 Codebook Supplement, *Appendix 6: Event History Creation and Documentation* — https://nlsinfo.org/content/cohorts/nlsy97/other-documentation/codebook-supplement/appendix-6-event-history-creation-and-documentation
- SHARE-ERIC, *SHARELIFE Methodology* (Feb 2011; module order rationale, the five-row calendar, AC004/AC006/AC007) — https://share-eric.eu/fileadmin/user_upload/Methodology_Volumes/FRB-Methodology_feb2011_color-1.pdf
- Ward, K. et al., 2009, *ELSA Wave 3 Life History User Guide* (the *lifegrid*) — https://ifs.org.uk/sites/default/files/output_url_files/Wave_3_Life_History_User_Guide.pdf
- NEPS, *Starting Cohort 6 Data Manual 17.0.0* (§5.1 modularized life-course measurement; §5.3.10 residence history) — https://www.neps-data.de/Portals/0/NEPS/Datenzentrum/Forschungsdaten/SC6/17-0-0/NEPS_SC6_DataManual_17-0-0_en.pdf
- Antoni, Drasch, Kleinert, Matthes, Ruland & Trahms, 2010, *IAB FDZ-Methodenreport 05/2010* (ALWA; the cost of modular collection and the feed-back-earlier-answers fix) — https://doku.iab.de/fdz/reporte/2010/MR_05-10.pdf
- UCL Centre for Longitudinal Studies, *NCDS Age 42 questionnaire* — https://cls.ucl.ac.uk/wp-content/uploads/2017/08/NCDS-Age-42-Questionnaire.pdf
- UCL Centre for Longitudinal Studies, *BCS70 Age 42 mainstage questionnaire* (mid-season month coding) — https://cls.ucl.ac.uk/wp-content/uploads/2017/07/BCS70_Mainstage_FULL_QUESTIONNAIRE_final.pdf
- Library of Congress Veterans History Project, *Field Kit* incl. the Biographical Data Form (mirror; loc.gov PDFs 403) — https://www.winnebagopubliclibrary.org/wp-content/uploads/2024/09/vhp-2018-fieldkit-accessible.pdf
- North Dakota State Archives, *Veterans History Project question guide* — https://www.history.nd.gov/archives/vetQuestions.pdf
- Smithsonian Center for Folklife and Cultural Heritage, *Folklife and Oral History Interviewing Guide* (hosted copy) — https://www.nativeoralhistory.org/system/files/atoms/file/InterviewingGuide.pdf
- Montana State Library, *Oral History Biographical Data Sheet* — https://docs.msl.mt.gov/mmpweb/Oralhistory/Oral-History-biographical-data.pdf
- StoryCorps, *Great Questions* — https://storycorpsorg-staging.s3.amazonaws.com/uploads/TGTL2021_Great-Questions-6165ff5e77f76-6165ff5e77f77.pdf
- Baylor University Institute for Oral History, *Introduction to Oral History* (2016) — https://library.web.baylor.edu/sites/g/files/ecbvkj1806/files/2024-12/intro_manual_2016.pdf
- Oral History Association, *Best Practices* — https://oralhistory.org/best-practices/
- Add Health, *Wave III Data Documentation* (§II Event History Calendar, p. 7; Appendix D public events) — https://addhealth.cpc.unc.edu/wp-content/uploads/docs/faq/W3-DataDocumentation.pdf
- *Quality principles of retrospective data collected through a life history calendar*, 2022 — https://pmc.ncbi.nlm.nih.gov/articles/PMC9612623/
- Glasner, van der Vaart & Belli, 2012, *Calendar Interviewing and the Use of Landmark Events — Implications for Cross-cultural Surveys*, *BMS* 115:45–52 (cited at abstract level; full text not fetched) — https://digitalcommons.unl.edu/psychfacpub/653/
- van der Vaart & Glasner, 2011, *Personal Landmarks as Recall Aids in Survey Interviews*, *Field Methods* — https://journals.sagepub.com/doi/10.1177/1525822X10384367
- Allen, J. F., 1983, *Maintaining Knowledge about Temporal Intervals*, *CACM* 26(11):832–843 — https://cse.unl.edu/~choueiry/Documents/Allen-CACM1983.pdf (author-institution mirror; DOI https://doi.org/10.1145/182.358434)
- NCES, *Types of state and district requirements for kindergarten entrance and attendance, by state: 2018* — https://nces.ed.gov/programs/statereform/tab5_3.asp
- Loftus & Marburger, 1983, *Since the eruption of Mt. St. Helens…* (title verified via Europe PMC, PMID 6865744) — https://europepmc.org/article/MED/6865744
- Shum, M. S., 1998, *The role of temporal landmarks in autobiographical memory processes*, *Psychological Bulletin* 124(3):423–442 — https://europepmc.org/article/MED/9849113
- Berney & Blane, 1997, *the life grid*, *Soc Sci Med* 45(10):1519–1525 (bibliographic only; body text not obtained)
- Archaeological Institute of America, *Introduction to Archaeology: Glossary* — https://www.archaeological.org/programs/educators/introduction-to-archaeology/glossary/
- Giroux, A. L., 2003, *Date Calculations*, *OnBoard* 9:12–13 (Board for Certification of Genealogists) — https://bcgcertification.org/skillbuilding-date-calculations
- Dai, Milkman & Riis, 2014, *The Fresh Start Effect: Temporal Landmarks Motivate Aspirational Behavior*, *Management Science* 60:2563–2582 (cited for the term's semantic drift) — https://doi.org/10.1287/mnsc.2014.1901
- Europe PMC, title query for "temporal landmarks" (evidence of the drift) — https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE%3A%22temporal%20landmarks%22%20AND%20SRC%3AMED&format=json&resultType=core&pageSize=10
- Wikipedia, *Dendrochronology* (tertiary; quoted for *floating chronology* / *anchored by cross-matching*) — https://en.wikipedia.org/wiki/Dendrochronology
- FamilySearch, *United States Vital Records* — https://www.familysearch.org/en/wiki/United_States_Vital_Records
- US National Archives, *Genealogy FAQs — vital records* — https://www.archives.gov/research/genealogy/start-research/faqs

Everything in `system/research/chronology.md`'s Sources list is assumed and
not repeated here.

## Research queue

See `system/research/QUEUE.md` § Landmarks.
