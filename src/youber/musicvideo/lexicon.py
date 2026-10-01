"""De una línea de la letra a un **plano** concreto (la letra dirige la imagen).

El criterio anterior elegía el encuadre por el *papel de la escena* de un guion
de vídeo hablado (gancho, desarrollo...) y no miraba la letra: daba igual lo
que se cantara, el plano era el mismo. Aquí el plano sale **de la línea**: el
léxico localiza el sujeto, la acción, el lugar y la luz de lo que se cuenta y
compone un :class:`~youber.visuals.beats.VisualBeat` en inglés.

Todo es **offline y determinista**: léxico local (español → inglés), sin
servicios ni red. El léxico traduce lo que sabe y deja en paz lo que no; si una
línea no aporta nada reconocible, el plano cae al encuadre de reserva de su
ánimo (antes que inventar).
"""

from __future__ import annotations

import hashlib
import unicodedata

from youber.music.models import Mood
from youber.musicvideo.models import SongSection
from youber.visuals.beats import TOPIC_GLOSSARY, VisualBeat

#: Sujeto: lo que se ve (persona, objeto, paisaje).
SUBJECTS: dict[str, str] = {
    "vida": "a life unfolding",
    "muerte": "a final breath",
    "amor": "two people almost touching",
    "corazon": "a beating heart",
    "alma": "a restless soul",
    "manos": "a pair of open hands",
    "ojos": "a pair of searching eyes",
    "piel": "bare skin",
    "voz": "a voice in the dark",
    "sombra": "a long shadow",
    "luz": "a shaft of light",
    "tiempo": "a clock running down",
    "miedo": "a trembling figure",
    "sueno": "a figure half asleep",
    "recuerdo": "a faded photograph",
    "memoria": "a fading photograph",
    "camino": "a long road",
    "puerta": "a half-open door",
    "ventana": "a rain-streaked window",
    "espejo": "a cracked mirror",
    "casa": "an empty house",
    "ciudad": "a sleeping city",
    "mar": "a restless sea",
    "lluvia": "rain on glass",
    "fuego": "a small fire",
    "cielo": "an open sky",
    "luna": "the moon",
    "sol": "the low sun",
    "estrella": "distant stars",
    "flor": "a single flower",
    "arbol": "a bare tree",
    "rio": "a dark river",
    "viento": "wind in the trees",
    "nieve": "falling snow",
    "silencio": "an empty room",
    "nino": "a small child",
    "gente": "a crowd of strangers",
    "mundo": "the world from above",
    "libertad": "a figure running free",
    "verdad": "a plain mirror",
    "historia": "pages turning",
    "momento": "a fleeting moment",
    "noche": "the night sky",
    "dia": "an open day",
    "invierno": "a bare winter landscape",
    "verano": "a sunlit summer field",
    "otono": "a street covered in leaves",
    "primavera": "branches coming into bloom",
    "cuerpo": "a still body",
    "sangre": "a drop of blood",
    "lagrima": "a single tear",
    "beso": "two faces inches apart",
    "abrazo": "an embrace",
    "palabra": "words hanging in the air",
    "silencio2": "a held breath",
}

#: Acción: qué hace el sujeto (el modelo de vídeo necesita movimiento).
ACTIONS: dict[str, str] = {
    "caminar": "walking slowly forward",
    "correr": "running hard",
    "caer": "falling through the frame",
    "volar": "drifting upward",
    "esperar": "waiting in the still air",
    "recordar": "remembering something lost",
    "olvidar": "slowly vanishing",
    "buscar": "searching through the scene",
    "perder": "drifting away",
    "amar": "reaching towards someone",
    "llorar": "as tears form",
    "reir": "breaking into a laugh",
    "gritar": "shouting into the void",
    "dormir": "sleeping",
    "despertar": "waking up",
    "bailar": "dancing",
    "cantar": "singing",
    "mirar": "looking straight into the lens",
    "respirar": "breathing slowly",
    "nacer": "coming into the light",
    "morir": "fading out",
    "vivir": "choosing to stay",
    "brillar": "glowing and pulsing",
    "quemar": "burning slowly",
    "romper": "shattering",
    "sanar": "healing",
    "viajar": "travelling onward",
    "crecer": "growing",
    "quedar": "standing still",
    "irse": "walking away",
    "volver": "coming back",
    "soltar": "letting go",
    "abrazar": "holding on tightly",
    "esconder": "hiding in the shadows",
    "pedir": "reaching out a hand",
    "dar": "offering something",
    "sentir": "feeling every second",
    "soñar": "dreaming",
    "cambiar": "transforming",
    "escapar": "breaking free and running",
}

