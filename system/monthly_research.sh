#!/usr/bin/env bash
# Lifehug Monthly Research
# Opens new question neighborhoods and Focus recommendations at a slow cadence.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_MONTHLY_DRY_RUN:-0}"

# --- Telegram notification helper ---
# Delegates to `lifehug.py notify` (resolves chat/token, chunks under the
# 4096-char cap). Never fails the flow.
telegram_notify() {
  printf '%s' "$1" | python3 "$WORKSPACE/system/lifehug.py" notify || true
}

record_learning_failure() {
  local component="$1"
  local operation="$2"
  local exit_code="$3"
  local output="$4"
  LEARNING_FAILURE_OUTPUT="$output" python3 - "$component" "$operation" "$exit_code" <<'PY' || true
import os
import sys

sys.path.insert(0, "system")
from lifehug_core import record_learning_failure

try:
    code = int(sys.argv[3])
except (IndexError, ValueError):
    code = None
record_learning_failure(
    sys.argv[1],
    sys.argv[2],
    os.environ.get("LEARNING_FAILURE_OUTPUT", ""),
    exit_code=code,
)
PY
}
GAP_LIMIT="${LIFEHUG_MONTHLY_GAP_LIMIT:-2}"
SELF_TOPIC="${LIFEHUG_MONTHLY_SELF_TOPIC:-Who I am becoming}"
SELF_OUTPUT="${LIFEHUG_MONTHLY_SELF_OUTPUT:-essay}"
FOCUS_MIN_SCORE="${LIFEHUG_MONTHLY_FOCUS_MIN_SCORE:-15}"
TARGETS_FILE="$(mktemp "${TMPDIR:-/tmp}/lifehug-monthly-targets.XXXXXX")"
ROSTER_PREVIEW_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lifehug-roster-preview.XXXXXX")"
trap 'rm -f "$TARGETS_FILE"; rm -rf "$ROSTER_PREVIEW_DIR"' EXIT

run_step() {
  echo
  echo "==> $*"
  "$@"
}

run_optional() {
  echo
  echo "==> $*"
  set +e
  local out
  out=$("$@" 2>&1)
  local status=$?
  set -e
  echo "$out"
  if [[ "$status" -ne 0 ]]; then
    echo "warn: monthly step failed with exit ${status}: $*"
    # The class of silent failure that caused the 2026-07 roster regression —
    # record it so doctor and the weekly summary surface it.
    record_learning_failure "monthly_research" "$1" "$status" "$out"
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
  set +e
  local git_out
  git_out=$(
    git add -- "${existing[@]}" &&
    { git diff --cached --quiet ||
      { git commit -m "Monthly research $(date +%Y-%m-%d)" &&
        git pull --rebase --autostash &&
        git push; }; } 2>&1
  )
  local git_status=$?
  set -e
  if [[ "$git_status" -ne 0 ]]; then
    echo "warn: git housekeeping failed" >&2
    echo "$git_out" >&2
    record_learning_failure "monthly_research" "git_autocommit" "$git_status" "$git_out"
  fi
  return 0
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
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
limit = int(sys.argv[2])
sys.path.insert(0, str(workspace / "system"))

import research_expand as research  # noqa: E402

# The planner computes expansion urgency "for the cron to act on" — this is
# the cron acting on it. Low urgency (Focuses still have room) → no new
# neighborhoods this month; the archive deepens instead of widening.
try:
    queue = json.loads((workspace / "state" / "question_queue.json").read_text(encoding="utf-8"))
    urgency = float(queue.get("allocation", {}).get("expansion", {}).get("urgency", 1.0))
except (OSError, ValueError):
    urgency = 1.0  # no queue signal → don't block expansion
if urgency < 0.25:
    print(f"expansion urgency {urgency:.2f} < 0.25 — skipping new gap neighborhoods this month",
          file=sys.stderr)
    raise SystemExit(0)

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
for item in gaps.get("unfocused_family", gaps.get("un" "spot" "lighted_family", []))[:2]:
    add(item["label"], "person", "letter")

for row in rows:
    print("\t".join(row))
PY
}

