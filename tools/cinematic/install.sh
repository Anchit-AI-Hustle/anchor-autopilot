#!/bin/bash
# Installs the idle-only cinematic shot maker as a LaunchAgent (every 10 minutes, background
# priority: the Mac's efficiency cores and lowest GPU and disk priority). Remove with:
#   launchctl bootout gui/$(id -u)/com.anchor.cinematic && rm ~/Library/LaunchAgents/com.anchor.cinematic.plist
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CIN="$HOME/anchor-gpu/cinematic"
PY="$CIN/venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.anchor.cinematic.plist"
REPO="$CIN/repo"
mkdir -p "$CIN/clips" "$HOME/Library/LaunchAgents"
# the worker runs from its own clone of main and pulls it every run
if [ ! -d "$REPO/.git" ]; then
  git clone -q --depth 1 https://github.com/Anchit-AI-Hustle/anchor-autopilot "$REPO"
fi
git -C "$REPO" pull -q --ff-only
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.anchor.cinematic</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/sbin/taskpolicy</string><string>-b</string>
    <string>$PY</string><string>$REPO/tools/cinematic/worker.py</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>LowPriorityBackgroundIO</key><true/>
  <key>Nice</key><integer>19</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTORCH_ENABLE_MPS_FALLBACK</key><string>1</string>
    <key>HF_HUB_OFFLINE</key><string>1</string>
    <key>ANCHOR_REPO</key><string>$REPO</string>
    <key>ANCHOR_CINEMATIC_DIR</key><string>$CIN/clips</string>
  </dict>
  <key>StandardOutPath</key><string>$CIN/worker.out</string>
  <key>StandardErrorPath</key><string>$CIN/worker.out</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/com.anchor.cinematic" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $PLIST"