#: Lugar: dónde ocurre la escena.
PLACES: dict[str, str] = {
    "noche": "under a dark night sky",
    "dia": "in broad daylight",
    "amanecer": "at first light",
    "atardecer": "at sunset",
    "mar": "beside the open sea",
    "playa": "on an empty beach",
    "ciudad": "on a rain-slicked city street",
    "calle": "along a narrow street",
    "campo": "in open countryside",
    "montana": "on a mountain ridge",
    "bosque": "deep in a forest",
    "desierto": "in a vast desert",
    "casa": "inside a quiet room",
    "cuarto": "inside a quiet room",
    "ventana": "by a tall window",
    "coche": "on an empty road",
    "carretera": "on an empty road",
    "tren": "through a train window",
    "bar": "in a dim bar",
    "fiesta": "in a crowded room",
    "cielo": "against an open sky",
    "lluvia": "in the rain",
    "niebla": "in thick fog",
    "nieve": "in falling snow",
    "rio": "along a dark river",
    "invierno": "in a cold winter air",
    "verano": "in warm summer air",
    "otono": "in autumn leaves",
    "primavera": "among fresh blossoms",
    "trabajo": "in a bare office",
    "oficina": "in a bare office",
    "iglesia": "in a silent old church",
    "puente": "on a bridge over the water",
}

#: Luz: cómo ilumina la escena (la dicta la línea, no el estilo).
LIGHTS: dict[str, str] = {
    "noche": "low key moonlight and deep shadow",
    "sol": "warm golden sunlight",
    "amanecer": "cold dawn light",
    "atardecer": "amber sunset backlight",
    "lluvia": "flat grey rain light",
    "niebla": "soft diffused fog light",
    "fuego": "the flicker of firelight",
    "luna": "pale moonlight",
    "sombra": "hard shadow and rim light",
    "brillante": "bright blown-out highlights",
    "oscuro": "low key lighting with deep shadows",
    "nieve": "cold even snowlight",
    "verano": "harsh midday sun",
    "invierno": "cold blue winter light",
}

#: Movimientos de cámara por papel de escena (el índice varía el encuadre).
CAMERAS_CHORUS: tuple[str, ...] = (
    "fast push in",
    "handheld close up",
    "slow motion wide shot",
    "low angle rising shot",
)
CAMERAS_VERSE: tuple[str, ...] = (
    "slow push in",
    "medium tracking shot",
    "static medium shot",
    "observational shot",
)
CAMERAS_INTRO: tuple[str, ...] = (
    "slow push in",
    "slow aerial sweep",
    "slow tilt up",
    "wide establishing shot",
)
CAMERAS_OUTRO: tuple[str, ...] = (
    "slow pull back",
    "static wide shot",
    "soft focus ending",
    "drifting aerial shot",
)
CAMERAS_GENERIC: tuple[str, ...] = (
    "slow push in",
    "medium tracking shot",
    "slow tilt up",
)

_CAMERAS_BY_SECTION: dict[SongSection, tuple[str, ...]] = {
    SongSection.INTRO: CAMERAS_INTRO,
    SongSection.VERSE: CAMERAS_VERSE,
    SongSection.PRE_CHORUS: CAMERAS_VERSE,
    SongSection.CHORUS: CAMERAS_CHORUS,
    SongSection.BRIDGE: CAMERAS_VERSE,
    SongSection.OUTRO: CAMERAS_OUTRO,
}

#: Encuadre de reserva por ánimo (cuando la línea no aporta imagen reconocible).
FALLBACK_BEATS: dict[str, VisualBeat] = {
    str(Mood.SAD): VisualBeat(
        camera="slow push in",
        subject="a lone figure",
        action="standing still in the rain",
        setting="an empty street at night",
        light="cold blue light",
    ),
    str(Mood.HAPPY): VisualBeat(
        camera="handheld tracking shot",
        subject="a person",
        action="walking in the open air",
        setting="a sunlit field",
        light="warm golden light",
    ),
    str(Mood.ENERGETIC): VisualBeat(
        camera="fast push in",
        subject="a running figure",
        action="moving at full speed",
        setting="a city street in motion",
        light="hard contrast light",
    ),
    str(Mood.RELAXING): VisualBeat(
        camera="static wide shot",
        subject="an open landscape",
        action="resting in the stillness",
        setting="a quiet valley at dawn",
        light="soft even light",
    ),
    str(Mood.MYSTERIOUS): VisualBeat(
        camera="slow tilt up",
        subject="a dark silhouette",
        action="emerging from the fog",
        setting="an empty alley",
        light="fog and deep shadow",
    ),
}

