#!/usr/bin/env bash
# Lifehug Daily Question
# Picks today's question, sends it, then marks it delivered only after success.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-${LIFEHUG_VAULT_ROOT:-$(dirname "$SCRIPT_DIR")}}"
WORKSPACE="$(python3 "$SCRIPT_DIR/vault_paths.py" root --vault-root "$WORKSPACE")" || exit 1
export LIFEHUG_VAULT_ROOT="$WORKSPACE"
cd "$WORKSPACE"
DRY_RUN="${LIFEHUG_DAILY_DRY_RUN:-0}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Every real scheduled mutation enters the durable local queue.  The worker
# re-enters this canonical script with a live lease-bound token while holding
# the one vault writer lock. An explicit identity override is the
# owner escape hatch after an ambiguous failed daily send; normal launchd
# retries deduplicate by local date and cannot double-send blindly.
if ! python3 "$SCRIPT_DIR/jobs.py" active --vault-root "$WORKSPACE" >/dev/null 2>&1 \
    && [[ "$DRY_RUN" != "1" ]]; then
  JOB_IDENTITY="${LIFEHUG_JOB_IDENTITY:-daily:$(date +%F)}"
  exec python3 "$SCRIPT_DIR/jobs.py" enqueue daily --identity "$JOB_IDENTITY" \
    --wait --vault-root "$WORKSPACE"
fi

read_config_value() {
  local key="$1"
  python3 - "$key" <<'PY'
import re
import sys
key = sys.argv[1]
try:
    config = open("config.yaml", encoding="utf-8").read()
except FileNotFoundError:
    print("")
    raise SystemExit
m = re.search(rf"^{re.escape(key)}:\s*[\"']*([^\s\"'#]+)[\"']*", config, re.MULTILINE)
print(m.group(1) if m else "")
PY
}

CHAT_ID="${TELEGRAM_CHAT_ID:-$(read_config_value telegram_chat_id)}"
if [[ -z "$CHAT_ID" ]]; then
  CHAT_ID="$(read_config_value group_chat_id)"
fi

TOKEN="${TELEGRAM_BOT_TOKEN:-$(python3 - <<'PY'
import json
import os
try:
    path = os.path.expanduser("~/.openclaw/openclaw.json")
    c = json.load(open(path, encoding="utf-8"))
    print(c["channels"]["telegram"]["botToken"])
except Exception:
    print("")
PY
)}"

if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID/group_chat_id must be set" >&2
  exit 1
fi

# The [QID] marker is what daily_question.sh keys the delivered message on
# (and the answer-filing flow after it), so the parse has ONE definition used
# by both the dry run and the real send.
parse_question_id() {
  python3 -c '
import re
import sys
text = sys.stdin.read()
m = re.search(r"\[([A-Z]\d+[a-z]*)\]", text)
print(m.group(1) if m else "")
'
}

