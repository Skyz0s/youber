// Youber Dashboard — Fase 2 (plugin runtime + bridge)
//
// Registra el tab "Youber" en la Control UI y un prefijo HTTP auth:"plugin"
// que enruta:
//
//   GET  /youber-dashboard/            → UI estática (src/routes/ui.js)
//   GET  /youber-dashboard/ping        → pong
//   GET  /youber-dashboard/api/<ruta>  → proxy al bridge (src/routes/api.js)
//   POST /youber-dashboard/api/jobs    → jobs.submit vía bridge
//
// El tab se renderiza en un iframe con sandbox (sin token de la UI), por lo
// que el contenido se sirve con auth:"plugin" + guard de loopback; las
// respuestas llevan CORS para el origen opaco del iframe.

import { registerTab } from "./src/tab.js";
import { handleApi } from "./src/routes/api.js";
import { handleUi } from "./src/routes/ui.js";

/** Cabeceras CORS amables para el iframe con sandbox (origen opaco). */
function corsHeaders(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
}

/** Acepta solo peticiones loopback (la Control UI corre en esta máquina). */
function isLoopback(req) {
  const addr = req.socket?.remoteAddress || "";
  return addr === "127.0.0.1" || addr === "::1" || addr === "::ffff:127.0.0.1";
}

function sendText(res, status, text, contentType = "text/plain; charset=utf-8") {
  res.statusCode = status;
  res.setHeader("Content-Type", contentType);
  res.end(text);
}

export default {
  id: "youber-dashboard",
  name: "Youber Dashboard",
  description: "Panel nativo de Youber en la Control UI",
  version: "0.2.0",
  register(api) {
    registerTab(api);

    api.registerHttpRoute({
      path: "/youber-dashboard",
      auth: "plugin",
      match: "prefix",
      handler: async (req, res) => {
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
      "Youber Dashboard (Fase 2): tab + UI estática + proxy /api/* → youber.api"
    );
  },
};
