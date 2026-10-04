# ADR 0043: One person, one record

Date: 2026-10-04
Status: ratified (owner, 2026-10-04 — design decisions D3, D6, D7, D8, D9)

## Context

The owner, 2026-10-04: *"We have the idea of an entity and the idea of a
focus. Then we have a roster and then we have wiki pages. Fundamentally these
should all be similar or the same in concept. … Under Entity Recommendations or
Focus it says 'author's father', or 'Dottie' or 'Harvey'. Those are already
focuses, so it is not connecting these people."* (lifehug-platform
`docs/design/identity.md`, tracking lifehug-platform#987.)

One person had five representations — a Focus category, a roster row, a wiki
page, a recommendation's raw detector string and a claim's `subject_ref` — and
only the roster row carried aliases. The others did not point at it, and the
row itself could not hold the plain fact "this is a real person who has a
Focus", because of ONE overloaded field: `maps_to_focus` meant both "this
person has a Focus" and "this row was folded into row X", and
`identity_resolution.is_alias_row` read any value as a pointer. A row mapped to
its Focus vanished from the Timeline's identity index; a row left unmapped was
invisible to recommendation suppression (`_focus_covered_aliases`), so people
with Focuses and pages were recommended as new Focuses. The recommender
compared raw strings ("Author's father") by exact lowercase and never called
the owner-possessive reading the claim resolver already had. And names collide
in a real family: three generations share a first name, two children share a
role word, a state holds three cities, a grandmother shares a nickname with a
friend nobody has recorded.

## Decision

**A person is one record. Everything else is a view of it or a decision about
it.** The record is the roster row, keyed `person/<slug>`.

1. **The overload is split.** A row carries `focus` (the Focus that ATTENDS to
   it — the record stays a live person: offered, counted, bound) and
   `folded_into` (the survivor, when the row is a duplicate pointer — a fold is
   a pointer, never a deletion, ADR 0041). `is_alias_row` reads `folded_into`
   only; `page_eligible` requires both to be empty. A one-version converter
   (`roster_relations.convert_legacy_roster`, read on every load, persisted on
   the next write and by `entity-roster --convert-identity`) maps a
   `maps_to_focus` naming another row to `folded_into` and anything else to
   `focus`, drops the key, and is byte-stable on a second run — the
   `state/landmarks.json` converter precedent (amendment Q1). Pure readers
   handed raw rows apply the same split (`identity_resolution
   .split_legacy_pointers`). Each Focus attaches to the one record its slug,
   title or a resolved title names (`attach_focuses`), never to two.
2. **Resolution is typed and takes context.** `resolve_person(text, roster, *,
   context)` returns a `Resolution` — `resolved` (one ref), `ambiguous` (every
   candidate) or `unknown`. `ambiguous` is first-class: callers render it or
   ask, never pick. The ladder: a dwelling possessive is a place; a shared
   alias is held; `resolve_mention`'s exact/alias/owner-possessive/full-name/
   relationship-qualified/census rungs; the first name exactly one record
   answers to (ADR 0041 D4) under the v383 relationship guard; a bare relation
   word answered as a set. A collision is split by context only: a relationship
   word in the clause, a generation marker, a stated year against `born`, the
   Focus the text was filed under. `resolve_place` resolves by name or alias,
   or "City, State" by containment — never upward.
3. **Recommendations, approvals and normalization resolve first.** `recommend`
   skips a person who already has a Focus or page and labels a row with
   `resolved_ref`/`resolved_name` beside the raw string (D5);
   `approve_recommendation`/`focus_new` attach the Focus (`person_ref` on the
   Focus, `focus` on the record) and refuse a twin; `normalize` sets `focus` by
   slug OR by a name/alias equal to a Focus title.
