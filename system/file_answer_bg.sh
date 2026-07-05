#!/usr/bin/env bash
# file_answer_bg.sh — Detached wrapper for process-answer.
#
# Purpose: chat should NOT block waiting on wiki compile (which calls
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
#
# Confirmation destination: `lifehug.py notify` resolves the target
# (TELEGRAM_CHAT_ID env → telegram_chat_id → group_chat_id; token from
# TELEGRAM_BOT_TOKEN env → ~/.openclaw/openclaw.json), chunked under the
# 4096-char Telegram limit. Notification failure never fails the filing.

set -u

QID="${1:-}"
if [[ -z "$QID" ]]; then
  echo "usage: file_answer_bg.sh <question_id> [--flag ...]" >&2
  exit 2
fi
shift

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Back-compat: v82 callers pass LIFEHUG_CHAT_ID; the framework's own
# override is TELEGRAM_CHAT_ID (lifehug_core.resolve_telegram_target).
if [[ -n "${LIFEHUG_CHAT_ID:-}" && -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  export TELEGRAM_CHAT_ID="$LIFEHUG_CHAT_ID"
fi

send_msg() {
  printf '%s' "$1" | python3 system/lifehug.py notify || true
}

# Capture stdin body to a temp file so we can retry or debug
BODY=$(mktemp -t lifehug-answer-XXXXXX)
LOCK="$REPO/state/.filing.lock"
HAVE_LOCK=0
trap '[[ $HAVE_LOCK -eq 1 ]] && rmdir "$LOCK" 2>/dev/null; rm -f "$BODY"' EXIT
cat > "$BODY"

cd "$REPO"

# Serialize concurrent filings: process-answer mutates shared state
# (rotation.json, coverage, manifest, git), so two detached filers must not
# interleave. Portable mkdir lock (macOS has no flock binary); a lock older
# than 15 min is stolen so a killed filer can't wedge future filings; after
# ~4 min of waiting we proceed anyway — a rare race beats a dropped answer.
LOCK_NOTE=""
for _ in $(seq 1 120); do
  if mkdir "$LOCK" 2>/dev/null; then
    HAVE_LOCK=1
    break
  fi
  if [[ -n "$(find "$LOCK" -maxdepth 0 -mmin +15 2>/dev/null)" ]]; then
    rmdir "$LOCK" 2>/dev/null || true
    continue
  fi
  sleep 2
done
if [[ $HAVE_LOCK -eq 0 ]]; then
  LOCK_NOTE=$'\n'"(note: filed without the lock — another filing ran long)"
fi

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
  send_msg "${MSG}${LOCK_NOTE}"
else
  ERR=$(echo "$OUT" | tail -20)
  send_msg "⚠️ Filing ${QID} failed (rc=${RC})${LOCK_NOTE}"$'\n\n'"${ERR}"
fi

exit $RC
