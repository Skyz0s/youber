"""Elige el **estilo visual** (y el ritmo del montaje) según audio y metadatos.

Un estilo fijo quema el concepto: si todos los vídeos salen con el mismo
aspecto, en una semana el canal parece el mismo vídeo repetido. Aquí el
estilo se decide **midiendo señales** de la pieza:

- **Audio**: energía, valencia (alegría), tempo, bailabilidad, acústica y
  modo (mayor/menor), de :class:`~youber.music.audio_features.models.AudioProfile`
  si el catálogo está enriquecido, o de un perfil de sonoridad medido con
  FFmpeg (:func:`youber.visuals.short.loudness_profile`) si solo hay fichero.
- **Metadatos de YouTube**: el texto público del canal/vídeo (título,
  descripción, etiquetas: *lofi*, *workout*, *tutorial*...) y los
  **temas/sentimiento** que se extraen de él con el mismo léxico que las
  letras (tristeza, misterio, amor...).

De esas señales salen el estilo (``cinematic``, ``dreamy``, ``dark``,
``vibrant``, ``minimal``), la duración de los fundidos, el arranque del ciclo
de movimientos y los segundos por plano. Todo es **determinista**: mismas
señales + misma ``variation_key`` → mismo resultado, así que cualquier render
se puede repetir; pero dos vídeos distintos rara vez coinciden.

Ética: las señales salen de tu propio audio y de metadatos públicos del
contenido; no se analiza ni se copia material de terceros.
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from youber.music.audio_features.models import AudioProfile
from youber.visuals.models import DEFAULT_MOTION_CYCLE, VisualStyle

#: Valor de ``--style`` que activa la elección automática.
AUTO_STYLE = "auto"

#: Ejes normalizados (0..1) que describen el contenido.
AXES: tuple[str, ...] = ("energy", "valence", "tempo", "dance", "tension", "intimacy")

#: Nombres legibles de los ejes (para los motivos).
AXIS_LABELS: dict[str, str] = {
    "energy": "energía",
    "valence": "valencia",
    "tempo": "tempo",
    "dance": "baile",
    "tension": "tensión",
    "intimacy": "intimidad",
}

#: Pesos lineales de cada estilo sobre los ejes (centrados en 0.5).
STYLE_WEIGHTS: dict[VisualStyle, dict[str, float]] = {
    VisualStyle.CINEMATIC: {"energy": 0.45, "tension": 0.55, "dance": -0.10},
    VisualStyle.DREAMY: {
        "energy": -0.65,
        "valence": 0.45,
        "intimacy": 0.85,
        "tension": -0.30,
        "tempo": -0.25,
    },
    VisualStyle.DARK: {
        "energy": -0.20,
        "valence": -1.30,
        "tension": 1.55,
        "tempo": -0.20,
        "dance": -0.35,
    },
    VisualStyle.VIBRANT: {
        "energy": 1.30,
        "valence": 1.00,
        "tempo": 0.70,
        "dance": 0.65,
        "tension": -0.50,
    },
    VisualStyle.MINIMAL: {
        "energy": -0.70,
        "tempo": -0.35,
        "tension": -0.30,
        "intimacy": -0.15,
        "dance": -0.25,
    },
}

#: Sesgo de partida: con señales neutras el estilo "seguro" es el cinematográfico.
STYLE_BIAS: dict[VisualStyle, float] = {
    VisualStyle.CINEMATIC: 0.25,
    VisualStyle.DREAMY: 0.0,
    VisualStyle.DARK: 0.0,
    VisualStyle.VIBRANT: 0.0,
    VisualStyle.MINIMAL: 0.0,
}

#: Palabras que apuntan a un estilo concreto (texto en minúsculas, sin acentos).
STYLE_KEYWORDS: dict[VisualStyle, tuple[str, ...]] = {
    VisualStyle.DARK: (
        "triste", "sad", "melancol", "dark", "oscuro", "luto", "lluvia", "rain",
        "noche", "night", "sombra", "shadow", "misterio", "mystery", "noir",
        "terror", "horror", "gothic", "suspense", "thriller",
    ),
    VisualStyle.DREAMY: (
        "calma", "calm", "relax", "sleep", "dormir", "medit", "ambient", "lofi",
        "soft", "suave", "paz", "peace", "zen", "bienestar", "dream", "sueno",
        "etereo", "ethereal", "neon", "instrumental",
    ),
    VisualStyle.VIBRANT: (
        "feliz", "happy", "fiesta", "party", "dance", "bail", "verano", "summer",
        "workout", "energ", "pop", "reggaeton", "upbeat", "color", "fitness",
        "running", "gym",
    ),
    VisualStyle.MINIMAL: (
        "tutorial", "educa", "aprende", "learn", "ciencia", "science", "tecno",
        "tech", "programa", "code", "python", "analisis", "datos", "data",
        "minimal", "clean", "limpio", "productividad", "productivity", "negocio",
    ),
    VisualStyle.CINEMATIC: (
        "cinemat", "epic", "epico", "documental", "documentary", "cine", "film",
        "historia", "story", "naturaleza", "nature", "viaje", "travel", "explora",
    ),
}

#: Bonus por palabra clave encontrada y tope de palabras que puntúan.
KEYWORD_BONUS = 0.9
MAX_KEYWORD_HITS = 2

#: Aporte de cada tema (mismo léxico que las letras) a los ejes.
THEME_VALENCE: dict[str, float] = {
    "felicidad": 1.0,
    "amor": 0.8,
    "calma": 0.5,
    "energia": 0.4,
    "misterio": 0.0,
    "tristeza": -1.0,
}
THEME_TENSION: dict[str, float] = {
    "tristeza": 0.9,
    "misterio": 1.0,
    "amor": -0.2,
    "calma": -0.3,
    "felicidad": -0.5,
    "energia": -0.2,
}
THEME_INTIMACY: dict[str, float] = {
    "amor": 1.0,
    "calma": 0.8,
    "tristeza": 0.3,
    "misterio": 0.2,
    "felicidad": 0.1,
    "energia": -0.4,
}
THEME_ENERGY: dict[str, float] = {
    "energia": 1.0,
    "felicidad": 0.7,
    "calma": -0.7,
    "tristeza": -0.5,
    "misterio": -0.2,
    "amor": -0.1,
}

#: Valencias de sentimiento (``LyricsAnalysis.sentiment``).
SENTIMENT_VALENCE: dict[str, float] = {
    "positivo": 0.75,
    "neutral": 0.5,
    "negativo": 0.2,
}

#: Margen de puntuación para considerar dos estilos "empatados".
TIE_EPSILON = 0.35

#: Normalización del tempo (BPM) y de la sonoridad medida (RMS de PCM 16 bits).
TEMPO_REFERENCE = 180.0
RMS_REFERENCE = 8000.0
DYNAMICS_REFERENCE = 1.2

#: Rangos del ritmo del montaje (segundos).
MIN_TRANSITION = 0.4
MAX_TRANSITION = 1.3
MIN_SECONDS_PER_SHOT = 10.0
MAX_SECONDS_PER_SHOT = 24.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Recorta ``value`` al rango ``[low, high]``."""
    return max(low, min(high, value))


