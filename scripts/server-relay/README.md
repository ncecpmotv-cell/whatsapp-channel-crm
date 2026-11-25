# Optional: public link via Cloudflare quick tunnel

Gives the phone-hosted EspoCRM a reachable HTTPS URL **without** opening any
port and **without** a Cloudflare account. The URL is random and changes when
the tunnel restarts — for a stable hostname use a named tunnel on your own
domain (needs a Cloudflare account + zone).

```
browser → Cloudflare → relay.py (Basic auth) → 127.0.0.1:18082
        → phone's SSH reverse forward 18081 → phone nginx 8081 → EspoCRM
```

## On the phone

`scripts/runit/webforward/run` keeps `ssh -R 127.0.0.1:18081:127.0.0.1:8081`
alive. The server must allow that port for the phone's key:

```
permitlisten="127.0.0.1:18081"
```

## On the server

```bash
sudo install -d /opt/cf-relay
sudo cp relay.py /opt/cf-relay/
printf 'RELAY_USER=crm\nRELAY_PASS=%s\n' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  | sudo tee /opt/cf-relay/relay.env >/dev/null
sudo chmod 600 /opt/cf-relay/relay.env
sudo cp cf-relay.service /etc/systemd/system/
sudo systemctl enable --now cf-relay

# quick tunnel (ephemeral URL)
sudo cloudflared tunnel --no-autoupdate --url http://127.0.0.1:18082
```

## Security

- The public URL is useless without the Basic credentials; EspoCRM's own login
  is a second layer.
- Only the CRM is published. The bridge (`8085`) and GOWA (`3000`) stay on the
  phone's loopback.
- Rotate: edit `relay.env`, `systemctl restart cf-relay`.
- Nothing is stored in Cloudflare beyond the tunnel itself.
