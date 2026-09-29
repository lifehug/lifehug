# ADR 0039: A re-key is not a change to a life

Date: 2026-09-29
Status: ratified (owner, 2026-09-29) — v375, `timeline-rules:26`

## Context

The owner's ruling, 2026-09-29:

> "A software re-key is not a change to my life; carry links over."

A timeline node id is a hash of its kind, the words its subject is keyed on
and a discriminator (`temporal_projection.derive_node_id`). Rule moves re-mint
those ids without anything in a life moving: v350's identity re-key
(`AN_IDENTITY_RE_KEY_IS_A_WAY_A_NODE_ID_MOVES`, a subject mention that newly
resolves to a roster ref), v345's landmark redraw, a participation stay's
re-discriminated start. Classifier freshness (`classifier_context`,
`docs/pr-specs/classifier-independent-context.md`, ADR 0035/0036) digested each
event's candidate set by node id, so every such move reported `context_changed`
for every story that could see the node. On Sep 27-28 the sweep spent about 800
model calls and 40M tokens re-reading stories; 56% of the rewrites changed no
status and no link, only node ids. The spec already said "machine manifest
rekeys ... cannot alter freshness"; node ids were the machine key it had not
reached.

The stored links had the mirror defect. A classifier link names a node id; the
projection publishes `node_aliases` for re-keyed ids and every other reader
follows them, but the fold's anchor lookup did not, so a link to a re-keyed node
stood as `anchor_unresolved` (33 such anchors in the owner's published
projection at `timeline-rules:25`). v373's `A_RE_KEYED_LINK_REMAPS_BY_IDENTITY`
could re-point such a link without a model, but only once the digest had
already queued the story for a refresh.

## Decision

1. **The digest names candidates by identity, in the filed id space**
   (`classifier_context.A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE`). A candidate the
   stored reading filed keeps its id. A candidate with a new id stands for a
   filed id that vanished when the projection's `node_aliases` walks to it, or,
   when no other candidate of the event shares its node kind, event kind and
   entities, when the vanished id recomputes from its identity (v373's proof).
   The pairing is one-to-one or nothing is renamed. Every other digested field
   is unchanged. With no vanished filed id the digest input is the v374 input
   byte for byte; `CONTEXT_SCHEMA_VERSION` stays 1.
2. **A link follows its node through a re-key at read time**
   (`temporal_timeline.A_LINK_FOLLOWS_ITS_NODE_THROUGH_A_RE_KEY`,
   `timeline-rules:26`): an anchor naming a node id the drawing no longer
   publishes follows this generation's own `node_aliases`.
3. **A link the drawing neither draws nor redirects is `link_orphaned`**: a new
   pending reason, a timeline-mode refresh ranked after `classifier_changed` and
   before `relationship_changed`/`context_changed`. v373's remap settles it by
   rule when it proves one target; otherwise the model reads it. A timeline
   refresh stamps the digest its re-filed reading will be judged by
   (`snapshot_metadata_after_timeline_refile`).
4. **Discriminator-only siblings are never paired by recomputation.** Two
   candidates of one kind about the same entities differ only by discriminator;
   a re-key that re-orders discriminators would make recomputation prove the
   other one. Freshness and v373's rule remap both refuse, so the story goes to
   the model.

Alternatives considered. A record-independent identity key (a hash of kind,
entities and discriminator) in place of `candidate_id`: measured on the owner's
vault, 705 of 849 candidates are minted on words, not refs, so their identity
key would differ from their node id and every digest would move once, the
whole-vault refresh the ruling exists to prevent. Bumping
`CONTEXT_SCHEMA_VERSION` has the same cost (`legacy_snapshot` everywhere).
Dropping `candidate_ids` from the digest would hide genuine candidate-set
changes, which the spec forbids.

## Consequences

- Binds: a rule move that only re-keys ids and publishes a redirect costs no
  model call and no refresh. Any future node-id minter change must publish its
  redirect in `node_aliases`; without one, stored links surface as
  `link_orphaned`.
- Binds: freshness still invalidates on every digested field (roster terms,
  entity refs, ambiguities, basis, conflict state, alternatives, reference keys,
  grounding identity, completeness, human decisions). `supported_bounds` has not
  been digested since 7f4d748 (2026-09-17, ADR 0036); v375 does not change that.
- Forecloses: treating a vanished link id as silently unresolved.
- Measured read-only on a scratch copy of the owner's vault (`origin/main`
  26a1fc713): pending was 321 under v374 (315 `context_changed`, 3
  `relationship_changed`, 3 `unclassified`) and is 321 under v375 (314
  `context_changed`, 1 `link_orphaned`, 3, 3). The rule renamed re-keyed
  candidates in 279 of those sources, but their stamps were already stale for
  other reasons: 269 have a different candidate set even after renaming (new
  moments admitted through a shared entity, candidates that left), and 45 with
  the same set differ in a digested field. So this release does not shrink that
  backlog; it stops the NEXT rule move that only re-keys from re-growing it.
- Delete-when: node ids stop depending on subject words (an id minted only from
  durable refs), at which point the filed-id naming is a no-op.

## How to tell if a bug traces back here

Symptom: after a rule move, a story is linked to the wrong stay or event, or a
story that should have refreshed did not. Check, in order: the classification's
events for `timeline_relation.remapped_from` (a v373 rule remap happened; the
`rule_settlements` notes say which rule), the refresh report for
`link_orphaned` rows (`classify-story --refresh-targets`), and whether the
projection's `node_aliases` redirects the stored id and to what. Then compare
the source's stored `classification_snapshot.context_digest` with
`build_context_snapshot(...)["context_digest"]`: equal means freshness judged
the change a pure re-key. If two candidates of one kind share entities and the
link moved between them, the defect is in a redirect (the fold's contract) or
in the sibling guard here. Cross-references: v373
(`timeline_settlement.A_RE_KEYED_LINK_REMAPS_BY_IDENTITY`), v375, the
2026-09-29 amendment in `docs/pr-specs/classifier-independent-context.md`.
