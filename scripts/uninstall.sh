#!/usr/bin/env bash
# Remove the stack installed by scripts/install.sh. Data is kept unless --purge.
set -euo pipefail
ROOT="${CRM_HOME:-$HOME/.whatsapp-crm}"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
[ -x "$ROOT/bin/crmctl" ] && "$ROOT/bin/crmctl" stop || true
if [ "$PURGE" = 1 ]; then
  read -r -p "Delete $ROOT including the database and media? [y/N] " a
  case "$a" in [yY]*) rm -rf "$ROOT"; echo "removed $ROOT" ;; *) echo "kept data" ;; esac
else
  echo "Stopped. Binaries and data remain in $ROOT (use --purge to delete)."
fi
