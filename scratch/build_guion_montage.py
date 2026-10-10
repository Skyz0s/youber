"""Monta un videoclip desde un guion en carpeta (fotos + instrucciones.json v2).

- Coloca cada plano en su TRAMO real (secciones medidas del audio).
- Cortes en la rejilla de compases (cada plano dura un numero entero de compases).
- Los planos se recortan a su hueco (si el hueco es mas corto) o se estiran un
  poco (si es mas largo), para que cada corte caiga en el tiempo.
- Cierra con la portada (zoom lento + fundido a negro), que absorbe el resto.

Uso:
    python scratch/build_guion_montage.py --folder <dir> --cover <png> [--plan-only]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.visuals.tempo import detect_grid  # noqa: E402

AUDIO = Path(r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav")
FPS = 24
SONG = 264.72
VOICE_END = 211.26
MIN_BARS, MAX_BARS = 2, 4

FRAME_W, FRAME_H = 1280, 704
#: La portada ocupa como mucho esta fraccion del alto (deja margen arriba y
#: abajo para que una portada cuadrada no parezca estirada a lo alto).
COVER_SCALE = 0.85

#: Tramo del audio (nombre, inicio, fin). El interludio va con el verso 2.
REGIONS: list[tuple[str, float, float]] = [
    ("intro", 0.00, 46.86),
    ("verse1", 46.86, 82.40),
    ("verse2", 82.40, 106.45),
    ("pre_chorus", 106.45, 124.22),
    ("chorus1", 124.22, 137.28),
    ("verse3", 137.28, 158.71),
    ("bridge", 158.71, 177.00),
    ("chorus2", 177.00, 194.25),
    ("outro", 194.25, 264.72),
]

#: Etiqueta del guion -> tramo del audio.
LABEL_MAP = {
    "Instrumental Intro": "intro", "Intro": "intro", "Verse 1": "verse1",
    "Verse 2": "verse2", "Pre-Chorus": "pre_chorus", "Chorus": "chorus1",
    "Verse 3": "verse3", "Bridge": "bridge", "Final Chorus": "chorus2",
    "Outro": "outro",
}


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout[-1200:], res.stderr[-2500:])
        raise SystemExit(f"ffmpeg fallo ({res.returncode})")


def seg_frames(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return int(out.stdout.strip() or 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--cover", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()

    folder = Path(a.folder)
    clips_dir = folder / "_clips"
    out = Path(a.out) if a.out else folder / f"{folder.name}-videoclip.mp4"
    work = folder / "_montage"
    work.mkdir(parents=True, exist_ok=True)

    doc = None
    for cand in sorted(folder.glob("*.json")):
        data = json.loads(cand.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("shots"):
            doc = data
            break
    if doc is None:
        raise SystemExit("no encuentro JSON con 'shots'")
    shots = doc["shots"]

    grid = asyncio.run(detect_grid(str(AUDIO)))
    bar = 4 * grid.interval
    total_frames = round(SONG * FPS)

    # agrupar planos por tramo (en orden)
    by_region: dict[str, list[dict]] = {name: [] for name, _, _ in REGIONS}
    for shot in shots:
        region = LABEL_MAP.get(shot.get("section", ""), None)
        if region is None:
            continue
        by_region[region].append(shot)

    bounds = [0.0]
    plan: list[tuple[str, str, int, float, float]] = []  # (region, shot_id, bars, t0, t1)
    bars_acc = 0
    for name, start, end in REGIONS:
        group = by_region[name]
        if not group:
            continue
        sb = max(MIN_BARS, min(MAX_BARS, round((end - start) / bar / len(group))))
        for shot in group:
            t0 = bounds[-1]
            bars_acc += sb
            t1 = grid.offset + bars_acc * bar
            bounds.append(t1)
            plan.append((name, shot["id"], sb, t0, t1))

    used = sum(round((bounds[i + 1] - bounds[i]) * FPS) for i in range(len(bounds) - 1))
    cover_frames = total_frames - used
    print(f"BPM {grid.bpm:.1f} | compas {bar:.3f}s | total {total_frames} frames | "
          f"planos {len(plan)} | planos={used}f ({used / FPS:.1f}s) | portada={cover_frames}f "
          f"({cover_frames / FPS:.1f}s)")
    for region, sid, sb, t0, t1 in plan:
        print(f"  {sid} {region:10s} {sb} comp {t0:7.2f}-{t1:7.2f}s")

    if a.plan_only:
        return 0

    SEG = work
    parts: list[Path] = []
    for i, (region, sid, sb, t0, t1) in enumerate(plan):
        frames = round((t1 - t0) * FPS)
        src = clips_dir / f"clip{sid}_720p.mp4"
        if not src.exists():
            raise SystemExit(f"falta el clip {src}")
        seg = SEG / f"seg{i:02d}.mp4"
        if not seg.exists() or seg.stat().st_size == 0:
            if frames <= 193:
                vf = f"fps={FPS}"  # recortar (sin ralentizar)
            else:
                vf = f"setpts={frames / 193:.6f}*PTS,fps={FPS}"
            run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf,
                 "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), str(seg)])
        parts.append(seg)
        print(f"  {i:02d} {sid} {region} {frames}f")

    card = SEG / "card.png"
    if not card.exists():
        # Portada SIN deformar: el fondo es la misma portada recortada a 16:9 y
        # desenfocada (nunca estirada), y la portada entera va encima, con
        # margen arriba/abajo (no pegada a los bordes).
        side = int(FRAME_H * COVER_SCALE)
        run(["ffmpeg", "-y", "-v", "error", "-i", a.cover, "-i", a.cover, "-filter_complex",
             f"[1:v]scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
             f"crop={FRAME_W}:{FRAME_H},gblur=sigma=36,eq=brightness=-0.22[bg];"
             f"[0:v]scale={side}:{side}:force_original_aspect_ratio=decrease[fg];"
             "[bg][fg]overlay=(W-w)/2:(H-h)/2", "-frames:v", "1", str(card)])
    used = sum(seg_frames(p) for p in parts)
    cover_frames = total_frames - used
    cover_seg = SEG / "seg_cover.mp4"
    cover_seg.unlink(missing_ok=True)
    fade_st = max(0.0, cover_frames / FPS - 2.5)
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(card), "-vf",
         (f"scale=2560:1408,zoompan=z='min(1+0.08*on/{cover_frames},1.08)'"
          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x704,"
          f"fps={FPS},fade=t=out:st={fade_st:.3f}:d=2.5"),
         "-frames:v", str(cover_frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), str(cover_seg)])
    parts.append(cover_seg)

    list_file = SEG / "concat.txt"
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts) + "\n", encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-i", str(AUDIO), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "256k", "-movflags", "+faststart", "-shortest", str(out)])
    print(f"VIDEO={out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
