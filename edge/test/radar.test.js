import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";
import { decodeEntities, parseFeed } from "../src/radar.js";

const TOKEN = "secret";

const RSS = `<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
<item><title>الذكاء الاصطناعي يغيّر غرف الأخبار</title>
<link>https://example.com/a</link><pubDate>Wed, 26 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title><![CDATA[ثلاث أدوات مجانية للفيديو &amp; الصوت]]></title>
<link>https://example.com/b</link></item>
<item><title>بلا رابط</title></item>
</channel></rss>`;

const ATOM = `<feed><entry><title>خبر أتوم</title>
<link href="https://example.com/atom"/><updated>2026-11-26T09:00:00Z</updated></entry></feed>`;

function fakeEnv(extra = {}) {
  const store = new Map();
  return {
    EDGE_TOKEN: TOKEN,
    STATUS: {
      async get(key, type) {
        const raw = store.get(key);
        if (raw === undefined) return null;
        return type === "json" ? JSON.parse(raw) : raw;
      },
      async put(key, value) { store.set(key, value); },
    },
    AI: {
      async run() {
        return { choices: [{ message: { content: '{"angles":[{"i":0,"angle":"لماذا يهم هذا؟"}]}' } }] };
      },
    },
    _store: store,
    ...extra,
  };
}

const auth = { authorization: `Bearer ${TOKEN}` };

test("parseFeed reads both RSS and Atom and skips entries without a link", () => {
  const items = parseFeed(RSS, "example.com");
  assert.equal(items.length, 2);
  assert.equal(items[0].title, "الذكاء الاصطناعي يغيّر غرف الأخبار");
  assert.equal(items[1].title, "ثلاث أدوات مجانية للفيديو & الصوت");
  const atom = parseFeed(ATOM, "example.com");
  assert.equal(atom[0].url, "https://example.com/atom");
});

test("decodeEntities strips CDATA, tags and named entities", () => {
  assert.equal(decodeEntities("<![CDATA[نص <b>عريض</b> &amp; أكثر]]>"), "نص عريض & أكثر");
});

test("ingest stores a batch and the second run does not duplicate it", async () => {
  const env = fakeEnv({ RADAR_FEEDS: JSON.stringify(["https://feed.test/rss"]) });
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(RSS, { status: 200 });
  try {
    const first = await (await worker.fetch(new Request("https://edge.test/radar/ingest", {
      method: "POST", headers: auth,
    }), env)).json();
    assert.equal(first.ok, true);
    assert.equal(first.newItems, 2);

    const second = await (await worker.fetch(new Request("https://edge.test/radar/ingest", {
      method: "POST", headers: auth,
    }), env)).json();
    assert.equal(second.newItems, 0);

    const batch = await (await worker.fetch(new Request("https://edge.test/radar", { headers: auth }), env)).json();
    assert.equal(batch.count, 2);
    assert.match(batch.items[0].id, /^[0-9a-f]{16}$/);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("a dead feed is reported, not fatal", async () => {
  const env = fakeEnv({ RADAR_FEEDS: JSON.stringify(["https://feed.test/dead"]) });
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("nope", { status: 503 });
  try {
    const body = await (await worker.fetch(new Request("https://edge.test/radar/ingest", {
      method: "POST", headers: auth,
    }), env)).json();
    assert.equal(body.ok, true);
    assert.equal(body.failures.length, 1);
    assert.match(body.failures[0].error, /503/);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("summarize returns angles and refuses more than six titles", async () => {
  const env = fakeEnv();
  const ok = await (await worker.fetch(new Request("https://edge.test/radar/summarize", {
    method: "POST", headers: auth, body: JSON.stringify({ titles: ["عنوان"] }),
  }), env)).json();
  assert.equal(ok.ok, true);
  assert.equal(ok.angles[0].angle, "لماذا يهم هذا؟");

  const tooMany = await worker.fetch(new Request("https://edge.test/radar/summarize", {
    method: "POST", headers: auth, body: JSON.stringify({ titles: Array(7).fill("t") }),
  }), env);
  assert.equal(tooMany.status, 400);
});

test("radar endpoints require the bearer token", async () => {
  const env = fakeEnv();
  const response = await worker.fetch(new Request("https://edge.test/radar"), env);
  assert.ok([401, 403].includes(response.status));
});
