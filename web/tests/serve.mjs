// Static server for the site that sends the same security headers as the host (Cloudflare Pages reads web/_headers), so the browser test runs under the real policy.
// Adds the local API origins to connect-src for tests. Usage: node tests/serve.mjs [port] [folder]
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = process.argv[3] ? join(process.cwd(), process.argv[3]) : join(fileURLToPath(import.meta.url), "..", "..");  // optional second argument: the folder to serve (web/dist)
const port = Number(process.argv[2] ?? 8000);
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".geojson": "application/json", ".png": "image/png" };
const rules = (await readFile(join(root, "_headers"), "utf8")).split("\n").filter((line) => /^\s+\S+: /.test(line)).map((line) => line.trim().split(/: (.*)/s));
const headers = Object.fromEntries(rules.map(([key, value]) => [key, key === "Content-Security-Policy" ? value.replace("https://*.run.app", "https://*.run.app http://localhost:8080 http://127.0.0.1:8080") : value]));

createServer(async (request, response) => {
  const path = normalize(decodeURIComponent(new URL(request.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
  try {
    const file = await readFile(join(root, path.endsWith("/") ? `${path}index.html` : path));
    response.writeHead(200, { ...headers, "content-type": types[extname(path)] ?? (path.endsWith("/") ? types[".html"] : "application/octet-stream") });
    response.end(file);
  } catch {
    response.writeHead(404, headers);
    response.end("not found");
  }
}).listen(port, () => console.log(`site on http://localhost:${port} with the headers of _headers`));
