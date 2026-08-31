"""Tests del módulo de análisis musical (audio features).

Se usan clientes HTTP fake (sin red) y el estimador local (determinista)
para mantener la suite 100 % offline, igual que el resto del framework.
"""

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from youber.music.audio_features.analyzer import AudioAnalyzer
from youber.music.audio_features.enricher import (
    AudioFeatureStore,
    CatalogEnricher,
)
from youber.music.audio_features.estimator import LocalEstimator
from youber.music.audio_features.matcher import (
    TrackMatcher,
    artist_score,
    match_score,
    normalize,
    title_score,
)
from youber.music.audio_features.models import (
    AudioFeatures,
    build_profile,
    dance_bucket_for,
    energy_level_for,
    suggest_moods,
    suggest_tags,
    tempo_bucket_for,
    valence_bucket_for,
)
from youber.music.audio_features.recommender import (
    FeatureRecommender,
    feature_vector,
    similarity_score,
    weighted_distance,
)
from youber.music.audio_features.spotify import SpotifyClient
from youber.music.models import Mood, Track

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _features(**overrides) -> AudioFeatures:
    """AudioFeatures por defecto (valores válidos)."""
    base = {
        "danceability": 0.6,
        "energy": 0.7,
        "valence": 0.5,
        "acousticness": 0.3,
        "instrumentalness": 0.1,
        "liveness": 0.2,
        "speechiness": 0.05,
        "tempo": 120.0,
        "duration_ms": 180_000,
        "key": 5,
        "mode": 1,
        "time_signature": 4,
    }
    base.update(overrides)
    return AudioFeatures(**base)


def _profile(track_id="t1", title="Canción Uno", artist="Artista", **feat_overrides):
    return build_profile(track_id, title, artist, _features(**feat_overrides))


def _track(track_id="t1", title="Canción Uno", artist="Artista", genre="pop"):
    return Track(
        id=track_id,
        file_path=Path(f"music/{track_id}.mp3"),
        title=title,
        artist=artist,
        duration=180.0,
        genre=genre,
        moods=[Mood.ENERGETIC],
        file_hash="abc",
    )


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


