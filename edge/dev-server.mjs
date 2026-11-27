// Local adapter: runs the Worker's fetch handler on node:http, so the MCP
// endpoint can be exercised without a Cloudflare account.
//
//   EDGE_TOKEN=dev node dev-server.mjs        # http://127.0.0.1:8787/mcp
import http from "node:http";
import worker from "./src/index.js";

const env = {
  EDGE_TOKEN: process.env.EDGE_TOKEN || "dev",
  BRAVE_API_KEY: process.env.BRAVE_API_KEY || "",
  MAX_CHARS: process.env.MAX_CHARS || "6000",
};
const port = Number(process.env.PORT || 8787);

const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;

  const request = new Request(`http://127.0.0.1:${port}${req.url}`, {
    method: req.method,
    headers: req.headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : body,
  });

  try {
    const response = await worker.fetch(request, env);
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.writeHead(500, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: String(error) }));
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`edge-mcp dev on http://127.0.0.1:${port}/mcp (token: ${env.EDGE_TOKEN})`);
});
