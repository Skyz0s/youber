# youber-dashboard — Plugin de Control UI (Fase 0: spike)

Panel nativo de **Youber** dentro de la Control UI de OpenClaw
(`http://localhost:18789`). Fuente versionada en el repo de Youber e
instalada con `openclaw plugins install --link` (un enlace al repo, así el
código fuente vive solo en git).

## Entregable Fase 0

- Tab **Youber** en el sidebar de la Control UI (solo visible con el plugin
  habilitado).
- HTML estático servido por el plugin (página "En construcción" con un ping
  en vivo a la ruta del plugin).
- **Mecanismo de autenticación del iframe confirmado** (ver abajo).

## Cómo se añade el tab (API real, sin `ui.pages`)

`openclaw.plugin.json` **no** tiene sección `ui.pages`: es solo metadatos
(configSchema, activation, contracts…). El tab se registra en runtime:

```js
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

export default {
  id: "youber-dashboard",
  register(api) {
    api.session.controls.registerControlUiDescriptor({
      surface: "tab",
      id: "youber",
      label: "Youber",
      description: "Panel de control de Youber",
      icon: "dashboard",
      group: "control",        // "control" | "agent"
      requiredScopes: ["operator.read"],
      path: "/youber-dashboard",
    });
    api.registerHttpRoute({
      path: "/youber-dashboard",
      auth: "plugin",          // "gateway" | "plugin"
      match: "prefix",
      handler: async (req, res) => { /* servir HTML/JSON */ return true; },
    });
  },
};
```

## Hallazgo clave — auth del iframe (spike)

Verificado en el bundle de la Control UI
(`dist/control-ui/assets/plugin-page-*.js`): los tabs con `path` se renderizan
como:

```html
<iframe src="${path}" sandbox="${embedSandboxMode}"></iframe>
```

- El iframe **no recibe token** de la UI (ni header `Authorization`, ni query,
  ni cookie inyectada). Navega a `path` tal cual.
- Consecuencia: el contenido del tab debe servirse con **`auth: "plugin"`**
  (auth gestionada por el propio plugin). Una ruta `auth: "gateway"` responde
  `401` dentro del iframe (aunque funcione con `curl` + `Bearer` para
  operadores).
- `sandbox` por defecto = modo `scripts` (origen opaco, sin `allow-same-origin`):
  - El HTML/JS del iframe se ejecuta.
  - `fetch()` del iframe a rutas del plugin es cross-origin → las respuestas
    necesitan CORS (`Access-Control-Allow-Origin: *`) y el servidor debe
    aceptar `OPTIONS`. Nuestro handler ya lo hace.
  - El plugin no puede leer el token/localStorage de la UI (aislamiento real).

### Medidas de seguridad v1 (Fase 0)

- Ruta de contenido con `auth: "plugin"` **+ guard de loopback** en el
  handler (solo `127.0.0.1`/`::1`): la página solo se sirve a la propia
  máquina.
- Los secretos (API keys de Pexels/YouTube/Spotify, tokens OAuth) **nunca
  viajan al navegador**: viven en `~/.youber` / `.env` y el plugin solo
  reportará "configurado sí/no".
- Ruta de contraste `/youber-gateway-probe` con `auth: "gateway"`: documenta
  que la auth de Gateway funciona para operadores (curl con token → 200;
  sin token → 401) pero no dentro del iframe.
- Más adelante (Fase 4): acciones de escritura con `requiredScopes:
  operator.write`, y revisar si la UI ofrece postMessage de token al iframe
  (no observado en el bundle actual).

## Comandos útiles

```bash
openclaw plugins list                        # estado
openclaw plugins inspect youber-dashboard --runtime --json
openclaw plugins install --link <repo>/plugins/youber-dashboard
openclaw plugins enable youber-dashboard
openclaw gateway restart                     # necesario tras cambios
# rutas (con auth de gateway para operador):
#   GET /youber-dashboard            → 200 HTML (auth plugin + loopback)
#   GET /youber-dashboard/ping       → 200 "pong"
#   GET /youber-gateway-probe        → 200 con Bearer; 401 sin token
```

## Fases siguientes

1. **Fase 1**: bridge Python `youber.api` (JSON, testable) — comandos
   status/music/discovery/schedule/jobs.
2. **Fase 2**: plugin runtime → rutas `/youber/api/*` que ejecutan el bridge
   + job runner para `produce`/`workflow` (subproceso + estado en fichero).
3. **Fase 3**: UI Vite+Lit (5 páginas) servida por el plugin, consumiendo
   `/youber/api/*` desde el iframe (CORS ya contemplado).
4. **Fase 4**: scopes de escritura, redacción de secretos, docs finales.
