"""Lote nocturno: genera los planos del guion (stills FaceID + vídeo Wan I2V).

Pensado para lanzarse a las 22:00 y trabajar toda la noche:

- **Resumible**: si se corta, al relanzar sigue por donde iba (mira qué stills y
  qué clips ya existen y verifican).
- **Verificado**: cada clip pasa por ``youber.genvideo.verify`` (detalle, brillo,
  movimiento) y los que salen planos se reintentan a más steps.
- **Sin abortar por rachas**: un clip malo no tumba el lote.
- **Deja rastro**: manifiesto JSON + informe Markdown + log, actualizados tras
  cada clip.

Uso: python scratch/night_shots.py [--dry-run] [--outdir ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.genvideo.verify import verify_clip  # noqa: E402

SERVER = "http://127.0.0.1:8188"
SCRATCH = ROOT / "scratch"
GEN_STILL = SCRATCH / "gen_still_faceid.py"
GEN_VIDEO = SCRATCH / "gen_video_from_still.py"
OUT_DIR = Path(r"C:\Users\bypau\Videos\youber\Wrath\shots40")
REFS = [
    r"C:\Users\bypau\Videos\youber\_piloto\faceid_r12\fx02_r12.png",
    r"C:\Users\bypau\Videos\youber\_piloto\faceid_r12\fx05_r12.png",
    r"C:\Users\bypau\Videos\youber\_piloto\faceid_r12\fx10_r12.png",
]

WIDTH, HEIGHT, FRAMES, FPS = 1280, 704, 121, 24
STEPS, RETRY_STEPS = 8, 16
#: Segundos por clip medidos: 700 s a 8 steps y 720p; el reintento pide el doble.
TIMEOUT = 5400.0
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def log(message: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    print(line, flush=True)


class NightBatch:
    """El lote: stills primero, luego los vídeos, con manifiesto resumible."""

    def __init__(self, storyboard: Path, out_dir: Path, *, dry_run: bool = False) -> None:
        self.storyboard = json.loads(storyboard.read_text(encoding="utf-8"))
        self.shots = self.storyboard["shots"]
        self.out = out_dir
        self.dry_run = dry_run
        self.stills = out_dir / "stills"
        self.clips = out_dir / "clips"
        self.manifest_path = out_dir / "manifest.json"
        self.manifest: dict[str, dict] = {}
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    # --- utilidades ---------------------------------------------------------

    def still_path(self, shot_id: int) -> Path:
        return self.stills / f"fx{shot_id:03d}_s40.png"

    def clip_path(self, shot_id: int) -> Path:
        return self.clips / f"clip{shot_id:03d}_720p.mp4"

    def run(self, cmd: list[str], timeout: float) -> int:
        if self.dry_run:
            return 0
        try:
            return subprocess.run(cmd, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            log(f"TIMEOUT de {timeout:.0f}s")
            self.unblock()
            return 124

    def unblock(self) -> None:
        """Suelta un trabajo colgado: interrumpe y vacía la cola si es nuestra."""
        if self.dry_run:
            return
        try:
            import httpx

            with httpx.Client(timeout=10.0) as client:
                queue = client.get(f"{SERVER}/queue").json()
                pending = len(queue.get("queue_pending") or []) + len(
                    queue.get("queue_running") or []
                )
                if pending:
                    client.post(f"{SERVER}/interrupt")
                    client.post(f"{SERVER}/queue", json={"clear": True})
                    log(f"cola liberada ({pending} trabajos)")
        except Exception as exc:  # noqa: BLE001 - nunca debe tumbar el lote
            log(f"no pude liberar la cola: {type(exc).__name__}")

    def save(self) -> None:
        if self.dry_run:
            return
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.write_report()

    def write_report(self) -> None:
        if self.dry_run:
            return
        ok = [k for k, v in self.manifest.items() if v.get("ok")]
        ko = [k for k, v in self.manifest.items() if not v.get("ok")]
        lines = [
            "# Lote nocturno · planos del guion (Wrath, 40 huecos)",
            "",
            f"- Planos a generar: **{len(self.shots)}**",
            f"- Con clip verificado: **{len(ok)}**",
            f"- Sin clip / rechazados: **{len(ko)}** {ko if ko else ''}",
            "",
            "| plano | tramo | s | steps | detalle | brillo | mov | ok |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for shot in self.shots:
            entry = self.manifest.get(str(shot["id"]), {})
            lines.append(
                "| {id} | {section} | {secs} | {steps} | {detail} | {bright} | {motion} | {ok} |".format(
                    id=shot["id"],
                    section=shot["section"],
                    secs=f"{entry.get('seconds', 0):.0f}" if entry else "",
                    steps=entry.get("steps", ""),
                    detail=f"{entry['detail']:.1f}" if entry.get("detail") else "",
                    bright=f"{entry['brightness']:.0f}" if entry.get("brightness") else "",
                    motion=f"{entry['motion']:.1f}" if entry.get("motion") else "",
                    ok="✅" if entry.get("ok") else ("❌" if entry else "·"),
                )
            )
        (self.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- fases --------------------------------------------------------------
    def missing_stills(self) -> list[int]:
        return [int(s["id"]) for s in self.shots if not self.still_path(int(s["id"])).exists()]

    def generate_stills(self) -> None:
        for attempt in range(1, 4):
            missing = self.missing_stills()
            if not missing:
                return
            log(f"stills: faltan {len(missing)} (intento {attempt})")
            cmd = [
                str(PY),
                str(GEN_STILL),
                "--storyboard",
                str(SCRATCH / "storyboard40.json"),
                "--refs",
                *REFS,
                "--shots",
                *[str(i) for i in missing],
                "--outdir",
                str(self.stills),
                "--suffix",
                "_s40",
                "--width",
                str(WIDTH),
                "--height",
                str(HEIGHT),
                "--seed-base",
                "4000",
            ]
            self.run(cmd, timeout=3600.0)
            if self.dry_run:
                return

    def clip_ok(self, shot_id: int) -> bool:
        clip = self.clip_path(shot_id)
        if not clip.exists() or clip.stat().st_size == 0:
            return False
        try:
            quality = asyncio.run(
                verify_clip(clip, width=WIDTH, height=HEIGHT, fps=FPS, frames=FRAMES)
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[{shot_id:03d}] verificación falló: {type(exc).__name__}")
            return False
        return bool(quality.ok)

    def generate_clip(self, shot: dict, steps: int, timeout: float) -> dict:
        shot_id = int(shot["id"])
        seed = (2000 if steps == STEPS else 3000) + shot_id
        suffix = "" if steps == STEPS else "_r16"
        out = self.clips / f"clip{shot_id:03d}_720p{suffix}.mp4"
        cmd = [
            str(PY),
            str(GEN_VIDEO),
            "--image",
            str(self.still_path(shot_id)),
            "--motion",
            shot["motion"],
            "--out",
            str(out),
            "--width",
            str(WIDTH),
            "--height",
            str(HEIGHT),
            "--frames",
            str(FRAMES),
            "--fps",
            str(FPS),
            "--steps",
            str(steps),
            "--seed",
            str(seed),
            "--prefix",
            f"youber_s40_p{shot_id:03d}",
            "--timeout",
            str(timeout),
        ]
        started = time.time()
        code = self.run(cmd, timeout=timeout + 120.0)
        entry: dict = {"steps": steps, "seconds": round(time.time() - started, 1), "rc": code}
        if code != 0 or not out.exists():
            entry["ok"] = False
            entry["reason"] = f"rc={code}"
            return entry
        quality = asyncio.run(
            verify_clip(out, width=WIDTH, height=HEIGHT, fps=FPS, frames=FRAMES)
        )
        entry.update(
            {
                "ok": bool(quality.ok),
                "detail": quality.detail,
                "brightness": quality.brightness,
                "motion": quality.motion,
                "reasons": list(quality.reasons),
                "file": str(out),
            }
        )
        if quality.ok and steps == STEPS:
            target = self.clip_path(shot_id)
            shutil.copy2(out, target)
            entry["file"] = str(target)
        return entry

    def run_clips(self) -> None:
        for shot in self.shots:
            shot_id = int(shot["id"])
            key = str(shot_id)
            if self.clip_ok(shot_id):
                log(f"[{shot_id:03d}] ya está")
                self.manifest[key] = {**self.manifest.get(key, {}), "ok": True}
                continue
            log(f"[{shot_id:03d}] generando ({shot['section']}): {shot['text'][:40]!r}")
            entry = self.generate_clip(shot, STEPS, TIMEOUT)
            if not entry.get("ok"):
                log(f"[{shot_id:03d}] rechazado ({entry.get('reasons')}) -> reintento a {RETRY_STEPS} steps")
                retry = self.generate_clip(shot, RETRY_STEPS, TIMEOUT * 2)
                if retry.get("ok"):
                    target = self.clip_path(shot_id)
                    shutil.copy2(Path(retry["file"]), target)
                    retry["file"] = str(target)
                entry = {**retry, "first_attempt": entry}
            self.manifest[key] = {**entry, "section": shot["section"], "text": shot["text"]}
            log(
                f"[{shot_id:03d}] ok={entry.get('ok')} detalle={entry.get('detail')} "
                f"({entry.get('seconds')}s)"
            )
            self.save()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", default=str(SCRATCH / "storyboard40.json"))
    ap.add_argument("--outdir", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-stills", action="store_true")
    a = ap.parse_args()

    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    lock = out / "BATCH_RUNNING"
    if lock.exists() and not a.dry_run:
        log("ya hay un lote en marcha (BATCH_RUNNING); salgo")
        return 0
    if not a.dry_run:
        lock.write_text(datetime.now().isoformat(), encoding="utf-8")

    batch = NightBatch(Path(a.storyboard), out, dry_run=a.dry_run)
    log(f"lote: {len(batch.shots)} planos -> {out}")
    try:
        if not a.skip_stills:
            batch.generate_stills()
        batch.run_clips()
        batch.save()
        ok = sum(1 for entry in batch.manifest.values() if entry.get("ok"))
        log(f"FIIN: {ok}/{len(batch.shots)} clips verificados")
    finally:
        if not a.dry_run:
            lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