class StyleSignals(BaseModel):
    """Señales del contenido que orientan el estilo (todas en ``0..1``).

    Attributes:
        energy: Energía percibida (sonoridad/energía del audio).
        valence: Positividad (alegre arriba, triste abajo).
        tempo: Tempo normalizado (0 lento, 1 rápido).
        dance: Bailabilidad.
        tension: Tensión dramática (modo menor, misterio, tristeza).
        intimacy: Intimidad (acústica, poca energía, temas de amor/calma).
        mood: Mood principal de la música, si se conoce.
        themes: Temas emocionales con peso (mismo léxico que las letras).
        text: Metadatos usados para las palabras clave.
        sources: De dónde salió cada señal (``audio``, ``letras``, ``metadatos``,
            ``sonoridad``).
    """

    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    valence: float = Field(default=0.5, ge=0.0, le=1.0)
    tempo: float = Field(default=0.5, ge=0.0, le=1.0)
    dance: float = Field(default=0.5, ge=0.0, le=1.0)
    tension: float = Field(default=0.5, ge=0.0, le=1.0)
    intimacy: float = Field(default=0.5, ge=0.0, le=1.0)
    mood: str | None = None
    themes: dict[str, float] = Field(default_factory=dict)
    text: str = ""
    sources: list[str] = Field(default_factory=list)

    def as_axes(self) -> dict[str, float]:
        """Los seis ejes numéricos como diccionario."""
        return {axis: float(getattr(self, axis)) for axis in AXES}

    def dominant(self, limit: int = 3) -> list[tuple[str, float]]:
        """Ejes que más se apartan del neutro (0.5), de mayor a menor."""
        ordered = sorted(
            self.as_axes().items(),
            key=lambda item: abs(item[1] - 0.5),
            reverse=True,
        )
        return [(axis, value) for axis, value in ordered[:limit] if abs(value - 0.5) > 0.01]


