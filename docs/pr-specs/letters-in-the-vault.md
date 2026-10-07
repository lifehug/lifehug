# Letters in the vault: documents as evidence, on the right axis

Status: design, 2026-10-06, from four read-only research passes over the
vault (v324 code, timeline-rules:16 projection on disk), the framework
(v380), the platform, and the family-letters repo (533 transcripts at
`lifehug/letters` HEAD 970b053). Owner: Dave Taylor. Nothing built yet.

Companion: `intake-terminal-skill.md` (issue #469) is the front door this
design feeds; `~/Workspace/family-letters/review/vault-ingest-design.md` is
the earlier sketch this supersedes.

## What the owner asked for

1. Every letter in the vault, immutable, with the transcript and context the
   letters project already produced. Those are done; compile must not
   rewrite them.
2. On the timeline, a letter is a row that expands to read, like the letters
   site. Stories told inside a letter are moments beside it.
3. Letters ABOUT the owner during his life (great-grandparents on the
   "mischievous looking boy", 1984) are on his timeline. Letters about other
   people's lives (Mom's friend Kit, Dad's New Zealand areas) are not, but
   they feed who-people-are: Uncle Mark, Uncle Dane, Nan and Pop should rank
   high as entity recommendations and get pages, with birthdays.
4. Dad's New Zealand letters belong on Dad's page and timeline; Mom's on
   Mom's. Those pages should show a chronology the way the letters site does.
5. **Evidence is first class and heavily weighted when it corroborates.**
6. The scan → OCR → transcribe → review → answer-pass → row pipeline becomes
   Lifehug skills, so future scans work the same way. This is independent of
   the loop: a document page is made once, iterated until the owner is
   satisfied, then frozen unless something significant changes.

## Why it does not fit cleanly today (the research, compressed)

| Area | What exists | What blocks the ask |
|---|---|---|
| Source family | `sources/gmail/` and `sources/photos/` are `external_record` with `authority: third_party_record`; a new `sources/letters/` folder is read, linted, listed and compiled with **no code change** | No `letter` type; no author / recipient / written-date fields; `captured_at` would be the filing date; the compiler never branches on `authority`, so a record counts as primary evidence with no framing |
| Timeline, OSS | Nodes are `event | period | episode`; claims come from classifier events, landmarks, resolver; the `document` basis exists with the highest weight (7.0) and renders "printed on …" | **Nothing writes the `document` basis today.** No document or record row. `/views/timeline` still renders the legacy projection; the calculated one is attached but not drawn. A moment shows `source:` as plain text and cannot be read inline |
| Timeline, platform | Reads one file, `state/temporal_claims/calculated-timeline.json`; frames and eras expand, a moment opens an info dialog; person pages have a "dated moments" block (cap 8) keyed on `subject_refs` | No record node kind (the contract rejects unknown kinds); Gmail records appear nowhere; a build test blocks source bodies from every product page except `/chats` |
| Axis | timeline-rules:16 has four ordered rules: `owner/lived`, `none/pre_birth`, `none/subject_unresolved`, `family/immediate_family_in_lifetime`. Pre-birth goes "on the person's page, never on his axis" | "Someone else" is detected only by relation WORDS ("Mom", "Dave's mother"). A bare "Jim Taylor" falls to the owner. A letter's `from` never reaches the subject |
| Dating | The resolver reads a source's own date line ("a source's date is evidence too") but plans only owner-axis nodes; the classifier sees only `captured_at` | Present-tense lines in a 1974 letter cannot be dated from the letter's date; pre-birth nodes are never planned |
| Compiler | Person pages are Focus pages; witness accounts attach by `witness_slug`; `entity-verdict … graduate --born --died` exists (v217) | Synthesis takes the first 14 sources per page, answers first, so letters never reach Dad's or Mom's prose; roster eligibility counts only answered questions, so a relative in 50 letters stays ineligible; the Switzerland period attaches by the word "mission", which would also pull the New Zealand letters; `matching_sources` is a substring match ("Mom" matches "moment") |
| Per-person time | `cross_dating.age_frames` is pure arithmetic and could draw Dad's frames; parents' births are on disk | ADR 0030 rejects per-person frames; the platform person page's dated-moments block is the only per-person chronology |
| Letters data | 533 transcripts; 498 dated; ids stable; 206 inside the owner's life (198 of them the 2000-02 mission mail); 7 letters 1982-85 mention him as a child; `people.yaml` has 95 people with aliases but no dates (dates are prose in `people.md`) | No content hash; transcripts are still edited; `source_file` is not unique for split letters; Nan and Pop are one roster entry |

## Decisions this design proposes

### D1. A letter is a RECORD source: all of them, immutable, under `sources/letters/`

Every transcript is filed, not a selection. Records are small text and the
owner wants every letter visible. What stays SELECTIVE is what the loop
consumes (D6), which is the same split the Gmail connector already draws:
the ledger is permanent, relevance is recomputed.

```yaml
---
title: "Nan and Pop to Desi, Jim and the little sweethearts, 5 March 1984"
type: "letter"                      # new source type; a sub-kind of external_record
source_id: "letters:memory-box-1974/tippets-charles"
source_medium: "letter"
source_trust: "external_record"
authority: "third_party_record"     # first_person_record when from == owner
captured_at: "1984-03-05T00:00:00Z" # the DATE WRITTEN, never the filing date
written_date: "1984-03-05"          # EDTF; precision from the transcript
written_date_precision: "day"
written_date_evidence: "…"          # the transcript's own reasoning, verbatim
author_refs: ["person/nan-tippets", "person/pop-tippets"]
recipient_refs: ["person/mom", "person/dad"]
subject_refs: ["person/dave", "person/kristine", "person/jackie"]   # who it is ABOUT, from the transcript's people list
document_type: "letter"             # letter | card | note | newsletter | postcard | envelope_only | other
collection: "memory-box-1974"
origin:                             # the immutable reference tuple
  repo: "lifehug/letters"
  id: "memory-box-1974/tippets-charles"
  commit: "970b053d88d979dc7e322372fe5c1341d3b460ba"
  source_file: "TAYLOR FAMILY MEMORY BOX/TIPPETS CHARLES.pdf"
  source_pages: null
  scan_blob: "7d516bd417955a5cba20bf0b844510dd0a8e132b"
  scan_url: "https://taylor-family-letters.fly.dev/letters/memory-box-1974/tippets-charles/scan.pdf"
visibility: "owner_only"
sensitivity: "family"
status: "raw"
immutable: true
schema_version: 1
content_sha256: "…"
---
```

The body is the transcript as the letters project left it: the page-marked
text, `## Context`, `## Sources`, `## Uncertain readings`, `## Questions for
the family`. **The compiler never rewrites a record.** A later transcript
revision is a NEW record version (`supersedes: letters:<id>@<old commit>`),
the same additive rule the source contract applies to corrections.

Scans and page images are referenced by blob and URL, not copied. The vault
is a GitHub repo; 894 MB of PDFs do not belong in it. The platform asset
store is a later option.

The relation of the writer and recipient to the owner is carried as refs,
not relation words. That is what fixes the axis rule's blind spot (D3).

### D2. The letters pipeline becomes Lifehug skills, loop-adjacent by design

The family-letters pipeline is the reference implementation. It ports as a
`documents` package with one skill per stage, each script-first:

| Stage | Today (`family-letters/pipeline/`) | In Lifehug |
|---|---|---|
| Inventory + local OCR | `prepare.py` (render pages, Apple Vision, scanner text layer, typed/handwritten score) | `lifehug.py documents prepare <scan-dir>` — unchanged logic, writes to a documents workspace outside the vault |
| Transcribe on the subscription | `transcribe_cc.py` (headless `claude -p`, JSON schema, resumable, pause on limit) | `documents transcribe --all | --ids …` — same driver; the glossary it reads is the vault's entity roster plus `people.md` |
| Review | `review.py` (lowest confidence first, scan beside transcript) | `documents review` → `/views/documents/review` in the local viewer |
| Answer pass | `review/answer-pass/PLAN.md`, `answers.py` (letters issue #6) | `/answer-pass` skill: Sonnet explores, strong model decides, quotes verified, `Answered`/`Evidence` bullets; vault updates no longer go to the Desktop, they go through `intake --from-updates` (#469) |
| Split bundles, envelopes | `split.py` | `documents split --plan` |
| File into the vault | `build_site.py` rows | `documents file <id…>` → D1 records, manifest, commit, push |

Loop status: **Loop-adjacent.** None of this runs on the daily, weekly or
monthly rhythm. A document's record is made once; `documents refile <id>`
after a transcript revision writes a superseding version. Only `file` touches
the vault. What the LOOP does with a filed record is D6.

The letters SITE (chapters, month strips, people pages, the NZ guide) is not
ported as compiled wiki. Its two jobs land elsewhere: browsing rows become
the Sources and Timeline views (D4), and the long-form guides become Studio
pieces (D5).

### D3. Axis routing by refs: who it is about decides where it lands

The projection's four ordered rules stay. What changes is the INPUT: a
record's `author_refs`, `recipient_refs`, `subject_refs` and `written_date`
feed `subject_refs` on every claim the record produces, so the axis rule
never has to guess from wording.

| Letter | Routing | Result |
|---|---|---|
| 2000-02 mission mail to the owner (177 letters) | `recipient_refs` = owner; written inside his life | `owner/lived`, on his axis, inside the Switzerland Mission era by DATE (D6 fixes the keyword attachment) |
| Nan and Pop, 1984, about "little David" | `subject_refs` includes owner; written inside his life | `owner/lived` via `lived_effect`: a scene about him he lived |
| Dad's 1973-75 New Zealand letters (102) | author Dad; wholly before birth | `none/pre_birth`; `subject_refs` = Dad → Dad's page chronology, never the owner's axis |
| Letters to Mom 1973-75 about Kit, Royce, Ricks | subject Mom and friends; pre-birth | `none/pre_birth`; Mom's page; friends feed the roster only |
| Mom's 2001 letters mentioning her car crash | author Mom, recipient owner, inside his life | the LETTER is owner/lived; the crash moment is `family/immediate_family_in_lifetime` (timeline-rules:16 already does this) |

Two things the record carries that nothing carries today: the letter's own
date as the anchor for its present-tense lines ("we're on 18 days left" from
a letter dated 17 June 2002 is a `document`-basis date claim on the mission's
end), and the writer as the subject of first-person lines. The resolver
already prints "a source's date is evidence too"; this design lets the
classifier see `written_date` as well, and lets pre-birth nodes be dated
(they are planned for the person page, not the owner's axis).

### D4. A record is a node the timeline can open

The projection gains `event_kind: "record"` on an `event` node (no new
`NodeKind`, so the platform contract change is one enum value):

```json
{"node_id": "rec:letters:memory-box-1974/tippets-charles",
 "kind": "event", "event_kind": "record",
 "record": {"document_type": "letter", "author_refs": [...], "recipient_refs": [...],
            "title": "...", "source_id": "letters:…", "page_count": 2,
            "scan_url": "…", "excerpt": "first 300 chars"},
 "children": ["evt:…", "evt:…"],          # the moments this record's claims produced
 "corroborates": ["evt:…"],               # D7
 "date": {"best": "1984-03-05", "basis": "document", "confidence": "certain"},
 "subject_refs": [...], "axis_membership": "owner", "usable_placement": true}
```

Rendering, both mediums (parity rule, twin issues filed together):

- **OSS viewer:** `/views/timeline` cuts over to the calculated projection
  for record rows first (the cutover the code already calls "deliberate and
  later"). A record row shows writer → recipient, date, document type, an
  evidence chip (D7), and expands inline: left the transcript body read
  through the v120 source reader, right the scan link, below its child
  moments. Exactly the letters site's row, inside the vault.
- **Platform:** a `CompactRow` variant that uses `Disclosure` like frames
  and eras do; child moments as nested rows; the scan link out. Showing the
  transcript inline needs an **owner ruling** relaxing the source-body
  boundary test for `type: letter` (the 2026-08-12 reversal applied only to
  `/chats`), plus `source_body` widened to the letters path. Without that
  ruling the row still works: title, date, excerpt, children, and a link to
  the letters site.
- **Sources view:** letters listed under their own type with writer,
  recipient, written date and collection columns; the reader shows the
  letter fields it hides today.

### D5. Parents' chronologies: dated moments on the page, long form as pieces

Per-person age frames stay rejected (ADR 0030). Two surfaces do the job:

1. **The person page's dated section.** The platform already renders
   "dated moments" for a person from the same projection (cap 8, plain
   rows). This design adds the OSS twin (`render_page` gains a chronology
   section built from nodes whose `subject_refs` name the page's entity,
   sorted by date, records and moments interleaved) and raises the cap when
   the subject has records, with a "show all" that filters the timeline by
   subject. Dad's page then shows 1973 → 1975 by month from his own letters,
   like the letters site's activity strip.
2. **Long-form guides are Studio pieces.** The letters project's
   `guide.py` rebuilds "walk Jim's footsteps" from a standing brief. In the
   vault that is an artifact: `artifact new --format guide --subject dad
   --seed <brief>`, iterated with `artifact save --feedback`, marked final,
   promoted as an `authored_artifact` source. Made once, frozen, rebuilt
   only when the owner says a significant source arrived. This is the
   owner's "not open for change all the time" rule, and the Studio already
   has it.

### D6. What the loop consumes, and the compiler fixes that make it honest

Filing 533 records is cheap. Letting them all into synthesis is not, and
today it would not even work. In order of necessity:

1. **Date-aware attachment for periods and places.** A record attaches to a
   period when its `written_date` falls inside the period's span and its
   `subject_refs` or `recipient_refs` include the page's subject, before
   any keyword match. Ends "mission" pulling New Zealand onto Switzerland.
2. **Whole-word `matching_sources`.** "Mom" stops matching "moment".
3. **A records lane in synthesis.** The 14-item cap stays for answers; a
   second, capped lane (default 6) carries the highest-relevance records
   for the page, scored like the connector (date anchor, relationship
   signal, narrative density, novelty) plus **on-axis** and **landmark
   touch**. Prompt framing for `authority: third_party_record` and
   `first_person_record`: corroborating record, a younger voice, never the
   author's memory.
4. **Records count toward roster eligibility** as `unique_records`, with a
   lower weight than answers, and `author_refs`/`recipient_refs` count as
   mentions. Uncle Mark (51 mentions), Nan and Pop (45), Dane (6) then
   surface as entity recommendations with the owner's accelerator
   (`entity-verdict graduate --born --died`) unchanged. Split `nan-and-pop`
   into two people with their dates from `people.md` (Pop 1904-1985, Nan
   1914-2006) on the first filing.
5. **Candidates, not pages, for the memory-only questions.** The 28 open
   questions in `people.md` file as `letters-mined` candidates for the
   weekly planner. That is the one place the letters feed the daily loop.
6. **Classification in batches** through `classify-story --batch-plan`
   (ADR 0035), `--no-candidates` on the pre-birth records, and the cache
   re-keying accepted once.

### D7. Evidence is a first-class thing

Today evidence is half present: the `document` basis exists with the
highest weight, consilience adds +0.5 per independent corroborating source
(capped at 4), and the Gmail badge path runs on the legacy projection only.
This design makes it visible and makes corroboration count:

- **Producer.** Record claims carry `basis: document` with provenance
  `{source: "letters:<id>", claim: "<verbatim>", basis: "document"}`. This
  is the first producer of the `document` basis in the vault.
- **Corroboration on the node.** The fold stamps `corroborated_by: [record
  node ids]` and `corroboration_count` on any moment whose date a record
  claim independently agrees with, and `contradicted_by` when a record
  disagrees beyond the grain. Both mediums render a chip: "✉ 3 letters".
- **Weight.** A corroborated claim is not just +0.5 per source. Proposed:
  consilience from a `document`-basis source counts double (+1.0, cap
  unchanged at 4), so a remembered date agreed by two letters (6.0 + 2.0)
  outranks a lone document (7.0), and a document agreed by the memory (7.0
  + 1.0) outranks everything. The exact numbers are a `chronology` constant
  with a handbook parity annotation, so the owner can tune one dial.
- **Retire the legacy badge path** once record nodes carry corroboration;
  Gmail date evidence re-enters as record claims from `sources/gmail/`, the
  same way, so there is one evidence mechanism.

## What is deliberately NOT here

- No per-person age frames (ADR 0030).
- No compiled wiki page per letter. A letter is a record and a row, never a
  synthesized page.
- No new extractor or reading prompt. Record claims come from the existing
  classifier with two new fields in its context (`written_date`,
  `author_refs`).
- No copying of scans into the vault.
- No auto-graduation of relatives; eligibility rises, the owner's verdict
  still decides.

## Build order

| # | PR (framework unless noted) | Depends on |
|---|---|---|
| 1 | `letter` source type + fields; `documents file` writer; manifest/lint/reader show the fields; `sources/letters/` filed for all 533 from the letters repo at a pinned commit | nothing |
| 2 | `written_date` and `author_refs` into classifier context; `document`-basis claims with provenance; subject refs from the record's refs; pre-birth nodes datable for person pages | 1 |
| 3 | `event_kind: record` node with children; OSS `/views/timeline` record rows on the calculated projection, inline read via the v120 reader | 2 |
| 3p | Platform twin: contract enum, record `CompactRow` with `Disclosure`, link to scan; owner ruling on inline body (separate issue) | 3 |
| 4 | Compiler: date-aware attachment, whole-word matching, records lane, authority framing | 1 |
| 5 | Roster: `unique_records`, refs as mentions, Nan/Pop split with dates; `letters-mined` candidates | 1 |
| 6 | Evidence: `corroborated_by` / `contradicted_by` on nodes, chips in both mediums, consilience dial, legacy badge retirement | 2, 3 |
| 7 | Person page chronology section (OSS) + platform cap/filter; `guide` artifact format for Dad's New Zealand and Mom's Ricks years | 3, 4 |
| 8 | `documents` skills: prepare, transcribe, review, split, answer-pass, refile | 1 |

PR 1 alone gets every letter into the vault, readable in the Sources view,
with provenance pinned. Nothing after it rewrites a record.

## Owner rulings (2026-10-06)

1. **Inline transcript on the hosted timeline: yes, for `type: letter`.**
   The source-body boundary test is relaxed for letter records only;
   `source_body` and `_source_kind` widen to the letters path. Hosted and
   local rows behave the same.
2. **The owner's own letters are `authority: first_person_record`.** Their
   dates are contemporaneous statements and outrank recollection; prose
   treats them as a younger voice, never merged with memory.
3. **`sensitivity: family` on every letter record.**
4. **Document corroboration counts double:** +1.0 per agreeing
   `document`-basis source, cap unchanged at 4, one `chronology` constant
   with a handbook parity annotation.

Also settled: D1 changes nothing about how the family-letters repo works.
It stays the workshop (scan, transcribe, review, answer pass); the vault
holds a filed copy of each finished transcript, byte for byte, with the
vault frontmatter added on top.
