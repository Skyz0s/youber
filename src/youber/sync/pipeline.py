"""Integración de letras sincronizadas en los flujos de producción.

Helpers de alto nivel usados por ``youber-produce --sync`` y
``youber-workflow --sync``:

1. :func:`find_sidecar_lyrics`: busca un fichero de letra junto al audio
   (``<canción>.lrc`` / ``.srt`` / ``.json`` / ``.txt``).
2. :func:`build_sync_document`: letra explícita o sidecar (alineada tal cual
   si ya está temporizada, rough si es texto plano) o transcripción Whisper.
3. :func:`sync_video_with_track`: añade la canción como banda sonora (si el
   vídeo no tiene audio propio) y quema los subtítulos sincronizados.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from youber.audio.editor import replace_audio
from youber.sync.aligner import LyricsAligner
from youber.sync.renderer import RenderResult, SubtitleRenderer, SubtitleStyle
from youber.sync.timestamps import LyricsDocument, SyncError

# Orden de preferencia para el sidecar de letra junto al audio.
_SIDECAR_ORDER = (".lrc", ".srt", ".json", ".txt")


def find_sidecar_lyrics(audio_path: str | Path) -> Path | None:
    """Busca un fichero de letra junto al audio (mismo nombre, otro sufijo)."""
    audio = Path(audio_path)
    for suffix in _SIDECAR_ORDER:
        candidate = audio.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


async def build_sync_document(
    audio_path: str | Path,
    lyrics_file: str | Path | None = None,
    *,
    whisper: bool = False,
    model: str = "small",
    language: str | None = None,
) -> LyricsDocument:
    """Construye el documento de letra temporizado para un audio.

    Fuentes, por orden: fichero explícito (``lyrics_file``) → sidecar junto
    al audio (``.lrc``/``.srt``/``.json``/``.txt``) → transcripción Whisper
    (solo si ``whisper=True``).
    """
    audio = Path(audio_path)
    explicit = Path(lyrics_file) if lyrics_file is not None else None
    if explicit is not None and not explicit.is_file():
        raise SyncError(f"Letra no encontrada: {explicit}")

    source = explicit or find_sidecar_lyrics(audio)
    if source is not None:
        # Letra ya temporizada (LRC/SRT) se usa tal cual; texto plano se
        # alinea (rough o Whisper según la petición).
        return await LyricsAligner().align(
            audio,
            source,
            model_size=model if whisper else None,
            language=language,
        )
    if whisper:
        return await LyricsAligner().align(
            audio, None, model_size=model, language=language
        )
    raise SyncError(
        f"No hay letra para sincronizar con {audio.name}. Coloca un fichero "
        f"{audio.stem}.lrc/.txt/.srt junto a la canción, pasa --lyrics "
        "<fichero>, o usa --whisper para transcribir el audio."
    )


async def sync_video_with_track(
    video: str | Path,
    audio: str | Path,
    output: str | Path | None = None,
    *,
    lyrics_file: str | Path | None = None,
    whisper: bool = False,
    model: str = "small",
    language: str | None = None,
    style: SubtitleStyle | None = None,
    add_audio: bool = True,
) -> RenderResult:
    """Sincroniza la letra de ``audio`` y la quema sobre ``video``.

    Args:
        video: vídeo de entrada.
        audio: canción del catálogo (su letra se sincroniza a SU audio).
        output: ruta final (default: ``<video>_sync.mp4``). Si coincide con
            la entrada, el fichero se sustituye tras el render.
        add_audio: si ``True`` (default), la canción pasa a ser la banda
            sonora del vídeo (para montajes sin pista de audio). Si
            ``False``, se asume que el vídeo ya contiene la canción y solo
            se queman los subtítulos.

    Returns:
        RenderResult con la ruta final, duración y resolución.
    """
    document = await build_sync_document(
        audio,
        lyrics_file,
        whisper=whisper,
        model=model,
        language=language,
    )

    video_path = Path(video)
    target = (
        Path(output)
        if output is not None
        else video_path.with_name(f"{video_path.stem}_sync.mp4")
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="youber_sync_"))
    try:
        source_video = video_path
        if add_audio:
            # El montaje de youber-produce sale sin pista de audio: la canción
            # pasa a ser la banda sonora (sustitución, no mezcla amix).
            mixed = workdir / "with_audio.mp4"
            await replace_audio(str(video_path), str(audio), str(mixed))
            source_video = mixed

        burned = workdir / "burned.mp4"
        result = await SubtitleRenderer(style=style).render(
            source_video, document, output=burned
        )
        os.replace(burned, target)
        return RenderResult(
            output_path=target,
            duration=result.duration,
            resolution=result.resolution,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
