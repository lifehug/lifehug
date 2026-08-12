# Phase 3 — The Elicitation Craft: How Professional Interviewers Get People to Talk

Compiled 2026-08-11 for Lifehug's interaction design. Format: claim → source → design implication, evidence quality noted. Builds on (does not repeat) phases 1–2.

---

## 1. Rapport-based professional interviewing — what works at the highest stakes

**1.1 — Rapport + MI-consistent behavior produces yield, even from the least willing speakers on Earth.** The ORBIT program (Laurence & Emily Alison et al., 2013, *Psychology, Public Policy, and Law*) coded 418 real UK police interviews (288 hours) with convicted terrorists: interviewer use of motivational-interviewing-consistent skills (autonomy, acceptance, adaptation, empathy, evocation) → adaptive suspect behavior → increased interview yield. Now the backbone of UK counter-terrorism interview training; companion work shows rapport-based technique also reduces counter-interrogation tactics. *Highest-ecological-validity data in the field; correlational path model.*
→ The ceiling on how much users tell you is set by relational behavior, not question cleverness. Autonomy-support is a yield technique: "We can go anywhere you want with this — what part of that year matters to you?"

**1.2 — A single "maximizing" move measurably collapses yield.** Same dataset: even minimal pressuring, judging, sarcasm, demanding, or challenging-interruption increased maladaptive behavior and directly reduced yield. The effect is asymmetric: one bad move costs more than one good move gains. *Strong, replicated across ORBIT datasets.*
→ Design for ZERO pressure moves, not "mostly warm." No "you haven't told me much about X," no streak guilt, no "just one more question," no evaluative reactions to thin answers. Pressure phrasing = hard prohibition; QA tests for it.

**1.3 — Information-gathering beats accusatorial approaches on quantity AND quality.** Meissner, Redlich et al. meta-analyses (Campbell 2012; *J. Experimental Criminology* 2014; updated Catlin et al. 2024): more relevant information, more true statements, fewer false ones. *Meta-analytic; strong.*
→ The AI's only mode is information-gathering. Never "test" the user against their own record in a challenge frame — discrepancies are curiosity material, not confrontation material.

**1.4 — The FBI's Behavioral Change Stairway: influence is earned sequentially through listening.** Vecchi, Van Hasselt & Romano, 2005: active listening → empathy → rapport → influence → behavioral change; skipping steps fails. Stage 1 micro-skills: minimal encouragers, paraphrasing, emotion labeling, mirroring, open questions, effective pauses. *Field-derived, case-validated; micro-skill list matches the experimental literatures below.*
→ No steering before listening moves have been banked in the same session. Even a 4-turn chat opens with receiving, not steering.

**1.5 — Dreeke's rapport principles: their thoughts front and center, ego suspended, validation.** Robin Dreeke (former head, FBI Behavioral Analysis Program), 2011: ego suspension and validation are the highest-leverage techniques; plus open how/what questions and honest light time-frames ("this'll just take a minute" lowers the felt commitment). *Practitioner; convergent with ORBIT/MI.*
→ The AI has no ego to suspend — but LLMs DO have a failure mode of performing their own cleverness. The AI's job is to be impressed, not impressive. Honest "quick one today" framing genuinely lowers the cost of starting a daily chat — only if true.

---

## 2. The Scharff technique — and its ethical translation

**2.1 — The technique and its experimental record.** Hanns Scharff (Luftwaffe interrogator, ~500 Allied pilots, never coercive), tested by Granhag, Oleszkiewicz, Kleinman et al. (first test 2015; meta-analytic review: Luke 2021, *Applied Cognitive Psychology*). Five tactics on a friendly foundation: conversational tone; never press; the "illusion of knowing it all" (open with a substantial accurate summary of what you already know); pose CLAIMS to confirm/disconfirm instead of questions; deadpan new information. Replicated results: more new and more precise information than direct questioning; sources rate the interviewer as more knowledgeable; and — signature finding — sources UNDERESTIMATE how much they revealed. *Meta-analytic; strong.*

