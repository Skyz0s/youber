"""Ruta ``uploads`` — estado de la subida a YouTube (sin exponer secretos)."""

from __future__ import annotations

import os
from typing import Any

from youber.upload.auth import YouTubeAuth


async def uploads_status(params: dict[str, Any]) -> dict[str, Any]:
    """Indica si la subida a YouTube está configurada (solo booleanos)."""
    client_id = bool(os.environ.get("GOOGLE_CLIENT_ID", "").strip())
    client_secret = bool(os.environ.get("GOOGLE_CLIENT_SECRET", "").strip())
    try:
        token_saved = YouTubeAuth().has_token()
    except Exception:
        token_saved = False
    return {
        "youtube": {
            "client_configured": client_id and client_secret,
            "token_saved": token_saved,
            "ready": token_saved,
        }
    }
