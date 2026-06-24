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

safe_autocommit() {
  local paths=(
    README.md
    system/question-bank.md
    system/rotation.json
    system/coverage.json
    answers
    outputs
    sources/manual
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
    git commit -m "Daily update $(date +%Y-%m-%d)"
    git push
  fi
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
python3 "$WORKSPACE/system/wiki_compile.py" >/dev/null 2>&1 || true

safe_autocommit

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
