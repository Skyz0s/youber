// Youber Dashboard — plugin runtime (Fases 2-4)
//
// Registra el tab "Youber" en la Control UI y un prefijo HTTP auth:"plugin"
// que enruta:
//
//   GET  /youber-dashboard/            → UI (dist/ de Vite, fallback static/)
//   GET  /youber-dashboard/ping        → pong
//   GET  /youber-dashboard/api/<ruta>  → proxy al bridge (src/routes/api.js)
//   POST /youber-dashboard/api/jobs    → jobs.submit vía bridge
//   GET  /youber-dashboard/api/jobs/download?id= → artefacto de un job
//
// Modelo de seguridad (Fase 4):
//  - auth:"plugin": la ruta NO pide token de la Gateway (el iframe del tab va
//    con sandbox y origen opaco, sin token). El acceso se limita a loopback.
//  - Comprobación de Origin: solo se sirven peticiones SIN cabecera Origin
//    (curl, misma-origen) o con "Origin: null" (iframe sandbox de la Control
//    UI). Cualquier otro origen (un sitio web abierto en el mismo navegador)
//    recibe 403 sin cabeceras CORS → no puede leer respuestas ni lanzar jobs
//    contra 127.0.0.1 (drive-by localhost).
//  - Las respuestas llevan CORS (ACAO *) solo para orígenes permitidos.
//  - X-Content-Type-Options: nosniff en todo el prefijo.

import { registerTab } from "./src/tab.js";
import { handleApi } from "./src/routes/api.js";
import { handleUi } from "./src/routes/ui.js";

/** Cabeceras CORS para el iframe con sandbox (origen opaco). */
function corsHeaders(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("X-Content-Type-Options", "nosniff");
}

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

/**
 * Un origen externo (sitio web) no debe poder hablar con 127.0.0.1.
 * Permitido: sin Origin (curl/misma-origen), "null" (iframe sandbox de la
 * Control UI) u orígenes loopback (p.ej. abrir el dashboard en una pestaña
 * directa http://127.0.0.1:<puerto>). Cualquier otro origen → 403 sin CORS.
 */
function originAllowed(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  if (origin === "null") return true;
  try {
    const host = new URL(origin).hostname;
    return LOOPBACK_HOSTS.has(host);
  } catch {
    return false;
  }
}

/** Acepta solo peticiones loopback (la Control UI corre en esta máquina). */
function isLoopback(req) {
  const addr = req.socket?.remoteAddress || "";
  return addr === "127.0.0.1" || addr === "::1" || addr === "::ffff:127.0.0.1";
}

function sendText(res, status, text, contentType = "text/plain; charset=utf-8") {
  res.statusCode = status;
  res.setHeader("Content-Type", contentType);
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.end(text);
}

export default {
  id: "youber-dashboard",
  name: "Youber Dashboard",
  description: "Panel nativo de Youber en la Control UI",
  version: "0.4.0",
  register(api) {
    registerTab(api);

    api.registerHttpRoute({
      path: "/youber-dashboard",
      auth: "plugin",
      match: "prefix",
      handler: async (req, res) => {
        if (!originAllowed(req)) {
          sendText(res, 403, "forbidden: origin not allowed");
          return true;
        }
        corsHeaders(res);
        if (req.method === "OPTIONS") {
          res.statusCode = 204;
          res.end();
          return true;
        }
        if (!isLoopback(req)) {
          sendText(res, 403, "forbidden: loopback only");
          return true;
        }
        const url = new URL(req.url || "/", "http://localhost");
        const pathname = url.pathname;
        if (pathname === "/youber-dashboard/ping" || pathname.endsWith("/ping")) {
          sendText(res, 200, "pong (auth plugin, loopback)");
          return true;
        }
        if (pathname.startsWith("/youber-dashboard/api/")) {
          await handleApi(req, res, url);
          return true;
        }
        await handleUi(req, res, url);
        return true;
      },
    });

    // Ruta de contraste: auth:"gateway" exige el token de la Gateway
    // (funciona con curl + Bearer; 401 dentro del iframe del tab).
    api.registerHttpRoute({
      path: "/youber-gateway-probe",
      auth: "gateway",
      match: "exact",
      handler: async (_req, res) => {
        sendText(res, 200, "ok (auth gateway)");
        return true;
      },
    });

    api.logger.info(
      "Youber Dashboard (Fase 4): tab + UI Vite/Lit (dist) + proxy /api/* → youber.api (hardened)"
    );
  },
};
