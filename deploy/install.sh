#!/usr/bin/env bash
set -euo pipefail

# Install HALSPA Test Runner on the Raspberry Pi.
# Run this script from the HALSPA-runner repository root.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Building frontend ==="
cd "$REPO_DIR/frontend"
if command -v npm &>/dev/null; then
    npm install
    npm run build
else
    echo "WARNING: npm not found. Frontend must be pre-built."
    if [ ! -d dist ]; then
        echo "ERROR: frontend/dist/ does not exist and npm is not available."
        exit 1
    fi
fi

echo "=== Installing Python dependencies ==="
cd "$REPO_DIR"
uv sync

echo "=== Installing systemd service ==="
mkdir -p "$HOME/.config/systemd/user"
# Substitute %h with actual home directory for user service
sed "s|%h|$HOME|g; s|%i|$(whoami)|g" deploy/halspa-runner.service \
    > "$HOME/.config/systemd/user/halspa-runner.service"

systemctl --user daemon-reload
systemctl --user enable halspa-runner.service
systemctl --user start halspa-runner.service

echo "=== Installing Chromium kiosk autostart ==="
mkdir -p "$HOME/.config/autostart"
cp deploy/chromium-kiosk.desktop "$HOME/.config/autostart/"

echo "=== Done ==="
echo "The backend is running. Chromium kiosk will start on next login."
echo "To start Chromium now: chromium-browser --kiosk http://localhost:8080"
