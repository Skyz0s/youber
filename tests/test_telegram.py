"""Tests del bot de Telegram de BARF (handlers, keyboards, messages).

Se usan fakes de ``Update``/``Context`` (sin bot real ni red) y se mockean
los módulos del framework que los handlers delegan.
"""

import json
from pathlib import Path

import pytest

from youber.music.models import Mood, Track
from youber.research.data_models import ChannelData, VideoData
from youber.telegram.commands import COMMANDS
from youber.telegram.handlers import (
    ACTIVE_TASKS,
    TaskStore,
    handle_callback,
    handle_edit,
    handle_help,
    handle_music,
    handle_research,
    handle_schedule,
    handle_status,
    handle_upload,
    handle_workflow,
)
from youber.telegram.keyboards import confirm_keyboard, mood_keyboard, privacy_keyboard
from youber.telegram.messages import (
    escape_html,
    format_channel,
    format_help,
    format_scheduled,
    format_status,
    format_tracks,
)

# ---------------------------------------------------------------------------
# Fakes de Telegram
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.sent.append((text, kwargs))
        return self


class FakeCallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.answered = False
        self.edited: list[tuple[str, dict]] = []

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text: str, **kwargs):
        self.edited.append((text, kwargs))


class FakeUpdate:
    def __init__(self, args: list[str] | None = None, callback_data: str | None = None):
        self.effective_message = FakeMessage()
        self.callback_query = (
            FakeCallbackQuery(callback_data) if callback_data is not None else None
        )
        self._args = args or []


class FakeContext:
    def __init__(self, args: list[str] | None = None):
        self.args = args or []
        self.bot_data = {}
        self.user_data = {}
        self.chat_data = {}


def sent_text(update: FakeUpdate) -> str:
    return update.effective_message.sent[-1][0]


def sent_kwargs(update: FakeUpdate) -> dict:
    return update.effective_message.sent[-1][1]


# ---------------------------------------------------------------------------
# Mocks de los módulos del framework
# ---------------------------------------------------------------------------


def make_channel() -> ChannelData:
    return ChannelData(
        name="Canal Demo",
        url="https://www.youtube.com/@canaldemo",
        handle="canaldemo",
        subscribers="12,3 K",
        videos=[
            VideoData(
                title="Vídeo de prueba",
                url="https://www.youtube.com/watch?v=abc",
                video_id="abc",
                views="1,2 K",
                duration="12:34",
                channel_name="Canal Demo",
                channel_url="https://www.youtube.com/@canaldemo",
            )
        ],
    )


def make_track() -> Track:
    return Track(
        id="t1",
        file_path=Path("/tmp/musica.mp3"),
        title="Mi tema",
        artist="Artista",
        duration=180.0,
        moods=[Mood.RELAXING],
        file_hash="abc",
    )


class FakeAnalyzer:
    async def analyze(self, channel, max_videos=10, mode="html"):
        return make_channel()


class FakeLibrary:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def search(self, **kwargs):
        return [make_track()]

    def suggest(self, mood=None, limit=5):
        return [make_track()]

    def close(self):
        self.closed = True


class FakeUploader:
    def __init__(self, auth):
        self.auth = auth

    async def upload_video(self, video, metadata):
        return {"id": "video123"}

    @staticmethod
    def get_video_url(video_id):
        return f"https://www.youtube.com/watch?v={video_id}"


@pytest.fixture(autouse=True)
def clean_tasks():
    ACTIVE_TASKS.clear()
    yield
    ACTIVE_TASKS.clear()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def test_escape_html():
    assert escape_html("<b>&") == "&lt;b&gt;&amp;"


def test_format_channel():
    text = format_channel(make_channel())
    assert "Canal Demo" in text
    assert "Vídeo de prueba" in text
    assert "<b>" in text  # HTML parse mode


def test_format_tracks_empty_and_full():
    assert "No hay pistas" in format_tracks([])
    text = format_tracks([make_track()])
    assert "Mi tema" in text
    assert "relajante" in text


def test_format_scheduled_empty_and_full():
    assert "No hay tareas" in format_scheduled([])
    text = format_scheduled([{"id": "abc", "command": "research", "target": "@python", "cadence": "daily"}])
    assert "abc" in text
    assert "@python" in text


def test_format_status_empty_and_full():
    assert "Sin tareas" in format_status({})
    text = format_status({"research @python": "en curso"})
    assert "research @python" in text


def test_format_help():
    text = format_help(COMMANDS)
    assert "/research" in text
    assert "/help" in text
    assert "Investiga un canal" in text


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------


def test_mood_keyboard():
    keyboard = mood_keyboard()
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == len(Mood)
    assert any(button.callback_data == "mood:relajante" for button in buttons)


def test_privacy_keyboard():
    keyboard = privacy_keyboard()
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == 3
    assert any(button.callback_data == "privacy:public" for button in buttons)


def test_confirm_keyboard():
    keyboard = confirm_keyboard("upload", "video.mp4")
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.callback_data for button in buttons] == [
        "upload:yes:video.mp4",
        "upload:no:video.mp4",
    ]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def test_handle_research_requires_arg():
    update = FakeUpdate(args=[])
    await handle_research(update, FakeContext())
    assert "Uso:" in sent_text(update)


