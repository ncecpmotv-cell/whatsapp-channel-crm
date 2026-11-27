# 0003 — Authenticated media: upload limits, storage, previews

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.0.0
- **Roadmap:** R-02
- **Files:** `bridge/app.py`, `bridge/ui.py`

## Why

The UI advertised a 20 MB media cap while the HTTP layer rejected anything above 1 MiB, so
every real photo failed **silently** — the form returned "choose a file" and the owner
blamed the phone. Uploaded files were also invisible: no route served them, so a saved
image could not be checked before publishing.

## How

- `MAX_BODY` is 26 MiB (20 MiB payload + multipart overhead) and an oversized request gets
  an explicit `413` instead of an empty body.
- Extensions are whitelisted per content type (`image` → jpg/png/webp/gif, …); anything else
  returns `error=media_type` without creating a post.
- Files are stored under a random 12-hex name in `MEDIA_DIR`.
- `GET /ui/media/{name}` requires the UI credentials, matches `MEDIA_NAME_RE` (hex name +
  allowed extension), serves from `MEDIA_DIR` only, and sets a private cache header. `../`
  and unknown names return 404.
- PNG/GIF/JPEG dimensions are read from the file header at upload and stored in `meta`, so
  the post page can emit `width`/`height` and reserve space (CLS 0.215 → 0).

Decision worth noting: no transcoding and no thumbnailing on the device. A phone cannot
afford an image pipeline, and WhatsApp re-encodes anyway; previews use the original file
with `object-fit: contain`.

## Verify

```bash
# 2 MiB upload (previously failed)
POST /ui/content/new (multipart) → 200, file 2,097,152 bytes on disk
GET /ui/media/<name>             → 200 image/png   (with credentials)
GET /ui/media/<name>             → 401             (without)
GET /ui/media/../../etc/passwd   → 404
POST with filename evil.exe      → redirect ?error=media_type, no post created
```

Lighthouse on a post with an image: performance 90 → 100, CLS 0.215 → 0.

## Limits

- The browser's date/type inputs are the only validation of what the file *is*; the server
  trusts the extension, not the MIME sniff. Acceptable because files are never executed.
- No quota: media grows with the archive until the owner deletes files.
- Video/audio previews depend on the phone's codecs.

## Links

- `docs/API-MCP.md#ui-routes`
- `docs/ARCHITECTURE.md`
- CHANGELOG: "Media support…"
