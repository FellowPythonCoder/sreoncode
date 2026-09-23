#!/usr/bin/env bash
# Post-build checks for the macOS artifacts, run by CI (and runnable by hand).
#
#   bash Browser/tools/ci-verify-macos.sh Browser/dist
#
# Anything that would ship a broken double-click file is fatal. Anything that only tells
# us something interesting about headless CI - can a frozen Qt app start from a read-only
# image, what does codesign think of it - is printed and never fails the job, because a
# GitHub runner has no window server and we would just be learning that again every week.
set -uo pipefail

dist="${1:-Browser/dist}"
dmg="$dist/Sreon.dmg"
pkg="$dist/Sreon.pkg"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"

fail=0
say() { printf '%s\n' "$*"; }

# --- the image must be intact, mountable and styled ------------------------------
if [[ ! -f "$dmg" ]]; then
  say "::error::no $dmg was produced"
  exit 1
fi
say "--- $(du -h "$dmg" | cut -f1) $dmg ---"

if ! hdiutil verify "$dmg"; then
  say "::error::hdiutil verify says the image is corrupt"
  fail=1
fi

if ! python3 Browser/tools/check_dmg.py "$dmg" --mount; then
  say "::error::check_dmg.py rejected the image (see its output above)"
  fail=1
fi

# --- the pkg must carry the same payload ------------------------------------------
if [[ ! -f "$pkg" ]]; then
  say "::error::no $pkg was produced"
  fail=1
else
  say "--- pkg payload ---"
  if ! pkgutil --payload-files "$pkg" | grep -q 'Sreon.app/Contents/MacOS/Sreon$'; then
    say "::error::Sreon.pkg does not contain Sreon.app/Contents/MacOS/Sreon"
    fail=1
  fi
  pkgutil --payload-files "$pkg" | head -5
  pkgutil --check-signature "$pkg" 2>&1 | head -3 || true
fi

# --- launch out of the mounted image: informational only --------------------------
say "--- launch from the read-only image (offscreen, best effort) ---"
mount=/Volumes/Sreon-ci
hdiutil detach "$mount" -force >/dev/null 2>&1 || true
mkdir -p "$mount"
if hdiutil attach -readonly -noverify -noautoopen -mountpoint "$mount" "$dmg" >/dev/null 2>&1; then
  ls -A "$mount"
  QT_QPA_PLATFORM=offscreen "$mount/Sreon.app/Contents/MacOS/Sreon" >/tmp/sreon-launch.log 2>&1 &
  pid=$!
  sleep 25
  if kill -0 "$pid" 2>/dev/null; then
    say "still alive after 25s: it launched from a mounted DMG, which is the point"
    kill "$pid" 2>/dev/null || true
  else
    wait "$pid" 2>/dev/null && code=0 || code=$?
    say "exited early with status $code - expected on a headless runner with no window server"
  fi
  tail -20 /tmp/sreon-launch.log 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    hdiutil detach "$mount" -force >/dev/null 2>&1 && break
    lsof -t "$mount" 2>/dev/null | xargs -r kill 2>/dev/null || true
    sleep 4
  done
  rm -rf "$mount" 2>/dev/null || true
else
  say "could not mount for the launch test (skipped, not fatal)"
fi

say "--- signature state ---"
codesign -dvvv "$dist/Sreon.app" 2>&1 | tail -4 || true
say "--- sizes ---"
du -sh "$dist"/* 2>/dev/null | sort -h || true

if (( fail )); then
  say "FAILED"
  exit 1
fi
say "macOS artifacts verified: image is styled, mounts, and the pkg carries the app"
