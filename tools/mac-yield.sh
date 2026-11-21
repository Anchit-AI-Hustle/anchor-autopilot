#!/bin/bash
# The song renders keep running all the time and never compete with Anchit's own work on the
# Mac (2026-11-21: "it should keep happening but ensure no impact on overall system usage and
# efficiency"). Nothing is ever paused. Every 10 s every render process (ACE-Step's ace-synth
# and ace-lm on the GPU, the anchor make or studio run, its ffmpeg, the cinematic worker) is
# put at background priority: taskpolicy -b (macOS background QoS: efficiency cores, throttled
# disk and network, below every app in use) and nice 19. Whatever Anchit runs always goes
# first; the renders use only what is left over. The workflows start the renders this way too;
# this loop also catches every child process they spawn.
# Kept running by the heartbeat (scripts/mac-runner-setup.sh).
# Off: touch ~/anchor-gpu/yield.off   Log: ~/anchor-gpu/yield.log
set -u
BASE="${ANCHOR_GPU_DIR:-$HOME/anchor-gpu}"
LOG="$BASE/yield.log"
DONE="$BASE/yield.done"
# anchored on the program itself, so no shell or editor that merely mentions these names is
# ever touched (2026-11-21: an unanchored pattern caught a terminal running a command about it)
PATTERN='^[^ ]*/ace-(synth|lm)( |$)|^[^ ]*/[Pp]ython[0-9.]* -m anchor (make|studio)( |$)|^ffmpeg .*(build/|_work/)|^[^ ]*/[Pp]ython[^ ]* [^ ]*cinematic/worker[.]py'

pids() {
  pgrep -f "$PATTERN" 2>/dev/null | grep -v "^$$\$"
}

step() {
  [ -f "$BASE/yield.off" ] && return
  local p
  for p in $(pids); do
    # a render paused by the earlier pause-on-use version carries on
    kill -CONT "$p" 2>/dev/null
    grep -qx "$p" "$DONE" 2>/dev/null && continue
    taskpolicy -b -p "$p" 2>/dev/null
    renice -n 19 -p "$p" >/dev/null 2>&1
    echo "$p" >> "$DONE"
    tail -n 500 "$DONE" > "$DONE.tmp" && mv "$DONE.tmp" "$DONE"
    echo "$(date -u +%FT%TZ) background priority for $p $(ps -o comm= -p "$p" 2>/dev/null | head -c 80)" >> "$LOG"
  done
}

if [ "${1:-}" = "--loop" ]; then
  while true; do step; sleep 10; done
else
  step
fi
