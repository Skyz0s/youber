// Sirve los estáticos de la UI (static/) bajo /youber-dashboard/.
//
// Seguridad: solo ficheros dentro del directorio static/ (sin path traversal)
// y con tipos MIME explícitos por extensión.

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = path.resolve(__dirname, "..", "..", "static");
const PREFIX = "/youber-dashboard";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
};

function safeJoin(staticDir, relative) {
  const target = path.normalize(path.join(staticDir, relative));
  const prefix = staticDir.endsWith(path.sep) ? staticDir : staticDir + path.sep;
  if (!target.startsWith(prefix)) return null;
  return target;
}

export async function handleUi(_req, res, url) {
  let relative = decodeURIComponent(
    url.pathname.replace(new RegExp(`^${PREFIX}/?`), "")
  );
  if (!relative || relative.endsWith("/")) relative = "index.html";

  const target = safeJoin(STATIC_DIR, relative);
  if (target === null) {
    res.statusCode = 403;
    res.end("forbidden");
    return true;
  }
  try {
    const data = await readFile(target);
    const ext = path.extname(target).toLowerCase();
    res.statusCode = 200;
    res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
    res.setHeader("Cache-Control", "no-store");
    res.end(data);
  } catch {
    res.statusCode = 404;
    res.end("not found");
  }
  return true;
}
