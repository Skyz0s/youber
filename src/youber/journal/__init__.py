"""Registro de decisiones (*decision journal*) de BARF.

Guarda, para cada vídeo generado, **todo el razonamiento del algoritmo**: qué
patrón se detectó en los metadatos, qué atributos se extrajeron, qué canción se
eligió y por qué (con su puntuación y sus rivales), qué prompt/guion salió, qué
vídeo se renderizó y —pegando después las métricas de YouTube Studio— cómo
rindió de verdad: impresiones, CTR, retención, visualizaciones, suscripciones.

Con el tiempo eso deja de ser un generador y pasa a ser un **dataset** con el
que estudiar qué características del matching predicen un vídeo que funciona.

Uso:

.. code-block:: python

    from youber.journal import DecisionJournal, PerformanceSnapshot

    journal = DecisionJournal()
    journal.record(record)
    journal.attach_upload(record.id, video_id="abc123")
    journal.record_performance(
        record.id, PerformanceSnapshot(window="7d", views=1200, ctr=4.5)
    )
    for row in journal.dataset(window="7d"):
        print(row.features["theme_score"], row.outcomes["ctr"])
"""

from __future__ import annotations

from youber.journal.analytics import (
    FEATURE_LABELS,
    OUTCOME_LABELS,
    DatasetRow,
    build_dataset,
    build_report,
    compare_groups,
    feature_correlations,
    pearson,
    summarize,
)
from youber.journal.builder import (
    attributes_from_insights,
    record_from_lyrics_run,
    record_from_workflow_run,
    track_decision_from_match,
    video_id_from_url,
)
from youber.journal.importers import import_analytics_csv, read_analytics_csv
from youber.journal.journal import (
    DEFAULT_JOURNAL_DB,
    DecisionJournal,
    default_journal_path,
)
from youber.journal.models import (
    ALGORITHM_VERSION,
    WINDOWS,
    ContentAttributes,
    DecisionRecord,
    PerformanceSnapshot,
    TrackCandidate,
    TrackDecision,
    UploadRecord,
    VideoArtifact,
)
from youber.journal.storage import JournalStorage

__all__ = [
    "ALGORITHM_VERSION",
    "DEFAULT_JOURNAL_DB",
    "FEATURE_LABELS",
    "OUTCOME_LABELS",
    "WINDOWS",
    "ContentAttributes",
    "DatasetRow",
    "DecisionJournal",
    "DecisionRecord",
    "JournalStorage",
    "PerformanceSnapshot",
    "TrackCandidate",
    "TrackDecision",
    "UploadRecord",
    "VideoArtifact",
    "attributes_from_insights",
    "build_dataset",
    "build_report",
    "compare_groups",
    "default_journal_path",
    "feature_correlations",
    "import_analytics_csv",
    "pearson",
    "read_analytics_csv",
    "record_from_lyrics_run",
    "record_from_workflow_run",
    "summarize",
    "track_decision_from_match",
    "video_id_from_url",
]
