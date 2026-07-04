#!/usr/bin/env bash
# Lifehug Daily Question
# Picks today's question, sends it, then marks it delivered only after success.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"
DRY_RUN="${LIFEHUG_DAILY_DRY_RUN:-0}"

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

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: would use configured Telegram delivery target"
  python3 "$WORKSPACE/system/ask.py" --dry-run
  exit 0
fi

# Git housekeeping is deliberately NON-FATAL and runs AFTER delivery: a
# rejected push must never cost the author their daily question. Pull-rebase
# first — a second machine (dev box) writes to the same repo.
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

# Keep the wiki (the relational database the rest of the system reads) fresh
# before delivering. Cheap and deterministic; failures never block the question.
set +e
COMPILE_OUT=$(python3 "$WORKSPACE/system/wiki_compile.py" 2>&1)
COMPILE_STATUS=$?
set -e
if [[ "$COMPILE_STATUS" -ne 0 ]]; then
  record_learning_failure "daily_question" "wiki_compile" "$COMPILE_STATUS" "$COMPILE_OUT"
fi

AWAITING=$(python3 - <<'PY'
import json
r = json.load(open("system/rotation.json", encoding="utf-8"))
print("true" if r.get("awaiting_pass_transition") else "false")
PY
)

if [[ "$AWAITING" == "true" ]]; then
  DEFAULT_MODEL="$(read_config_value followup_model)"
  [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="anthropic/claude-opus-4-6"
  TARGET_PASS=$(python3 - <<'PY'
import json
r = json.load(open("system/rotation.json", encoding="utf-8"))
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

QUESTION_OUTPUT=$(python3 "$WORKSPACE/system/ask.py" --dry-run)

if [[ "$QUESTION_OUTPUT" == Pass\ *complete.* ]]; then
  TRANSITION_OUTPUT=$(python3 "$WORKSPACE/system/ask.py" --mark-pass-complete)
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

QUESTION_ID=$(printf '%s\n' "$QUESTION_OUTPUT" | python3 -c '
import re
import sys
text = sys.stdin.read()
m = re.search(r"\[([A-Z]\d+[a-z]*)\]", text)
print(m.group(1) if m else "")
'
)

if [[ -z "$QUESTION_ID" ]]; then
  echo "ERROR: Could not parse question ID from ask.py output" >&2
  echo "$QUESTION_OUTPUT" >&2
  exit 1
fi

TEXT="📖 Lifehug — Daily Question

${QUESTION_OUTPUT}

(Answer whenever you want — voice or text)"

RESPONSE=$(send_message "$TEXT")
MESSAGE_ID=$(printf '%s' "$RESPONSE" | extract_message_id)
python3 "$WORKSPACE/system/ask.py" --confirm-sent "$QUESTION_ID" >/dev/null
pin_message "$MESSAGE_ID"

echo "✓ Lifehug question sent and pinned (question: $QUESTION_ID, msg_id: $MESSAGE_ID)"

# Housekeeping AFTER delivery — a git failure can no longer eat the question.
safe_autocommit
