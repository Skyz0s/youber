# Plugin `youber-dashboard` (OpenClaw)

Cómo instalar, configurar y mantener el plugin nativo de Youber para la
Control UI de OpenClaw.

## Requisitos

- OpenClaw Gateway ≥ 2026.7.1-2 (API de plugins con `registerHttpRoute` y
  `registerControlUiDescriptor`).
- Node.js ≥ 20 (para el build de Vite).
- El repo de Youber con su venv (`youber.api` es el bridge que ejecuta el
  plugin por subproceso).

## Instalación

El plugin se desarrolla en el repo (`plugins/youber-dashboard`) y se instala
enlazado, de modo que los cambios se ven sin reinstalar:

```bash
# 1. Instalar dependencias y generar el build de Vite (una vez)
cd plugins/youber-dashboard
npm ci            # reproducible: usa package-lock.json
npm run build     # genera dist/ (SPA)

# 2. Registrar el plugin en OpenClaw (enlazado)
openclaw plugins install --link C:\Users\bypau\youber\plugins\youber-dashboard

# 3. Verificar
openclaw plugins list            # Youber Dashboard vX.Y.Z enabled
```

> `dist/` y `node_modules/` están en `.gitignore`: un clon limpio necesita
> `npm ci && npm run build` antes de servir la SPA. Si `dist/` no existe, el
> plugin sirve `static/` (página mínima de Fase 2) como fallback.

## Configuración

- **Entorno**: el proxy resuelve el Python del repo (`.venv`); override con
  `YOUBER_PYTHON`. El directorio de registros de jobs se redirige con
  `YOUBER_JOBS_DIR` (por defecto `~/.youber/jobs`).
- **Sin claves en el plugin**: las credenciales viven en el entorno del
  bridge; el dashboard solo consulta *presencia* (booleanos).
- El tab aparece con el scope `operator.read`; la Gateway se reinicia tras
  cambiar el plugin (`openclaw gateway restart`).

## Estructura

```
plugins/youber-dashboard/
├── index.js            # entry: tab + prefijo HTTP /youber-dashboard
├── package.json        # metadatos + scripts (dev/build/preview)
├── vite.config.js      # base /youber-dashboard/, outDir dist/
├── src/
│   ├── tab.js          # descriptor del tab en la Control UI
│   ├── routes/
│   │   ├── ui.js       # sirve dist/ (SPA) o static/ (fallback), MIME whitelist
│   │   └── api.js      # proxy HTTP → bridge (youber.api) + descarga
│   ├── main.js / App.js / pages/* / components/* / api/client.js / styles/
├── static/index.html   # fallback sin build
└── dist/               # build de Vite (generado, no versionado)
```

## Superficie HTTP

Todo bajo `auth:"plugin"`, solo loopback, con CORS para el iframe del tab:

| Ruta | Método | Función |
| --- | --- | --- |
| `/youber-dashboard/` | GET | SPA (dist) o estático |
| `/youber-dashboard/ping` | GET | pong (healthcheck) |
| `/youber-dashboard/api/status` | GET | estado agregado |
| `/youber-dashboard/api/music/*` | GET | list/search/lyrics |
| `/youber-dashboard/api/discovery/search` | GET | búsqueda de canales |
| `/youber-dashboard/api/research/channel` | GET | datos públicos de canal |
| `/youber-dashboard/api/schedule/list` | GET | tareas programadas |
| `/youber-dashboard/api/uploads/status` | GET | estado de subida a YouTube |
| `/youber-dashboard/api/jobs/status` | GET | estado de un job |
| `/youber-dashboard/api/jobs/history` | GET | historial de jobs |
| `/youber-dashboard/api/jobs` | POST | lanza un job (produce/workflow/upload) |
| `/youber-dashboard/api/jobs/download?id=` | GET | descarga el artefacto (solo `done`, dentro de jobs dir) |
| `/youber-gateway-probe` | GET | contraste: exige token de Gateway (401 sin él) |

## Modelo de seguridad (Fase 4)

1. **auth:"plugin" + loopback**: la ruta no exige token de la Gateway (el
   iframe del tab va con sandbox y sin token); el acceso se restringe a
   `127.0.0.1`/`::1`.
2. **Origin guard**: se rechazan orígenes no loopback (`403` sin CORS) →
   un sitio web abierto en el mismo navegador no puede llamar a la API
   local (anti drive-by). Orígenes válidos: sin `Origin`, `Origin: null`
   (iframe sandbox) y orígenes loopback.
3. **Sin secretos en el navegador**: solo booleanos de presencia.
4. **Path traversal**: la descarga valida el id (`[A-Za-z0-9_-]+`) y que la
   ruta resuelta esté dentro de `YOUBER_JOBS_DIR`; `ui.js` usa `safeJoin`.
5. **Jobs**: el bridge construye argv con **whitelist por tipo** (nunca
   shell) y rechaza valores que empiezan por `-`; el id de `jobs.status` se
   valida antes de tocar el disco.
6. **CORS/iframe**: las respuestas llevan `Access-Control-Allow-Origin`
   para el origen opaco y `X-Content-Type-Options: nosniff`.

## Desarrollo

```bash
cd plugins/youber-dashboard
npm run dev      # Vite dev server (HMR) — para iterar el frontend
npm run build    # build de producción a dist/
npm test         # (no hay suite JS propia; los tests viven en el repo Python)
```

Tras tocar `index.js`/`src/routes/*` hace falta reiniciar la Gateway para
recargar el runtime del plugin. Los cambios en `dist/` se sirven al momento
(el handler lee de disco por petición).

## Versiones

| Versión | Fase | Contenido |
| --- | --- | --- |
| 0.2.0 | Fase 2 | Estructura modular + proxy `/api/*` → bridge + UI estática |
| 0.3.0 | Fase 3 | SPA Vite+Lit: 5 páginas + polling de jobs + descarga |
| 0.4.0 | Fase 4 | Hardening (origin guard, nosniff, validación de ids), errores humanos, confirmaciones, hints, polling con backoff |

## Guía de uso

Para usar el dashboard (páginas, flujos y solución de problemas):
[DASHBOARD.md](DASHBOARD.md).