4. **Relations are sets (D6).** `relationship` is the typed field with a
   cardinality (`identity_resolution.RELATION_WORD_CARDINALITY`, re-exported by
   `relation_words`): a spouse or a father is one, a son is a set. Rows named
   by a set-valued role word (Son, Daughter, Kids, Parents, Siblings, Friend,
   Neighbor) are retired into top-level `relation_queries` carrying their
   counts and whole former rows; a spelling of one that names somebody ("my son
   Otto") moves to that record; role-word aliases stay only on cardinality-one
   relations, and the ones moved off are recorded on the query.
5. **Colliding names always display with a disambiguator (D7).**
   `display_name(record, roster)` is the bare name when unique and
   `Name (relation[, b. YYYY])` when another live record shares the name or the
   first name; `record_view` carries the record's handle (`@slug`, and the
   owner's short `@handle`) as a separate field, never inline.
6. **Places nest (D8).** `--located-in` writes `located_in`; a place fold is
   refused unless both rows are true duplicates (same `place_kind`, neither
   containing a place, neither inside the other); a place page lists the
   places inside it, nested.
7. **Objects and themes fold (6d)** exactly as people do.
8. **An alias can be shared with somebody who has no record (D9, D3).** An
   alias decision (`alias_meta`) may say `exclusive: false, shared_with:
   "<free text>"`: a BARE mention of it is held as uncertain — in
   `resolve_person` and in the claim resolver alike — while the record's
   exclusive compounds keep resolving; nobody is minted for the other claimant.
   A handle (`handle: true`) is exclusive by construction: refused when any
   other record answers to it.
9. **One writer, every door.** `entity-verdict` gains `--fold-into`, `--focus`,
   `--retract-alias` (every type), `--share-alias/--with`, `--located-in`,
   `--handle`; `--maps-to` is accepted for one version and rewritten with a
   deprecation line. The `focus-merge` roster union and the monthly refresh's
   alias union decide every alias through `roster_relations.alias_decision`.

Considered and rejected: a new identity store beside the roster (two writers
for one fact — the recurring-defect doctrine's failure shape); resolving a
collision by picking the most-mentioned candidate (a wrong attribution is worse
than a question); minting a record for an unrecorded nickname claimant (the
owner's rule: a mention alone never makes a person, D3).

## Consequences

- Binds: no reader treats `focus` as a pointer; no writer writes
  `maps_to_focus`. A new person-reading surface prints `display_name`, and a
  caller of `resolve_person` treats `ambiguous` as an answer to render.
- Binds: hosts that read roster files directly (the platform's vendored
  readers) read `focus`/`folded_into` or call `split_legacy_pointers`; the pin
  that carries this version runs `entity-roster --convert-identity` once.
- Forecloses: folding a city into its state; a role-word row standing for a
  set; a bare shared nickname attributed to the one record that happens to
  carry it.
- Delete-when: after one version every vault has been converted — the legacy
  reading (`split_legacy_pointers`, the `--maps-to` rewrite, `focus_of`'s
  fallback) is deleted in the following release.

## Pages are views (v389)

The compiled page is the record's view, addressed by the record's slug. A Focus
whose person record has a different slug ("katie" on `katie-taylor`) is written
at the record's slug, its old path keeps a one-line redirect stub for one
version, and a stale stub is removed by the orphan rule — which never touches a
live record's page, while a folded record's mention page leaves it and every
link that named it follows the pointer to the survivor. The page's frontmatter
names the record (`person_ref` / `record_ref`, `handle`, `aliases`,
`relationship`, `answers`); the viewer's identity header, alias add/remove and
"this is that record" read and write that record through the one verdict verb,
never the page. Records with no page are listed as "Known, no page yet", not
given pages (D2). Delete-when: the stubs go one version after v389.

## Handles (v390)

`@katie` is the record, and it is typeable in any conversation (design §3.1,
§4.1.4b, promise P14).

1. **Every identity record has a handle** — its slug with an `@`
   (`@katie-taylor`, `@yucaipa`, `@orange-shorts`), for every type: person,
   place, object, theme, period. A record may ALSO carry ONE short,
   owner-chosen handle (`@katie`), stored as an alias flagged `handle: true` in
   `alias_meta` (v388). `record_view` returns both as separate fields
   (`handle`, `short_handle`); the viewer's identity header shows them beside
   the display name, which is unchanged.
2. **A handle is unique across the vault.** `entity-verdict <type> <slug> clear
   --handle h` accepts lowercase letters, digits and hyphens (64 at most;
   `@` and capitals are normalised away) and refuses — exit 2, the
   `identity_uncertain` shape, the claimant named, nothing written — when ANY
   other record of ANY type already holds the text as a slug, a name, an alias
   or a handle (`identity_handles.claimants`). It is never shared: a shared
   alias (D9) is for a name, a handle is the opposite. A new handle replaces
   the old (the old spelling stays an ordinary alias); `--clear-handle` unflags
   it and falls back to the slug handle — it never deletes a name the record
   answers to.
3. **The grammar is the package's** (`identity_resolution.parse_handles(text)
   -> [HandleSpan(span, raw, ref|None, reason)]`, `HANDLE_RE`): `@` + a slug
   token, word-bounded, never inside an email address, a URL or a host name;
   a trailing `.` or `'s` is not part of it. Resolution is by (a) an alias
   flagged `handle` on any record, then (b) a record slug — person first, then
   place, object, theme, period. A token naming records of two types is
   `ambiguous_handle` and says both; no token is ever resolved by a fuzzy rung,
   the first-token rule or a model. The viewer, the platform composer and
   Telegram all mean the same thing by `@katie` because there is one parser.
4. **Statements by handle file with no model judgement.**
   `identity_handles.handle_statements(text, rosters, subject=…)` reads three
   shapes: *this is @h* / *X is @h* → `--alias <name>` on the record `@h`
   names; *same as @h* → `--fold-into` when the subject is an existing object
   or theme record, else `--alias` (a person is only ever aliased); *@a is in
   @b* → `--located-in` (both must be places). Every statement carries
   `basis: "handle"`. An unknown handle is `unknown_handle`, a cross-type token
   `ambiguous`, a pointer with no subject `unknown_subject`, a role word ("my
   wife") or a period `unsupported` — each is reported and files nothing. A
   name another record already answers to is a collision (`ambiguous`), never a
   re-point; a name the record already holds is a `noop`; a shared FIRST name is
   never "already known". It never passes `--ensure` — a conversation does not
   mint a record. `listen_to_answer(…, entity_rosters=…, handle_subject=…)`
   attaches the resolved statements to its outcome (`handle_statements`)
   whatever the completion did, and a host files
   `general_listener.handle_statement_invocations` FIRST, then acknowledges
   (D4). The model-mediated `person_identity` path still accepts an `@handle`
   in `refers_to`; both resolve through the one grammar.
5. **Display.** The classifier's "People you already know" block and the
   listener's known-people list print each person as `Name @handle` (the short
   handle when set, else `@slug`); the prompts tell the model the name is
   written without it, and that an `@handle` in `refers_to` is copied exactly.

## Work items (v391)

A `person_identity` record that is not `resolved` is work for the person, not a
filing. `general_listener.identity_work_items(records, roster)` (CLI:
`lifehug.py identity-work-items`, listener JSON on stdin) mints one row per
mention: `ambiguous` becomes an `identity_uncertain` row naming every candidate
("Which James?"), `unknown_person` / `unknown_handle` becomes a `new_person` row
("New person?") quoting the basis. A `resolved` record mints nothing. The id is
`derive_work_item_id(kind, unresolved mention, "identity")` — the derivation
Mirror's own `identity_uncertain` rows use — so the listener, the host's
recording job and Mirror converge on one row. D3 holds: the `new_person` row
only NAMES the `entity-verdict person <slug> clear --ensure --name <name>` argv
(`owner_choice_argv`); a host runs it only on the owner's explicit choice, and
a conversation never mints a person. `entity-roster --convert-identity` is now
reachable through `lifehug.py`.