**2.2 — Mechanism, decomposed.** (a) Perceived-knowledge lever: if the listener already knows most of it, the marginal cost of telling feels near zero. (b) Complicity lever: confirming/correcting a claim feels less active than answering a question. (c) Counter-strategy defeat: sources can't track what's new when questions never mark what the interviewer lacks.

**2.3 — Ethical translation for Lifehug.** Users aren't hostile, but telling still has costs: effort, "where do I start," "too trivial," "already told this," self-consciousness. Honestly deployed:
- **Demonstrated prior knowledge (the honest "illusion")** — Lifehug genuinely knows the corpus. Opening a thread with an accurate warm summary ("Here's what I have about the Peace Corps years: Ghana, '94–'96, the school, the malaria episode, and Ama who ran the kitchen") makes telling feel like ADDING to a shared record rather than performing from scratch, and makes the interviewer feel worth talking to. No deception needed — the one place the full technique runs truthfully.
- **Confirm/correct claims as a low-cost turn type** — "So the Denver move came before your brother's wedding, if I have that right?" People correct errors almost compulsively, and correction reliably arrives with elaboration.
- **Invert the concealment** — Scharff deadpans new information; Lifehug does the opposite: visibly receive and celebrate new material ("I didn't have any of that — it changes how I understand the whole Chicago chapter"). The underestimation effect serves spies and robs users; here the speaker should FEEL the archive growing.

*Do-not-import: feigning knowledge; concealing what's new; purpose ambiguity.*

---

## 3. The cognitive interview — memory enhancement, ported to life stories

**3.1 — Core result.** Fisher & Geiselman, 1992; meta-analysis Memon, Meissner & Fraser, 2010 (65 experiments): large increase in correct details (d ≈ 1.2; commonly 25–40%+ more information) with only a small error increase and no meaningful confabulation-rate increase — accuracy proportion preserved while volume rises. *The strongest-evidenced interview protocol in psychology.*

**3.2 — Components, each translatable:** context reinstatement (mentally recreate the scene — sights, sounds, smells, internal state; the most effective single mnemonic); report everything (no detail too small; fragments welcome); varied retrieval (backwards order, other perspectives); transfer of control ("you were there, I wasn't; you do the telling"); open-ended first, cued second; witness-compatible questions (follow THEIR retrieval order); no interruptions.

**3.3 — Bad interviewing, quantified.** Fisher, Geiselman & Raymond 1987: real officers interrupted witnesses on average **7.5 seconds** after free narrative began; rigid question lists in interviewer order; closed-question reliance — each suppresses recall, and frequent interruption TRAINS short answers. Enhanced CI vs standard: 57.5 vs 39.6 correct statements. *Strong.*
→ In chat, the "interruption" is a response arriving with a new topic or question stack mid-thread. Rules: ONE question max per turn; if the user's message ends mid-arc, respond with a continuer, not a new question; never redirect until the thread is visibly complete.

**3.4 — The Self-Administered Interview proves the mnemonics work as written copy.** Gabbert, Hope & Fisher 2009/2012: a booklet embedding context-reinstatement + report-everything elicits more correct information than free recall and PROTECTS the memory for later retellings. *Strong, replicated.*
→ CI mnemonics can live in question phrasing and standing UI copy. Also: an early detailed first telling protects the memory — prompt stories SOON after a user first mentions an event.

**3.5 — Autobiographical retrieval science.**
- **Reminiscence bump**: adults over ~40 disproportionately recall ages 10–30 (Rubin; Koppel & Rubin 2016). The bump's location is CUE-DEPENDENT: odor cues → early childhood (<10); music cues → own bump + involuntary fast vivid retrieval (Jakubowski et al. 2020); "most important memories" → 15–30. *Strong.*
- **Retrieval practice**: practiced autobiographical retrieval increases episodic detail on later recall; life-review therapy reduces depression in older adults. *Moderate.*
- **Landmark anchoring**: life-history-calendar methods show anchoring recall to personal landmarks (moves, jobs, births) substantially improves completeness. *Moderate-strong.*
→ (a) Weight questions toward each user's ages 10–30 for volume; use sensory-cue phrasing to reach childhood ("What did your grandmother's house smell like?") — cue type is a steering wheel for which era opens. (b) Ask about the music of specific years. (c) Build the landmark timeline early and hang questions off it. (d) Revisiting a story ENRICHES it — "walk me through it again, whatever comes now" is a legitimate deepening move, not redundancy.

