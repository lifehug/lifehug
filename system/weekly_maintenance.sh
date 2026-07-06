#!/usr/bin/env bash
# Lifehug Weekly Maintenance
# Runs the low-friction self-improvement loop without changing daily delivery.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_WEEKLY_DRY_RUN:-0}"
QUEUE_LIMIT="${LIFEHUG_WEEKLY_QUEUE_LIMIT:-8}"
ARC_MAX="${LIFEHUG_WEEKLY_ARC_MAX:-2}"
EXPIRES_DAYS="${LIFEHUG_WEEKLY_EXPIRES_DAYS:-8}"
CLASSIFY_LIMIT="${LIFEHUG_WEEKLY_CLASSIFY_LIMIT:-5}"

# v86 (issue #35): the Telegram message is a short counts-first summary;
# the full step-by-step output is persisted here instead (committed with
# state by safe_autocommit, so it's readable from the phone via GitHub
# and on the desktop via the wiki viewer's Reports view).
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REPORT_DIR="state/reports"
REPORT_FILE="$REPORT_DIR/weekly-$(date +%F).md"

# --- Telegram notification helper ---
# Delegates to `lifehug.py notify`, which resolves chat/token and CHUNKS long
# messages under Telegram's 4096-char cap (a single oversized weekly summary
# used to vanish silently). Never fails the flow.
telegram_notify() {
  printf '%s' "$1" | python3 "$WORKSPACE/system/lifehug.py" notify || true
}

run_step() {
  echo
  echo "==> $*"
  "$@"
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

learning_failures_summary() {
  python3 - <<'PY'
import sys

sys.path.insert(0, "system")
from lifehug_core import format_learning_failures_summary

print(format_learning_failures_summary(limit=3, since_days=14))
PY
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
      { git commit -m "Weekly maintenance $(date +%Y-%m-%d)" &&
        git pull --rebase --autostash &&
        git push; }; } 2>&1
  )
  local git_status=$?
  set -e
  if [[ "$git_status" -ne 0 ]]; then
    echo "warn: git housekeeping failed" >&2
    echo "$git_out" >&2
    record_learning_failure "weekly_maintenance" "git_autocommit" "$git_status" "$git_out"
  fi
  return 0
}

has_safe_source_findings() {
  python3 - "$WORKSPACE/state/source_lint_findings.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except json.JSONDecodeError:
    raise SystemExit(1)
for finding in data.get("findings", []):
    if finding.get("status") == "open" and finding.get("fixability") == "safe":
        raise SystemExit(0)
raise SystemExit(1)
PY
}

