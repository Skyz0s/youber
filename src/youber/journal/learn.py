"""Aprendizaje de los pesos del selector a partir de las métricas del canal.

El :mod:`youber.journal` guarda, por cada vídeo, el desglose del scoring que
eligió la canción y —pegando después las métricas de YouTube Studio— cómo
rindió. Este módulo cierra el bucle: mide cuánto correlaciona cada señal con
el resultado y **reescala su peso** en :class:`~youber.music.weights.SelectionWeights`.

Cómo se aprende (sencillo y auditable, sin dependencias):

1. Se toman las decisiones con métrica medida (p. ej. ``ctr``).
2. Para cada señal se calcula la correlación de Pearson entre su valor y esa
   métrica (``sentiment_match``, ``mood_match``, ``keyword_hits``...).
3. El peso se multiplica por ``1 + dirección · fuerza · r · encogimiento``,
   con ``encogimiento = n / (n + min_samples)``: con pocos datos el peso se
   queda cerca del prior; con muchos, la evidencia manda.
4. El factor se acota (``FACTOR_CLAMP``) para que una racha corta no desboque
   el scoring.

Si no hay métricas suficientes devuelve **los pesos por defecto**: el flujo se
comporta exactamente igual que antes.
"""

from __future__ import annotations

from collections.abc import Sequence

from youber.journal.analytics import DatasetRow, feature_correlations
from youber.music.weights import (
    DEFAULT_WEIGHTS,
    SIGNAL_NAMES,
    SelectionWeights,
    SignalWeight,
)

#: Cuánto puede mover la evidencia cada peso (0 = nada, 1 = todo el tirón).
LEARNING_STRENGTH = 0.5

#: Decisiones medidas mínimas para aprender algo.
MIN_SAMPLES = 5

#: Pares mínimos para aceptar una correlación como señal.
MIN_CORRELATION_PAIRS = 3

#: Límites del factor multiplicativo (evita que una racha desboque el scoring).
FACTOR_CLAMP = (0.25, 4.0)

#: Señal → (feature del dataset, dirección).
#: ``+1`` premia la señal al subir; ``-1`` en las penalizaciones (más usos
#: previos correlacionando con peor resultado ⇒ el castigo debe subir).
SIGNAL_FEATURES: dict[str, tuple[str, float]] = {
    "theme": ("theme_score", +1.0),
    "sentiment": ("sentiment_match", +1.0),
    "mood": ("mood_match", +1.0),
    "keyword": ("keyword_hits", +1.0),
    "favorite": ("favorite", +1.0),
    "usage": ("usage_count", -1.0),
}


def shrinkage(n: int, *, min_samples: int = MIN_SAMPLES) -> float:
    """Cuánto se deja mover el peso con ``n`` muestras (0..1).

    Con ``n = min_samples`` la evidencia pesa la mitad; con muchas muestras
    tiende a 1 (manda la evidencia).
    """
    if n <= 0:
        return 0.0
    return n / (n + max(1, min_samples))


def factor_for(
    r: float,
    n: int,
    direction: float,
    *,
    strength: float = LEARNING_STRENGTH,
    min_samples: int = MIN_SAMPLES,
    clamp: tuple[float, float] = FACTOR_CLAMP,
) -> float:
    """Factor multiplicativo del peso de una señal.

    Args:
        r: Correlación de Pearson observada entre la señal y el resultado.
        n: Tamaño de muestra de esa correlación.
        direction: ``+1`` (premiar al subir) o ``-1`` (penalización).
        strength: Cuánto puede mover la evidencia (0 = nada).
        min_samples: Muestras a las que la evidencia pesa la mitad.
        clamp: Límites inferior y superior del factor.

    Returns:
        El factor (1.0 = se queda como el prior).
    """
    raw = 1.0 + direction * strength * r * shrinkage(n, min_samples=min_samples)
    low, high = clamp
    return max(low, min(high, raw))


def learn_weights(
    rows: Sequence[DatasetRow],
    *,
    metric: str = "ctr",
    min_samples: int = MIN_SAMPLES,
    strength: float = LEARNING_STRENGTH,
    min_pairs: int = MIN_CORRELATION_PAIRS,
) -> SelectionWeights:
    """Aprende los pesos del selector desde el dataset del journal.

    Args:
        rows: Filas del dataset (:func:`youber.journal.build_dataset`).
        metric: Métrica de resultado a optimizar (``ctr``, ``views``,
            ``retention``...).
        min_samples: Decisiones medidas mínimas para aprender.
        strength: Cuánto puede mover la evidencia cada peso.
        min_pairs: Pares mínimos para aceptar una señal.

    Returns:
        Los :class:`SelectionWeights` aprendidos, o los de defecto (con el
        motivo en ``reason``) si no hay datos suficientes.
    """
    measured = [
        row for row in rows if row.outcomes.get(metric) is not None
    ]
    if len(measured) < min_samples:
        return SelectionWeights.defaults(
            reason=(
                f"hacen falta {min_samples} vídeos con '{metric}' medido "
                f"(hay {len(measured)}): se usan los pesos por defecto"
            )
        )

    correlations = {
        item.feature: item
        for item in feature_correlations(measured, metric, min_n=min_pairs)
    }

    signals: dict[str, SignalWeight] = {}
    for name in SIGNAL_NAMES:
        base = DEFAULT_WEIGHTS[name]
        feature, direction = SIGNAL_FEATURES[name]
        found = correlations.get(feature)
        if found is None:
            signals[name] = SignalWeight(
                name=name, base=base, weight=base, factor=1.0
            )
            continue
        factor = factor_for(
            found.r, found.n, direction, strength=strength, min_samples=min_samples
        )
        signals[name] = SignalWeight(
            name=name,
            base=base,
            weight=round(base * factor, 4),
            factor=round(factor, 4),
            r=round(found.r, 4),
            n=found.n,
        )

    weights = SelectionWeights(
        metric=metric,
        samples=len(measured),
        learned=True,
        reason=(
            f"aprendidos de {len(measured)} vídeos con '{metric}' medido "
            f"(fuerza {strength:g}, encogimiento n/(n+{min_samples}))"
        ),
        signals=signals,
        theme=signals["theme"].weight,
        sentiment=signals["sentiment"].weight,
        mood=signals["mood"].weight,
        keyword=signals["keyword"].weight,
        favorite=signals["favorite"].weight,
        usage=signals["usage"].weight,
    )
    return weights


def weights_report(weights: SelectionWeights) -> str:
    """Informe de texto (Markdown) de unos pesos, para guardar o imprimir."""
    lines = [
        "# Pesos del selector de canciones",
        "",
        f"- Procedencia: **{weights.source_label()}**",
        f"- Métrica objetivo: `{weights.metric}`",
        f"- Vídeos usados: **{weights.samples}**",
        f"- Detalle: {weights.reason}",
        "",
        "| Señal | Peso base | Peso final | Factor | Evidencia |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for label, base, weight, factor, correlation in weights.describe():
        lines.append(f"| {label} | {base:g} | {weight:g} | {factor} | {correlation} |")
    lines.append("")
    return "\n".join(lines)
