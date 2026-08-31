"""Tests del módulo de descubrimiento de canales (categories, search, ranking,
similarity, cache y cli).

Se usan clientes HTTP fake (sin red) y canales sintéticos (modo demo) para
mantener la suite 100 % offline, igual que el resto del framework.
"""

import argparse
import asyncio
import json

import httpx
import pytest

from youber.discovery.cache import DiscoveryCache
from youber.discovery.categories import (
    CATEGORY_TOPICS,
    ChannelCategory,
    all_categories,
    infer_category,
    topic_scores,
    topics_for,
)
from youber.discovery.cli import _category, build_parser
from youber.discovery.ranking import (
    RankingMetric,
    engagement_score,
    metric_value,
    rank_channels,
    summarize,
    views_per_video,
)
from youber.discovery.search import (
    ChannelHit,
    ChannelSearcher,
    SearchResult,
    _parse_compact,
    parse_search_html,
)
from youber.discovery.similarity import find_similar, shared_topics, similarity_score

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _channel_renderer(channel_id, title, subs_text, videos_text, desc="", handle="/@canal"):
    """Construye un ``channelRenderer`` de YouTube en formato JSON."""
    return {
        "channelId": channel_id,
        "title": {"simpleText": title},
        "descriptionSnippet": {"runs": [{"text": desc}]} if desc else None,
        "subscriberCountText": {"simpleText": subs_text},
        "videoCountText": {"simpleText": videos_text},
        "thumbnail": {"thumbnails": [{"url": f"https://i.ytimg.com/{channel_id}.jpg"}]},
        "navigationEndpoint": {
            "browseEndpoint": {"canonicalBaseUrl": handle}
        },
    }


