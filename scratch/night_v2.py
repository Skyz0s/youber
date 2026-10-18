"""Lote v2 de 'Everything is breaking down' — 69 planos de ~4 s.

Diferencias con el lote v1:

- Lee `_v2/plan.json` (duraciones, prompts, pasos y LoRA por plano).
- Verifica cada clip con `verify_clip` **y** con `locomotion.measure`; los planos
  que piden locomocion se reintentan si el fondo/sujeto no se desplazan.
- Reanudable: manifiesto incremental en `_v2/clips/manifest.json`.
- Deja `report.md` y `gen.log`; no aborta el lote por un plano malo.

Uso:
    python scratch/night_v2.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.genvideo.locomotion import measure  # noqa: E402
from youber.genvideo.verify import verify_clip  # noqa: E402

SRC = Path(
    r"C:\Users\bypau\Music\Gpt\Everything_breaking_down_COMPLETO\Everything_breaking_down"
)
V2 = SRC / "_v2"
PLAN = V2 / "plan.json"
CLIPS = V2 / "clips"
PROMPTS = V2 / "prompts"
MANIFEST = CLIPS / "manifest.json"
GEN = ROOT / "scratch" / "gen_video_from_still.py"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER = "http://127.0.0.1:8188"
RUNNING = CLIPS / "BATCH_RUNNING"

WIDTH, HEIGHT, FPS = 1280, 704, 24.0


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    with (CLIPS / "gen.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


class Batch:
    def __init__(self, *, dry_run: bool = False, limit: int = 0) -> None:
        self.doc = json.loads(PLAN.read_text(encoding="utf-8"))
        self.shots = self.doc["shots"]
        self.negative = self.doc["negative"]
        self.dry_run = dry_run
        self.limit = limit
        self.manifest: dict[str, dict] = {}
        if MANIFEST.exists():
            self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def clip_path(self, shot: dict) -> Path:
        return CLIPS / f"clip{shot['id']}.mp4"

    def save(self) -> None:
        if self.dry_run:
            return
        CLIPS.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        self.write_report()

    def write_report(self) -> None:
        if self.dry_run:
            return
        ok = [k for k, v in self.manifest.items() if v.get("ok")]
        review = [k for k, v in self.manifest.items() if v.get("review")]
        ko = [k for k, v in self.manifest.items() if not v.get("ok") and not v.get("review")]
        lines = [
            "# Lote v2 — Everything is breaking down",
            "",
            f"- Planos: **{len(self.shots)}**",
            f"- Verificados: **{len(ok)}**",
            f"- A revisar (locomocion dudosa): **{len(review)}** {review if review else ''}",
            f"- Sin clip: **{len(ko)}** {ko if ko else ''}",
            "",
            "| plano | seccion | modo | steps | seg | detalle | brillo | mov | fondo | sujeto | ok |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for shot in self.shots:
            e = self.manifest.get(shot["id"], {})
            lines.append(
                f"| {shot['id']} | {shot['section']} | {shot['mode']} | {e.get('steps', '')} | "
                f"{e.get('seconds', 0):.0f} | {e.get('detail', 0):.1f} | "
                f"{e.get('brightness', 0):.0f} | {e.get('motion', 0):.1f} | "
                f"{e.get('bg_dx', 0):+.1f} | {e.get('subject_dx', 0):.1f} | "
                f"{'OK' if e.get('ok') else ('REVIEW' if e.get('review') else '-')} |"
            )
        (CLIPS / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def unblock(self) -> None:
        if self.dry_run:
            return
        try:
            import httpx

            with httpx.Client(timeout=10.0) as c:
                q = c.get(f"{SERVER}/queue").json()
                pending = len(q.get("queue_pending") or []) + len(q.get("queue_running") or [])
                if pending:
                    c.post(f"{SERVER}/interrupt")
                    c.post(f"{SERVER}/queue", json={"clear": True})
                    log(f"cola liberada ({pending} trabajos)")
        except Exception as exc:  # noqa: BLE001
            log(f"no pude liberar la cola: {type(exc).__name__}")

    def generate(self, shot: dict, *, steps: int, lora: float, seed: int,
                 timeout: float) -> tuple[int, float]:
        out = self.clip_path(shot)
        prompt_file = PROMPTS / f"{shot['id']}.txt"
        neg_file = PROMPTS / "negative.txt"
        cmd = [
            str(PY), "-u", str(GEN),
            "--image", shot["still"],
            "--motion-file", str(prompt_file),
            "--negative-file", str(neg_file),
            "--out", str(out),
            "--width", str(WIDTH), "--height", str(HEIGHT),
            "--frames", str(shot["frames"]), "--fps", str(int(FPS)),
            "--steps", str(steps), "--lora", str(lora),
            "--seed", str(seed), "--prefix", f"v2_{shot['id']}",
            "--timeout", str(int(timeout) - 60),
        ]
        started = time.time()
        log(f"[{shot['id']}] {shot['mode']} | {shot['frames']}f | steps {steps} | "
            f"lora {lora} | seed {seed}")
        if self.dry_run:
            return 0, 0.0
        logfile = CLIPS / "logs" / f"{shot['id']}_s{steps}.log"
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n$ " + " ".join(cmd) + "\n")
            fh.flush()
            try:
                rc = subprocess.run(cmd, timeout=timeout, stdout=fh,
                                    stderr=subprocess.STDOUT).returncode
            except subprocess.TimeoutExpired:
                log(f"[{shot['id']}] TIMEOUT {timeout:.0f}s")
                self.unblock()
                rc = 124
        return rc, round(time.time() - started, 1)

    def check(self, shot: dict, rc: int, seconds: float, steps: int) -> dict:
        out = self.clip_path(shot)
        entry: dict = {"steps": steps, "seconds": seconds, "rc": rc, "mode": shot["mode"]}
        if self.dry_run:
            entry.update(ok=True, review=False, reasons=[])
            return entry
        if rc != 0 or not out.exists() or out.stat().st_size == 0:
            entry.update(ok=False, review=False, reasons=[f"rc={rc}"])
            return entry
        q = asyncio.run(verify_clip(out, width=WIDTH, height=HEIGHT, fps=FPS,
                                    frames=shot["frames"]))
        entry.update(detail=round(float(q.detail), 2), brightness=round(float(q.brightness), 2),
                     motion=round(float(q.motion), 2), ok=bool(q.ok), reasons=list(q.reasons))
        if shot["mode"] in ("away", "lateral", "tracking", "toward"):
            lap = measure(out, mode=shot["mode"], fps=FPS)
            entry.update(bg_dx=round(lap.bg_dx, 1), bg_dy=round(lap.bg_dy, 1),
                         subject_dx=round(lap.subject_dx, 1),
                         area_ratio=round(lap.area_ratio, 3), loco_score=lap.score)
            if not lap.ok:
                entry["ok"] = False
                entry["reasons"] = list(entry.get("reasons") or []) + lap.reasons
        return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="genera solo los N primeros pendientes")
    a = ap.parse_args()

    batch = Batch(dry_run=a.dry_run, limit=a.limit)
    PROMPTS.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    (PROMPTS / "negative.txt").write_text(batch.negative, encoding="utf-8")
    for shot in batch.shots:
        (PROMPTS / f"{shot['id']}.txt").write_text(shot["prompt"], encoding="utf-8")

    todo = [s for s in batch.shots if not batch.manifest.get(s["id"], {}).get("ok")]
    total_frames = sum(s["frames"] for s in batch.shots)
    log(f"plan: {len(batch.shots)} planos | {total_frames / FPS:.2f}s | "
        f"pendientes: {len(todo)}")
    if a.limit:
        todo = todo[: a.limit]

    if not a.dry_run:
        RUNNING.write_text(str(datetime.now()), encoding="utf-8")
    failures = 0
    try:
        for i, shot in enumerate(todo, 1):
            log(f"--- {i}/{len(todo)} · plano {shot['id']} ({shot['title']}) ---")
            steps, lora = int(shot["steps"]), float(shot["lora"])
            seed = 710000 + int(shot["id"][:3]) * 10
            rc, secs = batch.generate(shot, steps=steps, lora=lora, seed=seed, timeout=2400)
            entry = batch.check(shot, rc, secs, steps)

            if not entry.get("ok") and not entry.get("review"):
                retry_steps = max(16, steps + 8)
                log(f"[{shot['id']}] rechazado ({', '.join(entry.get('reasons') or [])}) "
                    f"-> reintento {retry_steps} steps")
                rc, secs = batch.generate(shot, steps=retry_steps, lora=lora, seed=seed + 1,
                                          timeout=3600)
                entry = batch.check(shot, rc, secs, retry_steps)

            if not entry.get("ok"):
                # ultimo intento solo para locomocion: otra semilla, mas LoRA base
                if shot["mode"] in ("away", "lateral", "tracking", "toward"):
                    log(f"[{shot['id']}] locomocion dudosa -> tercer intento")
                    rc, secs = batch.generate(shot, steps=max(12, steps), lora=0.9,
                                              seed=seed + 2, timeout=3600)
                    entry = batch.check(shot, rc, secs, max(12, steps))
                if not entry.get("ok"):
                    entry["review"] = True if entry.get("rc") == 0 else False
                    failures += 1

            batch.manifest[shot["id"]] = entry
            batch.save()
            log(f"[{shot['id']}] ok={entry.get('ok')} review={entry.get('review')} "
                f"detalle={entry.get('detail')} brillo={entry.get('brightness')} "
                f"mov={entry.get('motion')} bg={entry.get('bg_dx')}")
    finally:
        batch.save()
        if not a.dry_run:
            RUNNING.unlink(missing_ok=True)
    log(f"FIN: {len([k for k, v in batch.manifest.items() if v.get('ok')])}/{len(batch.shots)} OK, "
        f"{failures} a revisar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
