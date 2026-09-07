# src/youber/adapters/adapter.py
"""
Adaptador para OpenMontage - Orquestador de producción de video.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger

class OpenMontageAdapter:
    """Adaptador para controlar OpenMontage desde Youber."""

    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = project_dir or Path.cwd()
        self.montage_cli = self.project_dir / "OpenMontage" / "montage.py"

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
        pass