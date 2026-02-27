#!/usr/bin/env bash
# Lifehug — First-run setup helper
# Run this after cloning to verify your environment and start setup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🤗 Lifehug — First-run setup"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Install it first: https://python.org"
  exit 1
fi
echo "✅ Python 3 found: $(python3 --version)"

# Check ask.py works
if python3 "$SCRIPT_DIR/system/ask.py" --dry-run &>/dev/null; then
  echo "✅ Rotation engine works"
else
  echo "❌ Rotation engine failed — check system/ask.py"
  exit 1
fi

# Check config
if [ -f "$SCRIPT_DIR/config.yaml" ]; then
  echo "✅ config.yaml exists (already set up)"
else
  echo "📝 No config.yaml yet — your AI will create this during setup"
  cp "$SCRIPT_DIR/config.yaml.example" "$SCRIPT_DIR/config.yaml" 2>/dev/null || true
fi

# Check for OpenClaw
echo ""
if command -v openclaw &>/dev/null; then
  echo "✅ OpenClaw detected: $(openclaw --version 2>&1 | head -1)"

  # Install skill if not already installed
  SKILL_DIR="${HOME}/.openclaw/skills/lifehug"
  if [ -d "$SKILL_DIR" ]; then
    echo "✅ Lifehug skill already installed"
  else
    echo "📦 Installing Lifehug skill..."
    mkdir -p "${HOME}/.openclaw/skills"
    ln -s "$SCRIPT_DIR/skill" "$SKILL_DIR" 2>/dev/null || cp -r "$SCRIPT_DIR/skill" "$SKILL_DIR"
    echo "✅ Lifehug skill installed → your AI will auto-detect answers"
  fi

  echo ""
  echo "To start setup, tell your AI:"
  echo ""
  echo "  \"Set up Lifehug in $SCRIPT_DIR\""
  echo ""
  echo "Or open the workspace directly:"
  echo ""
  echo "  openclaw agent --message \"Set up Lifehug in $SCRIPT_DIR\""
  echo ""
else
  echo "ℹ️  OpenClaw not found — you can use any AI that reads CLAUDE.md"
  echo "   (Claude Code, Cursor, etc.)"
  echo ""
  echo "   Open this folder in your AI tool and say: \"Set me up\""
  echo ""
  echo "   Get OpenClaw: https://openclaw.ai"
fi

# Check for project categories (setup already done?)
if grep -q "^## [F-Z]:" "$SCRIPT_DIR/system/question-bank.md" 2>/dev/null; then
  echo "📚 Project categories detected — setup was already completed"
  echo ""
  python3 "$SCRIPT_DIR/system/ask.py" --status
else
  echo "🆕 Fresh install — ready for setup"
fi

echo ""
echo "Docs: https://github.com/lifehug/lifehug"
