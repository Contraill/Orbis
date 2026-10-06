#!/bin/sh
set -eu
# Synthetic 4-second H.264/AAC clip for isolated player browser tests.
cd "$(dirname "$0")"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i 'testsrc2=size=320x180:rate=24' \
  -f lavfi -i 'sine=frequency=440:sample_rate=44100' \
  -t 4 -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -c:a aac -b:a 48k -movflags +faststart -y player-clip.mp4
