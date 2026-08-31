"""Teclados interactivos (InlineKeyboard) del bot de Telegram de BARF.

Generan botones inline para elegir opciones sin escribir: estados de ánimo
del catálogo de música, privacidad de subida y confirmaciones.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from youber.music.models import Mood
from youber.upload.metadata import PrivacyStatus


def mood_keyboard() -> InlineKeyboardMarkup:
    """Teclado con un botón por estado de ánimo (callback ``mood:<valor>``)."""
    buttons = [
        [
            InlineKeyboardButton(
                mood.value.capitalize(), callback_data=f"mood:{mood.value}"
            )
        ]
        for mood in Mood
    ]
    return InlineKeyboardMarkup(buttons)


def privacy_keyboard() -> InlineKeyboardMarkup:
    """Teclado con las opciones de privacidad (callback ``privacy:<valor>``)."""
    buttons = [
        [
            InlineKeyboardButton(
                privacy.value.capitalize(), callback_data=f"privacy:{privacy.value}"
            )
        ]
        for privacy in PrivacyStatus
    ]
    return InlineKeyboardMarkup(buttons)


def confirm_keyboard(action: str, payload: str) -> InlineKeyboardMarkup:
    """Teclado de confirmación (callback ``<action>:yes|no:<payload>``)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Sí", callback_data=f"{action}:yes:{payload}"),
                InlineKeyboardButton("❌ No", callback_data=f"{action}:no:{payload}"),
            ]
        ]
    )
