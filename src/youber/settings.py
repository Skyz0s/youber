"""Configuración base del framework BARF.

Carga variables de entorno desde `.env` (si existe) y expone la configuración
tipada con pydantic. Todo el framework lee la configuración a través de
`get_settings()` para que sea consistente entre módulos.

La configuración vive dentro del paquete (``youber.settings``) para que el
framework sea instalable y portable; los recursos (``config/user_agents.json``)
y el ``.env`` se resuelven contra la raíz del proyecto.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field, field_validator

# Raíz del proyecto (src/youber/settings.py -> 3 niveles arriba: projects/barf)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Cargar variables del fichero .env si existe (no falla si no está)
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseModel):
    """Configuración base del framework."""

    browser_headless: bool = Field(
        default=False,
        description="Ejecutar el navegador sin interfaz gráfica.",
    )
    browser_timeout: int = Field(
        default=30_000,
        description="Timeout por defecto de las operaciones de Playwright (ms).",
    )
    log_level: str = Field(
        default="INFO",
        description="Nivel de log: DEBUG, INFO, WARNING, ERROR.",
    )
    user_agent_list: Path = Field(
        default=Path("./config/user_agents.json"),
        description="Ruta al fichero JSON con user agents para estudios de navegador.",
    )

    @field_validator("user_agent_list", mode="after")
    @classmethod
    def _resolve_relative_path(cls, value: Path) -> Path:
        """Resuelve rutas relativas contra la raíz del proyecto."""
        if not value.is_absolute():
            return PROJECT_ROOT / value
        return value

    @classmethod
    def from_env(cls) -> Settings:
        """Construye la configuración desde variables de entorno (con defaults)."""

        def _bool(value: str) -> bool:
            return value.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            browser_headless=_bool(os.getenv("BROWSER_HEADLESS", "false")),
            browser_timeout=int(os.getenv("BROWSER_TIMEOUT", "30000")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            user_agent_list=Path(os.getenv("USER_AGENT_LIST", "./config/user_agents.json")),
        )


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (una única instancia por proceso)."""
    return Settings.from_env()


def configure_logging() -> None:
    """Configura loguru con el nivel de log indicado en la configuración."""
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        level=get_settings().log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan> - <level>{message}</level>"
        ),
    )
