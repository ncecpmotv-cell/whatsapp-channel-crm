#!/data/data/com.termux/files/usr/bin/bash
# Audit the phone's footprint and (optionally) remove only provably-safe cruft.
#
#   bash scripts/audit-clean.sh            # dry run: report + savings, delete nothing
#   bash scripts/audit-clean.sh --apply    # delete the SAFE set only
#
# Never touches: ~/gowa-espo/.env, gowa-espo/storages (WhatsApp session),
# databases, the git repo, or any EspoCRM application file.
set -uo pipefail
APPLY=0
AGGRESSIVE=0
for arg in "$@"; do
  [ "$arg" = "--apply" ] && APPLY=1
  [ "$arg" = "--aggressive" ] && AGGRESSIVE=1
done
H="${HOME:-/data/data/com.termux/files/home}"
P="${PREFIX:-/data/data/com.termux/files/usr}"

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
size() { du -sh "$1" 2>/dev/null | cut -f1; }
have() { [ -e "$1" ]; }

say "host"
free -m | sed -n '1,2p'
df -h "$H" | tail -1

say "top disk consumers in \$HOME"
du -sh "$H"/* 2>/dev/null | sort -rh | head -12

say "running footprint (top RSS)"
ps -eo rss,args --sort=-rss 2>/dev/null | head -10

say "cleanup candidates"

CANDIDATES=()

add_candidate() { # path, label, kind(file|dir|pkgcache|pycache|svlog)
  local path="$1" label="$2" kind="$3"
  if [ "$kind" = "pkgcache" ]; then
    local s; s=$(du -sh "$path" 2>/dev/null | cut -f1)
    [ -n "$s" ] && printf '  %-8s %-45s %s\n' "${s:-–}" "$label" "$path"
    CANDIDATES+=("$kind|$path")
    return
  fi
  if [ "$kind" = "pycache" ]; then
    local total=0
    while IFS= read -r d; do
      local b; b=$(du -sb "$d" 2>/dev/null | cut -f1); total=$((total + ${b:-0}))
    done < <(python3 - "$H" <<'PY'
import pathlib, sys
for p in pathlib.Path(sys.argv[1]).rglob("__pycache__"):
    print(p)
PY
)
    if [ "$total" -gt 0 ]; then
      printf '  %-8s %-45s %s\n' "$(numfmt --to=iec "$total" 2>/dev/null || echo "${total}B")" "$label" "(all __pycache__)"
      CANDIDATES+=("$kind|")
    fi
    return
  fi
  if have "$path"; then
    printf '  %-8s %-45s %s\n' "$(size "$path")" "$label" "$path"
    CANDIDATES+=("$kind|$path")
  fi
}

add_candidate "$P/var/cache/apt/archives" "Termux downloaded .deb cache" pkgcache
add_candidate "" "Python bytecode caches" pycache
add_candidate "$H/install_espo_sanad.sh" "leftover EspoCRM installer script" file
add_candidate "$H/espo_user.py" "scratch script" file
add_candidate "$H/espo_key2.py" "scratch script" file
add_candidate "$H/espo_key3.py" "scratch script" file
add_candidate "$H/espo_fix_auth.py" "scratch script" file
add_candidate "$H/espo_role.py" "scratch script" file
add_candidate "$H/espo_role2.py" "scratch script" file
add_candidate "$H/role_dbg.py" "scratch script" file
add_candidate "$H/role_err.py" "scratch script" file
add_candidate "$H/role_post.py" "scratch script" file
add_candidate "$H/role_shapes.py" "scratch script" file
add_candidate "$H/role_final.py" "scratch script" file
add_candidate "$H/role_stream.py" "scratch script" file
add_candidate "$H/role_add_note.py" "scratch script" file
add_candidate "$H/e2e_in.py" "scratch script" file
add_candidate "$H/note_test.py" "scratch script" file
add_candidate "$H/qr.png" "stale QR image" file
add_candidate "$H/gowa-espo/qr.png" "stale QR image" file
add_candidate "$H/gowa-espo/qr.json" "stale QR json" file
add_candidate "$H/t" "legacy experiment binaries (memos/pocketbase/dufs)" dir
add_candidate "$H/hermes-agent" "unused Hermes source checkout (re-clonable)" dir
add_candidate "$P/var/service/mysqld" "retired duplicate MariaDB unit" dir
add_candidate "$P/var/log/sv/mysqld" "retired MariaDB unit logs" dir

say "old rotated service logs"
find "$P/var/log/sv" -type f \( -name '@*' -o -name '*.s' \) -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -10 || true

if [ "$APPLY" -eq 0 ]; then
  say "DRY RUN — nothing deleted"
  echo "Re-run with --apply to remove the safe set."
  echo "Add --aggressive to also remove the large legacy directories (t/, hermes-agent/)."
  exit 0
fi

say "applying"
for entry in "${CANDIDATES[@]:-}"; do
  [ -z "${entry:-}" ] && continue
  kind="${entry%%|*}"; path="${entry#*|}"
  case "$kind" in
    pkgcache) pkg clean >/dev/null 2>&1 && echo "pkg clean: done" ;;
    pycache) python3 - "$H" <<'PY'
import pathlib, shutil, sys
n = 0
for p in pathlib.Path(sys.argv[1]).rglob("__pycache__"):
    shutil.rmtree(p, ignore_errors=True); n += 1
print(f"removed {n} __pycache__ dirs")
PY
    ;;
    file) rm -f "$path" && echo "removed $path" ;;
    dir)
      if [ "$AGGRESSIVE" -eq 1 ]; then
        rm -rf "$path" && echo "removed $path"
      else
        echo "SKIPPED (needs --aggressive): $path"
      fi
      ;;
  esac
done

say "trim old rotated logs"
find "$P/var/log/sv" -type f \( -name '@*' -o -name '*.s' \) -delete 2>/dev/null || true
echo "rotated logs trimmed"

if [ -x "$P/bin/php" ] && [ -f "$H/sanad/espocrm/bin/command" ]; then
  ( cd "$H/sanad/espocrm" && php bin/command clear-cache >/dev/null 2>&1 && echo "espocrm cache cleared" )
fi

say "after"
df -h "$H" | tail -1
free -m | sed -n '2p'
