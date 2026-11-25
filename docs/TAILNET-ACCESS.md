# Private access over Tailscale (no public URL)

A dedicated tailnet node runs **inside Termux** and publishes only the CRM. No
port is exposed, no public hostname exists, and no shared password is needed —
identity is the device's Tailscale membership.

```
device (phone/laptop, same tailnet)
   │ WireGuard
   ▼
espocrm.tailXXXX.ts.net ── tailscaled (userspace, in Termux) ──▶ 127.0.0.1:8081
```

## How it runs

`scripts/runit/tailscaled/run` starts `tailscaled --tun=userspace-networking`
under proot. Userspace mode is the key: Android gives no `/dev/net/tun` without
root, and userspace networking needs neither root nor TUN. proot supplies the
`/etc/resolv.conf` and CA bundle that every Go binary expects on Android.

Join the node (once):

```bash
tailscale --socket=$HOME/gowa-espo/var/tailscaled.sock up \
  --hostname=espocrm --accept-dns=false --accept-routes=false
# open the printed https://login.tailscale.com/a/... URL, approve the device
```

Publish the CRM to the tailnet only:

```bash
tailscale --socket=... serve --bg --http=80 http://127.0.0.1:8081
tailscale --socket=... serve status
```

## Why http and not https

`serve --https` makes tailscaled obtain a Let's Encrypt certificate via ACME,
which needs outbound HTTPS from the node. In userspace mode that dial-out fails
(`bootstrapDNS … network is unreachable`), so the command hangs. Traffic is
already encrypted by WireGuard, so `http://` inside the tailnet is not plaintext
on the wire. If HTTPS is required, run the serve front on a machine with normal
outbound networking, or enable HTTPS certificates in the tailnet and give
tailscaled an outbound proxy.

## Access

Install Tailscale on the client device and sign in to the **same tailnet**. Then:

```
http://espocrm.tailXXXX.ts.net/
```

Devices on a *different* tailnet cannot resolve or reach it — tailnets are
isolated by design. Cross-tailnet access needs Tailscale **node sharing**.
