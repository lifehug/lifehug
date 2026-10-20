# ADR 0047: The owner is one record

Date: 2026-10-20
Status: accepted (design `docs/design/owner-identity.md` in lifehug-platform,
tracking lifehug-platform#1046; OSS twin #499; owner grant 2026-10-20).
Amends ADR 0043 (one person, one record).

## Context

The owner, 2026-10-20:

> "looks like the system doesn't connect that Dave and David James Taylor are
> both me. Do you see the same?"

He was right. The vault's profile says `name: "Dave"`, `full_name: "David
James Taylor"`, and the owner was then three things that never pointed at
each other:

- **a roster person** — row `dave`, aliases `David Taylor`, `David James
  Taylor` and the wrong `Dave's kids`, no `relationship`. The row is
  deliberate (the owner rostered himself so the photos connector and the
  identity bindings could recognise him), but a monthly refresh then made it
  page-eligible and the compiler wrote him a person page;
- **the life hub** — `wiki/life/<slug(full_name)>.md`, the primary Focus;
- **a profile** — which the Timeline fold, the cornerstones grid and the
  graph read through `temporal_publication.owner_identity_inputs`, so on the
  Timeline the row IS the owner.

Nothing on the roster or wiki side asked that definition. `entity_roster`
minted him from classifications ("David Taylor", "Dave", "Dave (narrator)");
`recommend_focuses` kept him out only because his person page existed; the
viewer offered him as a new person Focus; `roster_relations
.convert_legacy_roster` reattributed the placeholder alias "Dave's kids" onto
his row because the owner possessive resolves to the owner. The defect class
is "a seat spells the owner for itself" — the recurring-defect doctrine's
shape, so the fix is one definition, every seat rewired, a guard, and a
converter.

## Decision

**The owner is one record: the roster row that answers to the profile names,
marked `relationship: "self"`. Its page is the life hub. No seat treats that
record as a stranger, and no seat spells the owner for itself.**

1. **Keep the row; mark it (D1).** The owner's row stays — the bindings, the
   photos connector and the Timeline fold depend on it. It gains
   `relationship: "self"` (the word `cornerstones.SELF`,
   `landmark_edit.CATEGORY_RELATIONSHIP` and `OWNER_SUBJECT_REF` already use)
   and `focus: <primary Focus id>`: ADR 0043's `focus` is the Focus that
   attends to a record, and the life story attends to the owner (J2 — no new
   field, every "covered by a Focus" check works for free). `page_eligible`
   is false: his page is the hub, never `wiki/people/`.
2. **One definition (D2).** `system/owner_identity.py` holds the profile
   readers (`owner_profile`, `owner_names_from_profile`,
   `owner_name_variants`, `owner_identity_inputs`, moved from
   `temporal_publication`, which re-exports them unchanged) and the
   predicates every seat asks: `owner_row` / `find_owner_row` (the `self` row,
   else the one row `identity_resolution.owner_name_refs` finds — two is
   `ambiguous` and names nobody), `is_owner_row`, `owner_ref`,
   `is_owner_mention` (the owner-only words, a whole profile spelling, a
   2–4 word name whose first word is his given name and last his surname,
   and `<spelling> (narrator|author|self|me)` — J4), `is_owner_possessive`,
   `owner_slug`, `hub_page`. `focus_pages.author_names`, `roadmap`'s primary
   Focus label, `mirror`'s prompt name and `temporal_timeline._names_the_owner`
   read through it; a guard test refuses an inline `profile["name"]` /
   `["full_name"]` read in the known readers.
3. **The roster never makes a stranger of the owner (D3).**
   `entity_roster.normalize` (both the model and the deterministic path)
   merges every owner mention into the one self row — minting it, named the
   profile `name`, when there is none; the roster prompt says who the author
   is; `first_name_aliases` skips the self row; `apply_previous_decisions`
   keeps `self` whatever a refresh says. `convert_legacy_roster` never moves
   a possessive onto its own possessor ("Dave's kids" stays on the `kids`
   relation query). `entity_verdict` refuses, on the self row, a
   relationship, a person Focus, graduate, never, retire and folding it into
   another row — one reason, `ENTITY_IS_OWNER` (`EntityIsOwner`); folding
   another row INTO the owner stays allowed. `roadmap.focus_new` and
   `entity_verdict.attach_focus` refuse a person Focus for the owner
   (`THE_OWNER_IS_NOT_A_PERSON_FOCUS`). `recommend_focuses` treats the owner
   as covered by the primary Focus, page or no page. The classifier's known-
   people block lists him as `- Dave (you, the author) — also: …`, and
   `classifier_context._resolved_subject_refs` asks `is_owner_mention`
   BEFORE the roster, so an owner subject is `self`, never `person/<owner>`.
4. **The owner's page is the hub (D4)** — the compiler side (a redirect stub
   at `wiki/people/<owner>.md`, links repointed, the hub carrying the
   record's handle and aliases) lands in v427.
5. **One node, one row, "You" (D5)** — the viewer and graph side, v427 and
   the hosted twin.
6. **Migration is a converter step plus one verb (D6).**
   `convert_legacy_roster` gains the owner step (run on every load with the
   owner context, persisted on the next write and by `entity-roster
   --convert-identity`, byte-stable on a second run): mark the found row
   `self`, set its `focus` to the primary Focus (left alone without a
   roadmap), clear `page_eligible`, and move owner-possessive aliases back to
   their relation query. `lifehug.py owner-identity [--apply] [--json]`
   reports and applies it on demand.

Decided by the design: relationship page slugs stay `<name>-and-<person>`
(J1); the self row reuses `focus` (J2); the old person page stays one version
as a redirect stub (J3); "Dave (narrator)" is an owner mention (J4).

## Consequences

- Binds: a seat that needs the owner asks `owner_identity`; reading the
  profile names inline is a guard-test failure. A host that reads roster rows
  directly treats `relationship == "self"` as the owner.
- Binds: a refusal on the owner's row is `ENTITY_IS_OWNER` (the platform
  answers 409); a person Focus for him is `THE_OWNER_IS_NOT_A_PERSON_FOCUS`.
