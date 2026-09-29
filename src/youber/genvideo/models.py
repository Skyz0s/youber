"""Modelos del motor de generación de vídeo local (``youber.genvideo``).

El backend de referencia es **ComfyUI** hablando por su API HTTP en local con
Wan 2.2 TI2V-5B; los demás backends se enchufan detrás de la misma interfaz
(:mod:`youber.genvideo.client`). Aquí viven las piezas compartidas: la
configuración de generación (:class:`GenConfig`) con los **presets medidos** en
la RTX 3050, un trabajo de la cola (:class:`ClipRequest`) y el informe de un
lote nocturno (:class:`BatchReport`).

Los números de los presets no son inventados: salen de las mediciones del spike
(``ai/spike/RESULTS.md``). Resumen de lo aprendido allí y que está codificado
aquí:

- a 720p el cuello de botella es la **decodificación del VAE**, no la difusión
  → ``tiled_vae=True`` siempre (5× más rápido y el pico de VRAM baja de 7,9 a
  3,2 GB);
- con la LoRA Turbo hacen falta **8 steps** a 720p (con 4 la imagen sale plana
  y oscura) y bastan **4** a 480p;
- los pesos **GGUF Q8 son un 10 % más lentos** que el fp16 → se usa fp16;
- el multiplicador del latente es cosmético → por defecto 1,0.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

#: Servidor local de ComfyUI por defecto (el que se usó en el spike).
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"

#: Pesos por defecto: Wan 2.2 TI2V-5B en fp16 (el GGUF salió más lento).
DEFAULT_UNET = "wan2.2_ti2v_5B_fp16.safetensors"

#: Codificador de texto y VAE de Wan 2.2.
DEFAULT_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
DEFAULT_VAE = "wan2.2_vae.safetensors"

#: LoRA Turbo: sin ella hacen falta ~20 steps en vez de 8.
DEFAULT_LORA = "wan22_ti2v_5b_turbo_lora_rank64_fp16.safetensors"

#: Fotogramas por segundo de la generación.
DEFAULT_FPS = 24.0

#: 121 frames a 24 fps ≈ 5 s de vídeo (el trozo con el que se midió todo).
DEFAULT_FRAMES = 121

#: Wan 2.2 comprime el tiempo 4×: la longitud del latente tiene que ser ``4k+1``.
FRAME_STEP = 4

#: Rango sensato de duración por clip: 49 frames ≈ 2 s y 241 ≈ 10 s.
MIN_FRAMES = 49
MAX_FRAMES = 241

#: Prompt negativo por defecto. Con cfg 1,0 (Turbo) su peso es pequeño; se
#: queda corto y en inglés a propósito, que es lo que entienden los modelos.
DEFAULT_NEGATIVE_PROMPT = (
    "static image, still frame, blurry, low quality, distorted anatomy, extra limbs, "
    "watermark, text, subtitles, jpeg artifacts, flicker, oversaturated"
)


class Resolution(StrEnum):
    """Resolución de generación (los dos presets medidos en la RTX 3050)."""

    HD = "720p"
    SD = "480p"


#: Ajustes medidos por preset. 720p necesita 8 steps para no salir plano;
#: 480p aguanta el detalle con 4 (es el preset barato: ~2,8 min por clip).
PRESET_SETTINGS: dict[Resolution, dict[str, Any]] = {
    Resolution.HD: {"width": 1280, "height": 704, "steps": 8},
    Resolution.SD: {"width": 832, "height": 480, "steps": 4},
}

#: Anclas medidas (píxeles, steps, frames) → segundos por clip. Se usan solo
#: para decidir si un clip más cabe antes del cierre de la ventana nocturna.
MEASURED_SECONDS: tuple[tuple[int, int, int, float], ...] = (
    (1280 * 704, 8, 121, 600.0),
    (832 * 480, 4, 121, 180.0),
)


class JobStatus(StrEnum):
    """Estado de un clip dentro de la cola."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class GenConfig(BaseModel):
    """Configuración de una generación: los ajustes que van al grafo.

    Los valores por defecto son la **receta definitiva** del spike (720p,
    Turbo, VAE troceado, 8 steps).
    """

    server_url: str = DEFAULT_SERVER_URL
    unet_name: str = DEFAULT_UNET
    clip_name: str = DEFAULT_CLIP
    vae_name: str = DEFAULT_VAE
    lora_name: str | None = DEFAULT_LORA
    lora_strength: float = 1.0
    steps: int = Field(default=8, ge=1, le=100)
    cfg: float = Field(default=1.0, ge=0.0, le=20.0)
    shift: float = Field(default=8.0, ge=0.0)
    sampler_name: str = "euler"
    scheduler: str = "simple"
    fps: float = Field(default=DEFAULT_FPS, gt=0)
    width: int = Field(default=1280, ge=64)
    height: int = Field(default=704, ge=64)
    frames: int = Field(default=DEFAULT_FRAMES, ge=1)
    tiled_vae: bool = True
    tile_size: int = Field(default=256, ge=64)
    tile_overlap: int = Field(default=64, ge=0)
    temporal_size: int = Field(default=16, ge=1)
    temporal_overlap: int = Field(default=4, ge=0)
    latent_multiplier: float = 1.0
    weight_dtype: str = "default"
    timeout_seconds: int = Field(default=3600, gt=0)
    output_dir: Path | None = None
    resolution: Resolution | None = None

    @classmethod
    def for_resolution(cls, resolution: Resolution | str, **overrides: Any) -> GenConfig:
        """Configuración de un preset (``"720p"`` o ``"480p"``) con retoques.

        Args:
            resolution: Preset medido.
            **overrides: Campos que se quieren cambiar sobre el preset.

        Returns:
            La configuración del preset.
        """
        preset = Resolution(resolution)
        settings = dict(PRESET_SETTINGS[preset])
        settings.update(overrides)
        return cls(resolution=preset, **settings)

    @property
    def clip_seconds(self) -> float:
        """Duración del clip generado (segundos)."""
        return self.frames / self.fps

    def with_duration(self, seconds: float) -> GenConfig:
        """Copia con la duración pedida (frames ajustados a ``4k+1``).

        Es lo que usa la generación desde un guion: cada clip dura lo que su
        plano en el montaje (acotado al rango sensato de Wan 2.2), en vez de
        5 s fijos.
        """
        return self.model_copy(
            update={"frames": frames_for_seconds(seconds, self.fps)}
        )

    @property
    def estimated_seconds(self) -> float:
        """Estimación de lo que tarda el clip (según las mediciones del spike)."""
        return estimate_clip_seconds(self)

    def describe(self) -> str:
        """Resumen legible de la configuración (para logs e informes)."""
        resolution = self.resolution.value if self.resolution else f"{self.width}x{self.height}"
        lora = f"LoRA {self.lora_name}@{self.lora_strength:g}" if self.lora_name else "sin LoRA"
        vae = "VAEDecodeTiled" if self.tiled_vae else "VAEDecode"
        return (
            f"{resolution} ({self.width}x{self.height}) · {self.frames} frames @ {self.fps:g} fps "
            f"= {self.clip_seconds:.1f} s · {self.steps} steps · cfg {self.cfg:g} · "
            f"{self.sampler_name}/{self.scheduler} · {vae} · {lora} · "
            f"~{self.estimated_seconds / 60:.1f} min/clip"
        )