run_source_integrity() {
  echo
  echo "==> python3 system/lifehug.py source-lint"
  set +e
  python3 "$WORKSPACE/system/lifehug.py" source-lint
  local lint_status=$?
  set -e

  if has_safe_source_findings; then
    echo
    echo "==> python3 system/lifehug.py source-lint --fix"
    if ! python3 "$WORKSPACE/system/lifehug.py" source-lint --fix; then
      echo "warn: source lint still has manual findings after safe fixes"
    fi
  elif [[ "$lint_status" -ne 0 ]]; then
    echo "warn: source lint has manual findings; see state/source_lint_findings.json"
  fi
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: weekly maintenance"
  run_step python3 "$WORKSPACE/system/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$WORKSPACE/system/lifehug.py" source-lint --no-write-findings
  run_step python3 "$WORKSPACE/system/lifehug.py" classify-story --classify-all --unclassified --limit "$CLASSIFY_LIMIT" --dry-run
  run_step python3 "$WORKSPACE/system/lifehug.py" quality-stats
  run_step python3 "$WORKSPACE/system/lifehug.py" candidates-auto-promote --dry-run
  run_step python3 "$WORKSPACE/system/lifehug.py" planner-report --limit "$QUEUE_LIMIT"
  run_step python3 "$WORKSPACE/system/research_expand.py" --gaps --dry-run
  run_step python3 "$WORKSPACE/system/lifehug.py" progress
  SINCE_7D=$(python3 -c "from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)-timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  run_step python3 "$WORKSPACE/system/lifehug.py" weekly-summary --since "$SINCE_7D"
  exit 0
fi

run_step python3 "$WORKSPACE/system/lifehug.py" compile --no-ai
run_source_integrity
echo
echo "==> python3 system/lifehug.py classify-story --classify-all --unclassified --limit ${CLASSIFY_LIMIT}"
set +e
CLASSIFY_OUT=$(python3 "$WORKSPACE/system/lifehug.py" classify-story --classify-all --unclassified --limit "$CLASSIFY_LIMIT" 2>&1)
CLASSIFY_STATUS=$?
set -e
if [[ "$CLASSIFY_STATUS" -ne 0 ]]; then
  record_learning_failure "weekly_maintenance" "classify_story" "$CLASSIFY_STATUS" "$CLASSIFY_OUT"
fi
echo "$CLASSIFY_OUT"

# Every learning-loop step below is wrapped: a failure is recorded and reported,
# never allowed to silently kill the rest of the flow under set -e.
run_learning_step() {
  local component="$1"; shift
  local out status
  echo
  echo "==> $*"
  set +e
  out=$("$@" 2>&1)
  status=$?
  set -e
  echo "$out"
  if [[ "$status" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "$component" "$status" "$out"
    out="⚠ ${component} FAILED (exit ${status})
${out}"
  fi
  LAST_STEP_OUT="$out"
}

run_learning_step "quality_update" python3 "$WORKSPACE/system/lifehug.py" quality-update

# Synthesis→question loop (v71): non-boilerplate open questions from compiled
# wiki pages become candidates (capped at 3/week — the wiki whispers).
run_learning_step "wiki_harvest" python3 - <<'PY'
import sys
sys.path.insert(0, "system")
from question_candidates import harvest_wiki_questions
harvested = harvest_wiki_questions()
if harvested:
    print(f"✓ Harvested {len(harvested)} open question(s) from the wiki into candidates: {', '.join(harvested)}")
else:
    print("No new wiki open questions to harvest.")
PY

run_learning_step "auto_promote" python3 "$WORKSPACE/system/lifehug.py" candidates-auto-promote
PROMOTE_OUT="$LAST_STEP_OUT"

run_learning_step "planner_queue" python3 "$WORKSPACE/system/lifehug.py" planner-queue --limit "$QUEUE_LIMIT" --arc-max "$ARC_MAX" --expires-days "$EXPIRES_DAYS"
QUEUE_OUT="$LAST_STEP_OUT"

run_step python3 "$WORKSPACE/system/research_expand.py" --gaps --dry-run
PROGRESS_OUT=$(python3 "$WORKSPACE/system/lifehug.py" progress 2>&1)
echo "$PROGRESS_OUT"
LEARNING_OUT=$(learning_failures_summary 2>&1 || true)
echo "$LEARNING_OUT"

# Pending Focus recommendations — 19 once sat unreviewed for weeks because no
# scheduled surface ever mentioned them. One line, with the approve command.
RECS_OUT=$(python3 - <<'PY' 2>/dev/null || true
import json, sys
from pathlib import Path
try:
    data = json.loads(Path("state/focus_recommendations.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    sys.exit(0)
pending = [r for r in data.get("recommendations", []) if r.get("status", "pending") == "pending"]
if not pending:
    sys.exit(0)
top = ", ".join(f"{r['entity']} ({r['score']:.0f})" for r in pending[:3])
print(f"🎯 {len(pending)} Focus recommendation(s) pending — top: {top}")
print("   approve: lifehug.py recommend-focuses --approve <rec-id> (creates the Focus + starter questions)")
PY
)
echo "$RECS_OUT"

# Scheduled health check — surfaces queue expiry, backlog age, zombie Focuses,
# cadence stalls, and roster wipes while there is still time to act.
set +e
DOCTOR_OUT=$(python3 "$WORKSPACE/system/lifehug.py" doctor 2>&1)
DOCTOR_STATUS=$?
set -e
echo "$DOCTOR_OUT"
if [[ "$DOCTOR_STATUS" -ne 0 ]]; then
  record_learning_failure "weekly_maintenance" "doctor" "$DOCTOR_STATUS" "$DOCTOR_OUT"
fi

# Persist the full raw report (the old wall-of-text) as a document.
mkdir -p "$REPORT_DIR"
{
  echo "# Lifehug Weekly Report — $(date '+%Y-%m-%d %H:%M')"
  for section in \
    "Classification:CLASSIFY_OUT" \
    "Candidate promotion:PROMOTE_OUT" \
    "Planner queue:QUEUE_OUT" \
    "Progress:PROGRESS_OUT" \
    "Learning failures:LEARNING_OUT" \
    "Focus recommendations:RECS_OUT" \
    "Doctor:DOCTOR_OUT"; do
    title="${section%%:*}"; var="${section##*:}"
    echo; echo "## ${title}"; echo; echo '```'
    printf '%s\n' "${!var:-—}"
    echo '```'
  done
} > "$REPORT_FILE"
echo "✓ Full report written to $REPORT_FILE"

safe_autocommit

# Second-voice offer (v72, Tier 2): at most N/month (config, default 2), one
# ignorable line, offered questions never repeat. Empty most weeks by design.
SECOND_VOICE_OUT=$(python3 - <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, "system")
from question_planner import pick_second_voice_offer
offer = pick_second_voice_offer()
if offer:
    print(offer)
PY
)

# Present-tense capture (v71): the system only mined the past — one weekly
# prompt records the life being lived. Replies ingest via ingest-story.
PRESENT_PROMPTS=(
  "What happened this week that future-you will want to remember?"
  "What's one moment from this week you'd put in the book, however small?"
  "What are you carrying right now — the worry or the hope this week ran on?"
  "Who did you connect with this week, and what did it leave you with?"
  "What did this week teach you, or confirm, about yourself?"
  "What's one ordinary detail of your life right now that will sound exotic in 20 years?"
)
PRESENT_PROMPT="${PRESENT_PROMPTS[$(( $(date +%V | sed 's/^0//') % ${#PRESENT_PROMPTS[@]} ))]}"

# v86 (issue #35): counts-first summary derived from state — never the raw
# step output (that lives in $REPORT_FILE). Doctor output is piped in so the
# checks don't run twice.
SUMMARY=$(printf '%s' "$DOCTOR_OUT" | python3 "$WORKSPACE/system/lifehug.py" weekly-summary \
  --since "$START_TS" --report-path "$REPORT_FILE" --doctor-file - 2>&1) \
  || SUMMARY="⚠ weekly summary generation failed — see $REPORT_FILE"

telegram_notify "${SUMMARY}

${SECOND_VOICE_OUT}

📸 This week, while it's fresh: ${PRESENT_PROMPT}
(Reply and it saves as a story)"
