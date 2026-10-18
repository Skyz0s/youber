"""Metricas de locomocion para clips generados con I2V.

El verificador clasico (`verify.py`) mira detalle, brillo y movimiento medio.
Con eso un plano "caminando en el sitio" pasa perfectamente: hay movimiento,
hay detalle, hay brillo. Lo que no hay es **desplazamiento**.

Aqui se mide lo que de verdad delata la locomocion, sin dependencias nuevas:

- **fondo**: correlacion de fase entre frames consecutivos sobre una banda
  superior (paredes/techo). Un travelling mueve el fondo; una camara fija no.
- **sujeto**: mascara de diferencia contra el primer frame -> caja y centroide.
  Si se aleja, el area baja; si cruza el encuadre, el centroide se desplaza en x;
  si se acerca, el area sube.

`measure()` devuelve un `LocomotionReport` y `judge()` lo compara con el modo
esperado del plano: ``away``, ``toward``, ``lateral``, ``tracking`` o ``static``.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: Ancho/alto de trabajo: suficiente para medir, barato de decodificar.
WORK_W, WORK_H = 320, 176
#: Umbral de diferencia (0-255) para considerar que un pixel cambio.
DIFF_THRESHOLD = 18.0
#: Fraccion de la altura que se considera "fondo" (banda superior).
BG_BAND = 0.35
#: Cada cuantos frames se muestrea.
SAMPLE_STEP = 4

#: Umbrales de veredicto, en fraccion del ancho/alto del frame.
MIN_BG_SHIFT = 0.04
MIN_SUBJECT_SHIFT = 0.05
MIN_AREA_CHANGE = 0.10


@dataclass
class LocomotionReport:
    """Medidas de un clip y veredicto frente al modo esperado."""

    mode: str
    frames: int
    fps: float
    bg_dx: float
    bg_dy: float
    subject_dx: float
    subject_dy: float
    area_ratio: float
    motion: float
    score: float
    ok: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.frames / self.fps if self.fps else 0.0

    def summary(self) -> str:
        return (
            f"{self.mode}: bg=({self.bg_dx:+.1f},{self.bg_dy:+.1f})px "
            f"sujeto=({self.subject_dx:+.1f},{self.subject_dy:+.1f})px "
            f"area={self.area_ratio:.2f} score={self.score:.2f} "
            f"{'OK' if self.ok else 'RECHAZADO'}"
        )


def load_frames(path: Path, fps: float = 24.0) -> np.ndarray:
    """Decodifica el clip a gris 320x176 en float32 (n, h, w)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={fps},scale={WORK_W}:{WORK_H},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True,
    ).stdout
    n = len(raw) // (WORK_W * WORK_H)
    if n == 0:
        raise RuntimeError(f"no pude decodificar frames de {path}")
    return np.frombuffer(raw[: n * WORK_W * WORK_H], dtype=np.uint8).reshape(
        n, WORK_H, WORK_W
    ).astype(np.float32)


def phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Desplazamiento (dx, dy) dominante entre dos imagenes (correlacion de fase)."""
    a = a - a.mean()
    b = b - b.mean()
    cross = np.fft.rfft2(b) * np.conj(np.fft.rfft2(a))
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape)
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    dx = float(px if px <= a.shape[1] // 2 else px - a.shape[1])
    dy = float(py if py <= a.shape[0] // 2 else py - a.shape[0])
    return dx, dy


def _bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) < 30:
        return None
    return float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())


def measure(path: Path, mode: str = "walk", fps: float = 24.0) -> LocomotionReport:
    """Mide el clip y lo juzga contra el modo de locomocion esperado."""
    frames = load_frames(path, fps)
    n, h, w = frames.shape

    band_h = max(8, int(h * BG_BAND))
    bg_dx = bg_dy = 0.0
    for i in range(0, n - 1, SAMPLE_STEP):
        dx, dy = phase_shift(frames[i, :band_h], frames[i + 1, :band_h])
        bg_dx += dx
        bg_dy += dy

    ref = frames[0]
    boxes = []
    for i in range(SAMPLE_STEP, n, SAMPLE_STEP):
        box = _bbox(np.abs(frames[i] - ref) > DIFF_THRESHOLD)
        if box is not None:
            boxes.append(box)

    subject_dx = subject_dy = 0.0
    area_ratio = 1.0
    if len(boxes) >= 2:
        first, last = boxes[0], boxes[-1]
        cx = [(b[0] + b[1]) / 2 for b in boxes]
        cy = [(b[2] + b[3]) / 2 for b in boxes]
        subject_dx = float(max(cx) - min(cx))
        subject_dy = float(max(cy) - min(cy))
        area_first = max(1.0, (first[1] - first[0]) * (first[3] - first[2]))
        area_last = max(1.0, (last[1] - last[0]) * (last[3] - last[2]))
        area_ratio = float(area_last / area_first)

    motion = float(np.abs(np.diff(frames[::2], axis=0)).mean())

    return judge(
        LocomotionReport(
            mode=mode,
            frames=n,
            fps=fps,
            bg_dx=bg_dx,
            bg_dy=bg_dy,
            subject_dx=subject_dx,
            subject_dy=subject_dy,
            area_ratio=area_ratio,
            motion=motion,
            score=0.0,
            ok=True,
        ),
        width=w,
        height=h,
    )


def judge(report: LocomotionReport, *, width: int = WORK_W, height: int = WORK_H) -> LocomotionReport:
    """Rellena ``score``/``ok``/``reasons`` segun el modo esperado."""
    mode = report.mode
    reasons: list[str] = []
    score = 0.0

    bg_norm = max(abs(report.bg_dx), abs(report.bg_dy)) / width
    subj_norm = max(report.subject_dx, report.subject_dy) / width
    area_delta = abs(1.0 - report.area_ratio)

    if mode == "tracking":
        score = min(1.0, bg_norm / MIN_BG_SHIFT)
        if bg_norm < MIN_BG_SHIFT:
            reasons.append(
                f"travelling sin parallax: el fondo solo se mueve {report.bg_dx:+.1f}px"
            )
    elif mode == "lateral":
        score = min(1.0, max(subj_norm, bg_norm) / MIN_SUBJECT_SHIFT)
        if subj_norm < MIN_SUBJECT_SHIFT and bg_norm < MIN_BG_SHIFT:
            reasons.append(
                f"no cruza el encuadre: sujeto {report.subject_dx:.1f}px, fondo {report.bg_dx:+.1f}px"
            )
    elif mode == "away":
        shrink = 1.0 - report.area_ratio
        score = min(1.0, max(shrink, subj_norm) / MIN_AREA_CHANGE)
        if shrink < MIN_AREA_CHANGE and subj_norm < MIN_SUBJECT_SHIFT:
            reasons.append(
                f"no se aleja: area x{report.area_ratio:.2f}, desplazamiento {report.subject_dy:.1f}px"
            )
    elif mode == "toward":
        grow = report.area_ratio - 1.0
        score = min(1.0, max(grow, subj_norm) / MIN_AREA_CHANGE)
        if grow < MIN_AREA_CHANGE and subj_norm < MIN_SUBJECT_SHIFT:
            reasons.append(
                f"no se acerca: area x{report.area_ratio:.2f}, desplazamiento {report.subject_dy:.1f}px"
            )
    else:  # static / walk generico
        score = 1.0 if mode == "static" else min(
            1.0, max(subj_norm, bg_norm, area_delta) / MIN_SUBJECT_SHIFT
        )
        if mode != "static" and score < 1.0:
            reasons.append("sin senal de locomocion")

    report.score = round(score, 3)
    report.ok = not reasons
    report.reasons = reasons
    return report
