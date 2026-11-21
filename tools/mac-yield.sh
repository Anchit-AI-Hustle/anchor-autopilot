#!/bin/bash
# The song renders never slow the Mac down while Anchit uses it (2026-11-21: "ensure all song
# creations happen in the background without affecting cpu usage or gpu usage or speed of
# laptop at all"). Every 10 s: if the keyboard, mouse or trackpad was used in the last
# 2 minutes, every render process (ACE-Step's ace-synth and ace-lm on the GPU, the anchor make
# or studio run, its ffmpeg, the cinematic worker) is paused with SIGSTOP, so it uses no CPU,
# GPU or disk at all; after 2 idle minutes they carry on with SIGCONT exactly where they were.
# The renders also run at background priority (taskpolicy -b, nice 19) in the workflows.
# The GitHub runner itself keeps answering, so a paused job is not lost, only slower.
# Started and kept alive by the heartbeat (scripts/mac-runner-setup.sh).
# Pause by hand: touch ~/anchor-gpu/yield.off   Log: ~/anchor-gpu/yield.log
set -u
BASE="${ANCHOR_GPU_DIR:-$HOME/anchor-gpu}"
LOG="$BASE/yield.log"
IDLE_S="${ANCHOR_YIELD_IDLE_S:-120}"
# anchored on the program itself, so no shell or editor that merely mentions these names is
# ever paused (2026-11-21: an unanchored pattern paused a terminal running a command about it)
PATTERN='^[^ ]*/ace-(synth|lm)( |$)|^[^ ]*/[Pp]ython[0-9.]* -m anchor (make|studio)( |$)|^ffmpeg .*(build/|_work/)|^[^ ]*/[Pp]ython[^ ]* [^ ]*cinematic/worker[.]py'

idle_s() {
  ioreg -c IOHIDSystem 2>/dev/null | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}'
}

pids() {
  pgrep -f "$PATTERN" 2>/dev/null | grep -v "^$$\$"
}

step() {
  [ -f "$BASE/yield.off" ] && { pids | xargs kill -CONT 2>/dev/null; return; }
  local idle state
  idle="$(idle_s)"; idle="${idle:-999999}"
  if [ "$idle" -lt "$IDLE_S" ]; then state=STOP; else state=CONT; fi
  local p
  p="$(pids)"
  [ -n "$p" ] || return
  echo "$p" | xargs kill "-$state" 2>/dev/null
  if [ "$state" != "$(cat "$BASE/yield.state" 2>/dev/null)" ]; then
    echo "$state" > "$BASE/yield.state"
    echo "$(date -u +%FT%TZ) ${state} $(echo "$p" | wc -l | tr -d ' ') render process(es); idle ${idle}s" >> "$LOG"
  fi
}

if [ "${1:-}" = "--loop" ]; then
  trap 'pids | xargs kill -CONT 2>/dev/null; exit 0' TERM INT
  while true; do step; sleep 10; done
else
  step
fi
