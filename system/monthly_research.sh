#!/usr/bin/env bash
# Lifehug Monthly Research
# Opens new question neighborhoods and Focus recommendations at a slow cadence.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-${LIFEHUG_VAULT_ROOT:-$(dirname "$SCRIPT_DIR")}}"
WORKSPACE="$(python3 "$SCRIPT_DIR/vault_paths.py" root --vault-root "$WORKSPACE")" || exit 1
export LIFEHUG_VAULT_ROOT="$WORKSPACE"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_MONTHLY_DRY_RUN:-0}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if ! python3 "$SCRIPT_DIR/jobs.py" active --vault-root "$WORKSPACE" >/dev/null 2>&1 \
    && [[ "$DRY_RUN" != "1" ]]; then
  JOB_IDENTITY="${LIFEHUG_JOB_IDENTITY:-monthly:$(date +%Y-%m)}"
  exec python3 "$SCRIPT_DIR/jobs.py" enqueue monthly --identity "$JOB_IDENTITY" \
    --wait --vault-root "$WORKSPACE"
fi

# v86 (issue #35): Telegram gets a short summary; the full output is
# persisted as a committed report document.
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REPORT_DIR="$(python3 "$SCRIPT_DIR/vault_paths.py" data-path reports --vault-root "$WORKSPACE")"
REPORT_FILE="$REPORT_DIR/monthly-$(date +%F).md"
QUESTION_QUEUE_PATH="$WORKSPACE/$(python3 "$SCRIPT_DIR/vault_paths.py" data-path question_queue --vault-root "$WORKSPACE")"
AGENT_TASKS_DIR="$(python3 "$SCRIPT_DIR/vault_paths.py" data-path agent_tasks --vault-root "$WORKSPACE")"
export QUESTION_QUEUE_PATH

