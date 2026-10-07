"""Storyboard de 40 planos para «Wrath» a partir de la letra (guion -> planos).

Reutiliza el esquema del storyboard del piloto (``character``/``style``/
``negative`` + ``shots``) para que ``scratch/gen_still_faceid.py`` y
``scratch/gen_video_from_still.py`` funcionen sin tocar nada.

Uso: python scratch/build_storyboard40.py [--slots 40]
Escribe: scratch/storyboard40.json y scratch/plan40.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.musicvideo.director import direct_song  # noqa: E402
from youber.musicvideo.pipeline import load_lyrics, measure_song  # noqa: E402
from youber.musicvideo.sections import sections_from_markers  # noqa: E402
from youber.musicvideo.shots import (  # noqa: E402
    DEFAULT_SLOTS,
    build_shot_slots,
    distinct_count,
    slot_coverage,
    slots_to_shot_plan,
)
from youber.visuals.models import Motion, VisualStyle  # noqa: E402
from youber.visuals.tempo import detect_grid  # noqa: E402

AUDIO = r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav"
LRC = ROOT / "scratch" / "wrath_marked.lrc"
PILOT_STORYBOARD = ROOT / "scratch" / "storyboard.json"

#: Texto de movimiento por cada movimiento de cámara (el prompt del I2V).
MOTION_PHRASES: dict[Motion, str] = {
    Motion.ZOOM_IN: "very slow continuous push-in, the camera creeps closer, everything else almost still",
    Motion.ZOOM_OUT: "very slow continuous pull-back, the camera eases away, everything else almost still",
    Motion.PAN_LEFT: "slow steady lateral drift to the left, the subject stays put, nothing else moves",
    Motion.PAN_RIGHT: "slow steady lateral drift to the right, the subject stays put, nothing else moves",
    Motion.TILT_UP: "slow steady tilt upward, the camera rises, the subject stays put",
    Motion.TILT_DOWN: "slow steady tilt downward, the camera lowers, the subject stays put",
    Motion.STATIC: "almost imperceptible camera, the subject breathes and blinks, dust drifts slowly",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=DEFAULT_SLOTS)
    ap.add_argument("--audio", default=AUDIO)
    ap.add_argument("--lyrics", default=str(LRC))
    ap.add_argument("--title", default="Wrath")
    ap.add_argument("--out", default=str(ROOT / "scratch" / "storyboard40.json"))
    ap.add_argument("--plan-out", default=str(ROOT / "scratch" / "plan40.json"))
    a = ap.parse_args()

    pilot = json.loads(PILOT_STORYBOARD.read_text(encoding="utf-8"))
    document = load_lyrics(a.lyrics, a.audio)
    measurement = asyncio.run(measure_song(a.audio, max_seconds=180.0))
    markers = sections_from_markers(
        document,
        Path(a.lyrics).read_text(encoding="utf-8-sig"),
        duration=measurement.duration,
    )
    plan = direct_song(
        document,
        title=a.title,
        duration=measurement.duration,
        energies=measurement.energies or None,
        sections=markers,
    )
    grid = asyncio.run(detect_grid(a.audio))
    slots = build_shot_slots(plan, a.slots, grid=grid)
    report = slot_coverage(slots, plan)
    shot_plan = slots_to_shot_plan(
        plan, slots, style=VisualStyle.DARK, transition=0.0, include_topic=True
    )
    beats = {scene.index: scene.beat for scene in plan.scenes}

    shots = []
    for slot, shot in zip(slots, shot_plan.shots, strict=True):
        if slot.repeat_of is not None:
            continue  # es motivo: reutiliza el clip del hueco original
        shots.append(
            {
                "id": slot.index,
                "section": slot.section.value,
                "window": [slot.start, slot.end],
                "text": slot.text,
                "still": shot.prompt,
                "motion": f"{MOTION_PHRASES[shot.motion]}, {beats[slot.scene_index].describe()}",
            }
        )

    storyboard = {
        "character": pilot["character"],
        "style": pilot["style"],
        "negative": pilot["negative"],
        "note": (
            f"Generado desde la letra ({a.slots} huecos, {distinct_count(slots)} planos reales). "
            "Cada plano va atado a su tramo; los huecos de motivo reutilizan clip."
        ),
        "shots": shots,
    }
    Path(a.out).write_text(json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(a.plan_out).write_text(
        json.dumps(
            {
                "coverage": report.model_dump(mode="json"),
                "slots": [slot.model_dump(mode="json") for slot in slots],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"huecos={report.slots} a_generar={len(shots)} motivo={report.repeated} "
        f"ok={report.ok} cubre={report.covered:.1f}/{report.duration:.1f}s"
    )
    print(f"storyboard -> {a.out}")
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
