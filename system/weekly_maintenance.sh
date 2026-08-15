#!/usr/bin/env bash
# Lifehug Weekly Maintenance
# Runs the low-friction self-improvement loop without changing daily delivery.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-${LIFEHUG_VAULT_ROOT:-$(dirname "$SCRIPT_DIR")}}"
WORKSPACE="$(python3 "$SCRIPT_DIR/vault_paths.py" root --vault-root "$WORKSPACE")" || exit 1
export LIFEHUG_VAULT_ROOT="$WORKSPACE"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_WEEKLY_DRY_RUN:-0}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
QUEUE_LIMIT="${LIFEHUG_WEEKLY_QUEUE_LIMIT:-8}"
ARC_MAX="${LIFEHUG_WEEKLY_ARC_MAX:-2}"
EXPIRES_DAYS="${LIFEHUG_WEEKLY_EXPIRES_DAYS:-8}"
CLASSIFY_LIMIT="${LIFEHUG_WEEKLY_CLASSIFY_LIMIT:-5}"

if ! python3 "$SCRIPT_DIR/jobs.py" active --vault-root "$WORKSPACE" >/dev/null 2>&1 \
    && [[ "$DRY_RUN" != "1" ]]; then
  JOB_IDENTITY="${LIFEHUG_JOB_IDENTITY:-weekly:$(date +%G-W%V)}"
  exec python3 "$SCRIPT_DIR/jobs.py" enqueue weekly --identity "$JOB_IDENTITY" \
    --wait --vault-root "$WORKSPACE"
fi

# v86 (issue #35): the Telegram message is a short counts-first summary;
# the full step-by-step output is persisted here instead (committed with
# state by safe_autocommit, so it's readable from the phone via GitHub
# and on the desktop via the wiki viewer's Reports view).
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REPORT_DIR="$(python3 "$SCRIPT_DIR/vault_paths.py" data-path reports --vault-root "$WORKSPACE")"
REPORT_FILE="$REPORT_DIR/weekly-$(date +%F).md"
SOURCE_FINDINGS_FILE="$WORKSPACE/$(python3 "$SCRIPT_DIR/vault_paths.py" data-path source_lint_findings --vault-root "$WORKSPACE")"
FOCUS_RECS_FILE="$WORKSPACE/$(python3 "$SCRIPT_DIR/vault_paths.py" data-path focus_recommendations --vault-root "$WORKSPACE")"
AGENT_TASKS_DIR="$(python3 "$SCRIPT_DIR/vault_paths.py" data-path agent_tasks --vault-root "$WORKSPACE")"
export FOCUS_RECS_FILE

# --- Telegram notification helper ---
# Delegates to `lifehug.py notify`, which resolves chat/token and CHUNKS long
# messages under Telegram's 4096-char cap (a single oversized weekly summary
# used to vanish silently). Never fails the flow.
telegram_notify() {
  printf '%s' "$1" | python3 "$SCRIPT_DIR/lifehug.py" notify || true
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

from lifehug_core import format_learning_failures_summary

print(format_learning_failures_summary(limit=3, since_days=14))
PY
}

