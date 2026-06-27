#!/usr/bin/env bash
# Lifehug Monthly Research
# Opens new question neighborhoods and spotlight recommendations at a slow cadence.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_MONTHLY_DRY_RUN:-0}"
GAP_LIMIT="${LIFEHUG_MONTHLY_GAP_LIMIT:-2}"
SELF_TOPIC="${LIFEHUG_MONTHLY_SELF_TOPIC:-Who I am becoming}"
SELF_OUTPUT="${LIFEHUG_MONTHLY_SELF_OUTPUT:-essay}"
SPOTLIGHT_MIN_SCORE="${LIFEHUG_MONTHLY_SPOTLIGHT_MIN_SCORE:-15}"
TARGETS_FILE="$(mktemp "${TMPDIR:-/tmp}/lifehug-monthly-targets.XXXXXX")"
trap 'rm -f "$TARGETS_FILE"' EXIT

run_step() {
  echo
  echo "==> $*"
  "$@"
}

run_optional() {
  echo
  echo "==> $*"
  set +e
  "$@"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "warn: monthly step failed with exit ${status}: $*"
    return 0
  fi
}

safe_autocommit() {
  local paths=(
    README.md
    system/question-bank.md
    system/rotation.json
    system/coverage.json
    answers
    outputs
    sources
    state
    wiki
  )
  local existing=()
  for path in "${paths[@]}"; do
    [[ -e "$path" ]] && existing+=("$path")
  done
  [[ ${#existing[@]} -eq 0 ]] && return 0
  git add -- "${existing[@]}"
  if ! git diff --cached --quiet; then
    git commit -m "Monthly research $(date +%Y-%m-%d)"
    git push
  fi
}

neighborhood_exists() {
  python3 - "$WORKSPACE" "$1" <<'PY'
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
topic = sys.argv[2]
sys.path.insert(0, str(workspace / "system"))

import research_expand as research  # noqa: E402

nbhd_id = research.neighborhood_id_for(topic)
data = research.load_neighborhoods()
if any(n.get("id") == nbhd_id for n in data.get("neighborhoods", [])):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

select_gap_targets() {
  python3 - "$WORKSPACE" "$GAP_LIMIT" <<'PY'
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
limit = int(sys.argv[2])
sys.path.insert(0, str(workspace / "system"))

import research_expand as research  # noqa: E402

answers = research.load_answers()
if not answers or limit <= 0:
    raise SystemExit(0)

gaps = research.detect_gaps(answers)
existing = {
    n.get("id")
    for n in research.load_neighborhoods().get("neighborhoods", [])
}
rows: list[tuple[str, str, str]] = []

def add(label: str, topic_type: str, output: str) -> None:
    if len(rows) >= limit:
        return
    if research.neighborhood_id_for(label) in existing:
        return
    rows.append((label, topic_type, output))

for item in gaps.get("thin_periods", [])[:3]:
    add(item["label"], "time_period", "chapter")
for item in gaps.get("thin_themes", [])[:3]:
    add(item["label"], "theme", "essay")
for item in gaps.get("unspotlighted_family", [])[:2]:
    add(item["label"], "person", "letter")

for row in rows:
    print("\t".join(row))
PY
}

preview_spotlights() {
  python3 - "$WORKSPACE" "$SPOTLIGHT_MIN_SCORE" <<'PY'
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
min_score = float(sys.argv[2])
sys.path.insert(0, str(workspace / "system"))

import recommend_spotlights as spotlights  # noqa: E402

recs = spotlights.recommend(min_score=min_score)
spotlights.display_recommendations(recs)
PY
}

generate_topic() {
  local topic="$1"
  local topic_type="$2"
  local output="$3"
  if neighborhood_exists "$topic"; then
    echo "skip: neighborhood already exists for ${topic}"
    return 0
  fi
  run_optional python3 "$WORKSPACE/system/research_expand.py" --topic "$topic" --type "$topic_type" --output "$output"
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: monthly research"
  run_step python3 "$WORKSPACE/system/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$WORKSPACE/system/research_expand.py" --gaps --dry-run
  select_gap_targets > "$TARGETS_FILE"
  if [[ ! -s "$TARGETS_FILE" ]]; then
    echo
    echo "No new gap neighborhoods selected."
  fi
  while IFS=$'\t' read -r topic topic_type output; do
    [[ -z "${topic:-}" ]] && continue
    run_step python3 "$WORKSPACE/system/research_expand.py" --topic "$topic" --type "$topic_type" --output "$output" --dry-run
  done < "$TARGETS_FILE"
  if neighborhood_exists "$SELF_TOPIC"; then
    echo "skip: neighborhood already exists for ${SELF_TOPIC}"
  else
    run_step python3 "$WORKSPACE/system/research_expand.py" --topic "$SELF_TOPIC" --type self --output "$SELF_OUTPUT" --dry-run
  fi
  echo
  echo "==> preview spotlight recommendations"
  preview_spotlights
  run_step python3 "$WORKSPACE/system/lifehug.py" progress
  exit 0
fi

run_step python3 "$WORKSPACE/system/lifehug.py" compile
run_step python3 "$WORKSPACE/system/research_expand.py" --gaps
select_gap_targets > "$TARGETS_FILE"
if [[ ! -s "$TARGETS_FILE" ]]; then
  echo
  echo "No new gap neighborhoods selected."
fi
while IFS=$'\t' read -r topic topic_type output; do
  [[ -z "${topic:-}" ]] && continue
  generate_topic "$topic" "$topic_type" "$output"
done < "$TARGETS_FILE"
generate_topic "$SELF_TOPIC" self "$SELF_OUTPUT"
run_optional python3 "$WORKSPACE/system/lifehug.py" recommend-spotlights --min-score "$SPOTLIGHT_MIN_SCORE"
run_step python3 "$WORKSPACE/system/lifehug.py" progress
safe_autocommit
