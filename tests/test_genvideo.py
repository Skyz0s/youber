"""Tests del motor de generación de vídeo local (``youber.genvideo``).

Sin GPU, sin ComfyUI y sin salir a internet: la API de ComfyUI se prueba con un
``httpx.MockTransport`` y el lote completo con el backend de pruebas
``StubClient`` (que escribe un MP4 sintético con FFmpeg). Los tests que
necesitan FFmpeg de verdad se saltan solos si no está instalado.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path

import httpx
import pytest

from youber.genvideo import power
from youber.genvideo.cli import main as genvideo_main
from youber.genvideo.client import (
    ComfyUIClient,
    ComfyUIError,
    StubClient,
    outputs_from,
)
from youber.genvideo.graph import SAVE_NODE, build_graph, save_node_id
from youber.genvideo.models import (
    BatchReport,
    ClipQuality,
    ClipRequest,
    GenConfig,
    JobStatus,
    Resolution,
    clip_id,
    estimate_clip_seconds,
)
from youber.genvideo.queue import JobQueue
from youber.genvideo.runner import (
    NightlyRunner,
    requests_from_prompts,
    requests_from_script,
    resolve_window,
    run_nightly,
    script_from_topic,
    write_report,
)
from youber.genvideo.verify import judge_quality, parse_fraction, verify_clip
from youber.scheduler.jobs import JOB_RUNNERS, run_job
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType
from youber.script.generator import generate_script

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no instalado")


def _prompt_clip(prompt: str = "un tren cruzando un valle nevado") -> ClipRequest:
    """Clip de prueba con la configuración 480p (la barata)."""
    config = GenConfig.for_resolution(Resolution.SD)
    return ClipRequest(prompt=prompt, seed=1, config=config)


# -- modelos --------------------------------------------------------------


def test_presets_medidos():
    """Los presets son los medidos en el spike, no valores al azar."""
    hd = GenConfig.for_resolution("720p")
    sd = GenConfig.for_resolution("480p")
    assert (hd.width, hd.height, hd.steps) == (1280, 704, 8)
    assert (sd.width, sd.height, sd.steps) == (832, 480, 4)
    assert hd.resolution == Resolution.HD
    assert hd.clip_seconds == pytest.approx(121 / 24, rel=1e-6)
    assert "720p" in hd.describe()
    assert "VAEDecodeTiled" in hd.describe()


def test_describe_sin_lora():
    """Sin LoRA, el resumen lo dice (y no miente con un nombre de fichero)."""
    config = GenConfig(lora_name=None, tiled_vae=False)
    assert "sin LoRA" in config.describe()
    assert "VAEDecode" in config.describe()


def test_estimate_clip_seconds_anclas():
    """La estimación coincide con lo medido en las dos anclas."""
    assert estimate_clip_seconds(GenConfig.for_resolution("720p")) == pytest.approx(600, rel=0.01)
    assert estimate_clip_seconds(GenConfig.for_resolution("480p")) == pytest.approx(180, rel=0.01)
    mas_lento = GenConfig.for_resolution("720p", steps=16)
    assert estimate_clip_seconds(mas_lento) > estimate_clip_seconds(GenConfig.for_resolution("720p"))


def test_clip_id_determinista():
    """El identificador depende del contenido: reencolar no duplica."""
    first = clip_id("un prompt", 3, width=832, steps=4)
    assert first == clip_id("un prompt", 3, width=832, steps=4)
    assert first != clip_id("un prompt", 4, width=832, steps=4)
    assert first != clip_id("un prompt", 3, width=1280, steps=4)


# -- grafo ----------------------------------------------------------------


def test_build_graph_estructura():
    """El grafo lleva los nodos de Wan 2.2 y los ajustes del clip."""
    request = _prompt_clip()
    request.config.steps = 6
    graph = build_graph(request, filename_prefix="genvideo/batch/clip")
    classes = {node["class_type"] for node in graph.values()}
    assert {
        "UNETLoader",
        "LoraLoaderModelOnly",
        "CLIPLoader",
        "VAELoader",
        "CLIPTextEncode",
        "ModelSamplingSD3",
        "Wan22ImageToVideoLatent",
        "KSampler",
        "VAEDecodeTiled",
        "CreateVideo",
        SAVE_NODE,
    } <= classes
    sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
    assert sampler["inputs"]["steps"] == 6
    assert sampler["inputs"]["seed"] == request.seed
    latent = next(
        node for node in graph.values() if node["class_type"] == "Wan22ImageToVideoLatent"
    )
    assert latent["inputs"]["width"] == request.config.width
    assert latent["inputs"]["length"] == request.config.frames
    save = graph[save_node_id(graph) or ""]
    assert save["inputs"]["filename_prefix"] == "genvideo/batch/clip"
    encode = [node for node in graph.values() if node["class_type"] == "CLIPTextEncode"]
    assert request.prompt in {node["inputs"]["text"] for node in encode}


def test_build_graph_sin_lora_ni_vae_troceado():
    """Sin LoRA no hay nodo de LoRA, y sin trocear se usa VAEDecode normal."""
    request = _prompt_clip()
    request.config.lora_name = None
    request.config.tiled_vae = False
    graph = build_graph(request, filename_prefix="x/y")
    classes = {node["class_type"] for node in graph.values()}
    assert "LoraLoaderModelOnly" not in classes
    assert "VAEDecodeTiled" not in classes
    assert "VAEDecode" in classes


def test_build_graph_multiplier_latente():
    """El multiplicador del latente solo añade nodo si no es 1,0."""
    request = _prompt_clip()
    assert "LatentMultiply" not in {
        node["class_type"] for node in build_graph(request, filename_prefix="x").values()
    }
    request.config.latent_multiplier = 0.8
    assert "LatentMultiply" in {
        node["class_type"] for node in build_graph(request, filename_prefix="x").values()
    }


def test_save_node_id_ausente():
    """Un grafo sin SaveVideo no tiene nodo de guardado."""
    assert save_node_id({"1": {"class_type": "KSampler"}}) is None


# -- cliente de ComfyUI ---------------------------------------------------


def test_outputs_from_history():
    """Los ficheros se extraen con independencia del nombre de la clave."""
    entry = {
        "outputs": {
            "12": {
                "images": [{"filename": "gen_00001_.mp4", "subfolder": "genvideo", "type": "output"}],
                "animated": [True],
            },
            "13": {"images": []},
        }
    }
    outputs = outputs_from(entry)
    assert len(outputs) == 1
    assert outputs[0].filename == "gen_00001_.mp4"
    assert outputs[0].node_id == "12"
    assert outputs[0].is_video


def _transport(handler: object) -> httpx.AsyncClient:
    """Cliente HTTP con transporte simulado (sin red)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_comfy_client_flujo_completo(tmp_path: Path):
    """Encolar → esperar → salidas → descarga, contra un servidor simulado."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path == "/history/p-1":
            return httpx.Response(
                200,
                json={
                    "p-1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"12": {"images": [{"filename": "clip.mp4", "subfolder": ""}]}},
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=b"MP4!")
        return httpx.Response(404)

    async def scenario() -> None:
        client = ComfyUIClient(client=_transport(handler), poll_interval=0.01)
        graph = build_graph(_prompt_clip(), filename_prefix="x")
        prompt_id = await client.queue_prompt(graph)
        assert prompt_id == "p-1"
        entry = await client.wait(prompt_id, timeout=5)
        assert entry["status"]["completed"]
        outputs = outputs_from(entry)
        assert outputs[0].filename == "clip.mp4"
        target = await client.download(outputs[0], tmp_path / "clip.mp4")
        assert target.read_bytes() == b"MP4!"

    asyncio.run(scenario())
    assert "POST /prompt" in seen
    assert "GET /history/p-1" in seen
    assert "GET /view" in seen


def test_comfy_client_rechaza_grafo():
    """Un 400 del servidor se convierte en error legible (no en un KeyError)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Node ID '#3' not found")

    async def scenario() -> None:
        client = ComfyUIClient(client=_transport(handler))
        with pytest.raises(ComfyUIError, match="rechazó"):
            await client.queue_prompt({"1": {"class_type": "X"}})

    asyncio.run(scenario())


