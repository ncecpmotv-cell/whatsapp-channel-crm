#!/usr/bin/env bash
# Deploy the edge Worker with bindings and secrets.
#
#   CF_API_TOKEN=cfut_...            bash scripts/deploy-edge.sh   # scoped token (preferred)
#   CF_EMAIL=you@example.com CF_KEY=cfk_... bash scripts/deploy-edge.sh   # legacy global key
#
# What it does, in order: verify the credential, create the R2 bucket and KV namespace
# (idempotent), write the KV id into wrangler.toml, set EDGE_TOKEN and BACKUP_KEY,
# deploy, and print the URL plus the two env lines the phone needs.
set -euo pipefail

cd "$(dirname "$0")/../edge"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

if [ -n "${CF_API_TOKEN:-}" ]; then
  export CLOUDFLARE_API_TOKEN="$CF_API_TOKEN"
elif [ -n "${CF_KEY:-}" ] && [ -n "${CF_EMAIL:-}" ]; then
  export CLOUDFLARE_API_KEY="$CF_KEY"
  export CLOUDFLARE_EMAIL="$CF_EMAIL"
else
  die "set CF_API_TOKEN (scoped) or CF_EMAIL + CF_KEY (global key)"
fi

say "verifying the credential"
npx --yes wrangler whoami >/dev/null || die "wrangler rejected the credential"

say "R2 bucket crm-backups"
npx wrangler r2 bucket create crm-backups 2>&1 | grep -v "already exists" || true

say "KV namespace STATUS"
if grep -q 'REPLACE_WITH_KV_ID' wrangler.toml; then
  out="$(npx wrangler kv namespace create STATUS 2>&1)"
  echo "$out" | tail -3
  kv_id="$(printf '%s' "$out" | grep -oE '[0-9a-f]{32}' | head -1)"
  [ -n "$kv_id" ] || die "could not read the KV id from wrangler output"
  sed -i.bak "s/REPLACE_WITH_KV_ID/$kv_id/" wrangler.toml
  say "KV id written to wrangler.toml: $kv_id"
else
  say "KV id already present in wrangler.toml"
fi

if [ -z "${EDGE_TOKEN:-}" ]; then
  EDGE_TOKEN="edge-$(openssl rand -hex 16)"
fi
if [ -z "${BACKUP_KEY:-}" ]; then
  BACKUP_KEY="$(openssl rand -base64 32 | tr -d '\n')"
  printf '\n  BACKUP_KEY (keep it in a password manager):\n  %s\n\n' "$BACKUP_KEY" >&2
fi

say "secrets"
printf '%s' "$EDGE_TOKEN" | npx wrangler secret put EDGE_TOKEN >/dev/null
printf '%s' "$BACKUP_KEY" | npx wrangler secret put BACKUP_KEY >/dev/null

say "deploying"
npx wrangler deploy 2>&1 | tee /tmp/edge-deploy.log | tail -6
url="$(grep -oE 'https://[A-Za-z0-9._-]+\.workers\.dev' /tmp/edge-deploy.log | tail -1)"

cat <<EOF

Done.

Worker URL : ${url:-<see the log above>}
Phone env  :
  EDGE_URL=${url:-https://<worker>.workers.dev}
  EDGE_TOKEN=${EDGE_TOKEN}

Keep BACKUP_KEY safe: without it the archives cannot be decrypted.
Verify with: curl -s ${url:-https://<worker>.workers.dev}/health
EOF
