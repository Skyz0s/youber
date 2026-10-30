"""Tests de ``youber.console`` (stdio en UTF-8 sin romper en cp1252)."""

from __future__ import annotations

import sys

import pytest

from youber.console import UTF8_STDIO_ENV, ensure_utf8_console, utf8_env


class FakeStream:
    """Stream de texto mínimo con ``reconfigure`` observable."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self._error = error

    def reconfigure(self, **kwargs: str) -> None:
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)


class PlainStream:
    """Stream sin ``reconfigure`` (p. ej. un objeto capturado por otra librería)."""


def test_reconfigura_stdout_y_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    ensure_utf8_console()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_ignora_streams_sin_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", PlainStream())
    monkeypatch.setattr(sys, "stderr", PlainStream())

    ensure_utf8_console()  # no debe lanzar


def test_ignora_streams_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    ensure_utf8_console()  # no debe lanzar


@pytest.mark.parametrize("error", [ValueError("cerrado"), OSError("io"), AttributeError("raro")])
def test_tolera_errores_de_reconfigure(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(sys, "stdout", FakeStream(error=error))
    monkeypatch.setattr(sys, "stderr", FakeStream(error=error))

    ensure_utf8_console()  # no debe lanzar


def test_utf8_env_fuerza_stdio_utf8_y_conserva_el_resto() -> None:
    env = utf8_env({"PATH": "C:/Windows", "OTRA": "1"})

    assert env[UTF8_STDIO_ENV] == "utf-8"
    assert env["PATH"] == "C:/Windows"
    assert env["OTRA"] == "1"


def test_utf8_env_no_muta_el_diccionario_original() -> None:
    original = {"PATH": "C:/Windows"}

    utf8_env(original)

    assert original == {"PATH": "C:/Windows"}
