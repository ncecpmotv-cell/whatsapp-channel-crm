# Public link from the phone (no server, no domain)

`ngrok` gives a phone-hosted EspoCRM a stable HTTPS hostname without owning a
domain and without opening any port: the agent dials out to ngrok's edge.

Free tier: one static domain (`*.ngrok-free.dev`), HTTPS, and a Basic-auth
traffic policy. Limits: monthly traffic cap and a one-time browser warning page.

## One-time setup (on the phone)

```bash
ngrok config add-authtoken <TOKEN>          # stored in ~/.config/ngrok/ngrok.yml (600)
mkdir -p ~/gowa-espo/etc
printf 'crm:%s\n' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(10))')" \
  > ~/gowa-espo/etc/ngrok-auth.txt && chmod 600 ~/gowa-espo/etc/ngrok-auth.txt
```

`~/gowa-espo/etc/ngrok-policy.yml`:

```yaml
on_http_request:
  - actions:
      - type: basic-auth
        config:
          realm: "EspoCRM"
          credentials:
            - "crm:<password>"
```

Then run the service (`scripts/runit/ngrok/run`). Target is **8081** (the CRM),
never 8080 (nginx's stock landing page).

## Why proot

`ngrok` is a Go binary and reads `/etc/resolv.conf` / `/etc/ssl/certs`, which do
not exist on Android. Without the bind-mounts it fails with
`lookup connect.ngrok-agent.com on [::1]:53: connection refused`.

## Two auth layers — and why login used to fail

| Layer | Who asks | Credentials |
|-------|----------|-------------|
| ngrok Basic-auth policy | browser dialog, before the page | `crm:<password>` |
| EspoCRM login form | the app itself | a CRM user (e.g. `admin`) |

Three things must be true or the CRM will reject valid credentials:

1. **`siteUrl` must equal the public URL.** Left at `http://127.0.0.1:8081`,
   every absolute URL/redirect points at localhost.
   `php bin/command config:set siteUrl https://<domain>`
2. **nginx must forward the Authorization header** —
   `fastcgi_param HTTP_AUTHORIZATION $http_authorization;`. PHP-FPM drops it
   otherwise; the user still authenticates via `PHP_AUTH_USER`, but EspoCRM
   never issues an auth token (`token: null` in `GET App/user`).
3. **The ngrok gate must not swallow the login header.** The front-end
   authenticates with `Espo-Authorization` (not the standard header), but a
   browser that already answered the basic-auth dialog also attaches
   `Authorization` to every request. The traffic policy therefore excludes
   `/api/` from the gate.

Verify end-to-end without a browser:

```bash
B=$(printf 'admin:PASSWORD' | base64 -w0)
TOKEN=$(curl -s -H "Espo-Authorization: $B" -H 'X-Requested-With: XMLHttpRequest' \
  https://<domain>/api/v1/App/user | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
curl -s -H "Espo-Authorization: $(printf 'admin:%s' "$TOKEN" | base64 -w0)" \
  https://<domain>/api/v1/Contact?maxSize=1
```
