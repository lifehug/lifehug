# ADR 0020: candidate research becomes exact user-grounded source

Date: 2026-08-18
Status: proposed

## Context

Issue #172 adds conversational research for pending Focus and entity
candidates. Those conversations need to improve a later compiled page, but a
model-authored dossier is not evidence: it can paraphrase, merge speakers,
change a detail, or outlive the exact candidate identity it described.
Likewise, completing research cannot silently approve a Focus or graduate an
entity; those are separate lifecycle decisions with their own automatic and
owner-directed authorities.

Question Candidate v181 established exact candidate/placement revisions and a
model-without-write-authority boundary. Candidate promotion PR #173/v182
establishes the one writer lease and Git-backed receipt/adoption boundary. The
research source must use both shapes without adding a second writer or trusting
a projected candidate/manifest record after a crash.

## Decision

Add one generic candidate-research source authority shared by future
`focus_candidate` and `entity_candidate` Interactions. Evidence consists only
of exact revision-bound slices of authoritative raw user turns. Assistant
turns, model summaries, classifier output, recommendation snippets, and
generated seed questions are structurally excluded. A deterministic readiness
assessment maps those spans onto a closed dimension roster and recomputes each
kind/type's minimum; a model may propose the mapping but cannot assert ready.

Readiness is not completion. Completion additionally requires an explicit user
confirmation span bound to the exact ready assessment revision. The resulting
research revision deterministically binds the subject identity/state,
evidence, coverage, generated non-evidence questions, and confirmation.
Confirmation cannot overlap a substantive evidence span: attesting to the
assessment is a distinct user act, not a relabeled excerpt.

Completion renders one immutable `type: candidate_research` Markdown source at
a safe identity-digest path. It carries a closed base64 marker and typed source
metadata/manifest fields. The body contains literal user excerpts and a
visibly separate generated-question section; it contains no generated
summary. A marker-bound body digest and source revision bind those exact
sections to the research revision; a rewritten frontmatter content hash alone
cannot bless changed prose. Candidate sources decode as strict UTF-8 and use
strict scalar types. One candidate identity has one source path. Exact-byte replay adopts;
different bytes, revisions, or paths conflict. A pre-completion candidate
tombstone blocks the write; a later candidate deletion never deletes completed
source truth, which remains subject to the normal additive correction and
retraction contract.

The source informs downstream compilation but never changes candidate
lifecycle. After an independently approved Focus exists, matching Focus
research is primary citable material and prevents an empty placeholder. After
an independently page-eligible entity exists, matching entity research is
citable material for person, place, period, object, and theme. Research itself
never enters generic keyword routing; a static theme needs an independently
eligible roster row before its research attaches. Research never approves,
maps, qualifies, sets an owner verdict, or graduates anything.

The live mutation delegates to the canonical v182 writer/Git authority in
`system/exact_file_git.py`. The research module does not acquire a writer
lease or run Git. v183 extends that single public authority with optional
declared targets and closed-subtree discovery; promotion retains the ordinary
callback path. Missing targets may create safe parents only inside the same
bounded exact-file transaction. Candidate identity discovery occurs after
pull and under the same lease, strict-decodes raw subtree bytes, and never
treats the manifest as authority.

Adoption derives from the immutable source marker and canonical Git tree/first
introducing commit, never a projection. A validated missing or stale manifest
may be repaired on adoption while the receipt remains `changed:false` and
keeps the source-introducing commit. The source resolver requires a
fresh-subject loader, and the adapter invokes its revalidation callback in the
post-pull decision and every fresh validation, including after rebase.

## Consequences

- Future Focus Candidate and Entity Candidate packages share one evidence,
  readiness, confirmation, source, manifest, compiler, and receipt contract;
  prompt packages cannot invent their own durable research shape.
- A useful page can be produced immediately after later approval/graduation
  without promoting generated prose into source truth.
- Candidate identity/lifecycle churn fails closed before completion, while
  completed source survives ordinary candidate cleanup.
- Seed questions can guide later asking but can never be cited as something the
  author said.
- The framework gains no second writer, receipt ledger, or projection-based
  recovery path. Git remains the crash-adoption authority.
- v183 follows merged v182 (`639f2d2555d80e80fc41b85d313077f4a2113060`)
  in the release train and uses its shared live adapter rather than creating a
  second authority.

🤖 Generated with Codex
