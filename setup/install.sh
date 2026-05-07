#!/bin/bash
#
# Alfred — one-line installer
# Usage: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ellippma/Alfred/main/setup/install.sh)"
#

set -e

REPO_URL="https://github.com/ellippma/Alfred-Public.git"
INSTALL_DIR="$HOME/alfred-repo"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; RESET='\033[0m'

fail()  { echo -e "\n${RED}  ✗  $1${RESET}\n"; exit 1; }
warn()  { echo -e "${YELLOW}  ⚠  $1${RESET}"; }
ok()    { echo -e "${GREEN}  ✓  $1${RESET}"; }

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "  🦇  ALFRED — Personal AI Chief of Staff"
echo "  Installer"
echo "══════════════════════════════════════════════════"
echo ""

# ── macOS check ───────────────────────────────────────────────────────────────
if [[ "$OSTYPE" != "darwin"* ]]; then
  fail "Alfred requires macOS. This installer only runs on Mac."
fi

# ── Dependency checks ─────────────────────────────────────────────────────────
echo "  Checking requirements..."

# Git
if ! command -v git &>/dev/null; then
  warn "Git is not installed."
  echo ""
  echo "  Git is required. macOS will prompt you to install it."
  echo "  After installing, re-run this installer."
  echo ""
  xcode-select --install 2>/dev/null || true
  exit 1
fi
ok "Git found ($(git --version | awk '{print $3}'))"

# Python 3
if ! command -v python3 &>/dev/null; then
  fail "Python 3 is not installed. Download it from https://python.org and re-run this installer."
fi
PY_VER=$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:2])))')
ok "Python $PY_VER found"

# Claude Code
if ! command -v claude &>/dev/null; then
  warn "Claude Code CLI not detected — this is fine if you installed the Mac app."
  warn "If you haven't installed Claude Code yet, get it at https://claude.ai/code first."
fi

echo ""

# ── Clone or update repo ──────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "  Alfred repo already exists at $INSTALL_DIR"
  echo "  Pulling latest updates..."
  git -C "$INSTALL_DIR" pull --quiet
  ok "Repo updated"
else
  echo "  Downloading Alfred to $INSTALL_DIR..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  ok "Alfred downloaded"
fi

echo ""

# ── Run setup wizard (browser UI) ────────────────────────────────────────────
exec python3 "$INSTALL_DIR/setup/alfred-setup-ui.py"
