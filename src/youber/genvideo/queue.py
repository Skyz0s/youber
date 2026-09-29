"""Cola de trabajos persistida y reanudable (*JSON* en disco).

Un lote nocturno puede durar horas: si el runner se corta, el gateway se
reinicia o la máquina se apaga, la cola **no se pierde**. Al cargarla, todo
trabajo que quedara en ``running`` vuelve a ``pending`` (nadie lo está
haciendo ya) y el lote continúa donde iba.

La escritura es atómica (fichero temporal + ``replace``): un corte a mitad de
guardado no deja un JSON roto.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from youber.genvideo.models import ClipRequest, JobStatus

#: Versión del formato de la cola (para migraciones futuras).
QUEUE_VERSION = 1

#: Variable de entorno que redirige el directorio de estado del módulo.
ENV_DIR = "YOUBER_GENVIDEO_DIR"

#: Nombre del fichero de cola dentro del directorio de estado.
QUEUE_FILENAME = "queue.json"


def default_dir() -> Path:
    """Directorio de estado del módulo (``YOUBER_GENVIDEO_DIR`` o ``~/.youber``)."""
    configured = os.environ.get(ENV_DIR)
    base = Path(configured) if configured else Path.home() / ".youber"
    return base / "genvideo" if configured else base / "genvideo"


def queue_path(path: str | Path | None = None) -> Path:
    """Ruta del fichero de cola: la indicada o la del directorio por defecto."""
    if path is not None:
        target = Path(path)
        return target / QUEUE_FILENAME if target.is_dir() else target
    return default_dir() / QUEUE_FILENAME


class JobQueue:
    """Cola de clips respaldada por un fichero JSON.

    Attributes:
        path: Fichero donde vive la cola.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = queue_path(path)
        self._lock = threading.Lock()
        self._requests: list[ClipRequest] = []
        self.load()

    # -- carga y guardado -------------------------------------------------

    def load(self) -> list[ClipRequest]:
        """Lee la cola del disco (si no existe, arranca vacía)."""
        with self._lock:
            if not self.path.exists():
                self._requests = []
                return self._requests
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"Cola de generación ilegible ({self.path}): {exc}")
                self._requests = []
                return self._requests
            self._requests = [ClipRequest(**item) for item in raw.get("requests", [])]
            return self._requests

    def save(self) -> Path:
        """Escribe la cola en disco de forma atómica."""
        with self._lock:
            payload = {
                "version": QUEUE_VERSION,
                "updated_at": datetime.now().isoformat(),
                "requests": [item.model_dump(mode="json") for item in self._requests],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(self.path)
            return self.path

    # -- operaciones ------------------------------------------------------

    @property
    def requests(self) -> list[ClipRequest]:
        """Todos los trabajos de la cola (copia de la lista)."""
        with self._lock:
            return list(self._requests)

    def add(self, request: ClipRequest) -> ClipRequest:
        """Añade un trabajo y persiste la cola."""
        with self._lock:
            self._requests.append(request)
        self.save()
        return request

    def extend(
        self, requests: list[ClipRequest], *, skip_existing: bool = True
    ) -> list[ClipRequest]:
        """Añade varios trabajos de una vez (una sola escritura).

        Con ``skip_existing`` (por defecto) se ignoran los que ya estaban en la
        cola y los repetidos dentro de la propia lista: volver a lanzar un lote
        no duplica clips.

        Returns:
            Los trabajos que de verdad se han añadido.
        """
        with self._lock:
            known = {item.id for item in self._requests}
            added: list[ClipRequest] = []
            for request in requests:
                if skip_existing and request.id in known:
                    continue
                known.add(request.id)
                added.append(request)
            self._requests.extend(added)
        if added:
            self.save()
        return added

    def get(self, request_id: str) -> ClipRequest | None:
        """Devuelve un trabajo por su identificador."""
        with self._lock:
            for request in self._requests:
                if request.id == request_id:
                    return request
        return None

    def update(self, request: ClipRequest) -> ClipRequest:
        """Sustituye un trabajo por su versión actualizada y persiste."""
        request.touch()
        with self._lock:
            for index, current in enumerate(self._requests):
                if current.id == request.id:
                    self._requests[index] = request
                    break
            else:
                self._requests.append(request)
        self.save()
        return request

    def pending(self) -> list[ClipRequest]:
        """Trabajos pendientes, en orden de encolado."""
        with self._lock:
            return [item for item in self._requests if item.status == JobStatus.PENDING]

    def by_status(self, status: JobStatus) -> list[ClipRequest]:
        """Trabajos en un estado concreto."""
        with self._lock:
            return [item for item in self._requests if item.status == status]

    def recover(self) -> int:
        """Devuelve a ``pending`` lo que quedó en ``running`` tras un corte.

        Returns:
            Cuántos trabajos se han recuperado.
        """
        recovered = 0
        with self._lock:
            for request in self._requests:
                if request.status == JobStatus.RUNNING:
                    request.status = JobStatus.PENDING
                    request.prompt_id = None
                    recovered += 1
        if recovered:
            logger.info(f"Cola recuperada: {recovered} clip(s) vuelven a pendiente")
            self.save()
        return recovered

    def requeue_failed(self) -> int:
        """Vuelve a encolar los clips descartados (para reintentarlos)."""
        with self._lock:
            count_ = 0
            for request in self._requests:
                if request.status == JobStatus.FAILED:
                    request.status = JobStatus.PENDING
                    request.error = None
                    count_ += 1
        if count_:
            self.save()
        return count_

    def clear(self, status: JobStatus | None = None) -> int:
        """Borra los trabajos en un estado (o todos, si ``status`` es ``None``)."""
        with self._lock:
            if status is None:
                removed = len(self._requests)
                self._requests = []
            else:
                kept = [item for item in self._requests if item.status != status]
                removed = len(self._requests) - len(kept)
                self._requests = kept
        if removed:
            self.save()
        return removed

    def stats(self) -> dict[str, int]:
        """Cuántos trabajos hay en cada estado."""
        with self._lock:
            counts = {status.value: 0 for status in JobStatus}
            for request in self._requests:
                counts[request.status.value] += 1
            counts["total"] = len(self._requests)
            return counts
