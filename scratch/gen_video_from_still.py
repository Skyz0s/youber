"""Piloto img->video: anima un still con Wan 2.2 TI2V-5B (ComfyUI).

Sube la imagen a ComfyUI, monta el grafo de imagen->video (start_image en
Wan22ImageToVideoLatent) y descarga el MP4 resultante.

Uso:
    python scratch/gen_video_from_still.py --image still.png --motion-file mov.txt \
        --out clip.mp4 --width 832 --height 480 --frames 121 --steps 8
"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

import httpx

SERVER = "http://127.0.0.1:8188"
UNET = "wan2.2_ti2v_5B_fp16.safetensors"
LORA = "wan22_ti2v_5b_turbo_lora_rank64_fp16.safetensors"
CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan2.2_vae.safetensors"


def upload_image(c: httpx.Client, path: Path) -> str:
    with path.open("rb") as fh:
        files = {"image": (path.name, fh, "image/png")}
        data = {"type": "input", "overwrite": "true"}
        r = c.post(f"{SERVER}/upload/image", files=files, data=data)
    r.raise_for_status()
    return str(r.json()["name"])


def build_graph(a: argparse.Namespace, image_name: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": a.lora},
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP, "type": "wan", "device": "default"},
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": a.motion, "clip": ["3", 0]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": a.negative, "clip": ["3", 0]},
        },
        "7": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": a.shift}},
        "8": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "9": {
            "class_type": "Wan22ImageToVideoLatent",
            "inputs": {
                "vae": ["4", 0],
                "width": a.width,
                "height": a.height,
                "length": a.frames,
                "batch_size": 1,
                "start_image": ["8", 0],
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["7", 0],
                "seed": a.seed,
                "steps": a.steps,
                "cfg": a.cfg,
                "sampler_name": a.sampler,
                "scheduler": a.scheduler,
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["9", 0],
                "denoise": 1.0,
            },
        },
        "11": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["10", 0],
                "vae": ["4", 0],
                "tile_size": a.tile_size,
                "overlap": a.tile_overlap,
                "temporal_size": a.temporal_size,
                "temporal_overlap": a.temporal_overlap,
            },
        },
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": a.fps}},
        "13": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["12", 0],
                "filename_prefix": a.prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }


def find_video(entry: dict) -> dict | None:
    for node_out in (entry.get("outputs") or {}).values():
        if not isinstance(node_out, dict):
            continue
        for value in node_out.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(
                        (".mp4", ".mkv", ".webm")
                    ):
                        return item
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--motion", default=None)
    ap.add_argument("--motion-file", default=None)
    ap.add_argument("--negative", default="text, watermark, cuts, horror creatures, glitch effects, cartoon, cgi, oversaturated, blurry, distorted anatomy, extra limbs, jpeg artifacts, flicker, static image, still frame, walking in place, treadmill, sliding feet, skating feet, floating feet, frozen legs, camera follows")
    ap.add_argument("--negative-file", default=None)
    ap.add_argument("--out", default="clip.mp4")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=480)
    #: 121 frames = 5,04 s es el rango nativo del 5B. Por encima de ~161 el
    #: modelo se sale de distribucion y empieza a balancerse en el sitio.
    ap.add_argument("--frames", type=int, default=121)
    ap.add_argument("--allow-long", action="store_true",
                    help="permite >161 frames (fuera del rango entrenado)")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--steps", type=int, default=8)
    #: El VAE va por teselas (VRAM justa): tiles pequenos dejan juntas visibles
    #: ("velo"/grano sobre las paredes lisas). 512/128 es el defecto bueno; solo
    #: bajarlo si no cabe en VRAM.
    ap.add_argument("--tile-size", type=int, default=512)
    ap.add_argument("--tile-overlap", type=int, default=128)
    ap.add_argument("--temporal-size", type=int, default=16)
    ap.add_argument("--temporal-overlap", type=int, default=4)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--shift", type=float, default=8.0)
    ap.add_argument("--lora", type=float, default=1.0)
    ap.add_argument("--sampler", default="euler")
    ap.add_argument("--scheduler", default="simple")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prefix", default="youber_i2v")
    ap.add_argument("--timeout", type=float, default=1800.0)
    a = ap.parse_args()

    if a.motion_file:
        a.motion = Path(a.motion_file).read_text(encoding="utf-8")
    if a.negative_file:
        a.negative = Path(a.negative_file).read_text(encoding="utf-8")
    if not a.motion:
        ap.error("hace falta --motion o --motion-file")
    if a.frames > 161 and not a.allow_long:
        ap.error(
            f"{a.frames} frames ({a.frames / a.fps:.2f}s) esta fuera del rango nativo "
            "(121 = 5,04s). Usa como maximo 161 o pasa --allow-long a sabiendas."
        )
    a.motion = " ".join(a.motion.split())

    image = Path(a.image)
    with httpx.Client(timeout=httpx.Timeout(120.0)) as c:
        c.get(f"{SERVER}/system_stats").raise_for_status()
        name = upload_image(c, image)
        print(f"imagen subida: {name}")
        graph = build_graph(a, name)
        r = c.post(f"{SERVER}/prompt", json={"prompt": graph, "client_id": str(uuid.uuid4())})
        if r.status_code != 200:
            print("ERROR /prompt:", r.status_code, r.text[:900])
            return 2
        pid = r.json()["prompt_id"]
        print(f"prompt_id={pid} (encolado)")
        started = time.time()
        while True:
            h = c.get(f"{SERVER}/history/{pid}").json()
            if pid in h:
                entry = h[pid]
                break
            if time.time() - started > a.timeout:
                print("TIMEOUT")
                return 3
            time.sleep(5)
        status = (entry.get("status") or {}).get("status_str")
        print(f"estado={status} en {time.time() - started:.0f}s")
        vid = find_video(entry)
        if vid is None:
            print("sin vídeo en la salida:", str(entry)[:900])
            return 4
        params = {"filename": vid["filename"], "subfolder": vid.get("subfolder", ""), "type": vid.get("type", "output")}
        data = c.get(f"{SERVER}/view", params=params)
        data.raise_for_status()
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data.content)
        print(f"guardado: {out} ({len(data.content) / 1024 / 1024:.1f} MB) <- {vid['filename']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
