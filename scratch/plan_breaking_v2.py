"""Plan v2 de 'Everything is breaking down': 69 planos de ~4 s (rejilla musical).

Cambios frente al v1 (35 planos de 8 s):

- 97 frames por plano (4,04 s a 24 fps) en vez de 193 (8,04 s). El modelo
  (Wan 2.2 TI2V-5B) esta entrenado a 121 frames; a 193 se sale de rango y
  entra en modo "balanceo" (caminar en el sitio).
- 8 beats a 117,6 bpm = 4,08 s: el corte cae en la rejilla de la cancion.
- Cada still da dos planos: el encuadre completo y un encuadre derivado
  (punch-in o recorte de detalle). Mas cobertura sin regenerar imagenes.
- Prompts centrados en lo que el modelo si sabe hacer: camara fija y
  micro-movimiento. Solo dos planos piden locomocion y se han reescrito para
  que el desplazamiento sea medible (alejarse / cruzar el umbral).

Uso:
    python scratch/plan_breaking_v2.py            # escribe _v2/plan.json + stills
    python scratch/plan_breaking_v2.py --dry-run  # solo imprime el plan
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youber.genvideo.framing import detail, punch_in  # noqa: E402

SRC = Path(
    r"C:\Users\bypau\Music\Gpt\Everything_breaking_down_COMPLETO\Everything_breaking_down"
)
OUT = SRC / "_v2"
STILLS = OUT / "stills"
PLAN = OUT / "plan.json"

WIDTH, HEIGHT, FPS = 1280, 704, 24
#: 97 frames = 4,0417 s; 68 planos + uno de 104 frames = 279,16 s exactos.
FRAMES = 97
LAST_FRAMES = 104

IDENT = (
    "Preserve the exact woman, face, hair, rust blouse, charcoal trousers, jewellery, "
    "lighting and scene geometry visible in the image. "
)
NEGATIVE = (
    "walking in place, treadmill, sliding feet, skating feet, floating feet, frozen legs, "
    "static pose, idle standing, camera follows, camera pans away, morphing face, "
    "identity change, wardrobe change, extra fingers, extra limbs, warped walls, "
    "text, subtitles, logos, camera shake, sudden zoom, flames, explosions, heavy debris"
)

STATIC = (
    "Animate the supplied still as the exact first frame. One continuous photorealistic "
    "1970s cinematic shot, landscape 16:9. " + IDENT +
    "The camera is locked off on a tripod and never moves: no pan, no zoom, no push-in, "
    "no shake, no handheld sway. Only quiet natural micro-motion: slow nasal breathing, "
    "one slow blink, fabric settling, fine dust drifting through the light, faint shimmer "
    "on the walls. She keeps her position and her pose. No dialogue, no singing, no "
    "whispering and no lip sync; mouth closed and lips motionless. No new people, no new "
    "props, no cuts, no text. Preserve natural anatomy."
)

DETAIL_SHOT = (
    "Animate the supplied still as the exact first frame. One continuous photorealistic "
    "1970s cinematic insert, landscape 16:9. Preserve the exact materials, colours, "
    "lighting and geometry visible in the image. "
    "The camera is locked off on a tripod and never moves: no pan, no zoom, no push-in. "
    "Only quiet natural micro-motion: dust drifting across the surfaces, faint shifts of "
    "light and shadow, tiny movement of fabric fibres, the amber light breathing very "
    "slightly. Nothing else in the frame moves. No new objects, no cuts, no text."
)

AWAY = (
    "Animate the supplied still as the exact first frame. One continuous photorealistic "
    "1970s cinematic shot, landscape 16:9. " + IDENT +
    "The camera stays locked off on a tripod: no pan, no zoom, no follow, no shake. "
    "She walks away from the camera down the corridor in three slow deliberate steps: the "
    "heel plants first, the weight rolls forward, the hips shift and her arms swing at her "
    "sides; one foot only lifts after the other is planted. The distance between her and "
    "the camera grows and she becomes smaller in the frame, while the walls, the two small "
    "frames and the far door stay exactly where they are. Dust drifts in the light. "
    "No dialogue, no lip sync; mouth closed. Preserve natural anatomy."
)

LATERAL = (
    "Animate the supplied still as the exact first frame. One continuous photorealistic "
    "1970s cinematic shot, landscape 16:9. " + IDENT +
    "The camera stays locked off on a tripod: no pan, no zoom, no follow, no shake. "
    "She steps across the threshold from left to right, one deliberate step: the front boot "
    "lands, the weight transfers, the back boot lifts and follows. Her body travels across "
    "the frame while the door, the doorframe and the corridor stay fixed in place. Warm "
    "amber light spills from the room and moves across her as she crosses. "
    "No dialogue, no lip sync; mouth closed. Preserve natural anatomy."
)

#: Plano -> (modo, steps, lora)
MOTION = {
    29: ("away", 12, 0.65),
    34: ("lateral", 12, 0.65),
}

#: Planos de detalle (inserts) que ya son primerisimos planos: micro-movimiento.
INSERTS = {13, 18, 21, 27, 31}

#: Centro y zoom del encuadre derivado segun lo que cuenta cada plano.
CROPS: dict[int, tuple[tuple[float, float], float]] = {
    3: ((0.5, 0.42), 1.7),    # cara
    6: ((0.62, 0.55), 2.0),   # picaporte de la puerta
    11: ((0.5, 0.40), 1.7),   # cara, ojos cerrados
    13: ((0.55, 0.45), 2.0),  # grieta
    18: ((0.5, 0.62), 2.0),   # mano en el brazo
    21: ((0.62, 0.5), 2.2),   # picaporte
    25: ((0.55, 0.5), 1.9),   # grieta / reconocimiento
    26: ((0.5, 0.5), 1.6),    # cuadro torcido
    27: ((0.5, 0.62), 2.0),   # manos abiertas
    31: ((0.6, 0.55), 2.0),   # mano en el picaporte
    33: ((0.5, 0.42), 1.7),   # cara en el umbral
    34: ((0.5, 0.8), 2.0),    # pies cruzando
    35: ((0.5, 0.45), 1.6),   # cara dentro
}


def build() -> list[dict]:
    doc = json.loads((SRC / "instrucciones.json").read_text(encoding="utf-8"))
    shots = sorted(doc["shots"], key=lambda s: int(s["id"]))
    plan: list[dict] = []

    for shot in shots:
        sid = int(shot["id"])
        title = shot.get("title_es", "")
        section = shot.get("suggested_section", "")
        mode, steps, lora = MOTION.get(sid, ("static", 8, 1.0))
        if mode == "static" and sid in INSERTS:
            prompt = DETAIL_SHOT
        elif mode == "away":
            prompt = AWAY
        elif mode == "lateral":
            prompt = LATERAL
        else:
            prompt = STATIC

        plan.append({
            "id": f"{sid:03d}a",
            "still": str(SRC / shot["image"]),
            "crop": "full",
            "mode": mode,
            "steps": steps,
            "lora": lora,
            "frames": FRAMES,
            "title": title,
            "section": section,
            "prompt": prompt,
        })

        if sid == 4:  # plano sin persona: no necesita cobertura
            continue
        center, zoom = CROPS.get(sid, ((0.5, 0.5), 1.35))
        if (center, zoom) == ((0.5, 0.5), 1.35):
            crop_kind = "punch"
            box = {"factor": 1.35}
            derived_prompt = DETAIL_SHOT
        else:
            crop_kind = "detail"
            box = {"center": center, "zoom": zoom}
            derived_prompt = DETAIL_SHOT
        plan.append({
            "id": f"{sid:03d}b",
            "still": str(STILLS / f"{sid:03d}b.png"),
            "source": str(SRC / shot["image"]),
            "crop": crop_kind,
            "crop_args": box,
            "mode": "static",
            "steps": 8,
            "lora": 1.0,
            "frames": FRAMES,
            "title": title,
            "section": section,
            "prompt": derived_prompt,
        })

    # el ultimo plano absorbe el resto para cuadrar la cancion
    plan[-1]["frames"] = LAST_FRAMES
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    plan = build()
    total = sum(s["frames"] for s in plan) / FPS
    print(f"plan: {len(plan)} planos | {total:.3f}s | 24 fps")
    for s in plan:
        crop = s["crop"] if s["crop"] == "full" else f"{s['crop']}{s.get('crop_args')}"
        print(f"  {s['id']}  {s['frames']:3d}f  {s['mode']:8s} steps {s['steps']:2d} "
              f"lora {s['lora']:.2f}  {crop:28s} {s['title'][:34]}")
    if a.dry_run:
        return 0

    STILLS.mkdir(parents=True, exist_ok=True)
    for s in plan:
        if s["crop"] == "full":
            continue
        src = Path(s["source"])
        out = Path(s["still"])
        if s["crop"] == "punch":
            punch_in(src, out, float(s["crop_args"].get("factor", 1.35)))
        else:
            detail(src, out, tuple(s["crop_args"]["center"]), float(s["crop_args"]["zoom"]))
    OUT.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps({
        "song_seconds": 279.16,
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "negative": NEGATIVE,
        "shots": plan,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nescrito: {PLAN}")
    print(f"stills derivados: {len(list(STILLS.glob('*.png')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
