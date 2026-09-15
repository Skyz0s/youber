"""Construcción de decisiones a partir de las ejecuciones del workflow.

Traduce lo que acaba de pasar en una ejecución de ``youber-workflow``
(metadatos investigados, perfil temático, canción elegida, prompt, guion y
vídeo renderizado) a un :class:`DecisionRecord` listo para guardar en el
journal. La traducción vive aquí —y no en la CLI— para poder testearla sin
tocar red, FFmpeg ni el catálogo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from youber.journal.models import (
    ContentAttributes,
    DecisionRecord,
    TrackCandidate,
    TrackDecision,
    UploadRecord,
    VideoArtifact,
)
from youber.music.lyrics_analyzer import LyricsAnalysis
from youber.music.models import Mood, Track
from youber.music.selector import TrackMatch, score_breakdown
from youber.research.data_models import ChannelData

#: Patrón para sacar el id de un vídeo de una URL de YouTube.
VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})")


def video_id_from_url(url: str | None) -> str | None:
    """Extrae el id de vídeo de una URL de YouTube (o ``None``)."""
    if not url:
        return None
    match = VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def attributes_from_insights(
    insights: Mapping[str, Any],
    *,
    topic: str = "",
    source: str | None = None,
    profile: LyricsAnalysis | None = None,
    keywords: Sequence[str] = (),
    target_duration: float | None = None,
    metadata_text: str | None = None,
) -> ContentAttributes:
    """Atributos del contenido a partir de los insights de un canal.

    Args:
        insights: Salida de :func:`youber.research.patterns.channel_overview`.
        topic: Tema del vídeo propio.
        source: Canal/vídeo de referencia.
        profile: Perfil temático del contenido (temas + sentimiento).
        keywords: Palabras clave del vídeo (B-roll / contenido).
        target_duration: Duración objetivo en segundos.
        metadata_text: Texto completo de los metadatos (para contar palabras).

    Returns:
        Los :class:`ContentAttributes` que el algoritmo «vio» al decidir.
    """
    hashtags = [
        str(entry.get("hashtag"))
        for entry in (insights.get("top_hashtags") or [])
        if entry.get("hashtag")
    ]
    return ContentAttributes(
        topic=topic,
        source=source,
        themes=dict(profile.themes) if profile is not None else {},
        dominant_theme=profile.dominant_theme if profile is not None else None,
        sentiment=profile.sentiment if profile is not None else "neutral",
        keywords=list(dict.fromkeys(keywords)),
        hashtags=hashtags,
        title_patterns=dict(insights.get("title_patterns") or {}),
        videos_analyzed=int(insights.get("videos_count") or 0),
        metadata_words=len((metadata_text or "").split()),
        target_duration=float(target_duration or 0.0),
    )


def _candidate(match: TrackMatch, rank: int) -> TrackCandidate:
    """Convierte un :class:`TrackMatch` en candidata con puesto."""
    return TrackCandidate(
        rank=rank,
        track_id=match.track_id,
        title=match.title,
        artist=match.artist,
        score=match.score,
        matched_themes=list(match.matched_themes),
        reason=match.reason,
    )


def track_decision_from_match(
    match: TrackMatch | None,
    *,
    candidates: Sequence[TrackMatch] = (),
    track: Track | None = None,
    profile: LyricsAnalysis | None = None,
    mood: Mood | None = None,
    keywords: Sequence[str] = (),
    forced: bool = False,
    catalog_size: int = 0,
) -> TrackDecision:
    """Decisión de banda sonora a partir de la canción elegida y sus rivales.

    Guarda las señales del scoring (tema, sentimiento, mood, keywords,
    favorita, uso previo) tal y como las calculó
    :func:`youber.music.selector.score_breakdown`.
    """
    decision = TrackDecision(
        forced=forced,
        catalog_size=catalog_size,
        candidates=[_candidate(candidate, rank) for rank, candidate in enumerate(candidates, 1)],
    )
    if match is None:
        return decision

    decision.chosen_id = match.track_id
    decision.chosen_title = match.title
    decision.chosen_artist = match.artist
    decision.score = match.score
    decision.reason = match.reason
    decision.matched_themes = list(match.matched_themes)

    if track is not None:
        decision.duration_seconds = round(float(track.duration), 3)
        breakdown = score_breakdown(
            track,
            themes=profile.themes if profile is not None else {},
            sentiment=profile.sentiment if profile is not None else "neutral",
            mood=mood,
            keywords=keywords,
        )
        decision.theme_score = round(breakdown.theme_score, 4)
        decision.sentiment_match = breakdown.sentiment_match
        decision.mood_match = breakdown.mood_match
        decision.favorite = track.favorite
        decision.usage_count = track.usage_count
        decision.keyword_hits = breakdown.keyword_hits
    if not decision.candidates:
        decision.candidates = [_candidate(match, 1)]
    return decision


def _video_artifact(
    path: str | Path | None,
    *,
    duration: float | None = None,
    clip_count: int = 0,
    clip_source: str = "none",
    scene_count: int = 0,
    music_mood: Mood | None = None,
) -> VideoArtifact:
    """Resume el vídeo generado (ruta, tamaño y procedencia de los clips)."""
    artifact = VideoArtifact(
        path=str(path) if path else None,
        duration_seconds=duration,
        clip_count=clip_count,
        clip_source=clip_source,
        scene_count=scene_count,
        music_mood=music_mood.value if music_mood is not None else None,
    )
    if path:
        real = Path(path)
        try:
            artifact.size_bytes = real.stat().st_size if real.is_file() else None
        except OSError:  # pragma: no cover - sistema de ficheros exótico
            artifact.size_bytes = None
    return artifact


def record_from_lyrics_run(
    *,
    topic: str,
    channel: ChannelData,
    insights: Mapping[str, Any],
    profile: LyricsAnalysis,
    match: TrackMatch | None = None,
    candidates: Sequence[TrackMatch] = (),
    chosen_track: Track | None = None,
    forced: bool = False,
    catalog_size: int = 0,
    prompt: str = "",
    keywords: Sequence[str] = (),
    target_duration: float | None = None,
    scenes: int = 0,
    music_mood: Mood | None = None,
    artifacts: Mapping[str, str] | None = None,
    video_path: str | Path | None = None,
    video_duration: float | None = None,
    clip_count: int = 0,
    clip_source: str = "none",
    mode: str = "html",
    run_id: str | None = None,
    metadata_text: str | None = None,
    notes: str = "",
) -> DecisionRecord:
    """Decisión completa del flujo ``--lyrics-video``.

    Returns:
        El :class:`DecisionRecord` con atributos, decisión de canción,
        artefactos y vídeo generado (sin subida ni métricas: eso llega luego).
    """
    source = channel.name
    return DecisionRecord(
        run_id=run_id,
        topic=topic,
        source_channel=channel.name,
        source_url=channel.url,
        mode=mode,
        attributes=attributes_from_insights(
            insights,
            topic=topic,
            source=source,
            profile=profile,
            keywords=keywords,
            target_duration=target_duration,
            metadata_text=metadata_text,
        ),
        track=track_decision_from_match(
            match,
            candidates=candidates,
            track=chosen_track,
            profile=profile,
            keywords=keywords,
            forced=forced,
            catalog_size=catalog_size,
        ),
        prompt=prompt,
        artifacts={key: str(value) for key, value in (artifacts or {}).items()},
        video=_video_artifact(
            video_path,
            duration=video_duration,
            clip_count=clip_count,
            clip_source=clip_source,
            scene_count=scenes,
            music_mood=music_mood,
        ),
        notes=notes,
    )


def record_from_workflow_run(
    *,
    channel: ChannelData,
    insights: Mapping[str, Any],
    profile: LyricsAnalysis | None = None,
    track: Track | None = None,
    keywords: Sequence[str] = (),
    target_duration: float | None = None,
    artifacts: Mapping[str, str] | None = None,
    video_path: str | Path | None = None,
    video_duration: float | None = None,
    clip_source: str = "none",
    mode: str = "html",
    run_id: str | None = None,
    upload_url: str | None = None,
    upload_title: str | None = None,
    privacy: str | None = None,
    metadata_text: str | None = None,
    notes: str = "",
) -> DecisionRecord:
    """Decisión del flujo clásico (investigación + edición), más ligera.

    No hay matching por letras: se registra la pista usada (si la había) y el
    vídeo/mezcla final, con los mismos atributos de metadatos.
    """
    topic = (upload_title or channel.name or "").strip() or "vídeo"
    record = DecisionRecord(
        run_id=run_id,
        topic=topic,
        source_channel=channel.name,
        source_url=channel.url,
        mode=mode,
        attributes=attributes_from_insights(
            insights,
            topic=topic,
            source=channel.name,
            profile=profile,
            keywords=keywords,
            target_duration=target_duration,
            metadata_text=metadata_text,
        ),
        prompt="",
        artifacts={key: str(value) for key, value in (artifacts or {}).items()},
        video=_video_artifact(
            video_path,
            duration=video_duration,
            clip_source=clip_source,
            scene_count=0,
        ),
        notes=notes,
    )
    if track is not None:
        record.track = TrackDecision(
            chosen_id=track.id,
            chosen_title=track.title,
            chosen_artist=track.artist,
            reason="canción del catálogo usada como banda sonora",
            forced=True,
            candidates=[
                TrackCandidate(
                    rank=1,
                    track_id=track.id,
                    title=track.title,
                    artist=track.artist,
                    reason="elegida a mano (--track)",
                )
            ],
        )
    if upload_url:
        record.upload = UploadRecord(
            video_id=video_id_from_url(upload_url) or upload_url,
            url=upload_url,
            title=upload_title,
            privacy=privacy,
        )
    return record
