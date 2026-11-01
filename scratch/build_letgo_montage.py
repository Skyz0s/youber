"""Montaje de **If I Let Go**: los 49 clips sobre la cancion.

- Orden y duracion por plano tomados de ``prompts_video.json`` (121 f a 24 fps
  cada uno = 5,041667 s; total 247,041667 s).
- Si el audio es mas corto que el plan (el JSON midio 244,272 s), el recorte se
  **reparte** entre todos los planos en frames enteros: no se machaca el ultimo
  plano ni se desincroniza el final.
- Escalado 1280x720 -> 1920x1080 (16:9 nativo, sin recorte).
- Un solo pase de FFmpeg con filter_complex + concat.

Uso:
    python scratch/build_letgo_montage.py --check
    python scratch/build_letgo_montage.py --preset master --audio "...wav"
    python scratch/build_letgo_montage.py --preset preview
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

PROJECT = Path(r"C:\Users\bypau\Videos\youber\IfILetGo\If_I_Let_Go")
CLIPS = PROJECT / "clips"
STILLS = PROJECT / "stills"
MONTAGE = PROJECT / "montage"
PLAN = PROJECT / "prompts_video.json"

#: Audio esperado: la version **obscure** de la cancion (244,272 s segun el ZIP).
AUDIO_CANDIDATES = [
    PROJECT / "audio" / "If I Let Go (Obscure).wav",
    PROJECT / "audio" / "If I Let Go - Obscure.wav",
    Path(r"C:\Users\bypau\Music\Distrokid\Is it me or is it you\If I let go - Obscure.wav"),
    Path(r"C:\Users\bypau\Music\Distrokid\Is it me or it's you\If I let go - Obscure.wav"),
]

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
FPS = 24
W, H = 1920, 1080
FADE = 1.6


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return float(out) if out else 0.0


def load_plan() -> list[dict]:
    doc = json.loads(PLAN.read_text(encoding="utf-8"))
    items = []
    for shot in sorted(doc["shots"], key=lambda s: s["id"]):
        frames = int(shot.get("frames", 121))
        fps = float(shot.get("fps", FPS)) or FPS
        items.append(
            {
                "id": shot["id"],
                "title": shot.get("title_es", ""),
                "clip": CLIPS / f"clip{shot['id']}_720p.mp4",
                "still": STILLS / Path(shot["image"]).name,
                "frames": frames,
                "fps": fps,
                "seconds": frames / fps,
            }
        )
    return items


def check(items: list[dict]) -> list[str]:
    return [it["id"] for it in items if not it["clip"].exists()]


def fit_frames(items: list[dict], audio_seconds: float) -> list[int]:
    """Reparte ``audio_seconds`` en frames enteros entre todos los planos."""
    plan_frames = [it["frames"] for it in items]
    plan_total = sum(plan_frames)
    if audio_seconds <= 0:
        return plan_frames
    target = int(round(audio_seconds * FPS))
    if target >= plan_total:
        return plan_frames
    base = target // len(items)
    extra = target - base * len(items)
    return [base + (1 if i < extra else 0) for i in range(len(items))]


def build_master(
    items: list[dict],
    out: Path,
    audio: Path,
    *,
    allow_missing: bool,
) -> None:
    missing = check(items)
    if missing and not allow_missing:
        raise SystemExit(f"faltan {len(missing)} clips: {', '.join(missing)}")
    items = [it for it in items if it["clip"].exists()]

    audio_seconds = duration(audio)
    plan_frames = fit_frames(items, audio_seconds)
    plan_seconds = sum(plan_frames) / FPS

    cmd: list[str] = [FFMPEG, "-y", "-v", "error", "-stats"]
    for it in items:
        cmd += ["-i", str(it["clip"])]
    cmd += ["-i", str(audio)]

    parts: list[str] = []
    labels: list[str] = []
    ratios: list[float] = []
    for i, (item, frames) in enumerate(zip(items, plan_frames, strict=True)):
        seconds = frames / FPS
        real = duration(item["clip"])
        ratio = (seconds / real) if real > 0 else 1.0
        ratios.append(ratio)
        setpts = "(PTS-STARTPTS)" if abs(ratio - 1.0) < 0.0005 else f"{ratio:.6f}*(PTS-STARTPTS)"
        parts.append(
            f"[{i}:v]setpts={setpts},fps={FPS},"
            f"scale={W}:{H}:flags=lanczos,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration=1.0,"
            f"trim=duration={seconds:.4f},setpts=PTS-STARTPTS,"
            f"format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(items)}:v=1:a=0[vc]")
    parts.append(
        f"[vc]fade=t=out:st={max(0.0, plan_seconds - FADE):.3f}:d={FADE:.3f}[vout]"
    )
    parts.append(
        f"[{len(items)}:a]atrim=0:{plan_seconds:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=out:st={max(0.0, plan_seconds - FADE):.3f}:d={FADE:.3f},"
        f"aresample=48000[aout]"
    )

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(out),
    ]
    print(
        f"clips {len(items)} | frames {sum(plan_frames)} ({plan_seconds:.3f}s) | "
        f"audio {audio_seconds:.2f}s | recorte {sum(it['frames'] for it in items) / FPS - plan_seconds:.3f}s",
        flush=True,
    )
    print(
        "re-temporizado: "
        + f"{min(ratios):.4f}x .. {max(ratios):.4f}x (todos los planos)",
        flush=True,
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        sys.stderr.write((result.stdout or "")[-2000:] + "\n")
        sys.stderr.write((result.stderr or "")[-4000:] + "\n")
        raise SystemExit(f"ffmpeg fallo rc={result.returncode}")


def build_preview(src: Path, out: Path, height: int, crf: int) -> None:
    cmd = [
        FFMPEG, "-y", "-v", "error", "-stats", "-i", str(src),
        "-vf", f"scale=-2:{height}:flags=lanczos",
        "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        sys.stderr.write((result.stderr or "")[-3000:] + "\n")
        raise SystemExit(f"preview fallo rc={result.returncode}")


def find_audio(explicit: str) -> Path:
    if explicit:
        return Path(explicit)
    for candidate in AUDIO_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "no encuentro el audio de la version obscure.\n"
        "Dejalo en " + str(AUDIO_CANDIDATES[0]) + " o pasa --audio <ruta>."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Solo comprobar clips y plan")
    ap.add_argument("--preset", choices=["master", "preview"], default="master")
    ap.add_argument("--audio", default="", help="Ruta del wav/mp3 (version obscure)")
    ap.add_argument("--src", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--crf", type=int, default=27)
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    items = load_plan()
    missing = check(items)
    ready = len(items) - len(missing)
    total = sum(it["frames"] for it in items) / FPS
    print(f"plan: {len(items)} planos | {total:.3f}s | clips listos: {ready} | faltan: {len(missing)}")
    if missing:
        print("  pendientes: " + ", ".join(missing))
    if args.check:
        return 0 if not missing else 1

    MONTAGE.mkdir(parents=True, exist_ok=True)
    master = PROJECT / "If_I_Let_Go.mp4"
    if args.preset == "master":
        out = Path(args.out) if args.out else master
        audio = find_audio(args.audio)
        if not audio.exists():
            raise SystemExit(f"no encuentro el audio: {audio}")
        print(f"audio: {audio} ({duration(audio):.2f}s)")
        build_master(items, out, audio, allow_missing=args.allow_missing)
    else:
        src = Path(args.src) if args.src else master
        if not src.exists():
            raise SystemExit(f"no hay master del que sacar el preview: {src}")
        out = Path(args.out) if args.out else MONTAGE / f"preview_{args.height}p.mp4"
        build_preview(src, out, args.height, args.crf)

    print(f"\nFINAL: {out}")
    print(f"       {duration(out):.3f}s, {out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
