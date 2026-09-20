"""Mide el **tempo** (BPM) de una canción en local, por onsets.

El tempo decide los fundidos y el ritmo del montaje, pero hasta ahora solo
llegaba desde el :class:`~youber.music.audio_features.models.AudioProfile` del
catálogo (Spotify o estimador). Si la pista no está enriquecida, aquí se
**mide del propio fichero**: sin red, sin dependencias extra y sin subir audio
a ningún sitio.

Cómo funciona:

1. se decodifica un tramo a PCM mono de 16 bits con FFmpeg
   (:func:`youber.audio._ffmpeg.decode_mono_pcm`),
2. se calcula la **envolvente de ataques** (*novelty*): el audio pasa por un
   filtro paso-alto barato (diferencia entre muestras consecutivas, que
   resalta la percusión), se mide la energía por fotograma solapado y solo
   cuenta el *subidón* respecto al fotograma anterior,
3. se resta una media móvil (umbral adaptativo) y se busca el **pulso** por
   autocorrelación en el rango 60-200 BPM, plegando la ambigüedad de octava
   hacia la zona 80-160 BPM: un patrón de corcheas acentuadas a 75 BPM no es
   "150 lento", es un pulso de 150 con acentos alternos.

Todo es determinista: mismo audio → mismo BPM. Solo se analiza un tramo
(``MAX_ANALYSIS_SECONDS``) para que las canciones largas no tarden de más.
"""

from __future__ import annotations

import array
import math
import statistics
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from youber.audio._ffmpeg import decode_mono_pcm

#: Frecuencia de muestreo del análisis (bastante para medir ataques).
ANALYSIS_SAMPLE_RATE = 11025

#: Fotograma de la envolvente (muestras) y salto entre fotogramas. El
#: fotograma solapado da la resolución temporal; la ventana se mantiene corta
#: (46 ms a 11 kHz) para que el ataque no se "adelante" demasiado.
FRAME_SIZE = 512
HOP_SIZE = 128

#: Rango de pulso que se considera (BPM).
MIN_BPM = 60.0
MAX_BPM = 200.0

#: Zona de BPM hacia la que se pliega la ambigüedad de octava.
PREFERRED_LOW = 80.0
PREFERRED_HIGH = 160.0

#: Tope de audio analizado (segundos): el tempo no cambia de un tramo a otro.
MAX_ANALYSIS_SECONDS = 180.0

#: Ventana del umbral adaptativo (segundos).
SMOOTHING_SECONDS = 0.4

#: Un pulso de otra octava solo sustituye al ganador si puntúa casi igual.
OCTAVE_TOLERANCE = 0.85

#: Mínimos para fiarse del pulso al cortar los planos (ver ``BeatGrid.reliable``).
MIN_CUT_CONFIDENCE = 0.3
MIN_CUT_PHASE = 0.15

