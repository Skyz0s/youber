// Youber Dashboard — Fase 0 (spike técnico)
//
// Objetivo del spike: confirmar que un plugin externo puede añadir un tab a la
// Control UI (registerControlUiDescriptor) cuyo contenido se sirve desde una
// ruta HTTP del plugin (registerHttpRoute) renderizada en un iframe con
// sandbox, y documentar el mecanismo de autenticación de ese iframe.
//
// Hallazgo clave (verificado en dist/control-ui/assets/plugin-page-*.js):
// la Control UI renderiza los tabs con `path` como:
//
//   <iframe src="${path}" sandbox="${embedSandboxMode}"></iframe>
//
// El iframe NO recibe token de la UI (ni header, ni query). Por tanto el
// contenido del tab debe servirse con auth:"plugin" (auth gestionada por el
// propio plugin). Una ruta auth:"gateway" responde 401 dentro del iframe
// (aunque funcione con curl + Bearer para operadores).
//
// Seguridad v1: ruta de contenido auth:"plugin" + comprobación de origen
// loopback en el handler. Los datos sensibles nunca viajan al navegador.

const PAGE_HTML = `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Youber</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font-family: system-ui, Segoe UI, Roboto, sans-serif;
         background:#0e1116; color:#e6e6e6; display:grid; place-items:center;
         min-height:100vh; }
  .card { max-width:560px; padding:2rem; border:1px solid #2a2f3a;
          border-radius:12px; background:#161b22; text-align:center; }
  h1 { margin:0 0 .4rem; font-size:1.4rem; }
  .badge { display:inline-block; margin-bottom:1rem; padding:.2rem .6rem;
           border-radius:999px; background:#1f6feb22; color:#58a6ff;
           border:1px solid #1f6feb55; font-size:.75rem; }
  p { color:#9da7b3; line-height:1.5; }
  code { background:#0d1117; padding:.1rem .35rem; border-radius:6px;
         color:#7ee787; }
  #probe { margin-top:1rem; font-size:.85rem; }
  .ok { color:#7ee787; } .err { color:#ff7b72; }
</style>
</head>
<body>
  <div class="card">
    <span class="badge">Fase 0 · Spike técnico</span>
    <h1>Youber Dashboard</h1>
    <p>En construcción. Este tab confirma que el plugin externo se sirve
       correctamente en la Control UI (ruta <code>auth: "plugin"</code> en
       iframe con sandbox).</p>
    <p>Plugin: <code>youber-dashboard</code> · origen:
       <code id="origin">…</code></p>
    <div id="probe">Probando ruta del plugin…</div>
  </div>
  <script>
    const probe = document.getElementById("probe");
    document.getElementById("origin").textContent = window.origin;
    fetch("/youber-dashboard/ping", { method: "GET" })
      .then((r) => r.text())
      .then((t) => {
        probe.className = "ok";
        probe.textContent = "Ruta del plugin responde: " + t;
      })
      .catch((e) => {
        probe.className = "err";
        probe.textContent = "Error de fetch: " + e;
      });
  </script>
</body>
</html>`;

/** Cabeceras CORS amables para el iframe con sandbox (origen opaco). */
function corsHeaders(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
}

/** Acepta solo peticiones loopback (seguridad básica de la ruta v1). */
function isLoopback(req) {
  const addr = req.socket?.remoteAddress || "";
  return addr === "127.0.0.1" || addr === "::1" || addr === "::ffff:127.0.0.1";
}

export default {
  id: "youber-dashboard",
  name: "Youber Dashboard",
  description: "Panel nativo de Youber en la Control UI",
  version: "0.1.0",
  register(api) {
    api.session.controls.registerControlUiDescriptor({
      surface: "tab",
      id: "youber",
      label: "Youber",
      description: "Panel de control de Youber",
      icon: "dashboard",
      group: "control",
      order: 60,
      requiredScopes: ["operator.read"],
      path: "/youber-dashboard",
    });

    // Contenido del tab (auth gestionada por el plugin; el iframe no lleva
    // token de la UI). Prefix: sirve "/youber-dashboard" y subrutas.
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
          res.statusCode = 403;
          res.end("forbidden: loopback only");
          return true;
        }
        const url = new URL(req.url || "/", "http://localhost");
        if (url.pathname.endsWith("/ping")) {
          res.setHeader("Content-Type", "text/plain; charset=utf-8");
          res.statusCode = 200;
          res.end("pong (auth plugin, loopback)");
          return true;
        }
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.statusCode = 200;
        res.end(PAGE_HTML);
        return true;
      },
    });

    // Ruta de CONTRASTE para documentar el mecanismo: auth:"gateway" exige
    // el token de la Gateway (Bearer). Funciona con curl de operador, pero
    // devuelve 401 dentro del iframe del tab (que no puede enviar headers).
    api.registerHttpRoute({
      path: "/youber-gateway-probe",
      auth: "gateway",
      match: "exact",
      handler: async (_req, res) => {
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        res.statusCode = 200;
        res.end("ok (auth gateway)");
        return true;
      },
    });

    api.logger.info("Youber Dashboard: tab + rutas registradas (Fase 0)");
  },
};