---

## 4. Micro-skills of keeping people talking

**4.1 — Silence and pauses.** Post-answer silence hands the turn back; interviewees resume with more elaborated self-generated material. *Moderate (CA/practitioner convergence).*
→ The chat-native version of silence is the **question-free receiving turn**: reflection only, no question — the user choosing to type more IS the elaboration. Use especially after emotionally significant material. Voice: literal 3–5s tolerance.

**4.2 — Backchannels: listeners are co-narrators.** Bavelas, Coates & Johnson 2000, *JPSP*: distracting listeners degraded their backchannels — and tellers' stories objectively deteriorated. Two classes with distinct effects: **generic** ("mm-hm") → teller advances to new events; **specific** (content-responsive: "he drove the Buick into the lake?!") → teller elaborates on the just-told material. *Strong experimental.*
→ A precision steering tool: choose backchannel CLASS deliberately per turn — specific for depth, generic to advance. Also the sharpest evidence that visible listening quality causally changes telling quality.

**4.3 — Mirroring (repeating last words).** Voss practitioner claim; research: verbal mimicry is prosocial (van Baaren 2003 — verbatim repetition doubled tips vs paraphrase; Kulesza "Echo Effect" 2014; Maddux 2008 mimicry→trust), but obvious mimicry backfires, and direct disclosure-yield evidence is absent. *Moderate for affiliation; practitioner for yield.*
→ Default register = the user's own nouns, phrases, names for things (also implements witness-compatible questioning). The literal mirror is a cheap continuer in moderation; LLMs are prone to formulaic overuse — cap frequency.

**4.4 — Emotional labeling.** Affect labeling is implicit emotion regulation — naming an emotion dampens amygdala response (Lieberman 2007; Torre & Lieberman 2018). Both good and bad for storytelling, by valence: for painful/avoided material, labeling lowers arousal enough to STAY IN the story; for joyful material, a clinical label flattens the intensity savoring should amplify. Tentative labels also double as Scharff-style claims inviting correction-plus-elaboration ("It sounds like you'd already forgiven him by then" → "Not forgiven exactly — more like…"). *Strong mechanism; practitioner deployment.*
→ Label negative affect tentatively and early; for positive affect prefer savoring moves over labels. Always tentative form — being correctably wrong is a feature.

**4.5 — Open vs. closed questions: the most-quantified craft finding in the field.** NICHD Protocol studies (Lamb), Powell, Oxburgh et al. 2010: **invitations** ("Tell me everything about…") elicit responses several times longer and richer with highest accuracy; option-posing and suggestive questions produce the shortest, least accurate answers. Among open subtypes, initial invitations and DEPTH prompts ("tell me more about the part where…") outperform breadth prompts. The **Griffiths Question Map** operationalizes auditing question-type mix; **TED prompts** (Tell/Explain/Describe) are the UK PEACE-model mnemonic. The NICHD **cued invitation** — "You mentioned [their words]; tell me more about that" — is the single best-evidenced follow-up form: mirroring + demonstrated listening + invitation in one move. *Strong, extensively replicated.*
→ Enforce a question grammar: default = TED invitation; follow-up default = cued invitation quoting the user's phrase; 5WH probes for specifics; closed questions only to pin facts at natural seams; option-posing ("was it scary or exciting?") and presupposing questions banned. This is LINTABLE — the product can audit its own question-type mix per session.

**4.6 — Not interrupting** is the hygiene factor everything else depends on (§3.3).

---

## 5. Disclosure reciprocity — and what substitutes for a self

**5.1 — Interviewer disclosure increases interviewee disclosure, with caveats.** Jourard's dyadic effect; Davis & Sloan 1974: facilitated but sustained only while the interviewer keeps disclosing. Sprecher 2013: turn-taking alternation itself matters. Caveats: can misfire as burden-shifting. *Moderate-strong, old but consistent.*

