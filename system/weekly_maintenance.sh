#!/usr/bin/env bash
# Lifehug Weekly Maintenance
# Runs the low-friction self-improvement loop without changing daily delivery.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"
cd "$WORKSPACE"

DRY_RUN="${LIFEHUG_WEEKLY_DRY_RUN:-0}"
QUEUE_LIMIT="${LIFEHUG_WEEKLY_QUEUE_LIMIT:-14}"
ARC_MAX="${LIFEHUG_WEEKLY_ARC_MAX:-2}"
EXPIRES_DAYS="${LIFEHUG_WEEKLY_EXPIRES_DAYS:-8}"

run_step() {
  echo
  echo "==> $*"
  "$@"
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
  git add -- "${existing[@]}"
  if ! git diff --cached --quiet; then
    git commit -m "Weekly maintenance $(date +%Y-%m-%d)"
    git push
  fi
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
  run_step python3 "$WORKSPACE/system/lifehug.py" quality-stats
  run_step python3 "$WORKSPACE/system/lifehug.py" planner-report --limit 10
  run_step python3 "$WORKSPACE/system/research_expand.py" --gaps --dry-run
  run_step python3 "$WORKSPACE/system/lifehug.py" progress
  exit 0
fi

run_step python3 "$WORKSPACE/system/lifehug.py" compile --no-ai
run_source_integrity
run_step python3 "$WORKSPACE/system/lifehug.py" quality-update
run_step python3 "$WORKSPACE/system/lifehug.py" planner-queue --limit "$QUEUE_LIMIT" --arc-max "$ARC_MAX" --expires-days "$EXPIRES_DAYS"
run_step python3 "$WORKSPACE/system/research_expand.py" --gaps --dry-run
run_step python3 "$WORKSPACE/system/lifehug.py" progress
safe_autocommit
