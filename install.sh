#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# advai — one-click installer (macOS / Linux)
#
#   sh <(curl -fsSL https://pypi.io/packages/source/a/advai-cli/install.sh)
#
# or save it locally and run it:
#
#   curl -fsSL https://example.com/install.sh | bash
#
# How it works:
#   1. Check python3 / pip3 are available; if not, print a friendly hint and exit.
#   2. Install the core via `pip3 install --user advai-cli` (fallback to system-wide
#      install if --user is not supported).
#   3. Make sure ~/.local/bin is on PATH (append to shell rc if missing).
# ---------------------------------------------------------------------------

set -e

ADVAI_VERSION="${ADVAI_VERSION:-latest}"
PY="python3"
PIP="pip3"

log()  { printf "\033[1;36m[advai]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[advai][warn]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[advai][error]\033[0m %s\n" "$*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

# ---- 1. Detect Python / pip ----
if ! command_exists "$PY"; then
  err "python3 not found. Please install Python 3 from https://www.python.org/downloads/"
  exit 1
fi
if ! command_exists "$PIP"; then
  err "pip3 not found. Try installing it with your system package manager (e.g. apt install python3-pip or brew install python)."
  exit 1
fi

log "Detected $(${PY} --version 2>&1 | head -n1)"

# ---- 2. Install advai-cli ----
log "Installing advai ($ADVAI_VERSION) ..."

INSTALL_TARGET="advai-cli"
if [ "$ADVAI_VERSION" != "latest"; then
  INSTALL_TARGET="advai-cli==${ADVAI_VERSION}"
fi

# Prefer --user; skip it if we are already inside a virtual environment
if [ -n "${VIRTUAL_ENV:-}" ]; then
  "$PIP" install --upgrade "$INSTALL_TARGET"
else
  if ! "$PIP" install --user --upgrade "$INSTALL_TARGET"; then
    warn "user-site installation failed, trying system-wide (may need sudo)..."
    if [ "$(id -u)" -eq 0 ]; then
      "$PIP" install --upgrade "$INSTALL_TARGET"
    else
      sudo "$PIP" install --upgrade "$INSTALL_TARGET"
    fi
  fi
fi

# ---- 3. Ensure ~/.local/bin is on PATH ----
LOCAL_BIN="$HOME/.local/bin"
SHELL_NAME="$(basename "${SHELL:-/bin/sh}")"
RC_FILE=""
case "$SHELL_NAME" in
  bash) RC_FILE="$HOME/.bashrc" ;;
  zsh)  RC_FILE="$HOME/.zshrc"  ;;
  fish) RC_FILE="$HOME/.config/fish/config.fish" ;;
  *)    RC_FILE="$HOME/.profile" ;;
esac

case ":$PATH:" in
  *":$LOCAL_BIN:"*) : ;;
  *)
    log "Adding $LOCAL_BIN to PATH (written to $RC_FILE)"
    mkdir -p "$(dirname "$RC_FILE")"
    if [ "$SHELL_NAME" = "fish" ]; then
      echo "fish_add_path -g $LOCAL_BIN" >> "$RC_FILE"
    else
      echo "export PATH=\"$LOCAL_BIN:\$PATH\" # added by advai installer" >> "$RC_FILE"
    fi
    warn "Please restart your terminal, or run: source $RC_FILE"
    ;;
esac

log "Installation complete! Try:"
log "  advai --help"
log "  advai install <skill-name>"