# --- Telegram notification helper ---
# Delegates to `lifehug.py notify` (resolves chat/token, chunks under the
# 4096-char cap). Never fails the flow.
telegram_notify() {
  printf '%s' "$1" | python3 "$SCRIPT_DIR/lifehug.py" notify || true
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
GAP_LIMIT="${LIFEHUG_MONTHLY_GAP_LIMIT:-2}"
SELF_TOPIC="${LIFEHUG_MONTHLY_SELF_TOPIC:-Who I am becoming}"
SELF_OUTPUT="${LIFEHUG_MONTHLY_SELF_OUTPUT:-essay}"
FOCUS_MIN_SCORE="${LIFEHUG_MONTHLY_FOCUS_MIN_SCORE:-15}"
# Conversation-thread offers (issue #118): at most this many ignorable lines a
# month, and an offered neighborhood stays quiet for a quarter afterwards.
THREAD_OFFERS="${LIFEHUG_MONTHLY_THREAD_OFFERS:-1}"
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
import os
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
limit = int(sys.argv[2])

import research_expand as research  # noqa: E402

# The planner computes expansion urgency "for the cron to act on" — this is
# the cron acting on it. Low urgency (Focuses still have room) → no new
# neighborhoods this month; the archive deepens instead of widening.
try:
    queue = json.loads(Path(os.environ["QUESTION_QUEUE_PATH"]).read_text(encoding="utf-8"))
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
  if [[ "${KEYLESS:-0}" == "1" ]]; then
    # v92 keyless agent mode: emit the expansion prompt as an agent task
    # instead of failing the AI call. Completed via research_expand
    # --from-response (see skills/maintenance).
    local slug
    slug=$(printf '%s' "$topic" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-')
    mkdir -p "$AGENT_TASKS_DIR/research"
    if python3 "$SCRIPT_DIR/research_expand.py" --topic "$topic" --type "$topic_type" --output "$output" --prompt \
        > "$AGENT_TASKS_DIR/research/${slug}.prompt.md" 2>&1; then
      echo "⏸ keyless — expansion prompt for '${topic}' emitted to $AGENT_TASKS_DIR/research/${slug}.prompt.md"
      echo "  complete: python3 system/research_expand.py --topic \"$topic\" --type $topic_type --output $output --from-response <response-file>"
    else
      echo "skip: could not emit prompt for ${topic} (see $AGENT_TASKS_DIR/research/${slug}.prompt.md)"
    fi
    return 0
  fi
  run_optional python3 "$SCRIPT_DIR/research_expand.py" --topic "$topic" --type "$topic_type" --output "$output"
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: monthly research"
  run_step python3 "$SCRIPT_DIR/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$SCRIPT_DIR/research_expand.py" --gaps --dry-run
  select_gap_targets > "$TARGETS_FILE"
  if [[ ! -s "$TARGETS_FILE" ]]; then
    echo
    echo "No new gap neighborhoods selected."
  fi
  while IFS=$'\t' read -r topic topic_type output; do
    [[ -z "${topic:-}" ]] && continue
    run_step python3 "$SCRIPT_DIR/research_expand.py" --topic "$topic" --type "$topic_type" --output "$output" --dry-run
  done < "$TARGETS_FILE"
  if neighborhood_exists "$SELF_TOPIC"; then
    echo "skip: neighborhood already exists for ${SELF_TOPIC}"
  else
    run_step python3 "$SCRIPT_DIR/research_expand.py" --topic "$SELF_TOPIC" --type self --output "$SELF_OUTPUT" --dry-run
  fi
  echo
  echo "==> preview conversation-thread offers"
  run_step python3 "$SCRIPT_DIR/lifehug.py" arc-thread-offers --limit "$THREAD_OFFERS" --dry-run
  echo
  echo "==> preview Focus recommendations"
  preview_focuses
  echo
  echo "==> preview entity roster refreshes"
  for etype in person place period object theme; do
    run_step python3 "$SCRIPT_DIR/lifehug.py" entity-roster --type "$etype" --emit-task "$ROSTER_PREVIEW_DIR/${etype}.json"
  done
  run_step python3 "$SCRIPT_DIR/lifehug.py" compile --dry-run --no-ai
  run_step python3 "$SCRIPT_DIR/lifehug.py" progress
  exit 0
fi

# v92: keyless agent mode — AI steps emit agent tasks to state/agent_tasks/
# instead of recording raw learning failures (see skills/maintenance).
# Keyless compile is already non-destructive (synthesis is skipped, never
# regressed), so the compile steps run unguarded.
python3 "$SCRIPT_DIR/lifehug.py" ai-status >/dev/null 2>&1 && KEYLESS=0 || KEYLESS=1
if [[ "$KEYLESS" == "1" ]]; then
  echo "keyless — AI steps will emit agent tasks (complete via skills/maintenance)"
fi

run_step python3 "$SCRIPT_DIR/lifehug.py" compile
RESEARCH_OUT=""
GAPS_OUT=$(python3 "$SCRIPT_DIR/research_expand.py" --gaps 2>&1)
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
FOCUSES_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" recommend-focuses --min-score "$FOCUS_MIN_SCORE" 2>&1) || true
echo "$FOCUSES_OUT"
# Refresh the canonical entity rosters (AI-curated) for every entity type, then
# recompile so newly-eligible entities graduate into pages and Focus pages pick up
# fresh mentions. The whole life graph — people, places, periods, symbolic objects
# — grows without any human interaction.
ROSTER_OUT=""
for etype in person place period object theme; do
  if [[ "$KEYLESS" == "1" ]]; then
    # Keyless: emit the resolution task for agent completion. NEVER fall back
    # to the deterministic roster — it stateless-refreshes junk (v90 lesson).
    mkdir -p "$AGENT_TASKS_DIR/roster"
    set +e
    ETYPE_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" entity-roster --type "$etype" --emit-task "$AGENT_TASKS_DIR/roster/${etype}.json" 2>&1)
    ETYPE_STATUS=$?
    set -e
    if [[ "$ETYPE_STATUS" -ne 0 ]]; then
      record_learning_failure "monthly_research" "entity_roster_${etype}_emit" "$ETYPE_STATUS" "$ETYPE_OUT"
      ETYPE_OUT="⚠ ${etype} roster task emission FAILED (exit ${ETYPE_STATUS})
${ETYPE_OUT}"
    else
      ETYPE_OUT="⏸ keyless — ${etype} roster task emitted, not a failure. Complete via entity-roster --type ${etype} --from-response.
${ETYPE_OUT}"
    fi
  else
    set +e
    ETYPE_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" entity-roster --type "$etype" 2>&1)
    ETYPE_STATUS=$?
    set -e
    if [[ "$ETYPE_STATUS" -ne 0 ]]; then
      record_learning_failure "monthly_research" "entity_roster_${etype}" "$ETYPE_STATUS" "$ETYPE_OUT"
      ETYPE_OUT="⚠ ${etype} roster refresh FAILED (exit ${ETYPE_STATUS})
${ETYPE_OUT}"
    fi
  fi
  ROSTER_OUT="${ROSTER_OUT}${ETYPE_OUT}
"
done
echo "$ROSTER_OUT"
run_step python3 "$SCRIPT_DIR/lifehug.py" compile

# Perennial re-asks (v71): questions marked perennial that were last answered
# ~a year ago get re-inserted WITH last year's answer attached (10Q model).
run_optional python3 "$SCRIPT_DIR/lifehug.py" perennials --generate-due

# Conversation-thread offers (issue #118): research neighborhoods that already
# have record to open from AND somewhere left to go become multi-session
# conversation threads. Deterministic (no AI), capped, and never repeated
# within a quarter — empty most months by design.
set +e
THREAD_OFFERS_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" arc-thread-offers --limit "$THREAD_OFFERS" 2>&1)
THREAD_OFFERS_STATUS=$?
set -e
if [[ "$THREAD_OFFERS_STATUS" -ne 0 ]]; then
  record_learning_failure "monthly_research" "arc_thread_offers" "$THREAD_OFFERS_STATUS" "$THREAD_OFFERS_OUT"
  THREAD_OFFERS_OUT="⚠ conversation-thread offers FAILED (exit ${THREAD_OFFERS_STATUS})
${THREAD_OFFERS_OUT}"
fi
echo "$THREAD_OFFERS_OUT"

# Echo-style resurfacing (v71): send one old answer back verbatim with a
# reflection question — reviewing past entries is itself the intervention
# (CHI 2013). Deterministic per month; replies become reflection sources.
RESURFACE_OUT=$(python3 - <<'PY' 2>&1 || true
import re
from pathlib import Path

from datetime import datetime, timezone

from lifehug_core import ANSWERS_DIR, send_telegram

files = sorted(ANSWERS_DIR.glob("*.md"))
now = datetime.now(timezone.utc)
old_enough = []
for f in files:
    text = f.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^answered_date:\s*"?([0-9-]{10})', text, re.MULTILINE)
    if not m:
        continue
    try:
        answered = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        continue
    if (now - answered).days >= 90:
        old_enough.append((f, m.group(1), text))
if not old_enough:
    print("Resurfacing: no answers ≥90 days old yet.")
    raise SystemExit(0)
pick = old_enough[(now.year * 12 + now.month) % len(old_enough)]
f, answered_date, text = pick
parts = text.split("---")
body = parts[-1] if len(parts) >= 3 else text
body = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)
body = " ".join(body.split())[:900]
message = (f"🪞 Lifehug — from your own archive\n\n"
           f"On {answered_date} you wrote ({f.stem}):\n\n“{body}”\n\n"
           f"Reading it now — what do you see that you couldn't see then? "
           f"(Reply and we'll talk it through — it saves as a reflection on {f.stem})")
if send_telegram(message):
    print(f"✓ Resurfaced {f.stem} ({answered_date}) with a reflection question")
else:
    print("Resurfacing: telegram unavailable; skipped")
PY
)
echo "$RESURFACE_OUT"

PROGRESS_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" progress 2>&1)
echo "$PROGRESS_OUT"

# Persist the full raw report (the old wall-of-text) as a document.
mkdir -p "$REPORT_DIR"
{
  echo "# Lifehug Monthly Research Report — $(date '+%Y-%m-%d %H:%M')"
  for section in \
    "Research neighborhoods:RESEARCH_OUT" \
    "Focus recommendations:FOCUSES_OUT" \
    "Entity rosters:ROSTER_OUT" \
    "Conversation threads:THREAD_OFFERS_OUT" \
    "Resurfacing:RESURFACE_OUT" \
    "Progress:PROGRESS_OUT"; do
    title="${section%%:*}"; var="${section##*:}"
    echo; echo "## ${title}"; echo; echo '```'
    printf '%s\n' "${!var:-—}"
    echo '```'
  done
} > "$REPORT_FILE"
echo "✓ Full report written to $REPORT_FILE"

safe_autocommit

# v86 (issue #35): counts-first summary derived from state.
SUMMARY=$(python3 "$SCRIPT_DIR/lifehug.py" weekly-summary \
  --kind monthly --since "$START_TS" --report-path "$REPORT_FILE" 2>&1) \
  || SUMMARY="⚠ monthly summary generation failed — see $REPORT_FILE"

# The month's conversation-thread offer (issue #118) rides along with the
# summary: one ignorable line, in the register of an invitation.
THREAD_OFFER_LINES=$(printf '%s\n' "$THREAD_OFFERS_OUT" | grep '^💬' || true)
if [[ -n "$THREAD_OFFER_LINES" ]]; then
  telegram_notify "${SUMMARY}

${THREAD_OFFER_LINES}"
else
  telegram_notify "${SUMMARY}"
fi
