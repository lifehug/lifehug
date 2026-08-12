# Contract: conversation session store + builders (issue #115)

Conversation Interaction build, Wave 1, PR 2 of 2. Owner-approved design
2026-08-11 (the design's §11 Wave 1 item 2). Depends on PR 1 (issue #114,
the `interactions/` scaffold) being merged or rebased under this branch —
the builders read `interactions/conversation/interaction.yaml` and
`evals/lints.yaml` from that PR. This contract is self-contained: all
schemas, registration mechanics, and conventions are stated here.

## Why

The vault has no stored conversation object anywhere — no thread files, no
turn transcripts. Before any conversation engine can exist (Wave 2), the
durable session document, its vault-contract registration, and the pure
prompt/context builders must exist and be tested. This PR is
**infrastructure only: no behavior change to any live flow** — `ask.py`,
`process_answer.py`, `answer_ack*.py`, `ingest_story.py`, delivery, and
the viewer behave byte-identically after this PR. Everything here is
reachable only via the new `conversation-*` subcommands and imports.

## Binding facts

- Repo version at `origin/main` is **149**; PR 1 (issue #114) is expected
  to land as 150, making this PR **version 151**. Re-read
  `system/version.json` at rebase time and take the next integer.
- CI: `python3 -m unittest discover -s tests -p "test_*.py"` on py3.11 +
  py3.14, **no pip install** (stdlib only — no PyYAML, no pytest
  dependency; tests are unittest-style, which pytest also runs),
  `scripts/ci/check_framework_files.py`, `scripts/ci/check_version_bump.py`.
- **Vault-contract machinery** (all verified against the current code —
  do not re-derive):
  - `system/vault_contract.json`: `data_paths` entries have shape
    `{"path", "kind": "file"|"directory", "required", "tracked",
    "schema": {"format", "version_field", "supported"}}` (plus optional
    `embedded_path`). `framework_paths` maps name → repo-relative path.
  - `system/vault_paths.py` loads it at import: `_load_contract()`
    validates entries; `_normalized_contract()` produces the exported
    form (adds `external_path`, sorts, classifies) — and **hardcodes the
    directory-kind framework paths as the set `{"system", "templates",
    "connectors"}`** (in the `framework_paths` normalization dict
    comprehension). Adding the `interactions` framework path requires
    adding `"interactions"` to that set, or its exported kind will be
    `file`.
  - **Digest interlock**: import FAILS (`RuntimeError: Lifehug vault
    contract identity digest does not match its content`) unless
    `identity.content_digest` in the raw file equals
    `_contract_digest(normalized_contract)` — the sha256 of the
    NORMALIZED export, canonical JSON, with `content_digest` popped.
    Because the check runs at module import, you cannot import
    `vault_paths` to compute the new digest. Working recipe (any
    equivalent is fine; the proof is that `import vault_paths` succeeds):
    extract the two pure functions and run them over the edited raw file —

    ```bash
    python3 - <<'PY'
    import ast, json, types
    src = open('system/vault_paths.py').read()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
            or (isinstance(n, ast.FunctionDef) and n.name in
                ('_contract_digest', '_normalized_contract'))]
    mod = types.ModuleType('vp')
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'vp', 'exec'),
         mod.__dict__)
    raw = json.load(open('system/vault_contract.json'))
    print(mod._contract_digest(mod._normalized_contract(raw)))
    PY
    ```

    Run this AFTER making the `vault_paths.py` code change (the
    `interactions` directory-set addition changes the normalized form and
    therefore the digest). Paste the printed digest into
    `identity.content_digest`.
  - `identity` currently reads `{"framework": "lifehug/lifehug",
    "framework_version": 120, "revision": "vault-contract-v1", ...}` —
    this PR is the first contract change since v120. Set
    `framework_version` to this PR's landing version and `revision` to
    `"vault-contract-v2"`. `contract_version` stays `1` (the FORMAT is
    unchanged; only entries were added).
  - **Test parity interlocks** in `tests/test_v120_vault_only.py` (all
    must be updated):
    - `EXPECTED_DATA_PATHS` (line ~37): a set of every data-path name —
      add `"arc_cards"`, `"conversations"`, `"mirror_responses"`.
    - `test_versioned_contract_is_the_exported_path_and_schema_authority`
      asserts `exported["identity"]["framework_version"] == 120` — update
      to the landing version.
    - The same test asserts (line ~238) that
      `set(re.findall(r'_data\("([^"]+)"\)', lifehug_core.py source)) ==
      EXPECTED_DATA_PATHS` — so `system/lifehug_core.py` MUST gain exactly
      one `_data("<name>")` accessor per new entry (see Deliverable 1).
  - `tracked_vault_paths()` derives git-housekeeping roots from entries
    with `"tracked": true` — the new entries below are tracked, so they
    join canonical git housekeeping automatically; no other wiring.
- **Builder convention** (the pattern to copy, verified):
  `system/answer_ack.py` — module docstring documents a stdin JSON object;
  `REQUIRED_FIELDS = {name: type}` dict; `build_prompt(payload) -> str`
  pure function; `main()` reads stdin, validates presence + type, prints
  the prompt to stdout, one-line error to stderr + exit 1 on empty stdin /
  invalid JSON / missing or mis-typed field. CLI wiring:
  `system/lifehug.py` `cmd_answer_ack_prompt` → `run_python(
  "answer_ack.py", [])` + `sub.add_parser("answer-ack-prompt", help=...)`
  (parser table ~line 1754; also add new names to the sorted command list
  at ~line 64).
- **Existing seams referenced (read-only this PR)**:
  `system/process_answer.py:88 next_followup_id()` (the `A14 → A14b`
  suffix chain — session filing reuses it in Wave 2);
  `system/timeline.py:581 compute_gaps()` (arc planner consumer, Wave 2);
  `lifehug_core.load_mission()` (mission block, if included in assembly).
- **PR 1 artifacts consumed** (paths fixed by the #114 contract):
  `interactions/conversation/interaction.yaml` — FLAT scalar YAML (dotted
  keys: `knob.*`, `budget.*`, `role.*`, `load_order`, `version`), parsed
  with `lifehug_core._parse_simple_yaml` (returns `dict[str, str]`; cast
  numerics yourself); `interactions/conversation/evals/lints.yaml` — flat
  scalar, `lint.<id>: on`, `banned.N: <phrase>`, `cap.turn_chars: 900`;
  `interactions/conversation/context/manifest.md` — documents the
  assembly order implemented here.
- Synthetic data only in tests/fixtures. NEVER reference
  `~/Workspace/dave` in test code (review rejection by itself).

## Scope

**In**: vault-contract + vault_paths + lifehug_core registrations; session
document store (`state/conversations/`); arc-card and mirror-responses
path registration + minimal typed read/write helpers;
`system/conversation.py` (pure CRUD + assembly + prompt builders);
`system/conversation_lints.py` (deterministic lint engine);
`lifehug.py conversation-*` subcommands; tests; version bump.

**Out** (explicitly): ANY model call or Telegram send (no
`conversation_delivery.py` — Wave 2 item 3); no `process_answer.py` /
`ingest_story.py` rewiring (Wave 2 items 3–4); no arc PLANNER (Wave 2
item 5 — this PR only registers `state/arc_cards.json` and reads cards);
no mirror inbound consumer (Wave 2 item 6 — registration only); no jobs.py
command kind; no viewer changes (so no walkthrough); no engagement
signals; no config keys (`conversation_model` etc. — Wave 2).

## Deliverables

### 1. Vault-contract registrations

`system/vault_contract.json` `data_paths` gains three entries:

```json
"arc_cards": {
  "path": "state/arc_cards.json",
  "kind": "file",
  "required": false,
  "tracked": true,
  "schema": {"format": "json", "version_field": "version", "supported": [1]}
},
"conversations": {
  "path": "state/conversations",
  "kind": "directory",
  "required": false,
  "tracked": true,
  "schema": {"format": "json_family", "version_field": "session_version", "supported": [1]}
},
"mirror_responses": {
  "path": "state/mirror_responses.json",
  "kind": "file",
  "required": false,
  "tracked": true,
  "schema": {"format": "json", "version_field": "version", "supported": [1]}
}
```

(`json_family` follows the `task_family`/`job_family` naming precedent for
directories of homogeneous records; schema formats are only strictly
validated for `required` entries, so this is descriptive, but keep the
precedent.) `framework_paths` gains `"interactions": "interactions"`, and
`vault_paths._normalized_contract`'s directory-kind set gains
`"interactions"`. Update `identity` (framework_version, revision
`vault-contract-v2`, recomputed `content_digest` — recipe in Binding
facts).

`system/lifehug_core.py` gains, next to the existing block at ~line 147:

```python
ARC_CARDS_FILE = _data("arc_cards")
CONVERSATIONS_DIR = _data("conversations")
MIRROR_RESPONSES_FILE = _data("mirror_responses")
```

(Exactly one `_data("...")` literal per name — the regex parity test
counts them.)

Update `tests/test_v120_vault_only.py` per the Binding-facts interlocks.

### 2. The session document (`state/conversations/<session_id>.json`)

Exact schema (design §5, ratified; `session_version` added here as the
durable-record version field, following `state/jobs`' `record_version`
precedent):

```json
{
  "session_version": 1,
  "session_id": "…",
  "mode": "chat|conversation",
  "channel": "telegram|web|cli",
  "interaction_version": "1.0.0",
  "status": "open|idle|closed",
  "arc": {"question_id": "A14b", "opening": "…",
           "intents": ["scene_sensory", "who_else", "meaning"]},
  "turns": [
    {"role": "user|lifehug", "text": "…", "ts": "…",
     "channel": "telegram|web|cli",
     "router": {"intent": "…", "confidence": 0.94},
     "model": "provider/model", "question_id": "A14b?"}
  ],
  "rolling_summary": "…",
  "extracted": {"facts": [], "entities": [], "candidate_ideas": [],
                 "mirror_responses": []},
  "close": {"reason": "done|idle_timeout|exit_taken", "takeaway": "…",
             "takeaway_delivered": true, "insight_receipts_count": 0,
             "filed": ["A14b", "A14ba"]}
}
```

Semantics the store must honor (all ratified):

- `session_id`: opaque, unique, filesystem-safe; pin the format
  `conv-YYYYMMDD-HHMMSS-<6 hex>` (UTC) so filenames sort chronologically.
- Session-level `channel` = opening channel only; **each turn carries its
  own channel** (a session can span Telegram + web).
- `arc.question_id` keys the card; a chat session **opens at first
  answer, not at delivery** — the arc card waits with the delivered
  question and answer latency never burns the idle clock. A conversation
  session opens at first inbound. (The store exposes open-with-arc; the
  policy callers land in Wave 2.)
- `router`, `model` per turn are optional (builders here never call
  models; Wave 2 fills them).
- `close` is absent until closed. `turns` may be empty on a just-opened
  conversation session.
- `extracted` consumers are Wave-2 wiring but the fields exist now:
  `facts` → re-asserted into the rolling summary each turn (the
  39%-degradation mitigation; in-session only); `entities` →
  classification hints; `candidate_ideas` → candidate store (provenance
  `conversation`); `mirror_responses` → mirror inbound path.
- **Single-flight turn mint via compare-and-set**: appending a turn takes
  an expected turn count (or expected last-turn id); on mismatch the
  append fails cleanly (typed error / False) — so concurrent answers on
  two surfaces mint exactly one turn. Same idiom as the existing
  `mint_follow_up` CAS on the platform; here it is enforced by
  re-reading the document and comparing before an atomic
  write-temp-then-rename within `state/conversations/`.
- Writes are atomic (temp file + `os.replace`) and go through
  `vault_paths` containment (`lifehug_core.CONVERSATIONS_DIR`); the store
  never touches git (commit/batching policy is Wave 2's
  `conversation-close` job).

### 3. `system/conversation.py` — pure builders (no model calls, no sends)

Follow the `answer_ack.py` build/deliver split: this module is the "build"
half only. Public surface (exact names; signatures may take
keyword-only extras):

**Session store CRUD** —
- `open_session(mode, channel, *, arc=None, vault_root=None) -> dict`
  (creates + persists the document, returns it)
- `load_session(session_id, *, vault_root=None) -> dict`
- `list_sessions(*, status=None, vault_root=None) -> list[dict]`
  (metadata-only summaries: id, mode, status, channel, turn count,
  opened/last ts)
- `append_turn(session_id, turn, *, expected_turns, vault_root=None)
  -> dict` (the CAS append; raises/returns typed failure on count
  mismatch or closed session)
- `close_session(session_id, close, *, vault_root=None) -> dict`
  (validates `close.reason` vocabulary; idempotent — closing a closed
  session with identical payload is a no-op, with different payload a
  typed error)

**Manifest + assembly** —
- `load_interaction_manifest(*, framework_root=None) -> dict` — parses
  `interactions/conversation/interaction.yaml` via
  `lifehug_core._parse_simple_yaml`, casts `knob.*`/`budget.*` ints,
  returns typed dict; resolves the file through the `interactions`
  framework path registered in Deliverable 1.
- `assemble_context(session, *, vault_root=None, blocks=None) -> str` —
  deterministic, in the manifest order: identity → behavior → examples →
  profile → record → session → turn_instructions. Stable blocks are the
  PR-1 prompt files read from `interactions/conversation/prompt/`. The
  `profile` and `record` blocks: when `blocks` (a dict of pre-fetched
  block texts) is provided — the platform path — use it verbatim; when
  not, assemble minimally from the vault deterministically (profile from
  `profile.yaml`/roadmap focus names; record = the arc's
  `question_id`-linked answer file if present, with provenance-ID
  prefix `[<id>, <answered_date>]`). Truncate each block to its
  `budget.*` (approximate: 4 chars/token). Honest freedom: RICH record
  retrieval (topic-relevance ranking, timeline spans, entity lineups) is
  Wave-2 scope — this PR pins the order, the budgets, the provenance-ID
  format, and the seam (`blocks` injection), not the retrieval quality.
  A parity test must assert the implemented order equals the
  `load_order` key in interaction.yaml (doc-drift guard).

**Prompt builders** (each pure; each has a stdin-JSON CLI path exactly
like `answer_ack.py`: documented `REQUIRED_FIELDS`, validation, prompt to
stdout, one-line stderr + exit 1 on bad input) —
- `build_turn_prompt(payload) -> str` — payload: `session` (the
  document), optional `blocks`; output = assembled context +
  `turn-instructions.md` with its `{placeholder}` slots filled (mode,
  current arc intent, turn position: opening / mid-arc / exit-friendly /
  closing-candidate, length cap from lints config).
- `build_router_prompt(payload) -> str` — payload: `message` (str),
  `session_open` (bool), `pending_question_id` (str|null); output =
  `router/router.md` with the message and state substituted. The five
  intents `{answer, new_story, command, continue_session, out_of_scope}`
  and the JSON output schema come from router.md — this builder never
  restates them (single source).
- `build_arc_prompt(payload) -> str` — payload: `question` (id, text,
  category, focus), `record_summary` (str), `gap_inputs` (list of
  strings, pre-computed — e.g. timeline-gap/scene-slot descriptions);
  output = a planning prompt per `plan/arc-templates.md` asking for one
  arc card (opening framing obeying the two-sentence rule + 2–4 intents).
  The WEEKLY caller lands in Wave 2 item 5; this PR only builds the
  prompt.
- `build_closing_prompt(payload) -> str` — payload: `session`; output =
  a prompt for the closing takeaway per behavior rule 8 (takeaway not
  recap + specific appreciation + continuity line + optional
  deposit-frame per `knob.deposit_framing` + named hook, then stop).

**Arc-card + mirror-responses helpers** (minimal, typed) —
- `load_arc_card(question_id, *, vault_root=None) -> dict | None` and
  `save_arc_card(card, *, vault_root=None)` against
  `state/arc_cards.json` shape
  `{"version": 1, "cards": {"<question_id>": {"question_id", "opening",
  "intents", "planned_at", "expires_at", "mode"}}}` (atomic write).
- `append_mirror_response(entry, *, vault_root=None)` against
  `state/mirror_responses.json` `{"version": 1, "responses": [...]}` —
  storage only; `mirror.load_mirror_entries()` integration is Wave 2
  item 6.

### 4. `system/conversation_lints.py` — the deterministic lint engine

One authoritative module (recurring-defect doctrine: the checks will run
in CI evals AND at runtime in Wave 2 — never inline copies). Public
surface:

- `load_lints_config(*, framework_root=None) -> dict` — reads
  `interactions/conversation/evals/lints.yaml` (flat subset). The yaml is
  the config authority (banned phrases, caps, on/off); the module is the
  engine.
- `lint_turn(text, *, is_reply_to_substantive=False, config=None) ->
  list[dict]` — findings `{"lint": "<id>", "detail": "…",
  "span": [start, end]}`. Implemented lint ids (exactly these, matching
  lints.yaml and behavior.md rule numbers):
  - `one_question_per_turn` (rule 1): >1 `?`-terminated question →
    finding. (Count question sentences, not raw `?` — handle quoted
    questions the user asked being echoed inside receipts pragmatically;
    document the heuristic in the module docstring.)
  - `banned_phrases` (rules 4/5/12 + do-not-use list): case-insensitive
    phrase list from lints.yaml (`banned.N` entries include at minimum:
    "that must have been", "you haven't told me", "streak", "as an AI",
    "I'm just an AI", "you should" as advice lead-in).
  - `question_grammar_audit` (rule 3): classify each question as
    `ted` (tell/describe/explain/walk-me-through openers), `cued`
    (contains a quoted user phrase), `closed` (aux-verb-first yes/no),
    `option_posing` (contains " or " between alternatives in the
    question), `other`; findings flag `closed` and `option_posing`.
  - `length_caps`: `cap.turn_chars` from config.
  - `receipt_before_question` (rule 2, structural): when
    `is_reply_to_substantive`, the text must not open with a question —
    at least one non-question sentence precedes the first question.
  - `year_question_detector` (rule 3): flags "what year", "which year",
    "in what year" question forms.
- `lint_transcript(turns, *, config=None) -> list[dict]` — maps
  `lint_turn` over lifehug-role turns with the substantive-reply flag
  derived from the preceding user turn (non-trivial length).

Lints are heuristic by design — the contract pins the ids, the config
source, and the obvious positive/negative cases in the test plan; exact
regexes are implementer freedom. False-negative-lenient, false-positive-
strict (a lint that flags good turns will be muted in Wave 2 — bias
against that).

### 5. `lifehug.py` subcommands

Add to the sorted command list (~line 64) and parser table, wired via
`run_python("conversation.py", ...)` / `run_python("conversation_lints.py",
...)` like the answer-ack trio:

- `conversation-open` (`--mode chat|conversation`, `--channel`,
  `--question-id` optional → attaches the arc card if one exists) —
  prints the created session id + document path
- `conversation-status` (`[session_id]`) — metadata-only list/detail
  (never prints turn text without an explicit `--full` flag; turn text is
  private content, keep the default output metadata-only like
  `answer-ack-status`)
- `conversation-record-turn` (`session_id --role user|lifehug
  --expected-turns N`, text on stdin) — the CAS append
- `conversation-close` (`session_id --reason done|idle_timeout|exit_taken`,
  takeaway on stdin optional) — store close only (no message send, no
  commit — Wave 2)
- `conversation-turn-prompt`, `conversation-router-prompt`,
  `conversation-arc-prompt`, `conversation-closing-prompt` — stdin JSON →
  prompt on stdout (the four builders)
- `conversation-lint` (text on stdin, `--reply-to-substantive` flag) —
  findings as JSON lines; exit 0 with findings printed (linting is
  reporting, not failing — CI decides what fails)

### 6. `system/version.json`

Bump version (151 expected) + changelog (sized to impact: durable
session-store + vault-contract v2 — real but not-yet-user-visible; a few
sentences). Add `system/conversation.py` and
`system/conversation_lints.py` to `framework_files`.

## Implementation notes

- Copy the `answer_ack.py` module shape wholesale (docstring format,
  REQUIRED_FIELDS validation, error behavior) — it is the established
  convention and the platform vendors these modules in Wave 3, so
  discipline here is load-bearing.
- All vault file access through `lifehug_core` `_data` paths /
  `vault_paths` helpers — never hand-built paths (the v120 containment
  boundary).
- `_parse_simple_yaml(..., validate_ai_routing=False)` — do not opt into
  AI-routing validation for interaction files.
- Order of operations for the contract edit: (1) edit
  `vault_paths._normalized_contract` directory set, (2) edit
  `vault_contract.json` entries, (3) run the digest recipe, (4) paste
  digest, (5) `python3 -c "import sys; sys.path.insert(0,'system');
  import vault_paths"` must succeed.
- Keep `conversation.py` importable with a cold vault (no
  `state/conversations/` yet): `list_sessions` returns `[]`,
  `load_arc_card` returns `None` — required-nothing degradation like
  every other state module.
- No behavior change means: no existing module imports the new ones
  (`grep -rn "import conversation" system/*.py` shows only
  `lifehug.py`'s subprocess dispatch strings and the new modules
  themselves).

## Test plan

New test file `tests/test_v151_conversation_store.py` (rename to the
actual landing version), unittest-style, using `tests/tempdirs.py`
temp-vault conventions (see `tests/test_v120_vault_only.py`'s
`make_vault` pattern). Subtests, explicitly named (state-machine-shaped
change → the v130/v131 precedent applies):

1. **Registration**: contract imports green; `EXPECTED_DATA_PATHS`
   includes the three names; exported kinds/tracked flags match
   Deliverable 1; `interactions` framework path exports kind
   `directory`; digest self-consistent (the existing
   `test_v120_vault_only` assertions, updated, already prove this — this
   subtest just pins the three new entries' shapes).
2. **Session lifecycle**: open (chat, with arc) → document on disk in
   `state/conversations/`, schema fields exactly as Deliverable 2;
   append user turn (CAS ok) → append with stale `expected_turns` fails
   typed and the file holds exactly one turn; close with `reason: done` →
   status closed, close block present; re-close idempotent; append after
   close fails typed.
3. **Assembly determinism**: same session + same blocks → byte-identical
   context twice; block order matches interaction.yaml `load_order`
   (parse the yaml in the test — the doc-drift guard); budgets truncate
   (oversized fake block → truncated to budget).
4. **Builders**: each of the four builders on a fixture payload — output
   contains the expected file content markers (e.g. router prompt
   contains all five intent names and the message; turn prompt ends with
   the filled turn-instructions; closing prompt reflects
   `knob.deposit_framing`); each CLI path: valid stdin JSON → prompt on
   stdout, exit 0; empty stdin / missing field → exit 1, one stderr line
   (subprocess invocation, same as `tests/test_answer_ack.py` does).
5. **Lints**: per lint id, at least one flagged and one clean fixture —
   e.g. two questions → `one_question_per_turn`; "That must have been so
   hard." → `banned_phrases`; "Did you like it?" → grammar `closed`
   flagged; "Was it the red one or the blue one?" → `option_posing`;
   "What year did you move?" → `year_question_detector`; reply opening
   with a question when `is_reply_to_substantive` →
   `receipt_before_question`; a correct payout turn (receipt sentence +
   one cued invitation quoting the user) → zero findings.
6. **No-behavior-change guard**: source scan asserting no module under
   `system/` other than `lifehug.py` and the two new modules references
   `conversation` imports (regex over file contents, same style as the
   `_data` parity assertion).

Invocations (scoped — full local suite forbidden while sibling agents
share the machine; CI is the full-suite arbiter):

```
python3 -m unittest tests.test_v151_conversation_store -v
python3 -m unittest tests.test_v120_vault_only -v
python3 -m unittest tests.test_lifehug_core tests.test_lifehug_wrapper -v
```

## Launch-and-verify

No `serve_wiki.py` changes → no walkthrough (BUILDING.md §4). Runnable
verification from a fresh checkout of the branch:

```bash
# 1. Contract + registrations healthy
python3 -c "import sys; sys.path.insert(0,'system'); import vault_paths, lifehug_core; \
  print(sorted(set(vault_paths.VAULT_DATA_PATHS) & {'arc_cards','conversations','mirror_responses'})); \
  print(vault_paths.FRAMEWORK_PATHS['interactions'])"
# expect: the three names; {'path': 'interactions', 'kind': 'directory', ...}

# 2. A session, end to end, in a scratch vault (NEVER a real vault)
export LIFEHUG_VAULT=/tmp/lifehug-verify-vault   # or the repo's env var per vault_paths.bootstrap docs
python3 system/lifehug.py conversation-open --mode conversation --channel cli
echo "The first thing I remember about the farm is the smell of diesel." | \
  python3 system/lifehug.py conversation-record-turn <SESSION_ID> --role user --expected-turns 0
python3 system/lifehug.py conversation-status <SESSION_ID>
# expect: open, 1 turn, channel cli, no turn text in default output

# 3. A prompt, no model anywhere
python3 - <<'PY' | python3 system/lifehug.py conversation-router-prompt
import json; print(json.dumps({"message": "what's the weather tomorrow?",
  "session_open": False, "pending_question_id": None}))
PY
# expect: router.md text with the message embedded and all five intents; exit 0

# 4. Lints catch and pass
printf 'That must have been so hard. What year was that? Or was it later?' | \
  python3 system/lifehug.py conversation-lint --reply-to-substantive
# expect: findings incl. banned_phrases, year_question_detector, receipt ok,
#         option_posing/one_question_per_turn per the text

# 5. Scoped tests
python3 -m unittest tests.test_v151_conversation_store tests.test_v120_vault_only -v
```

What to look at: the created `state/conversations/conv-*.json` document —
its fields should read exactly like Deliverable 2's schema; that file IS
the viewable artifact of this PR.

## Definition of done

- [ ] Registrations complete (contract v2, digest green on import,
      `_data` accessors, parity tests updated)
- [ ] `system/conversation.py` + `system/conversation_lints.py` per
      Deliverables 3–4; `lifehug.py` subcommands per Deliverable 5
- [ ] New test file green on py3.11 + py3.14 locally-scoped and in CI;
      no live-flow behavior change (subtest 6 proves it)
- [ ] `system/version.json` bumped; two new modules in `framework_files`;
      `check_framework_files.py` green
- [ ] AGENTS.md/CLAUDE.md untouched (no described behavior changes — the
      routing-prose sharpening is Wave 2)
- [ ] ADR: none new — ADR 0002 (from #114) already records the
      vault-contract additions; update it only if the shipped schema
      deviates from what it planned
- [ ] Evidence comment on the PR: Launch-and-verify transcript (commands
      + outputs) — no screenshots/GIFs needed (no UI surface)
- [ ] Owner closeout comment drafted with judgment items: (1) session-doc
      schema ratification (the durable shape), (2) `conv-*` session-id
      format, (3) lint banned-phrase starter list
- [ ] NEVER: labels, ready-for-review flips, or merges by the
      implementing agent
