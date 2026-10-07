"""Smoke: plan de 40 huecos para Wrath desde la letra marcada + cobertura."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\bypau\.openclaw\workspace\youber\projects\barf")
sys.path.insert(0, str(ROOT / "src"))

from youber.musicvideo.director import direct_song  # noqa: E402
from youber.musicvideo.pipeline import load_lyrics, measure_song  # noqa: E402
from youber.musicvideo.sections import sections_from_markers  # noqa: E402
from youber.musicvideo.shots import (  # noqa: E402
    build_shot_slots,
    distinct_count,
    slot_coverage,
    slots_to_shot_plan,
)
from youber.visuals.tempo import detect_grid  # noqa: E402
from youber.visuals.models import VisualStyle  # noqa: E402

AUDIO = r"C:\Users\bypau\Music\Distrokid\Pimennys\Wrath.wav"
LRC = ROOT / "scratch" / "wrath_marked.lrc"


def main() -> int:
    document = load_lyrics(LRC, AUDIO)
    text = LRC.read_text(encoding="utf-8-sig")
    markers = sections_from_markers(document, text, duration=264.72)
    measurement = asyncio.run(measure_song(AUDIO, max_seconds=180.0))
    plan = direct_song(
        document, title="Wrath", duration=264.72, energies=measurement.energies or None,
        sections=markers,
    )
    grid = asyncio.run(detect_grid(AUDIO))
    print(f"escenas={len(plan.scenes)} tramos={len(plan.sections)} duracion={plan.duration:.1f}s")
    print("tramos:", [(s.kind.value, round(s.start, 1), round(s.end, 1), s.repetition) for s in plan.sections])

    slots = build_shot_slots(plan, 40, grid=grid)
    report = slot_coverage(slots, plan)
    print(f"\nhuecos={report.slots} generar={report.generated} motivo={report.repeated} ok={report.ok}")
    print(f"cobertura={report.covered:.1f}s de {report.duration:.1f}s | huecos_gaps={report.gaps} solapes={report.overlaps}")
    print(f"escenas {report.scenes_covered}/{report.scenes_total} fuera={report.missing_scenes} stray={report.stray_slots} bad_repeat={report.bad_repeats}")
    print("por tramo:", report.per_section)

    shot_plan = slots_to_shot_plan(plan, slots, style=VisualStyle.DARK, transition=0.0, include_topic=True)
    print(f"\nShotPlan: {len(shot_plan.shots)} planos | prompt[0]={shot_plan.shots[0].prompt[:90]}...")

    print(f"\n{'#':>3} {'inicio':>7} {'fin':>7} {'tramo':<11} {'motivo':>6}  letra")
    for slot in slots:
        marker = "-" if slot.repeat_of is None else f"={slot.repeat_of}"
        print(f"{slot.index:>3} {slot.start:7.2f} {slot.end:7.2f} {slot.section.value:<11} {marker:>6}  {slot.text[:46]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
