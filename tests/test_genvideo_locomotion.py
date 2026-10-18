"""Tests de las metricas de locomocion (`youber.genvideo.locomotion`)."""

from __future__ import annotations

import numpy as np

from youber.genvideo.locomotion import LocomotionReport, judge, phase_shift


def _report(**kwargs: float | str) -> LocomotionReport:
    base: dict = {
        "mode": "static",
        "frames": 97,
        "fps": 24.0,
        "bg_dx": 0.0,
        "bg_dy": 0.0,
        "subject_dx": 0.0,
        "subject_dy": 0.0,
        "area_ratio": 1.0,
        "motion": 5.0,
        "score": 0.0,
        "ok": True,
    }
    base.update(kwargs)
    return LocomotionReport(**base)  # type: ignore[arg-type]


def test_phase_shift_detecta_desplazamiento_conocido() -> None:
    rng = np.random.default_rng(7)
    img = rng.random((64, 96)).astype(np.float32)
    shifted = np.roll(img, 5, axis=1)
    dx, dy = phase_shift(img, shifted)
    assert dx == 5
    assert dy == 0


def test_phase_shift_detecta_desplazamiento_vertical() -> None:
    rng = np.random.default_rng(11)
    img = rng.random((64, 96)).astype(np.float32)
    shifted = np.roll(img, -3, axis=0)
    dx, dy = phase_shift(img, shifted)
    assert dy == -3


def test_travelling_exige_movimiento_de_fondo() -> None:
    quieto = judge(_report(mode="tracking", bg_dx=1.0))
    assert not quieto.ok
    assert quieto.score < 0.5

    movido = judge(_report(mode="tracking", bg_dx=30.0))
    assert movido.ok


def test_alejarse_exige_que_encoja_o_se_desplace() -> None:
    congelado = judge(_report(mode="away", area_ratio=1.02, subject_dy=1.0))
    assert not congelado.ok

    alejandose = judge(_report(mode="away", area_ratio=0.62))
    assert alejandose.ok


def test_lateral_exige_cruzar_el_encuadre() -> None:
    quieto = judge(_report(mode="lateral", subject_dx=2.0, bg_dx=0.0))
    assert not quieto.ok

    cruzando = judge(_report(mode="lateral", subject_dx=40.0))
    assert cruzando.ok


def test_estatico_siempre_pasa() -> None:
    assert judge(_report(mode="static")).ok


def test_acercarse_exige_que_crezca() -> None:
    assert not judge(_report(mode="toward", area_ratio=1.01)).ok
    assert judge(_report(mode="toward", area_ratio=1.35)).ok
