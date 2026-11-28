/**
 * Ops endpoints for edge-mcp: encrypted off-device backups, heartbeat/status,
 * and Workers AI helpers (speech-to-text, image captioning).
 *
 * Bindings (wrangler.toml):
 *   BACKUPS  R2 bucket        encrypted archives
 *   STATUS   KV namespace     heartbeat + backup index
 *   AI       Workers AI       whisper / llava
 * Secrets:
 *   EDGE_TOKEN   bearer for every write endpoint
 *   BACKUP_KEY   base64 32-byte AES-GCM key
 */

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };
const MAX_BACKUP_BYTES = 25 * 1024 * 1024;
const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const MAX_IMAGE_BYTES = 6 * 1024 * 1024;
const KEEP_BACKUPS = 30;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export function authorised(request, env) {
  const auth = request.headers.get("authorization") || "";
  const token = auth.replace(/^Bearer\s+/i, "");
  const expected = env.EDGE_TOKEN || "";
  if (!expected || token.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= token.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

export function b64ToBytes(value) {
  const binary = atob(value);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

async function key(env) {
  if (!env.BACKUP_KEY) throw new Error("BACKUP_KEY is not configured");
  return await crypto.subtle.importKey("raw", b64ToBytes(env.BACKUP_KEY), "AES-GCM", false,
                                       ["encrypt", "decrypt"]);
}

export async function encrypt(bytes, env) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cipher = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv },
                                                            await key(env), bytes));
  const out = new Uint8Array(iv.length + cipher.length);
  out.set(iv, 0);
  out.set(cipher, iv.length);
  return out;
}

export async function decrypt(packed, env) {
  const iv = packed.slice(0, 12);
  const body = packed.slice(12);
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv }, await key(env), body));
}

// ---------------------------------------------------------------- backups
export async function handleBackupPut(request, env, url) {
  if (!env.BACKUPS) return json({ error: "R2 binding BACKUPS is missing" }, 501);
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BACKUP_BYTES) return json({ error: "archive too large" }, 413);
  const raw = new Uint8Array(await request.arrayBuffer());
  if (!raw.length) return json({ error: "empty body" }, 400);
  if (raw.length > MAX_BACKUP_BYTES) return json({ error: "archive too large" }, 413);

  const name = (url.searchParams.get("name") || `crm-${Date.now()}.tar.gz`)
    .replace(/[^A-Za-z0-9._-]/g, "");
  const packed = await encrypt(raw, env);
  const keyName = `backups/${name}.enc`;

  await env.BACKUPS.put(keyName, packed, {
    httpMetadata: { contentType: "application/octet-stream" },
    customMetadata: { plainSize: String(raw.length), uploadedAt: new Date().toISOString() },
  });
  const index = (await env.STATUS.get("backup:index", "json")) || [];
  index.unshift({ name, plainSize: raw.length, packedSize: packed.length,
                  at: new Date().toISOString() });
  const kept = index.slice(0, KEEP_BACKUPS);
  for (const old of index.slice(KEEP_BACKUPS)) {
    await env.BACKUPS.delete(`backups/${old.name}.enc`).catch(() => {});
  }
  await env.STATUS.put("backup:index", JSON.stringify(kept));
  return json({ ok: true, name, plainSize: raw.length, packedSize: packed.length,
                kept: kept.length });
}

export async function handleBackupList(env) {
  const index = (await env.STATUS.get("backup:index", "json")) || [];
  return json({ ok: true, count: index.length, backups: index });
}

export async function handleBackupGet(env, url) {
  if (!env.BACKUPS) return json({ error: "R2 binding BACKUPS is missing" }, 501);
  const name = (url.searchParams.get("name") || "").replace(/[^A-Za-z0-9._-]/g, "");
  if (!name) return json({ error: "name is required" }, 400);
  const object = await env.BACKUPS.get(`backups/${name}.enc`);
  if (!object) return json({ error: "not found" }, 404);
  const plain = await decrypt(new Uint8Array(await object.arrayBuffer()), env);
  return new Response(plain, {
    headers: { "content-type": "application/gzip",
               "content-disposition": `attachment; filename="${name}"` },
  });
}

// ---------------------------------------------------------------- status
export async function handleHeartbeat(request, env) {
  let payload = {};
  try {
    payload = await request.json();
  } catch {
    return json({ error: "invalid json" }, 400);
  }
  const beat = {
    at: new Date().toISOString(),
    posts: Number(payload.posts || 0),
    scheduled: Number(payload.scheduled || 0),
    gowa: Boolean(payload.gowa),
    version: String(payload.version || ""),
    backup: String(payload.backup || ""),
  };
  await env.STATUS.put("heartbeat", JSON.stringify(beat), { expirationTtl: 86400 });
  return json({ ok: true });
}

