import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";
import { decrypt, encrypt, renderStatus } from "../src/ops.js";

const TOKEN = "secret";
const KEY = Buffer.from("0123456789abcdef0123456789abcdef").toString("base64");

function fakeEnv(extra = {}) {
  const store = new Map();
  const objects = new Map();
  return {
    EDGE_TOKEN: TOKEN,
    BACKUP_KEY: KEY,
    STATUS: {
      async get(key, type) {
        const raw = store.get(key);
        if (raw === undefined) return null;
        return type === "json" ? JSON.parse(raw) : raw;
      },
      async put(key, value, opts = {}) {
        store.set(key, value);
        return opts;
      },
    },
    BACKUPS: {
      async put(key, bytes, opts = {}) {
        // Monotonic timestamps: real uploads are seconds apart, tests are microseconds apart.
        const uploaded = new Date(Date.now() + objects.size);
        objects.set(key, { bytes, uploaded, customMetadata: opts.customMetadata || {} });
      },
      async get(key) {
        const hit = objects.get(key);
        return hit ? { arrayBuffer: async () => hit.bytes } : null;
      },
      async delete(key) { objects.delete(key); },
      async list({ prefix = "" } = {}) {
        return {
          objects: [...objects.entries()]
            .filter(([key]) => key.startsWith(prefix))
            .map(([key, value]) => ({
              key, size: value.bytes.length, uploaded: value.uploaded,
              customMetadata: value.customMetadata,
            })),
        };
      },
    },
    AI: {
      async run(model, input) {
        if (model.includes("whisper")) return { text: " مرحبا من الصوت " };
        return { description: "صورة منتج على طاولة #منتج" };
      },
    },
    _store: store,
    _objects: objects,
    ...extra,
  };
}

function post(path, body, { token = TOKEN, headers = {} } = {}) {
  return new Request(`https://edge.test${path}`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...headers },
    body,
  });
}

test("status page reports a fresh heartbeat", async () => {
  const env = fakeEnv();
  await worker.fetch(post("/heartbeat", JSON.stringify({ posts: 40, scheduled: 1, gowa: true,
                                                          version: "4.0.0" })), env);
  const response = await worker.fetch(new Request("https://edge.test/status"), env);
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(html, /يعمل/);
  assert.match(html, /40/);
  assert.match(html, /واتساب/);
});

test("status page says stale when the beat is old", async () => {
  const env = fakeEnv();
  env._store.set("heartbeat", JSON.stringify({ at: new Date(Date.now() - 3600_000).toISOString(),
                                                posts: 1, scheduled: 0, gowa: false }));
  const html = await (await worker.fetch(new Request("https://edge.test/status"), env)).text();
  assert.match(html, /متوقف عن الإرسال/);
});

test("backup round-trips through encryption", async () => {
  const env = fakeEnv();
  const payload = new TextEncoder().encode("archive-bytes-".repeat(100));
  const put = await worker.fetch(
    post("/backup?name=crm-test.tar.gz", payload, { headers: { "content-type": "application/gzip" } }),
    env);
  assert.equal(put.status, 200);
  const stored = [...env._objects.values()][0].bytes;
  assert.ok(!new TextDecoder().decode(stored).includes("archive-bytes"));
  const got = await worker.fetch(
    new Request("https://edge.test/backup?name=crm-test.tar.gz",
                { headers: { authorization: `Bearer ${TOKEN}` } }), env);
  assert.equal(got.status, 200);
  const round = new Uint8Array(await got.arrayBuffer());
  assert.deepEqual([...round], [...payload]);
});

test("backup index lists what was uploaded", async () => {
  const env = fakeEnv();
  await worker.fetch(post("/backup?name=a.tar.gz", new Uint8Array([1, 2, 3])), env);
  const body = await (await worker.fetch(
    new Request("https://edge.test/backup", { headers: { authorization: `Bearer ${TOKEN}` } }), env
  )).json();
  assert.equal(body.count, 1);
  assert.equal(body.backups[0].name, "a.tar.gz");
});

test("retention keeps the newest three and deletes the rest", async () => {
  const env = fakeEnv();
  for (const name of ["a", "b", "c", "d"]) {
    const response = await worker.fetch(post(`/backup?name=${name}.tar.gz`, new Uint8Array([1, 2, 3])), env);
    assert.equal(response.status, 200);
  }
  const body = await (await worker.fetch(
    new Request("https://edge.test/backup", { headers: { authorization: `Bearer ${TOKEN}` } }), env
  )).json();
  assert.equal(body.count, 3);
  assert.equal(env._objects.size, 3);
  assert.equal(body.backups[0].name, "d.tar.gz");
  assert.ok(![...env._objects.keys()].some((key) => key.includes("a.tar.gz")));
});

test("a full storage budget refuses the upload instead of billing", async () => {
  const env = fakeEnv({ MAX_TOTAL_MB: "0.001" });
  const response = await worker.fetch(post("/backup?name=big.tar.gz", new Uint8Array(4096)), env);
  assert.equal(response.status, 507);
  assert.equal((await response.json()).limit, true);
});

test("ops endpoints reject a wrong token", async () => {
  const env = fakeEnv();
  const response = await worker.fetch(post("/heartbeat", "{}", { token: "nope" }), env);
  assert.equal(response.status, 401);
});

test("transcribe returns whisper text", async () => {
  const env = fakeEnv();
  const response = await worker.fetch(post("/ai/transcribe", new Uint8Array([1, 2, 3])), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.match(body.text, /مرحبا/);
});

test("caption returns an Arabic one-liner", async () => {
  const env = fakeEnv();
  const body = await (await worker.fetch(post("/ai/caption", new Uint8Array([9, 9])), env)).json();
  assert.match(body.text, /منتج/);
});

test("ai failures are reported, not swallowed", async () => {
  const env = fakeEnv({ AI: { async run() { throw new Error("model requires Workers Paid"); } } });
  const body = await (await worker.fetch(post("/ai/caption", new Uint8Array([1])), env)).json();
  assert.match(body.error, /Paid/);
});

test("encrypt/decrypt helpers round-trip", async () => {
  const env = fakeEnv();
  const data = new TextEncoder().encode("hello");
  const packed = await encrypt(data, env);
  assert.notDeepEqual([...packed.slice(12)], [...data]);
  const back = await decrypt(packed, env);
  assert.equal(new TextDecoder().decode(back), "hello");
});

test("status renders without a heartbeat", () => {
  const html = renderStatus(null, null);
  return html.text().then((text) => assert.match(text, /لا نبضة بعد/));
});