#: Encuadre de reserva genérico (sin ánimo conocido).
GENERIC_BEAT = VisualBeat(
    camera="slow push in",
    subject="an evocative scene",
    action="holding for a moment",
    setting="an open space",
    light="soft natural light",
)


def _strip_accents(text: str) -> str:
    """Quita los acentos (para casar el léxico sin duplicar claves)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize(text: str) -> str:
    """Normaliza una línea: minúsculas, sin acentos y sin signos."""
    lowered = _strip_accents(text.lower())
    return " ".join(
        "".join(char if char.isalnum() else " " for char in lowered).split()
    )


def _tokens(text: str) -> list[str]:
    """Palabras normalizadas de un texto."""
    return normalize(text).split()


def _stable(text: str) -> int:
    """Entero estable para variar el encuadre de forma determinista."""
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:6], "big")


def _match_longest(tokens: list[str], table: dict[str, str]) -> tuple[str, str] | None:
    """Busca la clave más larga del léxico presente en la línea.

    Se prueban frases de hasta tres palabras antes que las sueltas, para que
    «primeros pasos» gane a «paso».

    Returns:
        ``(clave, valor)`` de la coincidencia más larga, o ``None``.
    """
    for size in (3, 2, 1):
        for index in range(0, len(tokens) - size + 1):
            phrase = " ".join(tokens[index : index + size])
            if phrase in table:
                return phrase, table[phrase]
    return None


def _all_matches(tokens: list[str], table: dict[str, str]) -> list[str]:
    """Todos los valores del léxico presentes en la línea (sin duplicados)."""
    found: list[str] = []
    for token in tokens:
        value = table.get(token)
        if value and value not in found:
            found.append(value)
    return found


def keywords_from_line(text: str, *, limit: int = 6) -> list[str]:
    """Términos en inglés de la línea para buscar B-roll (best-effort).

    Combina el léxico propio con el glosario de temas de
    :mod:`youber.visuals.beats`; lo que no se sabe se deja en paz.
    """
    tokens = _tokens(text)
    terms: list[str] = []
    for table in (SUBJECTS, ACTIONS, PLACES, TOPIC_GLOSSARY):
        for value in _all_matches(tokens, table):
            if value not in terms:
                terms.append(value)
    return terms[:limit]


def _camera_for(text: str, section: SongSection, index: int) -> str:
    """Movimiento de cámara del plano (por papel de escena, variado por línea)."""
    options = _CAMERAS_BY_SECTION.get(section, CAMERAS_GENERIC)
    return options[(_stable(text) + index) % len(options)]


def _light_for(text: str, tokens: list[str], mood: Mood | None) -> str:
    """Luz de la escena: la de la línea si la nombra; si no, la del ánimo."""
    match = _match_longest(tokens, LIGHTS)
    if match is not None:
        return match[1]
    return _mood_beat(mood).light


def _mood_beat(mood: Mood | None) -> VisualBeat:
    """Encuadre de reserva del ánimo (genérico si es ``None``)."""
    if mood is None:
        return GENERIC_BEAT
    return FALLBACK_BEATS.get(str(mood), GENERIC_BEAT)


def beat_from_line(
    text: str,
    *,
    index: int = 0,
    section: SongSection = SongSection.UNKNOWN,
    mood: Mood | None = None,
) -> VisualBeat:
    """Convierte una línea de la letra en el plano que la ilustra.

    Toma de la línea el sujeto, la acción y el lugar con el léxico local; la
    luz sale de la línea o del ánimo, y el movimiento de cámara del papel de
    escena (estribillo más dinámico), variado de forma determinista por línea.
    Si la línea no aporta imagen reconocible, el sujeto cae al encuadre de
    reserva del ánimo; así nunca sale un plano vacío.

    Args:
        text: La línea (tal cual se canta).
        index: Posición de la línea (varía el encuadre sin romper el determinismo).
        section: Tramo de la canción al que pertenece.
        mood: Ánimo global de la pieza (para el sujeto/luz de reserva).

    Returns:
        El :class:`~youber.visuals.beats.VisualBeat` del plano, en inglés.
    """
    tokens = _tokens(text)
    fallback = _mood_beat(mood)

    subject = _match_longest(tokens, SUBJECTS)
    action = _match_longest(tokens, ACTIONS)
    place = _match_longest(tokens, PLACES)

    return VisualBeat(
        camera=_camera_for(text, section, index),
        subject=subject[1] if subject else fallback.subject,
        action=action[1] if action else fallback.action,
        setting=place[1] if place else fallback.setting,
        light=_light_for(text, tokens, mood),
    )