- (Closed by v427.) Until v427 lands, a compile after this version drops
  `wiki/people/<owner>.md` (its row is no longer page-eligible) without the
  stub; ship v426 and v427 together.
- Forecloses: a second row for the owner; a person Focus, a recommendation or
  a person page for him; an owner possessive as one of his aliases.

## Amendment 2026-10-20 — v427 (D4, D5)

- **The stub rule.** The compile never plans a person page for the `self` row.
  A page at one of the owner's person-page slugs
  (`owner_identity.owner_page_slugs`: the row's slug and the profile `name`'s
  slug), when one exists and is a mention, Focus or redirect page, is rewritten
  every compile as a v389-shaped redirect stub, `redirect_to: life/<hub>`
  (`owner_identity.hub_target`), `person_ref` naming the record, and is never
  removed as an orphan. A hand-authored page there is kept and reported; with
  no hub yet the page is kept untouched. No stub is written where no page was.
- **The hub carries the record.** It is written with the record's identity
  frontmatter (`person_ref`, `handle`, `aliases`, `relationship: "self"`) —
  the v389 keys, which every host already reads, rather than a new `record`
  key.
- **One spelling set.** `owner_identity.owner_spellings` (the profile
  spellings, the hub slug, the row's name, slug and every alias that is not a
  possessive) is what the graph's resolver, the relationship ends and the
  viewer's wikilink index send to the hub. Wikilinks in compiled prose whose
  target is an owner page slug are rewritten to the hub's title.
- **No owner kind.** The graph's `owner` node kind, its weight and its
  `exclude_kinds` entry are gone; a redirect stub is never a node and its
  edges land on its target.
