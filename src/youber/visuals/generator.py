"""Generadores de imagen para los planos del vídeo.

Dos implementaciones intercambiables tras la misma interfaz:

- :class:`DiffusersGenerator`: modelo local (SDXL-Turbo por defecto) en la
  GPU, vía ``diffusers``. Importa torch **en diferido**: el framework sigue
  funcionando (y testeándose) sin GPU ni 2,5 GB de dependencias.
- :class:`StubGenerator`: PNG deterministas sin dependencias. Sirve para
  tests, CI y para montar el flujo completo sin GPU.

La imagen generada se devuelve como **bytes PNG**, no como ruta: quién la
escribe en disco decide el plan (:mod:`youber.visuals.render`).
"""

from __future__ import annotations

import hashlib
import importlib.util
import struct
import zlib
from typing import Any, Protocol, runtime_checkable

from loguru import logger

#: Modelo por defecto: SDXL-Turbo (1024px, 1-4 pasos, gratis y local).
DEFAULT_MODEL = "stabilityai/sdxl-turbo"

#: Valores que activan el generador de prueba (sin modelo, sin GPU).
STUB_ALIASES = frozenset({"stub", "none", "fake", ""})


@runtime_checkable
class ImageGenerator(Protocol):
    """Interfaz mínima de un generador de imágenes (texto → bytes PNG)."""

    name: str

    def generate(self, prompt: str, *, width: int, height: int, seed: int) -> bytes:
        """Genera una imagen y la devuelve como bytes PNG."""
        ...


def _png(width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    """PNG RGB con degradado vertical (escritor mínimo, sin dependencias)."""
    rows = bytearray()
    for y in range(height):
        t = y / max(1, height - 1)
        pixel = bytes(
            round(top[channel] + (bottom[channel] - top[channel]) * t) for channel in range(3)
        )
        rows += b"\x00" + pixel * width

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


class StubGenerator:
    """Generador determinista sin GPU: un degradado derivado del prompt.

    Mismo prompt + misma semilla ⇒ mismos bytes. Suficiente para validar el
    pipeline (plan → imágenes → clips → montaje) en tests y CI.
    """

    name = "stub"

    def generate(self, prompt: str, *, width: int, height: int, seed: int) -> bytes:
        """Devuelve un PNG con un degradado reproducible desde ``prompt``/``seed``."""
        digest = hashlib.sha256(f"{prompt}|{seed}".encode()).digest()
        top = (digest[0], digest[1], digest[2])
        bottom = (digest[3] // 2, digest[4] // 2, digest[5] // 2)
        return _png(width, height, top, bottom)


class DiffusersGenerator:
    """Generador local con ``diffusers`` (SDXL-Turbo por defecto).

    El modelo se carga la primera vez que se genera algo (``_load``), no al
    construir el objeto: así el CLI puede planificar sin tocar la GPU.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        steps: int = 2,
        guidance: float = 0.0,
        device: str = "cuda",
        torch_dtype: str = "float16",
        offload: bool = True,
    ) -> None:
        """Configura el generador (sin cargar el modelo todavía).

        Args:
            model: Identificador del modelo (p. ej. ``stabilityai/sdxl-turbo``).
            steps: Pasos de inferencia (los modelos *turbo* funcionan con 1-4).
            guidance: *Guidance scale*; 0.0 es lo correcto en los turbo.
            device: Dispositivo de torch (``cuda`` o ``cpu``).
            torch_dtype: Precisión (``float16`` en GPU, ``float32`` en CPU).
            offload: Mover los módulos a la GPU solo cuando toca
                (``enable_model_cpu_offload``). En tarjetas de 8 GB es la
                diferencia entre generar en segundos o paginar VRAM a disco
                durante minutos; con mucha VRAM libre se puede desactivar
                para ir algo más rápido por imagen.
        """
        self.model = model
        self.steps = steps
        self.guidance = guidance
        self.device = device
        self.torch_dtype = torch_dtype
        self.offload = offload
        self.name = model
        self._pipe: Any = None

    def _load(self) -> Any:
        """Carga el pipeline en memoria (primera llamada) y lo deja listo."""
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import AutoPipelineForText2Image

        dtype = getattr(torch, self.torch_dtype)
        kwargs: dict[str, Any] = {"torch_dtype": dtype}
        if "xl" in self.model.lower():
            kwargs["variant"] = "fp16"
            kwargs["use_safetensors"] = True
        pipe = AutoPipelineForText2Image.from_pretrained(self.model, **kwargs)
        if self.offload and self.device.startswith("cuda"):
            # Los módulos viven en RAM y van a la GPU por turnos: la VRAM nunca
            # se llena (crítico en 8 GB con el escritorio compartiendo GPU).
            pipe.enable_model_cpu_offload()
        else:
            pipe = pipe.to(self.device)
        # Trocear atención y VAE baja el pico de memoria en cada paso.
        for method in ("enable_attention_slicing", "enable_vae_slicing"):
            enable = getattr(pipe, method, None)
            if enable is not None:
                try:
                    enable()
                except Exception:  # pragma: no cover - depende del pipeline
                    logger.debug(f"No se pudo activar {method} en el pipeline")
        pipe.set_progress_bar_config(disable=True)
        self._pipe = pipe
        return pipe

    def generate(self, prompt: str, *, width: int, height: int, seed: int) -> bytes:
        """Genera un plano y lo devuelve como bytes PNG."""
        import io

        pipe = self._load()
        import torch

        generator = torch.Generator(device=self.device).manual_seed(seed)
        result = pipe(
            prompt=prompt,
            num_inference_steps=self.steps,
            guidance_scale=self.guidance,
            width=width,
            height=height,
            generator=generator,
        )
        buffer = io.BytesIO()
        result.images[0].save(buffer, format="PNG")
        return buffer.getvalue()


def diffusers_available() -> bool:
    """``True`` si ``torch`` y ``diffusers`` están instalados."""
    return all(
        importlib.util.find_spec(module) is not None for module in ("torch", "diffusers")
    )


def create_generator(
    model: str | None = None,
    *,
    steps: int = 2,
    guidance: float = 0.0,
    device: str = "cuda",
    offload: bool = True,
) -> ImageGenerator:
    """Crea el generador adecuado: local (diffusers) o de prueba (stub).

    Args:
        model: Modelo a usar. ``None`` o un alias de :data:`STUB_ALIASES`
            devuelven el :class:`StubGenerator` (sin GPU, sin descargas).
        steps: Pasos de inferencia para el modelo local.
        guidance: *Guidance scale* para el modelo local.
        device: Dispositivo de torch para el modelo local.
        offload: Mover los módulos del modelo a la GPU por turnos (recomendado
            en tarjetas de 8 GB).

    Raises:
        RuntimeError: si se pide un modelo real sin ``torch``/``diffusers``.
    """
    if model is None or model.strip().lower() in STUB_ALIASES:
        return StubGenerator()
    if not diffusers_available():
        raise RuntimeError(
            "Para generar planos con IA local hacen falta torch y diffusers:\n"
            "  pip install youber[visuals]"
        )
    return DiffusersGenerator(
        model, steps=steps, guidance=guidance, device=device, offload=offload
    )