class StyleChoice(BaseModel):
    """Estilo elegido y los ajustes de montaje que trae consigo.

    Attributes:
        style: Estilo visual resuelto.
        explicit: ``True`` si lo pidió el usuario a mano (no se eligió solo).
        reason: Por qué se eligió (se imprime y se guarda en el plan).
        scores: Puntuación de cada estilo con estas señales.
        candidates: Estilos que empataron con el ganador (rotación determinista).
        signals: Señales usadas.
        transition: Duración sugerida de los fundidos (segundos).
        motion_offset: Desplazamiento del ciclo de movimientos (variedad
            determinista sin cambiar el estilo).
        seconds_per_shot: Objetivo de segundos por plano.
    """

    style: VisualStyle
    explicit: bool = False
    reason: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    signals: StyleSignals = Field(default_factory=StyleSignals)
    transition: float = 0.8
    motion_offset: int = 0
    seconds_per_shot: float = 16.0


def _axis_value(contributions: list[tuple[float, float]], default: float = 0.5) -> float:
    """Media ponderada de ``(valor, peso)`` recortada a ``0..1``."""
    total_weight = sum(weight for _, weight in contributions if weight > 0)
    if total_weight <= 0:
        return default
    value = sum(value * weight for value, weight in contributions if weight > 0)
    return _clamp(value / total_weight)


def signals_from_audio(profile: AudioProfile | None) -> dict[str, tuple[float, float]]:
    """Ejes que aporta un :class:`AudioProfile` (vacío si no hay perfil)."""
    if profile is None:
        return {}
    features = profile.features
    mode_minor = 1.0 - float(features.mode)
    return {
        "energy": (features.energy, 1.0),
        "valence": (features.valence, 1.0),
        "tempo": (_clamp(features.tempo / TEMPO_REFERENCE), 1.0),
        "dance": (features.danceability, 1.0),
        "tension": (_clamp(0.65 * (1.0 - features.valence) + 0.35 * mode_minor), 1.0),
        "intimacy": (
            _clamp(0.6 * features.acousticness + 0.4 * (1.0 - features.energy)),
            1.0,
        ),
    }


def signals_from_loudness(energies: Sequence[float]) -> dict[str, tuple[float, float]]:
    """Ejes que aporta el perfil de sonoridad medido con FFmpeg.

    La energía es el RMS medio (referenciado a PCM de 16 bits) y la tensión
    sale de la **dinámica**: un máster aplastado (poca variación) tira a menos
    tensión que uno con crescendos marcados.
    """
    usable = [float(value) for value in energies if value > 0]
    if not usable:
        return {}
    mean = statistics.fmean(usable)
    dynamic = statistics.pstdev(usable) / mean if len(usable) > 1 else 0.0
    return {
        "energy": (_clamp(mean / RMS_REFERENCE), 1.0),
        "tension": (_clamp(dynamic / DYNAMICS_REFERENCE), 0.6),
    }