def test_comfy_client_error_de_ejecucion():
    """Un trabajo fallido en el servidor explica qué nodo falló."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "p-2": {
                    "status": {
                        "status_str": "error",
                        "completed": False,
                        "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "OOM"}]],
                    }
                }
            },
        )

    async def scenario() -> None:
        client = ComfyUIClient(client=_transport(handler), poll_interval=0.01)
        with pytest.raises(ComfyUIError, match="OOM"):
            await client.wait("p-2", timeout=5)

    asyncio.run(scenario())


def test_comfy_client_timeout():
    """Sin historial, el cliente corta por tiempo en vez de esperar eternamente."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> None:
        client = ComfyUIClient(client=_transport(handler), poll_interval=0.01)
        with pytest.raises(ComfyUIError, match="Timeout"):
            await client.wait("p-3", timeout=0.05)

    asyncio.run(scenario())


def test_comfy_client_is_up_y_opciones():
    """/system_stats y /object_info se leen sin explotar si vienen raros."""
    stats = {"ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if request.url.path == "/object_info/UNETLoader":
            return httpx.Response(
                200, json={"UNETLoader": {"input": {"required": {"unet_name": [["a.safetensors"]]}}}}
            )
        return httpx.Response(404, text="nope")

    async def scenario() -> None:
        client = ComfyUIClient(client=_transport(handler))
        stats["ok"] = await client.is_up()
        options = await client.available_options("UNETLoader", "unet_name")
        assert options == ["a.safetensors"]
        with pytest.raises(ComfyUIError, match="404"):
            await client.available_options("NoExiste", "x")

    asyncio.run(scenario())
    assert stats["ok"] is True


# -- cola -----------------------------------------------------------------


def test_queue_persiste_y_reanuda(tmp_path: Path):
    """La cola sobrevive al reinicio y devuelve a pendiente lo que quedó a medias."""
    path = tmp_path / "queue.json"
    queue = JobQueue(path)
    clip = _prompt_clip()
    queue.add(clip)
    assert path.exists()

    otra = JobQueue(path)
    assert [item.id for item in otra.requests] == [clip.id]

    en_curso = otra.requests[0]
    en_curso.status = JobStatus.RUNNING
    otra.update(en_curso)
    assert JobQueue(path).by_status(JobStatus.RUNNING)[0].id == clip.id
    assert JobQueue(path).recover() == 1
    assert JobQueue(path).pending()[0].id == clip.id


def test_queue_no_duplica_al_reencolar(tmp_path: Path):
    """Reencolar el mismo trabajo (mismo id) no lo duplica."""
    path = tmp_path / "queue.json"
    queue = JobQueue(path)
    clip = _prompt_clip()
    assert len(queue.extend([clip])) == 1
    assert queue.extend([clip]) == []
    assert queue.stats()["total"] == 1


def test_queue_estados_y_limpieza(tmp_path: Path):
    """Estados, reencolado de fallidos y borrado."""
    queue = JobQueue(tmp_path / "queue.json")
    first = queue.add(_prompt_clip("uno"))
    second = queue.add(_prompt_clip("dos"))
    first.status = JobStatus.DONE
    second.status = JobStatus.FAILED
    queue.update(first)
    queue.update(second)
    stats = queue.stats()
    assert stats["done"] == 1 and stats["failed"] == 1 and stats["total"] == 2
    assert queue.requeue_failed() == 1
    assert queue.stats()["pending"] == 1
    assert queue.clear(JobStatus.DONE) == 1
    assert queue.stats()["total"] == 1


def test_queue_json_roto_no_revienta(tmp_path: Path):
    """Un JSON corrupto deja la cola vacía en vez de romper el arranque."""
    path = tmp_path / "queue.json"
    path.write_text("{esto no es json", encoding="utf-8")
    assert JobQueue(path).requests == []


# -- verificación ---------------------------------------------------------


def test_judge_quality_clip_plano():
    """Detalle bajo = imagen plana (lo que pasa con Turbo a 4 steps a 720p)."""
    quality = ClipQuality(duration=5.0, width=64, height=64, fps=24.0, frames=120, detail=12.0)
    judged = judge_quality(quality)
    assert not judged.ok
    assert any("detalle bajo" in reason for reason in judged.reasons)


def test_judge_quality_oscuro_y_congelado():
    """Un clip negro o inmóvil tampoco vale."""
    negro = ClipQuality(duration=5.0, width=64, height=64, fps=24.0, frames=120, brightness=4.0)
    assert not judge_quality(negro).ok
    congelado = ClipQuality(
        duration=5.0, width=64, height=64, fps=24.0, frames=120, motion=0.0
    )
    reasons = judge_quality(congelado).reasons
    assert any("sin movimiento" in reason for reason in reasons)


def test_judge_quality_correcto_y_dimensiones():
    """Un clip bueno pasa; si no cuadran las medidas, se dice."""
    bueno = ClipQuality(
        duration=5.04, width=832, height=480, fps=24.0, frames=121, brightness=120.0, detail=48.0, motion=6.0
    )
    assert judge_quality(bueno, width=832, height=480, fps=24.0, frames=121).ok
    malo = judge_quality(bueno, width=1280, height=704, frames=200)
    assert not malo.ok
    assert any("ancho" in reason for reason in malo.reasons)
    assert any("frames" in reason for reason in malo.reasons)


def test_judge_quality_vacio():
    """Un fichero sin flujo de vídeo se detecta como vacío."""
    judged = judge_quality(ClipQuality())
    assert not judged.ok
    assert any("vacío" in reason for reason in judged.reasons)


def test_parse_fraction():
    """Los fps de ffprobe vienen como fracción."""
    assert parse_fraction("24/1") == 24.0
    assert parse_fraction("30000/1001") == pytest.approx(29.97, rel=1e-3)
    assert parse_fraction(None) == 0.0
    assert parse_fraction("basura") == 0.0


@needs_ffmpeg
def test_verify_clip_real(tmp_path: Path):
    """Verificación de verdad: un clip con imagen pasa y uno negro no."""
    import subprocess

    bueno = tmp_path / "bueno.mp4"
    negro = tmp_path / "negro.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=832x480:r=24",
         "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(bueno)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=832x480:r=24",
         "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(negro)],
        check=True,
    )
    quality = asyncio.run(verify_clip(bueno, width=832, height=480))
    assert quality.ok, quality.reasons
    assert quality.detail is not None and quality.detail > 25
    plano = asyncio.run(verify_clip(negro))
    assert not plano.ok
    with pytest.raises(FileNotFoundError):
        asyncio.run(verify_clip(tmp_path / "no-existe.mp4"))


