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

# ---- Git remote setup ----
echo ""
ORIGIN_URL=$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo "")

if echo "$ORIGIN_URL" | grep -q "lifehug/lifehug"; then
  echo "📡 Git remotes"
  echo "   origin currently points to the Lifehug template repo."
  echo "   To save your answers and progress, you need your own repo."
  echo ""

  # Rename origin → upstream
  if ! git -C "$SCRIPT_DIR" remote get-url upstream &>/dev/null; then
    git -C "$SCRIPT_DIR" remote rename origin upstream
    echo "   ✅ Renamed origin → upstream (for receiving Lifehug updates)"
  else
    echo "   ✅ upstream remote already exists"
  fi

  echo ""
  echo "   Create a repo on GitHub (e.g. github.com/yourname/lifehug)"
  echo "   Then enter the URL below, or press Enter to skip for now."
  echo ""
  read -r -p "   Your repo URL (or Enter to skip): " USER_REPO

  if [ -n "$USER_REPO" ]; then
    git -C "$SCRIPT_DIR" remote add origin "$USER_REPO" 2>/dev/null || \
      git -C "$SCRIPT_DIR" remote set-url origin "$USER_REPO"
    echo "   ✅ origin → $USER_REPO"
    echo ""

    read -r -p "   Push now? (y/N): " PUSH_NOW
    if [[ "$PUSH_NOW" =~ ^[Yy] ]]; then
      git -C "$SCRIPT_DIR" push -u origin main 2>&1 || echo "   ⚠️  Push failed — you can try again later with: git push -u origin main"
    fi
  else
    echo ""
    echo "   No problem — your work is saved locally via git commits."
    echo "   When you're ready, create a repo and run:"
    echo ""
    echo "     git remote add origin <your-repo-url>"
    echo "     git push -u origin main"
    echo ""
  fi
elif [ -z "$ORIGIN_URL" ]; then
  echo "📡 No git remote configured."
  echo "   Your work is saved locally. To back up to GitHub:"
  echo ""
  echo "     git remote add origin <your-repo-url>"
  echo "     git push -u origin main"
  echo ""
  echo "   To receive Lifehug updates:"
  echo ""
  echo "     git remote add upstream https://github.com/lifehug/lifehug.git"
  echo ""
else
  echo "📡 Git remotes"
  echo "   origin: $ORIGIN_URL"
  UPSTREAM_URL=$(git -C "$SCRIPT_DIR" remote get-url upstream 2>/dev/null || echo "")
  if [ -n "$UPSTREAM_URL" ]; then
    echo "   upstream: $UPSTREAM_URL ✅"
  else
    echo "   ⚠️  No upstream remote — you won't receive Lifehug updates."
    echo "   Add it with: git remote add upstream https://github.com/lifehug/lifehug.git"
  fi
fi

# ---- Claude Code desktop skill (/focus) ----
echo ""
CLAUDE_SKILLS="${HOME}/.claude/skills"
if [ -d "$SCRIPT_DIR/skills/focus" ]; then
  mkdir -p "$CLAUDE_SKILLS"
  if [ -e "$CLAUDE_SKILLS/focus" ]; then
    echo "✅ /focus desktop skill already installed"
  else
    ln -s "$SCRIPT_DIR/skills/focus" "$CLAUDE_SKILLS/focus" 2>/dev/null \
      || cp -r "$SCRIPT_DIR/skills/focus" "$CLAUDE_SKILLS/focus"
    echo "✅ Installed /focus skill → use it in Claude Code to add and manage Focuses"
  fi
fi

# ---- OpenClaw ----
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
  echo ""
  echo "📚 Project categories detected — setup was already completed"
  echo ""
  python3 "$SCRIPT_DIR/system/ask.py" --status
else
  echo ""
  echo "🆕 Fresh install — ready for setup"
fi

echo ""
echo "Docs: https://github.com/lifehug/lifehug"