def estimate_clip_seconds(config: GenConfig) -> float:
    """Estima cuánto tarda un clip a partir de las anclas medidas.

    El coste escala aproximadamente con ``píxeles × steps × frames`` (el VAE
    troceado incluido), así que se extrapola desde la ancla más cercana de
    :data:`MEASURED_SECONDS`. Es una estimación **gruesa**: solo sirve para
    decidir si otro clip cabe antes del cierre de la ventana nocturna.
    """
    cost = float(config.width * config.height * config.steps * config.frames)
    best: tuple[float, float] | None = None
    for pixels, steps, frames, seconds in MEASURED_SECONDS:
        anchor = float(pixels * steps * frames)
        estimate = seconds * cost / anchor
        distance = abs(cost - anchor) / anchor
        if best is None or distance < best[0]:
            best = (distance, estimate)
    if best is None:  # pragma: no cover - MEASURED_SECONDS nunca está vacío
        return 600.0
    return max(30.0, best[1])


def clip_id(prompt: str, seed: int, *, width: int, steps: int, frames: int) -> str:
    """Identificador **determinista** de un clip.

    Se deriva del prompt, la semilla y lo que cambia la imagen (ancho, steps y
    frames), de forma que volver a encolar el mismo trabajo **no lo duplica**:
    es lo que permite reanudar un lote sin repetir clips ya hechos.
    """
    payload = f"{prompt}|{seed}|{width}|{steps}|{frames}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def frames_for_seconds(
    seconds: float,
    fps: float = DEFAULT_FPS,
    *,
    minimum: int = MIN_FRAMES,
    maximum: int = MAX_FRAMES,
) -> int:
    """Frames que caben en ``seconds`` respetando el paso temporal de Wan 2.2.

    Wan 2.2 comprime el tiempo 4× (la longitud del latente es ``4k+1``), así que
    no vale cualquier cifra: se toma el ``4k+1`` **más cercano** a ``seconds``
    (a lo sumo se falla un par de fotogramas, ~0,08 s) y se acota al rango
    sensato (:data:`MIN_FRAMES` ≈ 2 s, :data:`MAX_FRAMES` ≈ 10 s). Así el clip
    dura lo que dura su plano en el montaje, en vez de 5 s fijos que luego
    había que estirar o repetir.

    Args:
        seconds: Duración objetivo del clip.
        fps: Fotogramas por segundo.
        minimum: Longitud mínima del clip, en frames.
        maximum: Longitud máxima del clip, en frames.

    Returns:
        La longitud en frames (siempre ``4k+1``).
    """
    wanted = int(round(max(seconds, 0.0) * fps))
    lower = wanted - ((wanted - 1) % FRAME_STEP)
    frames = lower + FRAME_STEP if (wanted - lower) > FRAME_STEP / 2 else lower
    frames = max(minimum, min(maximum, frames))
    return frames - ((frames - 1) % FRAME_STEP)


