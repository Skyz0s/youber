"""Experimento de locomocion: por que los planos de caminar no se desplazan.

Genera 3 variantes del plano 029 (el de "Caminar hacia ella") con Wan 2.2
TI2V-5B y las mide:

- control: prompt actual del lote, pero a 121 frames (5 s) en vez de 193 (8 s)
- estatico: camara fija, ella se aleja por el pasillo (prompt reescrito)
- lateral: travelling lateral, ella cruza el encuadre de izquierda a derecha

Metricas por clip:
- desplazamiento del fondo (correlacion de fase horizontal en la banda superior)
- deriva del centroide de lo que cambia respecto al primer frame
- movimiento residual (diferencia media entre frames)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
GEN = ROOT / "scratch" / "gen_video_from_still.py"
SRC = Path(
    r"C:\Users\bypau\Music\Gpt\Everything_breaking_down_COMPLETO\Everything_breaking_down"
)
IMG = SRC / "029.png"
OUT = ROOT / "scratch" / "_loco_test"

IDENT = (
    "Preserve the exact woman, face, hair, rust blouse, charcoal trousers, jewelry, "
    "lighting and scene geometry visible in the image. "
)

NEG_COMMON = (
    "walking in place, treadmill, sliding feet, skating feet, floating feet, static pose, "
    "idle standing, frozen legs, morphing face, identity change, extra limbs, warped walls, "
    "text, subtitles, logos, camera shake, sudden zoom, flames, explosions"
)

VARIANTS = [
    {
        "name": "A_control",
        "steps": 8,
        "lora": 1.0,
        "prompt": (
            "Animate the supplied still as the exact first frame. One continuous photorealistic "
            "1970s cinematic shot, landscape 16:9. " + IDENT +
            "Use restrained natural motion. Slow deliberate forward walk, camera follows behind. "
            "Fine dust drifts, she does not retreat. Keep feet grounded and hallway stable. "
            "No dialogue, no lip sync. Keep mouth closed. Preserve natural anatomy."
        ),
    },
    {
        "name": "B_estatico",
        "steps": 8,
        "lora": 1.0,
        "prompt": (
            "Animate the supplied still as the exact first frame. One continuous photorealistic "
            "1970s cinematic shot, landscape 16:9. " + IDENT +
            "She walks away from the camera down the hallway toward the amber light under the door. "
            "Three slow deliberate steps: heel down first, weight forward, hips shift, arms swing "
            "naturally at her sides. Her boots plant on the floor and stay planted while the other "
            "foot lifts; the distance between her and the camera grows and she becomes smaller in "
            "frame. Locked-off camera on a tripod: no pan, no zoom, no push-in, no shake. "
            "Dust drifts in the air. No dialogue, no lip sync. Keep mouth closed. Preserve anatomy."
        ),
    },
    {
        "name": "C_lateral",
        "steps": 8,
        "lora": 0.7,
        "prompt": (
            "Animate the supplied still as the exact first frame. One continuous photorealistic "
            "1970s cinematic shot, landscape 16:9. " + IDENT +
            "Side-on shot: she walks from left to right along the hallway, crossing in front of the "
            "doorframes. Three steps, heel to toe: each foot lifts, swings forward and plants while "
            "the hips bob and her coat sways; her whole body travels across the frame. The camera "
            "tracks her horizontally at walking speed, so the doorframes and the door slide past "
            "behind her with clear parallax; foreground doorframe sweeps past. Steady camera height, "
            "no zoom. No dialogue, no lip sync. Keep mouth closed. Preserve anatomy."
        ),
    },
]


def run_variant(v: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    clip = OUT / f"{v['name']}.mp4"
    prompt_file = OUT / f"{v['name']}.txt"
    prompt_file.write_text(v["prompt"], encoding="utf-8")
    neg_file = OUT / f"{v['name']}.neg.txt"
    neg_file.write_text(NEG_COMMON, encoding="utf-8")
    if clip.exists() and clip.stat().st_size > 0:
        print(f"[skip] {v['name']} ya existe")
        return clip
    cmd = [
        str(PY), "-u", str(GEN), "--image", str(IMG),
        "--motion-file", str(prompt_file), "--negative-file", str(neg_file),
        "--out", str(clip), "--width", "1280", "--height", "704",
        "--frames", "121", "--fps", "24",
        "--steps", str(v["steps"]), "--lora", str(v["lora"]),
        "--seed", "777001", "--prefix", f"loco_{v['name']}",
        "--timeout", "3600",
    ]
    print(f"\n=== {v['name']} | steps {v['steps']} | lora {v['lora']} ===", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(proc.stdout[-1500:])
    if proc.returncode != 0:
        print(proc.stderr[-800:])
        raise RuntimeError(f"{v['name']} fallo rc={proc.returncode}")
    return clip


def frames(path: Path, w: int = 320, h: int = 176) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    ).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.float32)


def shift_x(a: np.ndarray, b: np.ndarray) -> float:
    """Desplazamiento horizontal dominante entre dos bandas (correlacion de fase)."""
    a = a - a.mean()
    b = b - b.mean()
    fa = np.fft.rfft2(a)
    fb = np.fft.rfft2(b)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    dx = peak[1]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    return float(dx)


def probe(path: Path) -> dict:
    f = frames(path)
    n, h, w = f.shape
    band = f[:, : int(h * 0.35), :]  # fondo: paredes/techo
    bg = []
    for i in range(0, n - 1, 6):
        bg.append(shift_x(band[i], band[i + 1]))
    bg_disp = float(np.sum(bg))
    # deriva del sujeto: centroide de pixeles que cambian respecto al frame 0
    ref = f[0]
    cx = []
    for i in range(0, n, 6):
        d = np.abs(f[i] - ref) > 18
        if d.sum() > 40:
            ys, xs = np.nonzero(d)
            cx.append(float(xs.mean()))
    drift = (max(cx) - min(cx)) if cx else 0.0
    motion = float(np.abs(np.diff(f[::3], axis=0)).mean())
    return {"frames": n, "bg_dx": bg_disp, "subject_drift": drift, "motion": motion}


def main() -> int:
    which = sys.argv[1:] or [v["name"] for v in VARIANTS]
    for v in VARIANTS:
        if v["name"] not in which:
            continue
        clip = run_variant(v)
        m = probe(clip)
        print(f"[{v['name']}] frames={m['frames']} bg_dx={m['bg_dx']:+.1f}px "
              f"drift={m['subject_drift']:.1f}px motion={m['motion']:.2f}", flush=True)

    clips = [OUT / f"{v['name']}.mp4" for v in VARIANTS]
    if all(c.exists() for c in clips):
        cmp_path = OUT / "comparativa.mp4"
        inputs: list[str] = []
        for c in clips:
            inputs += ["-i", str(c)]
        filt = "".join(f"[{i}:v]scale=640:352,setsar=1[v{i}];" for i in range(len(clips)))
        filt += "".join(f"[v{i}]" for i in range(len(clips)))
        filt += f"hstack=inputs={len(clips)}[out]"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filt,
             "-map", "[out]", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "22", "-pix_fmt", "yuv420p", str(cmp_path)],
            check=True,
        )
        print(f"\ncomparativa: {cmp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