def signals_from_themes(
    themes: Mapping[str, float], sentiment: str | None = None
) -> dict[str, tuple[float, float]]:
    """Ejes que aportan los temas/sentimiento (letras o metadatos)."""
    weights = {theme: float(weight) for theme, weight in themes.items() if weight > 0}
    if not weights:
        return {}
    total = sum(weights.values()) or 1.0
    weighted = {theme: weight / total for theme, weight in weights.items()}

    def blend(table: Mapping[str, float]) -> float:
        return max(-1.0, min(1.0, sum(table.get(theme, 0.0) * weight for theme, weight in weighted.items())))

    contributions: dict[str, tuple[float, float]] = {
        "valence": (_clamp(0.5 + 0.45 * blend(THEME_VALENCE)), 0.8),
        "tension": (_clamp(0.85 * blend(THEME_TENSION)), 0.9),
        "intimacy": (_clamp(0.9 * blend(THEME_INTIMACY)), 0.8),
        "energy": (_clamp(0.5 + 0.4 * blend(THEME_ENERGY)), 0.5),
    }
    if sentiment and sentiment in SENTIMENT_VALENCE:
        contributions["valence"] = (
            (_clamp(SENTIMENT_VALENCE[sentiment]) + contributions["valence"][0]) / 2,
            0.6,
        )
    return contributions


def keyword_hits(text: str) -> dict[VisualStyle, int]:
    """Cuenta palabras clave de metadatos por estilo."""
    lowered = text.lower()
    return {
        style: sum(1 for word in words if word in lowered)
        for style, words in STYLE_KEYWORDS.items()
    }


def build_signals(
    *,
    profile: AudioProfile | None = None,
    energies: Sequence[float] | None = None,
    themes: Mapping[str, float] | None = None,
    sentiment: str | None = None,
    metadata_text: str = "",
    mood: str | None = None,
) -> StyleSignals:
    """Mezcla todas las fuentes disponibles en un :class:`StyleSignals`.

    Cada fuente aporta ``(valor, peso)`` por eje y el resultado es su media
    ponderada; los ejes que ninguna fuente toca se quedan en el neutro
    (``0.5``). Todo es determinista y offline.
    """
    contributions: dict[str, list[tuple[float, float]]] = {axis: [] for axis in AXES}
    sources: list[str] = []

    def add(part: Mapping[str, tuple[float, float]], source: str) -> None:
        if not part:
            return
        sources.append(source)
        for axis, (value, weight) in part.items():
            contributions[axis].append((value, weight))

    add(signals_from_audio(profile), "audio")
    if energies is not None:
        add(signals_from_loudness(energies), "sonoridad")
    if themes:
        add(signals_from_themes(themes, sentiment), "temas")

    hits = keyword_hits(metadata_text)
    if any(hits.values()):
        sources.append("palabras clave")

    if mood and mood in THEME_VALENCE:
        for axis, (value, weight) in signals_from_themes({mood: 1.0}).items():
            contributions[axis].append((value, weight * 0.5))
        sources.append("mood")

    def axis_value(axis: str) -> float:
        values = contributions[axis]
        return _axis_value(values) if values else 0.5

    axes = {axis: axis_value(axis) for axis in AXES}

    return StyleSignals(
        **axes,
        mood=mood,
        themes={theme: round(float(weight), 4) for theme, weight in (themes or {}).items()},
        text=metadata_text,
        sources=sources,
    )


def score_styles(signals: StyleSignals) -> dict[VisualStyle, float]:
    """Puntúa cada estilo con las señales dadas (mayor = mejor encaje).

    Los pesos se aplican sobre los ejes **centrados** en 0.5 (así, con señales
    neutras, todos los estilos empatan salvo el sesgo de partida) y las
    palabras clave de los metadatos suman un extra directo.
    """
    hits = keyword_hits(signals.text)
    axes = signals.as_axes()
    scores: dict[VisualStyle, float] = {}
    for style in VisualStyle:
        score = STYLE_BIAS.get(style, 0.0)
        for axis, weight in STYLE_WEIGHTS[style].items():
            score += weight * (axes[axis] - 0.5) * 2.0
        score += KEYWORD_BONUS * min(hits.get(style, 0), MAX_KEYWORD_HITS)
        scores[style] = score
    return scores


