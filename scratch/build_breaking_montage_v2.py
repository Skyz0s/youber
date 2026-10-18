"""Montaje v2 de 'Everything is breaking down' — 69 planos de ~4 s.

Lee `_v2/plan.json` (duraciones por plano) y los clips de `_v2/clips/`.

- Rejilla musical: 117,6 bpm -> 8 beats = 4,08 s; los planos son de 4,04 s.
- Los dos planos que fallaron la metrica de locomocion (029a y 034a) se
  recortan a 2,0 s para que el "caminar en el sitio" no tenga tiempo de
  delatarse; los frames que sobran pasan al plano derivado siguiente para
  que el total siga cuadrando con la cancion.
- `deflicker` (1,25 s) + fundido a negro de 1,2 s al final.

Uso:
    python scratch/build_breaking_montage_v2.py --dry-run
    python scratch/build_breaking_montage_v2.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(
    r"C:\Users\bypau\Music\Gpt\Everything_breaking_down_COMPLETO\Everything_breaking_down"
)
V2 = SRC / "_v2"
CLIPS = V2 / "clips"
WORK = V2 / "_montaje"
SEG = WORK / "seg"
PLAN = V2 / "plan.json"
AUDIO = Path(r"C:\Users\bypau\Music\Distrokid\It's all for you\Everything is breaking down.wav")
OUT = SRC / "Everything_is_breaking_down_v2.mp4"

WIDTH, HEIGHT, PAD_Y, FPS = 1920, 1080, 12, 24
END_FADE = 1.2

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-1500:] + "\n" + p.stderr[-3000:] + "\n")
        raise RuntimeError(f"fallo: {' '.join(cmd[:8])}... rc={p.returncode}")


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def build_plan() -> tuple[list[dict], dict]:
    doc = json.loads(PLAN.read_text(encoding="utf-8"))
    shots = doc["shots"]
    plan = []
    for s in shots:
        clip = CLIPS / f"clip{s['id']}.mp4"
        plan.append({
            "id": s["id"],
            "frames": s["frames"],
            "duration": s["frames"] / FPS,
            "clip": str(clip),
            "exists": clip.exists(),
            "mode": s["mode"],
            "title": s["title"],
        })
    return plan, doc


def check(plan: list[dict], song: float) -> tuple[float, list[str]]:
    problems = [f"falta {p['id']}" for p in plan if not p["exists"]]
    total = sum(p["duration"] for p in plan)
    if abs(total - song) > 0.05:
        problems.append(f"el plan suma {total:.3f}s y la cancion {song:.3f}s")
    for p in plan:
        if not p["exists"]:
            continue
        have = duration(Path(p["clip"]))
        if have + 1e-3 < p["duration"]:
            if have >= p["duration"] * 0.95:
                # un pelo corto: se estira con setpts en vez de rechazar
                p["slowdown"] = p["duration"] / have
            else:
                problems.append(f"{p['id']}: clip {have:.3f}s < {p['duration']:.3f}s")
    return total, problems


def render(plan: list[dict], deflicker: int) -> list[Path]:
    SEG.mkdir(parents=True, exist_ok=True)
    pre = f"deflicker=size={deflicker}:mode=am," if deflicker else ""
    vf = (f"{pre}scale={WIDTH}:1056:flags=lanczos,setsar=1,fps={FPS},"
          f"pad={WIDTH}:{HEIGHT}:0:{PAD_Y}:color=black")
    segs = []
    for i, p in enumerate(plan):
        out = SEG / f"seg{p['id']}.mp4"
        last = i == len(plan) - 1
        v = vf
        if last:
            st = max(0.0, p["duration"] - END_FADE)
            v = f"{vf},fade=t=out:st={st:.3f}:d={END_FADE:.3f}"
        slow = p.get("slowdown")
        pts = f"setpts=PTS*{slow:.4f}" if slow else "setpts=PTS-STARTPTS"
        pre_trim = "" if slow else f"trim=start=0:end={p['duration']:.6f},"
        run([FFMPEG, "-y", "-v", "error", "-i", p["clip"],
             "-filter_complex",
             f"[0:v]{pre_trim}{pts},{v}[v]",
             "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
        print(f"  {p['id']}  {p['duration']:5.3f}s  {p['title'][:40]}", flush=True)
        segs.append(out)
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--deflicker", type=int, default=30)
    a = ap.parse_args()

    plan, doc = build_plan()
    song = duration(AUDIO)
    total, problems = check(plan, song)
    print(f"plan: {len(plan)} planos | {total:.3f}s | cancion {song:.3f}s")
    if problems:
        for p in problems:
            print("  -", p)
        if a.dry_run:
            return 1
        print("abortado")
        return 1
    if a.dry_run:
        print("dry-run OK")
        return 0

    if WORK.exists():
        shutil.rmtree(WORK)
    SEG.mkdir(parents=True, exist_ok=True)

    print("\n1/3 cortando y normalizando...")
    segs = render(plan, a.deflicker)

    print("\n2/3 uniendo...")
    lst = WORK / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in segs) + "\n", encoding="utf-8")
    silent = WORK / "_silent.mp4"
    run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(silent)])

    print("3/3 montando la cancion...")
    run([FFMPEG, "-y", "-v", "error", "-i", str(silent), "-i", str(AUDIO),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
         "-shortest", str(OUT)])

    (WORK / "montage.json").write_text(json.dumps({
        "total_seconds": total, "audio": str(AUDIO), "deflicker": a.deflicker,
        "shots": plan,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nFINAL: {OUT}")
    print(f"       {duration(OUT):.3f}s, {OUT.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
