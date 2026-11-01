"""Estado compacto del lote de If I Let Go (para el resumen de la manana).

Uso:
    python scratch/status_letgo.py
    python scratch/status_letgo.py --md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

PROJECT = Path(r"C:\Users\bypau\Videos\youber\IfILetGo\If_I_Let_Go")
CLIPS = PROJECT / "clips"
PLAN = PROJECT / "prompts_video.json"
MANIFEST = CLIPS / "manifest.json"
FFPROBE = "ffprobe"


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    doc = json.loads(PLAN.read_text(encoding="utf-8"))
    shots = {s["id"]: s for s in doc["shots"]}
    manifest: dict = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    ready, missing, failed = [], [], []
    for sid in sorted(shots):
        clip = CLIPS / f"clip{sid}_720p.mp4"
        if clip.exists() and clip.stat().st_size > 0:
            ready.append(sid)
        else:
            missing.append(sid)
            entry = manifest.get(sid)
            if entry is not None and not entry.get("ok", True):
                failed.append(sid)

    running = (CLIPS / "BATCH_RUNNING").exists()
    total_gb = sum((CLIPS / f"clip{sid}_720p.mp4").stat().st_size for sid in ready) / 1e9
    if not ready:
        print("If I Let Go: 0/49 clips")
        return 0
    sample = CLIPS / f"clip{ready[-1]}_720p.mp4"
    print(
        f"If I Let Go: {len(ready)}/{len(shots)} clips | {total_gb:.2f} GB | "
        f"lote {'EN MARCHA' if running else 'parado'} | ultimo {ready[-1]} {duration(sample):.2f}s"
    )
    if missing:
        print(f"  pendientes ({len(missing)}): {', '.join(missing)}")
    if failed:
        print(f"  rechazados con rastro ({len(failed)}): {', '.join(failed)}")
    if args.md and (CLIPS / "report.md").exists():
        print()
        print((CLIPS / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