# -- ventana y plan de clips ----------------------------------------------


def test_resolve_window_cruza_medianoche():
    """Una ventana 22:00-07:00 termina mañana, no hoy (aunque 07:00 ya haya pasado)."""
    referencia = datetime(2026, 9, 28, 21, 0)
    start, end = resolve_window(dt_time(22, 0), dt_time(7, 0), now=referencia)
    assert start == referencia  # 22:00 aún no ha llegado: empieza ya
    assert end == datetime(2026, 9, 29, 7, 0)

    dentro = datetime(2026, 9, 28, 23, 30)
    start, end = resolve_window(dt_time(22, 0), dt_time(7, 0), now=dentro)
    assert start == dentro  # ya estamos dentro de la ventana
    assert end == datetime(2026, 9, 29, 7, 0)


def test_resolve_window_con_espera():
    """Con ``allow_wait`` el lote espera a la hora de inicio si aún no ha llegado."""
    referencia = datetime(2026, 9, 28, 20, 0)
    start, end = resolve_window(
        dt_time(22, 0), dt_time(7, 0), now=referencia, allow_wait=True
    )
    assert start == datetime(2026, 9, 28, 22, 0)
    assert end == datetime(2026, 9, 29, 7, 0)


def test_resolve_window_sin_horas():
    """Sin ventana no hay ni inicio ni cierre."""
    assert resolve_window(None, None, now=datetime(2026, 9, 28, 20, 0)) == (None, None)