preview_focuses() {
  python3 - "$WORKSPACE" "$FOCUS_MIN_SCORE" <<'PY'
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
min_score = float(sys.argv[2])
sys.path.insert(0, str(workspace / "system"))

import recommend_focuses as focuses  # noqa: E402

recs = focuses.recommend(min_score=min_score)
focuses.display_recommendations(recs)
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
  echo "==> preview Focus recommendations"
  preview_focuses
  echo
  echo "==> preview entity roster refreshes"
  for etype in person place period object; do
    run_step python3 "$WORKSPACE/system/lifehug.py" entity-roster --type "$etype" --emit-task "$ROSTER_PREVIEW_DIR/${etype}.json"
  done
  run_step python3 "$WORKSPACE/system/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$WORKSPACE/system/lifehug.py" progress
  exit 0
fi

run_step python3 "$WORKSPACE/system/lifehug.py" compile
RESEARCH_OUT=""
GAPS_OUT=$(python3 "$WORKSPACE/system/research_expand.py" --gaps 2>&1)
echo "$GAPS_OUT"
RESEARCH_OUT="${RESEARCH_OUT}${GAPS_OUT}
"
select_gap_targets > "$TARGETS_FILE"
if [[ ! -s "$TARGETS_FILE" ]]; then
  echo
  echo "No new gap neighborhoods selected."
  RESEARCH_OUT="${RESEARCH_OUT}No new gap neighborhoods selected.
"
fi
while IFS=$'\t' read -r topic topic_type output; do
  [[ -z "${topic:-}" ]] && continue
  TOPIC_OUT=$(generate_topic "$topic" "$topic_type" "$output" 2>&1)
  echo "$TOPIC_OUT"
  RESEARCH_OUT="${RESEARCH_OUT}${TOPIC_OUT}
"
done < "$TARGETS_FILE"
SELF_OUT=$(generate_topic "$SELF_TOPIC" self "$SELF_OUTPUT" 2>&1)
echo "$SELF_OUT"
RESEARCH_OUT="${RESEARCH_OUT}${SELF_OUT}
"
FOCUSES_OUT=$(python3 "$WORKSPACE/system/lifehug.py" recommend-focuses --min-score "$FOCUS_MIN_SCORE" 2>&1) || true
echo "$FOCUSES_OUT"
# Refresh the canonical entity rosters (AI-curated) for every entity type, then
# recompile so newly-eligible entities graduate into pages and Focus pages pick up
# fresh mentions. The whole life graph — people, places, periods, symbolic objects
# — grows without any human interaction.
ROSTER_OUT=""
for etype in person place period object; do
  set +e
  ETYPE_OUT=$(python3 "$WORKSPACE/system/lifehug.py" entity-roster --type "$etype" 2>&1)
  ETYPE_STATUS=$?
  set -e
  if [[ "$ETYPE_STATUS" -ne 0 ]]; then
    record_learning_failure "monthly_research" "entity_roster_${etype}" "$ETYPE_STATUS" "$ETYPE_OUT"
    ETYPE_OUT="⚠ ${etype} roster refresh FAILED (exit ${ETYPE_STATUS})
${ETYPE_OUT}"
  fi
  ROSTER_OUT="${ROSTER_OUT}${ETYPE_OUT}
"
done
echo "$ROSTER_OUT"
run_step python3 "$WORKSPACE/system/lifehug.py" compile
PROGRESS_OUT=$(python3 "$WORKSPACE/system/lifehug.py" progress 2>&1)
echo "$PROGRESS_OUT"
safe_autocommit

telegram_notify "🔬 Lifehug Monthly Research — $(date '+%B %-d')

${RESEARCH_OUT}

${FOCUSES_OUT}

${ROSTER_OUT}

${PROGRESS_OUT}"
