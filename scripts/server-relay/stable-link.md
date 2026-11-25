# Stable public link (no domain, no account)

`sslip.io` maps an IP embedded in a hostname (`84-8-97-31.sslip.io` → `84.8.97.31`),
so a real Let's Encrypt certificate can be issued for the server's IP without
owning a domain.

Requirements: inbound TCP **80 and 443** open (cloud security list + host
firewall). On Oracle Cloud that is the VCN Security List; the instance's own
iptables also needs:

```bash
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 7 -p tcp --dport 443 -j ACCEPT
```

Then:

```bash
sudo cp Caddyfile.example /etc/caddy/Caddyfile
sudo cp caddy.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now caddy
```

Chain: browser → Caddy :443 (auto TLS) → 127.0.0.1:18082 (Basic auth relay)
→ phone reverse tunnel :18081 → phone nginx :8081 → EspoCRM.

`bind 10.0.0.19` pins Caddy to the private interface: Tailscale already owns
`100.86.11.20:443`, and a wildcard bind would collide.

Notes:
- The hostname is stable only while the instance keeps the same public IP —
  attach a **Reserved Public IP** (free while attached) before relying on it.
- Adding another app later = another port or path; no accounts involved.
