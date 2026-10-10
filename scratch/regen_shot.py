"""Regenera planos concretos de un guion (fotos + instrucciones.json).

Sirve para rehacer tomas mal generadas sin repetir el lote entero. Usa los
prompts de instrucciones.json, o los de <carpeta>/prompt_overrides.json si
existe (mismo formato: {id: {"motion": ..., "negative": ...}}).

Uso:
    python scratch/regen_shot.py --folder DIR --shots 007,008 --res 480p \
        --shift 6 --reseed --out-dir DIR/_preview
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.genvideo.verify import verify_clip  # noqa: E402

GEN = ROOT / "scratch" / "gen_video_from_still.py"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
PRESETS = {"720p": (1280, 704, 8), "480p": (832, 480, 4)}
FPS = 24.0
STEPS_RETRY = 16
TIMEOUT = 5400.0


def log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def load_doc(folder: Path) -> dict:
    for cand in sorted(folder.glob("*.json")):
        data = json.loads(cand.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("shots"):
            return data
    raise SystemExit(f"ningun JSON con 'shots' en {folder}")


def frame_for(src: Path, dst: Path, w: int, h: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", "-frames:v", "1", str(dst)],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--shots", required=True, help="lista separada por comas")
    ap.add_argument("--res", default="480p", choices=sorted(PRESETS))
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--shift", type=float, default=6.0)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--seed-base", type=int, default=None)
    ap.add_argument("--reseed", action="store_true")
    ap.add_argument("--tag", default="v2", help="sufijo del clip generado")
    ap.add_argument("--replace", action="store_true",
                    help="sustituye clip{id}_{res}.mp4 (hace copia _v1)")
    a = ap.parse_args()

    folder = Path(a.folder)
    out_dir = Path(a.out_dir) if a.out_dir else folder / "_regen"
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h, steps0 = PRESETS[a.res]
    steps0 = a.steps or steps0

    doc = load_doc(folder)
    by_id = {s["id"]: s for s in doc["shots"]}
    overrides_path = folder / "prompt_overrides.json"
    overrides = (
        json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides_path.exists()
        else {}
    )

    ids = [s.strip() for s in a.shots.split(",") if s.strip()]
    frames_dir = out_dir / f"_frames_{a.res}"
    for sid in ids:
        shot = by_id.get(sid)
        if shot is None:
            log(f"[{sid}] no esta en el guion")
            continue
        frame = frames_dir / f"{sid}.png"
        if not frame.exists():
            frame_for(folder / shot["image"], frame, w, h)
        ov = overrides.get(sid, {})
        motion = ov.get("motion") or shot.get("animation_prompt_en") or ""
        negative = ov.get("negative") or shot.get("negative_prompt") or ""
        mfile = out_dir / f"_p{sid}.motion.txt"
        nfile = out_dir / f"_p{sid}.negative.txt"
        mfile.write_text(motion, encoding="utf-8")
        nfile.write_text(negative, encoding="utf-8")
        frames = int(round(float(shot.get("clip_duration_seconds") or 8) * FPS))
        base = a.seed_base if a.seed_base is not None else 8000 + int(sid)
        seed = base + (random.randint(1000, 900000) if a.reseed else 0)
        out = out_dir / f"clip{sid}_{a.res}_{a.tag}.mp4"
        out.unlink(missing_ok=True)

        for attempt, steps in enumerate((steps0, STEPS_RETRY), start=1):
            log(f"[{sid}] intento {attempt} steps={steps} shift={a.shift} seed={seed} "
                f"{frames}f -> {out.name}")
            cmd = [str(PY), str(GEN), "--image", str(frame),
                   "--motion-file", str(mfile), "--negative-file", str(nfile),
                   "--out", str(out), "--width", str(w), "--height", str(h),
                   "--frames", str(frames), "--fps", str(FPS), "--steps", str(steps),
                   "--shift", str(a.shift), "--seed", str(seed),
                   "--prefix", f"youber_wrath_{sid}_{a.tag}", "--timeout", str(TIMEOUT)]
            t0 = time.time()
            rc = subprocess.run(cmd, timeout=TIMEOUT + 300).returncode
            log(f"[{sid}] rc={rc} en {time.time() - t0:.0f}s")
            if rc != 0 or not out.exists():
                continue
            q = asyncio.run(verify_clip(out, width=w, height=h, fps=FPS, frames=frames))
            log(f"[{sid}] ok={q.ok} detalle={q.detail} motivos={q.reasons}")
            if q.ok:
                break
        if not out.exists():
            log(f"[{sid}] NO se genero")
            continue
        if a.replace:
            final = folder / "_clips" / f"clip{sid}_{a.res}.mp4"
            if final.exists():
                final.with_name(f"clip{sid}_{a.res}_v1.mp4").write_bytes(final.read_bytes())
            final.write_bytes(out.read_bytes())
            log(f"[{sid}] sustituido -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
