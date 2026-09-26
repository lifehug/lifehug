---
title: The Spine — Age Frames & Anchors
parent: Handbook
nav_order: 13
---

# The Spine — Age Frames & Anchors

## 1. What it does & what it's for

Every Lifehug vault starts with a timeline before the person has told it
anything but a birthday. That starting frame is the **spine**: the thing every
moment is placed against. It begins generic and gets specific as the person
gives it **anchors**. In the owner's words (2026-09-19, ADR 0037): *"the loop is
a model resolving and calculating placement against a spine; the spine is a
generic lifetime timeline first, improved by the user's keystones and
landmarks."*

The page exists so onboarding, the template vault, and every surface that asks
a dating question share one picture of what a fresh repository starts with,
what it must learn first, and how it learns the rest.

## 2. The nouns

- **Spine**: age frames plus anchors, the whole frame placement is calculated
  against (`resolver.spine`, ADR 0037).
- **Age frames**: the default spine, derived from the birth date alone:
  Childhood `[0,13)`, Teen years `[13,20)`, then every reached decade: my 20s,
  my 30s, my 40s, my 50s… (`cross_dating.age_frames`, [Eras](eras.md)). With
  nothing but a birthday, a moment told with an age ("when I was 12") already
  lands, calculated against it.
- **Anchors** (owner-named product word, 2026-09-25; the code term since
  v197): everything the person gives that other dates hang off. Two kinds:
  - **Cornerstones**: the fixed dated POINTS, asked to the day: births,
    weddings, divorces, deaths ([glossary](glossary.md)).
  - **Landmarks**: the SPANS, asked to a month or coarser: homes, schools,
    work, and the mention-opened stretches such as a mission
    ([Landmarks](interactions/landmarks.md)).
- **Keystone**: not a kind of anchor. It's whichever missing anchor would place
  the most moments *right now*, recomputed from what is still unknown, with at
  most two starred ([Timeline](timeline.md)). A missing cornerstone or landmark
  *becomes* a keystone when filling it would unlock the most.
- **Whisper / keystone question**: the two ways a keystone is asked. A whisper
  rides inside a conversation where it fits: the Today page marks the
  conversation with an icon, labelled "A keystone is waiting in this
  conversation". A keystone question is the day's question. Neither nags.

## 3. How it works — the skeleton of a fresh vault

A new repository (the template Lifehug, or a hosted vault at onboarding) starts
with this skeleton:

| Layer | What it holds | At onboarding |
|---|---|---|
| **Birth date** | The one hard requirement. It creates the age frames. | **Required.** Without it nothing can be calculated. |
| **Age frames** | Childhood, Teen years, every reached decade. | Derived automatically, never asked. |
| **Required cornerstones** | The person's birth; each child's birth; parents', siblings' and spouse's births; each wedding and divorce; the deaths of parents, spouse, siblings, children and grandparents. | As many as the person will give; each is asked to the day. |
| **Required landmarks** | Birth, family, homes, schools, partnerships, children (onboarding domains in `interactions/landmarks/questions.yaml`), then work, military and losses. | Asked in *generalities* first ("where did you grow up?"), then refined up each domain's specificity ladder. |
| **Mention-opened anchors** | Missions and baptism today (`offered: on_mention`), and a child's wedding or divorce. | Never asked by default; a mention opens them. |

After onboarding, keystones and whispers fill the spine in over time. The
skeleton is the same for every person; how fast it fills depends on what they
say.

**Precision.** A month is enough for almost everything. Only cornerstones are
asked to the day, and a card never asks for finer than a month otherwise. The
precision the person uses when they say something is the precision it's placed
at. More precision is asked for only when it's hot, meaning it would move many
other placements.

**What the person sees.** The Timeline's two square buttons open the
Landmarks view (spans in lanes, with a cornerstone marker row to compare
against) and the Cornerstones view (the required set, plus Others for
discrete dates the person gave about anyone else).

## 4. The algorithm

The arithmetic is not new. It lives in the pages this one links:
cross-dating and band dating ([Timeline](timeline.md), ADR 0026), age frames
([Eras](eras.md)), the resolver against the spine (ADR 0037), keystone planning
(`timeline_gain`, ADR 0026), and cornerstone asking
(`temporal_work_items.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE`). This page is the
map, not a second definition.

## 5. In the loop

Onboarding asks for the birthday and the general landmarks. The daily loop's
whispers and keystone questions ask for the highest-leverage missing anchor.
Every filing republishes the timeline, so each anchor re-places everything
that leans on it the same day.

## 6. Where it lives

`resolver.spine`, `cross_dating.age_frames`, `cornerstones.CORNERSTONES`,
`interactions/landmarks/questions.yaml`, `timeline_gain`,
`timeline_views` (the two views). Onboarding work is tracked in the GitHub
issue that references this page.

## 7. Decisions

- 2026-09-19: the spine is a generic lifetime timeline first, improved by
  keystones and landmarks (ADR 0037).
- 2026-09-25: **cornerstones** named, the fixed day-precision points.
- 2026-09-25: **anchors** becomes the product word for cornerstones plus
  landmarks, keeping its code meaning. Spine = age frames + anchors.
