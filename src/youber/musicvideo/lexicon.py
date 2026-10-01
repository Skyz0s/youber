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

# -- English (mitad del catálogo canta en inglés) ----------------------------

SUBJECTS.update(
    {
        "life": "a life unfolding",
        "death": "a final breath",
        "love": "two people almost touching",
        "heart": "a beating heart",
        "soul": "a restless soul",
        "hands": "a pair of open hands",
        "eyes": "a pair of searching eyes",
        "skin": "bare skin",
        "voice": "a voice in the dark",
        "shadow": "a long shadow",
        "shadows": "a long shadow",
        "light": "a shaft of light",
        "time": "a clock running down",
        "fear": "a trembling figure",
        "dream": "a figure half asleep",
        "dreams": "a figure half asleep",
        "memory": "a fading photograph",
        "road": "a long road",
        "door": "a half-open door",
        "window": "a rain-streaked window",
        "mirror": "a cracked mirror",
        "house": "an empty house",
        "home": "an empty house",
        "city": "a sleeping city",
        "sea": "a restless sea",
        "ocean": "a restless sea",
        "rain": "rain on glass",
        "fire": "a small fire",
        "sky": "an open sky",
        "moon": "the moon",
        "sun": "the low sun",
        "star": "distant stars",
        "stars": "distant stars",
        "flower": "a single flower",
        "tree": "a bare tree",
        "river": "a dark river",
        "wind": "wind in the trees",
        "snow": "falling snow",
        "silence": "an empty room",
        "child": "a small child",
        "people": "a crowd of strangers",
        "world": "the world from above",
        "freedom": "a figure running free",
        "truth": "a plain mirror",
        "story": "pages turning",
        "moment": "a fleeting moment",
        "night": "the night sky",
        "day": "an open day",
        "body": "a still body",
        "blood": "a drop of blood",
        "tear": "a single tear",
        "tears": "a single tear",
        "kiss": "two faces inches apart",
        "hug": "an embrace",
        "words": "words hanging in the air",
        "breath": "a held breath",
        "name": "a name written in dust",
        "war": "a battlefield at dawn",
        "wrath": "a clenched fist",
        "anger": "a clenched fist",
        "hate": "a clenched fist",
        "hope": "a figure facing the light",
        "ghost": "a pale figure",
        "stone": "a weathered stone",
        "wall": "a crumbling wall",
        "storm": "a gathering storm",
        "winter": "a bare winter landscape",
        "summer": "a sunlit summer field",
        "autumn": "a street covered in leaves",
        "spring": "branches coming into bloom",
    }
)

ACTIONS.update(
    {
        "walk": "walking slowly forward",
        "walking": "walking slowly forward",
        "run": "running hard",
        "running": "running hard",
        "fall": "falling through the frame",
        "falling": "falling through the frame",
        "fly": "drifting upward",
        "wait": "waiting in the still air",
        "waiting": "waiting in the still air",
        "remember": "remembering something lost",
        "forget": "slowly vanishing",
        "search": "searching through the scene",
        "lose": "drifting away",
        "lost": "drifting away",
        "cry": "as tears form",
        "crying": "as tears form",
        "laugh": "breaking into a laugh",
        "scream": "shouting into the void",
        "shout": "shouting into the void",
        "sleep": "sleeping",
        "wake": "waking up",
        "dance": "dancing",
        "sing": "singing",
        "look": "looking straight into the lens",
        "breathe": "breathing slowly",
        "born": "coming into the light",
        "die": "fading out",
        "live": "choosing to stay",
        "shine": "glowing and pulsing",
        "burn": "burning slowly",
        "break": "shattering",
        "heal": "healing",
        "travel": "travelling onward",
        "grow": "growing",
        "stay": "standing still",
        "leave": "walking away",
        "return": "coming back",
        "hold": "holding on tightly",
        "hide": "hiding in the shadows",
        "reach": "reaching out a hand",
        "give": "offering something",
        "feel": "feeling every second",
        "change": "transforming",
        "escape": "breaking free and running",
        "stop": "coming to a halt",
        "push": "pushing forward",
        "press": "pressing hard",
    }
)

PLACES.update(
    {
        "night": "under a dark night sky",
        "day": "in broad daylight",
        "dawn": "at first light",
        "sunset": "at sunset",
        "sea": "beside the open sea",
        "ocean": "beside the open sea",
        "beach": "on an empty beach",
        "city": "on a rain-slicked city street",
        "street": "along a narrow street",
        "field": "in open countryside",
        "mountain": "on a mountain ridge",
        "forest": "deep in a forest",
        "desert": "in a vast desert",
        "house": "inside a quiet room",
        "home": "inside a quiet room",
        "room": "inside a quiet room",
        "window": "by a tall window",
        "car": "on an empty road",
        "road": "on an empty road",
        "train": "through a train window",
        "bar": "in a dim bar",
        "sky": "against an open sky",
        "rain": "in the rain",
        "fog": "in thick fog",
        "snow": "in falling snow",
        "river": "along a dark river",
        "winter": "in cold winter air",
        "summer": "in warm summer air",
        "autumn": "in autumn leaves",
        "spring": "among fresh blossoms",
        "work": "in a bare office",
        "office": "in a bare office",
        "church": "in a silent old church",
        "bridge": "on a bridge over the water",
        "war": "on a battlefield at dawn",
    }
)