def test_requests_from_script_deterministas():
    """Los clips salen del plan visual: al menos un plano por escena y semillas estables."""
    script = generate_script({}, topic="el paso del tiempo", duration=60)
    config = GenConfig.for_resolution("480p")
    first = requests_from_script(script, config=config, shots=4)
    second = requests_from_script(script, config=config, shots=4)
    # Cada escena aporta al menos un plano, así que nunca salen menos que escenas.
    assert len(first) >= max(4, len(script.scenes))
    assert [clip.id for clip in first] == [clip.id for clip in second]
    assert len({clip.seed for clip in first}) == len(first)
    assert all(clip.config.width == 832 for clip in first)
    assert {clip.scene_type for clip in first} == {scene.type.value for scene in script.scenes}
    assert all(clip.duration_hint and clip.duration_hint > 0 for clip in first)
    assert all(clip.id == clip_id(clip.prompt, clip.seed, width=832, steps=4) for clip in first)


def test_requests_from_prompts():
    """El camino corto: un clip por prompt."""
    config = GenConfig.for_resolution("720p")
    requests = requests_from_prompts(["uno", "dos"], config=config)
    assert [clip.prompt for clip in requests] == ["uno", "dos"]
    assert requests[0].seed != requests[1].seed


def test_script_from_topic():
    """Un tema suelto genera un guion usable sin canal de referencia."""
    script = script_from_topic("prueba")
    assert script.topic == "prueba"
    assert script.scenes


