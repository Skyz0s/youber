"""Recordatorios del registro de decisiones («¿a qué vídeo le faltan métricas?»).

Convierte el journal en una lista de deberes: qué vídeos ya publicados no
tienen todavía las mediciones de cada ventana (7d, 28d...) y, por tanto, siguen
esperando a que pegues el CSV de YouTube Studio.

Es lógica pura sobre datos locales (más un aviso opcional por Telegram), así
que se puede usar desde la CLI, desde el scheduler (``journal_reminder``) o
desde código.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import httpx
from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from youber.journal.journal import DecisionJournal

#: Ventanas que el recordatorio vigila por defecto.
DEFAULT_WINDOWS: tuple[str, ...] = ("7d", "28d")

#: Antigüedad mínima (días) para considerar que una ventana «debería» existir.
DEFAULT_MIN_AGE_DAYS = 3.0

#: Variables de entorno para el aviso por Telegram (opcional).
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ENV = "TELEGRAM_CHAT_ID"

#: Máximo de vídeos que se listan en el mensaje (el resto se resume).
MAX_LISTED = 10


class PendingMetric(BaseModel):
    """Un vídeo publicado al que le faltan ventanas de métricas."""

    decision_id: str
    topic: str
    video_id: str | None = None
    published_at: datetime | None = None
    age_days: float = 0.0
    missing_windows: list[str] = Field(default_factory=list)
    measured_windows: list[str] = Field(default_factory=list)


class ReminderReport(BaseModel):
    """Estado del journal de cara al recordatorio semanal."""

    generated_at: datetime = Field(default_factory=datetime.now)
    windows: list[str] = Field(default_factory=list)
    min_age_days: float = DEFAULT_MIN_AGE_DAYS
    decisions: int = 0
    published: int = 0
    measured: int = 0
    pending: list[PendingMetric] = Field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        """``True`` si hay algún vídeo esperando métricas."""
        return bool(self.pending)

    def message(self) -> str:
        """Mensaje listo para la consola (o para Telegram)."""
        windows = ", ".join(self.windows)
        if not self.pending:
            return (
                f"🗂️  Registro de decisiones al día: {self.published} vídeo(s) publicados, "
                f"ninguno con ventanas pendientes ({windows})."
            )
        lines = [
            f"🗂️  Toca pegar el CSV de YouTube Studio — {len(self.pending)} vídeo(s) "
            f"sin métricas completas ({windows}):",
            "",
        ]
        for item in self.pending[:MAX_LISTED]:
            lines.append(
                f"• {item.decision_id} · «{item.topic}» (hace {item.age_days:.0f} d) · "
                f"faltan: {', '.join(item.missing_windows)}"
            )
        if len(self.pending) > MAX_LISTED:
            lines.append(f"  … y {len(self.pending) - MAX_LISTED} más")
        lines += [
            "",
            "Studio → Analytics → Modo avanzado → exportar CSV y luego:",
            "  youber-journal import <csv> --window 7d",
            "  youber-journal import <csv> --window 28d",
        ]
        return "\n".join(lines)

    def as_text(self) -> str:
        """Alias de :meth:`message` (mensaje plano)."""
        return self.message()


def _age_days(record: object, now: datetime) -> float:
    """Días desde la publicación (o desde la creación, si no se publicó)."""
    upload = getattr(record, "upload", None)
    published = upload.published_at if upload is not None else None
    reference = published or getattr(record, "created_at", None) or now
    return round(max(0.0, (now - reference).total_seconds() / 86400.0), 2)


def pending_metrics(
    journal: DecisionJournal,
    *,
    windows: tuple[str, ...] = DEFAULT_WINDOWS,
    min_age_days: float = DEFAULT_MIN_AGE_DAYS,
    require_upload: bool = True,
    now: datetime | None = None,
) -> ReminderReport:
    """Calcula a qué vídeos les faltan ventanas de métricas.

    Args:
        journal: Journal abierto.
        windows: Ventanas a vigilar (``7d``, ``28d``...).
        min_age_days: Antigüedad mínima del vídeo para pedirle métricas
            (no tiene sentido reclamar el CTR de algo publicado ayer).
        require_upload: Ignorar las decisiones sin vídeo publicado (no se
            pueden medir en la plataforma).
        now: Instante de referencia (por defecto, ahora).

    Returns:
        El :class:`ReminderReport` con los vídeos pendientes y el resumen.
    """
    moment = now or datetime.now()
    report = ReminderReport(
        generated_at=moment, windows=list(windows), min_age_days=min_age_days
    )
    for record in journal.list_decisions():
        report.decisions += 1
        if record.video_id:
            report.published += 1
        elif require_upload:
            continue

        measured = [
            window
            for window in windows
            if journal.latest_performance(record.id, window=window) is not None
        ]
        missing = [window for window in windows if window not in measured]
        if measured:
            report.measured += 1
        if not missing:
            continue
        age = _age_days(record, moment)
        if age < min_age_days:
            continue
        upload = record.upload
        report.pending.append(
            PendingMetric(
                decision_id=record.id,
                topic=record.topic or "(sin tema)",
                video_id=record.video_id,
                published_at=upload.published_at if upload is not None else None,
                age_days=age,
                missing_windows=missing,
                measured_windows=measured,
            )
        )
    report.pending.sort(key=lambda item: item.age_days, reverse=True)
    return report


def notify_telegram(
    text: str, *, token: str | None = None, chat_id: str | None = None
) -> bool:
    """Envía el recordatorio por Telegram (best-effort).

    Usa ``TELEGRAM_BOT_TOKEN`` y ``TELEGRAM_CHAT_ID`` (o los argumentos). Si
    falta configuración o la API falla, devuelve ``False`` y lo registra: un
    aviso no debe tumbar el daemon.

    Returns:
        ``True`` si la API aceptó el mensaje.
    """
    import os

    from dotenv import load_dotenv

    # Permite definir el token/chat en el `.env` del proyecto (idempotente).
    load_dotenv()
    token = token or os.getenv(TELEGRAM_TOKEN_ENV)
    chat_id = chat_id or os.getenv(TELEGRAM_CHAT_ENV)
    if not token or not chat_id:
        logger.debug(
            f"Aviso Telegram omitido: faltan {TELEGRAM_TOKEN_ENV}/{TELEGRAM_CHAT_ENV}"
        )
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10.0,
        )
    except Exception as exc:  # pragma: no cover - red
        logger.warning(f"No se pudo enviar el aviso Telegram: {exc}")
        return False
    if response.status_code != 200:
        logger.warning(f"Telegram rechazó el aviso ({response.status_code}): {response.text[:200]}")
        return False
    return True
