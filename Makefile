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
