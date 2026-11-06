#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$project/vendor"
[[ -f "$project/vendor/hls.light.min.js" ]] || curl -fL --retry 3 -o "$project/vendor/hls.light.min.js" https://cdn.jsdelivr.net/npm/hls.js@1.6.13/dist/hls.light.min.js
[[ -f "$project/vendor/hls.LICENSE" ]] || curl -fL --retry 3 -o "$project/vendor/hls.LICENSE" https://cdn.jsdelivr.net/npm/hls.js@1.6.13/LICENSE
(cd "$project/vendor" && sha256sum -c <<'EOF'
3ff29c965f23f6e45d0a33886ea959bd87a9fc4565825e9b7e85270d40fdaaaa  hls.light.min.js
ca8773cf798c7ed997d4dd7c8e23c348699f8d5b7462636694cc14de6cda12db  hls.LICENSE
EOF
)

