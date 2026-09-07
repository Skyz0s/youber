"""CLI para producción de vídeo con OpenMontage (youber-produce)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from youber.montage.adapter import OpenMontageAdapter
from youber.montage.models import (
    AudioSource,
    ProductionMode,
    ProductionPlan,
)
from youber.montage.pattern_analyzer import PatternAnalyzer


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos para youber-produce."""
    parser = argparse.ArgumentParser(
        prog="youber-produce",
        description="Produce un vídeo nuevo a partir de un patrón (YouTube o local) + audio propio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  youber-produce --pattern https://youtu.be/abc123 --mood epica
  youber-produce --pattern video.mp4 --audio musica.mp3 --mode remix
  youber-produce --pattern https://youtu.be/abc123 --mode inspired --title "Mi Remix"
        """,
    )

    # Entrada: patrón (obligatorio)
    parser.add_argument(
        "--pattern",
        required=True,
        help="Vídeo patrón: URL de YouTube (https://youtu.be/...) o archivo local (video.mp4)",
    )

    # Modo de producción
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ProductionMode],
        default=ProductionMode.HYBRID.value,
        help="Modo de producción: remix (reutiliza footage), inspired (solo estructura), hybrid (mezcla)",
    )

    # Audio: mutuamente excluyentes (mood XOR audio)
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument(
        "--mood",
        help="Estado de ánimo para buscar en catálogo youber.music (ej: epica, chill, corporativo)",
    )
    audio_group.add_argument(
        "--audio",
        help="Archivo de audio local arbitrario (MP3, WAV, etc.)",
    )

    # Ajustes de audio
    parser.add_argument(
        "--volume",
        type=float,
        default=1.0,
        help="Volumen de la pista de audio (0.0-2.0)",
    )
    parser.add_argument(
        "--audio-start",
        type=float,
        default=0.0,
        help="Offset de inicio en la pista de audio (segundos)",
    )
    audio_loop = audio_group.add_mutually_exclusive_group()
    audio_loop.add_argument(
        "--loop",
        action="store_true",
        help="Repetir audio si es más corto que el vídeo",
    )
    audio_loop.add_argument(
        "--no-loop",
        action="store_false",
        dest="loop",
        help="No repetir audio (default)",
    )
    parser.set_defaults(loop=False)

    # Salida
    parser.add_argument(
        "-o", "--output",
        help="Ruta del archivo de salida (MP4). Si no se especifica, usa temp y muestra la ruta",
    )
    parser.add_argument(
        "--title",
        help="Título del vídeo generado",
    )
    parser.add_argument(
        "--description",
        help="Descripción del vídeo generado",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        help="Tags para el vídeo (separados por espacio)",
    )

    # Configuración OpenMontage
    parser.add_argument(
        "--pipeline",
        default="hybrid",
        help="Pipeline de OpenMontage a usar (default: hybrid)",
    )
    parser.add_argument(
        "--playbook",
        default="clean-professional",
        help="Playbook de estilo (default: clean-professional)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=2.0,
        help="Presupuesto máximo USD (default: 2.0)",
    )

    # Objetivo (opcional, si se quiere forzar duración/resolución)
    parser.add_argument(
        "--duration",
        type=float,
        help="Duración objetivo en segundos (default: duración del patrón)",
    )
    parser.add_argument(
        "--resolution",
        help="Resolución objetivo WxH (ej: 1920x1080)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="FPS objetivo (default: 30)",
    )

    # YouTube API key (opcional, para modo API)
    parser.add_argument(
        "--api-key",
        help="YouTube Data API key (usa variable de entorno YOUTUBE_API_KEY si no se pasa)",
    )

    # Verbosidad
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Aumenta verbosidad (-v, -vv)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Solo salida esencial",
    )

    return parser


def _parse_resolution(res_str: str | None) -> tuple[int, int] | None:
    if not res_str:
        return None
    try:
        w, h = res_str.lower().split("x")
        return (int(w), int(h))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Resolución inválida: {res_str}. Usa WxH (ej: 1920x1080)"
        ) from None


async def _run_produce(args: argparse.Namespace) -> int:
    """Ejecuta la producción completa."""
    # Configurar logging
    log_level = "WARNING"
    if args.verbose >= 2:
        log_level = "DEBUG"
    elif args.verbose >= 1:
        log_level = "INFO"
    if args.quiet:
        log_level = "ERROR"
    logger.remove()
    logger.add(sys.stderr, level=log_level)

    # Validar patrón
    pattern_input = args.pattern.strip()
    if not pattern_input:
        logger.error("--pattern es obligatorio")
        return 1

    # Analizar patrón
    logger.info(f"Analizando patrón: {pattern_input}")
    analyzer = PatternAnalyzer(api_key=args.api_key)
    try:
        pattern_spec = await analyzer.analyze(pattern_input)
    except Exception as e:
        logger.error(f"Error analizando patrón: {e}")
        return 1

    logger.info(
        f"Patrón: {pattern_spec.title} | {pattern_spec.duration:.1f}s | "
        f"{pattern_spec.resolution[0]}x{pattern_spec.resolution[1]} @ {pattern_spec.fps}fps | "
        f"audio={pattern_spec.has_audio} | escenas={len(pattern_spec.scene_changes)} | "
        f"picos_audio={len(pattern_spec.audio_peaks)}"
    )

    # Resolver audio
    audio = AudioSource(
        track_id=None,  # Se resolverá en adapter si se pasa mood
        mood=args.mood,
        file_path=Path(args.audio) if args.audio else None,
        volume=args.volume,
        start_at=args.audio_start,
        loop=args.loop,
    )

    # Resolución objetivo
    target_res = _parse_resolution(args.resolution)
    if target_res is None:
        target_res = pattern_spec.resolution

    # Plan de producción
    plan = ProductionPlan(
        pattern=pattern_spec,
        mode=ProductionMode(args.mode),
        audio=audio,
        target_duration=args.duration,
        target_resolution=target_res,
        target_fps=args.fps,
        output_path=Path(args.output) if args.output else None,
        pipeline=args.pipeline,
        playbook=args.playbook,
        budget_usd=args.budget,
        title=args.title,
        description=args.description,
        tags=args.tags,
    )

    # Ejecutar adapter
    logger.info(f"Ejecutando pipeline {plan.pipeline} con playbook {plan.playbook}...")
    adapter = OpenMontageAdapter()
    try:
        result = await adapter.produce(plan)
    except Exception as e:
        logger.exception(f"Error en adapter: {e}")
        return 1

    if not result.success:
        logger.error(f"Producción falló: {result.error}")
        return 1

    # Éxito
    out_path = result.output_path
    if out_path:
        logger.success(
            f"✅ Vídeo generado: {out_path} | "
            f"{result.duration:.1f}s | {result.resolution[0]}x{result.resolution[1]}"
        )
        if not args.output:
            print(str(out_path))  # Para piping en scripts
    else:
        logger.warning("Producción reportada como exitosa pero sin archivo de salida")
        return 1

    return 0


def main() -> int:
    """Entry point para setuptools."""
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run_produce(args))


if __name__ == "__main__":
    sys.exit(main())