#: Autocorrelación normalizada (energía que sigue al pulso / energía total) a
#: partir de la cual se considera que el pulso es de fiar. En música real con
#: mezcla y voz el pulso suele quedar en 0.10-0.30 (medido sobre el catálogo de
#: prueba); un tren de clics sube a 0.5 y más.
CONFIDENCE_REFERENCE = 0.35


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Recorta ``value`` al rango ``[low, high]``."""
    return max(low, min(high, value))


class TempoEstimate(BaseModel):
    """Tempo medido de una pieza.

    Attributes:
        bpm: Pulsos por minuto estimados (``0.0`` si no se pudo medir).
        confidence: Cuánta energía sigue al pulso ganador sobre el total
            (``0..1``), normalizado por :data:`CONFIDENCE_REFERENCE`.
        seconds: Segundos de audio analizados.
        onsets: Fotogramas de la envolvente de ataques.
    """

    bpm: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    seconds: float = Field(default=0.0, ge=0.0)
    onsets: int = Field(default=0, ge=0)

    @property
    def detected(self) -> bool:
        """``True`` si se pudo medir un pulso."""
        return self.bpm > 0.0


def attack_envelope(
    samples: Sequence[float],
    *,
    frame_size: int = FRAME_SIZE,
    hop_size: int = HOP_SIZE,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
    smoothing: float = SMOOTHING_SECONDS,
) -> list[float]:
    """Envolvente de ataques (*novelty*) por fotograma.

    Realza los golpes con un filtro paso-alto por diferencias (la percusión
    vive en los cambios bruscos, no en el nivel absoluto), mide la energía por
    fotograma solapado y se queda con el **incremento** respecto al fotograma
    anterior. Después resta una media móvil: es un umbral adaptativo, así que
    un pasaje flojo también aporta onsets.

    Cada golpe aparece como un pico en el fotograma en el que entra en la
    ventana (ver :func:`onset_time_offset`), no en su instante exacto.

    Args:
        samples: Muestras PCM mono (enteras o flotantes).
        frame_size: Muestras por fotograma.
        hop_size: Salto entre fotogramas (marca la resolución temporal).
        sample_rate: Frecuencia de muestreo de ``samples``.
        smoothing: Ventana del umbral adaptativo (segundos).

    Returns:
        Un valor ``>= 0`` por fotograma; lista vacía si no hay audio suficiente.
    """
    total_samples = len(samples)
    if hop_size <= 0 or frame_size <= hop_size or total_samples <= frame_size:
        return []

    # Suma acumulada de la energía del paso-alto: deja la energía de cualquier
    # fotograma en O(1) sin recorrer el audio dos veces.
    prefix = array.array("d", [0.0]) * (total_samples + 1)
    accumulator = 0.0
    previous = samples[0]
    for index in range(1, total_samples):
        value = samples[index]
        delta = value - previous
        accumulator += delta * delta
        prefix[index] = accumulator
        previous = value
    prefix[total_samples] = accumulator

    novelty: list[float] = [0.0]
    previous_energy = 0.0
    for start in range(0, total_samples - frame_size + 1, hop_size):
        energy = math.sqrt((prefix[start + frame_size - 1] - prefix[start]) / frame_size)
        if start > 0:
            novelty.append(max(0.0, energy - previous_energy))
        previous_energy = energy

    window = max(1, int(round(smoothing * sample_rate / hop_size)))
    if window <= 1 or len(novelty) <= window:
        return novelty

    smoothed: list[float] = []
    running = 0.0
    for index, value in enumerate(novelty):
        running += value
        if index >= window:
            running -= novelty[index - window]
            mean = running / window
        else:
            mean = running / (index + 1)
        smoothed.append(max(0.0, value - mean))
    return smoothed


def onset_time_offset(*, sample_rate: int = ANALYSIS_SAMPLE_RATE) -> float:
    """Cuánto puede adelantarse un ataque en la envolvente (segundos).

    La energía se mide por ventana, así que el salto aparece en el fotograma en
    el que el golpe **entra** en la ventana: hasta un fotograma antes del
    instante real. Es un desfase constante (no cambia los intervalos, y por
    tanto no toca el BPM), pero conviene documentarlo.
    """
    return (FRAME_SIZE + HOP_SIZE) / sample_rate


def _octave_candidates(lag: int, min_lag: int, max_lag: int) -> set[int]:
    """Retardos equivalentes a ``lag`` en otra octava (mitades y dobles)."""
    candidates = {lag}
    for factor in (2, 3):
        multiple = lag * factor
        if multiple <= max_lag:
            candidates.add(multiple)
    for divisor in (2, 3):
        if lag % divisor == 0:
            quotient = lag // divisor
            if quotient >= min_lag:
                candidates.add(quotient)
    return candidates


def tempo_from_envelope(
    envelope: Sequence[float],
    *,
    rate: float,
    min_bpm: float = MIN_BPM,
    max_bpm: float = MAX_BPM,
    preferred: tuple[float, float] = (PREFERRED_LOW, PREFERRED_HIGH),
) -> tuple[float, float]:
    """Estima ``(bpm, confianza)`` a partir de una envolvente de ataques.

    La autocorrelación de la envolvente marca cada cuántos fotogramas se repite
    el patrón (el pulso). Se normaliza por la energía de la envolvente, así que
    la puntuación es comparable entre piezas (y la confianza, interpretable).
    Cuando el ganador cae fuera de la zona preferida, se prueba el mismo pulso
    al doble o a la mitad: la gente percibe el pulso en esa banda, no en sus
    múltiplos.

    Args:
        envelope: Envolvente de ataques (:func:`attack_envelope`).
        rate: Fotogramas por segundo de la envolvente.
        min_bpm: Pulso más lento que se considera.
        max_bpm: Pulso más rápido que se considera.
        preferred: Zona de BPM a la que se pliega la ambigüedad de octava.

    Returns:
        ``(bpm, confianza)`` con la confianza en ``0..1``; ``(0.0, 0.0)`` si la
        envolvente es demasiado corta para medir nada.
    """
    if rate <= 0 or len(envelope) < 4:
        return 0.0, 0.0
    mean = statistics.fmean(envelope)
    centered = [value - mean for value in envelope]
    zero_lag = statistics.fmean(value * value for value in centered)
    if zero_lag <= 0:
        return 0.0, 0.0
    min_lag = max(1, math.floor(60.0 / max_bpm * rate))
    max_lag = min(len(centered) - 1, math.ceil(60.0 / min_bpm * rate))
    if max_lag <= min_lag:
        return 0.0, 0.0

    scores: dict[int, float] = {}
    for lag in range(min_lag, max_lag + 1):
        total = 0.0
        for index in range(len(centered) - lag):
            total += centered[index] * centered[index + lag]
        scores[lag] = total / (len(centered) - lag) / zero_lag

    best_lag = max(scores, key=lambda item: scores[item])
    best_score = scores[best_lag]
    low, high = preferred
    viable = [
        candidate
        for candidate in _octave_candidates(best_lag, min_lag, max_lag)
        if scores[candidate] >= best_score * OCTAVE_TOLERANCE
        and low <= 60.0 * rate / candidate <= high
    ]
    chosen = (
        max(viable, key=lambda item: (scores[item], 60.0 * rate / item))
        if viable
        else best_lag
    )
    return 60.0 * rate / chosen, _clamp(scores[chosen] / CONFIDENCE_REFERENCE)


def beat_offset(
    envelope: Sequence[float],
    *,
    rate: float,
    interval: float,
) -> tuple[float, float]:
    """Fase del pulso: instante del primer *beat* (segundos) y su fuerza.

    Con el intervalo ya medido solo falta saber **dónde** cae el pulso. Se
    prueban todas las fases posibles (resolución de un fotograma) y se elige la
    que más energía de ataque acumula sobre la rejilla: si el ritmo es real,
    los golpes caen siempre en la misma fase.

    Args:
        envelope: Envolvente de ataques (:func:`attack_envelope`).
        rate: Fotogramas por segundo de la envolvente.
        interval: Segundos entre pulsos (``60 / bpm``).

    Returns:
        ``(offset, fuerza)`` con el offset en segundos (``>= 0``) y la fuerza
        en ``0..1`` (cuánta energía extra cae en la rejilla respecto a la media).
    """
    if interval <= 0 or rate <= 0 or not envelope:
        return 0.0, 0.0
    period_frames = interval * rate
    mean = statistics.fmean(envelope)
    if mean <= 0:
        return 0.0, 0.0
    steps = max(1, int(round(period_frames)))
    best_phase = 0
    best_score = -1.0
    for phase in range(steps):
        total = 0.0
        count = 0
        position = float(phase)
        while position < len(envelope):
            index = int(round(position))
            if index < len(envelope):
                total += envelope[index]
                count += 1
            position += period_frames
        score = total / count if count else 0.0
        if score > best_score:
            best_score = score
            best_phase = phase
    return best_phase / rate, _clamp((best_score - mean) / mean)


class BeatGrid(BaseModel):
    """Rejilla de pulsos de una pieza: cada cuánto suena el beat y desde dónde.

    Attributes:
        bpm: Pulsos por minuto (``0.0`` si no se pudo medir).
        offset: Segundo del primer pulso (dentro de ``[0, interval)``).
        confidence: Confianza del tempo (ver :class:`TempoEstimate`).
        phase_strength: Cuánta energía extra cae sobre la rejilla (``0..1``).
        seconds: Segundos de audio analizados.
    """

    bpm: float = Field(default=0.0, ge=0.0)
    offset: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    phase_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    seconds: float = Field(default=0.0, ge=0.0)

    @property
    def interval(self) -> float:
        """Segundos entre pulsos (``0.0`` si no hay tempo)."""
        return 60.0 / self.bpm if self.bpm > 0 else 0.0

    @property
    def detected(self) -> bool:
        """``True`` si se pudo medir el pulso."""
        return self.bpm > 0.0

    def reliable(
        self,
        *,
        min_confidence: float = MIN_CUT_CONFIDENCE,
        min_phase: float = MIN_CUT_PHASE,
    ) -> bool:
        """``True`` si el pulso es lo bastante firme para cortar los planos ahí.

        Un tempo flojo o una fase difusa no deben mandar sobre el montaje: sin
        esto, alinear los cortes a un pulso inventado quedaría peor que un
        reparto uniforme.
        """
        return (
            self.detected
            and self.confidence >= min_confidence
            and self.phase_strength >= min_phase
        )

    def next_beat(self, time: float) -> float:
        """Primer pulso ``>= time`` (``time`` si no hay tempo)."""
        interval = self.interval
        if interval <= 0:
            return time
        steps = math.ceil((time - self.offset) / interval - 1e-9)
        return self.offset + max(steps, 0) * interval

    def nearest_beat(self, time: float) -> float:
        """Pulso más cercano a ``time``."""
        interval = self.interval
        if interval <= 0:
            return time
        return self.offset + round((time - self.offset) / interval) * interval

    def beat_times(self, *, start: float = 0.0, end: float | None = None) -> list[float]:
        """Pulsos dentro de ``[start, end)`` (sin fin si ``end`` es ``None``)."""
        interval = self.interval
        if interval <= 0:
            return []
        times: list[float] = []
        current = self.next_beat(start)
        while end is None or current < end:
            times.append(round(current, 4))
            current += interval
        return times

    def shifted(self, delta: float) -> BeatGrid:
        """Copia con la rejilla desplazada ``delta`` segundos.

        Sirve cuando se trabaja sobre un trozo de la pieza (por ejemplo el
        corte vertical del Short): la fase se recalcula dentro del fragmento.
        """
        interval = self.interval
        if interval <= 0:
            return self.model_copy()
        offset = (self.offset - delta) % interval
        return self.model_copy(update={"offset": round(offset, 4)})


async def _analyse(
    song: str | Path,
    *,
    sample_rate: int,
    max_seconds: float,
) -> tuple[list[float], float, float]:
    """Envolvente de ataques, fotogramas por segundo y segundos analizados."""
    samples = await decode_mono_pcm(song, sample_rate=sample_rate, seconds=max_seconds)
    envelope = attack_envelope(samples, sample_rate=sample_rate)
    return envelope, sample_rate / HOP_SIZE, len(samples) / sample_rate


async def detect_tempo(
    song: str | Path,
    *,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
    max_seconds: float = MAX_ANALYSIS_SECONDS,
) -> TempoEstimate:
    """Mide el tempo (BPM) de un fichero de audio en local.

    Args:
        song: Fichero de audio (wav/mp3/m4a...).
        sample_rate: Frecuencia de muestreo del análisis.
        max_seconds: Tope de audio analizado (segundos).

    Returns:
        Un :class:`TempoEstimate`; ``bpm == 0.0`` si no se pudo medir.

    Raises:
        FileNotFoundError: si el fichero no existe.
        RuntimeError: si FFmpeg falta o falla.
    """
    envelope, rate, seconds = await _analyse(
        song, sample_rate=sample_rate, max_seconds=max_seconds
    )
    bpm, confidence = tempo_from_envelope(envelope, rate=rate)
    logger.info(
        f"Tempo medido: {bpm:.1f} BPM (confianza {confidence:.2f}, "
        f"{seconds:.0f} s, {len(envelope)} fotogramas)"
    )
    return TempoEstimate(
        bpm=round(bpm, 1),
        confidence=round(confidence, 3),
        seconds=round(seconds, 2),
        onsets=len(envelope),
    )


async def detect_grid(
    song: str | Path,
    *,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
    max_seconds: float = MAX_ANALYSIS_SECONDS,
) -> BeatGrid:
    """Mide tempo **y fase** del pulso: la rejilla de *beats* de la pieza.

    Es una sola pasada de análisis (decodifica una vez) y sirve para cortar los
    planos justo en el pulso.

    Args:
        song: Fichero de audio (wav/mp3/m4a...).
        sample_rate: Frecuencia de muestreo del análisis.
        max_seconds: Tope de audio analizado (segundos).

    Returns:
        La :class:`BeatGrid` medida; ``bpm == 0.0`` si no se pudo medir.

    Raises:
        FileNotFoundError: si el fichero no existe.
        RuntimeError: si FFmpeg falta o falla.
    """
    envelope, rate, seconds = await _analyse(
        song, sample_rate=sample_rate, max_seconds=max_seconds
    )
    bpm, confidence = tempo_from_envelope(envelope, rate=rate)
    if bpm <= 0:
        return BeatGrid(seconds=round(seconds, 2))
    offset, strength = beat_offset(envelope, rate=rate, interval=60.0 / bpm)
    logger.info(
        f"Pulso medido: {bpm:.1f} BPM, primer beat en {offset:.2f} s "
        f"(confianza {confidence:.2f}, fase {strength:.2f}, {seconds:.0f} s)"
    )
    return BeatGrid(
        bpm=round(bpm, 1),
        offset=round(offset, 3),
        confidence=round(confidence, 3),
        phase_strength=round(strength, 3),
        seconds=round(seconds, 2),
    )
