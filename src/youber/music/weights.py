"""Pesos del selector de canciones, aprendibles desde el decision journal.

El scoring de :mod:`youber.music.selector` usa unos pesos fijos (documentados
para que la elección sea auditable). Este módulo los encapsula en
:class:`SelectionWeights`, que puede:

- quedarse en los **valores por defecto** (comportamiento de siempre), o
- venir **aprendido** de las métricas reales del canal
  (:mod:`youber.journal.learn`), reescalando cada señal según cuánto
  correlaciona con el resultado.

Es puramente local y determinista: no llama a nada externo ni usa modelos.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

#: Señales del scoring, en el orden en que se documentan.
SIGNAL_NAMES: tuple[str, ...] = (
    "theme",
    "sentiment",
    "mood",
    "keyword",
    "favorite",
    "usage",
)

#: Pesos por defecto (los de siempre; el «prior» antes de mirar datos).
DEFAULT_WEIGHTS: dict[str, float] = {
    "theme": 3.0,  # por tema compartido (× peso del vídeo × peso de la letra)
    "sentiment": 1.5,  # sentimiento de la letra == sentimiento del vídeo
    "mood": 2.0,  # mood etiquetado en la pista == mood del vídeo
    "keyword": 0.5,  # por palabra del vídeo presente en título/artista/género
    "favorite": 0.5,  # las favoritas del usuario pesan un poco más
    "usage": 0.1,  # penalización por uso previo (rota las canciones)
}

#: Etiquetas legibles de cada señal (para informes y consola).
SIGNAL_LABELS: dict[str, str] = {
    "theme": "Afinidad temática",
    "sentiment": "Sentimiento",
    "mood": "Estado de ánimo",
    "keyword": "Palabras clave",
    "favorite": "Favorita",
    "usage": "Rotación (penalización por uso)",
}

#: Variable de entorno para apuntar a otro fichero de pesos.
WEIGHTS_ENV = "YOUBER_WEIGHTS"

#: Ruta por defecto del fichero de pesos aprendidos.
DEFAULT_WEIGHTS_PATH = Path.home() / ".youber" / "selection_weights.json"


def default_weights_path() -> Path:
    """Ruta del fichero de pesos (``YOUBER_WEIGHTS`` o ``~/.youber/...``)."""
    override = os.getenv(WEIGHTS_ENV)
    return Path(override) if override else DEFAULT_WEIGHTS_PATH


class SignalWeight(BaseModel):
    """Un peso, con la evidencia que lo movió (para poder auditarlo)."""

    name: str
    base: float
    weight: float
    factor: float = 1.0
    r: float | None = None
    n: int = 0

    @property
    def label(self) -> str:
        """Nombre legible de la señal."""
        return SIGNAL_LABELS.get(self.name, self.name)


class SelectionWeights(BaseModel):
    """Pesos del scoring, con su procedencia.

    Attributes:
        theme/sentiment/mood/keyword/favorite/usage: Peso de cada señal.
        metric: Métrica de resultado usada para aprender (``ctr``, ``views``...).
        samples: Decisiones medidas usadas en el aprendizaje.
        learned: ``True`` si vienen de datos reales (no del prior).
        learned_at: Cuándo se aprendieron.
        reason: Explicación de por qué son estos pesos (o por qué no se pudo
            aprender y se usan los de defecto).
        signals: Desglose por señal (factor, correlación y muestra).
    """

    theme: float = DEFAULT_WEIGHTS["theme"]
    sentiment: float = DEFAULT_WEIGHTS["sentiment"]
    mood: float = DEFAULT_WEIGHTS["mood"]
    keyword: float = DEFAULT_WEIGHTS["keyword"]
    favorite: float = DEFAULT_WEIGHTS["favorite"]
    usage: float = DEFAULT_WEIGHTS["usage"]
    metric: str = "ctr"
    samples: int = 0
    learned: bool = False
    learned_at: datetime | None = None
    reason: str = ""
    signals: dict[str, SignalWeight] = Field(default_factory=dict)

    # -- Constructores ------------------------------------------------------

    @classmethod
    def defaults(cls, *, reason: str = "") -> SelectionWeights:
        """Pesos por defecto (el prior, sin datos)."""
        signals = {
            name: SignalWeight(name=name, base=DEFAULT_WEIGHTS[name], weight=DEFAULT_WEIGHTS[name])
            for name in SIGNAL_NAMES
        }
        return cls(
            reason=reason
            or "pesos por defecto (aún no hay métricas suficientes en el journal)",
            signals=signals,
        )

    # -- Consulta -----------------------------------------------------------

    def as_dict(self) -> dict[str, float]:
        """Pesos como diccionario ``{señal: peso}``."""
        return {name: float(getattr(self, name)) for name in SIGNAL_NAMES}

    def factor(self, name: str) -> float:
        """Factor aplicado a una señal (1.0 = igual que el prior)."""
        entry = self.signals.get(name)
        return entry.factor if entry else 1.0

    def source_label(self) -> str:
        """Etiqueta corta de la procedencia de los pesos."""
        if not self.learned:
            return "por defecto"
        return f"aprendidos ({self.samples} vídeos, {self.metric})"

    def summary(self) -> str:
        """Resumen de una línea para consolas e informes."""
        weights = " · ".join(
            f"{SIGNAL_LABELS[name]} {self.as_dict()[name]:.2f}" for name in SIGNAL_NAMES
        )
        return f"{self.source_label()}: {weights}"

    # -- Persistencia -------------------------------------------------------

    def save(self, path: str | Path | None = None) -> Path:
        """Guarda los pesos en JSON (por defecto, el fichero del usuario)."""
        target = Path(path) if path is not None else default_weights_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path | None = None) -> SelectionWeights:
        """Carga los pesos guardados; si no hay, devuelve los de defecto.

        Un fichero corrupto no rompe el flujo: se avisa en ``reason`` y se
        sigue con el prior.
        """
        target = Path(path) if path is not None else default_weights_path()
        if not target.is_file():
            return cls.defaults(
                reason=f"sin pesos guardados en {target}: se usan los de defecto"
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            return cls.model_validate(payload)
        except (ValueError, OSError) as exc:  # pragma: no cover - defensivo
            return cls.defaults(reason=f"no se pudo leer {target} ({exc}): prior")

    @staticmethod
    def clear(path: str | Path | None = None) -> bool:
        """Borra el fichero de pesos. Devuelve ``True`` si existía."""
        target = Path(path) if path is not None else default_weights_path()
        if target.is_file():
            target.unlink()
            return True
        return False

    def describe(self) -> list[tuple[str, float, float, str, str]]:
        """Filas ``(señal, base, peso, factor, correlación)`` para tablas."""
        rows: list[tuple[str, float, float, str, str]] = []
        for name in SIGNAL_NAMES:
            entry = self.signals.get(name)
            base = entry.base if entry else DEFAULT_WEIGHTS[name]
            weight = float(getattr(self, name))
            factor = entry.factor if entry else 1.0
            if entry and entry.r is not None:
                correlation = f"r={entry.r:+.2f} (n={entry.n})"
            else:
                correlation = "—"
            rows.append(
                (SIGNAL_LABELS[name], base, weight, f"×{factor:.2f}", correlation)
            )
        return rows
