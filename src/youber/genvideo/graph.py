"""Grafo de ComfyUI (formato API) para Wan 2.2 TI2V-5B.

Traduce un :class:`~youber.genvideo.models.ClipRequest` al JSON que espera
``POST /prompt`` de ComfyUI: cargadores (UNET, CLIP, VAE), la LoRA Turbo
opcional, los dos ``CLIPTextEncode``, el muestreo SD3, el latente de imagen a
vídeo, el ``KSampler`` y la decodificación del VAE (troceada por defecto).

El grafo es el mismo que se usó en el spike, con los nodos numerados y
titulados para poder leer los errores del servidor sin adivinar.
"""

from __future__ import annotations

from itertools import count
from typing import Any

from youber.genvideo.models import ClipRequest

#: Nodo que escribe el vídeo en disco; de sus salidas se saca el fichero.
SAVE_NODE = "SaveVideo"


def build_graph(request: ClipRequest, *, filename_prefix: str) -> dict[str, Any]:
    """Construye el grafo API de un clip.

    Args:
        request: Clip a generar (prompt, seed y configuración).
        filename_prefix: Prefijo con el que ComfyUI guarda el resultado.

    Returns:
        El grafo en formato API (``{id_nodo: {"class_type", "inputs"}}``).
    """
    config = request.config
    graph: dict[str, Any] = {}
    ids = count(1)

    def add(kind: str, inputs: dict[str, Any], title: str | None = None) -> str:
        node_id = str(next(ids))
        graph[node_id] = {
            "class_type": kind,
            "inputs": inputs,
            "_meta": {"title": title or kind},
        }
        return node_id

    unet = add("UNETLoader", {"unet_name": config.unet_name, "weight_dtype": config.weight_dtype})
    model_ref: list[Any] = [unet, 0]
    if config.lora_name:
        model_ref = [
            add(
                "LoraLoaderModelOnly",
                {
                    "model": model_ref,
                    "lora_name": config.lora_name,
                    "strength_model": config.lora_strength,
                },
                title="LoRA Turbo",
            ),
            0,
        ]

    clip = add("CLIPLoader", {
        "clip_name": config.clip_name,
        "type": "wan",
        "device": "default",
    })
    vae = add("VAELoader", {"vae_name": config.vae_name})
    positive = add("CLIPTextEncode", {"text": request.prompt, "clip": [clip, 0]}, title="prompt")
    negative = add(
        "CLIPTextEncode",
        {"text": request.negative_prompt, "clip": [clip, 0]},
        title="prompt negativo",
    )
    sampling = add("ModelSamplingSD3", {"model": model_ref, "shift": config.shift})
    latent = add(
        "Wan22ImageToVideoLatent",
        {
            "vae": [vae, 0],
            "width": config.width,
            "height": config.height,
            "length": config.frames,
            "batch_size": 1,
        },
    )
    sampler = add(
        "KSampler",
        {
            "model": [sampling, 0],
            "seed": request.seed,
            "steps": config.steps,
            "cfg": config.cfg,
            "sampler_name": config.sampler_name,
            "scheduler": config.scheduler,
            "positive": [positive, 0],
            "negative": [negative, 0],
            "latent_image": [latent, 0],
            "denoise": 1.0,
        },
    )
    samples: list[Any] = [sampler, 0]
    if config.latent_multiplier != 1.0:
        samples = [
            add("LatentMultiply", {"samples": samples, "multiplier": config.latent_multiplier}),
            0,
        ]
    if config.tiled_vae:
        decoded = add(
            "VAEDecodeTiled",
            {
                "samples": samples,
                "vae": [vae, 0],
                "tile_size": config.tile_size,
                "overlap": config.tile_overlap,
                "temporal_size": config.temporal_size,
                "temporal_overlap": config.temporal_overlap,
            },
            title="VAE troceado",
        )
    else:
        decoded = add("VAEDecode", {"samples": samples, "vae": [vae, 0]})
    video = add("CreateVideo", {"images": [decoded, 0], "fps": config.fps})
    add(
        SAVE_NODE,
        {
            "video": [video, 0],
            "filename_prefix": filename_prefix,
            "format": "auto",
            "codec": "auto",
        },
    )
    return graph


def save_node_id(graph: dict[str, Any]) -> str | None:
    """Identificador del nodo que guarda el vídeo (o ``None`` si no está)."""
    for node_id, node in graph.items():
        if node.get("class_type") == SAVE_NODE:
            return node_id
    return None