class FakeAsyncClient:
    """Cliente async fake que responde según la URL."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.handler("post", url, kwargs)

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.handler("get", url, kwargs)


def _spotify_handler(method, url, kwargs):
    """Handler fake de la API de Spotify."""
    if url.endswith("/api/token"):
        return FakeResponse(json_data={"access_token": "tok123"})
    if "/search" in url:
        params = kwargs.get("params", {})
        query = params.get("q", "")
        if "Inexistente" in query:
            return FakeResponse(json_data={"tracks": {"items": []}})
        return FakeResponse(
            json_data={
                "tracks": {
                    "items": [
                        {
                            "id": "sp1",
                            "name": "Canción Uno",
                            "artists": [{"name": "Artista"}],
                            "album": {"name": "Álbum"},
                            "duration_ms": 180_000,
                            "popularity": 70,
                        }
                    ]
                }
            }
        )
    if "/audio-features/" in url:
        return FakeResponse(
            json_data={
                "id": "sp1",
                "danceability": 0.65,
                "energy": 0.75,
                "valence": 0.55,
                "acousticness": 0.2,
                "instrumentalness": 0.05,
                "liveness": 0.25,
                "speechiness": 0.04,
                "tempo": 118.5,
                "duration_ms": 180_000,
                "key": 5,
                "mode": 1,
                "time_signature": 4,
            }
        )
    return FakeResponse(status_code=404)


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestAudioFeaturesModel:
    def test_valores_validos(self):
        features = _features()
        assert features.danceability == 0.6
        assert features.confidence == 1.0
        assert features.source == "api"

    def test_rangos_danceability(self):
        with pytest.raises(ValidationError):
            _features(danceability=1.5)

    def test_rangos_negativos(self):
        with pytest.raises(ValidationError):
            _features(energy=-0.1)

    def test_key_fuera_de_rango(self):
        with pytest.raises(ValidationError):
            _features(key=12)

    def test_key_negativa_permitida(self):
        assert _features(key=-1).key == -1

    def test_time_signature_fuera(self):
        with pytest.raises(ValidationError):
            _features(time_signature=8)

    def test_tempo_no_negativo(self):
        with pytest.raises(ValidationError):
            _features(tempo=-5)

    def test_confianza_estimada(self):
        features = _features(confidence=0.5)
        assert features.source == "estimator"


class TestBuckets:
    def test_energy_level(self):
        assert energy_level_for(0.2) == "baja"
        assert energy_level_for(0.5) == "media"
        assert energy_level_for(0.8) == "alta"

    def test_valence_bucket(self):
        assert valence_bucket_for(0.2) == "triste"
        assert valence_bucket_for(0.5) == "neutral"
        assert valence_bucket_for(0.8) == "alegre"

    def test_tempo_bucket(self):
        assert tempo_bucket_for(80) == "lento"
        assert tempo_bucket_for(110) == "medio"
        assert tempo_bucket_for(140) == "rápido"

    def test_dance_bucket(self):
        assert dance_bucket_for(0.2) == "baja"
        assert dance_bucket_for(0.5) == "media"
        assert dance_bucket_for(0.8) == "alta"


class TestMoodsAndTags:
    def test_suggest_moods_energetica(self):
        moods = suggest_moods(_features(energy=0.9, valence=0.2))
        assert Mood.ENERGETIC.value in moods
        assert Mood.SAD.value in moods

    def test_suggest_moods_relajante(self):
        moods = suggest_moods(_features(energy=0.1))
        assert Mood.RELAXING.value in moods

    def test_suggest_moods_instrumental(self):
        moods = suggest_moods(_features(instrumentalness=0.8))
        assert Mood.FOCUSED.value in moods

    def test_suggest_tags(self):
        tags = suggest_tags(_features(danceability=0.85, acousticness=0.7))
        assert "bailable" in tags
        assert "acústico" in tags

    def test_build_profile_completo(self):
        profile = build_profile("t1", "Canción", "Artista", _features(tempo=140, energy=0.8))
        assert profile.track_id == "t1"
        assert profile.energy_level == "alta"
        assert profile.tempo_bucket == "rápido"
        assert profile.moods
        assert profile.recommendation_tags


# ---------------------------------------------------------------------------
# estimator.py
# ---------------------------------------------------------------------------


class TestLocalEstimator:
    def test_estimacion_determinista(self):
        estimator = LocalEstimator()
        first = estimator.estimate(genre="pop", bpm=110)
        second = estimator.estimate(genre="pop", bpm=110)
        assert first == second

    def test_confianza_estimacion(self):
        features = LocalEstimator().estimate(genre="pop")
        assert features.confidence == 0.5
        assert features.source == "estimator"

    def test_tempo_del_bpm(self):
        features = LocalEstimator().estimate(genre="pop", bpm=95)
        assert features.tempo == 95.0

    def test_perfil_genero_electronic(self):
        features = LocalEstimator().estimate(genre="electronic")
        assert features.energy > 0.7
        assert features.danceability > 0.6

    def test_perfil_genero_classical(self):
        features = LocalEstimator().estimate(genre="classical")
        assert features.acousticness > 0.7
        assert features.energy < 0.5

    def test_mood_relajante_baja_energia(self):
        relajado = LocalEstimator().estimate(genre="pop", moods=["relajante"])
        normal = LocalEstimator().estimate(genre="pop")
        assert relajado.energy < normal.energy

    def test_sin_genero(self):
        features = LocalEstimator().estimate()
        assert 0.0 <= features.energy <= 1.0
        assert features.tempo > 0


# ---------------------------------------------------------------------------
# matcher.py
# ---------------------------------------------------------------------------


class TestMatcher:
    def test_normalize(self):
        assert normalize("Café del Mar") == "cafe del mar"
        assert normalize("  Hello, World!  ") == "hello world"

    def test_title_score_exacto(self):
        assert title_score("Canción Uno", "Canción Uno") == 1.0

    def test_title_score_contenido(self):
        assert title_score("Canción", "Canción Uno") == 0.7

    def test_title_score_distinto(self):
        assert title_score("Uno", "Dos") == 0.0

    def test_artist_score(self):
        assert artist_score("Artista", "Artista") == 1.0
        assert artist_score("Artista", "Otro") == 0.0
        assert artist_score("Artista", None) == 0.5

    def test_match_score(self):
        score = match_score("Canción Uno", "Artista", "Canción Uno", "Artista")
        assert score == 1.0

    def test_best_match(self):
        matcher = TrackMatcher(threshold=0.7)
        candidates = [
            {"track_id": "a", "title": "Otra Canción", "artist": "Otro"},
            {"track_id": "b", "title": "Canción Uno", "artist": "Artista"},
        ]
        match = matcher.best_match("Canción Uno", "Artista", candidates)
        assert match is not None
        assert match["track_id"] == "b"
        assert match["score"] == 1.0

    def test_best_match_bajo_umbral(self):
        matcher = TrackMatcher(threshold=0.9)
        candidates = [{"track_id": "a", "title": "Otra Canción", "artist": "Otro"}]
        assert matcher.best_match("Canción Uno", "Artista", candidates) is None

    def test_best_match_vacio(self):
        assert TrackMatcher().best_match("Canción", "Artista", []) is None


# ---------------------------------------------------------------------------
# spotify.py
# ---------------------------------------------------------------------------


class TestSpotifyClient:
    def test_available_sin_credenciales(self):
        assert SpotifyClient().available is False

    def test_available_con_credenciales(self):
        client = SpotifyClient(client_id="id", client_secret="secret")
        assert client.available is True

    @pytest.mark.asyncio
    async def test_search_track_sin_credenciales(self):
        client = SpotifyClient()
        with pytest.raises(RuntimeError, match="sin credenciales"):
            await client.search_track("Canción")

    @pytest.mark.asyncio
    async def test_search_track(self, monkeypatch):
        client = SpotifyClient(client_id="id", client_secret="secret")
        fake = FakeAsyncClient(_spotify_handler)
        monkeypatch.setattr("youber.music.audio_features.spotify.httpx.AsyncClient", lambda **kw: fake)
        result = await client.search_track("Canción Uno", "Artista")
        assert result is not None
        assert result["track_id"] == "sp1"
        assert result["title"] == "Canción Uno"
        assert result["artist"] == "Artista"
        # El token se pide una vez y se cachea
        assert sum(1 for m, url, _ in fake.calls if url.endswith("/api/token")) == 1

    @pytest.mark.asyncio
    async def test_search_track_sin_resultados(self, monkeypatch):
        client = SpotifyClient(client_id="id", client_secret="secret")
        fake = FakeAsyncClient(_spotify_handler)
        monkeypatch.setattr("youber.music.audio_features.spotify.httpx.AsyncClient", lambda **kw: fake)
        assert await client.search_track("Canción Inexistente") is None

    @pytest.mark.asyncio
    async def test_get_audio_features(self, monkeypatch):
        client = SpotifyClient(client_id="id", client_secret="secret")
        fake = FakeAsyncClient(_spotify_handler)
        monkeypatch.setattr("youber.music.audio_features.spotify.httpx.AsyncClient", lambda **kw: fake)
        features = await client.get_audio_features("sp1")
        assert features is not None
        assert features.energy == 0.75
        assert features.confidence == 1.0


# ---------------------------------------------------------------------------
# analyzer.py
# ---------------------------------------------------------------------------


class TestAudioAnalyzer:
    @pytest.mark.asyncio
    async def test_usa_spotify_si_disponible(self, monkeypatch):
        client = SpotifyClient(client_id="id", client_secret="secret")
        fake = FakeAsyncClient(_spotify_handler)
        monkeypatch.setattr("youber.music.audio_features.spotify.httpx.AsyncClient", lambda **kw: fake)
        analyzer = AudioAnalyzer(spotify=client)
        profile = await analyzer.analyze("Canción Uno", "Artista", track_id="t1")
        assert profile.features.confidence == 1.0
        assert profile.features.energy == 0.75
        assert profile.track_id == "t1"

    @pytest.mark.asyncio
    async def test_fallback_estimador_sin_credenciales(self):
        analyzer = AudioAnalyzer(spotify=SpotifyClient())
        profile = await analyzer.analyze("Canción", "Artista", genre="pop", track_id="t1")
        assert profile.features.confidence == 0.5
        assert profile.features.source == "estimator"

    @pytest.mark.asyncio
    async def test_fallback_si_spotify_no_encuentra(self, monkeypatch):
        client = SpotifyClient(client_id="id", client_secret="secret")
        fake = FakeAsyncClient(_spotify_handler)
        monkeypatch.setattr("youber.music.audio_features.spotify.httpx.AsyncClient", lambda **kw: fake)
        analyzer = AudioAnalyzer(spotify=client)
        profile = await analyzer.analyze("Canción Inexistente", track_id="t1", genre="rock")
        assert profile.features.confidence == 0.5

    @pytest.mark.asyncio
    async def test_perfil_con_buckets(self):
        analyzer = AudioAnalyzer(spotify=SpotifyClient())
        profile = await analyzer.analyze(
            "Canción", genre="electronic", bpm=128, track_id="t1"
        )
        assert profile.energy_level in ("baja", "media", "alta")
        assert profile.valence_bucket in ("triste", "neutral", "alegre")
        assert profile.tempo_bucket in ("lento", "medio", "rápido")
        assert profile.dance_bucket in ("baja", "media", "alta")


# ---------------------------------------------------------------------------
# enricher.py
# ---------------------------------------------------------------------------


class TestAudioFeatureStore:
    def test_set_get(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        profile = _profile()
        store.set(profile)
        assert store.get("t1") == profile

    def test_get_desconocido(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        assert store.get("nope") is None

    def test_has(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        store.set(_profile())
        assert store.has("t1")
        assert not store.has("t2")

    def test_all(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        store.set(_profile("t1"))
        store.set(_profile("t2", title="Canción Dos"))
        assert len(store.all()) == 2

    def test_clear(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        store.set(_profile())
        store.clear()
        assert store.stats()["entradas"] == 0

    def test_stats(self, tmp_path):
        store = AudioFeatureStore(path=tmp_path / "af.json")
        store.set(_profile())
        stats = store.stats()
        assert stats["entradas"] == 1
        assert stats["bytes"] > 0

    def test_persistencia(self, tmp_path):
        path = tmp_path / "af.json"
        AudioFeatureStore(path=path).set(_profile())
        assert AudioFeatureStore(path=path).get("t1") is not None

    def test_fichero_corrupto(self, tmp_path):
        path = tmp_path / "af.json"
        path.write_text("{no es json", encoding="utf-8")
        assert AudioFeatureStore(path=path).all() == []


class TestCatalogEnricher:
    @pytest.mark.asyncio
    async def test_enrich(self, tmp_path):
        library = _FakeLibrary([_track()])
        store = AudioFeatureStore(path=tmp_path / "af.json")
        analyzer = AudioAnalyzer(spotify=SpotifyClient())
        enricher = CatalogEnricher(library=library, analyzer=analyzer, store=store)
        profile = await enricher.enrich(_track())
        assert profile is not None
        assert profile.features.source == "estimator"
        assert store.has("t1")

    @pytest.mark.asyncio
    async def test_enrich_all(self, tmp_path):
        library = _FakeLibrary([_track("t1"), _track("t2", title="Canción Dos")])
        store = AudioFeatureStore(path=tmp_path / "af.json")
        enricher = CatalogEnricher(
            library=library,
            analyzer=AudioAnalyzer(spotify=SpotifyClient()),
            store=store,
        )
        result = await enricher.enrich_all()
        assert result.total == 2
        assert result.enriched == 2
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_enrich_all_omite_ya_guardadas(self, tmp_path):
        library = _FakeLibrary([_track("t1"), _track("t2", title="Canción Dos")])
        store = AudioFeatureStore(path=tmp_path / "af.json")
        store.set(_profile("t1"))
        enricher = CatalogEnricher(
            library=library,
            analyzer=AudioAnalyzer(spotify=SpotifyClient()),
            store=store,
        )
        result = await enricher.enrich_all()
        assert result.enriched == 1


class _FakeLibrary:
    """Sustituto mínimo de MusicLibrary para los tests."""

    def __init__(self, tracks: list[Track]) -> None:
        self._tracks = tracks

    def all(self) -> list[Track]:
        return self._tracks

    def get(self, track_id: str) -> Track | None:
        return next((t for t in self._tracks if t.id == track_id), None)


# ---------------------------------------------------------------------------
# recommender.py
# ---------------------------------------------------------------------------


class TestRecommender:
    def test_feature_vector(self):
        vector = feature_vector(_features(tempo=120))
        assert vector["energy"] == 0.7
        assert 0.0 <= vector["tempo"] <= 1.0

    def test_distancia_cero_identicos(self):
        features = _features()
        assert weighted_distance(features, features) == 0.0

    def test_distancia_mayor_con_mas_diferencia(self):
        a = _features(energy=0.9, valence=0.9)
        b = _features(energy=0.1, valence=0.1)
        c = _features(energy=0.8, valence=0.85)
        assert weighted_distance(a, b) > weighted_distance(a, c)

    def test_similarity_score(self):
        features = _features()
        assert similarity_score(features, features) == 1.0

    def test_recommend_ordena(self):
        target = _profile("t0", title="Referencia", energy=0.9, valence=0.9)
        catalog = [
            _profile("a", title="Parecida", energy=0.85, valence=0.85),
            _profile("b", title="Opuesta", energy=0.1, valence=0.1),
        ]
        recommender = FeatureRecommender()
        result = recommender.recommend(target, catalog)
        assert result[0].track_id == "a"
        assert result[1].track_id == "b"

    def test_recommend_excluye_objetivo(self):
        target = _profile("t0", title="Referencia", energy=0.9)
        catalog = [
            _profile("t0", title="Referencia", energy=0.9),
            _profile("a", title="Otra", energy=0.8),
        ]
        result = FeatureRecommender().recommend(target, catalog)
        assert [item.track_id for item in result] == ["a"]

    def test_recommend_limit(self):
        target = _profile("t0", title="Ref", energy=0.9)
        catalog = [
            _profile(str(i), title=f"Canción {i}", energy=0.8) for i in range(5)
        ]
        result = FeatureRecommender(limit=2).recommend(target, catalog)
        assert len(result) == 2

    def test_recommend_min_score(self):
        target = _profile("t0", title="Ref", energy=0.9, valence=0.9)
        catalog = [
            _profile("a", title="Parecida", energy=0.85, valence=0.85),
            _profile("b", title="Opuesta", energy=0.1, valence=0.1),
        ]
        result = FeatureRecommender(min_score=0.8).recommend(target, catalog)
        assert [item.track_id for item in result] == ["a"]

    def test_recommend_moods_compartidos(self):
        target = _profile("t0", title="Ref")
        target.moods = ["alegre", "energética"]
        other = _profile("a", title="Otra")
        other.moods = ["alegre", "triste"]
        result = FeatureRecommender().recommend(target, [other])
        assert result[0].shared_moods == ["alegre"]


# ---------------------------------------------------------------------------
# cli.py (subcomandos analyze/recommend)
# ---------------------------------------------------------------------------


class TestCliAudioFeatures:
    def test_register_añade_subcomandos(self):
        from youber.music.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["analyze", "t1"])
        assert args.command == "analyze"
        assert args.track_id == "t1"
        args = parser.parse_args(["recommend", "t1", "-n", "3"])
        assert args.command == "recommend"
        assert args.limit == 3

    def test_analyze_local_con_store(self, tmp_path, monkeypatch, capsys):
        from youber.music.cli import run

        library = _FakeLibraryWithClose([_track()])
        monkeypatch.setattr(
            "youber.music.cli.MusicLibrary", lambda *a, **k: library
        )
        store_path = tmp_path / "af.json"
        monkeypatch.setattr(
            "youber.music.audio_features.enricher.DEFAULT_STORE_PATH", store_path
        )
        args = _parse(["analyze", "t1", "--local"])
        run(args)
        out = capsys.readouterr().out
        assert "Canción Uno" in out
        assert "Estimación local" in out

    def test_analyze_all(self, tmp_path, monkeypatch, capsys):
        from youber.music.cli import run

        library = _FakeLibraryWithClose([_track("t1"), _track("t2", title="Canción Dos")])
        monkeypatch.setattr("youber.music.cli.MusicLibrary", lambda *a, **k: library)
        store_path = tmp_path / "af.json"
        monkeypatch.setattr(
            "youber.music.audio_features.enricher.DEFAULT_STORE_PATH", store_path
        )
        args = _parse(["analyze", "--all", "--local"])
        run(args)
        out = capsys.readouterr().out
        assert "Analizadas 2/2" in out

    def test_analyze_pista_no_encontrada(self, tmp_path, monkeypatch):
        from youber.music.cli import run

        library = _FakeLibraryWithClose([])
        monkeypatch.setattr("youber.music.cli.MusicLibrary", lambda *a, **k: library)
        args = _parse(["analyze", "nope", "--local"])
        with pytest.raises(SystemExit):
            run(args)

    def test_recommend_sin_perfil(self, tmp_path, monkeypatch, capsys):
        from youber.music.cli import run

        library = _FakeLibraryWithClose([_track()])
        monkeypatch.setattr("youber.music.cli.MusicLibrary", lambda *a, **k: library)
        monkeypatch.setattr(
            "youber.music.audio_features.enricher.DEFAULT_STORE_PATH", tmp_path / "af.json"
        )
        args = _parse(["recommend", "t1"])
        with pytest.raises(SystemExit):
            run(args)


class _FakeLibraryWithClose(_FakeLibrary):
    """Fake de MusicLibrary con close() para el CLI."""

    def close(self) -> None:  # pragma: no cover
        pass


def _parse(argv: list[str]):
    from youber.music.cli import build_parser

    return build_parser().parse_args(argv)
