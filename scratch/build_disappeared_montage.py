"""Montaje de **Before I Disappeared**: los 39 clips sobre la canción.

- Orden y duración por plano tomados del JSON editorial (``start/end_seconds``).
- Escalado 1280x720 -> 1920x1080 (16:9 nativo, sin recorte).
- Audio: la canción, recortada a la duración del plan (el plan suma 309,96 s;
  el máster de Pimennys dura 362,64 s) con fundido de salida.
- Un solo pase de FFmpeg con filter_complex + concat.

Uso:
    python scratch/build_disappeared_montage.py --check
    python scratch/build_disappeared_montage.py --preset master
    python scratch/build_disappeared_montage.py --preset preview
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(r"C:\Users\bypau\Videos\youber\BeforeIDisappeared")
CLIPS = PROJECT / "clips"
MONTAGE = PROJECT / "montage"
PLAN = PROJECT / "stills" / "Before_I_Disappeared_instrucciones.json"

#: Máster de la canción. El JSON la llama «Before I desapeared.wav» (309,96 s);
#: el único wav con ese nombre en el equipo es el de Pimennys (362,64 s), así
#: que el montaje recorta al plan. Si aparece otra mezcla, se pasa con --audio.
AUDIO = Path(r"C:\Users\bypau\Music\Pimennys\Before Disappearing.wav")

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
    for shot in sorted(doc["shots"], key=lambda s: float(s["start_seconds"])):
        items.append(
            {
                "id": shot["id"],
                "title": shot.get("title_es", ""),
                "clip": CLIPS / f"clip{shot['id']}_720p.mp4",
                "seconds": float(shot["edit_duration_seconds"]),
            }
        )
    return items


def check(items: list[dict]) -> list[str]:
    missing = [it["id"] for it in items if not it["clip"].exists()]
    return missing


def build_master(items: list[dict], out: Path, audio: Path, *, allow_missing: bool) -> None:
    missing = check(items)
    if missing and not allow_missing:
        raise SystemExit(f"faltan {len(missing)} clips: {', '.join(missing)}")
    items = [it for it in items if it["clip"].exists()]

    plan_seconds = sum(it["seconds"] for it in items)
    frames = [round(it["seconds"] * FPS) for it in items]
    total = sum(frames)

    cmd: list[str] = [FFMPEG, "-y", "-v", "error", "-stats"]
    for it in items:
        cmd += ["-i", str(it["clip"])]
    cmd += ["-i", str(audio)]

    parts: list[str] = []
    labels: list[str] = []
    for i, (item, count) in enumerate(zip(items, frames, strict=True)):
        parts.append(
            f"[{i}:v]trim=start_frame=0:end_frame={count},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS},format=yuv420p[v{i}]"
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
        f"clips {len(items)} | frames {total} ({total / FPS:.3f}s) | "
        f"plan {plan_seconds:.2f}s | audio {duration(audio):.2f}s",
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Solo comprobar clips y plan")
    ap.add_argument("--preset", choices=["master", "preview"], default="master")
    ap.add_argument("--audio", default=str(AUDIO))
    ap.add_argument("--src", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--crf", type=int, default=27)
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    items = load_plan()
    missing = check(items)
    ready = len(items) - len(missing)
    print(f"plan: {len(items)} planos | clips listos: {ready} | faltan: {len(missing)}")
    if missing:
        print("  pendientes: " + ", ".join(missing))
    if args.check:
        return 0 if not missing else 1

    MONTAGE.mkdir(parents=True, exist_ok=True)
    master = PROJECT / "Before_I_Disappeared.mp4"
    if args.preset == "master":
        out = Path(args.out) if args.out else master
        audio = Path(args.audio)
        if not audio.exists():
            raise SystemExit(f"no encuentro el audio: {audio}")
        build_master(items, out, audio, allow_missing=args.allow_missing)
    else:
        src = Path(args.src) if args.src else master
        if not src.exists():
            raise SystemExit(f"no hay máster del que sacar el preview: {src}")
        out = Path(args.out) if args.out else MONTAGE / f"preview_{args.height}p.mp4"
        build_preview(src, out, args.height, args.crf)

    print(f"\nFINAL: {out}")
    print(f"       {duration(out):.3f}s, {out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
