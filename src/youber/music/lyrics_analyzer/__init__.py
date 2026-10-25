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
            "blue", "broken", "break", "broke", "breaking", "crack", "shatter",
            "wound", "scar", "bleed", "hurt", "ache", "pain", "fear", "scared",
            "hollow", "numb", "ghost", "fade", "fading", "gone", "lose", "left",
            "leaving", "ending", "dead", "dying", "drown", "blame", "regret",
            "mistake", "liar", "lie", "betray", "cold", "storm", "wreck",
            "romper", "romperse", "roto", "rota", "herida", "cicatriz", "sangrar",
            "doler", "miedo", "asustado", "asustada", "hueco", "fantasma", "perder", "perdido", "final", "muerto", "morir",
            "ahogar", "culpa", "arrepentir", "error", "mentira", "mentiroso",
            "traicion", "frio", "tormenta", "caer", "caida", "hundir", "naufragio",
            "hurts", "cries", "cried", "aching", "scars", "wounds",
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
POSITIVE_THEMES = frozenset({"felicidad", "amor", "energia"})
NEGATIVE_THEMES = frozenset({"tristeza"})
#: Temas atmosféricos: describen tono, no polaridad.
NEUTRAL_THEMES = frozenset({"calma", "misterio"})

#: Cuánto pesa cada tema en la polaridad (energía pesa menos que felicidad/amor).
THEME_POLARITY: dict[str, float] = {
    "felicidad": 1.0,
    "amor": 0.9,
    "energia": 0.35,
    "tristeza": -1.0,
}

#: Negaciones: invierten la polaridad de las NEGATION_WINDOW palabras siguientes.
NEGATIONS: frozenset[str] = frozenset(
    {
        "no", "not", "never", "none", "nothing", "nobody", "nowhere", "without",
        "nada", "nadie", "nunca", "jamas", "tampoco", "sin", "ni",
        "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "isn't", "isnt",
        "aren't", "arent", "wasn't", "wasnt", "weren't", "werent", "can't", "cant",
        "cannot", "won't", "wont", "wouldn't", "wouldnt", "shouldn't", "shouldnt",
        "couldn't", "couldnt", "ain't", "aint",
    }
)
NEGATION_WINDOW = 3

#: Términos con evidencia clara. El resto del léxico (genéricos) pesa la mitad.
STRONG_TERMS: dict[str, frozenset[str]] = {
    "felicidad": frozenset(
        {
            "feliz", "felicidad", "alegria", "contento", "contenta", "maravilloso",
            "maravillosa", "fantastico", "increible", "genial", "perfecto",
            "perfecta", "happy", "happiness", "joy", "joyful", "wonderful",
        }
    ),
    "tristeza": frozenset(
        {
            "triste", "tristeza", "llanto", "llorar", "llorando", "lagrima",
            "lagrimas", "dolor", "doloroso", "sufrimiento", "sufrir", "pena",
            "nostalgia", "melancolia", "sollozo", "depresion", "desesperanza",
            "solo", "sola", "solitario", "perdida", "adios", "olvido", "roto",
            "rota", "herida", "cicatriz", "culpa", "mentira", "traicion", "miedo",
            "sad", "sadness", "cry", "crying", "tear", "tears", "sob", "weep",
            "grief", "sorrow", "heartbreak", "heartbroken", "lonely", "loneliness",
            "alone", "goodbye", "broken", "hurt", "ache", "pain", "fear", "scared",
            "hollow", "numb", "ghost", "lost", "regret", "blame", "liar", "betray",
        }
    ),
    "energia": frozenset(
        {
            "energia", "fuerza", "poder", "intenso", "intensa", "vibrante", "fuego",
            "fuerte", "salvaje", "energy", "power", "powerful", "strong", "strength",
            "force", "intense", "fire", "wild", "burn", "fight", "rise",
        }
    ),
    "calma": frozenset(
        {
            "calma", "paz", "sereno", "serena", "tranquilo", "tranquila", "apacible",
            "placido", "quietud", "calm", "peace", "peaceful", "tranquil", "serene",
            "serenity", "relax",
        }
    ),
    "misterio": frozenset(
        {
            "misterio", "misterioso", "misteriosa", "enigmatico", "enigmatica",
            "secreto", "oculto", "oculta", "penumbra", "niebla", "bruma",
            "mystery", "mysterious", "enigmatic", "cryptic", "secret", "hidden",
            "concealed", "fog", "mist", "unknown",
        }
    ),
    "amor": frozenset(
        {
            "amor", "amante", "amada", "amado", "ternura", "devocion", "beso",
            "abrazo", "corazon", "deseo", "love", "lover", "beloved", "darling",
            "adore", "cherish", "affection", "devotion", "kiss", "heart", "desire",
        }
    ),
}

