# Visualizing chronological certainty

*Research-only literature review (v206). Every claim is sourced; nothing here
is implemented. It is the fourth corpus in the chronology topic and it assumes
the other two still current: `system/research/chronology.md` (v194 — how you
place ONE memory in time) and `system/research/landmarks.md` (v198 — the small
set of facts that makes placing every other memory cheap). (A third,
`system/research/go-deep.md`, v197 — the evidence-driven session, and §8's
arithmetic for what resolving an unknown is worth — was the authority this
document deferred to on the width-sum, the submodularity warnings and the STP
frame; it is retired with the Reading Room, 2026-09-03, ADR 0025's dated note,
and its arithmetic now lives in ADR 0027, the placement score, unchanged.)
What is new here is the *display* and the *level* where it gave the *ranking*
and the *margin*. It feeds a platform design issue (lifehug-platform, "The
certainty line") and `system/research.md` §4a.*

---

## 0. The picture the owner drew

> "A visual way to see all these data points, how they are floating and
> undated, and how answering one question might bring 53 things into
> alignment. In my head there's a line — my life — with floating data points
> around it; as we solve one point and bring it into the line, it drags others.
> There's got to be research showing a visual representation of the accuracy of
> a profile. The graph page visualizes the algorithm's goal (balance — a small
> sibling node means ask more there); the timeline needs its twin: a score of
> how UNORGANIZED the data is versus the goal of a straight line and a 1. I
> want research on visualizing how accurate this information is and organizing
> it on a linear timeline." — owner, 2026-08-24

