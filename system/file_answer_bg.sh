#!/usr/bin/env bash
# file_answer_bg.sh — Detached wrapper for process-answer.
#
# Purpose: Lily's chat should NOT block waiting on wiki compile (which calls
# an LLM per synthesis and routinely exceeds chat idle timeout). Instead:
#   1. Chat spawns this script with nohup + &
#   2. Chat sends an immediate "🎙️ Filing…" ack and exits the turn
#   3. This script runs process-answer to completion
#   4. On finish, this script sends its OWN Telegram message with the result
#
# Usage (from a chat turn):
#   echo "answer body" | nohup bash system/file_answer_bg.sh <QID> [flags...] \
#     >/tmp/lifehug-file-<QID>.log 2>&1 &
#
# Flags after QID are passed through to `lifehug.py process-answer`
# (e.g. --source telegram-voice --sensitivity family --followup name --force).
#
# The answer body is read from stdin — DO NOT close stdin before nohup dispatch.

set -u

QID="${1:-}"
if [[ -z "$QID" ]]; then
  echo "usage: file_answer_bg.sh <question_id> [--flag ...]" >&2
  exit 2
fi
shift

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Chat destination: env override wins, otherwise read from profile.yaml/config.yaml.
# Instance-specific (each Lifehug user has their own telegram_chat_id).
read_chat_id() {
  REPO="$REPO" python3 - <<'PY' 2>/dev/null || true
import os, pathlib
try:
    import yaml
except ImportError:
    yaml = None
repo = pathlib.Path(os.environ["REPO"])
cfg = {}
if yaml is not None:
    for name in ("profile.yaml", "config.yaml"):
        p = repo / name
        if p.exists():
            data = yaml.safe_load(open(p)) or {}
            cfg.update(data)
print(cfg.get("telegram_chat_id", ""))
PY
}
CHAT_ID="${LIFEHUG_CHAT_ID:-}"
if [[ -z "$CHAT_ID" ]]; then
  CHAT_ID=$(read_chat_id)
fi

# Capture stdin body to a temp file so we can retry or debug
BODY=$(mktemp -t lifehug-answer-XXXXXX)
trap 'rm -f "$BODY"' EXIT
cat > "$BODY"

# Load bot token from OpenClaw config
BOT_TOKEN=$(python3 -c "import json,os; c=json.load(open(os.path.expanduser('~/.openclaw/openclaw.json'))); print(c['channels']['telegram']['botToken'])" 2>/dev/null || true)

send_msg() {
  local text="$1"
  if [[ -z "$BOT_TOKEN" ]]; then return 0; fi
  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${text}" \
    >/dev/null 2>&1 || true
}

cd "$REPO"

# Run the actual filing
OUT=$(cat "$BODY" | python3 system/lifehug.py process-answer "$QID" "$@" 2>&1)
RC=$?

if [[ $RC -eq 0 ]]; then
  # Extract coverage line if present
  COVERAGE=$(echo "$OUT" | grep -oE "Coverage: [0-9]+/[0-9]+" | tail -1 || true)
  FOLLOWUPS=$(echo "$OUT" | grep -oE "Adaptive follow-up question sent: [A-Z][0-9]+[a-z]?" | head -1 || true)
  MSG="✅ Filed ${QID}"
  [[ -n "$COVERAGE" ]] && MSG="${MSG} · ${COVERAGE}"
  [[ -n "$FOLLOWUPS" ]] && MSG="${MSG}"$'\n'"↳ ${FOLLOWUPS}"
  send_msg "$MSG"
else
  # Truncate error to fit
  ERR=$(echo "$OUT" | tail -20)
  send_msg "⚠️ Filing ${QID} failed (rc=${RC})"$'\n\n'"${ERR}"
fi

exit $RC