export function renderStatus(beatRaw, backupsRaw, now = Date.now()) {
  const beat = beatRaw ? JSON.parse(beatRaw) : null;
  const backups = backupsRaw ? JSON.parse(backupsRaw) : [];
  const ageMinutes = beat ? Math.round((now - Date.parse(beat.at)) / 60000) : null;
  const state = !beat ? "لا نبضة بعد" : ageMinutes <= 15 ? "يعمل" : "متوقف عن الإرسال";
  const lastBackup = backups[0]
    ? `${backups[0].name} · ${Math.round(backups[0].plainSize / 1024)}KB · ${backups[0].at}`
    : "لا نسخ بعد";
  const html = `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>حالة CRM</title>
<style>body{font-family:system-ui;background:#151a17;color:#e8e4da;margin:0;padding:24px}
.card{max-width:560px;margin:0 auto;background:#1d241f;border:1px solid #2e3a31;border-radius:14px;padding:20px}
h1{font-size:20px;margin:0 0 12px}.ok{color:#8fd694}.warn{color:#e0b062}
p{margin:6px 0;color:#b9c2b9}code{color:#e8e4da}</style></head>
<body><div class="card"><h1>حالة النظام</h1>
<p>الحالة: <b class="${state === "يعمل" ? "ok" : "warn"}">${state}</b>
${ageMinutes === null ? "" : ` · آخر نبضة قبل ${ageMinutes} دقيقة`}</p>
${beat ? `<p>منشورات: <code>${beat.posts}</code> · مجدول: <code>${beat.scheduled}</code>
 · واتساب: <code>${beat.gowa ? "متصل" : "غير متصل"}</code> · إصدار: <code>${beat.version}</code></p>` : ""}
<p>آخر نسخة احتياطية: <code>${lastBackup}</code></p>
<p>نسخ محفوظة: <code>${backups.length}</code></p>
</div></body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8",
                                         "cache-control": "no-store" } });
}

export async function handleStatus(env) {
  const beat = await env.STATUS.get("heartbeat");
  const backups = await env.STATUS.get("backup:index");
  return renderStatus(beat, backups);
}

// ---------------------------------------------------------------- AI
// Models get deprecated on a schedule (llava-1.5 died 2026-11-20, whisper-turbo no longer
// answers Arabic), so speech walks a list and vision uses one multimodal chat model that
// accepts a data-URI image and returns strict JSON.
const TRANSCRIBE_MODELS = ["@cf/openai/whisper-large-v3-turbo", "@cf/openai/whisper"];
const VISION_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct";

function toBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function looseJson(text) {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end <= start) return null;
  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return null;
  }
}

export async function handleTranscribe(request, env) {
  if (!env.AI) return json({ error: "AI binding is missing" }, 501);
  const raw = new Uint8Array(await request.arrayBuffer());
  if (!raw.length) return json({ error: "empty audio" }, 400);
  if (raw.length > MAX_AUDIO_BYTES) return json({ error: "audio too large" }, 413);
  const errors = [];
  for (const model of TRANSCRIBE_MODELS) {
    try {
      const result = await env.AI.run(model, { audio: Array.from(raw) });
      const text = (result.text || "").trim();
      if (text) return json({ ok: true, text, model });
      errors.push(`${model}: empty transcript`);
    } catch (error) {
      errors.push(`${model}: ${error.message || error}`);
    }
  }
  return json({ error: errors.join(" | "), model: "whisper" }, 502);
}

export async function handleCaption(request, env) {
  if (!env.AI) return json({ error: "AI binding is missing" }, 501);
  const raw = new Uint8Array(await request.arrayBuffer());
  if (!raw.length) return json({ error: "empty image" }, 400);
  if (raw.length > MAX_IMAGE_BYTES) return json({ error: "image too large" }, 413);
  const mime = (request.headers.get("content-type") || "image/jpeg").split(";")[0];
  const prompt = "صف الصورة في سطر عربي واحد، ثم أعط ثلاث هاشتاقات مناسبة. "
    + 'أجب بصيغة JSON فقط: {"description":"","hashtags":["#"]}';
  try {
    const result = await env.AI.run(VISION_MODEL, {
      messages: [{
        role: "user",
        content: [
          { type: "text", text: prompt },
          { type: "image_url", image_url: { url: `data:${mime};base64,${toBase64(raw)}` } },
        ],
      }],
      max_tokens: 300,
    });
    const content = result?.choices?.[0]?.message?.content
      ?? result?.description ?? result?.response ?? "";
    const text = String(content).trim();
    const parsed = looseJson(text);
    if (parsed?.description) {
      const hashtags = Array.isArray(parsed.hashtags)
        ? parsed.hashtags.filter((tag) => typeof tag === "string").slice(0, 5) : [];
      return json({
        ok: true,
        description: parsed.description,
        hashtags,
        text: [parsed.description, hashtags.join(" ")].filter(Boolean).join("\n\n"),
        model: VISION_MODEL,
      });
    }
    if (text) return json({ ok: true, text, model: VISION_MODEL });
    return json({ error: "empty description", model: VISION_MODEL }, 502);
  } catch (error) {
    return json({ error: String(error.message || error), model: VISION_MODEL }, 502);
  }
}
