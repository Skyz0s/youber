# Subida a YouTube (`youber.upload`)

Módulo educativo para publicar **contenido propio** (o con licencia) en
YouTube usando la YouTube Data API v3 con OAuth 2.0.

## Requisitos

1. **OAuth Client ID**: crea unas credenciales de tipo "App de escritorio" en
   [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   y habilita la **YouTube Data API v3**.
2. Exporta las credenciales:

   ```bash
   # Windows (PowerShell)
   $env:GOOGLE_CLIENT_ID="xxxx.apps.googleusercontent.com"
   $env:GOOGLE_CLIENT_SECRET="xxxx"
   # Linux/macOS
   export GOOGLE_CLIENT_ID="xxxx.apps.googleusercontent.com"
   export GOOGLE_CLIENT_SECRET="xxxx"
   ```

3. Autoriza la app (solo una vez):

   ```bash
   youber-upload auth
   ```

   Se abre una URL, autorizas con tu cuenta y pegas el código. Los tokens se
   guardan en `~/.youber/credentials/youtube_token.json` (se refrescan solos).

## CLI

```bash
# Autenticar (una vez)
youber-upload auth

# Subir vídeo (privado por defecto, para revisar antes de publicar)
youber-upload video.mp4 --title "Mi Video" --description "..." --tags "python,tutorial" --privacy public

# Programar publicación (la API fuerza privado hasta la fecha)
youber-upload schedule video.mp4 --title "..." --publish-at "2026-09-15 10:00:00"

# Consultar estado
youber-upload status <video_id>
```

Opciones de `upload`/`schedule`:

- `--title` (obligatorio), `--description`, `--tags "a,b,c"`.
- `--category` (id de categoría; por defecto 22 = People & Blogs).
- `--privacy public|unlisted|private` (por defecto `private`).
- `--publish-at "YYYY-MM-DD HH:MM:SS"` (solo en `schedule`; fuerza `private`).

## Uso desde código

```python
import asyncio
from youber.upload import YouTubeAuth, YouTubeUploader, VideoMetadata

async def main():
    auth = YouTubeAuth()  # usa GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
    uploader = YouTubeUploader(auth)
    metadata = VideoMetadata(
        title="Mi vídeo",
        description="Hecho con BARF",
        tags=["python", "educación"],
        privacy_status="public",
    )
    resource = await uploader.upload_video("final.mp4", metadata)
    video_id = resource["id"]
    print(YouTubeUploader.get_video_url(video_id))

asyncio.run(main())
```

## Cómo funciona

- **OAuth 2.0** (`auth.py`): flujo de código de autorización (installed app)
  con refresh token automático.
- **Metadatos** (`metadata.py`): `VideoMetadata` (pydantic v2) valida título,
  tags y privacidad; `to_snippet()`/`to_status()` generan el payload de la API.
  Si hay `publish_at`, fuerza `privacyStatus=private` (requisito de la API).
- **Subida** (`youtube.py`): **subida resumable** oficial — primero un POST
  con los metadatos (recibe la URL de subida) y después un PUT con los bytes
  del vídeo. `check_status()` consulta el estado y `get_video_url()` la URL.

## Ética

Solo se publica **contenido propio o con licencia**: vídeos que tú hayas
creado con BARF (investigación + edición) o que tengas permiso de usar. Sin
spam, sin contenido malicioso y sin manipulación de métricas. Publicar tus
propias creaciones con la API oficial es completamente conforme a la ToS.