# -- runner ---------------------------------------------------------------


def _run(coro: object) -> object:
    """Ejecuta una corrutina en un bucle nuevo (los tests son síncronos)."""
    return asyncio.run(coro)  # type: ignore[arg-type]


@needs_ffmpeg
def test_runner_lote_completo_con_stub(tmp_path: Path):
    """Lote de punta a punta con el backend de pruebas: clips verificados."""
    report = _run(
        run_nightly(
            prompts=["un tren en la nieve", "una calle vacía de noche"],
            preset=Resolution.SD,
            stub=True,
            output_dir=tmp_path / "clips",
            report_dir=tmp_path / "reports",
            state_path=tmp_path / "queue.json",
        )
    )
    assert isinstance(report, BatchReport)
    assert len(report.done) == 2
    assert report.failed == []
    assert report.stopped_reason == "cola vacía"
    assert report.metrage == pytest.approx(2 * 121 / 24, rel=1e-6)
    for clip in report.done:
        assert clip.output and Path(clip.output).exists()
        assert clip.quality is not None and clip.quality.ok
    assert (tmp_path / "reports" / f"lote-{report.id}.md").exists()
    assert (tmp_path / "reports" / f"lote-{report.id}.json").exists()


@needs_ffmpeg
def test_runner_reintenta_clip_plano(tmp_path: Path):
    """Un clip plano se reintenta con más steps y, si sigue plano, se descarta."""
    report = _run(
        run_nightly(
            prompts=["clip que sale plano"],
            preset=Resolution.HD,
            stub=True,
            stub_flat=True,
            output_dir=tmp_path / "clips",
            state_path=tmp_path / "queue.json",
        )
    )
    assert report.done == []
    assert len(report.failed) == 1
    assert report.total == 2  # dos intentos
    descartado = report.failed[0]
    assert descartado.attempts == 2
    assert descartado.config.steps == 16  # 8 → 16 al reintentar
    assert descartado.error and "verificación" in descartado.error


