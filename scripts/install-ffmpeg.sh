#!/usr/bin/env bash
# ffmpeg for CI and the robot. apt first (the same ffmpeg as always), but with a hard time
# limit: GitHub's apt mirrors sometimes stall for 30+ min, which cancelled the 2026-10-22 and
# 2026-10-23 drops and their CI. After 7 min it falls back to the static BtbN build.
set -u
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
ffmpeg -version | head -n 1
exit 0
fi
OPTS="-o Acquire::Retries=3 -o Acquire::http::Timeout=30"
if timeout 420 bash -c "sudo apt-get $OPTS update -qq && sudo apt-get $OPTS install -y -qq ffmpeg"; then
ffmpeg -version | head -n 1
exit 0
fi
echo "::warning::apt did not install ffmpeg within 7 min; using the static build"
set -e
NAME=ffmpeg-master-latest-linux64-gpl
curl -fsSL --retry 3 --max-time 600 -o /tmp/$NAME.tar.xz "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/$NAME.tar.xz"
sudo tar -xJf /tmp/$NAME.tar.xz -C /opt
sudo ln -sf /opt/$NAME/bin/ffmpeg /opt/$NAME/bin/ffprobe /usr/local/bin/
ffmpeg -version | head -n 1
