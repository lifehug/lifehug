# Contract: Natural Date Ranges for Source Grounding

Generated with GPT-5.6 Sol via Codex. Owner authorized implementation 2026-09-17.

## Why

Timeline evidence validates exact temporal quotations through
`system.timeline_evidence._same_date`, but `chronology.parse_loose_date`
currently rejects ordinary whole-string ranges such as `January 2012 through
December 2015` and `2012 to 2015`. A new-source event can therefore quote the
source exactly and normalize to the correct EDTF range yet still be refused as
`context_grounding_invalid`. This v308 bug fix restores that exact-quote path
without relaxing provenance or evidence checks.

## Binding facts

- Base is merged `lifehug/lifehug` main at
  `f3f851c33d640479617ad4c0ede4135b4db905ae` (v307); this PR is v308.
- `system/chronology.py:parse_loose_date` remains the one authority for loose
  date normalization used by `system/timeline_evidence.py:_same_date`.
- Accepted new forms are whole-string ranges with explicit endpoints joined by
  one unambiguous top-level `through` or `to`, with optional leading `from`.
- Each endpoint must independently parse as an existing explicit single date,
  including year, month-year, and full known month/day forms. There is no
  missing-year inference, arbitrary text parsing, nested range acceptance, or
  ambiguous numeric-date grammar.
- Preserve endpoint chronology, granularity, bounds, source precision,
  uncertainty, exact quotation, and provenance checks. Invalid or reversed
  endpoints are rejected; they are never swapped.
- No dependency, framework, job-engine, fixture-date substitution, private
  vault access, or hosted-platform change is in scope.

## Scope

In scope: the narrow parser extension; chronology and source-grounding
regressions; a pure calculated-timeline regression showing compatible exact
evidence narrows an existing human range without changing node or constraint
identity; v308 release metadata; and brief parser-limit documentation.

Out of scope: general natural-language date extraction, relative dates,
implicit endpoints, changes to exact quote/subject/provenance validation,
timeline fold behavior, hosted pin/deploy work, and live/private data.

## Implementation notes

- Extend `system/chronology.py:parse_loose_date` with a bounded internal helper
  so endpoint parsing cannot recursively admit ranges.
- Continue to use existing single-date and EDTF parsing for both endpoints and
  construct the resulting range from their validated outer bounds.
- Keep `system/timeline_evidence.py:normalize_source_grounding` unchanged unless
  a test exposes an integration defect outside the parser.

## Test plan

Update `tests/test_chronology.py`, `tests/test_timeline_evidence_links.py`, and
`tests/test_temporal_timeline.py`. Cover supported year/month/day endpoints,
optional `from`, exact River House grounding, and negative wrong-bounds,
outside-quote, invalid, reversed, missing-year, nested-range, and ambiguous-date
cases. Run:

```bash
python3 -m unittest \
  tests.test_chronology \
  tests.test_timeline_evidence_links \
  tests.test_temporal_timeline
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/ci/check_framework_files.py
python3 scripts/ci/check_version_bump.py \
  --base f3f851c33d640479617ad4c0ede4135b4db905ae --head HEAD
```

## Definition of done

- [ ] Contract committed before implementation and draft PR opened.
- [ ] Focused regressions and full core suite pass locally.
- [ ] `system/version.json` is v308, released 2026-09-17, with an accurate
      changelog and this distributable contract listed in `framework_files`.
- [ ] Brief chronology documentation describes supported range forms and hard
      parser limits.
- [ ] Branch pushed with truthful model/surface attribution; PR remains draft
      with no labels, readiness change, merge, CI watching, hosted deploy, or
      private-vault work.
