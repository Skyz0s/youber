"""Módulo ``youber.genvideo``: generación de vídeo local con verificación.

Local-first por diseño: el backend de referencia es **ComfyUI** en la propia
máquina (Wan 2.2 TI2V-5B con la receta medida en el spike), con los backends
externos como opción explícita y apagada por defecto.

Piezas:

- :class:`~youber.genvideo.models.GenConfig` — la receta (presets ``720p``/``480p``).
- :class:`~youber.genvideo.client.ComfyUIClient` — backend local por API HTTP.
- :class:`~youber.genvideo.client.StubClient` — backend de pruebas (sin GPU).
- :class:`~youber.genvideo.queue.JobQueue` — cola persistida y reanudable.
- :class:`~youber.genvideo.verify` — verificación de cada clip (nada de planos).
- :class:`~youber.genvideo.runner.NightlyRunner` — el lote nocturno completo.
"""

from youber.genvideo.client import ComfyOutput, ComfyUIClient, ComfyUIError, StubClient
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
    requests_from_shot_plan,
    resolve_window,
    run_nightly,
    write_report,
)
from youber.genvideo.verify import judge_quality, verify_clip

__all__ = [
    "BatchReport",
    "ClipQuality",
    "ClipRequest",
    "ComfyUIClient",
    "ComfyUIError",
    "ComfyOutput",
    "GenConfig",
    "JobQueue",
    "JobStatus",
    "NightlyRunner",
    "Resolution",
    "StubClient",
    "clip_id",
    "estimate_clip_seconds",
    "judge_quality",
    "requests_from_prompts",
    "requests_from_script",
    "requests_from_shot_plan",
    "resolve_window",
    "run_nightly",
    "verify_clip",
    "write_report",
]
