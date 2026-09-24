#!/bin/sh
# Optional authoring fixture only; requires a local ffmpeg installation.
# Run in tests/provider_fixtures/reference. Never downloads external media.
set -eu
mkdir -p 360 720
for height in 360 720; do
  ffmpeg -hide_banner -loglevel error -f lavfi -i "testsrc2=size=$((height * 16 / 9))x${height}:rate=24" \
    -f lavfi -i sine=frequency=440:sample_rate=44100 -t 12 -c:v libx264 -preset ultrafast \
    -pix_fmt yuv420p -g 48 -c:a aac -f hls -hls_time 2 -hls_playlist_type vod \
    -hls_segment_filename "$height/segment-%03d.ts" "$height/index.m3u8"
done
ffmpeg -hide_banner -loglevel error -i 360/index.m3u8 -c copy -movflags +faststart sample.mp4
