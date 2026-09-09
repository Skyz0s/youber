#!/usr/bin/env python3
"""Driver headless de OpenMontage para youber (contrato docs/MONTAGE.md).

OpenMontage upstream es *agent-driven*: no expone un CLI headless estable.
Este driver implementa el contrato minimo que espera ``youber-produce`` y
produce un montaje real de forma determinista usando las herramientas del
propio checkout de OpenMontage (``tools.video.pexels_video``) + FFmpeg.

Interfaz (contrato con youber.montage.adapter)::

    python montage.py --prompt <texto> --output-dir <dir> \\
        [--pipeline <name>] [--playbook <name>] [--budget-usd <n>] \\
        [--output <fichero.mp4>] [--duration <s>] [--resolution WxH] \\
        [--fps <n>] [--clips <n>]

Modos:
    normal        Busca clips reales en Pexels (requiere PEXELS_API_KEY en el
                  .env del checkout o en el entorno) y los monta con FFmpeg.
    --demo        Genera clips sinteticos con FFmpeg (sin red ni API key),
                  util para validar el pipeline localmente o en CI.
    --self-check  Verifica dependencias y credenciales sin producir nada.

Codigos de salida:
    0  exito
    1  error de ejecucion (red, descarga, ffmpeg...)
    2  error de configuracion (falta PEXELS_API_KEY, ffmpeg, dependencias)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DRIVER_DIR = Path(__file__).resolve().parent

# Palabras vacias (en/es) que no aportan a la busqueda de footage.
_STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "can", "con",
    "create", "de", "del", "do", "el", "en", "for", "from", "generate", "hacer",
    "how", "in", "is", "la", "las", "lo", "los", "make", "making", "montage",
    "of", "on", "or", "para", "que", "se", "the", "to", "tutorial", "un", "una",
    "video", "what", "why", "with", "y",
}

# Keywords "de sabor" por pipeline: complementan al topic real en la busqueda.
_FLAVOR: dict[str, list[str]] = {
    "animation": ["abstract", "animation", "motion"],
    "animated-explainer": ["abstract", "technology", "animation"],
    "avatar-spokesperson": ["person", "studio", "speaking"],
    "character-animation": ["animation", "character", "colorful"],
    "cinematic": ["cinematic", "city", "nature", "dark"],
    "clip-factory": ["abstract", "b-roll", "texture"],
    "documentary": ["cinematic", "city", "aerial", "nature"],
    "documentary-montage": ["cinematic", "city", "aerial", "nature"],
    "explainer": ["abstract", "technology", "animation"],
    "hybrid": [],
    "podcast-repurpose": ["studio", "microphone", "people"],
    "screen-demo": ["code", "programming", "keyboard", "computer"],
    "talking-head": ["person", "studio", "interview"],
    "tutorial": ["code", "programming", "keyboard", "computer"],
}

# Alias youber -> nombre canonico del manifiesto en pipeline_defs/.
_ALIASES = {
    "documentary": "documentary-montage",
    "explainer": "animated-explainer",
    "tutorial": "screen-demo",
}


def _log(msg: str) -> None:
    print(f"[montage] {msg}")


def _err(msg: str) -> None:
    print(f"[montage] ERROR: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entorno
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Carga .env del checkout (PEXELS_API_KEY, etc.) si python-dotenv existe."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(DRIVER_DIR / ".env")
    except Exception:
        pass


def pexels_key() -> str:
    return os.environ.get("PEXELS_API_KEY", "").strip()


def _which(binary: str) -> str | None:
    found = shutil.which(binary)
    return found


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------


def self_check() -> int:
    """Verifica el entorno y devuelve 0 si el driver puede producir footage real."""
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    add("ffmpeg", _which("ffmpeg") is not None, str(_which("ffmpeg") or "no encontrado"))
    add("ffprobe", _which("ffprobe") is not None, str(_which("ffprobe") or "no encontrado"))
    try:
        import requests  # noqa: F401

        add("requests", True, "importable")
    except Exception as exc:
        add("requests", False, f"import fallo: {exc}")
    try:
        import dotenv  # noqa: F401

        add("python-dotenv", True, "importable")
    except Exception as exc:
        add("python-dotenv", False, f"import fallo: {exc}")
    try:
        from tools.video.pexels_video import PexelsVideo  # noqa: F401

        add("tools.video.pexels_video", True, "importable (checkout OpenMontage)")
    except Exception as exc:
        add("tools.video.pexels_video", False, f"import fallo: {exc}")
    key = pexels_key()
    add(
        "PEXELS_API_KEY",
        bool(key),
        "definida (env o .env)" if key else "FALTA: anade PEXELS_API_KEY a .env",
    )

    ok = True
    for name, is_ok, detail in checks:
        marker = "OK " if is_ok else "FAIL"
        print(f"  [{marker}] {name}: {detail}")
        ok = ok and is_ok
    if ok:
        _log("self-check: listo para producir footage real con Pexels")
        return 0
    _log("self-check: faltan componentes (usa --demo para validar sin API key)")
    return 2


# ---------------------------------------------------------------------------
# Keywords / queries
# ---------------------------------------------------------------------------


def normalize_pipeline(pipeline: str) -> str:
    name = pipeline.strip().lower().replace("_", "-")
    return _ALIASES.get(name, name)


def extract_keywords(prompt: str, max_words: int = 4) -> list[str]:
    """Palabras significativas del prompt (las mas largas primero)."""
    tokens = re.findall(r"[a-zA-Z0-9\u00c0-\u024f]+", prompt.lower())
    words = [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]
    unique: list[str] = []
    for word in sorted(words, key=len, reverse=True):
        if word not in unique:
            unique.append(word)
        if len(unique) >= max_words:
            break
    return unique


def build_queries(prompt: str, pipeline: str) -> list[str]:
    """Construye la lista de queries de busqueda para Pexels."""
    canon = normalize_pipeline(pipeline)
    base = extract_keywords(prompt) + list(_FLAVOR.get(canon, []))
    queries = [w for w in base if len(w) >= 3]
    # Intercala topic y flavor para que la rotacion no repita el mismo patron.
    topics = extract_keywords(prompt)
    interleaved: list[str] = []
    i, j = 0, 0
    flavors = [w for w in _FLAVOR.get(canon, []) if len(w) >= 3]
    while i < len(topics) or j < len(flavors):
        if i < len(topics):
            interleaved.append(topics[i])
            i += 1
        if j < len(flavors):
            interleaved.append(flavors[j])
            j += 1
    return interleaved or queries or ["technology", "nature", "city"]


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------


def _run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    ffmpeg = _which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg no esta en PATH")
    proc = subprocess.run([ffmpeg, "-y", *args], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip()[-800:]
        raise RuntimeError(f"ffmpeg fallo (exit {proc.returncode}): {tail or 'sin salida'}")
    return proc


def probe_duration(path: Path) -> float:
    """Duracion en segundos via ffprobe (0.0 si no se puede leer)."""
    ffprobe = _which("ffprobe")
    if ffprobe is None or not path.is_file():
        return 0.0
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def make_synthetic_clip(path: Path, index: int, seconds: float, width: int, height: int, fps: int) -> None:
    """Genera un clip sintetico (testsrc2/smptebars/rgbtestsrc) sin red."""
    sources = [
        f"testsrc2=size={width}x{height}:rate={fps}",
        f"smptebars=size={width}x{height}:rate={fps}",
        f"rgbtestsrc=size={width}x{height}:rate={fps}",
    ]
    source = sources[index % len(sources)]
    _run_ffmpeg(
        [
            "-f", "lavfi", "-i", source,
            "-t", f"{seconds:.2f}",
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p",
            str(path),
        ]
    )


def fetch_pexels_clips(
    queries: list[str],
    count: int,
    out_dir: Path,
    min_seconds: float,
) -> list[tuple[Path, float]]:
    """Descarga clips de Pexels usando la tool real del checkout de OpenMontage."""
    from tools.video.pexels_video import PexelsVideo

    tool = PexelsVideo()
    clips: list[tuple[Path, float]] = []
    attempts = max(count * 3, len(queries) * 2)
    for i in range(attempts):
        query = queries[i % len(queries)]
        target = out_dir / f"pexels_{len(clips):02d}.mp4"
        result = tool.execute(
            {
                "query": query,
                "per_page": 3,
                "page": (i // len(queries)) + 1,
                "orientation": "landscape",
                "size": "medium",
                "min_duration": min_seconds,
                "preferred_quality": "hd",
                "output_path": str(target),
            }
        )
        if not result.success or not target.is_file():
            reason = getattr(result, "error", None) or "sin resultado"
            _log(f"query '{query}' sin clip: {reason}")
            continue
        data = result.data or {}
        duration = float(data.get("duration_seconds") or probe_duration(target))
        clips.append((target, duration))
        _log(f"clip {len(clips)}/{count}: '{query}' -> {target.name} ({duration:.1f}s)")
        if len(clips) >= count:
            break
    return clips


# ---------------------------------------------------------------------------
# Ensamblado
# ---------------------------------------------------------------------------


def normalize_clip(
    src: Path,
    dest: Path,
    seconds: float,
    width: int,
    height: int,
    fps: int,
) -> None:
    """Re-encodea un clip a tamano/fps/format comunes, sin audio, recortado."""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps},format=yuv420p"
    )
    _run_ffmpeg(
        [
            "-i", str(src),
            "-t", f"{seconds:.2f}",
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            str(dest),
        ]
    )


def concat_segments(segments: list[Path], output: Path) -> None:
    """Concatena segmentos normalizados (mismo codec/params) en un solo MP4."""
    n = len(segments)
    cmd: list[str] = []
    for seg in segments:
        cmd += ["-i", str(seg)]
    cmd += ["-filter_complex", f"concat=n={n}:v=1:a=0[v]", "-map", "[v]"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart"]
    cmd += [str(output)]
    _run_ffmpeg(cmd)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "montage"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="montage.py",
        description="Driver headless de OpenMontage para youber (contrato docs/MONTAGE.md)",
    )
    parser.add_argument("--prompt", required=True, help="Tema del video")
    parser.add_argument("--output-dir", required=True, help="Directorio de salida")
    parser.add_argument("--output", default=None, help="Fichero MP4 de salida (default: <slug>.mp4 en output-dir)")
    parser.add_argument("--pipeline", default="hybrid", help="Pipeline (hybrid, screen-demo, documentary-montage, ...)")
    parser.add_argument("--playbook", default=None, help="Playbook de estilo (aceptado por compatibilidad)")
    parser.add_argument("--budget-usd", type=float, default=None, help="Presupuesto USD (aceptado por compatibilidad)")
    parser.add_argument("--duration", type=float, default=30.0, help="Duracion objetivo en segundos (default: 30)")
    parser.add_argument("--resolution", default=None, help="Resolucion WxH (default: 1280x720; demo: 640x360)")
    parser.add_argument("--fps", type=int, default=30, help="FPS objetivo (default: 30)")
    parser.add_argument("--clips", type=int, default=5, help="Numero de clips a montar (default: 5)")
    parser.add_argument("--min-clip-seconds", type=float, default=3.0, help="Duracion minima de clip en Pexels (default: 3)")
    parser.add_argument("--demo", action="store_true", help="Genera clips sinteticos (sin red ni API key)")
    parser.add_argument("--self-check", action="store_true", help="Verifica dependencias y credenciales y sale")
    return parser


def _parse_resolution(value: str | None) -> tuple[int, int]:
    if value:
        match = re.fullmatch(r"(\d+)[xX](\d+)", value.strip())
        if match:
            w = int(match.group(1))
            h = int(match.group(2))
            return (w - w % 2, h - h % 2)  # pares para yuv420p
        _err(f"resolucion invalida '{value}', usando 1280x720")
    return (1280, 720)


def main() -> int:
    args = build_parser().parse_args()
    load_env()

    if args.self_check:
        return self_check()

    pipeline = normalize_pipeline(args.pipeline)
    width, height = _parse_resolution(args.resolution)
    if args.demo and args.resolution is None:
        width, height = 640, 360
    fps = args.fps
    target_duration = max(1.0, args.duration)
    count = max(1, args.clips)

    _log(
        f"pipeline={pipeline} topic='{args.prompt[:80]}' "
        f"duracion={target_duration:.0f}s clips={count} "
        f"resolucion={width}x{height}@{fps}fps"
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{slugify(args.prompt)}.mp4"
    if output_path.suffix.lower() != ".mp4":
        output_path = output_path.with_suffix(".mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="montage_"))
    try:
        # 1) Conseguir clips
        if args.demo:
            clips: list[tuple[Path, float]] = []
            for i in range(count):
                clip = workdir / f"demo_{i:02d}.mp4"
                per = target_duration / count
                make_synthetic_clip(clip, i, per + 0.5, width, height, fps)
                clips.append((clip, per))
                _log(f"clip sintetico {i + 1}/{count} -> {clip.name}")
        else:
            key = pexels_key()
            if not key:
                _err(
                    "PEXELS_API_KEY no configurada. Anadela a .env (junto a este "
                    "driver) o exporta la variable. O usa --demo para validar "
                    "el pipeline sin red."
                )
                return 2
            queries = build_queries(args.prompt, args.pipeline)
            _log(f"queries: {queries}")
            try:
                clips = fetch_pexels_clips(queries, count, workdir, args.min_clip_seconds)
            except Exception as exc:
                _err(f"descarga de clips fallo: {exc}")
                return 1
            if not clips:
                _err("Pexels no devolvio ningun clip para las queries usadas")
                return 1

        # 2) Normalizar (mismo tamano/fps/codec, sin audio) con presupuesto por clip
        per_clip = max(2.0, target_duration / len(clips))
        segments: list[Path] = []
        for i, (clip, clip_duration) in enumerate(clips):
            usable = min(clip_duration, per_clip) if clip_duration > 0 else per_clip
            if usable < 1.0:
                _log(f"clip {i + 1} demasiado corto ({clip_duration:.1f}s), se omite")
                continue
            seg = workdir / f"seg_{len(segments):02d}.mp4"
            normalize_clip(clip, seg, usable, width, height, fps)
            segments.append(seg)
            _log(f"segmento {len(segments)}: {usable:.1f}s")

        if not segments:
            _err("no hay clips validos para montar")
            return 1

        # 3) Concatenar
        concat_segments(segments, output_path)

        # 4) Validar con ffprobe
        duration = probe_duration(output_path)
        if duration <= 0.5 or not output_path.is_file():
            _err(f"el video final no es valido (duracion {duration:.1f}s)")
            return 1

        _log(
            f"OK pipeline={pipeline} clips={len(segments)} "
            f"output={output_path} duration={duration:.1f}s "
            f"resolution={width}x{height} fps={fps}"
        )
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
