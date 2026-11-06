#!/usr/bin/env bash
set -euo pipefail
main() {
configure=0
public=0
for option in "$@"; do
  case "$option" in
    --configure) configure=1 ;;
    --public) public=1 ;;
    *) echo 'Usage: scripts/build.sh [--configure] [--public]' >&2; exit 1 ;;
  esac
done
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
work=${PIPLAYER_WORK:-${XDG_CACHE_HOME:-$HOME/.cache}/piplayer-build}
version=2025.02.19
archive_sha=e5e58bff1da91f022f60cefdfe280140c08023cd0aeec1e5f6f9da0ea866d69c
[[ "$work" != *' '* ]] || { echo 'Build directory must not contain spaces.' >&2; exit 1; }
mkdir -p "$work" "$project/.build" "$project/vendor"
# Archives are data, so an alias is safe here even when the project has spaces.
# Keep them on disk and across reboots instead of filling a RAM-backed /tmp.
mkdir -p "$project/.build/downloads"
if [[ ! -e "$work/downloads" ]]; then ln -s "$project/.build/downloads" "$work/downloads"; fi
if [[ -d "$project/.build/tools/usr" ]]; then
  mkdir -p "$work/tools"
  cp -a "$project/.build/tools/usr" "$work/tools/"
  export PATH="$work/tools/usr/bin:$PATH"
fi
missing=()
for command in make gcc g++ cpio rsync bc unzip wget curl python3 file \
  patch perl tar xz bison flex openssl ssh-keygen sha256sum; do
  command -v "$command" >/dev/null 2>&1 || missing+=("$command")
done
if (( ${#missing[@]} )); then
  printf 'Missing build dependencies: %s\n' "${missing[*]}" >&2
  echo 'Install the missing commands and run scripts/build.sh again.' >&2
  exit 1
fi
if [[ ! -d "$work/buildroot-$version" ]]; then
  archive="$work/buildroot-$version.tar.xz"
  curl -fL --retry 3 -o "$archive" "https://buildroot.org/downloads/buildroot-$version.tar.xz"
  printf '%s  %s\n' "$archive_sha" "$archive" | sha256sum -c -
  tar -xf "$archive" -C "$work"
fi
python3 "$project/scripts/configure.py"
if [[ "$public" == 1 ]]; then
  touch "$project/.local/public-mode"
  # Buildroot applies its users table after post-build; lock the account there.
  printf '%s\n' 'player 1000 player 1000 * /data /bin/sh - PiPlayer' > "$project/.local/users.txt"
  chmod 600 "$project/.local/users.txt"
else
  rm -f "$project/.local/public-mode"
fi
"$project/scripts/fetch-web.sh"
# Buildroot does not accept spaces in source, output or BR2_EXTERNAL paths.
mkdir -p "$work/project"
rsync -a --exclude=.git --exclude=.build --exclude=dist --exclude=.agents --exclude=.aws --exclude=.codex "$project/" "$work/project/"
br="$work/buildroot-$version"
# Command-line DL_DIR intentionally keeps the short alias: Buildroot normally
# dereferences download directories, which would reintroduce project spaces.
args=(-C "$br" "O=$work/output" "BR2_EXTERNAL=$work/project" "BR2_DL_DIR=$work/downloads" "DL_DIR=$work/downloads")
if [[ ! -f "$work/output/.config" || "$configure" == 1 ]]; then
  make "${args[@]}" player_defconfig
fi
echo "Building; log: $project/.build/build.log"
if ! make "${args[@]}" "-j${JOBS:-4}" > "$project/.build/build.log" 2>&1; then
  tail -n 50 "$project/.build/build.log" >&2
  exit 1
fi
if [[ "${PIPLAYER_SKIP_PACKAGE:-0}" != 1 ]]; then
  "$project/scripts/package.sh" "$work/output/images"
fi
}
main "$@"

