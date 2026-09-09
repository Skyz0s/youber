// Sirve la UI del plugin bajo /youber-dashboard/.
//
// Fuente de la UI (Fase 3): build de Vite en dist/ (SPA Lit). Si no existe
// (p.ej. antes del primer build), cae a static/ (página simple de Fase 2).
//
// Seguridad: solo ficheros dentro del directorio elegido (sin path
// traversal) y con tipos MIME explícitos por extensión.

import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(__dirname, "..", "..");
const DIST_DIR = path.join(PLUGIN_ROOT, "dist");
const STATIC_DIR = path.join(PLUGIN_ROOT, "static");
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
  ".woff2": "font/woff2",
  ".map": "application/json",
};

async function pickUiDir() {
  try {
    await stat(path.join(DIST_DIR, "index.html"));
    return DIST_DIR;
  } catch {
    return STATIC_DIR;
  }
}

function safeJoin(rootDir, relative) {
  const target = path.normalize(path.join(rootDir, relative));
  const prefix = rootDir.endsWith(path.sep) ? rootDir : rootDir + path.sep;
  if (!target.startsWith(prefix)) return null;
  return target;
}

export async function handleUi(_req, res, url) {
  const uiDir = await pickUiDir();
  let relative = decodeURIComponent(
    url.pathname.replace(new RegExp(`^${PREFIX}/?`), "")
  );
  if (!relative || relative.endsWith("/")) relative = "index.html";

  const target = safeJoin(uiDir, relative);
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
    // SPA: rutas que no son ficheros (hash routing no las genera, pero por
    // robustez servimos index.html si el cliente pide HTML).
    const acceptsHtml = (req.headers.accept || "").includes("text/html");
    if (acceptsHtml) {
      try {
        const data = await readFile(safeJoin(uiDir, "index.html"));
        res.statusCode = 200;
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(data);
        return true;
      } catch {
        /* sigue al 404 */
      }
    }
    res.statusCode = 404;
    res.end("not found");
  }
  return true;
}
