# Subida a TikTok (Content Posting API)

Módulo `youber.upload.tiktok` + CLI `youber-tiktok`. Publica **contenido propio** en
TikTok con la API oficial. Nada de automatizar el navegador: el ToS de TikTok prohíbe la
publicación automatizada por vías no oficiales y eso pondría la cuenta en riesgo.

## Los dos modos

| Modo | Endpoint | Cuándo |
| --- | --- | --- |
| **Bandeja de entrada** (`inbox`) | `/v2/post/publish/inbox/video/init/` | App **no auditada**. El vídeo aparece como borrador en el perfil y se termina de publicar en la app. Solo necesita el scope `video.upload`. |
| **Post directo** (`direct`) | `/v2/post/publish/video/init/` | App auditada y con *Direct Post* habilitado + scope `video.publish`. Publica sin intervención humana. Sin auditoría, todo sale restringido a `SELF_ONLY`. |

## Requisitos previos (una sola vez)

1. Crear una app en <https://developers.tiktok.com/> y añadir el producto **Content Posting API**.
2. Configurar la *redirect URI* (p. ej. `https://localhost:8765/callback`) en la app.
3. Pedir los scopes `user.info.basic`, `video.upload` y, si se quiere post directo, `video.publish`.
4. Guardar las credenciales en `~/.youber/credentials/tiktok_client.json`:

   ```json
   {"client_key": "...", "client_secret": "..."}
   ```

   o definirlas como `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`.

Los tokens viven en `~/.youber/credentials/tiktok_token.json`. Con `YOUBER_ACCOUNT=<cuenta>`
se guardan en `~/.youber/credentials/<cuenta>/`, igual que en YouTube, para convivir con
varias cuentas.

## Uso

```bash
# 1. Autorizar: imprime la URL, autorizas en el navegador y pegas la URL de vuelta
youber-tiktok auth --redirect-uri https://localhost:8765/callback
youber-tiktok auth --exchange "https://localhost:8765/callback?code=XXXX&state=..."

# 2. Ver el creador y sus límites (duración máxima, opciones de privacidad)
youber-tiktok whoami

# 3. Subir a la bandeja de entrada (borrador para terminar en el móvil)
youber-tiktok upload short.mp4

# 4. Post directo (solo con app auditada)
youber-tiktok upload video.mp4 --mode direct --title "Da un paso hacia mi" --privacy public

# 5. Estado de una publicación
youber-tiktok status v_pub_file~v2-1.123456789
```

## Cómo funciona la subida

1. `creator_info/query` — opciones de privacidad y duración máxima permitida.
2. `init` — devuelve `publish_id` + `upload_url`.
3. `PUT` del fichero en **chunks secuenciales** con `Content-Range`. Reglas de TikTok:
   5 MB ≤ chunk ≤ 64 MB (el último absorbe el resto, hasta 128 MB), entre 1 y 1000
   chunks; los ficheros de menos de 5 MB van enteros en una petición.
   `plan_chunks(size)` calcula los rangos y es una función pura, testeada sin red.
4. `status/fetch` hasta `PUBLISH_COMPLETE` (o `SEND_TO_USER_INBOX`).

`TikTokUploader.publish()` encadena los cuatro pasos y devuelve
`{"publish_id", "upload_url", "uploaded_bytes", "status"}`.

## Errores

`TikTokAPIError` lleva `code`, `message` y `log_id`. Los códigos habituales:

- `scope_not_authorized` / `access_token_invalid` → repetir `youber-tiktok auth`.
- `url_ownership_unverified` → solo afecta a `PULL_FROM_URL` (aquí se sube por fichero).
- `spam_risk_too_many_posts` / `rate_limit_exceeded` → espaciar las subidas.

## Límites que conviene conocer

- **No auditada**: el contenido publicado directamente queda en `SELF_ONLY` (privado).
  Por eso el modo por defecto del CLI es `inbox`.
- **Música comercial**: el contenido debe ser propio o con licencia; TikTok no permite
  usar audio de su catálogo comercial vía API.
- La cuenta debe tener el perfil de creador y cumplir los requisitos de la app.