class ClipQuality(BaseModel):
    """Resultado de la verificación de un clip (para no colar basura).

    Attributes:
        duration: Duración medida (segundos).
        width: Ancho del flujo de vídeo.
        height: Alto del flujo de vídeo.
        fps: Fotogramas por segundo medidos.
        frames: Número de fotogramas.
        brightness: Brillo medio de un fotograma (0-255).
        detail: Desviación típica de un fotograma; mide el detalle. Con Turbo a
            4 steps a 720p cae a 9-21 (imagen plana) y con 8 steps sube a ~40.
        motion: Diferencia media entre el 20 % y el 80 % del clip.
        ok: Si el clip pasa los umbrales.
        reasons: Motivos por los que no pasa (vacío si ``ok``).
    """

    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frames: int = 0
    brightness: float | None = None
    detail: float | None = None
    motion: float | None = None
    ok: bool = True
    reasons: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        """Resumen legible de las métricas."""
        parts = [
            f"{self.width}x{self.height}",
            f"{self.frames} frames",
            f"{self.duration:.2f} s",
        ]
        if self.detail is not None:
            parts.append(f"detalle {self.detail:.1f}")
        if self.brightness is not None:
            parts.append(f"brillo {self.brightness:.1f}")
        if self.motion is not None:
            parts.append(f"movimiento {self.motion:.2f}")
        state = "OK" if self.ok else "RECHAZADO"
        return f"{state}: " + " · ".join(parts)


class ClipRequest(BaseModel):
    """Un clip a generar: qué se pide, con qué configuración y cómo acabó.

    El objeto es **autocontenido** (lleva su propio :class:`GenConfig`) para
    que la cola guardada en disco se pueda reanudar tal cual, sin depender de
    los ajustes con los que se lanzó el lote.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = ""
    scene_index: int | None = None
    scene_type: str | None = None
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    seed: int = 0
    duration_hint: float | None = None
    config: GenConfig = Field(default_factory=GenConfig)
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    prompt_id: str | None = None
    output: str | None = None
    seconds: float | None = None
    quality: ClipQuality | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None

    def touch(self) -> None:
        """Marca el trabajo como actualizado ahora mismo."""
        self.updated_at = datetime.now()


class BatchReport(BaseModel):
    """Informe de un lote nocturno: qué se generó, qué costó y cómo salió."""

    id: str
    created_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    config: GenConfig = Field(default_factory=GenConfig)
    window_start: datetime | None = None
    window_end: datetime | None = None
    stopped_reason: str = ""
    clips: list[ClipRequest] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Clips intentados en el lote."""
        return len(self.clips)

    @property
    def done(self) -> list[ClipRequest]:
        """Clips generados y verificados."""
        return [clip for clip in self.clips if clip.status == JobStatus.DONE]

    @property
    def failed(self) -> list[ClipRequest]:
        """Clips que no se pudieron dar por buenos."""
        return [clip for clip in self.clips if clip.status == JobStatus.FAILED]

    @property
    def metrage(self) -> float:
        """Metraje generado (segundos de vídeo) sumando los clips buenos."""
        return sum(clip.config.clip_seconds for clip in self.done)

    @property
    def seconds_total(self) -> float:
        """Tiempo de GPU consumido (segundos)."""
        return sum(clip.seconds or 0.0 for clip in self.clips)

    def to_markdown(self) -> str:
        """Resumen del lote en Markdown (para el diario y los informes)."""
        lines = [
            f"# Lote de generación {self.id}",
            "",
            f"- Config: {self.config.describe()}",
            f"- Inicio: {self.created_at:%Y-%m-%d %H:%M:%S}",
        ]
        if self.finished_at is not None:
            lines.append(f"- Fin: {self.finished_at:%Y-%m-%d %H:%M:%S}")
        if self.window_end is not None:
            lines.append(f"- Cierre de ventana: {self.window_end:%Y-%m-%d %H:%M:%S}")
        lines.append(f"- Parada: {self.stopped_reason or '—'}")
        lines += [
            f"- Clips: {len(self.done)}/{self.total} buenos "
            f"({len(self.failed)} descartados) · {self.metrage:.1f} s de metraje · "
            f"{self.seconds_total / 60:.1f} min de GPU",
            "",
            "| Clip | Escena | Estado | Tiempo | Calidad | Salida |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for clip in self.clips:
            scene = clip.scene_type or (clip.label or "—")
            seconds = f"{clip.seconds / 60:.1f} min" if clip.seconds else "—"
            quality = clip.quality.summary() if clip.quality else (clip.error or "—")
            lines.append(
                f"| {clip.label or clip.id} | {scene} | {clip.status.value} | {seconds} | "
                f"{quality} | {clip.output or '—'} |"
            )
        return "\n".join(lines) + "\n"
