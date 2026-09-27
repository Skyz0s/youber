"""Pistas de subtítulos (captions) para YouTube.

Sube el ``.srt`` que genera :mod:`youber.sync` como **pista de subtítulos
activable** (``captions.insert``): accesibilidad, búsqueda y traducción
automática sin volver a renderizar el vídeo. La letra ya está quemada en la
imagen, pero la pista es lo que hace el vídeo accesible y localizable.

La API exige el scope ``youtube.force-ssl`` (el token de solo subida no
sirve): si al subir la pista llega un 403 de permisos, se avisa de que hay
que rehacer ``youber-upload auth``.

Solo se suben letras propias o con licencia: aquí no se descarga ni se
publica material ajeno.
"""

from __future__ import annotations

import uuid

#: Endpoint de subida de pistas (multipart/related).
CAPTIONS_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/captions"

#: Endpoint de lectura (list/delete).
CAPTIONS_API_URL = "https://www.googleapis.com/youtube/v3/captions"

#: MIME por defecto del fichero de subtítulos (SRT).
DEFAULT_CAPTION_MIME = "application/octet-stream"

#: Idioma por defecto de las pistas (los flujos de letras son en español).
DEFAULT_LANGUAGE = "es"


def build_multipart_body(
    snippet: dict,
    media: bytes,
    *,
    mime: str = DEFAULT_CAPTION_MIME,
    boundary: str | None = None,
) -> tuple[bytes, str]:
    """Cuerpo ``multipart/related`` de ``captions.insert`` (puro y testeable).

    La API de subida de YouTube espera dos partes: la primera con el JSON del
    ``snippet`` (``application/json``) y la segunda con los bytes del fichero.

    Args:
        snippet: Objeto ``snippet`` de la pista (``videoId``, ``language``...).
        media: Contenido del fichero de subtítulos (.srt).
        mime: Tipo MIME de la parte binaria.
        boundary: Separador (se genera si es ``None``).

    Returns:
        ``(cuerpo, content_type)``: los bytes del cuerpo y el valor para la
        cabecera ``Content-Type``.
    """
    import json

    sep = boundary or f"youber-{uuid.uuid4().hex}"
    head = (
        f"--{sep}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(snippet, ensure_ascii=False)}\r\n"
        f"--{sep}\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{sep}--\r\n".encode()
    return head + media + tail, f"multipart/related; boundary={sep}"


def caption_snippet(
    video_id: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    name: str | None = None,
    is_draft: bool = False,
) -> dict:
    """Construye el ``snippet`` de una pista de subtítulos.

    Args:
        video_id: Id del vídeo al que pertenece la pista.
        language: Código de idioma ISO 639-1 (por defecto ``es``).
        name: Nombre visible de la pista.
        is_draft: Si es ``True``, la pista queda como borrador (solo visible
            para el propietario) en vez de publicada.

    Returns:
        El diccionario del ``snippet`` para la API.
    """
    snippet: dict = {"videoId": video_id, "language": language}
    if name:
        snippet["name"] = name
    if is_draft:
        snippet["isDraft"] = True
    return snippet
