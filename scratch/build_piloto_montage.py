"""Monta el videoclip del piloto: 17 planos animados sobre 'Wrath', cortes al beat.

- Cortes cada 9 pulsos (~4,70 s) sobre la rejilla medida de la cancion.
- Cortes **por frames exactos**: cada frontera se redondea a un frame y cada
  segmento se corta con `-frames:v n`. Asi el error NO se acumula (deriva 0);
  el desvio de cada corte respecto al pulso queda <= medio frame (~21 ms a 24 fps).
- Los 17 planos rotan en bucle; cada vuelta usa un punto de entrada distinto
  del clip (0 / 3 / 5 / 8 frames) para que la repeticion no cante.
- Cortes secos (sin transiciones): el corte cae en el pulso.
- Salida 1280x704 (nativo de los clips, sin reescalar ni recortar) + cancion AAC.

Uso: python scratch/build_piloto_montage.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.visuals.tempo import detect_grid  # noqa: E402

AUDIO = Path(r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav")
ANIM = Path(r"C:\Users\bypau\Videos\youber\_piloto\anim")
OUT_DIR = Path(r"C:\Users\bypau\Videos\youber\_piloto\out")
SEG_DIR = Path(r"C:\wr\piloto_seg")
FFMPEG = "ffmpeg"
FPS = 24
BEATS_PER_CUT = 9
FIRST_CUT_BEATS = 8

CLIPS = [
    ANIM / "plano02_720p.mp4",
    ANIM / "plano03_720p.mp4",
    ANIM / "plano05_720p.mp4",
    ANIM / "plano07_720p.mp4",
    ANIM / "plano09_720p.mp4",
    ANIM / "plano11_720p.mp4",
    ANIM / "anim01_720p.mp4",
    ANIM / "anim04_720p.mp4",
    ANIM / "anim06_720p.mp4",
    ANIM / "anim08_720p.mp4",
    ANIM / "anim10_720p.mp4",
    ANIM / "anim12_720p.mp4",
    ANIM / "anim13_720p.mp4",
    ANIM / "anim14_720p.mp4",
    ANIM / "anim15_720p.mp4",
    ANIM / "anim16_720p.mp4",
    ANIM / "anim18_720p.mp4",
]
ENTRY_FRAMES = [0, 3, 5, 8]


def probe(path: Path, entries: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout[-2000:])
        print(res.stderr[-4000:])
        raise SystemExit(f"ffmpeg fallo ({res.returncode})")


def main() -> int:
    song = probe(AUDIO, "format=duration")
    grid = asyncio.run(detect_grid(str(AUDIO)))
    slot = BEATS_PER_CUT * grid.interval
    print(f"cancion {song:.3f} s | {grid.bpm:.1f} BPM | corte cada {BEATS_PER_CUT} pulsos = {slot:.4f} s")

    # Fronteras sobre la rejilla: 0 -> 8 pulsos -> multiplos de 9 pulsos -> final
    first = grid.offset + FIRST_CUT_BEATS * grid.interval
    bounds = [0.0, first]
    while bounds[-1] + slot < song - 2.0:
        bounds.append(bounds[-1] + slot)
    if song - bounds[-1] < 2.0 and len(bounds) > 2:
        bounds.pop()
    bounds.append(song)

    # Snap a frames exactos (0, 1, 2, ... N): cada segmento dura un numero entero de frames
    frames = [round(t * FPS) for t in bounds]
    frames = [max(1, frames[i + 1] - frames[i]) for i in range(len(frames) - 1)]

    # Verificacion: desvio de cada corte respecto al pulso mas cercano
    pos = 0
    devs: list[float] = []
    for n in frames[:-1]:
        pos += n
        t = pos / FPS
        beat_n = round((t - grid.offset) / grid.interval)
        devs.append(abs(t - (grid.offset + beat_n * grid.interval)))
    worst = max(devs) * 1000 if devs else 0.0
    print(f"{len(frames)} planos montados ({len(frames) / len(CLIPS):.2f} vueltas al set de {len(CLIPS)})")
    print(f"cortes comprobados: {len(devs)} | peor desvio del pulso: {worst:.1f} ms (medio frame = {1000 / FPS / 2:.1f} ms)")

    SEG_DIR.mkdir(parents=True, exist_ok=True)
    listfile = SEG_DIR / "list.txt"
    lines: list[str] = []
    for index, n in enumerate(frames):
        clip = CLIPS[index % len(CLIPS)]
        lap = index // len(CLIPS)
        entry = ENTRY_FRAMES[lap % len(ENTRY_FRAMES)] / FPS
        seg = SEG_DIR / f"seg{index:03d}.mp4"
        if not seg.exists():
            run([
                FFMPEG, "-y", "-v", "error", "-i", str(clip),
                "-ss", f"{entry:.6f}", "-frames:v", str(n), "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
                str(seg),
            ])
        lines.append(f"file '{seg.as_posix()}'")
        print(f"  {index:02d} {clip.name:20s} frames={n:3d} dur={n / FPS:6.3f} entrada={entry:.3f}")

    listfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "Wrath-piloto-17planos.mp4"
    run([
        FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-i", str(AUDIO),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", "-shortest", str(out),
    ])
    total_frames = sum(frames)
    meta = {
        "planos": len(frames),
        "set_distinto": len(CLIPS),
        "cancion_s": round(song, 3),
        "bpm": round(grid.bpm, 2),
        "corte_pulsos": BEATS_PER_CUT,
        "frames_video": total_frames,
        "duracion_video_s": round(total_frames / FPS, 3),
        "peor_desvio_pulso_ms": round(worst, 1),
        "salida": str(out),
        "bytes": out.stat().st_size,
    }
    (OUT_DIR / "Wrath-piloto-17planos.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