safe_autocommit() {
  local paths=()
  while IFS= read -r path; do
    [[ -n "$path" ]] && paths+=("$path")
  done < <(python3 "$SCRIPT_DIR/vault_paths.py" git-paths --vault-root "$WORKSPACE")
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
  python3 - "$SOURCE_FINDINGS_FILE" <<'PY'
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
  python3 "$SCRIPT_DIR/lifehug.py" source-lint
  local lint_status=$?
  set -e

  if has_safe_source_findings; then
    echo
    echo "==> python3 system/lifehug.py source-lint --fix"
    if ! python3 "$SCRIPT_DIR/lifehug.py" source-lint --fix; then
      echo "warn: source lint still has manual findings after safe fixes"
    fi
  elif [[ "$lint_status" -ne 0 ]]; then
    echo "warn: source lint has manual findings; see state/source_lint_findings.json"
  fi
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: weekly maintenance"
  run_step python3 "$SCRIPT_DIR/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$SCRIPT_DIR/lifehug.py" source-lint --no-write-findings
  run_step python3 "$SCRIPT_DIR/lifehug.py" classify-story --classify-all --unclassified --limit "$CLASSIFY_LIMIT" --dry-run
  run_step python3 "$SCRIPT_DIR/lifehug.py" quality-stats
  run_step python3 "$SCRIPT_DIR/lifehug.py" judgment-update --dry-run
  run_step python3 "$SCRIPT_DIR/lifehug.py" timeline-retire --dry-run
  echo "==> (real run) lifehug.py mirror-compile — synthesizes wiki/self/mirror.md (skipped in dry run: costs an AI call)"
  run_step python3 "$SCRIPT_DIR/lifehug.py" candidates-auto-promote --dry-run
  run_step python3 "$SCRIPT_DIR/lifehug.py" planner-report --limit "$QUEUE_LIMIT"
  run_step python3 "$SCRIPT_DIR/lifehug.py" arc-plan --dry-run --limit "$QUEUE_LIMIT" --gap-max "${LIFEHUG_WEEKLY_ARC_GAP_MAX:-3}"
  run_step python3 "$SCRIPT_DIR/lifehug.py" focus-autopilot --dry-run
  run_step python3 "$SCRIPT_DIR/research_expand.py" --gaps --dry-run
  run_step python3 "$SCRIPT_DIR/lifehug.py" progress
  SINCE_7D=$(python3 -c "from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)-timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  run_step python3 "$SCRIPT_DIR/lifehug.py" weekly-summary --since "$SINCE_7D"
  exit 0
fi

run_step python3 "$SCRIPT_DIR/lifehug.py" compile --no-ai
run_source_integrity

# v92: keyless agent mode. With no AI route (gateway or key), classification
# emits agent tasks to state/agent_tasks/classify instead of recording a raw
# learning failure. The maintenance skill (skills/maintenance) completes them
# via --from-response — ideally BEFORE this script runs, so the planner queue
# sees this week's classifications.
python3 "$SCRIPT_DIR/lifehug.py" ai-status >/dev/null 2>&1 && KEYLESS=0 || KEYLESS=1
echo
if [[ "$KEYLESS" == "1" ]]; then
  echo "==> keyless — emitting classification tasks for agent completion"
  set +e
  CLASSIFY_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" classify-story --classify-all --unclassified --limit "$CLASSIFY_LIMIT" --emit-prompts "$AGENT_TASKS_DIR/classify" 2>&1)
  CLASSIFY_STATUS=$?
  set -e
  if [[ "$CLASSIFY_STATUS" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "classify_story_emit" "$CLASSIFY_STATUS" "$CLASSIFY_OUT"
  elif ! grep -q "^No source files to classify" <<< "$CLASSIFY_OUT"; then
    CLASSIFY_OUT="⏸ keyless — tasks emitted, not failures. Complete them via the maintenance skill (--from-response), then re-run.
$CLASSIFY_OUT"
  fi
else
  echo "==> python3 system/lifehug.py classify-story --classify-all --unclassified --limit ${CLASSIFY_LIMIT}"
  set +e
  CLASSIFY_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" classify-story --classify-all --unclassified --limit "$CLASSIFY_LIMIT" 2>&1)
  CLASSIFY_STATUS=$?
  set -e
  if [[ "$CLASSIFY_STATUS" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "classify_story" "$CLASSIFY_STATUS" "$CLASSIFY_OUT"
  fi
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

run_learning_step "quality_update" python3 "$SCRIPT_DIR/lifehug.py" quality-update

# Weekly question-judgment RUBRIC-EDIT (decisions-feed-the-loop, ADR 0009):
# the owner's promote/dismiss/defer decisions plus this week's freshly-
# updated quality-profile bucket movements become AT MOST ONE bounded,
# evidence-cited amendment to state/question_judgment/learned.md — never a
# rewrite, never a deterministic invention when no model is available.
# Runs immediately after quality_update (freshest profile snapshot) and
# before candidate auto-promotion (order matters: this run's edit informs
# NEXT week's generation prompts, not this run's — see ADR 0009's one-run
# lag). The cursor file makes a same-week re-run a no-op. Keyless machines
# emit the rubric-edit task for agent completion instead.
if [[ "$KEYLESS" == "1" ]]; then
  echo
  echo "==> keyless — emitting judgment rubric-edit task for agent completion"
  set +e
  JUDGMENT_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" judgment-update --emit-task "$AGENT_TASKS_DIR/judgment/edit.json" 2>&1)
  JUDGMENT_STATUS=$?
  set -e
  if [[ "$JUDGMENT_STATUS" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "judgment_update_emit" "$JUDGMENT_STATUS" "$JUDGMENT_OUT"
  elif ! grep -q "no change" <<< "$JUDGMENT_OUT"; then
    JUDGMENT_OUT="⏸ keyless — rubric-edit task emitted, not a failure. Complete via the maintenance skill (--from-response).
$JUDGMENT_OUT"
  fi
  echo "$JUDGMENT_OUT"
else
  run_learning_step "judgment_update" python3 "$SCRIPT_DIR/lifehug.py" judgment-update
fi

# Pin retirement (v105): manual timeline pins whose event the (fresh)
# classification now places by itself retire automatically — the filed date
# assertion is the durable information; the pin was only the display overlay.
run_learning_step "timeline_retire" python3 "$SCRIPT_DIR/lifehug.py" timeline-retire

# Synthesis→question loop (v71): non-boilerplate open questions from compiled
# wiki pages become candidates (capped at 3/week — the wiki whispers).
run_learning_step "wiki_harvest" python3 - <<'PY'
import sys
from question_candidates import harvest_wiki_questions
harvested = harvest_wiki_questions()
if harvested:
    print(f"✓ Harvested {len(harvested)} open question(s) from the wiki into candidates: {', '.join(harvested)}")
else:
    print("No new wiki open questions to harvest.")
PY

# Mirror synthesis (v100): distill classifier contradictions/insights/positions
# into wiki/self/mirror.md — this week's introspection edition. Runs after
# classification so the freshest signals are in. Keyless machines emit the
# synthesis task for agent completion instead (see skills/maintenance).
if [[ "$KEYLESS" == "1" ]]; then
  echo
  echo "==> keyless — emitting mirror synthesis task for agent completion"
  set +e
  MIRROR_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" mirror-compile --emit-task "$AGENT_TASKS_DIR/mirror" 2>&1)
  MIRROR_STATUS=$?
  set -e
  if [[ "$MIRROR_STATUS" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "mirror_emit" "$MIRROR_STATUS" "$MIRROR_OUT"
  elif ! grep -qE "^(No mirror material|Mirror already fresh)" <<< "$MIRROR_OUT"; then
    MIRROR_OUT="⏸ keyless — mirror task emitted, not a failure. Complete via the maintenance skill (--from-response).
$MIRROR_OUT"
  fi
  echo "$MIRROR_OUT"
else
  run_learning_step "mirror_compile" python3 "$SCRIPT_DIR/lifehug.py" mirror-compile
  MIRROR_OUT="$LAST_STEP_OUT"
fi

run_learning_step "auto_promote" python3 "$SCRIPT_DIR/lifehug.py" candidates-auto-promote
# Read indirectly by the report section table below.
# shellcheck disable=SC2034
PROMOTE_OUT="$LAST_STEP_OUT"

run_learning_step "planner_queue" python3 "$SCRIPT_DIR/lifehug.py" planner-queue --limit "$QUEUE_LIMIT" --arc-max "$ARC_MAX" --expires-days "$EXPIRES_DAYS"
# Read indirectly by the report section table below.
# shellcheck disable=SC2034
QUEUE_OUT="$LAST_STEP_OUT"

# Arc cards (issue #118): one card per question the queue just planned — an
# opening framing plus 2–4 typed follow-up intents — so the daily loop can
# ATTACH a plan instead of asking three unrelated questions. Runs DIRECTLY
# after planner_queue so the cards are planned against the queue just written,
# and they expire with it.
#
# PARITY SPEC (binding): the platform transports this step verbatim as
# StepSpec("arcs", "arc_plan", llm=True) + LlmPurpose "arc_plan". Every cap,
# gate, and fallback the platform needs must appear HERE first — a
# platform-side gate absent from this step is a parity merge-blocker.
ARC_GAP_MAX="${LIFEHUG_WEEKLY_ARC_GAP_MAX:-3}"
# ARCS_OUT is read indirectly by the report section table below.
# shellcheck disable=SC2034
if [[ "$KEYLESS" == "1" ]]; then
  echo
  echo "==> keyless — writing deterministic arc cards and emitting the arc-plan task"
  set +e
  ARCS_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" arc-plan --limit "$QUEUE_LIMIT" --gap-max "$ARC_GAP_MAX" --emit-tasks "$AGENT_TASKS_DIR/arcs" 2>&1)
  ARCS_STATUS=$?
  set -e
  if [[ "$ARCS_STATUS" -ne 0 ]]; then
    record_learning_failure "weekly_maintenance" "arc_plan_emit" "$ARCS_STATUS" "$ARCS_OUT"
  elif ! grep -q "^No queued questions" <<< "$ARCS_OUT"; then
    ARCS_OUT="⏸ keyless — arc-plan task emitted, not a failure. Deterministic cards are already written; complete the model pass via the maintenance skill (--from-response).
$ARCS_OUT"
  fi
  echo "$ARCS_OUT"
else
  run_learning_step "arc_plan" python3 "$SCRIPT_DIR/lifehug.py" arc-plan --limit "$QUEUE_LIMIT" --gap-max "$ARC_GAP_MAX"
  ARCS_OUT="$LAST_STEP_OUT"
fi

# Focus autopilot (ADR 0011 — the Convergence Principle's floor applied to
# focus creation): while the "developing" set (active, non-primary,
# unsaturated Focuses) is thinner than target, the highest-scoring pending
# idea at/above the floor is auto-approved through approve_recommendation()
# itself — the exact same path a manual approval takes, so category
# scaffolding and starter-question seeding ride along for free. Runs AFTER
# candidate auto-promotion and queue planning (auto_promote, planner_queue,
# arc_plan above): a newly-approved Focus's seeded starter questions land in
# the question bank too late for THIS run's already-written queue/arc cards
# — they enter NEXT week's planning. Accepted one-run lag, mirroring ADR
# 0009's — see docs/adr/0011-focus-autopilot.md. Gentle by default (at most
# one approval per run); --catch-up is a manual CLI-only escalation, never
# wired into the weekly run.
run_learning_step "focus_autopilot" python3 "$SCRIPT_DIR/lifehug.py" focus-autopilot
# Read indirectly by the report section table below.
# shellcheck disable=SC2034
FOCUS_AUTOPILOT_OUT="$LAST_STEP_OUT"

run_step python3 "$SCRIPT_DIR/research_expand.py" --gaps --dry-run
PROGRESS_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" progress 2>&1)
echo "$PROGRESS_OUT"
LEARNING_OUT=$(learning_failures_summary 2>&1 || true)
echo "$LEARNING_OUT"

# Pending Focus recommendations — 19 once sat unreviewed for weeks because no
# scheduled surface ever mentioned them. One line, with the approve command.
RECS_OUT=$(python3 - <<'PY' 2>/dev/null || true
import json, os, sys
from pathlib import Path
try:
    data = json.loads(Path(os.environ["FOCUS_RECS_FILE"]).read_text(encoding="utf-8"))
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
DOCTOR_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" doctor 2>&1)
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
    "Mirror:MIRROR_OUT" \
    "Candidate promotion:PROMOTE_OUT" \
    "Planner queue:QUEUE_OUT" \
    "Arc cards:ARCS_OUT" \
    "Focus autopilot:FOCUS_AUTOPILOT_OUT" \
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
SUMMARY=$(printf '%s' "$DOCTOR_OUT" | python3 "$SCRIPT_DIR/lifehug.py" weekly-summary \
  --since "$START_TS" --report-path "$REPORT_FILE" --doctor-file - 2>&1) \
  || SUMMARY="⚠ weekly summary generation failed — see $REPORT_FILE"

telegram_notify "${SUMMARY}

${SECOND_VOICE_OUT}

📸 This week, while it's fresh: ${PRESENT_PROMPT}
(Reply and it saves as a story)"
