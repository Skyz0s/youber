// Proxy HTTP → bridge Python (youber-api), Fase 2.
//
// Convierte peticiones bajo /youber-dashboard/api/* en llamadas al bridge:
//
//   python -m youber.api.server --route <ruta> --params '<json>'
//
// El bridge imprime el envoltorio {"ok": true, "data"|"error"} en stdout.
// Mapeo de rutas (equivalencia con docs/API.md):
//
//   GET  /api/status              → status
//   GET  /api/music/list          → music.list
//   GET  /api/music/search?query= → music.search
//   GET  /api/music/lyrics?query= → music.lyrics
//   GET  /api/discovery/search    → discovery.search
//   GET  /api/research/channel    → research.channel
//   GET  /api/schedule/list       → schedule.list
//   GET  /api/uploads/status      → uploads.status
//   GET  /api/jobs/status?id=     → jobs.status
//   GET  /api/jobs/history?limit= → jobs.history
//   POST /api/jobs                → jobs.submit (body JSON = params)
//
// Seguridad: whitelist estricta de rutas; los params se normalizan (números
// a texto, arrays a CSV); el subproceso usa el venv del repo. Las cabeceras
// CORS y el guard de loopback los pone el handler del prefijo en index.js.

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// api.js está en <repo>/plugins/youber-dashboard/src/routes
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const MAX_BODY = 1024 * 1024; // 1 MB
const BRIDGE_TIMEOUT_MS = 300_000;
const MAX_BUFFER = 20 * 1024 * 1024;

// Rutas GET/lectura permitidas: path HTTP → ruta canónica del bridge.
const READ_ROUTES = new Map([
  ["status", "status"],
  ["music/list", "music.list"],
  ["music/search", "music.search"],
  ["music/lyrics", "music.lyrics"],
  ["discovery/search", "discovery.search"],
  ["research/channel", "research.channel"],
  ["schedule/list", "schedule.list"],
  ["uploads/status", "uploads.status"],
  ["jobs/status", "jobs.status"],
  ["jobs/history", "jobs.history"],
]);

function resolvePython() {
  if (process.env.YOUBER_PYTHON) return process.env.YOUBER_PYTHON;
  const win = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
  const posix = path.join(REPO_ROOT, ".venv", "bin", "python");
  if (existsSync(win)) return win;
  if (existsSync(posix)) return posix;
  return "python";
}

/** Normaliza params HTTP → params del bridge (JSON-safe y tipados). */
function normalizeParams(raw) {
  const params = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      params[key] = value.map(String).join(",");
    } else if (typeof value === "boolean") {
      params[key] = value;
    } else if (typeof value === "number") {
      params[key] = String(value);
    } else {
      params[key] = String(value);
    }
  }
  return params;
}

function queryToParams(url) {
  const params = {};
  for (const [key, value] of url.searchParams.entries()) {
    params[key] = value;
  }
  return params;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new Error("body demasiado grande (máx 1 MB)"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function runBridge(route, params) {
  return new Promise((resolve) => {
    const args = [
      "-m",
      "youber.api.server",
      "--route",
      route,
      "--params",
      JSON.stringify(params),
    ];
    execFile(
      resolvePython(),
      args,
      { cwd: REPO_ROOT, timeout: BRIDGE_TIMEOUT_MS, maxBuffer: MAX_BUFFER },
      (error, stdout) => {
        if (error) {
          resolve({
            ok: false,
            error: `bridge falló: ${error.message}`,
            raw: stdout || "",
          });
          return;
        }
        try {
          const envelope = JSON.parse(stdout);
          resolve({ ok: envelope.ok === true, envelope });
        } catch {
          resolve({ ok: false, error: "bridge no devolvió JSON válido", raw: stdout });
        }
      }
    );
  });
}

function sendJson(res, statusCode, payload) {
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

/** Handler del proxy: path sin prefijo (ej. "music/list" o "jobs"). */
export async function handleApi(req, res, url) {
  const apiPath = url.pathname.replace(/^\/youber-dashboard\/api\/?/, "");
  const queryParams = queryToParams(url);

  // POST /api/jobs → jobs.submit
  if (req.method === "POST" && (apiPath === "jobs" || apiPath === "jobs/submit")) {
    let body = {};
    try {
      const raw = await readBody(req);
      if (raw) body = JSON.parse(raw);
    } catch (err) {
      sendJson(res, 400, { ok: false, error: err.message });
      return true;
    }
    const params = normalizeParams({ ...queryParams, ...body });
    const result = await runBridge("jobs.submit", params);
    if (!result.ok) {
      sendJson(res, result.envelope ? 200 : 502, result.envelope ?? { ok: false, error: result.error });
      return true;
    }
    sendJson(res, 200, result.envelope);
    return true;
  }

  if (req.method !== "GET") {
    sendJson(res, 405, { ok: false, error: `método no permitido: ${req.method}` });
    return true;
  }

  const route = READ_ROUTES.get(apiPath);
  if (!route) {
    sendJson(res, 404, { ok: false, error: `ruta API desconocida: ${apiPath}` });
    return true;
  }
  const params = normalizeParams(queryParams);
  const result = await runBridge(route, params);
  if (!result.ok) {
    sendJson(res, result.envelope ? 200 : 502, result.envelope ?? { ok: false, error: result.error });
    return true;
  }
  sendJson(res, 200, result.envelope);
  return true;
}
