# lifehug (OSS) — root Makefile.
#
# The only convention codified here (lifehug#85 / v132) is the walkthrough
# pattern rule: `make walkthrough-<slug>` runs
# `tests/walkthrough_<slug>.py`, the evidence-harness convention described
# in docs/pr-specs/TEMPLATE.md's Launch-and-verify section and built on
# tests/walkthrough_lib.py.
#
# There is no fixed dev port to collide on here (unlike the platform repo's
# 3200/8200 walkthrough pairs): each run self-probes a free port via
# tests/walkthrough_lib.py's free_port(). LIFEHUG_WALKTHROUGH_PORT is a pure
# escape hatch — pin a port when you want a stable target for browser
# devtools while debugging a specific run — not a concurrency requirement.
LIFEHUG_WALKTHROUGH_PORT ?=
export LIFEHUG_WALKTHROUGH_PORT

walkthrough-%:
	python3 tests/walkthrough_$*.py --artifacts artifacts/walkthroughs/$*

# Explicit entry (issue #146, ADR 0008): the generic pattern rule substitutes
# `$*` literally, so a hyphenated slug like `unified-quality` would look for
# `tests/walkthrough_unified-quality.py` (hyphen mid-filename) rather than
# the standard-Python-module-naming `tests/walkthrough_unified_quality.py`
# the contract specifies. An explicit target (Make prefers an exact match
# over a pattern rule) bridges the two without changing the pattern rule
# itself or renaming every other slug's script.
walkthrough-unified-quality:
	python3 tests/walkthrough_unified_quality.py --artifacts artifacts/walkthroughs/unified-quality

# Explicit entry (decisions-feed-the-loop): same hyphen-vs-underscore bridge
# as walkthrough-unified-quality above, for tests/walkthrough_decision_reason.py.
walkthrough-decision-reason:
	python3 tests/walkthrough_decision_reason.py --artifacts artifacts/walkthroughs/decision-reason