# Arc-card attach (issue #118) — a PURE FILE READ, no AI on the daily path.
# Prints the assembled message for a live card (unexpired and still in the
# current queue) or nothing at all; the caller branches on empty-vs-nonempty,
# which is the whole of the stale-plan fallback.
arc_card_text() {
  python3 "$SCRIPT_DIR/lifehug.py" arc-card "$1" --daily-text 2>/dev/null || true
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: would use configured Telegram delivery target"
  # Day-rollover preview (design §D): one deterministic line, no mutation —
  # mirrors the real pre-question step below (same --day-rollover flag),
  # added with --dry-run so this preview stays a pure read.
  python3 "$SCRIPT_DIR/lifehug.py" conversation-close --day-rollover --dry-run
  DRY_OUTPUT=$(python3 "$SCRIPT_DIR/ask.py" --dry-run)
  printf '%s\n' "$DRY_OUTPUT"
  DRY_QID=$(printf '%s\n' "$DRY_OUTPUT" | parse_question_id)
  if [[ -n "$DRY_QID" ]]; then
    DRY_ARC=$(arc_card_text "$DRY_QID")
    echo
    if [[ -n "$DRY_ARC" ]]; then
      echo "==> arc card attach for ${DRY_QID} (would send):"
      printf '%s\n' "$DRY_ARC"
    else
      echo "==> no live arc card for ${DRY_QID} — today's message format unchanged"
    fi
  fi
  exit 0
fi

# Read fresh at decision time — discipline 1 of the shared-vault contract.
# One vault can be driven by several operators at once (this Mac, a dev box, a
# hosted environment), and the question we are about to pick is only as good as
# the rotation/bank state we read. So pull BEFORE picking, not just after
# delivering. Non-fatal by the same logic as safe_autocommit: if the pull fails
# we ask from local state, which is exactly the behavior that shipped before
# this discipline existed — a stale question is a real question, and no git
# problem may cost the author their daily question. Skipped when there is no
# remote at all (a local-only install must not log a failure every morning).
safe_pull() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  [[ -n "$(git remote 2>/dev/null)" ]] || return 0
  set +e
  local git_out
  git_out=$(git pull --rebase --autostash 2>&1)
  local git_status=$?
  set -e
  if [[ "$git_status" -ne 0 ]]; then
    echo "warn: pull before pick failed (asking from local state)" >&2
    echo "$git_out" >&2
    record_learning_failure "daily_question" "git_pull_before_pick" "$git_status" "$git_out"
  fi
  return 0
}

# Git housekeeping is deliberately NON-FATAL and runs AFTER delivery: a
# rejected push must never cost the author their daily question. Pull-rebase
# first — a second machine (dev box) writes to the same repo.
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
      { git commit -m "Daily update $(date +%Y-%m-%d)" &&
        git pull --rebase --autostash &&
        git push; }; } 2>&1
  )
  local git_status=$?
  set -e
  if [[ "$git_status" -ne 0 ]]; then
    echo "warn: git housekeeping failed (question already delivered)" >&2
    echo "$git_out" >&2
    record_learning_failure "daily_question" "git_autocommit" "$git_status" "$git_out"
  fi
  return 0
}

send_message() {
  local text="$1"
  curl -fsS -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${text}"
}

