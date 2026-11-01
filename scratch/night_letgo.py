"""Lote nocturno de **If I Let Go** (49 planos revisados).

Lee ``prompts_video.json`` del ZIP editorial (49 planos, 121 f cada uno a 24 fps)
y genera un clip por plano cargando su PNG como imagen inicial en Wan 2.2 5B.

Mismo esqueleto que ``night_disappeared.py`` (el que funciono en *Before I
Disappeared*):

- **Resumible**: manifiesto en ``clips/manifest.json``; si el clip ya existe y
  verifica, se salta.
- **Verificado**: ``youber.genvideo.verify``; si no llega al umbral, reintento a
  16 steps con el doble de timeout.
- **Lavado**: receta fuerte aprobada el 2026-10-22; el crudo se guarda en
  ``clips/raw/``.
- **Sin abortar por rachas**: un plano malo no tumba el lote.
- **Deja rastro**: manifiesto + ``report.md`` + ``gen.log`` + logs hijos.

Diferencia con el lote anterior: aqui *todos* los planos son retratos o insertos
quietos con una microaccion (parpadeo, respiracion) y camara fija, asi que no
hay orden de riesgo: se generan en orden narrativo (001 -> 049).

Uso:
    python scratch/night_letgo.py --dry-run
    python scratch/night_letgo.py --until 08:30
    python scratch/night_letgo.py --only 001,002 --limit 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

from youber.genvideo.clean import DENOISE_STRONG, clean_clip_sync  # noqa: E402
from youber.genvideo.service import ComfyUIService  # noqa: E402
from youber.genvideo.verify import verify_clip  # noqa: E402

SCRATCH = ROOT / "scratch"
GEN_VIDEO = SCRATCH / "gen_video_from_still.py"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER = "http://127.0.0.1:8188"

PROJECT = Path(r"C:\Users\bypau\Videos\youber\IfILetGo\If_I_Let_Go")
SRC = PROJECT / "stills"
INSTRUCTIONS = PROJECT / "prompts_video.json"
OUT = PROJECT / "clips"
REPORTS = PROJECT / "reports"
MANIFEST = OUT / "manifest.json"

#: 16:9 nativo (las fuentes son 1672x941 = 1,7768). 720 si es multiplo de 16.
WIDTH, HEIGHT = 1280, 720
FPS = 24
STEPS, RETRY_STEPS = 8, 16
CFG, LORA = 1.0, 1.0

#: Medido en el lote anterior: ~700 s por 121 f a 720p/8 steps.
TIMEOUT = 3600.0

WASH_CRF = 18

WASH_RECIPES = {
    "fuerte": DENOISE_STRONG,
    "medio": "hqdn3d=3:2.5:8:8,tmix=frames=5:weights='0.1 0.2 0.4 0.2 0.1'",
    "suave": "hqdn3d=1.2:1.0:4:4,tmix=frames=3:weights='0.15 0.7 0.15'",
}


def log(message: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    print(line, flush=True)
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "gen.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class Batch:
    def __init__(self, *, dry_run: bool = False, wash_recipe: str = "fuerte") -> None:
        doc = json.loads(INSTRUCTIONS.read_text(encoding="utf-8"))
        self.title = doc.get("project", "If I Let Go")
        self.audio_seconds = doc.get("audio_duration_seconds_previously_measured")
        self.declared_fps = int(doc.get("generation_settings", {}).get("fps", FPS))
        self.shots = []
        for shot in doc["shots"]:
            shot = dict(shot)
            shot.setdefault("frames", 121)
            shot.setdefault("fps", FPS)
            #: El JSON ya declara 121 f; si algun dia trae segundos, se respeta.
            shot["frames"] = int(shot["frames"])
            self.shots.append(shot)
        self.dry_run = dry_run
        self.wash_denoise = WASH_RECIPES.get(wash_recipe, DENOISE_STRONG)
        self.manifest: dict[str, dict] = {}
        if MANIFEST.exists():
            self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.overrides: dict[str, dict] = {}
        overrides_path = OUT / "prompt_overrides.json"
        if overrides_path.exists():
            self.overrides = json.loads(overrides_path.read_text(encoding="utf-8"))

    def prompt_text(self, shot: dict) -> str:
        return self.overrides.get(shot["id"], {}).get("video_prompt_en") or shot["video_prompt_en"]

    def negative_text(self, shot: dict) -> str:
        return (
            self.overrides.get(shot["id"], {}).get("negative_prompt_en")
            or shot.get("negative_prompt_en")
            or "text, watermark, cuts, glitch effects, cartoon, cgi, oversaturated, blurry, "
            "distorted anatomy, extra limbs, extra people, flicker, camera movement, "
            "speech, singing, lip movement"
        )

    # --- utilidades ---------------------------------------------------------
    def still(self, shot: dict) -> Path:
        return SRC / Path(shot["image"]).name

    def clip_path(self, shot_id: str) -> Path:
        return OUT / f"clip{shot_id}_720p.mp4"

    def prompt_file(self, shot: dict) -> Path:
        prompts = OUT / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        path = prompts / f"{shot['id']}.txt"
        path.write_text(self.prompt_text(shot), encoding="utf-8")
        return path

    def negative_file(self, shot: dict) -> Path:
        prompts = OUT / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        path = prompts / f"{shot['id']}_negative.txt"
        path.write_text(self.negative_text(shot), encoding="utf-8")
        return path

    def publish(self, src: Path, shot_id: str) -> Path:
        target = self.clip_path(shot_id)
        if src.resolve() == target.resolve():
            return target
        if not src.exists():
            log(f"[{shot_id}] no hay clip que publicar: {src.name}")
            return src
        for attempt in range(1, 4):
            try:
                shutil.copy2(src, target)
                return target
            except PermissionError:
                if attempt == 3:
                    log(f"[{shot_id}] no pude publicar el clip: {src.name}")
                    return src
                time.sleep(1.5 * attempt)
        return src

    def wash(self, src: Path, shot_id: str) -> dict:
        stash = OUT / "raw"
        stash.mkdir(parents=True, exist_ok=True)
        raw_target = stash / f"clip{shot_id}_720p.mp4"
        if src.resolve() != raw_target.resolve():
            for attempt in range(1, 4):
                try:
                    shutil.copy2(src, raw_target)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(1.5 * attempt)
        washed = OUT / f"_{shot_id}_lavado.mp4"
        report = clean_clip_sync(
            raw_target,
            washed,
            denoise=self.wash_denoise,
            equalize=False,
            crf=WASH_CRF,
            max_level_shift=99.0,
        )
        final = self.clip_path(shot_id)
        if final.exists():
            final.unlink()
        washed.replace(final)
        if src.resolve() != raw_target.resolve() and src.exists():
            src.unlink(missing_ok=True)
        return {
            "wash": True,
            "wash_whites": round(report.whites_before, 2),
            "wash_whites_after": round(report.whites_after, 2),
            "wash_pulse_after": round(report.pulse_after, 2),
            "wash_seconds": report.seconds,
        }

    def run(self, cmd: list[str], timeout: float, *, tag: str = "") -> int:
        log(f"$ {Path(cmd[0]).name}{tag} (timeout {timeout:.0f}s)")
        if self.dry_run:
            return 0
        logfile = OUT / "logs" / f"child{tag}.log"
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n$ " + " ".join(cmd) + "\n")
            fh.flush()
            try:
                return subprocess.run(
                    cmd, timeout=timeout, stdout=fh, stderr=subprocess.STDOUT
                ).returncode
            except subprocess.TimeoutExpired:
                log(f"TIMEOUT de {timeout:.0f}s")
                self.unblock()
                return 124

    def unblock(self) -> None:
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
        except Exception as exc:  # noqa: BLE001
            log(f"no pude liberar la cola: {type(exc).__name__}")

    def save(self) -> None:
        if self.dry_run:
            return
        OUT.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(
            json.dumps(self.manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.write_report()

    def write_report(self) -> None:
        if self.dry_run:
            return
        REPORTS.mkdir(parents=True, exist_ok=True)
        ok = [k for k, v in self.manifest.items() if v.get("ok")]
        ko = [k for k, v in self.manifest.items() if not v.get("ok")]
        lines = [
            "# Lote — If I Let Go",
            "",
            f"- Receta: {self.shots[0]['frames']} f ({self.shots[0]['frames'] / FPS:.4f} s) @ "
            f"{WIDTH}x{HEIGHT} · {STEPS} steps · cfg {CFG} · LoRA {LORA}",
            f"- Planos: **{len(self.shots)}**",
            f"- Verificados: **{len(ok)}**",
            f"- Rechazados/sin clip: **{len(ko)}** {ko if ko else ''}",
            "",
            "| plano | titulo | frames | steps | seg | detalle | brillo | mov | ok |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for shot in self.shots:
            entry = self.manifest.get(shot["id"], {})
            lines.append(
                "| {id} | {t} | {fr} | {steps} | {s} | {d} | {b} | {m} | {ok} |".format(
                    id=shot["id"],
                    t=shot.get("title_es", ""),
                    fr=shot["frames"],
                    steps=entry.get("steps", ""),
                    s=f"{entry.get('seconds', 0):.0f}" if entry else "",
                    d=f"{entry['detail']:.1f}" if entry.get("detail") else "",
                    b=f"{entry['brightness']:.0f}" if entry.get("brightness") else "",
                    m=f"{entry['motion']:.1f}" if entry.get("motion") else "",
                    ok="OK" if entry.get("ok") else ("KO" if entry else "-"),
                )
            )
        (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (REPORTS / f"lote-{datetime.now():%Y%m%d-%H%M}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    # --- fases --------------------------------------------------------------
    def clip_ok(self, shot: dict) -> bool:
        clip = self.clip_path(shot["id"])
        if not clip.exists() or clip.stat().st_size == 0:
            return False
        try:
            quality = asyncio.run(
                verify_clip(
                    clip, width=WIDTH, height=HEIGHT, fps=FPS, frames=shot["frames"]
                )
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[{shot['id']}] verificacion fallo: {type(exc).__name__}")
            return False
        return bool(quality.ok)

    def generate_clip(self, shot: dict, steps: int, timeout: float) -> dict:
        sid = shot["id"]
        seed = (20000 if steps == STEPS else 21000) + int(sid)
        suffix = "" if steps == STEPS else f"_r{steps}"
        out = OUT / f"clip{sid}_720p{suffix}.mp4"

        cmd = [
            str(PY),
            str(GEN_VIDEO),
            "--image",
            str(self.still(shot)),
            "--motion-file",
            str(self.prompt_file(shot)),
            "--negative-file",
            str(self.negative_file(shot)),
            "--out",
            str(out),
            "--width",
            str(WIDTH),
            "--height",
            str(HEIGHT),
            "--frames",
            str(shot["frames"]),
            "--allow-long",
            "--fps",
            str(FPS),
            "--steps",
            str(steps),
            "--cfg",
            str(CFG),
            "--lora",
            str(LORA),
            "--seed",
            str(seed),
            "--prefix",
            f"ifl_p{sid}",
            "--timeout",
            str(timeout),
        ]
        started = time.time()
        code = self.run(cmd, timeout=timeout + 180.0, tag=f"_p{sid}_s{steps}")
        entry: dict = {
            "steps": steps,
            "seconds": round(time.time() - started, 1),
            "rc": code,
            "seed": seed,
            "frames": shot["frames"],
        }
        if code != 0 or not out.exists():
            entry["ok"] = False
            entry["reason"] = f"rc={code}"
            return entry
        quality = asyncio.run(
            verify_clip(out, width=WIDTH, height=HEIGHT, fps=FPS, frames=shot["frames"])
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
        if quality.ok:
            try:
                entry.update(self.wash(out, sid))
                washed = self.clip_path(sid)
                after = asyncio.run(
                    verify_clip(
                        washed, width=WIDTH, height=HEIGHT, fps=FPS, frames=shot["frames"]
                    )
                )
                entry.update(
                    {
                        "detail": after.detail,
                        "brightness": after.brightness,
                        "motion": after.motion,
                        "ok": bool(after.ok),
                        "reasons": list(after.reasons),
                        "file": str(washed),
                    }
                )
                log(
                    f"[{sid}] lavado ({entry['wash_whites']}->{entry['wash_whites_after']}% "
                    f"blancos) detalle {entry['detail']:.1f} mov {entry['motion']:.1f}"
                )
            except Exception as exc:  # noqa: BLE001 - sin lavado, el clip sigue valiendo
                entry["wash_error"] = f"{type(exc).__name__}: {exc}"[:300]
                log(f"[{sid}] el lavado fallo ({type(exc).__name__}); publico el crudo")
                entry["file"] = str(self.publish(out, sid))
        return entry

    def run_clips(
        self, only: set[str], limit: int, until: datetime | None, *, force: bool = False
    ) -> None:
        done = 0
        shots = sorted(self.shots, key=lambda s: s["id"])
        rejected = OUT / f"rejected_{datetime.now():%Y%m%d}"
        for shot in shots:
            sid = shot["id"]
            if only and sid not in only:
                continue
            if limit and done >= limit:
                log(f"limite de {limit} alcanzado")
                break
            if until and datetime.now() >= until:
                log("hora de parada alcanzada")
                break
            if not force and self.clip_ok(shot):
                log(f"[{sid}] ya esta")
                self.manifest[sid] = {**self.manifest.get(sid, {}), "ok": True}
                continue
            if force:
                current = self.clip_path(sid)
                if current.exists():
                    rejected.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(current, rejected / current.name)
                        log(f"[{sid}] copia del anterior en {rejected.name}")
                    except PermissionError:
                        log(f"[{sid}] no pude copiar el anterior (bloqueado)")
            log(
                f"[{sid}] {shot.get('title_es', '')!r} | {shot['frames']}f "
                f"({shot['frames'] / FPS:.2f}s) @ {WIDTH}x{HEIGHT} | steps {STEPS}"
            )
            if self.dry_run:
                done += 1
                continue
            entry = self.generate_clip(shot, STEPS, TIMEOUT)
            if not entry.get("ok"):
                log(
                    f"[{sid}] rechazado ({entry.get('reasons') or entry.get('reason')}) "
                    f"-> reintento a {RETRY_STEPS} steps"
                )
                retry = self.generate_clip(shot, RETRY_STEPS, TIMEOUT * 2)
                entry = {**retry, "first_attempt": entry}
            self.manifest[sid] = {**entry, "title": shot.get("title_es", "")}
            log(
                f"[{sid}] ok={entry.get('ok')} detalle={entry.get('detail')} "
                f"mov={entry.get('motion')} ({entry.get('seconds')}s)"
            )
            self.save()
            done += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--until", default="", help="hora local de parada (HH:MM)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="ids separados por coma")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Regenerar aunque el clip ya verifique (guarda copia en rejected_<fecha>)",
    )
    ap.add_argument(
        "--wash-recipe",
        choices=sorted(WASH_RECIPES),
        default="fuerte",
        help="Receta de lavado (por defecto la del lote original)",
    )
    ap.add_argument(
        "--keep-comfyui",
        action="store_true",
        help="No parar ComfyUI al terminar (si lo arranco este lote)",
    )
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "BATCH_RUNNING"
    if lock.exists() and not args.dry_run:
        log("ya hay un lote en marcha (BATCH_RUNNING); salgo")
        return 0

    until = None
    if args.until:
        hh, mm = (int(x) for x in args.until.split(":"))
        until = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if until <= datetime.now():
            until = until + timedelta(days=1)

    batch = Batch(dry_run=args.dry_run, wash_recipe=args.wash_recipe)
    missing = [shot["id"] for shot in batch.shots if not batch.still(shot).exists()]
    if missing:
        log(f"faltan fuentes: {', '.join(missing)}")
        return 2

    pending = [shot for shot in batch.shots if not batch.clip_ok(shot)]
    if not pending and not args.dry_run:
        log(f"nada que hacer: {len(batch.shots)}/{len(batch.shots)} clips ya verificados")
        return 0

    service: ComfyUIService | None = None
    started_comfyui = False
    if not args.dry_run:
        service = ComfyUIService()
        try:
            started_comfyui = asyncio.run(service.ensure_running())
        except Exception as exc:  # noqa: BLE001
            log(f"ComfyUI no arranca: {type(exc).__name__}: {exc}")
            return 3

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    total_frames = sum(shot["frames"] for shot in batch.shots)
    log(
        f"lote If I Let Go: {len(batch.shots)} planos | {total_frames} frames | "
        f"{WIDTH}x{HEIGHT} | {STEPS} steps cfg {CFG} lora {LORA} | "
        f"parada {args.until or 'sin limite'}"
    )
    if not args.dry_run:
        lock.write_text(datetime.now().isoformat(), encoding="utf-8")
    try:
        batch.run_clips(only, args.limit, until, force=args.force)
        batch.save()
        ok = sum(1 for entry in batch.manifest.values() if entry.get("ok"))
        log(f"FIN: {ok}/{len(batch.shots)} clips verificados")
    finally:
        if not args.dry_run:
            lock.unlink(missing_ok=True)
            if service is not None and started_comfyui and not args.keep_comfyui:
                asyncio.run(service.stop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