def _search_html_fixture(renderers):
    """HTML mínimo con ``ytInitialData`` emulado (patrón de fixtures offline)."""
    data = {
        "contents": {
            "twoColumnSearchResultsRenderer": {
                "primaryContents": {
                    "sectionListRenderer": {
                        "contents": [
                            {
                                "itemSectionRenderer": {
                                    "contents": [
                                        {"channelRenderer": renderer}
                                        for renderer in renderers
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }
    }
    return (
        "<html><body><script>var ytInitialData = "
        + json.dumps(data)
        + ";</script></body></html>"
    )


def _hit(
    channel_id="UC123",
    title="Canal Python",
    subs=1_000_000,
    videos=300,
    views=50_000_000,
    category=None,
    topics=None,
):
    return ChannelHit(
        channel_id=channel_id,
        title=title,
        url=f"https://www.youtube.com/channel/{channel_id}",
        handle=f"canal{channel_id}",
        description="Tutoriales de programación",
        subscriber_count=subs,
        video_count=videos,
        view_count=views,
        category=category,
        matched_topics=topics or [],
        source="api",
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
    """Cliente async fake que registra llamadas y responde según la URL."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)


def _api_handler(url, kwargs):
    """Handler fake para la YouTube Data API v3 (search + channels)."""
    params = kwargs.get("params", {})
    if url.endswith("/search"):
        q = params.get("q", "")
        return FakeResponse(
            json_data={
                "items": [
                    {
                        "id": {"channelId": "UC1"},
                        "snippet": {
                            "title": f"Canal {q} Uno",
                            "description": "Tutoriales de python y programación",
                            "channelTitle": "Canal Uno",
                            "thumbnails": {"high": {"url": "https://x/uc1.jpg"}},
                        },
                    },
                    {
                        "id": {"channelId": "UC2"},
                        "snippet": {
                            "title": f"Canal {q} Dos",
                            "description": "Noticias de actualidad",
                            "channelTitle": "Canal Dos",
                            "thumbnails": {"medium": {"url": "https://x/uc2.jpg"}},
                        },
                    },
                ]
            }
        )
    if url.endswith("/channels"):
        ids = params.get("id", "").split(",")
        items = []
        for cid in ids:
            if cid == "UC1":
                items.append(
                    {
                        "id": cid,
                        "statistics": {
                            "subscriberCount": "1200000",
                            "videoCount": "345",
                            "viewCount": "50000000",
                        },
                    }
                )
            elif cid == "UC2":
                items.append(
                    {
                        "id": cid,
                        "statistics": {
                            "subscriberCount": "800000",
                            "videoCount": "120",
                            "viewCount": "9000000",
                        },
                    }
                )
        return FakeResponse(json_data={"items": items})
    return FakeResponse(status_code=404)


# ---------------------------------------------------------------------------
# categories.py
# ---------------------------------------------------------------------------


class TestCategories:
    def test_veinte_categorias(self):
        assert len(all_categories()) == 20

    def test_valores_en_espanol(self):
        assert ChannelCategory.TECHNOLOGY.value == "tecnología"
        assert ChannelCategory.EDUCATION.value == "educación"
        assert ChannelCategory.GAMING.value == "gaming"
        assert ChannelCategory.MUSIC.value == "música"
        assert ChannelCategory.LIFESTYLE.value == "estilo_de_vida"
        assert ChannelCategory.SCIENCE.value == "ciencia"
        assert ChannelCategory.BUSINESS.value == "negocios"
        assert ChannelCategory.HEALTH.value == "salud"
        assert ChannelCategory.TRAVEL.value == "viajes"
        assert ChannelCategory.FOOD.value == "cocina"
        assert ChannelCategory.FASHION.value == "moda"
        assert ChannelCategory.SPORTS.value == "deportes"
        assert ChannelCategory.NEWS.value == "noticias"
        assert ChannelCategory.ENTERTAINMENT.value == "entretenimiento"
        assert ChannelCategory.FILM.value == "cine"
        assert ChannelCategory.ANIMATION.value == "animación"
        assert ChannelCategory.PODCAST.value == "podcast"
        assert ChannelCategory.DIY.value == "manualidades"
        assert ChannelCategory.PHOTOGRAPHY.value == "fotografía"
        assert ChannelCategory.MARKETING.value == "marketing"

    def test_temas_tecnologia(self):
        topics = topics_for(ChannelCategory.TECHNOLOGY)
        assert "python" in topics
        assert "machine learning" in topics
        assert "cybersecurity" in topics

    def test_temas_categoria_desconocida(self):
        assert topics_for(ChannelCategory.PHOTOGRAPHY) == CATEGORY_TOPICS[
            ChannelCategory.PHOTOGRAPHY
        ]

    def test_temas_devuelve_copia(self):
        topics = topics_for(ChannelCategory.MUSIC)
        topics.append("extra")
        assert "extra" not in topics_for(ChannelCategory.MUSIC)

    def test_todas_las_categorias_tienen_temas(self):
        for category in all_categories():
            assert topics_for(category), f"{category} sin temas"

    def test_infer_category_tecnologia(self):
        assert infer_category("Curso de python con machine learning") == (
            ChannelCategory.TECHNOLOGY
        )

    def test_infer_category_sin_coincidencias(self):
        assert infer_category("qwerty zzz") is None

    def test_topic_scores(self):
        scores = topic_scores("aprende python y javascript")
        assert scores[ChannelCategory.TECHNOLOGY] == 2


# ---------------------------------------------------------------------------
# search.py
# ---------------------------------------------------------------------------


class TestParseCompact:
    def test_suscriptores_compactos(self):
        assert _parse_compact("1,2 M de suscriptores") == 1_200_000.0

    def test_videos_sin_sufijo(self):
        assert _parse_compact("345 vídeos") == 345.0

    def test_miles_con_puntos(self):
        assert _parse_compact("1.234.567") == 1_234_567.0

    def test_sufijo_k(self):
        assert _parse_compact("12K") == 12_000.0

    def test_vacio(self):
        assert _parse_compact("") is None

    def test_sin_numero(self):
        assert _parse_compact("sin datos") is None


class TestParseSearchHtml:
    def test_parsea_canales(self):
        html = _search_html_fixture(
            [
                _channel_renderer(
                    "UC1",
                    "Canal Python",
                    "1,2 M de suscriptores",
                    "345 vídeos",
                    desc="Tutoriales de python",
                    handle="/@canalpython",
                ),
                _channel_renderer("UC2", "Canal Noticias", "800 K", "120 vídeos"),
            ]
        )
        hits = parse_search_html(html)
        assert len(hits) == 2
        first = hits[0]
        assert first.channel_id == "UC1"
        assert first.title == "Canal Python"
        assert first.subscriber_count == 1_200_000
        assert first.video_count == 345
        assert first.handle == "canalpython"
        assert first.url == "https://www.youtube.com/channel/UC1"
        assert first.category == ChannelCategory.TECHNOLOGY
        assert "python" in first.matched_topics
        assert first.source == "html"

    def test_sin_resultados(self):
        assert parse_search_html(_search_html_fixture([])) == []

    def test_html_sin_datos(self):
        assert parse_search_html("<html><body>no data</body></html>") == []


class TestChannelSearcher:
    def test_build_query_con_texto(self):
        searcher = ChannelSearcher()
        assert searcher._build_query("python", None, None) == "python"

    def test_build_query_con_temas(self):
        searcher = ChannelSearcher()
        assert searcher._build_query(None, None, ["ia", "python"]) == "ia python"

    def test_build_query_con_categoria(self):
        searcher = ChannelSearcher()
        query = searcher._build_query(None, ChannelCategory.TECHNOLOGY, None)
        assert "python" in query

    def test_build_query_sin_criterios(self):
        searcher = ChannelSearcher()
        with pytest.raises(ValueError):
            searcher._build_query(None, None, None)

    def test_resolve_mode_auto_con_clave(self):
        assert ChannelSearcher(api_key="KEY")._resolve_mode("auto") == "api"

    def test_resolve_mode_auto_sin_clave(self):
        assert ChannelSearcher()._resolve_mode("auto") == "html"

    @pytest.mark.asyncio
    async def test_search_api(self, monkeypatch):
        client = FakeAsyncClient(_api_handler)
        monkeypatch.setattr("youber.discovery.search.httpx.AsyncClient", lambda **kw: client)
        searcher = ChannelSearcher(api_key="KEY")
        result = await searcher.search("python", limit=5, mode="api")
        assert isinstance(result, SearchResult)
        assert result.backend == "api"
        assert len(result.channels) == 2
        first = result.channels[0]
        assert first.subscriber_count == 1_200_000
        assert first.view_count == 50_000_000
        assert first.video_count == 345
        assert first.category == ChannelCategory.TECHNOLOGY
        # El orden de llamadas: search -> channels
        assert any(url.endswith("/search") for url, _ in client.calls)
        assert any(url.endswith("/channels") for url, _ in client.calls)

    @pytest.mark.asyncio
    async def test_search_api_sin_clave(self):
        searcher = ChannelSearcher()
        with pytest.raises(ValueError, match="requiere YOUTUBE_API_KEY"):
            await searcher.search("python", mode="api")

    @pytest.mark.asyncio
    async def test_search_html(self, monkeypatch):
        html = _search_html_fixture(
            [
                _channel_renderer("UC1", "Canal Python", "1,2 M", "345 vídeos")
            ]
        )
        client = FakeAsyncClient(lambda url, kwargs: FakeResponse(text=html))
        monkeypatch.setattr("youber.discovery.search.httpx.AsyncClient", lambda **kw: client)
        searcher = ChannelSearcher(request_delay=0)
        result = await searcher.search("python", mode="html")
        assert result.backend == "html"
        assert len(result.channels) == 1
        assert result.channels[0].subscriber_count == 1_200_000

    @pytest.mark.asyncio
    async def test_search_demo_determinista(self):
        searcher = ChannelSearcher()
        first = await searcher.search("python", category=ChannelCategory.TECHNOLOGY, limit=5, mode="demo")
        second = await searcher.search("python", category=ChannelCategory.TECHNOLOGY, limit=5, mode="demo")
        assert first.channels == second.channels
        assert len(first.channels) == 5
        assert all(ch.category == ChannelCategory.TECHNOLOGY for ch in first.channels)
        assert all(ch.source == "demo" for ch in first.channels)

    @pytest.mark.asyncio
    async def test_search_demo_limit(self):
        searcher = ChannelSearcher()
        result = await searcher.search("ia", limit=3, mode="demo")
        assert len(result.channels) == 3

    @pytest.mark.asyncio
    async def test_search_modo_desconocido(self):
        searcher = ChannelSearcher()
        with pytest.raises(ValueError, match="Modo desconocido"):
            await searcher.search("python", mode="raro")


# ---------------------------------------------------------------------------
# ranking.py
# ---------------------------------------------------------------------------


class TestRanking:
    def test_metric_value_subscribers(self):
        hit = _hit(subs=5000)
        assert metric_value(hit, RankingMetric.SUBSCRIBERS) == 5000.0

    def test_engagement_score(self):
        hit = _hit(subs=1000, views=5000)
        assert engagement_score(hit) == 5.0

    def test_engagement_sin_suscriptores(self):
        assert engagement_score(_hit(subs=0, views=5000)) == 0.0

    def test_views_per_video(self):
        hit = _hit(videos=100, views=10_000)
        assert views_per_video(hit) == 100.0

    def test_rank_por_engagement(self):
        low = _hit(channel_id="low", subs=10_000, views=20_000)
        high = _hit(channel_id="high", subs=10_000, views=100_000)
        ranked = rank_channels([low, high], metric=RankingMetric.ENGAGEMENT)
        assert ranked[0].channel.channel_id == "high"
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_rank_con_metrica_texto(self):
        hit = _hit(subs=5000)
        ranked = rank_channels([hit], metric="subscribers")
        assert ranked[0].metric == RankingMetric.SUBSCRIBERS

    def test_rank_limit(self):
        hits = [_hit(channel_id=str(i), subs=i * 100) for i in range(1, 6)]
        ranked = rank_channels(hits, metric=RankingMetric.SUBSCRIBERS, limit=2)
        assert len(ranked) == 2
        assert ranked[0].channel.channel_id == "5"

    def test_rank_vacio(self):
        assert rank_channels([]) == []

    def test_summarize(self):
        hits = [_hit(subs=1000, views=5000), _hit(subs=3000, views=15_000)]
        summary = summarize(hits)
        assert summary["canales"] == 2
        assert summary["suscriptores_medio"] == 2000.0
        assert summary["suscriptores_mediana"] == 2000.0


# ---------------------------------------------------------------------------
# similarity.py
# ---------------------------------------------------------------------------


class TestSimilarity:
    def test_similarity_misma_categoria_y_temas(self):
        a = _hit(category=ChannelCategory.TECHNOLOGY, topics=["python", "ia"])
        b = _hit(
            channel_id="UC2",
            category=ChannelCategory.TECHNOLOGY,
            topics=["python", "ia", "javascript"],
        )
        score, _ = similarity_score(a, b)
        assert score > 0.8

    def test_similarity_categorias_distintas(self):
        a = _hit(category=ChannelCategory.TECHNOLOGY, topics=["python"])
        b = _hit(channel_id="UC2", category=ChannelCategory.MUSIC, topics=["piano"])
        score, _ = similarity_score(a, b)
        assert score < 0.6

    def test_shared_topics(self):
        a = _hit(topics=["python", "ia"])
        b = _hit(channel_id="UC2", topics=["ia", "javascript"])
        assert shared_topics(a, b) == ["ia"]

    def test_find_similar_excluye_objetivo(self):
        target = _hit(channel_id="target", category=ChannelCategory.TECHNOLOGY, topics=["python"])
        pool = [
            target,
            _hit(channel_id="A", category=ChannelCategory.TECHNOLOGY, topics=["python", "ia"]),
            _hit(channel_id="B", category=ChannelCategory.TECHNOLOGY, topics=["python"]),
            _hit(channel_id="C", category=ChannelCategory.FOOD, topics=["cocina"]),
        ]
        similar = find_similar(target, pool, limit=3)
        assert [item.channel.channel_id for item in similar] == ["B", "A", "C"]

    def test_find_similar_min_score(self):
        target = _hit(channel_id="target", category=ChannelCategory.TECHNOLOGY, topics=["python"])
        pool = [
            _hit(channel_id="A", category=ChannelCategory.TECHNOLOGY, topics=["python", "ia"]),
            _hit(channel_id="C", category=ChannelCategory.FOOD, topics=["cocina"]),
        ]
        similar = find_similar(target, pool, min_score=0.7)
        assert [item.channel.channel_id for item in similar] == ["A"]

    def test_find_similar_vacio(self):
        assert find_similar(_hit(), []) == []


# ---------------------------------------------------------------------------
# cache.py
# ---------------------------------------------------------------------------


class TestCache:
    def test_set_get(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        cache.set("clave", {"a": 1})
        assert cache.get("clave") == {"a": 1}

    def test_get_desconocida(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        assert cache.get("nope") is None

    def test_ttl_expirado(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        cache.set("clave", "valor", ttl=-1)
        assert cache.get("clave") is None

    def test_delete(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        cache.set("clave", 1)
        assert cache.delete("clave") is True
        assert cache.delete("clave") is False

    def test_clear(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.stats()["entradas"] == 0

    def test_stats(self, tmp_path):
        cache = DiscoveryCache(path=tmp_path / "cache.json")
        cache.set("a", 1, ttl=60)
        cache.set("b", 2, ttl=-1)
        stats = cache.stats()
        assert stats["entradas"] == 2
        assert stats["validas"] == 1
        assert stats["expiradas"] == 1
        assert stats["bytes"] > 0

    def test_persistencia_entre_instancias(self, tmp_path):
        path = tmp_path / "cache.json"
        DiscoveryCache(path=path).set("clave", {"x": 1})
        assert DiscoveryCache(path=path).get("clave") == {"x": 1}

    def test_fichero_corrupto(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text("{no es json", encoding="utf-8")
        cache = DiscoveryCache(path=path)
        assert cache.get("clave") is None


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------


class TestCli:
    def test_category_valida(self):
        assert _category("tecnología") == ChannelCategory.TECHNOLOGY
        assert _category("TECHNOLOGY") == ChannelCategory.TECHNOLOGY

    def test_category_invalida(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _category("inexistente")

    def test_parser_categories(self):
        args = build_parser().parse_args(["categories"])
        assert args.command == "categories"

    def test_parser_search(self):
        args = build_parser().parse_args(["search", "python", "--category", "tecnología", "--demo"])
        assert args.command == "search"
        assert args.query == "python"
        assert args.category == ChannelCategory.TECHNOLOGY
        assert args.demo is True

    def test_parser_similar(self):
        args = build_parser().parse_args(["similar", "@canal", "--query", "python", "--demo"])
        assert args.command == "similar"
        assert args.target == "@canal"

    def test_parser_cache(self):
        args = build_parser().parse_args(["cache", "stats"])
        assert args.command == "cache"
        assert args.action == "stats"

    def test_export_json(self, tmp_path, capsys):
        from youber.discovery.cli import _cmd_search

        output = tmp_path / "canales.json"
        args = build_parser().parse_args(
            ["search", "python", "--demo", "--no-cache", "-o", str(output)]
        )
        asyncio.run(_cmd_search(args))
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data) > 0
        assert "channel" in data[0]
        assert "score" in data[0]

    def test_export_csv(self, tmp_path):
        from youber.discovery.cli import _cmd_search

        output = tmp_path / "canales.csv"
        args = build_parser().parse_args(
            ["search", "python", "--demo", "--no-cache", "-o", str(output)]
        )
        asyncio.run(_cmd_search(args))
        content = output.read_text(encoding="utf-8-sig")
        assert content.startswith("rank,canal")
        assert "CanalDemo" in content

    def test_export_markdown(self, tmp_path):
        from youber.discovery.cli import _cmd_search

        output = tmp_path / "canales.md"
        args = build_parser().parse_args(
            ["search", "python", "--demo", "--no-cache", "-o", str(output)]
        )
        asyncio.run(_cmd_search(args))
        content = output.read_text(encoding="utf-8")
        assert "# Canales descubiertos" in content

    def test_search_sin_criterios(self, capsys):
        from youber.discovery.cli import _cmd_search

        args = build_parser().parse_args(["search", "--demo", "--no-cache"])
        with pytest.raises(SystemExit):
            asyncio.run(_cmd_search(args))

    def test_cache_stats_comando(self, tmp_path, monkeypatch, capsys):
        from youber.discovery import cache as cache_module
        from youber.discovery.cli import _cmd_cache

        monkeypatch.setattr(cache_module, "DEFAULT_CACHE_PATH", tmp_path / "c.json")
        cache = DiscoveryCache(path=tmp_path / "c.json")
        cache.set("clave", 1)
        args = build_parser().parse_args(["cache", "stats"])
        _cmd_cache(args)
        out = capsys.readouterr().out
        assert "Entradas: 1" in out
