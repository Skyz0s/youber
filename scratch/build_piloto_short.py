"""Corto vertical (9:16) del piloto: el estribillo medido por energia.

Corta desde el master (cortes ya alineados al pulso) empezando en una frontera
de plano, y compone 1080x1920: fondo desenfocado + video centrado 1080x594.

Uso: python scratch/build_piloto_short.py [segundos]
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.visuals.short import best_window_start, loudness_profile  # noqa: E402
from youber.visuals.tempo import detect_grid  # noqa: E402

MASTER = Path(r"C:\Users\bypau\Videos\youber\_piloto\out\Wrath-piloto-17planos.mp4")
OUT_DIR = Path(r"C:\Users\bypau\Videos\youber\_piloto\out")
FPS = 24
BEATS_PER_CUT = 9
FIRST_CUT_BEATS = 8


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    song_len = 264.72
    grid = asyncio.run(detect_grid(r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav"))

    energies = asyncio.run(loudness_profile(r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav"))
    ideal = best_window_start(energies, duration)
    # energia media del tramo elegido vs la media de la cancion (para saber si es el estribillo)
    span = int(round(duration))
    chosen = sum(energies[int(ideal):int(ideal) + span]) / span
    average = sum(energies) / len(energies)

    # fronteras de plano del master (en segundos, snapped a frame)
    slot = BEATS_PER_CUT * grid.interval
    bounds = [0.0, grid.offset + FIRST_CUT_BEATS * grid.interval]
    while bounds[-1] + slot < song_len - 2.0:
        bounds.append(bounds[-1] + slot)
    b = [round(t * FPS) / FPS for t in bounds]

    start = max((t for t in b if t <= ideal), default=0.0)
    end = min(start + duration, song_len)
    n_cuts = sum(1 for t in b if start < t < end)
    print(f"inicio ideal {ideal:.2f}s -> frontera de plano {start:.3f}s | +{duration:.1f}s = {end:.3f}s")
    print(f"cortes dentro: {n_cuts} | energia del tramo {chosen:.0f} vs media {average:.0f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "Wrath-piloto-short-vertical.mp4"
    fade_out_start = max(0.0, (end - start) - 1.5)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(MASTER),
        "-filter_complex",
        "[0:v]scale=1080:-2[fg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=30:2,eq=brightness=-0.15[bg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[v]",
        "-map", "[v]", "-map", "0:a",
        "-af", f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start:.2f}:d=1.5",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-3000:])
        return 1

    meta = {
        "inicio_s": round(start, 3),
        "duracion_s": round(end - start, 3),
        "cortes_dentro": n_cuts,
        "energia_tramo": round(chosen, 1),
        "energia_media_cancion": round(average, 1),
        "viz": "9:16 1080x1920 (fondo desenfocado + video centrado)",
        "salida": str(out),
        "bytes": out.stat().st_size,
    }
    (OUT_DIR / "Wrath-piloto-short-vertical.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
