/**
 * Radar: the edge half. Fetches free RSS feeds on a cron, de-duplicates against a rolling
 * seen-set, and stores one compact batch in KV. It never calls a model on the cron path — the
 * phone asks for a summarised angle only when the owner actually looks, so the 40-calls/day AI
 * budget is spent on demand, not on 48 empty runs.
 *
 * KV keys
 *   radar:latest  { fetchedAt, items: [{id,title,url,source,published}] }
 *   radar:seen    [hash, …] last 500
 *   radar:feeds   ["https://…", …] optional override
 */

const DEFAULT_FEEDS = [
  "https://feeds.bbci.co.uk/arabic/rss.xml",
  "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9",
  "https://aitnews.com/feed/",
];

const MAX_ITEMS = 40;
const MAX_SEEN = 500;
const FETCH_TIMEOUT = 8000;

function jsonLocal(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function feedList(env) {
  try {
    const raw = env.RADAR_FEEDS;
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) return parsed.slice(0, 10);
    }
  } catch {
    /* fall through to the defaults */
  }
  return DEFAULT_FEEDS;
}

export function decodeEntities(value) {
  const map = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&apos;": "'" };
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&(amp|lt|gt|quot|#39|apos);/g, (match) => map[match] || match)
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const tag = (block, name) => {
  const match = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  return match ? decodeEntities(match[1]) : "";
};

/** RSS <item> and Atom <entry> in one pass; no XML parser exists in the Workers runtime. */
export function parseFeed(xml, source) {
  const blocks = [
    ...xml.matchAll(/<item[\s>][\s\S]*?<\/item>/gi),
    ...xml.matchAll(/<entry[\s>][\s\S]*?<\/entry>/gi),
  ].map((match) => match[0]);

  const items = [];
  for (const block of blocks.slice(0, 15)) {
    const title = tag(block, "title");
    let link = tag(block, "link");
    if (!link) {
      const href = block.match(/<link[^>]*href="([^"]+)"/i);
      link = href ? decodeEntities(href[1]) : "";
    }
    const published = tag(block, "pubDate") || tag(block, "updated") || tag(block, "published");
    if (!title || !/^https?:\/\//.test(link)) continue;
    items.push({ title: title.slice(0, 200), url: link, source, published });
  }
  return items;
}

async function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { "user-agent": "crm-radar/1.0 (+https://github.com/ncecpmotv-cell/whatsapp-channel-crm)" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } finally {
    clearTimeout(timer);
  }
}

async function hash(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function handleRadarIngest(env) {
  const feeds = feedList(env);
  const settled = await Promise.allSettled(feeds.map((url) => fetchWithTimeout(url)));
  const failures = [];
  const fresh = [];

  for (let i = 0; i < feeds.length; i += 1) {
    const result = settled[i];
    if (result.status !== "fulfilled") {
      failures.push({ feed: feeds[i], error: String(result.reason?.message || result.reason) });
      continue;
    }
    const source = new URL(feeds[i]).hostname.replace(/^www\./, "");
    for (const item of parseFeed(result.value, source)) {
      fresh.push({ ...item, id: await hash(item.url) });
    }
  }

  const seen = (await env.STATUS.get("radar:seen", "json")) || [];
  const seenSet = new Set(seen);
  const unique = [];
  for (const item of fresh) {
    if (seenSet.has(item.id)) continue;
    seenSet.add(item.id);
    unique.push(item);
  }

  const previous = (await env.STATUS.get("radar:latest", "json")) || { items: [] };
  const merged = [...unique, ...(previous.items || [])].slice(0, MAX_ITEMS);
  const fetchedAt = new Date().toISOString();

  await env.STATUS.put("radar:latest", JSON.stringify({ fetchedAt, items: merged }));
  await env.STATUS.put("radar:seen", JSON.stringify([...seenSet].slice(-MAX_SEEN)));
  return jsonLocal({ ok: true, fetchedAt, feeds: feeds.length, newItems: unique.length,
                     kept: merged.length, failures });
}

export async function handleRadar(env) {
  const batch = (await env.STATUS.get("radar:latest", "json")) || { fetchedAt: null, items: [] };
  return jsonLocal({ ok: true, ...batch, count: (batch.items || []).length });
}

/** One model call for a handful of headlines — only when the owner asks for angles. */
export async function handleRadarSummarize(request, env) {
  if (!env.AI) return jsonLocal({ error: "AI binding is missing" }, 501);
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonLocal({ error: "invalid json" }, 400);
  }
  const titles = Array.isArray(body.titles) ? body.titles.filter((t) => typeof t === "string") : [];
  if (!titles.length) return jsonLocal({ error: "titles is required" }, 400);
  if (titles.length > 6) return jsonLocal({ error: "at most 6 titles" }, 400);

  const prompt = "لكل عنوان خبر، اقترح زاوية محتوى عربية واحدة قصيرة (سطر واحد) تصلح لقناة واتساب، "
    + "ولا تكرر الخبر نفسه. أجب بصيغة JSON فقط: {\"angles\":[{\"i\":0,\"angle\":\"...\"}]}";
  try {
    const result = await env.AI.run("@cf/meta/llama-4-scout-17b-16e-instruct", {
      messages: [{ role: "user", content: `${prompt}\n\n${titles.map((t, i) => `${i}. ${t}`).join("\n")}` }],
      max_tokens: 400,
    });
    const content = result?.choices?.[0]?.message?.content ?? result?.response ?? "";
    const start = String(content).indexOf("{");
    const end = String(content).lastIndexOf("}");
    let angles = [];
    if (start !== -1 && end > start) {
      try {
        angles = JSON.parse(String(content).slice(start, end + 1)).angles || [];
      } catch {
        angles = [];
      }
    }
    return jsonLocal({ ok: true, angles, model: "@cf/meta/llama-4-scout-17b-16e-instruct" });
  } catch (error) {
    return jsonLocal({ error: String(error.message || error) }, 502);
  }
}
