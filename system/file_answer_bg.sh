#!/usr/bin/env bash
# file_answer_bg.sh — Detached wrapper for process-answer.
#
# Purpose: file an answer FAST without blocking on wiki compile.
#   1. Chat spawns this script with nohup + &
#   2. Chat sends an immediate "🎙️ Filing…" ack and exits the turn
#   3. This script runs process-answer with --no-compile-wiki (fast, ~5s)
#   4. process-answer sends the warm acknowledgment, then any follow-up
#   5. On finish, this script sends a factual filing result only when the warm
#      acknowledgment was not confirmed (avoids a duplicate success message)
#   6. Wiki compile runs separately via hourly launchd cron
#
# This decoupling lets Dave rapid-fire 2-3 answers without compile conflicts.
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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-${LIFEHUG_VAULT_ROOT:-$(dirname "$SCRIPT_DIR")}}"
WORKSPACE="$(python3 "$SCRIPT_DIR/vault_paths.py" root --vault-root "$WORKSPACE")" || exit 1
export LIFEHUG_VAULT_ROOT="$WORKSPACE"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Back-compat: v82 callers pass LIFEHUG_CHAT_ID; the framework's own
# override is TELEGRAM_CHAT_ID (lifehug_core.resolve_telegram_target).
if [[ -n "${LIFEHUG_CHAT_ID:-}" && -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  export TELEGRAM_CHAT_ID="$LIFEHUG_CHAT_ID"
fi

send_msg() {
  printf '%s' "$1" | python3 "$SCRIPT_DIR/lifehug.py" notify || true
}


# The outer invocation streams stdin directly into the queue; it never writes a
# plaintext answer to /tmp. Only the lease-bound worker re-entry needs a local
# file because the canonical filing and notification steps both consume it.
if ! python3 "$SCRIPT_DIR/jobs.py" active --vault-root "$WORKSPACE" >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/jobs.py" file-answer --wait --vault-root "$WORKSPACE" \
    "$QID" "$@"
fi

BODY=$(mktemp "${TMPDIR:-/tmp}/lifehug-answer.XXXXXX")
chmod 600 "$BODY"
trap 'rm -f "$BODY"' EXIT
cat > "$BODY"

cd "$WORKSPACE" || exit 1

# Read fresh at decision time — discipline 1 of the shared-vault contract.
# The question id is explicit here, so this pull is not about WHICH question we
# are filing; it is about everything process-answer reads on the way through:
# the bank's answered flags, rotation state, and — through adaptive cadence —
# the pick for the optional same-day follow-up it may send. Filing on top of
# the other operators' work also keeps the hourly compile_and_commit rebase
# trivial. Non-fatal on purpose; if the pull fails we file against local state,
# which is what happened before this discipline existed. The worker lease spans
# this pull and the filing, so no other local surface can mutate the vault in
# between. A git problem never eats an answer. Skipped when there is no remote.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [[ -n "$(git remote 2>/dev/null)" ]]; then
  PULL_OUT=$(git pull --rebase --autostash 2>&1)
  PULL_RC=$?
  if [[ $PULL_RC -ne 0 ]]; then
    echo "warn: pull before filing failed (filing against local state)" >&2
    echo "$PULL_OUT" >&2
    LEARNING_FAILURE_OUTPUT="$PULL_OUT" python3 - "$PULL_RC" <<'PY' || true
import os
import sys

from lifehug_core import record_learning_failure

try:
    code = int(sys.argv[1])
except (IndexError, ValueError):
    code = None
record_learning_failure(
    "file_answer_bg",
    "git_pull_before_filing",
    os.environ.get("LEARNING_FAILURE_OUTPUT", ""),
    exit_code=code,
)
PY
  fi
fi

safe_autocommit() {
  local label="${1:-File answer}"
  local paths=()
  while IFS= read -r path; do
    [[ -n "$path" ]] && paths+=("$path")
  done < <(python3 "$SCRIPT_DIR/vault_paths.py" git-paths --vault-root "$WORKSPACE")
  local existing=()
  for path in "${paths[@]}"; do
    [[ -e "$path" ]] && existing+=("$path")
  done
  [[ ${#existing[@]} -eq 0 ]] && return 0
  local git_out
  git_out=$(
    git add -- "${existing[@]}" &&
    { git diff --cached --quiet ||
      { git commit -m "${label} $(date +%Y-%m-%d)" &&
        git pull --rebase --autostash &&
        git push; }; } 2>&1
  )
  local git_status=$?
  if [[ "$git_status" -ne 0 ]]; then
    echo "warn: git autocommit failed" >&2
    echo "$git_out" >&2
  fi
  return 0
}

# Run the actual filing — skip wiki compile (handled by hourly cron)
OUT=$(python3 "$SCRIPT_DIR/lifehug.py" process-answer "$QID" --no-compile-wiki "$@" < "$BODY" 2>&1)
RC=$?

# Signal that a compile is needed (picked up by hourly cron)
if [[ $RC -eq 0 ]]; then
  COMPILE_NEEDED="$(python3 "$SCRIPT_DIR/vault_paths.py" data-path compile_needed --vault-root "$WORKSPACE")" || exit 1
  touch "$WORKSPACE/$COMPILE_NEEDED"
fi

if [[ $RC -eq 0 ]]; then
  # Extract coverage line if present
  COVERAGE=$(echo "$OUT" | grep -oE "Coverage: [0-9]+/[0-9]+" | tail -1 || true)
  FOLLOWUPS=$(echo "$OUT" | grep -oE "Adaptive follow-up question sent: [A-Z][0-9]+[a-z]?" | head -1 || true)
  # v153+: a confirmed conversation turn replaces the ack — both count as
  # "the user already saw a message about this answer" (issue #133).
  ACK_CONFIRMED=$(echo "$OUT" | grep -oE "Answer acknowledgment: confirmed|Conversation turn: confirmed" | head -1 || true)
  MSG="✅ Filed ${QID}"
  [[ -n "$COVERAGE" ]] && MSG="${MSG} · ${COVERAGE}"
  [[ -n "$FOLLOWUPS" ]] && MSG="${MSG}"$'\n'"↳ ${FOLLOWUPS}"
  safe_autocommit "File ${QID}"
  if [[ -z "$ACK_CONFIRMED" ]]; then
    send_msg "$MSG"
  fi
else
  ERR=$(echo "$OUT" | tail -20)
  send_msg "⚠️ Filing ${QID} failed (rc=${RC})"$'\n\n'"${ERR}"
fi

exit $RC