LIGHTS.update(
    {
        "night": "low key moonlight and deep shadow",
        "sun": "warm golden sunlight",
        "sunlight": "warm golden sunlight",
        "dawn": "cold dawn light",
        "sunset": "amber sunset backlight",
        "rain": "flat grey rain light",
        "fog": "soft diffused fog light",
        "fire": "the flicker of firelight",
        "moon": "pale moonlight",
        "moonlight": "pale moonlight",
        "shadow": "hard shadow and rim light",
        "shadows": "hard shadow and rim light",
        "bright": "bright blown-out highlights",
        "dark": "low key lighting with deep shadows",
        "darkness": "low key lighting with deep shadows",
        "snow": "cold even snowlight",
        "summer": "harsh midday sun",
        "winter": "cold blue winter light",
        "light": "a single warm lamp",
    }
)

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

#: Encuadres de reserva por ánimo (cuando la línea no aporta imagen reconocible).
#: Dos variantes por ánimo: el índice de la línea elige, así dos líneas sin
#: imagen reconocible no acaban con el mismo plano.
FALLBACK_BEATS: dict[str, tuple[VisualBeat, ...]] = {
    str(Mood.SAD): (
        VisualBeat(
            camera="slow push in",
            subject="a lone figure",
            action="standing still in the rain",
            setting="an empty street at night",
            light="cold blue light",
        ),
        VisualBeat(
            camera="static wide shot",
            subject="an empty room",
            action="holding very still",
            setting="a bare room with a single window",
            light="grey light through thin curtains",
        ),
    ),
    str(Mood.HAPPY): (
        VisualBeat(
            camera="handheld tracking shot",
            subject="a person",
            action="walking in the open air",
            setting="a sunlit field",
            light="warm golden light",
        ),
        VisualBeat(
            camera="low angle slow push in",
            subject="a figure",
            action="laughing and looking up",
            setting="a bright open street",
            light="clear afternoon sun",
        ),
    ),
    str(Mood.ENERGETIC): (
        VisualBeat(
            camera="fast push in",
            subject="a running figure",
            action="moving at full speed",
            setting="a city street in motion",
            light="hard contrast light",
        ),
        VisualBeat(
            camera="whip pan",
            subject="a crowd",
            action="surging forward",
            setting="a packed night street",
            light="flashing neon light",
        ),
    ),
    str(Mood.RELAXING): (
        VisualBeat(
            camera="static wide shot",
            subject="an open landscape",
            action="resting in the stillness",
            setting="a quiet valley at dawn",
            light="soft even light",
        ),
        VisualBeat(
            camera="slow tilt down",
            subject="still water",
            action="rippling faintly",
            setting="a calm lake at dusk",
            light="pale dusk light",
        ),
    ),
    str(Mood.MYSTERIOUS): (
        VisualBeat(
            camera="slow tilt up",
            subject="a dark silhouette",
            action="emerging from the fog",
            setting="an empty alley",
            light="fog and deep shadow",
        ),
        VisualBeat(
            camera="slow dolly in",
            subject="an unlit doorway",
            action="standing ajar",
            setting="a corridor in the dark",
            light="a narrow strip of light",
        ),
    ),
}

#: Encuadres de reserva genéricos (sin ánimo conocido).
GENERIC_BEATS: tuple[VisualBeat, ...] = (
    VisualBeat(
        camera="slow push in",
        subject="an evocative scene",
        action="holding for a moment",
        setting="an open space",
        light="soft natural light",
    ),
    VisualBeat(
        camera="medium tracking shot",
        subject="a figure",
        action="moving slowly through the frame",
        setting="a quiet place",
        light="low ambient light",
    ),
    VisualBeat(
        camera="static composition",
        subject="a still object",
        action="waiting in the shadow",
        setting="an empty interior",
        light="a single soft light",
    ),
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


def _light_for(text: str, tokens: list[str], mood: Mood | None, index: int) -> str:
    """Luz de la escena: la de la línea si la nombra; si no, la del ánimo."""
    match = _match_longest(tokens, LIGHTS)
    if match is not None:
        return match[1]
    return _mood_beat(mood, index).light


def _mood_beat(mood: Mood | None, index: int = 0) -> VisualBeat:
    """Encuadre de reserva del ánimo (varía con el índice de la línea)."""
    variants = GENERIC_BEATS if mood is None else FALLBACK_BEATS.get(str(mood), GENERIC_BEATS)
    return variants[index % len(variants)]


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
    fallback = _mood_beat(mood, index)

    subject = _match_longest(tokens, SUBJECTS)
    action = _match_longest(tokens, ACTIONS)
    place = _match_longest(tokens, PLACES)

    return VisualBeat(
        camera=_camera_for(text, section, index),
        subject=subject[1] if subject else fallback.subject,
        action=action[1] if action else fallback.action,
        setting=place[1] if place else fallback.setting,
        light=_light_for(text, tokens, mood, index),
    )