**5.2 — The effect transfers to chatbots.** Lee, Yamashita, Huang & Fu, CHI 2020: over three weeks, a chatbot that itself self-disclosed produced reciprocally deeper, sustained user self-disclosure + higher intimacy; styles without it failed to deepen. And Lucas et al. 2014: people who believed the interviewer was fully automated feared judgment less and disclosed MORE, especially sensitive topics. *Moderate/strong.*
→ The AI's non-judgment is a disclosure asset never to squander with evaluative reactions. **Substitutes for a self, ranked:** (1) demonstrated knowledge and continuity — remembering is the AI's vulnerability-equivalent: it proves investment over time, which is what human disclosure signals; (2) reactive disclosure — honest first-person reactions to the story itself ("that detail about the folded map is going to stay with me"), without fabricating a biography; (3) normalizing statements — "a lot of people find the year after a parent dies goes blurry" (standard clinical shame-reducer); (4) vulnerability priming via question framing ("What's a moment from that marriage you've never had a good chance to tell properly?"). *Hard rule: no invented autobiographical disclosures — a fictitious childhood poisons trust retroactively.*

---

## 6. The ethical line — manipulation vs. facilitation

**Framework** (SEP "Ethics of Manipulation"; Susser, Roessler & Nissenbaum 2019): manipulation is influence that is COVERT — bypassing rational agency. Facilitation preserves autonomy. **Lifehug's four-part test for any elicitation move:**
1. **Beneficiary**: value accrues to the speaker (their private archive). ✓ by product structure.
2. **No purpose deception**: the user knows the AI wants their fullest story — that IS the advertised product.
3. **Autonomy preserved**: techniques widen options (easier to tell), never narrow them (harder to refuse). Declining stays costless.
4. **Endorsement test**: if we showed the user the design doc for the technique, would they say "yes, do that to me"?

Passes cleanly: open/TED/cued invitations; context reinstatement; report-everything permission; silence and continuers; specific backchannels; tentative labels; honest demonstrated knowledge and confirmation claims; normalization; reactive disclosure; sensory/landmark cueing; autonomy statements. Fails → §7e.

---

## 7. Synthesis for design

### (a) Turn-level elicitation toolkit — ranked moves

| # | Move | Form | Evidence |
|---|------|------|----------|
| 1 | Cued invitation | "You said '[their exact words]' — tell me more about that." | Strong (NICHD/Lamb; Powell) |
| 2 | TED opener | "Tell me about / Describe / Walk me through…" — one question per turn | Strong |
| 3 | Context-reinstatement phrasing | "Put yourself back in that kitchen — what could you smell? Who was there?" | Strong (CI meta) |
| 4 | Report-everything permission | "Nothing's too small — the trivial details are usually the best parts." | Strong (CI; SAI as written copy) |
| 5 | Specific backchannel (depth) vs generic continuer (advance) — chosen deliberately | "Into the *lake*?" / "…and then?" | Strong (Bavelas) |
| 6 | Confirmation claim | "So Denver came before the wedding, if I have it right?" | Strong mechanism (Scharff), honest variant |
| 7 | Demonstrated-knowledge summary as thread opener | "Here's what I hold about the Ghana years: … What's missing?" | Strong (Scharff) |
| 8 | Question-free receiving turn (chat-native silence) | Reflection only; no question | Moderate |
| 9 | Tentative negative-affect label | "It sounds like that was lonelier than anyone knew." | Strong mechanism (Lieberman) |
| 10 | Sensory/music/landmark cue | "What was playing in the car that summer?" | Strong (bump cueing) |
| 11 | Normalizer before a sensitive door | "A lot of people find that year goes blurry." | Practice-based |
| 12 | Autonomy handoff | "We can go anywhere — what part of that matters to you?" | Strong (ORBIT/MI; CI) |
| 13 | Voss mirror (rationed) | last 2–3 words, questioning tone | Moderate |
| 14 | Reactive disclosure / honest reciprocity | "That image is going to stay with me." | Moderate (Lee CHI 2020) |

Anti-moves: interrupt/redirect mid-arc (7.5s finding); question stacks; option-posing/suggestive questions; any pressure or evaluative move (ORBIT asymmetry); fake disclosure or feigned knowledge.

