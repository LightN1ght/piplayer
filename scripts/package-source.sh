#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$project/dist"
cp "$project/docs/QUICKSTART.md" "$project/dist/QUICKSTART.md"
cp "$project/docs/VALIDATION.md" "$project/dist/VALIDATION.md"
cp "$project/docs/DELIVERY.md" "$project/dist/DELIVERY.md"
if [[ -f "$project/.build/demo.mp4" ]]; then cp "$project/.build/demo.mp4" "$project/dist/demo.mp4"; fi
if [[ -f "$project/.build/player-preview-final.jpg" ]]; then
  cp "$project/.build/player-preview-final.jpg" "$project/dist/player-preview.jpg"
elif [[ -f "$project/.build/player-preview-arm.jpg" ]]; then
  cp "$project/.build/player-preview-arm.jpg" "$project/dist/player-preview.jpg"
elif [[ -f "$project/.build/player-preview.jpg" ]]; then
  cp "$project/.build/player-preview.jpg" "$project/dist/player-preview.jpg"
fi
tar -czf "$project/dist/piplayer-source.tar.gz" \
  --exclude=./.git --exclude=./.local --exclude=./.build --exclude=./dist \
  --exclude=./.agents --exclude=./.aws --exclude=./.codex --exclude='*/__pycache__' \
  -C "$project" .
echo 'Source archive and documentation refreshed; raw image was not modified.'
