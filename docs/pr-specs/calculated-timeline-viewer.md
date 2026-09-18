# Contract: calculated-timeline-viewer

## Why

Issue #247 is the open cross-medium parity item for the calculated Timeline
view (platform #671). The standalone viewer's current `view_timeline()` still
reads the legacy `timeline.timeline_data()` periods and event rows, while the
platform draws the published calculated projection: shared selection, the
Lived/Worked/Schooled lanes, and explicit work such as `NeedsPlacing`. This
contract defines the OSS viewer's parity boundary before implementation. It
also records the later lane/presentation work in #314 so this PR does not
silently duplicate or absorb it.

The feature is **In the Loop**: it is a read surface over the same calculated
projection that feeds queue and Mirror work. This PR is intentionally the
contract-only first step; it does not change the viewer or any durable data.

## Binding facts

Facts are pinned against `origin/main` `5612a229685d7f7e0769f8f1a28b97b8b5ee0907`
(v311) at contract authoring time.

- The visible entry point is `system/serve_wiki.py:view_timeline()` and the
  registered URL remains `/views/timeline`. Existing framework exports and
  navigation remain the integration surface; no second viewer or route is
  introduced.
- The canonical read model is
  `system/temporal_publication.py:calculated_view(vault_root)`. It reads the
  published materialized projection and returns the declared view block,
  including `published`, `projection_generation`, `published_at`,
  `schema_version`, `calculation_rule_version`, `score_formula_version`,
  `nodes`, `work_items`, `memberships`, `lanes`, `frame_display`, aliases,
  reach, keystones, and counts. The standalone must consume this block rather
  than call `timeline.timeline_data()` for the new timeline presentation.
- Projection schema and closed vocabularies remain owned by
  `system/temporal_projection.py`: `PROJECTION_SCHEMA_VERSION`,
  `projection_schema_version()`, `TEMPORAL_STATES`, `LIFE_VIEWS`,
  `OWNER_TIMELINE_RELATIONS`, `LANES`, `LANES_BY_EVENT_KIND`, and the
  validators. The viewer must not copy these lists or re-derive their meaning.
- Lane derivation remains owned by
  `system/temporal_timeline.py:lane_rows()` and its published `lanes` block.
  The viewer renders those rows; it never assigns an episode to a lane from
  labels, dates, or legacy period membership.
- Work-item identity and placement state remain owned by the calculated
  projection/work-item contracts. `NeedsPlacing` is a presentation of the
  canonical unplaced work state, not a new viewer-side classification. The
  implementation must use the existing work-item fields and allowed-surface
  rules rather than minting a parallel needs-placement list.
- Version/contract drift is a build failure. The implementation must add a
  focused guard proving that the viewer's consumed key set and state/lane
  vocabulary are derived from the exported calculated view/projection
  contracts, and that a changed projection schema or calculation-rule version
  cannot silently send the viewer back to legacy rows. The guard must fail
  closed with an explicit unavailable state or a required code update; it may
  not silently reinterpret a new projection.
- The viewer remains private-local. Preserve
  `system/serve_wiki.py`'s `_validated_bind_host`, loopback peer, exact
  Host/port, Origin, CSRF, and raw-source protections. The default bind is
  loopback, non-loopback bind hosts remain rejected, and a request that fails
  the existing loopback checks must not receive timeline material.
- No local/private raw data is a fixture, test input, screenshot, committed
  artifact, or PR evidence. Tests and walkthroughs use only disposable
  synthetic vaults and synthetic calculated projection payloads. They must not
  reference a personal checkout, private source path, or private answer text.
- The implementation PR is the release boundary: it must bump
  `system/version.json`, update the manifest for any new distributable test or
  walkthrough files, and update only the behavior docs required by the landed
  viewer. This contract-only PR deliberately does not make that version bump;
  the repository's documented contract-only precedent keeps this draft
  separate from shipped behavior.

## Scope

**In:**

- Upgrade the existing `/views/timeline` page to render the published
  calculated projection through `calculated_view()`.
- Keep selection and ordering consistent with the canonical projection and
  its published generation. Render calculated nodes, their temporal state and
  value shape, explicit uncertainty/conflict information, memberships, and
  the published lane rows without inventing a second fold.
- Render explicit user-facing states: no projection published yet; published
  but empty; normal calculated timeline; calculated nodes still `unplaced`
  with their canonical `NeedsPlacing` work; and a stale/unsupported or
  unreadable projection that is clearly unavailable rather than silently
  falling back to legacy interpretation.
- Preserve the current framework's navigation, owner-only semantics, and
  loopback-only serving. Preserve existing placement/action ownership unless
  the implementation contract for a calculated work item already provides the
  canonical route; no second writer is allowed.
- Add regression parity over shared synthetic fixtures: the same fixture
  projection must produce the same selected nodes, lane rows, unplaced work,
  and explicit state labels at the view boundary. Add UI checks for the
  existing viewer route and the states above.
- Add a runnable walkthrough using the existing `WalkthroughHarness`, a
  disposable synthetic vault, and the repository's standard 1440x900 and
  390x844 viewports.

**Out:**

- No implementation in this contract-only PR; no code, test, walkthrough,
  screenshot, generated wiki, or private-data artifact is added here.
- No changes to the calculated fold, publication writer, temporal schemas,
  queue, Mirror, placement writer, platform, hosted infrastructure, or
  deployment behavior.
- No duplicate selection, lane assignment, NeedsPlacing classifier, or
  projection parser in `serve_wiki.py`.
- No broad Timeline redesign, new route, visual-system rewrite, drag/drop
  placement interaction, or platform-side feature work. The lane and
  presentation extension tracked by #314 remains separately scoped.
- No real vault, local/private source, model/provider call, cloud operation,
  or fixture containing raw personal content.

## Implementation notes

- Replace the legacy data dependency in `system/serve_wiki.py:view_timeline()`
  with the existing calculated read-model seam. The function may compose HTML
  and links, but it must not calculate projection membership, lane assignment,
  selection, identity, or work-item status.
- Keep the legacy compiler/export behavior unchanged unless the implementation
  proves that the existing export is the same canonical read surface. A
  compatibility alias must not become a second source of truth.
- Use the projection's stable node/work-item ids for links and actions. Render
  aliases and generation/rule metadata only where the existing owner-facing
  viewer needs them; do not expose maintainer diagnostics or raw evidence by
  default.
- The guard should pin the consumed view-block keys and the versioned
  projection/rule identifiers through exported constants/functions. A fixture
  with an added unknown top-level key or changed required version must fail the
  guard instead of being silently ignored by the page.
- Keep the existing HTML escaping, owner-only page policy, loopback request
  checks, and mutation token handling. Read-only timeline rendering must not
  weaken any of those controls.

## Test plan

The implementation PR adds a focused view test module and one walkthrough;
existing projection tests remain the authority for projection behavior.

- `tests/test_calculated_timeline_view.py` uses only a disposable synthetic
  vault and synthetic published projection payloads. It proves: absent
  publication is an explicit state; an empty publication is distinct; placed
  and unplaced nodes render from `calculated_view()`; `NeedsPlacing` comes
  from canonical work items; published lane rows and stable ids are rendered
  without a legacy fallback; unsupported/stale versions fail closed; and
  private non-loopback/Host/Origin protections remain enforced.
- The same tests assert parity between the synthetic projection fixture and
  the view's selected node ids, lane rows, temporal states, work-item ids, and
  counts. They must import the shared projection validators/constants instead
  of repeating their vocabularies.
- The version/contract guard must be executable in the focused invocation and
  must fail when the fixture's required projection version or consumed view
  key set drifts.
- Required focused command:

  ```text
  TMPDIR=/private/tmp python3 -m unittest \
    tests.test_calculated_timeline_view \
    tests.test_projection_publication \
    tests.test_projection_schema_v3 \
    tests.test_eras_e1b -v
  ```

- The implementation must also run the repository's manifest/version checks
  after its release bump:

  ```text
  python3 scripts/ci/check_framework_files.py
  python3 scripts/ci/check_version_bump.py
  ```

## Launch-and-verify

The implementation PR adds `tests/walkthrough_calculated_timeline.py` and the
standard Makefile target `make walkthrough-calculated-timeline`. It runs only
against a disposable synthetic vault and the local loopback viewer. The run
must:

1. capture the unpublished/empty projection state;
2. publish the synthetic calculated fixture and capture the ordinary
   calculated timeline with at least one placed node and one lane;
3. capture the same fixture with an unplaced node and canonical
   `NeedsPlacing` work visible;
4. capture the fail-closed stale/unsupported projection state; and
5. probe the existing loopback/Host protection without recording any source
   body.

The walkthrough must emit exactly eight PNG screenshots: the four visual
  states at 1440x900 and 390x844, with each image's actual dimensions asserted
  by the script. The network probe is an assertion only and emits no private
  payload. Any interaction sequence must also emit the standard raw `.webm`
  alongside its GIF, per `docs/BUILDING.md`.

## Definition of done

- [ ] The implementation PR changes only the named viewer/test/walkthrough,
      required docs, and `system/version.json`; no private content or
      unrelated redesign is present.
- [ ] `calculated_view()` is the only new timeline data seam; no legacy
      periods/events are used for the calculated presentation and no duplicate
      selection/lane/NeedsPlacing logic exists.
- [ ] The version/contract guard, focused unittest command, and walkthrough
      command pass on synthetic data.
- [ ] Loopback, owner-only, Host/Origin, CSRF, and raw-source protections
      remain green.
- [ ] The implementation PR bumps `system/version.json` and its changelog;
      this contract-only draft intentionally does not.
- [ ] Issue #247 receives the implementation verification evidence; #314 is
      not closed or expanded by this contract.

🤖 Generated with Codex via Codex desktop
