#!/usr/bin/env bash
# compile_and_commit.sh — Periodic wiki compile + git commit.
#
# Runs via launchd (com.lifehug.compile.plist) every hour.
# Only does work if state/.compile-needed exists (touched by file_answer_bg.sh
# after each successful answer filing).
#
# This decouples wiki compile from answer filing so Dave can rapid-fire
# multiple answers without compile conflicts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

SENTINEL="state/.compile-needed"

# Nothing to do?
if [[ ! -f "$SENTINEL" ]]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') nothing to compile"
  exit 0
fi

if ! python3 "$SCRIPT_DIR/jobs.py" active --vault-root "$WORKSPACE" >/dev/null 2>&1; then
  JOB_IDENTITY="${LIFEHUG_JOB_IDENTITY:-compile-pending:$(date +%Y-%m-%dT%H)}"
  exec python3 "$SCRIPT_DIR/jobs.py" enqueue compile-pending --identity "$JOB_IDENTITY" \
    --wait --vault-root "$WORKSPACE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') compile needed — worker owns vault writer lease"

# Record failure for the learning loop (same pattern as daily_question.sh)
record_learning_failure() {
  python3 - "$@" <<'PY'
import json, sys, datetime
scope, action, status, detail = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else ""
entry = {"ts": datetime.datetime.now().isoformat(), "scope": scope, "action": action,
         "status": status, "detail": detail[:500]}
with open("state/learning_failures.jsonl", "a") as f:
    f.write(json.dumps(entry) + "\n")
PY
}

# Compile
set +e
COMPILE_OUT=$(python3 "$SCRIPT_DIR/lifehug.py" compile 2>&1)
COMPILE_RC=$?
set -e

if [[ $COMPILE_RC -ne 0 ]]; then
  echo "error: compile failed (rc=$COMPILE_RC)" >&2
  echo "$COMPILE_OUT" >&2
  record_learning_failure "compile_cron" "wiki_compile" "$COMPILE_RC" "$COMPILE_OUT"
  # Don't remove sentinel — retry next hour
  exit 1
fi

echo "$COMPILE_OUT"

# Remove sentinel — compile succeeded
rm -f "$SENTINEL"

# Git: add, commit, pull-rebase, push (non-fatal)
PATHS=(
  README.md
  question-bank.md
  state/rotation.json
  state/coverage.json
  system/question-bank.md
  system/rotation.json
  system/coverage.json
  answers
  outputs
  sources
  state
  wiki
)
EXISTING=()
for path in "${PATHS[@]}"; do
  [[ -e "$path" ]] && EXISTING+=("$path")
done

if [[ ${#EXISTING[@]} -gt 0 ]]; then
  set +e
  GIT_OUT=$(
    git add -- "${EXISTING[@]}" &&
    { git diff --cached --quiet ||
      { git commit -m "Wiki compile $(date +%Y-%m-%d\ %H:%M)" &&
        git pull --rebase --autostash &&
        git push; }; } 2>&1
  )
  GIT_RC=$?
  set -e
  if [[ $GIT_RC -ne 0 ]]; then
    echo "warn: git housekeeping failed (wiki still compiled)" >&2
    echo "$GIT_OUT" >&2
    record_learning_failure "compile_cron" "git_autocommit" "$GIT_RC" "$GIT_OUT"
  fi
fi

# Notify
printf '✅ Wiki compiled' | python3 "$SCRIPT_DIR/lifehug.py" notify || true

echo "$(date '+%Y-%m-%d %H:%M:%S') done"
