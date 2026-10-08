"""Comprobación rápida del arreglo de ``NightBatch.publish`` (sin GPU)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

spec = importlib.util.spec_from_file_location("night_shots", ROOT / "scratch" / "night_shots.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def make_batch(clips: Path) -> mod.NightBatch:
    batch = object.__new__(mod.NightBatch)
    batch.clips = clips
    batch.dry_run = False
    return batch


with tempfile.TemporaryDirectory() as tmp:
    clips = Path(tmp)
    batch = make_batch(clips)

    # 1) Mismo fichero: el primer intento escribe ya en la ruta final.
    final = batch.clip_path(0)
    final.write_bytes(b"AAA")
    got = batch.publish(final, 0)
    assert got == final, got
    assert final.read_bytes() == b"AAA", "el fichero mismo no debe tocarse"
    print("1) mismo fichero: OK (no copia, sin WinError 32)")

    # 2) Fichero distinto: el reintento a 16 steps se publica en la ruta final.
    r16 = clips / "clip007_720p_r16.mp4"
    r16.write_bytes(b"RETRY")
    got = batch.publish(r16, 7)
    assert got == batch.clip_path(7), got
    assert batch.clip_path(7).read_bytes() == b"RETRY"
    print("2) reintento distinto: OK (copia al nombre definitivo)")

    # 3) Fichero de origen inexistente -> no debe reventar el lote.
    missing = clips / "nope.mp4"
    got = batch.publish(missing, 9)
    print(f"3) origen inexistente: devuelve {got.name!r} (sin excepción)")

print("TODO OK")