_TERM_WEIGHT_STRONG = 1.0
_TERM_WEIGHT_WEAK = 0.5
_NEGATION_FACTOR = 0.75
_NEGATION_PRESSURE = 0.12
_NEGATION_PRESSURE_CAP = 1.2

#: palabra -> ((tema, peso), ...) construido a partir del léxico.
_WORD_THEMES: dict[str, tuple[tuple[str, float], ...]] = {}
for _theme, _lexicon in EMOTION_LEXICON.items():
    _strong = STRONG_TERMS.get(_theme, frozenset())
    for _word in sorted(_lexicon):
        _weight = _TERM_WEIGHT_STRONG if _word in _strong else _TERM_WEIGHT_WEAK
        _WORD_THEMES[_word] = (*_WORD_THEMES.get(_word, ()), (_theme, _weight))

#: Tokenizador que conserva los apóstrofos («don't» es una sola palabra).
_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Divide el texto en palabras, manteniendo contracciones y negaciones."""
    return [token.replace("\u2019", "'") for token in _TOKEN_RE.findall(text)]

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
        tokens = _tokenize(text_clean)
        themes, sentiment = self._score_lyrics(tokens)
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

    def _score_lyrics(self, tokens: list[str]) -> tuple[dict[str, float], str]:
        """Puntúa temas y sentimiento sobre la secuencia de palabras.

        A diferencia de un conteo plano, aquí importa el orden: una negación
        (``no``, ``never``, ``sin``…) invierte la polaridad de las palabras que
        vienen detrás, y los términos con evidencia clara pesan más que los
        genéricos (``heartbreak`` frente a ``night``).
        """
        raw: dict[str, float] = {}
        positive = 0.0
        negative = 0.0
        negate_until = -1
        negations = 0

        for index, token in enumerate(tokens):
            if token in NEGATIONS:
                negate_until = index + NEGATION_WINDOW
                negations += 1
                continue

            hits = _WORD_THEMES.get(token.split("'")[0])
            if not hits:
                continue

            negated = index <= negate_until
            for theme, weight in hits:
                # La palabra negada sigue contando para el tema, pero mucho menos.
                raw[theme] = raw.get(theme, 0.0) + weight * (0.4 if negated else 1.0)

                polarity = THEME_POLARITY.get(theme, 0.0)
                if polarity == 0.0:
                    continue
                if negated:
                    # «No te quiero» resta, pero «no llores» no suma: negar una
                    # tristeza solo la cancela, no convierte la letra en alegre.
                    if polarity > 0:
                        negative += weight * _NEGATION_FACTOR
                    continue
                value = weight * polarity
                if value > 0:
                    positive += value
                else:
                    negative -= value

        # Muchas negaciones seguidas son señal de tensión, no de calma.
        negative += min(_NEGATION_PRESSURE_CAP, negations * _NEGATION_PRESSURE)

        themes = {
            theme: round(min(1.0, score / 3.0), 4)
            for theme, score in raw.items()
            if score > 0
        }
        themes = dict(sorted(themes.items(), key=lambda item: item[1], reverse=True))
        return themes, self._sentiment(positive, negative)

    @staticmethod
    def _sentiment(positive: float, negative: float) -> str:
        """Sentimiento global a partir de la evidencia positiva y negativa.

        ``calma`` y ``misterio`` no aportan polaridad: una letra solo
        atmosférica se queda en ``neutral`` en vez de contar como positiva.
        """
        if positive <= 0.0 and negative <= 0.0:
            return "neutral"
        if positive >= 1.2 and positive > negative * 1.8:
            return "positive"
        if negative >= 1.0 and negative > positive * 1.15:
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
