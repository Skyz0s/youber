"""Análisis de letras (temática y sentimiento) para el catálogo de música.

Este módulo analiza ficheros de letras ``.txt`` **locales** (los tuyos) y
extrae un perfil temático que ayuda a alinear cada canción con el
contenido de un vídeo: temas dominantes, sentimiento general, idioma y
palabras clave.

Diseño:

- 100 % offline y determinista: diccionarios de léxico, sin modelos
  descargados ni llamadas a servicios externos (nada de scraping).
- Sin dependencias nuevas: solo biblioteca estándar + pydantic del repo.
- El resultado se guarda en la pista (:class:`~youber.music.models.Track`)
  como ``lyrical_themes`` (tema → peso) y ``lyrical_sentiment``.

Uso típico:

.. code-block:: python

    from youber.music.lyrics_analyzer import LyricsAnalyzer

    analyzer = LyricsAnalyzer()
    analysis = analyzer.analyze_lyrics(texto_de_la_letra)
    print(analysis.themes, analysis.sentiment)
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from youber.music.models import Mood, Track

# -- Léxicos ----------------------------------------------------------------

SPANISH_STOP_WORDS: frozenset[str] = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "pero",
        "porque", "como", "cuando", "donde", "quien", "que", "este", "esta",
        "esto", "eso", "aqui", "alli", "arriba", "abajo", "fue", "era", "ser",
        "estar", "tener", "hacer", "poder", "decir", "a", "ante", "bajo", "cabe",
        "con", "contra", "de", "desde", "durante", "en", "entre", "hacia",
        "hasta", "mediante", "para", "por", "segun", "sin", "so", "sobre",
        "tras", "versus", "vs", "e", "ni", "lo", "le", "me", "te", "se", "nos",
        "os", "les", "mi", "mis", "tu", "tus", "su", "sus", "nuestro",
        "nuestra", "vuestro", "vuestra", "estos", "estas", "ese", "esa", "esos",
        "esas", "aquel", "aquella", "aquellos", "aquellas", "algo", "nada",
        "alguien", "nadie", "mucho", "poca", "poco", "bastante", "muchos",
        "demasiado", "tan", "tanto", "cual", "quienes", "tambien", "solo",
        "sino", "aunque", "mientras", "siempre", "nunca", "todavia", "ya",
    }
)

ENGLISH_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "because", "as", "when", "where",
        "who", "that", "this", "these", "those", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "having", "do", "does",
        "did", "doing", "can", "could", "may", "might", "must", "shall",
        "should", "will", "would", "to", "of", "in", "for", "on", "with", "at",
        "by", "from", "up", "down", "out", "off", "over", "under", "again",
        "then", "once", "here", "there", "why", "how", "all", "any", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "still", "yet", "i", "you", "he", "she", "it", "we", "they", "me",
        "him", "her", "us", "them", "my", "your", "his", "its", "our", "their",
    }
)

#: Tema emocional → palabras clave (español e inglés).
EMOTION_LEXICON: dict[str, frozenset[str]] = {
    "felicidad": frozenset(
        {
            "feliz", "felicidad", "alegria", "contento", "contenta", "bienestar",
            "placer", "encanto", "maravilloso", "maravillosa", "fantastico",
            "increible", "genial", "excelente", "magnifico", "perfecto",
            "perfecta", "brillante", "radiante", "luz", "brillo", "risa",
            "sonrisa", "reir", "divertido", "diversion", "fiesta", "celebracion",
            "happy", "happiness", "joy", "joyful", "smile", "laugh", "laughter",
            "bright", "shine", "sunshine", "wonderful", "great", "party",
        }
    ),
    "tristeza": frozenset(
        {
            "triste", "tristeza", "llanto", "llorar", "llorando", "lagrima",
            "lagrimas", "pesadumbre", "dolor", "doloroso", "sufrimiento",
            "sufrir", "pena", "nostalgia", "melancolia", "sollozo", "depresion",
            "desanimado", "desesperanza", "vacio", "vacia", "solo", "sola",
            "solitario", "perdida", "adios", "olvido",
            "sad", "sadness", "cry", "crying", "tear", "tears", "sob", "weep",
            "grief", "sorrow", "mourning", "heartbreak", "heartbroken", "empty",
            "lonely", "loneliness", "alone", "loss", "goodbye", "miss",
        }
    ),
    "energia": frozenset(
        {
            "energia", "fuerza", "poder", "potencia", "intenso", "intensa",
            "vibrante", "dinamico", "dinamica", "activo", "activa", "animado",
            "animada", "vivaz", "energico", "energica", "brio", "empuje",
            "impulso", "correr", "saltar", "fuego", "fuerte", "salvaje",
            "energy", "power", "powerful", "strong", "strength", "force",
            "intense", "vibrant", "dynamic", "active", "lively", "run", "jump",
            "fire", "wild", "burn", "fight", "rise",
        }
    ),
    "calma": frozenset(
        {
            "calma", "tranquilo", "tranquila", "paz", "sereno", "serena",
            "apacible", "suave", "gentil", "placido", "quieto", "quieta",
            "quietud", "silencio", "sosegado", "respirar", "descanso",
            "calm", "peace", "peaceful", "tranquil", "serene", "serenity",
            "relax", "relaxed", "ease", "gentle", "soft", "hush", "silence",
            "silent", "whisper", "breathe", "rest", "slow",
        }
    ),
    "misterio": frozenset(
        {
            "misterio", "misterioso", "misteriosa", "enigmatico", "enigmatica",
            "secreto", "secreta", "oculto", "oculta", "velado", "oscuro",
            "oscura", "sombra", "sombras", "penumbra", "niebla", "bruma",
            "humo", "noche", "susurro", "silencio",
            "mystery", "mysterious", "enigmatic", "cryptic", "secret",
            "hidden", "concealed", "dark", "darkness", "shadow", "shadows",
            "fog", "mist", "haze", "smoke", "night", "whisper", "unknown",
        }
    ),
    "amor": frozenset(
        {
            "amor", "amante", "amada", "amado", "querido", "querida", "carino",
            "ternura", "devocion", "fidelidad", "fiel", "leal", "beso", "abrazo",
            "corazon", "pasional", "deseo", "te quiero",
            "love", "loving", "lover", "beloved", "dear", "dearest",
            "sweetheart", "sweet", "honey", "darling", "adore", "cherish",
            "affection", "tenderness", "tender", "devotion", "faithful",
            "loyal", "kiss", "hug", "heart", "desire",
        }
    ),
}

#: Polaridad de cada tema para el sentimiento global.
POSITIVE_THEMES = frozenset({"felicidad", "energia", "amor", "calma"})
NEGATIVE_THEMES = frozenset({"tristeza"})

#: Tema emocional → etiqueta de mood del catálogo (para filtrar/buscar).
THEME_TO_MOOD: dict[str, Mood] = {
    "felicidad": Mood.HAPPY,
    "tristeza": Mood.SAD,
    "energia": Mood.ENERGETIC,
    "calma": Mood.RELAXING,
    "misterio": Mood.MYSTERIOUS,
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_ACCENTS = str.maketrans("áéíóúüñçàèìòùâêîôû", "aeiouunca eiouaeiou".replace(" ", ""))


def _strip_accents(text: str) -> str:
    """Quita acentos/diacríticos básicos (español, catalán, portugués)."""
    return text.translate(_ACCENTS)


def _normalize_key(text: str) -> str:
    """Normaliza texto para comparar nombres (minúsculas, sin signos)."""
    return re.sub(r"[^0-9a-z]+", "", _strip_accents(text.lower()))


def _normalize_lyrics(text: str) -> str:
    """Normaliza la letra: minúsculas, sin acentos ni signos de puntuación."""
    return re.sub(r"\s+", " ", _strip_accents(text.lower())).strip()


class LyricsAnalysis(BaseModel):
    """Resultado del análisis de una letra."""

    #: Tema emocional → peso (0..1). Solo aparecen los temas detectados.
    themes: dict[str, float] = Field(default_factory=dict)
    #: Sentimiento global: ``positive``, ``negative`` o ``neutral``.
    sentiment: str = "neutral"
    #: Palabras significativas más frecuentes (sin stop words).
    top_words: list[str] = Field(default_factory=list)
    #: Idioma detectado: ``es``, ``en`` o ``unknown``.
    language: str = "unknown"
    #: Confianza del análisis (0..1).
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Número de palabras significativas analizadas.
    word_count: int = Field(default=0, ge=0)
    #: Recorte de la letra analizada (para depurar).
    raw_text: str | None = None

    @property
    def dominant_theme(self) -> str | None:
        """Tema con mayor peso (o ``None`` si no se detectó ninguno)."""
        if not self.themes:
            return None
        return max(self.themes, key=lambda theme: self.themes[theme])

    def moods(self) -> list[Mood]:
        """Moods del catálogo equivalentes a los temas detectados."""
        return [THEME_TO_MOOD[theme] for theme in self.themes if theme in THEME_TO_MOOD]


class LyricsAnalyzer:
    """Analiza letras locales y las relaciona con temas y sentimientos.

    El análisis es determinista y offline: frecuencias de palabras +
    léxicos emocionales. Se puede instanciar sin argumentos::

        LyricsAnalyzer().analyze_lyrics("letra...")
    """

    def __init__(self, top_words: int = 10, min_word_length: int = 3) -> None:
        """Configura el analizador.

        Args:
            top_words: Cuántas palabras frecuentes devolver.
            min_word_length: Longitud mínima para considerar una palabra.
        """
        self.top_words = top_words
        self.min_word_length = min_word_length

    # -- Análisis -----------------------------------------------------------

    def analyze_lyrics(self, lyrics_text: str) -> LyricsAnalysis:
        """Analiza el texto de una letra.

        Args:
            lyrics_text: Letra completa (texto plano).

        Returns:
            El :class:`LyricsAnalysis` con temas, sentimiento e idioma.
        """
        if not lyrics_text or not lyrics_text.strip():
            return LyricsAnalysis(confidence=0.0)

        text_clean = _normalize_lyrics(lyrics_text)
        language = self._detect_language(text_clean)
        words = self._significant_words(text_clean, language)
        themes = self._emotional_themes(words)
        sentiment = self._sentiment(themes)
        confidence = self._confidence(words, themes)

        return LyricsAnalysis(
            themes=themes,
            sentiment=sentiment,
            top_words=[word for word, _ in Counter(words).most_common(self.top_words)],
            language=language,
            confidence=confidence,
            word_count=len(words),
            raw_text=lyrics_text[:500],
        )

    # -- Pasos internos -----------------------------------------------------

    @staticmethod
    def _detect_language(text: str) -> str:
        """Detecta el idioma por densidad de stop words (es/en)."""
        words = set(text.split())
        spanish = len(words & SPANISH_STOP_WORDS)
        english = len(words & ENGLISH_STOP_WORDS)
        if spanish > english:
            return "es"
        if english > spanish:
            return "en"
        return "unknown"

    def _significant_words(self, text: str, language: str) -> list[str]:
        """Devuelve las palabras con carga semántica (sin stop words)."""
        stop = SPANISH_STOP_WORDS if language == "es" else ENGLISH_STOP_WORDS
        return [
            word
            for word in _WORD_RE.findall(text)
            if len(word) >= self.min_word_length and word not in stop
        ]

    @staticmethod
    def _emotional_themes(words: list[str]) -> dict[str, float]:
        """Puntúa cada tema emocional según su presencia en la letra.

        El peso combina la proporción de coincidencias del léxico con la
        densidad respecto al total de palabras (evita que un texto largo
        con una sola mención puntúe alto).
        """
        if not words:
            return {}
        unique = set(words)
        total = len(words)
        themes: dict[str, float] = {}
        for theme, lexicon in EMOTION_LEXICON.items():
            matches = len(unique & lexicon)
            if matches == 0:
                continue
            density = matches / total
            # Escala suave: 3 coincidencias ya saturan el peso del tema.
            themes[theme] = round(min(1.0, matches / 3.0) * 0.7 + min(1.0, density * 10) * 0.3, 4)
        return dict(sorted(themes.items(), key=lambda item: item[1], reverse=True))

    @staticmethod
    def _sentiment(themes: dict[str, float]) -> str:
        """Sentimiento global a partir de los temas detectados."""
        if not themes:
            return "neutral"
        positive = sum(score for theme, score in themes.items() if theme in POSITIVE_THEMES)
        negative = sum(score for theme, score in themes.items() if theme in NEGATIVE_THEMES)
        if positive > negative * 1.5:
            return "positive"
        if negative > positive * 1.5:
            return "negative"
        return "neutral"

    @staticmethod
    def _confidence(words: list[str], themes: dict[str, float]) -> float:
        """Confianza del análisis (longitud del texto + temas detectados)."""
        confidence = min(0.85, len(words) / 100.0)
        if themes:
            confidence = min(0.95, confidence + 0.1)
        return round(confidence, 4)

    # -- Integración con el catálogo ---------------------------------------

    def analyze_track_lyrics(self, track: Track, lyrics_dir: Path) -> LyricsAnalysis | None:
        """Busca y analiza la letra de una pista en un directorio local.

        Empareja por nombre de fichero de forma tolerante: título, título +
        artista, artista + título y coincidencia parcial sobre nombres
        normalizados (sin acentos, signos ni mayúsculas).

        Args:
            track: Pista del catálogo.
            lyrics_dir: Directorio con los ficheros ``.txt`` de letras.

        Returns:
            El análisis, o ``None`` si no se encontró letra para la pista.
        """
        path = self.find_lyrics_file(track, lyrics_dir)
        if path is None:
            return None
        text = read_lyrics_file(path)
        return self.analyze_lyrics(text) if text is not None else None

    @staticmethod
    def find_lyrics_file(track: Track, lyrics_dir: str | Path) -> Path | None:
        """Localiza el fichero de letras de una pista (o ``None``)."""
        directory = Path(lyrics_dir)
        if not directory.is_dir():
            return None

        files = [path for path in directory.rglob("*.txt") if path.is_file()]
        if not files:
            return None

        by_key = {_normalize_key(path.stem): path for path in files}
        title_key = _normalize_key(track.title)
        artist_key = _normalize_key(track.artist or "")

        for candidate in (title_key, title_key + artist_key, artist_key + title_key):
            if candidate and candidate in by_key:
                return by_key[candidate]

        # Coincidencia parcial: título contenido en el nombre (o viceversa).
        if len(title_key) >= 4:
            for key, path in by_key.items():
                if title_key in key or key in title_key:
                    return path
        return None


def read_lyrics_file(path: str | Path) -> str | None:
    """Lee un fichero de letras probando varias codificaciones.

    Args:
        path: Ruta del fichero ``.txt``.

    Returns:
        El contenido, o ``None`` si no se pudo leer.
    """
    file_path = Path(path)
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return file_path.read_bytes().decode("utf-8", errors="replace")


def create_default_analyzer() -> LyricsAnalyzer:
    """Crea un analizador con la configuración por defecto."""
    return LyricsAnalyzer()
