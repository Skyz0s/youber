"""Tests de la medición local del tempo (`youber.visuals.tempo`).

Los tests de la envolvente y de la autocorrelación son puros (sin FFmpeg): se
construyen trenes de clics a mano. Solo la detección sobre un fichero real
necesita FFmpeg, y va con ``skipif``. Nada toca la red.
"""

from __future__ import annotations

import array
import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from youber.visuals.selector import build_signals, choose_style, signals_from_tempo
from youber.visuals.tempo import (
    ANALYSIS_SAMPLE_RATE,
    FRAME_SIZE,
    HOP_SIZE,
    BeatGrid,
    attack_envelope,
    detect_tempo,
    onset_time_offset,
    tempo_from_envelope,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _click_track(
    times: Sequence[float],
    *,
    seconds: float,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
    amplitude: int = 20000,
) -> array.array:
    """Señal de silencio con un clic (40 muestras alternas) en cada instante."""
    samples = array.array("h", [0] * int(round(seconds * sample_rate)))
    for time in times:
        start = int(round(time * sample_rate))
        for offset in range(40):
            index = start + offset
            if index < len(samples):
                samples[index] = amplitude if offset % 2 == 0 else -amplitude
    return samples


def _pulse_envelope(period: float, *, seconds: float, rate: float, weights: dict[int, float]) -> list[float]:
    """Envolvente sintética con pulsos cada ``period`` s y pesos por posición.

    ``weights`` mapea el índice del pulso (0, 1, 2...) a su altura.
    """
    frames = int(round(seconds * rate))
    step = max(1, int(round(period * rate)))
    envelope = [0.0] * frames
    index = 0
    position = 0
    while index < frames:
        envelope[index] = weights.get(position % 2, 1.0)
        index += step
        position += 1
    return envelope


def _peaks(envelope: Sequence[float]) -> list[int]:
    """Índices de los máximos locales que destacan sobre el resto."""
    if not envelope:
        return []
    threshold = 0.15 * max(envelope)
    return [
        index
        for index in range(1, len(envelope) - 1)
        if envelope[index] > threshold
        and envelope[index] >= envelope[index - 1]
        and envelope[index] >= envelope[index + 1]
    ]


# ---------------------------------------------------------------------------
# Envolvente de ataques
# ---------------------------------------------------------------------------


def test_attack_envelope_marca_los_golpes():
    times = [index * 0.5 for index in range(8)]
    samples = _click_track(times, seconds=4.0, sample_rate=8000)
    envelope = attack_envelope(samples, sample_rate=8000)
    assert len(envelope) == (len(samples) - FRAME_SIZE) // HOP_SIZE + 1
    peaks = _peaks(envelope)
    assert 7 <= len(peaks) <= 9
    for peak in peaks:
        # El pico cae en el fotograma en el que el clic entra en la ventana de
        # energía: nunca después del golpe y como mucho un fotograma antes.
        frame = peak * HOP_SIZE / 8000
        click = min(times, key=lambda time: abs(frame - time))
        assert 0.0 <= click - frame <= onset_time_offset(sample_rate=8000)


def test_attack_envelope_con_audio_demasiado_corto():
    assert attack_envelope(array.array("h", [0] * 100)) == []
    assert attack_envelope(array.array("h", [])) == []


# ---------------------------------------------------------------------------
# Pulso por autocorrelación
# ---------------------------------------------------------------------------


def test_tempo_from_envelope_detecta_120_bpm():
    envelope = _pulse_envelope(0.5, seconds=30.0, rate=100.0, weights={0: 1.0})
    bpm, confidence = tempo_from_envelope(envelope, rate=100.0)
    assert bpm == pytest.approx(120.0, abs=2.0)
    assert confidence > 0.0


def test_tempo_from_envelope_pliega_la_octava():
    # Pulso real de 150 BPM (0.4 s) con acentos alternos: la autocorrelación
    # prefiere el doble de lento (75 BPM). El plegado devuelve 150.
    envelope = _pulse_envelope(0.4, seconds=30.0, rate=100.0, weights={0: 1.0, 1: 0.6})
    bpm, _ = tempo_from_envelope(envelope, rate=100.0)
    assert bpm == pytest.approx(150.0, abs=3.0)


def test_tempo_from_envelope_con_envolvente_corta():
    assert tempo_from_envelope([], rate=100.0) == (0.0, 0.0)
    assert tempo_from_envelope([1.0, 0.0, 1.0], rate=100.0) == (0.0, 0.0)
    assert tempo_from_envelope([1.0] * 100, rate=0.0) == (0.0, 0.0)


def test_signals_from_tempo_normaliza_los_bpm():
    assert signals_from_tempo(0.0) == {}
    assert signals_from_tempo(90.0)["tempo"][0] == pytest.approx(0.5)
    assert signals_from_tempo(360.0)["tempo"][0] == 1.0


# ---------------------------------------------------------------------------
# Integración con las señales de estilo
# ---------------------------------------------------------------------------


def test_build_signals_con_tempo_medido():
    signals = build_signals(tempo_bpm=176.0)
    assert signals.tempo_bpm == 176.0
    assert signals.tempo == pytest.approx(176.0 / 180.0, abs=1e-6)
    assert "tempo medido" in signals.sources


def test_choose_style_acorta_los_fundidos_con_tempo_alto():
    """Más BPM → fundidos más cortos; un tema lento los alarga."""
    fast = choose_style("auto", signals=build_signals(tempo_bpm=216.0), variation_key="a")
    slow = choose_style("auto", signals=build_signals(tempo_bpm=76.0), variation_key="a")
    neutral = choose_style("auto", variation_key="a")
    assert fast.transition == 0.4  # tope inferior
    assert slow.transition > neutral.transition == 0.8
    assert slow.transition <= 1.3


def test_song_signals_usa_el_pulso_medido(monkeypatch, tmp_path: Path):
    """El CLI de visuals mide el pulso y lo pasa a las señales y al render."""
    import youber.visuals.cli as visuals_cli
    import youber.visuals.short as short_module
    import youber.visuals.tempo as tempo_module

    async def fake_loudness(song, **kwargs):
        return [5000.0, 6000.0, 7000.0]

    async def fake_grid(song, **kwargs):
        return BeatGrid(
            bpm=176.0, offset=0.3, confidence=0.5, phase_strength=0.4, seconds=12.0
        )

    monkeypatch.setattr(short_module, "loudness_profile", fake_loudness)
    monkeypatch.setattr(tempo_module, "detect_grid", fake_grid)

    signals, grid = asyncio.run(visuals_cli._song_signals(tmp_path / "song.wav", topic="tema"))
    assert signals.tempo_bpm == 176.0
    assert "tempo medido" in signals.sources
    assert grid is not None and grid.reliable()


def test_song_signals_descarta_un_pulso_flojo(monkeypatch, tmp_path: Path):
    """Con pulso poco firme se devuelve ``None``: cortes uniformes, no a ciegas."""
    import youber.visuals.cli as visuals_cli
    import youber.visuals.short as short_module
    import youber.visuals.tempo as tempo_module

    async def fake_loudness(song, **kwargs):
        return [5000.0]

    async def fake_grid(song, **kwargs):
        return BeatGrid(bpm=100.0, offset=0.1, confidence=0.2, phase_strength=0.05)

    monkeypatch.setattr(short_module, "loudness_profile", fake_loudness)
    monkeypatch.setattr(tempo_module, "detect_grid", fake_grid)

    signals, grid = asyncio.run(visuals_cli._song_signals(tmp_path / "song.wav"))
    assert grid is None
    assert signals.tempo_bpm == 100.0  # el tempo sí se usa para el estilo


# ---------------------------------------------------------------------------
# Detección sobre audio real (FFmpeg)
# ---------------------------------------------------------------------------


def test_detect_tempo_sin_fichero(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(detect_tempo(tmp_path / "no-existe.wav"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_detect_tempo_con_click_real(tmp_path: Path):
    from youber.audio._ffmpeg import run_command

    song = tmp_path / "clicks.wav"
    # Tren de clics de 1 kHz a 120 BPM (0.5 s) durante 20 s.
    asyncio.run(
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc=0.8*sin(2*PI*1000*t)*between(mod(t\\,0.5)\\,0\\,0.03):s=22050:d=20",
                str(song),
            ]
        )
    )
    estimate = asyncio.run(detect_tempo(song))
    assert estimate.detected
    assert estimate.bpm == pytest.approx(120.0, abs=4.0)
    assert estimate.seconds == pytest.approx(20.0, abs=1.0)
    assert estimate.confidence > 0.0
    assert estimate.onsets > 0
