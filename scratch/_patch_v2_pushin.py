"""Sustituye 029a y 034a (los dos que fallaron locomocion) por un push-in fijo.

El modelo no sabe trasladar a la figura: se queda caminando en el sitio. En vez
de insistir, esos dos planos pasan a camara con dolly-in lento sobre la misma
pose: el movimiento lo pone la camara (que si sabe hacerlo) y deja de leerse
como treadmill. Se borran los clips y sus entradas del manifiesto para que el
runner los regenere.
"""
from __future__ import annotations

import json
from pathlib import Path

V2 = Path(r"C:\Users\bypau\Music\Gpt\Everything_breaking_down_COMPLETO\Everything_breaking_down\_v2")
PLAN = V2 / "plan.json"
CLIPS = V2 / "clips"

IDENT = (
    "Preserve the exact woman, face, hair, rust blouse, charcoal trousers, jewellery, "
    "lighting and scene geometry visible in the image. "
)

PUSH = (
    "Animate the supplied still as the exact first frame. One continuous photorealistic "
    "1970s cinematic shot, landscape 16:9. " + IDENT +
    "The camera makes one slow, smooth dolly-in toward her over the whole shot: a steady "
    "push forward, no zoom jumps, no shake, no pan, no follow. She holds her pose and only "
    "breathes: one slow blink, a swallow, fabric settling, dust drifting through the amber "
    "light. No dialogue, no singing, no lip sync; mouth closed and lips motionless. "
    "No new people, no new props, no cuts, no text. Preserve natural anatomy."
)

TARGETS = {"029a", "034a"}

doc = json.loads(PLAN.read_text(encoding="utf-8"))
patched = []
for shot in doc["shots"]:
    if shot["id"] in TARGETS:
        shot["mode"] = "static"
        shot["steps"] = 8
        shot["lora"] = 1.0
        shot["prompt"] = PUSH
        patched.append(shot["id"])
        clip = CLIPS / f"clip{shot['id']}.mp4"
        if clip.exists():
            clip.unlink()
        print(f"parcheado {shot['id']}: push-in, clip borrado")
PLAN.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

manifest_path = CLIPS / "manifest.json"
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in TARGETS:
        if key in manifest:
            del manifest[key]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"manifiesto: {len(manifest)} entradas tras limpiar {sorted(TARGETS)}")

print("parcheados:", patched)
