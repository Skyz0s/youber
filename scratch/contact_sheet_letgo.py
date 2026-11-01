"""Hoja de contactos de los 49 PNG de **If I Let Go** con id y minuto acumulado.

Uso:
    python scratch/contact_sheet_letgo.py [--cols 6] [--out ruta.png]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT = Path(r"C:\Users\bypau\Videos\youber\IfILetGo\If_I_Let_Go")
STILLS = PROJECT / "stills"
PLAN = PROJECT / "prompts_video.json"
OUT = PROJECT / "montage" / "contact_sheet.png"

TW, TH = 384, 216
LABEL = 26
PAD = 8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cols", type=int, default=7)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    doc = json.loads(PLAN.read_text(encoding="utf-8"))
    shots = sorted(doc["shots"], key=lambda s: s["id"])
    cols = args.cols
    rows = (len(shots) + cols - 1) // cols
    cw, ch = TW + PAD, TH + LABEL + PAD
    sheet = Image.new("RGB", (cols * cw + PAD, rows * ch + PAD), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 20)
    except OSError:
        font = ImageFont.load_default()

    clock = 0.0
    for i, shot in enumerate(shots):
        r, c = divmod(i, cols)
        x = PAD + c * cw
        y = PAD + r * ch
        img = Image.open(STILLS / Path(shot["image"]).name).convert("RGB")
        img.thumbnail((TW, TH), Image.LANCZOS)
        sheet.paste(img, (x, y))
        stamp = f"{int(clock) // 60:01d}:{clock % 60:04.1f}"
        draw.text((x + 4, y + TH + 2), f"{shot['id']}  {stamp}", fill=(255, 235, 130), font=font)
        clock += float(shot.get("frames", 121)) / float(shot.get("fps", 24) or 24)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    print(f"{out} ({sheet.width}x{sheet.height}, {out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