@needs_ffmpeg
def test_runner_puede_no_verificar(tmp_path: Path):
    """Con ``verify=False`` el clip se da por bueno aunque salga plano."""
    report = _run(
        run_nightly(
            prompts=["sin verificar"],
            preset=Resolution.SD,
            stub=True,
            stub_flat=True,
            verify=False,
            output_dir=tmp_path / "clips",
            state_path=tmp_path / "queue.json",
        )
    )
    assert len(report.done) == 1


@needs_ffmpeg
def test_runner_reanuda_sin_duplicar(tmp_path: Path):
    """Reanudar un lote continúa donde iba y no repite clips ya hechos."""
    state = tmp_path / "queue.json"
    prompts = ["uno", "dos", "tres"]
    first = _run(
        run_nightly(
            prompts=prompts,
            preset=Resolution.SD,
            stub=True,
            max_clips=1,
            output_dir=tmp_path / "clips",
            state_path=state,
        )
    )
    assert len(first.done) == 1
    assert first.stopped_reason.startswith("alcanzado el máximo")
    pendientes = JobQueue(state).pending()
    assert len(pendientes) == 2

    second = _run(
        run_nightly(
            prompts=prompts,
            preset=Resolution.SD,
            stub=True,
            output_dir=tmp_path / "clips",
            state_path=state,
        )
    )
    assert len(second.done) == 2
    assert JobQueue(state).pending() == []


@needs_ffmpeg
def test_runner_para_en_la_ventana(tmp_path: Path):
    """Pasado el cierre, el lote no arranca nada nuevo (los clips siguen en cola)."""

    async def scenario() -> BatchReport:
        runner = NightlyRunner(
            client=StubClient(),
            config=GenConfig.for_resolution("480p"),
            queue=JobQueue(tmp_path / "queue.json"),
            output_dir=tmp_path / "clips",
            deadline=datetime.now() - timedelta(minutes=1),
        )
        return await runner.run(requests_from_prompts(["sin tiempo"], preset=Resolution.SD))

    report = _run(scenario())
    assert report.done == []
    assert "ventana" in report.stopped_reason
    assert JobQueue(tmp_path / "queue.json").pending() != []


def test_ventana_ya_cerrada_pasa_a_mañana():
    """Si la hora de cierre ya pasó, la ventana que se resuelve es la de mañana.

    Es lo que permite lanzar el lote desde la CLI en cualquier momento: la CLI
    enseña siempre el cierre resuelto, así que no hay sorpresas.
    """
    referencia = datetime(2026, 9, 29, 8, 0)
    start, end = resolve_window(dt_time(22, 0), dt_time(7, 0), now=referencia, allow_wait=True)
    assert start == datetime(2026, 9, 29, 22, 0)
    assert end == datetime(2026, 9, 30, 7, 0)


def test_runner_aborta_con_fallos_seguidos(tmp_path: Path):
    """Tres fallos seguidos (backend caído) cortan el lote en vez de insistir."""

    class Roto(StubClient):
        async def queue_prompt(self, graph: dict) -> str:
            raise RuntimeError("ComfyUI no responde")

    async def scenario() -> BatchReport:
        runner = NightlyRunner(
            client=Roto(),
            config=GenConfig.for_resolution("480p"),
            queue=JobQueue(tmp_path / "queue.json"),
            output_dir=tmp_path / "clips",
        )
        return await runner.run(requests_from_prompts(["a", "b", "c", "d"], preset=Resolution.SD))

    report = _run(scenario())
    assert report.done == []
    assert len(report.failed) == 3
    assert "fallos seguidos" in report.stopped_reason


def test_runner_estima_si_cabe_en_la_ventana(tmp_path: Path):
    """Con poco tiempo por delante, el runner no arranca un clip que no cabría."""
    async def scenario() -> BatchReport:
        runner = NightlyRunner(
            client=StubClient(),
            config=GenConfig.for_resolution("720p"),
            queue=JobQueue(tmp_path / "queue.json"),
            output_dir=tmp_path / "clips",
            deadline=datetime.now() + timedelta(minutes=2),
        )
        return await runner.run(requests_from_prompts(["uno"], preset=Resolution.HD))

    report = _run(scenario())
    assert report.done == []
    assert "no cabe otro clip" in report.stopped_reason


