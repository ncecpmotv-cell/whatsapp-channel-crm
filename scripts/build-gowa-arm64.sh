#!/usr/bin/env bash
# Build a Termux-compatible GOWA binary.
#
# Why this exists: the official linux-arm64 release is linked against glibc
# (libc.so.6 + ld-linux-aarch64.so.1). Termux is bionic and has no glibc
# loader, so the release fails with "required file not found".
# GOWA also needs cgo (mattn/go-sqlite3), so a pure-Go CGO_ENABLED=0 build
# compiles but dies at runtime with "go-sqlite3 requires cgo to work".
#
# The working recipe is upstream's own: Alpine + musl + cgo, but linked fully
# static so no ELF interpreter is needed on Android.
#
# Requirements: docker on any aarch64/amd64 machine (runs linux/arm64 image).
# Usage: ./build-gowa-arm64.sh [version] [output]
set -euo pipefail

VERSION="${1:-9.10.0}"
OUT="${2:-./whatsapp}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> cloning go-whatsapp-web-multidevice v${VERSION}"
git clone --depth 1 --branch "v${VERSION}" \
  https://github.com/aldinokemal/go-whatsapp-web-multidevice.git "$WORK/src"

echo "==> building static musl arm64 binary (cgo required for sqlite)"
docker run --rm \
  -v "$WORK/src:/src:ro" \
  -v "$WORK/out:/out" \
  -w /src/src \
  --platform linux/arm64 \
  golang:1.26-alpine3.23 \
  sh -c "apk add --no-cache gcc musl-dev >/dev/null && \
         CGO_ENABLED=1 GOOS=linux GOARCH=arm64 go build -trimpath \
         -ldflags '-w -s -linkmode external -extldflags \"-static\"' \
         -o /out/whatsapp ."

cp "$WORK/out/whatsapp" "$OUT"
chmod +x "$OUT"

echo "==> sanity checks"
if readelf -l "$OUT" | grep -q INTERP; then
  echo "ERROR: binary still has an ELF interpreter (not static)" >&2
  exit 1
fi
if readelf -d "$OUT" 2>/dev/null | grep -q NEEDED; then
  echo "ERROR: binary still has dynamic dependencies" >&2
  exit 1
fi
echo "OK: static arm64 binary -> $OUT ($(du -h "$OUT" | cut -f1))"
