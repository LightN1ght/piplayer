#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then echo "Usage: $0 input-video output.mp4" >&2; exit 1; fi
# Bound bandwidth and keyframe intervals for a small HLS ring buffer.
ffmpeg -hide_banner -n -i "$1" -map 0:v:0 -map '0:a:0?' \
  -vf "scale=w='min(1280,iw)':h=-2,format=yuv420p" -r 25 \
  -c:v libx264 -preset veryfast -profile:v main -b:v 2000k -maxrate 3000k -bufsize 6000k \
  -g 50 -keyint_min 50 -sc_threshold 0 -c:a aac -b:a 128k -ac 2 \
  -movflags +faststart "$2"

