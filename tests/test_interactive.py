"""Tests del intérprete de comandos de la CLI interactiva del cliente."""

import pytest

from youber.client.interactive import execute_command

# Los comandos help/exit/desconocidos y la validación de argumentos no
# necesitan servidor: se prueban con tools=None.


async def test_help_command():
    output = await execute_command(None, "help")
    assert "open <url>" in output
    assert "audit <url>" in output
    assert "journey" in output
    assert "exit" in output


async def test_exit_command():
    output = await execute_command(None, "exit")
    assert "Hasta luego" in output


async def test_unknown_command():
    output = await execute_command(None, "frobnicate")
    assert "Comando desconocido" in output


async def test_empty_line():
    assert await execute_command(None, "") == ""
    assert await execute_command(None, "   ") == ""


async def test_missing_arguments():
    with pytest.raises(ValueError, match="Faltan argumentos"):
        await execute_command(None, "open")
    with pytest.raises(ValueError, match="Faltan argumentos"):
        await execute_command(None, "geo ES")
