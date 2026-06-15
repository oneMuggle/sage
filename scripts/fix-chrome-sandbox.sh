#!/bin/bash
# fix-chrome-sandbox.sh — re-apply SUID on Electron's Linux sandbox helper.
#
# Why: Electron aborts on Linux unless
# node_modules/electron/dist/chrome-sandbox is owned by root and has mode
# 4755. `npm install` rewrites the file with default perms, so this
# postinstall step re-applies them. No-op on macOS and Windows.
#
# Sudo: tries chown without sudo first (CI / Docker / root contexts),
# then non-interactive sudo (NOPASSWD sudoers). If both fail, prints a
# clear instruction and exits 0 so `npm install` still completes —
# Electron will just refuse to start until the user fixes the perms.

set -e

# Skip on non-Linux (the helper is a Linux-only construct)
case "$(uname -s)" in
  Linux*) ;;
  *) exit 0 ;;
esac

SANDBOX="node_modules/electron/dist/chrome-sandbox"

if [ ! -f "$SANDBOX" ]; then
  echo "[fix-chrome-sandbox] $SANDBOX not found, skipping"
  exit 0
fi

# Idempotent: skip if already correct
if [ "$(stat -c '%U' "$SANDBOX")" = "root" ] \
   && [ "$(stat -c '%a' "$SANDBOX")" = "4755" ]; then
  exit 0
fi

apply() {
  chown root:root "$SANDBOX" && chmod 4755 "$SANDBOX"
}

# 1. Direct (no sudo) — works in CI / Docker / root
if apply 2>/dev/null; then
  echo "[fix-chrome-sandbox] set SUID (direct chown)"
  exit 0
fi

# 2. Non-interactive sudo — works in NOPASSWD sudoers
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  if sudo -n chown root:root "$SANDBOX" && sudo -n chmod 4755 "$SANDBOX"; then
    echo "[fix-chrome-sandbox] set SUID (sudo -n)"
    exit 0
  fi
fi

# 3. Give up gracefully — don't break `npm install`
cat >&2 <<EOF
[fix-chrome-sandbox] could not set SUID on $SANDBOX.
  Electron will refuse to start on Linux until you run:
    sudo chown root:root $SANDBOX && sudo chmod 4755 $SANDBOX
EOF
exit 0
