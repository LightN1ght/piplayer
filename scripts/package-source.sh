#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$project/dist/docs"
cp "$project/docs/"*.md "$project/dist/docs/"
cp "$project/README.md" "$project/dist/README.md"
# Keep convenient top-level guides while preserving working documentation links.
python3 - "$project" <<'PY'
from pathlib import Path
import re, sys
project = Path(sys.argv[1])
for name in ('QUICKSTART', 'VALIDATION', 'DELIVERY', 'HLS', 'ETHERNET'):
    text = (project / 'docs' / (name + '.md')).read_text()
    text = re.sub(r'(\]\()([A-Za-z0-9_]+\.md)(\))', r'\1docs/\2\3', text)
    text = text.replace('](../README.md)', '](README.md)')
    (project / 'dist' / (name + '.md')).write_text(text)
PY
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
