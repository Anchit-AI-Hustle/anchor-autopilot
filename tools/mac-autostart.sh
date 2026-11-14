#!/bin/bash
# Start the next songs on the Mac the moment there is room, and post each one as soon as it is
# made (Anchit, 2026-11-14: "ensure all new songs are uploaded as soon as they are created").
# GitHub starts the scheduled daily runs hours late (2026-11-14: the 08:37 UTC run had not begun
# at 10:30), so the Mac's own heartbeat (every 5 min, launchd) starts a posting run itself when:
#   - the Mac runner is up and no daily run is queued or running (one run at a time, no clashes
#     with the overnight render-only batch)
#   - it is the YouTube quota day, 08:10 to 21:00 UTC (overnight, prerender.yml owns the Mac)
#   - today still needs songs and the quota has room (python -m anchor plan-drops)
#   - the last daily run started 45 min ago or more, and fewer than 8 were started here today
# Started with Anchit's own gh login, so the release step works (bot-started runs get 403).
# Pause: touch ~/anchor-gpu/autostart.off   Log: ~/anchor-gpu/autostart.log
set -u
export PATH="${ANCHOR_PATH_PREFIX:+$ANCHOR_PATH_PREFIX:}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPO="Anchit-AI-Hustle/anchor-autopilot"
BASE="${ANCHOR_GPU_DIR:-$HOME/anchor-gpu}"
DIR="$BASE/autostart-repo"
PY="$BASE/runner-venv/bin/python"
LOG="$BASE/autostart.log"
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

[ -f "$BASE/autostart.off" ] && exit 0
pgrep -f "Runner.Listener" >/dev/null || exit 0
HM=$((10#${ANCHOR_NOW_HM:-$(date -u +%H%M)}))
{ [ "$HM" -ge 810 ] && [ "$HM" -lt 2100 ]; } || exit 0

RUNS="$(gh run list -R "$REPO" -w daily.yml -L 20 --json status,createdAt 2>/dev/null)" || exit 0
BUSY="$(echo "$RUNS" | "$PY" -c 'import json,sys;print(sum(r["status"]!="completed" for r in json.load(sys.stdin)))')" || exit 0
[ "$BUSY" = 0 ] || exit 0
AGO="$(echo "$RUNS" | "$PY" -c '
import json,sys,datetime as d
r=json.load(sys.stdin)
t=d.datetime.fromisoformat(r[0]["createdAt"].replace("Z","+00:00")) if r else None
print(int((d.datetime.now(d.timezone.utc)-t).total_seconds()) if t else 10**9)')" || exit 0
[ "$AGO" -ge 2700 ] || exit 0

TODAY="${ANCHOR_TODAY:-$(date -u +%F)}"
COUNT="$BASE/autostart-$TODAY.count"
N="$(cat "$COUNT" 2>/dev/null || echo 0)"
[ "$N" -lt 8 ] || exit 0

if [ ! -d "$DIR/.git" ]; then
  gh repo clone "$REPO" "$DIR" -- -q >/dev/null 2>&1 || { log "clone failed"; exit 0; }
fi
git -C "$DIR" fetch -q origin main && git -C "$DIR" reset -q --hard origin/main || { log "pull failed"; exit 0; }
DROPS="$(cd "$DIR" && "$PY" -m anchor plan-drops 2>"$BASE/autostart-plan.txt")" || { log "plan failed: $(tail -n 1 "$BASE/autostart-plan.txt")"; exit 0; }
[ -n "$DROPS" ] && [ "$DROPS" != "[]" ] || exit 0

if gh workflow run daily.yml -R "$REPO" --ref main -f renderer=mac >/dev/null 2>&1; then
  echo $((N + 1)) > "$COUNT"
  log "started a posting run for $DROPS ($(tail -n 1 "$BASE/autostart-plan.txt"))"
else
  log "dispatch failed"
fi