pin_message() {
  local message_id="$1"
  curl -fsS -X POST "https://api.telegram.org/bot${TOKEN}/pinChatMessage" \
    -d "chat_id=${CHAT_ID}&message_id=${message_id}&disable_notification=true" >/dev/null || true
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

extract_message_id() {
  python3 -c '
import json
import sys
payload = json.load(sys.stdin)
if not payload.get("ok"):
    raise SystemExit(f"telegram send failed: {payload}")
print(payload["result"]["message_id"])
'
}

# Converge with the other operators before anything reads state: the compile
# below and every pick that follows it must see what the rest of the world
# already answered.
safe_pull

# Keep the wiki (the relational database the rest of the system reads) fresh
# before delivering. Cheap and deterministic; failures never block the question.
set +e
COMPILE_OUT=$(python3 "$SCRIPT_DIR/wiki_compile.py" 2>&1)
COMPILE_STATUS=$?
set -e
if [[ "$COMPILE_STATUS" -ne 0 ]]; then
  record_learning_failure "daily_question" "wiki_compile" "$COMPILE_STATUS" "$COMPILE_OUT"
fi

# Day-rollover pre-step (design §D, Chats-per-Focus, 2026-08-12): close
# EVERY open conversation session — no idle filter, the day owns the
# surface, not a timer — before minting today's question. Runs BEFORE the
# pass-transition check and ask.py's pick so no session survives into a new
# day's context. THE PLATFORM'S TRANSPORT SPEC: mirror this invocation
# verbatim (same flag, same placement — after compile, before pick) in
# workflow.py's delivery flow. Non-fatal, same idiom as the compile step
# above: a rollover failure must never cost the author their daily question.
set +e
ROLLOVER_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" conversation-close --day-rollover 2>&1)
ROLLOVER_STATUS=$?
set -e
if [[ "$ROLLOVER_STATUS" -ne 0 ]]; then
  echo "warn: day-rollover close failed (continuing)" >&2
  echo "$ROLLOVER_OUT" >&2
  record_learning_failure "daily_question" "day_rollover_close" "$ROLLOVER_STATUS" "$ROLLOVER_OUT"
else
  echo "$ROLLOVER_OUT"
fi

AWAITING=$(python3 - <<'PY'
from lifehug_core import ROTATION_FILE, read_json
r = read_json(ROTATION_FILE, default={}) or {}
print("true" if r.get("awaiting_pass_transition") else "false")
PY
)

if [[ "$AWAITING" == "true" ]]; then
  DEFAULT_MODEL="$(read_config_value followup_model)"
  [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="anthropic/claude-opus-4-6"
  TARGET_PASS=$(python3 - <<'PY'
from lifehug_core import ROTATION_FILE, read_json
r = read_json(ROTATION_FILE, default={}) or {}
print(r.get("target_pass") or r.get("current_pass", 1) + 1)
PY
)
  TEXT="📖 Lifehug — ready for Pass ${TARGET_PASS}

You've finished the current pass. Reply with a model name to generate the next set of deeper questions, or say **go** to use:

\`${DEFAULT_MODEL}\`"
  send_message "$TEXT" >/dev/null
  echo "✓ Pass transition reminder sent"
  safe_autocommit
  exit 0
fi

QUESTION_OUTPUT=$(python3 "$SCRIPT_DIR/ask.py" --dry-run)

if [[ "$QUESTION_OUTPUT" == Pass\ *complete.* ]]; then
  TRANSITION_OUTPUT=$(python3 "$SCRIPT_DIR/ask.py" --mark-pass-complete)
  PASS_NUM=$(echo "$TRANSITION_OUTPUT" | cut -d: -f2)
  DEFAULT_MODEL=$(echo "$TRANSITION_OUTPUT" | cut -d: -f3-)
  TEXT="📖 Lifehug — Pass ${PASS_NUM} complete

You've answered every question in this pass. Time to generate the next, deeper set of questions.

Default model: \`${DEFAULT_MODEL}\`

Reply with a model name to use a different one, or just say **go** to use the default."
  send_message "$TEXT" >/dev/null
  echo "✓ Pass ${PASS_NUM} transition prompt sent"
  safe_autocommit
  exit 0
fi

QUESTION_ID=$(printf '%s\n' "$QUESTION_OUTPUT" | parse_question_id)

if [[ -z "$QUESTION_ID" ]]; then
  echo "ERROR: Could not parse question ID from ask.py output" >&2
  echo "$QUESTION_OUTPUT" >&2
  exit 1
fi

# The day's pre-planned arc card, when one is live. The card's own text
# carries the same [QID] marker format_question produces, so the message the
# author sees — and every downstream parse of it — is unchanged in shape.
# Reengagement picks and expired queues simply have no card: empty output,
# today's format, no branch anywhere else in this script.
ARC_TEXT=$(arc_card_text "$QUESTION_ID")
if [[ -n "$ARC_TEXT" ]]; then
  QUESTION_BODY="$ARC_TEXT"
else
  QUESTION_BODY="$QUESTION_OUTPUT"
fi

TEXT="📖 Lifehug — Daily Question

${QUESTION_BODY}

(Answer whenever you want — voice or text)"

RESPONSE=$(send_message "$TEXT")
MESSAGE_ID=$(printf '%s' "$RESPONSE" | extract_message_id)
python3 "$SCRIPT_DIR/ask.py" --confirm-sent "$QUESTION_ID" >/dev/null
pin_message "$MESSAGE_ID"

echo "✓ Lifehug question sent and pinned (question: $QUESTION_ID, msg_id: $MESSAGE_ID)"

# Housekeeping AFTER delivery — a git failure can no longer eat the question.
safe_autocommit