def _stable_hash(key: str) -> int:
    """Hash estable entre ejecuciones (``hash()`` no lo es)."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def transition_for(signals: StyleSignals) -> float:
    """Duración de fundido según el tempo: rápido → cortes ágiles.

    Con tempo neutro (0.5, tempo desconocido) sale el fundido clásico de
    0.8 s; cuanto más lento el tema, más largos los fundidos.
    """
    return round(_clamp(1.3 - signals.tempo, MIN_TRANSITION, MAX_TRANSITION), 2)


def seconds_per_shot_for(signals: StyleSignals) -> float:
    """Segundos por plano según la energía: más energía → planos más cortos."""
    return round(
        _clamp(22.0 - 12.0 * signals.energy, MIN_SECONDS_PER_SHOT, MAX_SECONDS_PER_SHOT), 1
    )


def motion_offset_for(variation_key: str) -> int:
    """Desplazamiento del ciclo de movimientos (variedad sin cambiar el estilo)."""
    if not variation_key:
        return 0
    return _stable_hash(variation_key) % len(DEFAULT_MOTION_CYCLE)


def _reason(style: VisualStyle, signals: StyleSignals, scores: dict[VisualStyle, float]) -> str:
    """Motivo legible de la elección (se guarda en el plan)."""
    dominant = ", ".join(
        f"{AXIS_LABELS[axis]} {value:.2f}" for axis, value in signals.dominant()
    )
    detail = f" ({dominant})" if dominant else ""
    if signals.sources:
        detail += f" · fuentes: {', '.join(dict.fromkeys(signals.sources))}"
    text = signals.text.strip()
    if text:
        detail += f" · metadatos: {text[:60]}"
    return f"estilo automático: {style.value} [{scores[style]:+.2f}]{detail}"


def choose_style(
    style: VisualStyle | str = AUTO_STYLE,
    *,
    signals: StyleSignals | None = None,
    variation_key: str = "",
    epsilon: float = TIE_EPSILON,
) -> StyleChoice:
    """Resuelve el estilo y los ajustes de montaje de una pieza.

    Args:
        style: Estilo pedido (``"auto"`` lo deja a las señales).
        signals: Señales del audio/metadatos (neutras si no se dan).
        variation_key: Clave estable de la pieza (tema, semilla...). Cuando
            varios estilos empatan, elige entre ellos de forma determinista:
            dos vídeos distintos no se reparten el mismo.
        epsilon: Margen para considerar empate.

    Returns:
        El :class:`StyleChoice` con estilo, motivo, fundido, desplazamiento de
        movimientos y segundos por plano.
    """
    signals = signals or StyleSignals()
    scores = score_styles(signals)
    offset = motion_offset_for(variation_key)
    transition = transition_for(signals)
    pacing = seconds_per_shot_for(signals)

    if str(style) != AUTO_STYLE:
        chosen = VisualStyle(style)
        ordered = sorted(scores, key=lambda item: (-scores[item], item.value))
        return StyleChoice(
            style=chosen,
            explicit=True,
            reason=(
                f"estilo pedido a mano: {chosen.value} · el ritmo y los fundidos "
                f"siguen al audio ({', '.join(item.value for item in ordered[:3])} "
                f"puntuaban {', '.join(f'{scores[item]:+.2f}' for item in ordered[:3])})"
            ),
            scores={item.value: round(value, 4) for item, value in scores.items()},
            candidates=[chosen.value],
            signals=signals,
            transition=transition,
            motion_offset=offset,
            seconds_per_shot=pacing,
        )

    best = max(scores.values())
    tied = sorted(
        (item for item, value in scores.items() if value >= best - epsilon),
        key=lambda item: (-scores[item], item.value),
    )
    chosen = tied[_stable_hash(variation_key) % len(tied)] if variation_key else tied[0]
    return StyleChoice(
        style=chosen,
        explicit=False,
        reason=_reason(chosen, signals, scores),
        scores={item.value: round(value, 4) for item, value in scores.items()},
        candidates=[item.value for item in tied],
        signals=signals,
        transition=transition,
        motion_offset=offset,
        seconds_per_shot=pacing,
    )
