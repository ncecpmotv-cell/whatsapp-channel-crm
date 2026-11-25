# Keeping the stack alive on Huawei EMUI

Android will happily kill Termux when the screen turns off. Three layers are
needed; missing any one of them causes "it worked, then died overnight".

## 1. Termux wakelock

```bash
termux-wake-lock
```

Add it to `~/.termux/boot/00-server.sh` (install the **Termux:Boot** app so
that file runs at boot), or run it after every restart of the phone.

## 2. EMUI battery: manual launch management

Huawei's task killer is more aggressive than stock Android. On EMUI 9.x:

1. **Settings → Battery → App launch**
2. Find **Termux** → turn **Manage automatically** OFF
3. Enable all three:
   - **Auto-launch**
   - **Secondary launch**
   - **Run in background**
4. **Settings → Battery → More battery settings** → disable **Power-intensive
   prompt** for Termux (optional, only removes a nag dialog).

## 3. Disable battery optimisation for Termux

1. **Settings → Apps → Apps → Termux → Battery**
2. Choose **Unrestricted** / **Don't optimise**
3. Also check **Settings → Battery → Optimise battery usage → All apps →
   Termux → Don't optimise**

## Verify it survives

```bash
# lock the screen, wait 10 minutes, then:
sv status gowa bridge mariadb php-fpm nginx
curl -s http://127.0.0.1:8085/health
```

If `gowa` is `down`, EMUI killed the process tree — re-check step 2.

## RAM headroom

Reference device: 2.69 GB total, ~600 MB available with Android running.

```bash
free -m
```

Idle footprint of the stack is roughly 150 MB; peak (a channel post with media)
is ~450 MB. If `available` drops under ~150 MB, Android starts reclaiming and
you will see restarts. Levers, in order of impact:

1. `pm.max_children` in the PHP-FPM pool (default 4 → 2)
2. `innodb_buffer_pool_size` (48M → 32M)
3. Disable the EspoCRM UI you do not use (heavy pages are the peak)
4. `--auto-download-media=false` in GOWA (already the default here)