### (b) CI mechanics → life-story question phrasing
- Context reinstatement → scene-first grammar: "It's the winter of '89, you're in the Fremont apartment — take me into a normal evening there."
- Report everything → standing permission copy in UI + periodic in-chat renewal; welcome fragments.
- Varied retrieval → rotation of retellings: backwards, other-perspective ("how would your sister tell this one?"), revisits (retrieval practice enriches).
- Witness-compatible → follow the user's retrieval order within a session; the AI's agenda yields to the thread their memory is on.
- Transfer of control → the session's explicit contract: "you were there; I just keep the record."

### (c) The Scharff insight for a system that genuinely knows the corpus
Lifehug is the rare case where "we already know most of it" is TRUE. Open threads with accurate summaries; ask in confirm/correct form; let gaps be visible ("I have the wedding but nothing about the honeymoon — that's a blank page"). Lowers the felt cost of telling, raises perceived competence, harvests the correction reflex. And invert the concealment: celebrate new material explicitly — the speaker should feel the archive growing.

### (d) Daily chat vs. long conversation
- **Chat** (minutes): one cued invitation or sensory/landmark cue; honest small-frame ("quick one today"); specific backchannel + savoring on the answer; one confirmation claim max; bank the thread ("that's going in the Ghana chapter — there's clearly more there"). No stairway-skipping: even 4 turns open with receiving.
- **Conversation** (a sitting): full CI arc — rapport/autonomy opening → demonstrated-knowledge summary → scene-setting invitation → uninterrupted free narrative with continuers and question-free turns → cued-invitation depth passes in the user's order → confirmation claims + closed questions only in a final "for the record" sweep → savoring/capitalization close. Bump-targeting and varied-retrieval revisits live here.

### (e) Do-not-use list (fails the transparency test)
1. Feigning knowledge the system doesn't have. 2. Concealing that information is new (engineered underestimation). 3. Fabricated AI autobiography. 4. False urgency/time constraints. 5. Engineered-wrong labels/claims to provoke correction (tentative good-faith versions fine). 6. Flattery calibrated to extract. 7. Guilt/streak-pressure/"you haven't shared much" framing (also empirically counterproductive — ORBIT). 8. Suggestive/presupposing questions that implant content ("that must have been traumatic"). 9. Exploiting a disclosed vulnerability to steer toward topics the user deferred.

---

## Ranked elicitation principles

1. **Never spend a maximizing move** — one pressure/judgment/guilt turn suppresses yield; "no bad turns" outranks "more good turns" (ORBIT).
2. **Invitation grammar is the engine** — TED openers, cued invitations quoting the user's words, one question per turn; suggestive/option-posing banned (best-quantified finding in the field).
3. **Don't interrupt the arc** — no new topic or question stack while a thread is open (7.5-second finding, inverted).
4. **Reinstate context before asking for content** — scene, senses, internal state first (CI's most powerful mnemonic, deliverable as phrasing).
5. **Give report-everything permission, repeatedly** — works even as written copy (CI + SAI).
6. **Deploy demonstrated knowledge honestly** — open with what the record holds, ask confirm/correct, make gaps visible (Scharff run truthfully; Lifehug's unique structural advantage).
7. **Choose backchannel class on purpose** — specific deepens, generic advances (Bavelas, causal).
8. **Celebrate new material** — invert Scharff's concealment; the user should feel the archive grow.
9. **Cue by sense and era** — odor→childhood, music→involuntary vivid recall, ages 10–30 for volume, landmarks for completeness.
10. **Label the hard, savor the good** — tentative affect labels keep people inside painful stories; joy gets amplified, not named.
11. **Hand over control, out loud** — autonomy statements and following the user's retrieval order are yield techniques, not courtesies.
12. **Reciprocity without a fake self** — continuity-of-memory, honest reactive disclosure, normalizers; never a fabricated biography; protect the non-judgment advantage.

**Evidence-quality summary:** meta-analytic/strong — cognitive interview, information-gathering vs accusatorial, Scharff corpus, question-type effects, Bavelas co-narration, affect-labeling mechanism, bump cueing. Strong-observational — ORBIT. Moderate — silence, mirroring, chatbot reciprocity, retrieval practice. Practitioner-but-convergent — Voss, Dreeke, TED/PEACE doctrine.
