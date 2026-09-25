"""Tests del selector de canción por letras (youber.music.selector)."""

from __future__ import annotations

from pathlib import Path

from youber.music.models import Mood, Track, TrackSource
from youber.music.selector import (
    score_track_for_profile,
    select_best_track,
    select_tracks,
    theme_profile,
)

SAD_TEXT = (
    "La noche cae y el dolor no se va, lágrimas en la soledad, "
    "todo está perdido, adiós, la tristeza me acompaña."
)
HAPPY_TEXT = (
    "Hoy es un día feliz, alegría y risas, celebramos el amor, "
    "la luz y el brillo de la mañana."
)


def _track(
    track_id: str,
    title: str,
    *,
    themes: dict[str, float] | None = None,
    sentiment: str = "neutral",
    moods: list[Mood] | None = None,
    favorite: bool = False,
    usage: int = 0,
    artist: str | None = None,
    genre: str | None = None,
    source: TrackSource = TrackSource.LOCAL,
) -> Track:
    return Track(
        id=track_id,
        file_path=Path("music") / f"{track_id}.mp3",
        title=title,
        artist=artist,
        genre=genre,
        duration=120.0,
        moods=moods or [],
        favorite=favorite,
        usage_count=usage,
        file_hash=f"hash-{track_id}",
        lyrical_themes=themes or {},
        lyrical_sentiment=sentiment,
        source=source,
    )


# ---------------------------------------------------------------------------
# Perfil temático del texto de metadatos
# ---------------------------------------------------------------------------


def test_theme_profile_detecta_tristeza():
    profile = theme_profile(SAD_TEXT)
    assert "tristeza" in profile.themes
    assert profile.sentiment == "negative"
    assert profile.dominant_theme == "tristeza"


def test_theme_profile_texto_vacio():
    profile = theme_profile("")
    assert profile.themes == {}
    assert profile.sentiment == "neutral"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_por_tema_compartido():
    sad = _track("a", "Adiós", themes={"tristeza": 0.9}, sentiment="negative")
    other = _track("b", "Fiesta", themes={"felicidad": 0.9}, sentiment="positive")
    profile = theme_profile(SAD_TEXT)
    sad_score, sad_matched = score_track_for_profile(sad, themes=profile.themes)
    other_score, other_matched = score_track_for_profile(other, themes=profile.themes)
    assert sad_score > other_score
    assert sad_matched == ["tristeza"]
    assert other_matched == []


def test_score_sentimiento_mood_favorita_y_uso():
    base = dict(themes={"tristeza": 1.0}, sentiment="negative")
    plain = _track("a", "A", **base)
    favored = _track("b", "B", **base, favorite=True)
    used = _track("c", "C", **base, usage=5)
    with_mood = _track("d", "D", **base, moods=[Mood.SAD])

    plain_score, _ = score_track_for_profile(plain, themes={"tristeza": 1.0})
    favored_score, _ = score_track_for_profile(favored, themes={"tristeza": 1.0})
    used_score, _ = score_track_for_profile(used, themes={"tristeza": 1.0})
    mood_score, _ = score_track_for_profile(
        with_mood, themes={"tristeza": 1.0}, mood=Mood.SAD
    )
    assert favored_score > plain_score
    assert used_score < plain_score
    assert mood_score > plain_score


def test_score_keywords_en_titulo():
    track = _track("a", "Python Nights", artist="Skyzo")
    with_kw, _ = score_track_for_profile(track, keywords=["python", "rust"])
    without_kw, _ = score_track_for_profile(track, keywords=[])
    assert with_kw > without_kw


# ---------------------------------------------------------------------------
# Selección
# ---------------------------------------------------------------------------


def test_select_tracks_ordena_por_afinidad():
    sad = _track("a", "Adiós", themes={"tristeza": 0.9}, sentiment="negative")
    neutral = _track("b", "Instrumental", themes={})
    happy = _track("c", "Alegría", themes={"felicidad": 0.9}, sentiment="positive")
    matches = select_tracks([happy, neutral, sad], theme_profile(SAD_TEXT))
    assert [match.track_id for match in matches] == ["a", "c", "b"] or [
        match.track_id for match in matches
    ][0] == "a"
    assert matches[0].track_id == "a"
    assert "tristeza" in matches[0].reason


def test_select_tracks_require_lyrics_filtra():
    with_lyrics = _track("a", "Adiós", themes={"tristeza": 0.9})
    without = _track("b", "Sin letra")
    matches = select_tracks(
        [with_lyrics, without], theme_profile(SAD_TEXT), require_lyrics=True
    )
    assert [match.track_id for match in matches] == ["a"]


def test_select_tracks_require_local_ignora_pistas_de_plataforma():
    """La banda sonora se mezcla con FFmpeg: `cloud:*` no se puede montar."""
    cloud = _track(
        "a",
        "Adiós",
        themes={"tristeza": 1.0},
        sentiment="negative",
        source=TrackSource.YOUTUBE,
    )
    local = _track("b", "Otro adiós", themes={"tristeza": 0.4})
    # Sin el filtro, la de plataforma gana por puntuación...
    assert select_best_track([cloud, local], theme_profile(SAD_TEXT)).track_id == "a"
    # ...y con él se elige la única que se puede renderizar.
    chosen = select_best_track(
        [cloud, local], theme_profile(SAD_TEXT), require_local=True
    )
    assert chosen is not None and chosen.track_id == "b"


def test_select_tracks_require_local_sin_candidatas():
    cloud = _track("a", "Adiós", source=TrackSource.SPOTIFY)
    assert select_tracks([cloud], theme_profile(SAD_TEXT), require_local=True) == []


def test_select_tracks_limit():
    tracks = [_track(str(index), f"T{index}") for index in range(5)]
    assert len(select_tracks(tracks, theme_profile(SAD_TEXT), limit=2)) == 2


def test_select_best_track_vacio():
    assert select_best_track([], theme_profile(SAD_TEXT)) is None


def test_select_best_track_sin_perfil_usa_mood():
    relajante = _track("a", "Rain", moods=[Mood.RELAXING])
    epica = _track("b", "Fire", moods=[Mood.EPIC])
    best = select_best_track([epica, relajante], None, mood=Mood.RELAXING)
    assert best is not None
    assert best.track_id == "a"


def test_select_best_track_perfil_alegre():
    sad = _track("a", "Adiós", themes={"tristeza": 0.9}, sentiment="negative")
    happy = _track("b", "Alegría", themes={"felicidad": 0.9}, sentiment="positive")
    best = select_best_track([sad, happy], theme_profile(HAPPY_TEXT))
    assert best is not None
    assert best.track_id == "b"
    assert best.matched_themes == ["felicidad"]