@needs_ffmpeg
def test_write_report(tmp_path: Path):
    """El manifiesto guarda el lote entero y el resumen es legible."""
    report = _run(
        run_nightly(
            prompts=["uno"],
            preset=Resolution.SD,
            stub=True,
            output_dir=tmp_path / "clips",
            state_path=tmp_path / "queue.json",
        )
    )
    json_path, markdown_path = write_report(report, tmp_path / "reports")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["id"] == report.id
    assert data["config"]["width"] == 832
    text = markdown_path.read_text(encoding="utf-8")
    assert "Lote de generación" in text
    assert "clips" in text


# -- CLI ------------------------------------------------------------------


def test_cli_check_demo(capsys: pytest.CaptureFixture[str]):
    """``check --demo`` no consulta ComfyUI y enseña la capacidad de una noche."""
    assert genvideo_main(["check", "--demo"]) == 0
    salida = capsys.readouterr().out
    assert "720p" in salida
    assert "clips" in salida
    assert "Modo demo" in salida


def test_cli_enqueue_y_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Encolar desde un fichero de prompts y ver el estado de la cola."""
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("uno\ndos\n", encoding="utf-8")
    state = tmp_path / "queue.json"
    assert genvideo_main(["enqueue", "--prompts", str(prompts), "--state", str(state)]) == 0
    assert "2 clip(s) encolados" in capsys.readouterr().out

    assert genvideo_main(["status", "--state", str(state)]) == 0
    assert "total" in capsys.readouterr().out

    assert genvideo_main(["clear", "--all", "--state", str(state)]) == 0
    assert JobQueue(state).requests == []


def test_cli_enqueue_sin_fuente(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Sin guion, prompts ni tema, la CLI lo dice en vez de fingir que encola."""
    assert genvideo_main(["enqueue", "--state", str(tmp_path / "queue.json")]) == 1
    assert "No hay nada que encolar" in capsys.readouterr().out


def test_cli_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """``report`` reimprime el resumen de un lote guardado."""
    report = BatchReport(id="20260929-0200", config=GenConfig.for_resolution("480p"))
    report.clips.append(ClipRequest(id="x", label="01", prompt="algo"))
    path = tmp_path / "lote.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    assert genvideo_main(["report", str(path)]) == 0
    assert "20260929-0200" in capsys.readouterr().out