The "53" is not a metaphor. It is `timeline.leverage()` on the founder vault,
promised on a keystone row and then not delivered, which is the incident
`docs/design/dating-dataflow.md` (lifehug-platform PR #633) was written to
audit. So the owner is asking for two things that turn out to be one thing: a
**level** (how placed is this life) and a **margin** (what would the next
answer do to it). This review's central finding is that the package already
computes the margin — `timeline.unknown_width` and the greedy dig plan — and
that the level is the same arithmetic read the other way.

Four literatures have already built this picture, and one of them has been
drawing it for two hundred and sixty years.

---

## 1. Bayesian chronological modelling: the field that already draws this

Archaeology has the owner's exact problem — a set of events whose dates are
intervals, a set of constraints that relate them, and a need to show a
non-specialist what tightening one thing did to everything else — and it has
had a standard plot for it since the 1990s.

### 1.1 Two curves on one axis

The convention, from the author of OxCal:

> "It is often convenient to see how the marginal posterior distributions
> relate to the original likelihood, so these are often plotted together. For
> example in OxCal, the likelihood is shown **in outline, or light grey with
> the posterior marginal distribution overlain**. This allows the effect of
> the modeling to be **visually assessed**."
> ([Bronk Ramsey, 2009, *Radiocarbon* 51(1):337–360, p. 354](https://doi.org/10.1017/S0033822200033865))

Bayliss states it from the reader's side, in the caption archaeologists copy:
"For each 14C date, 2 distributions have been plotted: one **in outline** that
is the result of simple 14C calibration, and a **solid** one based on the
chronological model used"
([Bayliss, 2009, *Radiocarbon* 51(1):123–147](https://doi.org/10.1017/S0033822200033750)).

**This is the owner's before-and-after, and it is a static overlay, not an
animation.** The unmodelled shape stays on the page underneath the modelled
one, permanently. The reader sees what the answer did because both states are
drawn at once.

Ranges under each curve are **highest posterior density** intervals — "if we
have a 95% range, it is the shortest range that includes 95% of the
probability" — reported at 68.2%, 95.4% and 99.7%
([Bronk Ramsey 2009, p. 354](https://doi.org/10.1017/S0033822200033865);
[OxCal help, *Analysis details*](https://c14.arch.ox.ac.uk/oxcalhelp/hlp_analysis_detail.html)).
Because HPD regions are routinely multi-modal, one date normally reports two
or more disjoint sub-ranges with separate probabilities — "3600–3550 cal BC
(84% probability) or 3545–3525 cal BC (11% probability)"
([Bayliss 2009, p. 127](https://doi.org/10.1017/S0033822200033750)). A date is
not always one bar, and the display has to survive that.

### 1.2 Constraints sharpen, and that is the whole point of the plot

Constraints enter as `Sequence`, `Phase`, `Boundary`, and `Before`/`After`.
The published magnitude of the sharpening, at the level of a chronology rather
than a single date:

> "we now have a methodology that allows 14C dating to produce accurate
> chronologies routinely to a resolution of **less than a century — often to
> within the span of a human lifetime and sometimes down to a generation or a
> few decades**."
> ([Bayliss 2009, p. 141](https://doi.org/10.1017/S0033822200033750))

Bronk Ramsey puts the same range as "**subcentennial**" generally and
"**decadal**… in the case of wiggle-matching"
([Bronk Ramsey, 2010, *Radiocarbon* 52(3):953](https://doi.org/10.1017/S0033822200046063)).
An independent accuracy check rather than a precision claim: at Baguley Hall
the modelled felling estimate was cal AD 1450–1470 (95% probability) against a
dendrochronological felling date of AD 1443–1478 (95% confidence) — tighter
than, and consistent with, the tree rings
([Bayliss 2009, Fig. 18](https://doi.org/10.1017/S0033822200033750)).

**Calibrated claim.** The familiar shorthand "a 200-year range collapses to a
few decades" could not be sourced to a specific published single-date example
in this session. The chronology-level statements above are what the literature
supports; do not attach the sharper figure to one date without a citation.

Two structural notes that transfer directly. First, ordering alone is not a
model: "such constraints should only ever be used in conjunction with some kind
of a grouping model… The individual fragments above do not form plausible
models on their own"
([Bronk Ramsey 2009, Fig. 3 caption](https://doi.org/10.1017/S0033822200033865)) —
the `Boundary` pair supplies the prior that makes the sharpening legitimate
(§1.5). Second, `Span`, `Interval`, `First`, `Last`, `Order` and `Difference`
are **queries**, which "do not affect the prior or the likelihoods on which the
model is based" (ibid., p. 355). A read-out is not a constraint. Our analogue:
a score is a query over the timeline, never an input to it.

### 1.3 The agreement index is a 0→1 number, and it is not a completeness score

OxCal reports `A_i = 100 F_i`, the ratio of mean likelihoods under the full
model versus a flat prior, "a reasonable minimum acceptable value being in the
region of **60%**". Two properties are usually misquoted:

- **It can exceed 100%** — "the ratio F_i can be greater than 1… as this means
  the measurement is more likely under the full model than under the zero
  model."
- **Some failures are expected** — "On average, one might expect about **1 in
  20** A_i values to drop below 60%."
  ([Bronk Ramsey 2009, pp. 356–357](https://doi.org/10.1017/S0033822200033865))

Model-level, `A_model` is preferred over `A_overall` from OxCal v4 because it
accounts for correlation between parameters (ibid.). The 60% threshold is
calibrated against the χ² test at 5%
([Bronk Ramsey, 1995, *Radiocarbon* 37(2):425–430](https://doi.org/10.1017/S0033822200030903)).

And the warning that matters most to us: these are "**not actual Bayes
factors, but rather pseudo Bayes factors**, and should only be used to
determine if a model is **consistent or inconsistent**"
([Hamilton & Krus, 2018, *American Antiquity* 83(2), Misconception 5](https://doi.org/10.1017/aaq.2017.57)).
The discipline's own one-number summary is a **consistency flag with a
threshold**, not a quality percentage — and it is not used to rank models.
That is a precedent *against* the obvious reading of the owner's "a 1."

Outliers are handled by down-weighting, not deletion: `Outlier_Model` with a
typical prior of 0.05 ("a 1 in 20 chance") returns a posterior outlier
probability per date, and "samples are progressively down-weighted… the results
from the analysis are essentially an average between a model in which the
measurement is accepted and one in which it is rejected"
([Bronk Ramsey, 2009b, *Radiocarbon* 51(3):1023–1045](https://doi.org/10.1017/S0033822200034093)).
This is the same doctrine as `chronology.reconcile` — contradictions are
weighted, never dropped (chronology.md §4).

### 1.4 The tempo plot: a cumulative curve of a life

The one existing visual whose *shape* answers "how much of this life is
placed, and where" is the **tempo plot**, introduced by
[Dye, 2016, *Journal of Archaeological Science* 71:1–9](https://doi.org/10.1016/j.jas.2016.05.006)
and formalised by Philippe & Vibet
([2020, *Journal of Statistical Software* 93, Code Snippet 1](https://doi.org/10.18637/jss.v093.c01)).

- It plots `N(t) = Σᵢ 1_{]−∞,t]}(τᵢ)` — the number of dated events occurring
  before `t`. Because the `τᵢ` are themselves estimated, "the quantity of
  interest **cannot be viewed as a counting process**"; the Bayes estimate
  under quadratic loss is `N̂(t) = Σᵢ P(τᵢ < t | M)`.
- **The envelope is a credible region, not error bars**: the MCMC sample of
  functions "provide a sample from the posterior distribution of N. Therefore
  we can easily build a credible region for the function N."
- The **activity plot** is "the **first derivative** of N̂" — the same
  information as a rate.

Read together on the Ksâr 'Akil chronology, the tempo plot shows bulk activity
between −43,000 and −35,000 and the activity plot resolves a peak at −40,000.
The authors then supply the sentence that should be pinned above any version of
this we build: these curves "characterize more the **sampling** of the evidences
of human activity" — the apparent hiatus "is probably due to the **absence of
dated shells** rather than to the absence of human activity" (ibid., §4.4–4.5).

A life-story vault's density over time is *exactly* a sampling curve. A flat
stretch means we have not asked, not that nothing happened. Any cumulative or
density rendering of a life must be captioned as coverage, never as biography.

### 1.5 Five pitfalls, all of which we would hit

**(1) The prior is not neutral, and precision can rise while accuracy falls.**
The canonical demonstration:

> "specific assumptions about prior probabilities — **implemented in
> calibration programs and not evident to the user** — may create artifacts.
> This may result in dates with **higher precision but lower accuracy**." …
> "the algorithm **improves the precision but reduces the accuracy!**"
> ([Steier & Rom, 2000, *Radiocarbon* 42(2):183–198](https://doi.org/10.1017/S0033822200058999))

Bronk Ramsey's published reply concedes the mechanism, generalises it beyond
sequences, identifies `Boundary` as the fix, and adds the interpretive sentence
that governs every range bar we would draw:

> "The age range quoted (at, for example 95%) from Bayesian analysis… is a range
> of values that includes the 95% most likely results **based on the assumed
> prior**. It does not mean that we can be 95% confident that any result lying
> outside this range is false." … "**There is no one correct prior for a given
> situation.**"
> ([Bronk Ramsey, 2000, *Radiocarbon* 42(2):199–202](https://doi.org/10.1017/S0033822200059002))

He also names the limit of the diagnostic: the agreement index "should not…
be relied upon to identify all inappropriate priors, as it will only do so if
the **measurement data themselves are inconsistent** with the prior." **A model
can be wrong and green.**

**(2) The tautological loop.** Hamilton & Krus catalogue the field's actual
failures: ordering undated material by assumption is "unsubstantiated. One
should not use priors that do not reflect the archaeology. Even if they help
provide more precise posterior probabilities, the underpinning assumptions are
unfounded"; and feeding an expectation in as a constraint means "you **build a
model to ensure you never learn something new!**… this practice results in a
**tautological loop**"
([Hamilton & Krus 2018](https://doi.org/10.1017/aaq.2017.57)).

**(3) Deleting the vague to make the picture tighter is backwards.** The same
paper warns that imprecise legacy dates "may actually have the **most secure
connection between sample and event**."

**(4) The uniform-phase assumption is an assumption.** "should be used with
**caution** as, frequently, the samples derive from one construction or
destruction level and are **not evenly distributed**"
([Bronk Ramsey 1995](https://doi.org/10.1017/S0033822200030903)). This is the
same uniformity that §2 shows aoristic analysis assumes, and it is false for a
life: memories cluster in the reminiscence bump (chronology.md §3).

**(5) Hiding the outline turns interpretation into measurement.** Bayliss:
"Renfrew's 'good objective chronology' is now **contaminated by our
archaeological opinions** — the 'posterior density estimates' shown in black in
the graphs are not just based on independent scientific evidence, but also on
the 'prior beliefs' that have been included in the model"
([Bayliss 2009, p. 127](https://doi.org/10.1017/S0033822200033750)).

The field's reporting conventions encode all of this typographically, and are
worth stealing wholesale: modelled dates are printed **in italics** to separate
them from calibrated and from calendar dates (ibid., n.2); modelled
probabilities are rounded **outward to five years**; and one may **never write
1σ/2σ** for a calibrated or modelled result, because "calibrated radiocarbon
dates and modeled probabilities are in **no way normally distributed**"
([Hamilton & Krus 2018, pp. 195–196](https://doi.org/10.1017/aaq.2017.57);
concurring, [Bronk Ramsey 2009, p. 354](https://doi.org/10.1017/S0033822200033865)).
Our equivalent of the italic is already specified: `basis` and `confidence` on
every `DateRecord`, and the documentary-editing convention that an inferred
date is marked *conjectural* (chronology.md §1).

**Other tools, briefly.** **BCal** (Buck, Christen & James) *elicits* the
prior by questioning the user, returns HPD regions and elapsed-time estimates,
and attaches its own warning that users must "investigate how **sensitive**
your results are to the decisions you have made"
([BCal introduction](https://bcal.shef.ac.uk/info/index.html)).
**ChronoModel** (Lanos & Dufresne) replaces boundary parameters with a
hierarchical **event** model in which per-date errors sit under a uniform
shrinkage density, so outliers are penalised automatically; its authors state
the trade honestly — the event model "is **more robust** than models
implemented in BCal or OxCal, although it generally yields **less precise
credibility intervals**"
([Lanos & Philippe, 2018, *CSAM* 25(2):131–157](https://doi.org/10.29220/CSAM.2018.25.2.131)).
Robustness costs precision; that is the trade we are making too.

---

## 2. Aoristic analysis: drawing what is not yet placed

### 2.1 The method

The founding paper is
[Ratcliffe & McCullagh, 1998, *IJGIS* 12(7):751–764](https://doi.org/10.1080/136588198241644),
addressing crime data that "often lacks temporal definition." The mechanism,
stated exactly:

> "The aoristic method gives each crime a value of 1 and assigns an **equal
> fraction** of that value to each unit of analysis in which the crime could
> have occurred. So if a crime could have occurred in any one of 10 hours,
> aoristic analysis will assume that there is a probability of 0.1 that the
> crime occurred in any single hour-long period."
> ([Ashby & Bowers, 2013, *Crime Science* 2:1, p. 4](https://doi.org/10.1186/2193-7680-2-1))

Per-event weights sum to 1 by construction; the aggregate is a **sum of
fractions, not a count**. Ratcliffe's follow-up introduced the visual form —
"a **temporal intensity surface** can be created"
([Ratcliffe, 2000, *IJGIS* 14(7):669–679](https://doi.org/10.1080/136588100424963)) —
and the "aoristic signature"
([Ratcliffe, 2002, *J. Quantitative Criminology* 18(1):23–43](https://doi.org/10.1023/A:1013240828824);
metadata verified, text not read).

**It is measurably better than the deterministic alternatives.** Ashby & Bowers
tested six methods against 303 pedal-cycle thefts whose true times were
recovered from CCTV. Median error: start-time −7:02, end-time +2:53, midpoint
−1:52, random −1:33, **aoristic −0:59**. Their conclusion: "Aoristic analysis
and allocation of a random time to each offence allow accurate estimation of
peak offence times… Commonly-used deterministic methods were found to be
inaccurate and to produce misleading results"
([Ashby & Bowers 2013](https://doi.org/10.1186/2193-7680-2-1)).

**Directly transferable to us**: the four deterministic alternatives are the
four ways a product is tempted to fake a date — take the earliest bound, take
the latest, take the midpoint, or guess. All four are measurably worse than
smearing the event over its interval and refusing to pick. This is the
empirical form of ADR 0024's never-invent rule.

### 2.2 What it assumes, and what it cannot show

The uniform prior is the method's known weak point, and Ashby & Bowers found
the real distribution was not uniform ("The Rayleigh test showed that the
distribution of t_actual was significantly non-uniform"). They add two shape
warnings: as the interval grows the per-unit fraction "will asymptotically
approach zero," oversmoothing; and where intervals are short a handful of
tightly-bounded events "could create a temporal peak that outweighs several
crimes with a more typical t_range." Both bite on a life: an era-wide moment
contributes almost nothing anywhere, and one day-precise birthday can spike a
year.

Crema's critique is the one that constrains our score directly:

- **The summation problem.** Five events each smeared uniformly over five
  blocks, and five events each precisely placed in a different block, yield the
  **identical** summed vector {1,1,1,1,1} — "aoristic analysis does not
  distinguish between the two scenarios." The probability of 'no change'
  between two blocks is ~0.28 in the uncertain case and 1 in the certain one.
- **Periodisation artefacts.** Because date ranges inherit shared period
  boundaries, "artificial abrupt shifts in the frequency density are likely to
  be observed at major transitions between phases and periods."
- **It is descriptive, not inferential.** "at its best aoristic analysis can
  only be a good descriptive statistic for time-frequencies; it was **never
  designed as a tool to make inferences** about the underlying statistical
  population."
  ([Crema, 2024, *Archaeometry*](https://doi.org/10.1111/arcm.12984);
  [OA preprint](https://osf.io/98qkx/download))

**This is the finding that forces the design.** A smeared density and a placed
density can look identical. Therefore the certainty picture **cannot be a
single summed curve** — it must draw the smeared and the placed as two
distinguishable things, which is precisely OxCal's outline-over-solid (§1.1)
arrived at from the opposite direction. Crema's own remedy is Bayesian
(`baorista`, parametric or ICAR with credible envelopes); ours is simpler and
visual.

The alternative to summing is sampling: Crema's earlier Monte Carlo approach
"effectively sampl[es] n time-frequencies from the universe of all possible
permutations and then comput[es] the probability of observing specific
scenarios"
([Crema, 2012, *JAMT* 19(3):440–461](https://doi.org/10.1007/s10816-011-9122-3);
paywalled, characterised from Crema 2024). That is the same idea as
Hypothetical Outcome Plots (§3.3), reached in a different field a decade
earlier.

The same pathology recurs one level up in summed probability distributions of
radiocarbon dates, where the proxies "conflate process variation and
chronological uncertainty, which makes them unsuitable for point-wise
comparisons"
([Carleton & Groucutt, 2021, *The Holocene* 31(4):630–643](https://doi.org/10.1177/0959683620981700);
see also [Contreras & Meadows, 2014, *JAS* 52:591–608](https://doi.org/10.1016/j.jas.2014.05.030)).

### 2.3 The visual grammar that exists

Ratcliffe's own R package ships the grammar
([CRAN `aoristic` 1.1.1, maintained by Ratcliffe, replacing George Kikuchi's
discontinued 0.6](https://cran.r-project.org/web/packages/aoristic/index.html);
[reference manual](https://cran.r-project.org/web/packages/aoristic/aoristic.pdf)):

- **`aoristic.df`** — the atomic structure is a matrix of weights over
  **168 units = 24 hours × 7 days**, one row per event. The grid *is* the
  heatmap substrate.
- **`aoristic.plot`** — the summed signature per unit.
- **`aoristic.graph`** — eight small-multiple charts (one per day, plus a
  total).
- **`aoristic.map`** — every event that *could* have occurred in the chosen
  unit, "**color coded to represent the aoristic weight, range >0 to 1**.
  Events with weight 1 definitely occurred during that hour, while events with
  values at the lower end of the range could have occurred at one of many
  hours."
- **`aoristic.datacheck`** — a first-class data-quality pass flagging missing
  and inverted end-times, with documented fallbacks.

Two details worth copying outright: **weight-as-colour on the individual mark**
is a shipped, field-tested encoding of "how precisely is this one thing dated,"
and **the certainty audit is its own function**, not a footnote.

Ashby & Bowers render all six estimators as **circular (24-hour) kernel density
surfaces**, overlaying estimate on truth, arguing for circular statistics on
cyclical time. A life is not cyclical, so that particular move does not
transfer — but the overlay-estimate-on-truth habit does.

### 2.4 The one published read of "how much of this is precisely dated"

Johnson ported the method to archaeological survey pottery, defining "Aoristic
Weight per interval = Interval Size / Time span for artefact type," and already
anticipating non-uniform weights "if there is an 'a priori' reason"
([Johnson, 2004, *CAA 2003*, BAR Int. Ser. 1227](https://doi.org/10.15496/publikation-2085);
[PDF](https://publikationen.uni-tuebingen.de/xmlui/bitstream/handle/10900/60663/101_Johnson_CAA_2003.pdf)).
His warning is ours, exactly, with recency in place of modernity: equal
weighting "would seriously skew the analysis in favour of **recent periods**…
Even quite generic modern artefacts will achieve weightings of 0.5–1.0, whereas
the most distinctive Palaeolithic artefacts would rarely achieve a weighting of
0.1," and in his own maps "the discrimination provided by more diagnostic
pieces has been **largely swamped** by the effect of undifferentiated coarse
pottery."

A vault has the same gradient: this year's moments are day-precise, childhood
is era-wide. A naive certainty curve will show a life that gets sharper toward
the present and read it as *a better-known present* rather than *a coarser
past*, which is a fact about memory (Huttenlocher, Hedges & Bradburn 1990 —
chronology.md §3), not about the vault's quality.

Johnson's Figure 3 is the closest published precedent to what the owner is
asking for: **three curves on one axis** — aoristic weight, a raw count of
artefacts whose range merely *overlaps* the interval, and a count of artefacts
diagnostic enough to be *pinned* to it, the third "merging with the X axis." A
direct visual read of how much of the record is precisely dated, and of where.
Orton, Morris & Pipe add the other half — normalising by how hard anyone looked
("**calibration of results for variable research intensity**",
[*Open Quaternary* 2017](https://doi.org/10.5334/oq.29)) — which for us is the
same correction as "we have not asked about that decade."

**Honest gap:** no paper was found whose *primary subject* is visualizing
temporal-certainty density. It appears as a component of the above, never as an
established form of its own.

---

## 3. Uncertainty visualization: what actually reads

### 3.1 A bounded interval reads as a fact

Three independent results say the same thing, and together they are the single
most important constraint on this design.

**Within-the-bar bias.** Newman & Scholl ran six experiments (online samples of
~200–260 each): points falling *inside* a bar are judged more likely than
equidistant points outside it. The effect survives when the bar is removed
before judgment, when the bar's direction is reversed, and under free viewing
(F(1,255)=8.24, p=0.004) — so it is a **containment** metaphor, not a memory or
numeric-extremity artifact
([Newman & Scholl, 2012, *Psychonomic Bulletin & Review*](https://perception.yale.edu/papers/12-Newman-Scholl-PBR.pdf)).

**Binary interpretation.** Correll & Gleicher name two defects of
bar-plus-error-bar, not one: the containment metaphor above, and the fact that
"values are within the margins of error, or they are not… also makes viewers
overestimate effect sizes in comparisons." Across three crowdsourced
experiments (240 participants analysed of 368 recruited, 36 stimuli each) they
found bar-chart viewers predicted significantly larger effects (bar M=1.65 vs
box/gradient 1.54, violin 1.43; F(3,3424)=23.1, p<0.001) **with higher
confidence** (F(3,3424)=3.38, p=0.018) — overconfident overestimation. Their
replacements are **gradient plots** (α-transparency encodes density) and
**violin plots** (width encodes density), chosen for being visually symmetric
about the mean and visually continuous. Adherence to the statistically expected
strategy: violin 89.2%, gradient 88.5%, box 87.4%, bar 83.2%
(F(3,2982)=7.46, p<0.0001)
([Correll & Gleicher, 2014, *TVCG* 20(12):2142–2151](https://graphics.cs.wisc.edu/Papers/2014/CG14/Preprint.pdf)).
Note the sizes: the effect is real and it is not large. They also found that
moving the margin of error into *text* fixed the containment bias "at the
expense of making the chart sufficiently confusing… that participants are
highly inaccurate… and additionally they are unjustifiably more confident in
their incorrect judgments."

**Deterministic construal error.** The sharpest name for the failure, from the
forecasting literature: users "fail to realize that the graphic depicts
uncertainty. Instead they have a tendency to **interpret the image as
representing some deterministic quantity**." And the finding that kills the
obvious fix — they tested a predictive-interval bracket against Tufte-style
dashed lines *and against a bar with blurry, transparent ends* (MacEachren's
1992 convention) and "again the errors were made at approximately the same
rate. In other words, **these classic uncertainty features did not help at
all**"
([Joslyn & Savelli, 2021, *Frontiers in Computer Science* 2:590232](https://www.frontiersin.org/articles/10.3389/fcomp.2020.590232/pdf)).
They also report that participants inferred a roughly *normal* distribution
inside an interval "with all visualizations tested" — which is exactly wrong
for an aoristic interval, where the honest prior is uniform.

**Consequence for us.** A "circa 1965–1970" whisker on a timeline will be read
as *it definitely happened inside this box*, and blurring the ends will not fix
it. What the literature offers instead is symmetry, continuity, and — §3.3 —
discreteness.

### 3.2 Intuitive is not the same as readable

MacEachren et al. ran the field's reference study on which visual variables
convey uncertainty: 72 GIScience students and professionals rating 76 symbol
sets, plus a 30-participant map-reading task
([MacEachren, Roth, O'Brien, Li, Swingley & Gahegan, 2012, *TVCG* 18(12):2496–2505](https://web.archive.org/web/20130403072321/http://www.geovista.psu.edu/publications/2012/MacEachren_IEEE_TVCG_PrePub_2012_reduced_res.pdf)).
The ranking for general uncertainty:

- **Good** (mean > 5.0 of 7): **fuzziness, location, and value** — fuzziness
  and location both with a mode of 7.
- **Acceptable** (mean 4.0–5.0): arrangement, size, transparency.
- **Unacceptable** (mean, median and mode all < 4.0): saturation, hue,
  orientation, shape. The authors flag saturation specifically as
  "particularly interesting… commonly cited… thought to be intuitively related
  to uncertainty."

**Correction to a commonly-repeated ordering:** the top tier is *fuzziness,
location, value* — **arrangement is not in it, and value is**. Directionality
was part of the tested encoding: "fuzziness: more fuzzy = less certain;
location: further from center = less certain; value: **lighter = less
certain**."

Set that beside Joslyn & Savelli's null result for blurry ends and the field's
central tension is explicit — Correll, Moritz & Heer's name for it is the
**preference/performance gap**, where designers "must choose between encoding
uncertainty in a way that is intuitive but error prone, or use higher fidelity
channels that may not intuitively convey uncertainty." Their own answer is the
**value-suppressing uncertainty palette**: a quantized bivariate colormap
shaped as a tree, so that as uncertainty rises the number of distinguishable
*value* colours collapses and an uncertain region **cannot be read precisely at
all**
([Correll, Moritz & Heer, 2018, CHI](https://idl.cs.washington.edu/files/2018-UncertaintyPalettes-CHI.pdf)).
That is the most interesting idea in this section for us: rather than annotate
imprecision, **withhold the precision the data does not have**.

Sketchiness is a viable third channel — "as intuitive as blur; although people
subjectively prefer dashing style over blur, grayscale and sketchiness"
([Boukhelifa, Bezerianos, Isenberg & Fekete, 2012, *TVCG* 18(12):2769–2778](https://inria.hal.science/hal-00717441v1/file/nb_uncertainty.pdf))
— with a documented cost and a documented side-benefit: "relative area judgment
is **compromised** by sketchy rendering," but "where a visualization is clearly
sketchy, **engagement may be increased** and… attitudes to participating in
visualization annotation are more positive"
([Wood, Isenberg, Isenberg, Dykes, Boukhelifa & Slingsby, 2012, *TVCG* 18(12):2749–2758](https://inria.hal.science/hal-00720824/document)).
For a surface whose entire purpose is to invite annotation, that second finding
is not a footnote.

### 3.3 What outperforms a static interval, and for which task

**Hypothetical Outcome Plots** animate draws from the distribution instead of
summarising it. 288 MTurk subjects, 96 per condition (HOPs / error bars /
violin), 400 ms per frame. The results are **task-dependent and the caveats are
load-bearing**:

- Single variable, **mean estimation**: HOPs *significantly worse* than error
  bars and violins on high-variance data (both p_adj < 0.001).
- Two variables, **Pr(B > A)**: strong HOPs advantage (F(2,573) = 73, 57, 84,
  220; all p_adj < 0.001). Static encodings failed badly — "on no task was the
  mean absolute error less than 36 percentage points" for error bars.
- Three variables: HOPs lower MAE (F(2,573)=43, p<0.001).
  ([Hullman, Resnick & Adar, 2015, *PLOS ONE* 10(11):e0142444](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0142444))

The authors add that "The experiment tasks were about as favorable as possible
for the abstract, static representations." A follow-up extends the advantage to
*trends in time series*
([Kale, Nguyen, Kay & Hullman, 2019, *TVCG*](https://doi.org/10.1109/TVCG.2018.2864909)).

**Quantile dotplots** achieve much of the same benefit statically, by drawing a
fixed number of equally-likely discrete outcomes so probability is read by
*counting* rather than integrating area — chosen partly because it fits a
phone-sized strip where a density plot's height blows up for a confident
prediction. Across 541 analysed participants, dotplot-20 had the lowest
variance (SD ≈ 11 percentage points), about **1.15× more precise** than the
density plot
([Kay, Kola, Hullman & Munson, 2016, CHI, *When (ish) is My Bus?*](https://www.mjskay.com/papers/chi_2016_uncertain_bus.pdf)).
The stronger claim comes from the decision study, with real money at stake:
decisions with quantile dotplots of 50 outcomes "were (1) better on average,
having expected payoffs **97% of optimal** (95% CI [95%, 98%]), **5 percentage
points more than control** (95% CI [2, 8]); and (2) more consistent, having
within-subject SD of 3 percentage points… 4 percentage points less than
control." CDF plots performed nearly as well; textual uncertainty "was
sensitive to the probability interval communicated"
([Fernandes, Walls, Munson, Hullman & Kay, 2018, CHI](https://mjskay.com/papers/chi2018-uncertain-bus-decisions.pdf)).

**The transferable idea, cheaply:** a memory dated to "sometime in the
Yucaipa years" drawn as *N discrete dots spread across those years* is
readable, honest, uniform-by-construction (which is the actual prior), and
sized for a phone — and it is visibly a different object from a single dot
sitting on one month.

### 3.4 Timelines specifically — and Priestley got there in 1764

The best precedent in this entire review is the oldest. Joseph Priestley's own
*Description of a Chart of Biography* (1764):

> "The method I have used in this chart is to express **certainty by a full
> line, and what is uncertain by dots, or a broken line**, disposing of the
> dots in the following manner, **according to the kind or degree of the
> uncertainty** they have to express."
> ([Priestley, 1764, full text](https://archive.org/download/bim_eighteenth-century_a-description-of-a-chart_priestley-joseph_1764/bim_eighteenth-century_a-description-of-a-chart_priestley-joseph_1764_djvu.txt))

He then specifies a **five-level grammar**, and it is more sophisticated than
most modern practice: a single dot at a line's end for "a little before or
after"; a dot *beneath* the terminus for "about"; full-then-dots for a certain
birth and an uncertain death; dots-then-full for the reverse; for "flourished
at or about" a date, a short full line drawn **two-thirds before and one-third
after** it, with three dots before and two after, "because, in general, men are
said to flourish much nearer the time of their death than the time of their
birth"; and where even the century is unknown, "there is **no full line made at
all**, but only dots or a broken line."

Three properties to take: uncertainty is a **property of each end
independently**, not of the mark as a whole; it is **graded**, not binary; and
it is **asymmetric** where the underlying reasoning is asymmetric. All three
map onto `DateRecord`'s `earliest`/`latest`/`granularity` without translation.
(This *is* Priestley's own text; the frequently-cited secondary,
Rosenberg & Grafton's *Cartographies of Time*, could not be consulted and is
not relied on here.)

**Topotime** (Grossner & Meeks, Stanford, 2013) supplies the modern data shape.
A timespan is a quad `{s, ls, ee, e}` — start, latestStart, earliestEnd, end —
"adopted that terminology" from Simile Timeline; the outer terms mean
**"not before"** and **"not after"**, deliberately *not* *terminus post/ante
quem*, which implies documented evidence. The parser emits a polygon computed
"as trapezoids": a ramp up, a plateau at y=1, a ramp down, where y ∈ [0,1] is
"probability or alternatively, '**percent certainty**'". Optional `sls`/`eee`
terms articulate the ramps; area-of-intersection between two tSpans gives "a
relative level of temporal coincidence"
([*Temporal Geometry in Topotime*, 23 Dec 2013](https://raw.githubusercontent.com/kgeographer/topotime/master/docs/TemporalGeometry.pdf);
[project about page](https://raw.githubusercontent.com/kgeographer/topotime/master/about.html)).
**Calibrated note:** the trapezoid glyph is verified; the name "steamer plot"
sometimes attached to it appears nowhere in the project's own materials and is
not used here.

**PeriodO** reaches the same four numbers independently and then declines to
draw a curve through them. A period is an OWL-Time `ProperInterval` whose
beginning and end "can never be precisely identified," so the model carries a
**start interval** and a **stop interval**, each with `earliestYear` and
`latestYear`
([PeriodO Technical Overview](https://perio.do/technical-overview/)). The
discipline is the part to copy: each interval also carries the source's own
words, and "**the `skos:prefLabel` of an interval should be considered the
authoritative description**" — the numbers exist "for the purposes of ordering
and visualizing." They explicitly rejected fuzzy membership curves — "Natural
language is already a compact and easily indexable way to represent imprecision
or uncertainty. Rather than imposing an arbitrary mapping from natural language
to parameterized curves, we prefer to maintain the original natural language
terms" — and abandoned an earlier significant-digits scheme because "In almost
every single case that we observed, authors did not explicitly state a precise
level of uncertainty… we would, in effect, have been **putting words in
authors' mouths**"
([Golden & Shaw, 2016, *PeerJ CS* 2:e44](https://web.archive.org/web/20221218110339/https://peerj.com/articles/cs-44/)).

That last sentence is the never-propose-a-date rule, arrived at by a completely
different community for a completely different reason. It is also the argument
against ever rendering a life-interval as a smooth probability ramp: we do not
know the ramp, and drawing one invents it.

**Allen's interval algebra** is the vocabulary for what is known when no date
is: seven named relations — *before, equal, meets, overlaps, during, starts,
finishes* — of which six have distinct inverses, giving **6 × 2 + 1 = 13**.
Allen's motivation is ours verbatim: "In applications in which such knowledge
is imprecise or relative, current representations based on date lines or time
instants are **inadequate**"
([Allen, 1983, *CACM* 26(11):832–843](https://doi.org/10.1145/182.358434);
[Rochester TR 86, revised](https://urresearch.rochester.edu/fileDownloadForInstitutionalItem.action?itemId=10182&itemFileId=22361)).
`chronology.RELATIONS` is currently a three-element subset (`before`, `after`,
`during`); the algebra is the principled superset if ordering ever needs to be
first-class on the display.

**EDTF / ISO 8601-2:2019** is the interchange format the package already
speaks. Level 1: whole-date qualification with `?` (uncertain), `~`
(approximate), `%` (both), only at the end and applying to the whole date;
unspecified digits from the right with `X` (`201X`, `2004-XX`); extended
intervals with `..` for open and empty for unknown (`1985-04-12/..`,
`../1985-04`). Level 2 adds per-component qualification, where a character to
the **right** of a component applies to it and everything left of it
(`2004-06~-11`) and one to the **left** applies to that component only
(`?2004-06-~11`), plus `X` anywhere in a component (`1984-1X`) and sets
(`[1667,1668,1670..1672]`)
([Library of Congress, *EDTF*, 4 Feb 2019](https://www.loc.gov/standards/datetime/)).
`system/chronology.py` implements Level 1 and that is the right stopping point:
Level 2 is much less widely implemented, and per-component qualification is a
distinction our elicitation ladder never produces.

**The survey position.** Aigner, Miksch, Schumann & Tominski treat
indeterminacy as a first-class property of time — "*don't know exactly when*
information," introduced either by explicit earliest/latest specification or
implicitly by granularity conversion — and their §8.4 verdict is the honest
state of the art: "**we still do not know how to do this generally** for
different applications and different visualization techniques"
([*Visualization of Time-Oriented Data*, 2nd ed., 2023, open access](https://library.oapen.org/rest/bitstreams/ded8e046-46bd-4d5d-8573-7056412f9c13/retrieve);
[timeviz.net](https://www.timeviz.net/)). Their catalogue names the technique
closest to PeriodO's model: **PlanningLines** (Aigner et al. 2005), nested bars
for minimum and maximum duration bounded by caps that encode the *start
interval* and the *end interval* — one glyph, four numbers, no invented curve.
The **SOPO diagram** is the other idea worth knowing: plot begin-time against
end-time, so an interval becomes a *point* and temporal uncertainty becomes a
*polygon's area*.

Two negative results, so that later readers do not chase them: **Time Curves**
has no uncertainty component at all (the terms appear zero times; its
noise-injection section is MDS layout robustness testing), and no dedicated
literature was found on **storyline visualization with uncertain dates**.

### 3.5 Does showing uncertainty destroy trust?

Authors believe it does, and mostly do not show it. Of **612 data
visualizations** from 121 articles published in February 2019 by leading
data-journalism and social-science outlets, **449 (73%) presented data intended
for inference, but only 14 (3%) portrayed uncertainty visually** — while 76% of
90 surveyed professional authors said they had depicted uncertainty in the past
year. Reasons given for omitting it: not wanting to confuse or overwhelm
viewers **62%**, no access to the uncertainty information 47%, not knowing how
to calculate it 26%, not wanting to make the data seem questionable 17%
([Hullman, 2020, *TVCG*, "Why Authors Don't Visualize Uncertainty"](https://arxiv.org/pdf/1908.01697)).

The evidence says the fear is **specific to words, not to numbers**. Four
online experiments (combined n = 4,249) plus a live field experiment on the BBC
News website (n = 1,531), total n = 5,780:

| effect | Cohen's *d* | 95% CI |
| --- | --- | --- |
| uncertainty → perceived reliability of the number | −0.34 | [−0.16, −0.53] |
| **numeric** uncertainty → trust in numbers | **−0.15** | [−0.05, −0.24] |
| **verbal** uncertainty → trust in numbers | **−0.55** | [−0.35, −0.74] |
| uncertainty → trustworthiness of the source | −0.12 | [−0.03, −0.22] |
| — driven by verbal | −0.21 | [−0.12, −0.31] |
| — numeric | −0.03 | [−0.03, 0.06] (n.s.) |

([van der Bles, van der Linden, Freeman & Spiegelhalter, 2020, *PNAS* 117(14):7672–7683](https://pure.rug.nl/ws/files/131063442/7672.full.pdf))

In Experiment 1 verbal hedging dropped trust by a full scale point (M 3.51 vs
4.52, d = 0.75) while numeric uncertainty did not differ significantly from
control. The BBC field experiment replicated it.

**The rule this yields is one sentence: publish a range, not a hedge word.**
"1985–1989" costs almost nothing in trust; "probably around the mid-eighties"
costs a lot. That is a direct instruction for how a date chip is written.

One counterweight: it is not only *whether* you show uncertainty but *which*.
Comparing 95% confidence intervals against 95% prediction intervals,
"participants are willing to pay more for and overestimate the effect of a
treatment when shown confidence intervals relative to prediction intervals,"
and "depicting **inferential** uncertainty causes participants to
**underestimate variability in individual outcomes**"
([Hofman, Goldstein & Hullman, 2020, CHI](https://doi.org/10.1145/3313831.3376454)).
Our interval is the aoristic one — *where could this actually have happened* —
which is the prediction-interval analogue, and the honest one.

---

## 4. One number from 0 to 1

### 4.1 Completeness is not an intrinsic property

Wang & Strong derived data-quality dimensions empirically from data
*consumers*, defining data quality as "data that are fit for use by data
consumers," and produced four categories: intrinsic, contextual,
representational and accessibility. The detail that matters here is in their
framework-adjustment table: **completeness was moved out of the intrinsic
category into the contextual one**. Their own gloss — "Contextual DQ highlights
the requirement that data quality must be considered **within the context of
the task at hand**," whereas "Intrinsic DQ denotes that data have quality in
their own right"
([Wang & Strong, 1996, *JMIS*](https://courses.washington.edu/geog482/resource/14_Beyond_Accuracy.pdf)).

The most-cited empirical framework in the field concluded that completeness is
task-relative. A context-free 0→1 "how complete is this life" number asserts
exactly what their respondents rejected. **A placement score must therefore be
scoped to a stated task** — here, *can the timeline order and place what it
holds* — and never presented as a verdict on the life or on the person.

### 4.2 It is undefined without a declared scope

Razniewski & Nutt formalise partial completeness with **table completeness**
statements ("certain parts of a relation are complete") and **query
completeness** statements, and show the core decision problem is TC-QC
entailment
([Razniewski & Nutt, 2011, *PVLDB* 4(11)](http://www.vldb.org/pvldb/vol4/p749-razniewski.pdf)).
The lesson is blunt: completeness is only meaningful relative to a declared
scope, and "this is complete" is a claim someone must **assert** — it is not
derivable from the data. Their motivating case, a school database whose
statistics drove funding, is our shape exactly.

The knowledge-base literature says the same in recall terms. KB quality has
been measured by size and precision — YAGO "manually evaluated on a sample, and
was shown to have a precision of 95%" — while recall, "the proportion of facts
of the real world that are covered by the KB," has been neglected; their
framing example is that the KB knows Obama fathered Malia and Sasha but "does
not tell us whether these are **all** of his children"
([Razniewski, Suchanek & Nutt, 2016, AKBC](https://aclanthology.org/W16-1308.pdf)).
The trivial oracle — the **Partial Completeness Assumption**, predict complete
if any object exists — "will (wrongly) state that Barack Obama is complete for
the relation hasChild"; richer oracles reach "up to 100% precision" for *some*
relations only, and the same paper cites **71% of people in Freebase having no
known place of birth**
([Galárraga, Razniewski, Amarilli & Suchanek, 2017, WSDM; arXiv:1612.05786](https://arxiv.org/abs/1612.05786)).

**The denominator does not exist for a life.** Nobody knows how many memories a
person has. This is the open-world problem, and it is why the score below is
built on the **width of what we hold** and never on a count of what we lack.

### 4.3 Recoin — the closest live precedent

Wikidata's **Recoin** ("Relative Completeness Indicator") is the strongest
existing precedent for a per-entity completeness chip shown to the person who
can fix it. It shows "the extent of information found on an item **in
comparison with other similar items**," rendered as "a colored progress bar,
showing **5 possible color-coded levels**." Method: take the entity's top-5
missing properties, average their class-frequency, and band — Level 5 at 0–5%,
Level 4 at 5–10%, Level 3 at 10–25%, Level 2 at 25–50%, Level 1 at 50%+.
Multi-class entities weight frequency by class size; properties under 0.01%
frequency count as zero; and place and date of death are "strictly filtered
out" for living humans as "frequent yet frequently undesired"
([Wikidata:Recoin](https://www.wikidata.org/wiki/Wikidata:Recoin)).

Three properties transfer intact:

1. **Peer-relative, never absolute.**
2. **Coarse-banded — five levels, not a continuous percentage.**
3. **Decomposed** — the indicator and the named list of what is missing ship
   together, so the number is always accompanied by the thing to do about it.

The third is the one that makes it a tool rather than a grade. Lifehug already
has its half: the unknowns list, the keystone star, and the leverage sentence.

### 4.4 The width measure, and the arithmetic that is actually correct

For a uniform distribution on `[a, b]`, differential entropy is exactly
**h = log(b − a)** — the log of the interval width — and for independent
components the chain rule gives `h(X₁,…,Xₙ) = Σᵢ h(Xᵢ)`
([*Differential entropy*, table of differential entropies, after Cover & Thomas](https://en.wikipedia.org/wiki/Differential_entropy)).
So a summed log-width *is* the joint differential entropy of independent
uniform intervals. That is the exact justification for a width-based measure of
"how pinned down is this," and it is not an analogy.

Three caveats must travel with it or the number will mislead:

1. **It can be negative** — U(0, ½) has differential entropy −log 2. "Thus,
   differential entropy does not share all properties of discrete entropy."
2. **It is not scale-invariant** — `h(aX) = h(X) + log|a|`; "the differential
   entropy of a quantity measured in millimeters will be log(1000) more than
   the same quantity measured in meters." (It *is* translation-invariant.)
3. It "is not invariant under change of variables, and is therefore most useful
   with dimensionless variables."

**Practical consequence: use Shannon entropy over a discretised interval**
(fixed bins — days, months, years) or a plain normalised width, both of which
are non-negative and comparable. If a log-width sum is used anywhere it must be
described as an interval-width bookkeeping device in log-units of a chosen
grain, not as a scale-free information quantity.

The forward-looking version of the same quantity is expected information gain,
`EIG_θ(ξ) := E_p(y|ξ)[H[p(θ)] − H[p(θ|y,ξ)]]` — equivalently "the mutual
information between y and θ given ξ… or the expected Kullback-Leibler
divergence from the posterior to the prior"
([Rainforth, Foster, Ivanova & Bickford Smith, *Modern Bayesian Experimental
Design*, *Statistical Science*; arXiv:2302.14545 §2.1](https://arxiv.org/pdf/2302.14545),
after [Lindley, 1956](https://doi.org/10.1214/aoms/1177728069)). ADR 0027
already rules it out as the ranking objective for the right reason — it
needs a prior the vault does not have — and nothing here changes that.

**And ADR 0027's warning applies to the score, not just the plan.**
Summing marginal interval widths measures "the smallest hypercube containing"
the feasible polytope, so where ordering constraints exist it **overestimates**
— three events each in [0,50] with `t₁ ≤ t₂ ≤ t₃` give a marginal sum of 150
against a true joint flexibility of 50, a 3× overestimate
([Mountakis, Klos & Witteveen, 2015, ICAPS](https://doi.org/10.1609/icaps.v25i1.13720)).
A width-based *score* inherits this exactly: it will read a well-ordered but
loosely-bounded life as more disorganised than it is. The fix is known and
costs the same O(n³) as the Floyd–Warshall already implied by the STP frame,
but it is not free, and until it is built the score must be described as an
**upper bound on disorder**, never as an exact one.

### 4.5 Goodhart, named precisely

Manheim & Garrabrant define a Goodhart effect as the case where "optimization
causes a collapse of the statistical relationship between a goal which the
optimizer intends and the proxy used for that goal," with four mechanisms
([arXiv:1803.04585](https://arxiv.org/abs/1803.04585);
[full text](https://ar5iv.labs.arxiv.org/html/1803.04585)):

- **Regressional** — "When selecting for a proxy measure, you select not only
  for the true goal, but also for the difference between the proxy and the
  goal."
- **Extremal** — "Worlds in which the proxy takes an extreme value may be very
  different from the ordinary worlds" where the relation was estimated.
- **Causal** — "When the causal path between the proxy and the goal is
  indirect, intervening can change the relationship" (including *Metric
  Manipulation*).
- **Adversarial** — multi-agent exploitation of a known metric.

**Two of the four bite here.** *Extremal*: a person pushed toward 1.00 is
pushed into the regime where nothing about the score was calibrated — the
last few undated moments are undated precisely because they are the hardest.
*Causal / metric manipulation*: filling a date field is causally upstream of
the score without being causally upstream of *knowing when this happened*.
Campbell's law is the social form: "The more any quantitative social indicator
is used for social decision-making, the more subject it will be to corruption
pressures"
([*Campbell's law*](https://en.wikipedia.org/wiki/Campbell%27s_law)).

The strongest **experimental** result — not an adage — is **surrogation**:
managers fail "to fully appreciate the fact that measures are merely
representations of the strategic constructs," acting "as though the measures
were the construct of interest," and across two experiments the tendency "is
most prevalent when managers are compensated on a **single** measure of a
strategic construct, and… **less prevalent** when… compensated on **multiple**
measures"
([Choi, Hecht & Tayler, *The Accounting Review*; SSRN 1464803](https://doi.org/10.2139/ssrn.1464803)).

That is a measured finding that **one number is worse than several** — and it
is the sourced argument for the owner's "a 1" being shown as a small banded
chip beside the graph's own balance reading, rather than as the timeline's
headline.

**Honest gap:** no source could be found for the widely-assumed claim that
product completion meters (LinkedIn "profile strength," dating-app completion
bars) induce low-quality filler. The argument here rests on surrogation and
Goodhart, not on direct evidence about meters, and should be stated that way.

### 4.6 Proper scoring rules — the only principled guard

Gneiting & Raftery define a scoring rule as **proper** relative to a class P if
`S(Q, Q) ≥ S(P, Q)` for all P, Q ∈ P, and strictly proper if equality holds only
when P = Q, "thereby **encouraging honest quotes** by the forecaster"; "proper
scoring rules encourage the forecaster to make careful assessments and to be
honest"
([Gneiting & Raftery, 2007, *JASA* 102(477):359–378](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf)).

Two further gifts from that paper. Their stated goal for probabilistic
forecasting is "to maximize the **sharpness** of the predictive distributions
**subject to calibration**" — the exact slogan for a system that wants narrow
date intervals and must not reward invented ones. And they propose the
**interval score** "as a utility function in interval estimation that addresses
**width as well as coverage**" — a literature-backed scoring function for
precisely the object we are scoring.

**This is the answer to "the score must not reward inventing dates."** A
completeness meter — *does this field have a value?* — is an **improper**
scoring rule: it is maximised by reporting any value at all, true or not. A
width-based score over stored intervals is not, because the elicitation ladder
refuses to record a narrower interval than the person can hold (chronology.md
§6 rung 7; `chronology.widen_for_elapsed`), and a hedged answer is stored as a
*wider* interval with a weaker `confidence`. Guessing does not pay, because the
guess is not stored as a point.

We cannot compute the coverage half of the interval score — there is no ground
truth for a life. The honest consequence is that the score must be **explicitly
one-sided**: it measures sharpness only, and it is therefore only trustworthy
while the never-invent rule holds upstream of it. **The score is downstream of
the lint, and it does not police itself.**

---

## 5. Answer → watch it snap into place

### 5.1 The positive result, and its exact scope

Heer & Robertson is the strongest evidence for animated transitions: two
controlled experiments, 24 screened subjects (aged 26–62, M = 49.6), object
tracking and change estimation, finding that "animated transitions **can
significantly improve graphical perception**," with animation significantly
better than static across all conditions (F(2,286) ≥ 22.03, p < 0.001)
([Heer & Robertson, 2007, InfoVis](https://idl.cs.washington.edu/files/2007-AnimatedTransitions-InfoVis.pdf)).

Their design rules, organised under Tversky et al.'s two principles — the
**Congruence Principle** ("the structure and content of the external
representation should correspond to the desired structure and content of the
internal representation") and the **Apprehension Principle** ("…should be
readily and accurately perceived and comprehended") — are: *maintain valid data
graphics during transitions* (intermediate states must still be legible charts,
"to avoid unwarranted attributions to the data"); *use consistent
semantic-syntactic mappings*; *group similar transitions*; *minimize
occlusion*; *maximize predictability*; **use staging for complex transitions**;
and "make transitions **as long as needed, but no longer**." Their tested
durations were **1.25 s and 2 s**.

### 5.2 Three results that constrain it hard

**Staggering does not work.** The polish detail Heer recommends was tested
directly and failed: "We found that introducing staggering has a negligible, or
even negative, impact on multiple object tracking performance. The potential
benefits of staggering may be outweighed by strong costs: a **loss of
common-motion grouping information**… and less predictability about when any
specific object would begin to move"
([Chevalier, Dragicevic & Franconeri, 2014, *TVCG* 20(12):2241–2250](https://hal.inria.fr/hal-01054408/file/staggered-study.pdf)).
Note this contradicts the Common Fate rationale Heer invokes — staggering
destroys common fate. **If many marks move, move them together.**

**Animation is for presentation, not analysis.** Comparing animated trend
visualization against two static alternatives: "trend animation can be
challenging to use even for presentations; while it is the fastest technique
for presentation and participants find it enjoyable and exciting, it does lead
to many participant errors. **Animation is the least effective form for
analysis**; both static depictions of trends are significantly faster than
animation, and the small multiples display is more accurate"
([Robertson, Fernandez, Fisher, Lee & Stasko, 2008, *TVCG*](http://www.cc.gatech.edu/~john.stasko/papers/infovis08-anim.pdf)).

**And the mental map buys less than it is credited with.** In dynamic graphs,
"small multiples gave significantly faster performance than animation overall
and for each of our five graph comprehension tasks," with animation more
accurate for two set-identification tasks — and, decisively for the settling
metaphor, "**Preserving the mental map under either the animation or the small
multiples condition had little influence** in terms of error rate and response
time"
([Archambault & Purchase, 2011, *TVCG*](https://doi.org/10.1109/tvcg.2010.78);
the mental-map idea originates with
[Misue, Eades, Lai & Sugiyama, 1995, *JVLC*](https://doi.org/10.1006/jvlc.1995.1010)).

Worth knowing about the idiom's origin: force-directed layout is presented by
its authors as a **heuristic** — "strives for uniform edge lengths… developed in
analogy to forces in natural systems"
([Fruchterman & Reingold, 1991, *SP&E* 21(11)](https://doi.org/10.1002/spe.4380211102)).
The settling animation everyone finds satisfying is an artifact of iterative
relaxation. It was never designed to communicate anything.

**Calibrated note.** Tversky, Morrison & Bétrancourt's own paper could not be
retrieved this session; the two principles above are quoted through Heer &
Robertson, which is a reliable verbatim secondary. Its overall skeptical
finding — Heer & Robertson characterise it as "finding no benefit for
communicating the workings of complex systems," with an exception made for
animated transitions in visualizations — should be verified against the
original before it is leaned on further.

### 5.3 What survives

**Supported:** a *short* (≈1–2 s), *un-staggered*, *semantically valid*
transition showing a *small number of specific marks* moving from a known
before-state to a known after-state, where every intermediate frame is still a
legible chart.

**Not supported:** a general "watch everything settle" animation. Where many
things change, the literature says show the before and the after, not a longer
animation — which is, once again, OxCal's outline-over-solid overlay (§1.1),
and it is *better* than the animation because it persists.

**The honest framing of the owner's ask:** the settle is not an analysis
surface. It is the presentation of one causal claim — *you answered this, and
these three things moved* — and its job is legibility of that claim, nothing
more. The engagement finding from sketchy rendering (§3.2) is the closest
thing the literature offers to a defence of doing it for delight, and it is
about invitation to annotate, which is exactly what this page wants.

---

## 6. Design consequences

Numbered so a contract can cite them.

1. **Draw the unplaced and the placed as two distinguishable things on one
   axis.** Crema's summation problem (§2.2) proves a single summed curve cannot
   tell them apart; OxCal's outline-under-solid (§1.1) is the field's answer.
   Keep the wide interval visible underneath the placed mark, permanently.
2. **The score is a level and the leverage is its margin — one arithmetic, two
   readings.** `timeline.unknown_width` already ranks on width reduction
   (ADR 0027); the score is the same widths summed and
   normalised. Building them apart would be the promise/delivery drift the
   dating-dataflow audit already found once.
3. **Score on WIDTH, never on presence.** A field-filled meter is an improper
   scoring rule, maximised by writing anything down (§4.6). A width score is
   not, because the ladder stores a hedged answer as a wider interval.
4. **The score is downstream of the never-propose-a-date lint and does not
   police itself** (§4.6). It is only honest while
   `timeline_interaction.proposes_a_date` holds.
5. **Band it; never render a bare continuous percentage.** Recoin's five levels
   (§4.3) and the surrogation result that one measure is worse than several
   (§4.5). This also respects the timeline's own standing ruling that it never
   counts a percentage or a streak.
6. **Ship the number and the named next thing together** (§4.3). The unknowns
   list and the ★ already are that half.
7. **Describe the score as an upper bound on disorder, not an exact one**
   (§4.4) — marginal width sums overestimate wherever ordering constraints
   exist, by up to 3× in the worked case.
8. **Never write a percentage as a verdict on the life.** Completeness is
   contextual, not intrinsic (§4.1), and the denominator does not exist (§4.2).
   Scope the words to what the timeline can order and place.
9. **Publish a range, not a hedge word.** Numeric uncertainty costs ≈0.15 d in
   trust; verbal hedging costs ≈0.55 d (§3.5). "1985–1989" not "probably
   sometime in the mid-eighties."
10. **Do not rely on blur or fuzzy ends to carry the message.** They rank top
    for *intuitiveness* (§3.2) and measurably failed to reduce deterministic
    construal error (§3.1). Use them decoratively at most.
11. **Prefer withholding precision to annotating imprecision** — the
    value-suppressing palette idea (§3.2). A moment known only to an era should
    be *unable* to be read to a year.
12. **Consider discrete dots over a continuous band for a wide interval**
    (§3.3). Uniform by construction, phone-sized, countable, and visibly a
    different object from a pinned mark.
13. **Uncertainty is a property of each END, graded and possibly asymmetric** —
    Priestley 1764 (§3.4), and it maps onto `earliest`/`latest`/`granularity`
    with no translation.
14. **Never draw a probability ramp we do not have.** Topotime's trapezoid is
    honest only where the ramps are specified; PeriodO's refusal — "we would, in
    effect, be putting words in authors' mouths" — is the position that matches
    ADR 0024 (§3.4).
15. **Keep the person's own words authoritative over the numbers** (PeriodO,
    §3.4). The `DateRecord.provenance` and the `display` string already do this;
    the visual must not outrank them.
16. **Caption any density-over-time reading as COVERAGE, not biography**
    (§1.4). A flat stretch means nobody asked. Johnson's recency skew (§2.4) is
    the same warning: a life will always look sharper near the present, and
    that is memory, not quality.
17. **Distinguish derived from stated on the display** (§1.5's italic
    convention). v205's cross-dating pass (ADR 0026) already marks what it
    derived and reports it as `cross_dating` plus
    `counts["events_cross_dated"]`, so the inputs exist: a score computed from
    stated dates only, shown beside the one that includes derivation, is the
    honest pair.
18. **If it animates: ≤2 s, un-staggered, few marks, every frame a legible
    chart** (§5.1, §5.2). More than a handful of movers ⇒ show before/after
    instead.
19. **The animation is presentation, not analysis** (§5.2). It may never be the
    only way to see what changed.
20. **A model can be wrong and green** (§1.5). Whatever score exists, it must
    not be readable as a claim that the timeline is *correct* — only that it is
    *tight*. Sharpness subject to calibration; we can only measure the
    sharpness.

---

## 7. Honest gaps in this review

Stated so a later reader does not mistake silence for support.

- **No literature exists whose primary subject is visualizing temporal-certainty
  density** (§2.4). Every precedent here is a component of something else.
- **No literature was found on storyline visualization with uncertain dates**
  (§3.4).
- **Gschwandtner, Bögl, Federico & Miksch, "Visual Encodings of Temporal
  Uncertainty: A Comparative User Study," *TVCG* 22(1):539–548 (2016)** is the
  single most on-topic empirical paper for §3.4 and **could not be obtained**
  ([doi:10.1109/TVCG.2015.2467752](https://doi.org/10.1109/TVCG.2015.2467752),
  bibliographic record verified). It is the first thing to acquire.
- **Tversky, Morrison & Bétrancourt (2002)** is quoted only through Heer &
  Robertson (§5.2).
- **Bayliss 2015, "Quality in Bayesian chronological models in archaeology,"
  *World Archaeology* 47(4):677–700** — cited by Hamilton & Krus as the field's
  quality survey, and unreachable this session
  ([doi:10.1080/00438243.2015.1067640](https://doi.org/10.1080/00438243.2015.1067640)).
  Likewise Historic England's *Radiocarbon Dating and Chronological Modelling*
  guidelines.
- **Dye 2016's own full text** was unreachable; the tempo plot's mathematics is
  cited from Philippe & Vibet's formalisation, which is the safer source anyway.
- **Ratcliffe 2002** and **Crema 2012** are characterised from secondary
  sources; both are paywalled.
- **ISO/IEC 25012** could not be reached and is not relied on (§4.1).
- **No evidence was found either way about product completion meters inducing
  filler** (§4.5). The Goodhart argument stands on surrogation, not on meters.
- **"Steamer plot"** as a name for Topotime's trapezoid is unsourced and is not
  used here (§3.4).
- **The OxCal range-bar and hatching rendering conventions** are not documented
  in the software's own help pages; §1.1 describes only what is stated in print.
- **Rosenberg & Grafton, *Cartographies of Time*** could not be consulted;
  §3.4 rests on Priestley's own 1764 pamphlet, which is stronger.
- Effect sizes throughout §3.1 are **real but modest** (violin 89.2% vs bar
  83.2%). Nothing here supports a claim that changing the mark transforms
  comprehension.

---

## Sources

**Bayesian chronological modelling**

- Bronk Ramsey, C., 1995, *Radiocarbon calibration and analysis of stratigraphy: the OxCal program*, Radiocarbon 37(2):425–430 — https://doi.org/10.1017/S0033822200030903
- Bronk Ramsey, C., 2000, *Comment on 'The use of Bayesian statistics for 14C dates of chronologically ordered samples'*, Radiocarbon 42(2):199–202 — https://doi.org/10.1017/S0033822200059002
- Bronk Ramsey, C., 2009, *Bayesian analysis of radiocarbon dates*, Radiocarbon 51(1):337–360 — https://doi.org/10.1017/S0033822200033865
- Bronk Ramsey, C., 2009b, *Dealing with outliers and offsets in radiocarbon dating*, Radiocarbon 51(3):1023–1045 — https://doi.org/10.1017/S0033822200034093
- Bronk Ramsey, C., 2010, *Complex chronological modeling*, Radiocarbon 52(3) — https://doi.org/10.1017/S0033822200046063
- OxCal help, *Analysis details* — https://c14.arch.ox.ac.uk/oxcalhelp/hlp_analysis_detail.html
- OxCal help, *Viewing output* — https://c14.arch.ox.ac.uk/oxcalhelp/hlp_output.html
- Bayliss, A., 2009, *Rolling out revolution: using radiocarbon dating in archaeology*, Radiocarbon 51(1):123–147 — https://doi.org/10.1017/S0033822200033750
- Steier, P. & Rom, W., 2000, *The use of Bayesian statistics for 14C dates of chronologically ordered samples*, Radiocarbon 42(2):183–198 — https://doi.org/10.1017/S0033822200058999
- Hamilton, W. D. & Krus, A. M., 2018, *The myths and realities of Bayesian chronological modeling revealed*, American Antiquity 83(2) — https://doi.org/10.1017/aaq.2017.57
- Palomo, A. et al., 2022, wiggle-match at La Draga, Radiocarbon 64(5) — https://doi.org/10.1017/RDC.2022.56
- BCal (Buck, Christen, James), *Introduction* — https://bcal.shef.ac.uk/info/index.html
- Lanos, P. & Philippe, A., 2018, *Event date model: a robust Bayesian tool for chronology building*, CSAM 25(2):131–157 — https://doi.org/10.29220/CSAM.2018.25.2.131
- ChronoModel (Lanos & Dufresne) — https://chronomodel.com/
- Dye, T. S., 2016, *Long-term rhythms in the development of Hawaiian social stratification*, JAS 71:1–9 — https://doi.org/10.1016/j.jas.2016.05.006
- Philippe, A. & Vibet, M.-A., 2020, *Analysis of archaeological phases using the R package ArchaeoPhases*, JSS 93, Code Snippet 1 — https://doi.org/10.18637/jss.v093.c01
- ArchaeoPhases (CRAN) — https://cran.r-project.org/web/packages/ArchaeoPhases/index.html

**Aoristic analysis and summed distributions**

- Ratcliffe, J. H. & McCullagh, M. J., 1998, *Aoristic crime analysis*, IJGIS 12(7):751–764 — https://doi.org/10.1080/136588198241644
- Ratcliffe, J. H., 2000, *Aoristic analysis: the spatial interpretation of unspecific temporal events*, IJGIS 14(7):669–679 — https://doi.org/10.1080/136588100424963
- Ratcliffe, J. H., 2002, *Aoristic signatures and the spatio-temporal analysis of high volume crime patterns*, J. Quantitative Criminology 18(1):23–43 — https://doi.org/10.1023/A:1013240828824
- Ratcliffe, J. H., *Aoristic analysis* (author's own summary) — https://www.jerryratcliffe.net/aoristic-analysis
- `aoristic` R package (Ratcliffe; after Kikuchi) — https://cran.r-project.org/web/packages/aoristic/index.html and https://cran.r-project.org/web/packages/aoristic/aoristic.pdf
- Ashby, M. P. J. & Bowers, K. J., 2013, *A comparison of methods for temporal analysis of aoristic crime*, Crime Science 2:1 — https://doi.org/10.1186/2193-7680-2-1
- Johnson, I., 2004, *Aoristic analysis: seeds of a new approach to mapping archaeological distributions through time*, CAA 2003 — https://doi.org/10.15496/publikation-2085
- Crema, E. R., 2012, *Modelling temporal uncertainty in archaeological analysis*, JAMT 19(3):440–461 — https://doi.org/10.1007/s10816-011-9122-3
- Crema, E. R., 2024, *A Bayesian alternative for aoristic analyses in archaeology*, Archaeometry — https://doi.org/10.1111/arcm.12984 (preprint: https://osf.io/98qkx/download)
- Orton, D., Morris, J. & Pipe, A., 2017, *Catch per unit research effort*, Open Quaternary — https://doi.org/10.5334/oq.29
- Roberts, J. M. et al., 2012, *A method for chronological apportioning of ceramic assemblages*, JAS 39(5):1513–1520 — https://doi.org/10.1016/j.jas.2011.12.022
- Contreras, D. A. & Meadows, J., 2014, JAS 52:591–608 — https://doi.org/10.1016/j.jas.2014.05.030
- Carleton, W. C. & Groucutt, H. S., 2021, *Sum things are not what they seem*, The Holocene 31(4):630–643 — https://doi.org/10.1177/0959683620981700
- Steinmann, L. & Weissová, B., 2021, *datplot*, Advances in Archaeological Practice — https://doi.org/10.1017/aap.2021.8

**Uncertainty visualization**

- Belia, S., Fidler, F., Williams, J. & Cumming, G., 2005, *Researchers misunderstand confidence intervals and standard error bars*, Psychological Methods — https://pubmed.ncbi.nlm.nih.gov/16392994/
- Cumming, G., Fidler, F. & Vaux, D. L., 2007, *Error bars in experimental biology*, J Cell Biol — https://doi.org/10.1083/jcb.200611141
- Correll, M. & Gleicher, M., 2014, *Error bars considered harmful*, TVCG 20(12):2142–2151 — https://graphics.cs.wisc.edu/Papers/2014/CG14/Preprint.pdf
- Newman, G. E. & Scholl, B. J., 2012, *Bar graphs depicting averages are perceptually misinterpreted: the within-the-bar bias*, Psychonomic Bulletin & Review — https://perception.yale.edu/papers/12-Newman-Scholl-PBR.pdf
- Joslyn, S. & Savelli, S., 2021, *Visualizing uncertainty for non-expert end users*, Frontiers in Computer Science 2:590232 — https://www.frontiersin.org/articles/10.3389/fcomp.2020.590232/pdf
- Hullman, J., Resnick, P. & Adar, E., 2015, *Hypothetical outcome plots outperform error bars and violin plots*, PLOS ONE 10(11):e0142444 — https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0142444
- Kale, A., Nguyen, F., Kay, M. & Hullman, J., 2019, *Hypothetical outcome plots help untrained observers judge trends in ambiguous data*, TVCG — https://doi.org/10.1109/TVCG.2018.2864909
- Kay, M., Kola, T., Hullman, J. & Munson, S., 2016, *When (ish) is my bus?*, CHI — https://www.mjskay.com/papers/chi_2016_uncertain_bus.pdf
- Fernandes, M., Walls, L., Munson, S., Hullman, J. & Kay, M., 2018, *Uncertainty displays using quantile dotplots or CDFs improve transit decision-making*, CHI — https://mjskay.com/papers/chi2018-uncertain-bus-decisions.pdf
- MacEachren, A. M. et al., 2012, *Visual semiotics & uncertainty visualization: an empirical study*, TVCG 18(12):2496–2505 — https://web.archive.org/web/20130403072321/http://www.geovista.psu.edu/publications/2012/MacEachren_IEEE_TVCG_PrePub_2012_reduced_res.pdf
- Correll, M., Moritz, D. & Heer, J., 2018, *Value-suppressing uncertainty palettes*, CHI — https://idl.cs.washington.edu/files/2018-UncertaintyPalettes-CHI.pdf
- Wood, J. et al., 2012, *Sketchy rendering for information visualization*, TVCG 18(12):2749–2758 — https://inria.hal.science/hal-00720824/document
- Boukhelifa, N., Bezerianos, A., Isenberg, T. & Fekete, J.-D., 2012, *Evaluating sketchiness as a visual variable for the depiction of qualitative uncertainty*, TVCG 18(12):2769–2778 — https://inria.hal.science/hal-00717441v1/file/nb_uncertainty.pdf
- Hullman, J., 2020, *Why authors don't visualize uncertainty*, TVCG — https://arxiv.org/pdf/1908.01697
- van der Bles, A. M., van der Linden, S., Freeman, A. L. J. & Spiegelhalter, D. J., 2020, *The effects of communicating uncertainty on public trust in facts and numbers*, PNAS 117(14):7672–7683 — https://pure.rug.nl/ws/files/131063442/7672.full.pdf
- Hofman, J. M., Goldstein, D. G. & Hullman, J., 2020, *How visualizing inferential uncertainty can mislead readers about treatment effects*, CHI — https://doi.org/10.1145/3313831.3376454
- Gschwandtner, T., Bögl, M., Federico, P. & Miksch, S., 2016, *Visual encodings of temporal uncertainty: a comparative user study*, TVCG 22(1):539–548 — https://doi.org/10.1109/TVCG.2015.2467752 *(not obtained)*

**Time models and timeline forms**

- Priestley, J., 1764, *A Description of a Chart of Biography* — https://archive.org/download/bim_eighteenth-century_a-description-of-a-chart_priestley-joseph_1764/bim_eighteenth-century_a-description-of-a-chart_priestley-joseph_1764_djvu.txt
- Grossner, K. & Meeks, E., 2013, *Temporal Geometry in Topotime* — https://raw.githubusercontent.com/kgeographer/topotime/master/docs/TemporalGeometry.pdf
- Topotime, *About* — https://raw.githubusercontent.com/kgeographer/topotime/master/about.html
- PeriodO, *Technical Overview* — https://perio.do/technical-overview/
- Golden, P. & Shaw, R., 2016, *Nanopublication beyond the sciences: the PeriodO period gazetteer*, PeerJ CS 2:e44 — https://web.archive.org/web/20221218110339/https://peerj.com/articles/cs-44/
- Allen, J. F., 1983, *Maintaining knowledge about temporal intervals*, CACM 26(11):832–843 — https://doi.org/10.1145/182.358434
- Library of Congress, 2019, *Extended Date/Time Format (EDTF) Specification* — https://www.loc.gov/standards/datetime/
- Aigner, W., Miksch, S., Schumann, H. & Tominski, C., 2023, *Visualization of Time-Oriented Data*, 2nd ed. (open access) — https://library.oapen.org/rest/bitstreams/ded8e046-46bd-4d5d-8573-7056412f9c13/retrieve ; https://www.timeviz.net/
- Bach, B. et al., 2015, *Time curves*, TVCG 22(1):559–568 — https://aviz.fr/~bbach/timecurves/Bach2015timecurves.pdf

**Completeness, scoring, and the single number**

- Wang, R. Y. & Strong, D. M., 1996, *Beyond accuracy: what data quality means to data consumers*, JMIS — https://courses.washington.edu/geog482/resource/14_Beyond_Accuracy.pdf
- Razniewski, S. & Nutt, W., 2011, *Completeness of queries over incomplete databases*, PVLDB 4(11) — http://www.vldb.org/pvldb/vol4/p749-razniewski.pdf
- Razniewski, S., Suchanek, F. & Nutt, W., 2016, *But what do we actually know?*, AKBC — https://aclanthology.org/W16-1308.pdf
- Galárraga, L., Razniewski, S., Amarilli, A. & Suchanek, F., 2017, *Predicting completeness in knowledge bases*, WSDM — https://arxiv.org/abs/1612.05786
- Wikidata:Recoin (Balaraman, Razniewski & Nutt) — https://www.wikidata.org/wiki/Wikidata:Recoin
- *Differential entropy* (table of differential entropies, after Cover & Thomas) — https://en.wikipedia.org/wiki/Differential_entropy
- Lindley, D. V., 1956, *On a measure of the information provided by an experiment*, Ann. Math. Statist. 27(4):986–1005 — https://doi.org/10.1214/aoms/1177728069
- Rainforth, T., Foster, A., Ivanova, D. R. & Bickford Smith, F., *Modern Bayesian experimental design*, Statistical Science — https://arxiv.org/pdf/2302.14545
- Mountakis, K., Klos, T. & Witteveen, C., 2015, *Temporal flexibility revisited*, ICAPS — https://doi.org/10.1609/icaps.v25i1.13720
- Manheim, D. & Garrabrant, S., 2018, *Categorizing variants of Goodhart's law* — https://arxiv.org/abs/1803.04585
- *Campbell's law* — https://en.wikipedia.org/wiki/Campbell%27s_law
- Choi, J., Hecht, G. W. & Tayler, W. B., *Lost in translation: the effects of incentive compensation on strategy surrogation*, The Accounting Review — https://doi.org/10.2139/ssrn.1464803
- Espeland, W. N. & Sauder, M., 2007, *Rankings and reactivity*, AJS 113(1) — https://doi.org/10.1086/517897
- Gneiting, T. & Raftery, A. E., 2007, *Strictly proper scoring rules, prediction, and estimation*, JASA 102(477):359–378 — https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf

**Animation**

- Heer, J. & Robertson, G., 2007, *Animated transitions in statistical data graphics*, InfoVis — https://idl.cs.washington.edu/files/2007-AnimatedTransitions-InfoVis.pdf
- Chevalier, F., Dragicevic, P. & Franconeri, S., 2014, *The not-so-staggering effect of staggered animated transitions*, TVCG 20(12):2241–2250 — https://hal.inria.fr/hal-01054408/file/staggered-study.pdf
- Robertson, G., Fernandez, R., Fisher, D., Lee, B. & Stasko, J., 2008, *Effectiveness of animation in trend visualization*, TVCG — http://www.cc.gatech.edu/~john.stasko/papers/infovis08-anim.pdf
- Archambault, D., Purchase, H. & Pinaud, B., 2011, *Animation, small multiples, and the effect of mental map preservation in dynamic graphs*, TVCG — https://doi.org/10.1109/tvcg.2010.78
- Misue, K., Eades, P., Lai, W. & Sugiyama, K., 1995, *Layout adjustment and the mental map*, JVLC — https://doi.org/10.1006/jvlc.1995.1010
- Fruchterman, T. M. J. & Reingold, E. M., 1991, *Graph drawing by force-directed placement*, SP&E 21(11) — https://doi.org/10.1002/spe.4380211102
- Tversky, B., Morrison, J. B. & Bétrancourt, M., 2002, *Animation: can it facilitate?*, IJHCS 57(4) — https://doi.org/10.1006/ijhc.2002.1017 *(not obtained; quoted via Heer & Robertson)*

## Research queue

Tracked as backlog, in priority order, with ingestion status: see
`system/research/QUEUE.md`.
