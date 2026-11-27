#!/usr/bin/env bash
# Update a phone/termux install from the public repo, without git.
#
#   bash scripts/phone-update.sh                 # update ~/crm from main
#   CRM_HOME=~/crm bash scripts/phone-update.sh # explicit root
#   bash scripts/phone-update.sh --restart      # restart crm after copying
#
# It copies code and skills only. The database (var/), the env file and media are
# never touched: the update can be re-run safely.
set -euo pipefail

ROOT="${CRM_HOME:-$HOME/crm}"
REPO="${CRM_REPO:-ncecpmotv-cell/whatsapp-channel-crm}"
BRANCH="${CRM_BRANCH:-main}"
RESTART=0
[ "${1:-}" = "--restart" ] && RESTART=1

say() { printf '==> %s\n' "$*"; }
die() { printf '[x] %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || die "curl is required"
command -v tar  >/dev/null || die "tar is required"
[ -d "$ROOT/bridge" ] || die "no bridge/ under $ROOT — set CRM_HOME"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

say "downloading $REPO@$BRANCH"
# codeload caches tarballs for a few minutes; without the cache-buster an update can
# silently re-install the previous commit (observed: a fix "deployed" but not present).
curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
  "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH?cb=$(date +%s)" \
  -o "$tmp/src.tgz" || die "download failed (is the repo public?)"
say "archive $(wc -c <"$tmp/src.tgz" | tr -d ' ') bytes, sha $(sha256sum "$tmp/src.tgz" | cut -c1-12)"
tar xzf "$tmp/src.tgz" -C "$tmp"
src="$(find "$tmp" -maxdepth 1 -type d -name '*-*' | head -1)"
[ -d "$src/bridge" ] || die "unexpected archive layout"

if [ -d "$ROOT/bridge/__pycache__" ]; then rm -rf "$ROOT/bridge/__pycache__"; fi
say "copying bridge/ and scripts/"
mkdir -p "$ROOT/bridge" "$ROOT/scripts"
cp -R "$src/bridge/." "$ROOT/bridge/"
cp -R "$src/scripts/." "$ROOT/scripts/" 2>/dev/null || true
[ -d "$src/picoclaw/skills" ] && mkdir -p "$ROOT/picoclaw" && cp -R "$src/picoclaw/." "$ROOT/picoclaw/"

if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/var/service/crm" ]; then
  if [ -d "$ROOT/picoclaw/skills" ] && [ -d "$HOME/pico" ]; then
    cp -R "$ROOT/picoclaw/skills/." "$HOME/pico/skills/" 2>/dev/null || true
    say "skills refreshed in ~/pico/skills"
  fi
  if [ "$RESTART" = 1 ]; then
    say "restarting crm"
    SVDIR="$PREFIX/var/service" sv restart crm
    sleep 4
    curl -fsS -m 5 http://127.0.0.1:8085/health && echo
  else
    say "code copied — apply with: sv restart crm"
  fi
else
  say "code copied to $ROOT (no runit service detected)"
fi
