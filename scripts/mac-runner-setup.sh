#!/usr/bin/env bash
# One-time setup: this Mac renders ANCHOR's songs on its GPU (Anchit, 2026-10-29: "use the Mac
# GPU"). Run it yourself in Terminal, signed in to the GitHub CLI as the repo's owner:
#
#   bash scripts/mac-runner-setup.sh
#
# What it does, and nothing else:
#   1. a runner group "anchor-mac" in the Anchit-AI-Hustle org that only the daily Drop workflow
#      on main may use (this repo is public: no pull request or other workflow can reach the Mac)
#   2. a GitHub Actions runner in ~/actions-runner-anchor, labels self-hosted, macOS, ARM64,
#      anchor-mac, started at login (launchd)
#   3. a heartbeat every 5 minutes (launchd) that stamps the repo variable ANCHOR_MAC_SEEN while
#      the runner is up; the daily run renders on the Mac only when that is under 20 min old,
#      otherwise on GitHub's CPU as before
#   4. ffmpeg and cmake from Homebrew if missing
# The engine and the 4B models (about 11 GB, ~/anchor-gpu) are fetched by the first run.
# Undo: scripts/mac-runner-setup.sh --remove
set -euo pipefail
REPO="Anchit-AI-Hustle/anchor-autopilot"
ORG="${REPO%%/*}"
DIR="$HOME/actions-runner-anchor"
GROUP="anchor-mac"
HB_LABEL="com.anchor.heartbeat"
HB="$HOME/Library/LaunchAgents/$HB_LABEL.plist"
RUNNER_VERSION="2.329.0"

if [ "${1:-}" = "--remove" ]; then
  launchctl unload "$HB" 2>/dev/null || true; rm -f "$HB"
  if [ -d "$DIR" ]; then
    (cd "$DIR" && ./svc.sh stop || true; ./svc.sh uninstall || true
     TOKEN="$(gh api -X POST "repos/$REPO/actions/runners/remove-token" -q .token)"
     ./config.sh remove --token "$TOKEN" || true)
  fi
  gh variable delete ANCHOR_MAC_SEEN -R "$REPO" 2>/dev/null || true
  echo "Removed. Songs render on GitHub's CPU again."
  exit 0
fi

[ "$(uname -s)/$(uname -m)" = "Darwin/arm64" ] || { echo "This is for an Apple silicon Mac."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Sign in first: gh auth login"; exit 1; }
for tool in ffmpeg cmake; do command -v "$tool" >/dev/null || brew install "$tool"; done

# 1. the runner group: only daily.yml on main, public repos allowed (this one is public)
GID="$(gh api "orgs/$ORG/actions/runner-groups" -q ".runner_groups[] | select(.name==\"$GROUP\") | .id" || true)"
WF="$REPO/.github/workflows/daily.yml@refs/heads/main"
if [ -z "$GID" ]; then
  RID="$(gh api "repos/$REPO" -q .id)"
  GID="$(gh api -X POST "orgs/$ORG/actions/runner-groups" -f name="$GROUP" -f visibility=selected \
        -F "selected_repository_ids[]=$RID" -F allows_public_repositories=true \
        -F restricted_to_workflows=true -f "selected_workflows[]=$WF" -q .id)"
fi
echo "runner group $GROUP: id $GID, only $WF"

# 2. the runner, as a launchd service of this user
if [ ! -x "$DIR/run.sh" ]; then
  mkdir -p "$DIR" && cd "$DIR"
  curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-osx-arm64-$RUNNER_VERSION.tar.gz"
  tar xzf runner.tgz && rm runner.tgz
  TOKEN="$(gh api -X POST "orgs/$ORG/actions/runners/registration-token" -q .token)"
  ./config.sh --unattended --url "https://github.com/$ORG" --token "$TOKEN" --name "$(scutil --get LocalHostName)-anchor" \
    --runnergroup "$GROUP" --labels "anchor-mac" --work _work --replace
  ./svc.sh install && ./svc.sh start
fi

# 3. the heartbeat: the daily run picks the Mac only while this is fresh
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/anchor-gpu"
cat > "$HOME/anchor-gpu/heartbeat.sh" <<HBEOF
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
pgrep -f "Runner.Listener" >/dev/null || exit 0
gh variable set ANCHOR_MAC_SEEN -R "$REPO" --body "\$(date +%s)" >/dev/null 2>&1
HBEOF
chmod +x "$HOME/anchor-gpu/heartbeat.sh"
cat > "$HB" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$HB_LABEL</string>
  <key>ProgramArguments</key><array><string>$HOME/anchor-gpu/heartbeat.sh</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
PLEOF
launchctl unload "$HB" 2>/dev/null || true
launchctl load "$HB"
sleep 3
echo "heartbeat: ANCHOR_MAC_SEEN=$(gh variable get ANCHOR_MAC_SEEN -R "$REPO" 2>/dev/null || echo 'not yet')"
echo "Done. Keep the Mac awake and on power around 08:37 and 13:37 UTC (14:07 and 19:07 IST) for GPU renders."