@needs_ffmpeg
def test_cli_run_demo(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """``run --demo`` genera un lote completo sin GPU."""
    code = genvideo_main([
        "run",
        "--topic",
        "prueba de humo",
        "--preset",
        "480p",
        "--shots",
        "1",
        "--demo",
        "--max-clips",
        "1",
        "-o",
        str(tmp_path / "clips"),
        "--report",
        str(tmp_path / "reports"),
        "--state",
        str(tmp_path / "queue.json"),
    ])
    assert code == 0
    salida = capsys.readouterr().out
    assert "Lote de generación" in salida
    assert Path(tmp_path / "clips").exists()


@needs_ffmpeg
def test_cli_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """``verify`` mide un clip y devuelve 0 (bueno) o 1 (no sirve)."""
    import subprocess

    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=832x480:r=24",
         "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    assert genvideo_main(["verify", str(clip)]) == 0
    assert "OK" in capsys.readouterr().out


# -- energía -------------------------------------------------------------

#: Salida real de ``powercfg /query ... STANDBYIDLE`` (Windows en español).
POWERCFG_STANDBYIDLE = (
    "GUID de configuración de energía: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  "
    "(Suspender tras)\n"
    "  Mínima configuración posible: 0x00000000\n"
    "  Máxima configuración posible: 0xffffffff\n"
    "  Incremento de configuración posible: 0x00000001\n"
    "  Índice de configuración de corriente alterna actual: 0x00000384\n"
    "  Índice de configuración de corriente continua actual: 0x00000258\n"
)


def _powercfg_result(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """Resultado de ``powercfg`` simulado."""
    return subprocess.CompletedProcess(
        args=["powercfg"], returncode=returncode, stdout=stdout.encode("utf-8"), stderr=b""
    )


def test_standby_timeouts_lee_alterna_y_bateria(monkeypatch: pytest.MonkeyPatch):
    """De la salida localizada se sacan los dos valores (los dos últimos hex)."""
    monkeypatch.setattr(power, "is_windows", lambda: True)
    monkeypatch.setattr(
        power, "_run_powercfg", lambda args: _powercfg_result(POWERCFG_STANDBYIDLE)
    )
    assert power.standby_timeouts() == (900, 600)


def test_standby_timeouts_fuera_de_windows(monkeypatch: pytest.MonkeyPatch):
    """Fuera de Windows no se toca nada."""
    monkeypatch.setattr(power, "is_windows", lambda: False)
    assert power.standby_timeouts() == (None, None)
    assert power.set_standby_timeout(0) is False


def test_set_standby_timeout_comandos(monkeypatch: pytest.MonkeyPatch):
    """Los comandos son los de ``powercfg`` (alterna y batería)."""
    llamadas: list[list[str]] = []
    monkeypatch.setattr(power, "is_windows", lambda: True)

    def fake(args: list[str]) -> subprocess.CompletedProcess:
        llamadas.append(args)
        return _powercfg_result()

    monkeypatch.setattr(power, "_run_powercfg", fake)
    assert power.set_standby_timeout(0) is True
    assert power.set_standby_timeout(600, battery=True) is True
    assert llamadas == [
        ["/change", "standby-timeout-ac", "0"],
        ["/change", "standby-timeout-dc", "600"],
    ]


def test_keep_awake_desactiva_y_restaura(monkeypatch: pytest.MonkeyPatch):
    """El lote deja la suspensión en «nunca» y la devuelve como estaba."""
    llamadas: list[list[str]] = []
    monkeypatch.setattr(power, "is_windows", lambda: True)
    monkeypatch.setattr(power, "standby_timeouts", lambda: (900, 600))

    def fake(args: list[str]) -> subprocess.CompletedProcess:
        llamadas.append(args)
        return _powercfg_result()

    monkeypatch.setattr(power, "_run_powercfg", fake)
    with power.keep_awake() as despierto:
        assert despierto is True
        assert ["/change", "standby-timeout-ac", "0"] in llamadas
    assert llamadas[-2:] == [
        ["/change", "standby-timeout-ac", "900"],
        ["/change", "standby-timeout-dc", "600"],
    ]


def test_keep_awake_fuera_de_windows(monkeypatch: pytest.MonkeyPatch):
    """Sin Windows ``keep_awake`` es un no-op (y lo dice)."""
    monkeypatch.setattr(power, "is_windows", lambda: False)
    with power.keep_awake() as despierto:
        assert despierto is False


# -- enganche con el scheduler -------------------------------------------


def test_genvideo_registrado_en_el_scheduler():
    """El tipo de trabajo existe y tiene runner."""
    assert JobType.GENVIDEO == "genvideo"
    assert JobType.GENVIDEO in JOB_RUNNERS


@needs_ffmpeg
def test_scheduler_ejecuta_lote_genvideo(tmp_path: Path):
    """Un trabajo programado de ``genvideo`` (en modo demo) corre de verdad."""
    job = ScheduledJob(
        id="job-1",
        name="lote nocturno",
        job_type=JobType.GENVIDEO,
        schedule_type=ScheduleType.DAILY,
        schedule_value="22:00",
        params={
            "topic": "prueba del scheduler",
            "preset": "480p",
            "shots": 1,
            "demo": True,
            "max_clips": 1,
            "output_dir": str(tmp_path / "clips"),
            "report_dir": str(tmp_path / "reports"),
            "state": str(tmp_path / "queue.json"),
            "end": "07:00",
        },
    )
    result = _run(run_job(job))
    assert isinstance(result, dict)
    assert result["clips"] == 1
    assert result["metrage"] > 0
