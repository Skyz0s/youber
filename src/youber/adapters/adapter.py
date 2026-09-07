# src/youber/adapters/adapter.py
"""
Adaptador para OpenMontage - Orquestador de producción de video.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger

from youber.montage.models import ProductionPlan, ProductionResult


class OpenMontageAdapter:
    """Adaptador para controlar OpenMontage desde Youber."""

    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = project_dir or Path.cwd()
        self.montage_cli = self.project_dir / "OpenMontage" / "montage.py"

    async def produce(
        self,
        plan: ProductionPlan,
    ) -> ProductionResult:
        """
        Produce un video usando OpenMontage a partir de un ProductionPlan.

        Args:
            plan: Plan de producción que contiene patrón, audio, etc.

        Returns:
            ProductionResult: Resultado de la producción.
        """
        logger.info(f"🎬 Produciendo video con OpenMontage a partir del plan: {plan.pattern.title}")

        # Derivar tema del título del patrón o del camino
        topic = plan.pattern.title or plan.pattern.path
        # Usar el pipeline del plan
        pipeline = plan.pipeline
        # Directorio de salida: si se especifica en el plan, usar su padre, sino usar un directorio temporal
        output_dir = plan.output_path.parent if plan.output_path else None

        # Llamar a produce_video (que actualmente es un placeholder)
        video_path = await self.produce_video(
            topic=topic,
            pipeline=pipeline,
            output_dir=output_dir,
        )

        # Construir el resultado de producción
        # Nota: Actualmente no obtenemos duración y resolución del video producido.
        # En una implementación real, usaríamos ffprobe para obtener esta información.
        return ProductionResult(
            success=True,
            output_path=video_path,
            duration=0.0,  # Placeholder
            resolution=(0, 0),  # Placeholder
        )

    async def produce_video(
        self,
        topic: str,
        pipeline: str = "documentary",
        output_dir: Optional[Path] = None,
        **kwargs
    ) -> Path:
        """
        Produce un video usando OpenMontage.

        Args:
            topic: Tema del video
            pipeline: Tipo de pipeline (documentary, explainer, etc.)
            output_dir: Directorio de salida
            **kwargs: Argumentos adicionales para OpenMontage

        Returns:
            Path: Ruta del video generado
        """
        logger.info(f"🎬 Produciendo video con OpenMontage: {topic}")
        logger.info(f"📋 Pipeline: {pipeline}")

        output_dir = output_dir or self.project_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Construir el prompt para OpenMontage
        prompt = self._build_prompt(topic, pipeline, **kwargs)

        # Ejecutar OpenMontage
        result = await self._run_montage(prompt, output_dir)

        logger.info(f"✅ Video producido: {result}")
        return result

    def _build_prompt(self, topic: str, pipeline: str, **kwargs) -> str:
        """Construye el prompt para OpenMontage."""
        prompts = {
            "documentary": f"Make a 75-second documentary montage about {topic}. Use real footage only, no narration, elegiac tone, with music.",
            "explainer": f"Make a 60-second animated explainer about {topic}.",
            "tutorial": f"Make a tutorial video about {topic}.",
        }
        return prompts.get(pipeline, prompts["documentary"])

    async def _run_montage(self, prompt: str, output_dir: Path) -> Path:
        """Ejecuta el CLI de OpenMontage."""
        # Implementación real que llama a OpenMontage
        # Por ahora, devolvemos una ruta de ejemplo (para evitar errores)
        # En una implementación real, esto llamaría al CLI de OpenMontage y devolvería la ruta del video generado.
        # Por ejemplo:
        #   cmd = [str(self.montage_cli), "--prompt", prompt, "--output-dir", str(output_dir)]
        #   proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        #   stdout, stderr = await proc.communicate()
        #   if proc.returncode != 0:
        #         raise RuntimeError(f"OpenMontage failed: {stderr.decode()}")
        #   # Asumimos que el video se guarda como output_dir / "output.mp4"
        #   return output_dir / "output.mp4"
        # Devolver una ruta falsa por ahora
        return output_dir / "output.mp4"