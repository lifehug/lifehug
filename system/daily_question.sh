#!/usr/bin/env bash
# Lifehug Daily Question — no AI needed
# Picks today's question, sends + pins it in the delivery channel
#
# Reads WORKSPACE from environment or defaults to parent of this script.
# Reads TOKEN and CHAT_ID from config.yaml (telegram_chat_id) or environment.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$(dirname "$SCRIPT_DIR")}"

cd "$WORKSPACE"

# Read config values
CHAT_ID="${TELEGRAM_CHAT_ID:-$(python3 -c "
import re, sys
config = open('config.yaml').read()
m = re.search(r'^telegram_chat_id:\s*[\"\']*([^\s\"\'#]+)[\"\']*', config, re.MULTILINE)
print(m.group(1) if m else '')
")}"

TOKEN="${TELEGRAM_BOT_TOKEN:-$(python3 -c "
import json, os
try:
    c = json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))
    print(c['channels']['telegram']['botToken'])
except Exception:
    print('')
")}"

if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (via env or config.yaml)" >&2
  exit 1
fi

# 1. Commit + push any pending changes
git add -A
if ! git diff --cached --quiet; then
  git commit -m "Daily update $(date +%Y-%m-%d)"
  git push
fi

# 2. Check if we're already waiting for pass transition approval
AWAITING=$(python3 -c "
import json
r = json.load(open('system/rotation.json'))
print('true' if r.get('awaiting_pass_transition') else 'false')
")

if [[ "$AWAITING" == "true" ]]; then
  # Re-send the transition prompt (in case it was missed)
  DEFAULT_MODEL=$(python3 -c "
import re
config = open('config.yaml').read()
m = re.search(r'^followup_model:\s*[\"\'\"]*([^\s\"\'#]+)[\"\'\"]*', config, re.MULTILINE)
print(m.group(1) if m else 'anthropic/claude-opus-4-6')
")
  ROTATION=$(python3 -c "import json; r=json.load(open('system/rotation.json')); print(r.get('current_pass',1))")

  TEXT="📖 Lifehug — Pass ${ROTATION} complete!

Ready to generate your depth questions for Pass $((ROTATION + 1)).

Default model: \`${DEFAULT_MODEL}\`

Reply with a model name to use a different one, or just say **go** to use the default."

  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${TEXT}" > /dev/null

  echo "✓ Pass transition reminder sent (awaiting model confirmation)"
  exit 0
fi

# 3. Pick today's question
QUESTION_OUTPUT=$(python3 "$WORKSPACE/system/ask.py")

# 4. Check if pass just completed
if [[ "$QUESTION_OUTPUT" == PASS_COMPLETE:* ]]; then
  PASS_NUM=$(echo "$QUESTION_OUTPUT" | cut -d: -f2)
  DEFAULT_MODEL=$(echo "$QUESTION_OUTPUT" | cut -d: -f3-)

  TEXT="📖 Lifehug — Pass ${PASS_NUM} complete! 🎉

You've answered every question in this pass. Time to generate your depth questions for Pass $((PASS_NUM + 1)).

I'll use the best model available to craft questions that go deeper into your stories.

Default model: \`${DEFAULT_MODEL}\`

Reply with a model name to use a different one, or just say **go** to use the default."

  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${TEXT}" > /dev/null

  echo "✓ Pass ${PASS_NUM} complete — transition prompt sent"
  exit 0
fi

# 5. Normal question — send and pin
TEXT="📖 Lifehug — Daily Question

${QUESTION_OUTPUT}

(Answer whenever you want — voice or text)"

RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${TEXT}")

MESSAGE_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['message_id'])")

# 6. Pin the message
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/pinChatMessage" \
  -d "chat_id=${CHAT_ID}&message_id=${MESSAGE_ID}&disable_notification=true" > /dev/null

echo "✓ Lifehug question sent and pinned (msg_id: $MESSAGE_ID)"