async def test_handle_research_ok(monkeypatch):
    monkeypatch.setattr("youber.telegram.handlers.ChannelAnalyzer", FakeAnalyzer)
    update = FakeUpdate(args=["@python"])
    await handle_research(update, FakeContext(args=["@python"]))
    texts = [text for text, _ in update.effective_message.sent]
    assert any(text.startswith("🔄") for text in texts)
    assert any("Canal Demo" in text for text in texts)
    assert sent_kwargs(update)["parse_mode"] == "HTML"


async def test_handle_music_search(monkeypatch):
    monkeypatch.setattr("youber.telegram.handlers.MusicLibrary", FakeLibrary)
    update = FakeUpdate(args=["search", "piano"])
    await handle_music(update, FakeContext(args=["search", "piano"]))
    assert "Mi tema" in sent_text(update)


async def test_handle_music_suggest(monkeypatch):
    monkeypatch.setattr("youber.telegram.handlers.MusicLibrary", FakeLibrary)
    update = FakeUpdate(args=["suggest", "relajante"])
    await handle_music(update, FakeContext(args=["suggest", "relajante"]))
    assert "Mi tema" in sent_text(update)


async def test_handle_music_usage():
    update = FakeUpdate(args=[])
    await handle_music(update, FakeContext())
    assert "Uso:" in sent_text(update)


async def test_handle_workflow_ok(monkeypatch):
    async def fake_run_workflow(**kwargs):
        return {
            "channel": "Canal Demo",
            "final_video": "reports/final.mp4",
            "json": "reports/c.json",
            "csv": "reports/c.csv",
        }

    monkeypatch.setattr("youber.telegram.handlers.run_workflow", fake_run_workflow)
    update = FakeUpdate(args=["@python", "--edit"])
    await handle_workflow(update, FakeContext(args=["@python", "--edit"]))
    assert "Flujo completado" in sent_text(update)
    assert "final.mp4" in sent_text(update)


async def test_handle_workflow_usage():
    update = FakeUpdate(args=[])
    await handle_workflow(update, FakeContext())
    assert "Uso:" in sent_text(update)


async def test_handle_edit_ok(monkeypatch, tmp_path: Path):
    project = tmp_path / "proyecto.json"
    project.write_text(
        json.dumps({"title": "Mi vídeo", "clips": [], "resolution": [640, 360], "fps": 30}),
        encoding="utf-8",
    )

    class FakeEditor:
        @staticmethod
        def load(path):
            from youber.video.models import Project

            return Project(title="Mi vídeo", resolution=(640, 360), fps=30)

        async def render(self, project, output, music_path=None):
            return output

    monkeypatch.setattr("youber.telegram.handlers.VideoEditor", FakeEditor)
    update = FakeUpdate(args=[str(project)])
    await handle_edit(update, FakeContext(args=[str(project)]))
    assert "Vídeo renderizado" in sent_text(update)


async def test_handle_status():
    update = FakeUpdate()
    await handle_status(update, FakeContext())
    assert "Sin tareas" in sent_text(update)


async def test_handle_schedule_add_and_list(monkeypatch, tmp_path: Path):
    tasks_file = tmp_path / "tasks.json"
    monkeypatch.setattr("youber.telegram.handlers.TASKS_FILE", tasks_file)

    update = FakeUpdate(args=["add", "@python", "--daily"])
    await handle_schedule(update, FakeContext(args=["add", "@python", "--daily"]))
    assert "Tarea programada" in sent_text(update)

    update2 = FakeUpdate(args=["list"])
    await handle_schedule(update2, FakeContext(args=["list"]))
    assert "@python" in sent_text(update2)
    assert "daily" in sent_text(update2)


async def test_handle_schedule_usage():
    update = FakeUpdate(args=[])
    await handle_schedule(update, FakeContext())
    assert "Uso:" in sent_text(update)


async def test_handle_upload_ok(monkeypatch, tmp_path: Path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x")

    class FakeAuth:
        pass

    monkeypatch.setattr("youber.telegram.handlers.YouTubeAuth", FakeAuth)
    monkeypatch.setattr("youber.telegram.handlers.YouTubeUploader", FakeUploader)

    update = FakeUpdate(args=[str(video), "--title", "Mi Video"])
    await handle_upload(update, FakeContext(args=[str(video), "--title", "Mi Video"]))
    assert "Vídeo subido" in sent_text(update)
    assert "watch?v=video123" in sent_text(update)


async def test_handle_upload_usage():
    update = FakeUpdate(args=[])
    await handle_upload(update, FakeContext())
    assert "Uso:" in sent_text(update)


async def test_handle_help():
    update = FakeUpdate()
    await handle_help(update, FakeContext())
    assert "/research" in sent_text(update)
    assert sent_kwargs(update)["parse_mode"] == "HTML"


async def test_handle_callback_mood(monkeypatch):
    monkeypatch.setattr("youber.telegram.handlers.MusicLibrary", FakeLibrary)
    update = FakeUpdate(callback_data="mood:relajante")
    await handle_callback(update, FakeContext())
    assert update.callback_query.answered is True
    assert "Mi tema" in update.callback_query.edited[-1][0]


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------


def test_task_store_roundtrip(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.add("research", "@python", cadence="daily")
    tasks = store.load()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task["id"]
    assert store.remove(task["id"]) is True
    assert store.load() == []
