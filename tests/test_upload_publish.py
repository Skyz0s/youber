"""Tests de la publicación completa: miniatura, subtítulos y capítulos.

Estrategia offline: helpers puros (envoltura de texto, elección del
fotograma, capítulos, multipart de la API) y un cliente HTTP fake para la
API de YouTube. La generación real de la miniatura (FFmpeg) va con
``skipif`` si no hay FFmpeg instalado.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from youber.script.prompt import brief_to_script, build_video_brief
from youber.upload.captions import build_multipart_body, caption_snippet
from youber.upload.chapters import build_chapters, chapters_from_script, format_timestamp
from youber.upload.thumbnail import (
    ThumbnailResult,
    make_thumbnail,
    pick_thumbnail_time,
    thumbnail_filter,
    wrap_text,
)
from youber.upload.youtube import YouTubeUploader

HAS_FFMPEG = shutil.which("ffmpeg") is not None
VIDEO_ID = "vid123"


# ---------------------------------------------------------------------------
# Fakes HTTP (mismo patrón que tests/test_upload.py)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _record(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses[method](method, url, kwargs)

    async def post(self, url, **kwargs):
        return await self._record("post", url, kwargs)

    async def get(self, url, **kwargs):
        return await self._record("get", url, kwargs)

    async def delete(self, url, **kwargs):
        return await self._record("delete", url, kwargs)


def make_fake_client(monkeypatch, responses) -> FakeAsyncClient:
    client = FakeAsyncClient(responses)

    def factory(**kwargs):
        return client

    monkeypatch.setattr("youber.upload.youtube.httpx.AsyncClient", factory)
    return client


def auth_with_token(tmp_path: Path):
    from youber.upload.auth import YouTubeAuth

    auth = YouTubeAuth(client_id="id", client_secret="secret", credentials_dir=tmp_path)
    auth.token_file.write_text(
        '{"access_token": "tok", "refresh_token": "ref", "expires_at": 9999999999}',
        encoding="utf-8",
    )
    return auth


# ---------------------------------------------------------------------------
# Miniatura: helpers puros
# ---------------------------------------------------------------------------


def test_wrap_text_respeta_palabras():
    assert wrap_text("una ciudad bajo la lluvia", width=10) == [
        "una ciudad",
        "bajo la",
        "lluvia",
    ]


def test_wrap_text_palabra_larga_y_vacio():
    assert wrap_text("supercalifragilistico", width=5) == ["supercalifragilistico"]
    assert wrap_text("   ") == []


def test_pick_thumbnail_time_elige_el_pico():
    # 10 ventanas de 1 s: el pico está en la 6.ª (índice 5).
    energies = [1, 1, 2, 3, 1, 9, 4, 1, 1, 1]
    assert pick_thumbnail_time(energies, duration=10.0) == 5.0


def test_pick_thumbnail_time_ignora_los_bordes():
    # El pico está en el primer segundo (fade-in): se descarta por el margen.
    energies = [9, 1, 1, 2, 1, 1, 1, 1, 1, 1]
    assert pick_thumbnail_time(energies, duration=10.0, margin=0.2) == 3.0


def test_pick_thumbnail_time_sin_medidas():
    assert pick_thumbnail_time([], duration=40.0, margin=0.1) == 4.0


def test_pick_thumbnail_time_no_se_pasa_del_final():
    energies = [1, 1, 50]
    assert pick_thumbnail_time(energies, duration=3.0) <= 2.0


def test_thumbnail_filter_recorta_y_rotula():
    plain = thumbnail_filter()
    assert "scale=1280:720:force_original_aspect_ratio=increase" in plain
    assert "crop=1280:720" in plain
    assert "drawtext" not in plain

    with_text = thumbnail_filter(lines=["Hola mundo"], font_file="C:/f.ttf")
    assert "drawtext" in with_text
    assert "text='Hola mundo'" in with_text
    assert "fontfile='C\\:/f.ttf'" in with_text


def test_default_font_file_por_plataforma(monkeypatch):
    from youber.upload import thumbnail

    monkeypatch.setattr(thumbnail.sys, "platform", "linux")
    assert thumbnail.default_font_file() is None


# ---------------------------------------------------------------------------
# Miniatura: generación (FFmpeg mockeado)
# ---------------------------------------------------------------------------


def test_make_thumbnail_comando_y_resultado(monkeypatch, tmp_path: Path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")

    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"\xff\xd8jpeg")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    async def fake_duration(path):
        return 42.0

    async def fake_profile(path, **kwargs):
        return [1.0] * 42

    monkeypatch.setattr("youber.upload.thumbnail.run_command", fake_run)
    monkeypatch.setattr("youber.upload.thumbnail.probe_duration", fake_duration)
    monkeypatch.setattr("youber.upload.thumbnail.thumbnail_profile", fake_profile)
    monkeypatch.setattr("youber.upload.thumbnail.default_font_file", lambda: None)

    result = asyncio.run(
        make_thumbnail(video, text="Mi título", timestamp=7.5)
    )

    assert isinstance(result, ThumbnailResult)
    assert result.path == tmp_path / "v_thumb.jpg"
    assert result.timestamp == 7.5
    assert result.text == "Mi título"
    assert result.path.read_bytes().startswith(b"\xff\xd8")
    cmd = calls[0]
    assert "-ss" in cmd and "7.500" in cmd
    assert "-frames:v" in cmd


def test_make_thumbnail_sin_timestamp_usa_el_pico(monkeypatch, tmp_path: Path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    captured: dict = {}

    async def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"\xff\xd8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    async def fake_duration(path):
        return 10.0

    async def fake_profile(path, **kwargs):
        captured["profile_called"] = True
        return [1, 1, 1, 1, 9, 1, 1, 1, 1, 1]

    monkeypatch.setattr("youber.upload.thumbnail.run_command", fake_run)
    monkeypatch.setattr("youber.upload.thumbnail.probe_duration", fake_duration)
    monkeypatch.setattr("youber.upload.thumbnail.thumbnail_profile", fake_profile)

    result = asyncio.run(make_thumbnail(video))
    assert captured.get("profile_called") is True
    assert result.timestamp == 4.0


def test_make_thumbnail_video_inexistente(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(make_thumbnail(tmp_path / "no.mp4"))


# ---------------------------------------------------------------------------
# Subtítulos: multipart y snippet
# ---------------------------------------------------------------------------


def test_build_multipart_body():
    body, content_type = build_multipart_body(
        {"videoId": "v", "language": "es"}, b"1\n00:00:00,000 --> ...", boundary="sep"
    )
    assert content_type == "multipart/related; boundary=sep"
    assert b"--sep\r\n" in body
    assert b"Content-Type: application/json; charset=UTF-8" in body
    assert json.dumps({"videoId": "v", "language": "es"}, ensure_ascii=False).encode() in body
    assert b"1\n00:00:00,000 --> ..." in body
    assert body.endswith(b"\r\n--sep--\r\n")


def test_caption_snippet():
    assert caption_snippet("v") == {"videoId": "v", "language": "es"}
    assert caption_snippet("v", language="en", name="Letra", is_draft=True) == {
        "videoId": "v",
        "language": "en",
        "name": "Letra",
        "isDraft": True,
    }


# ---------------------------------------------------------------------------
# Capítulos
# ---------------------------------------------------------------------------


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65) == "01:05"
    assert format_timestamp(3725) == "1:02:05"


def test_build_chapters_ok_y_primer_capitulo_a_cero():
    text = build_chapters([(0.0, "Intro"), (20.0, "Desarrollo"), (45.0, "Cierre")])
    assert text.splitlines() == ["00:00 Intro", "00:20 Desarrollo", "00:45 Cierre"]


def test_build_chapters_fuerza_cero():
    text = build_chapters([(5.0, "Intro"), (20.0, "Medio"), (45.0, "Fin")])
    assert text.startswith("00:00 Intro")


def test_build_chapters_descarta_los_invalidos():
    # Solo dos capítulos: YouTube los ignoraría.
    assert build_chapters([(0.0, "A"), (30.0, "B")]) == ""
    # Un capítulo demasiado corto (5 s) invalida el bloque entero.
    assert build_chapters([(0.0, "A"), (5.0, "B"), (30.0, "C")]) == ""
    assert build_chapters([]) == ""


def test_chapters_from_script():
    from youber.research.data_models import ChannelData, VideoData
    from youber.research.patterns import channel_overview

    channel = ChannelData(
        name="Canal",
        url="https://youtube.com/@canal",
        videos=[
            VideoData(
                title="Uno",
                url="https://youtube.com/watch?v=1",
                video_id="1",
                views="1000",
                duration="2:00",
                channel_name="Canal",
                channel_url="https://youtube.com/@canal",
            ),
            VideoData(
                title="Dos",
                url="https://youtube.com/watch?v=2",
                video_id="2",
                views="2000",
                duration="3:00",
                channel_name="Canal",
                channel_url="https://youtube.com/@canal",
            ),
        ],
    )
    document = build_video_brief(
        channel_overview(channel), topic="Canal", duration=90
    )
    script = brief_to_script(document, channel_overview(channel))
    text = chapters_from_script(script)
    # El guion corto puede no dar 3 capítulos válidos de 10 s; si los da, el
    # primero es 00:00 y cada línea tiene marca de tiempo.
    if text:
        assert text.startswith("00:00 ")
        assert len(text.splitlines()) >= 3


def test_chapters_from_script_vacio_sin_timeline():
    assert chapters_from_script(SimpleNamespace()) == ""


# ---------------------------------------------------------------------------
# YouTubeUploader: miniatura y pistas
# ---------------------------------------------------------------------------


def test_set_thumbnail(monkeypatch, tmp_path: Path):
    image = tmp_path / "t.jpg"
    image.write_bytes(b"\xff\xd8img")

    def handler(method, url, kwargs):
        assert "thumbnails/set" in url
        assert kwargs["params"]["videoId"] == VIDEO_ID
        assert kwargs["params"]["uploadType"] == "media"
        assert kwargs["headers"]["Content-Type"] == "image/jpeg"
        assert kwargs["content"] == b"\xff\xd8img"
        return FakeResponse(json_data={"items": [{"default": {"url": "u"}}]})

    make_fake_client(monkeypatch, {"post": handler})
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    resource = asyncio.run(uploader.set_thumbnail(VIDEO_ID, image))
    assert "items" in resource


def test_set_thumbnail_fichero_inexistente(monkeypatch, tmp_path: Path):
    make_fake_client(monkeypatch, {"post": lambda *a: None})
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    with pytest.raises(FileNotFoundError):
        asyncio.run(uploader.set_thumbnail(VIDEO_ID, tmp_path / "no.jpg"))


def test_upload_caption(monkeypatch, tmp_path: Path):
    srt = tmp_path / "l.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHola\n", encoding="utf-8")

    def handler(method, url, kwargs):
        assert url.endswith("/upload/youtube/v3/captions")
        assert kwargs["params"]["uploadType"] == "multipart"
        assert kwargs["params"]["part"] == "snippet"
        assert kwargs["headers"]["Content-Type"].startswith("multipart/related; boundary=")
        assert b'"language": "es"' in kwargs["content"]
        assert b"Hola" in kwargs["content"]
        return FakeResponse(json_data={"id": "cap1", "snippet": {"language": "es"}})

    make_fake_client(monkeypatch, {"post": handler})
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    resource = asyncio.run(uploader.upload_caption(VIDEO_ID, srt, language="es"))
    assert resource["id"] == "cap1"


def test_upload_caption_fichero_inexistente(monkeypatch, tmp_path: Path):
    make_fake_client(monkeypatch, {"post": lambda *a: None})
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    with pytest.raises(FileNotFoundError):
        asyncio.run(uploader.upload_caption(VIDEO_ID, tmp_path / "no.srt"))


def test_list_and_delete_captions(monkeypatch, tmp_path: Path):
    def get_handler(method, url, kwargs):
        assert kwargs["params"]["videoId"] == VIDEO_ID
        return FakeResponse(json_data={"items": [{"id": "cap1"}]})

    def delete_handler(method, url, kwargs):
        assert kwargs["params"]["id"] == "cap1"
        return FakeResponse(status_code=204)

    make_fake_client(monkeypatch, {"get": get_handler, "delete": delete_handler})
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    assert asyncio.run(uploader.list_captions(VIDEO_ID)) == [{"id": "cap1"}]
    asyncio.run(uploader.delete_caption("cap1"))


def test_scope_hint_en_403(monkeypatch, tmp_path: Path):
    make_fake_client(
        monkeypatch, {"post": lambda *a: FakeResponse(status_code=403)}
    )
    uploader = YouTubeUploader(auth_with_token(tmp_path))
    image = tmp_path / "t.jpg"
    image.write_bytes(b"\xff\xd8")
    with pytest.raises(RuntimeError, match="force-ssl"):
        asyncio.run(uploader.set_thumbnail(VIDEO_ID, image))


# ---------------------------------------------------------------------------
# CLI youber-upload: nuevos subcomandos
# ---------------------------------------------------------------------------


def test_cli_parser_thumbnail_y_captions():
    from youber.upload.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["thumbnail", "v1", "--video", "v.mp4", "--text", "T", "--time", "3"]
    )
    assert args.command == "thumbnail"
    assert args.video == "v.mp4"
    assert args.time == 3.0

    args = parser.parse_args(["captions", "v1", "l.srt", "--language", "en", "--draft"])
    assert args.command == "captions"
    assert args.caption == "l.srt"
    assert args.language == "en"
    assert args.draft is True


def test_cli_thumbnail_genera_y_sube(monkeypatch, tmp_path: Path):
    from youber.upload import cli as upload_cli

    captured: dict = {}

    async def fake_make_thumbnail(video, output=None, **kwargs):
        captured["video"] = str(video)
        path = tmp_path / "gen.jpg"
        path.write_bytes(b"\xff\xd8")
        return ThumbnailResult(path=path, timestamp=2.0, text=kwargs.get("text") or "")

    class FakeUploader:
        def __init__(self, auth):
            pass

        async def set_thumbnail(self, video_id, image_path):
            captured["video_id"] = video_id
            captured["image"] = str(image_path)

    monkeypatch.setattr(upload_cli, "make_thumbnail", fake_make_thumbnail)
    monkeypatch.setattr(upload_cli, "YouTubeUploader", FakeUploader)

    args = upload_cli.build_parser().parse_args(
        ["thumbnail", "v1", "--video", "v.mp4", "--text", "Hola"]
    )
    upload_cli.run(args)
    assert captured["video_id"] == "v1"
    assert captured["image"].endswith("gen.jpg")


# ---------------------------------------------------------------------------
# Integración real con FFmpeg (se salta si no hay FFmpeg)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="sin FFmpeg instalado")
def test_make_thumbnail_real_ffmpeg(tmp_path: Path):
    from youber.audio._ffmpeg import run_command

    video = tmp_path / "clip.mp4"
    asyncio.run(
        run_command(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:d=4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(video),
            ]
        )
    )
    result = asyncio.run(make_thumbnail(video, text="Prueba real", size=(640, 360)))
    assert result.path.is_file()
    assert result.path.stat().st_size > 0
    assert result.path.read_bytes().startswith(b"\xff\xd8")
    assert 0.0 <= result.timestamp <= 4.0
