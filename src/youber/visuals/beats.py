"""Guion visual: de la escena del guion al prompt que entiende el modelo.

El criterio anterior tenía tres problemas medidos sobre la salida real: el
prompt salía de una plantilla de encuadre con el **tema en español** incrustado
dentro («close up detail of el paso del tiempo»), no describía **acción** ni
**movimiento de cámara** (el modelo de vídeo sabe moverse y no se le pedía), y
los tres bloques de contenido daban **el mismo prompt** (solo cambiaba la
semilla, así que la variedad era falsa).

Aquí el plano se describe con campos explícitos — :class:`VisualBeat` con
cámara, sujeto, acción, escena y luz — todos en inglés, que es el idioma con el
que Wan 2.2 (umt5) y SDXL entienden las descripciones visuales. El tema se
traduce con un **léxico local determinista** (:func:`describe_topic`): sin
servicios, sin red y con el texto original entre paréntesis para poder revisar
de dónde sale todo.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from youber.script.models import SceneType

#: Glosario tema es→en (palabras y frases). Es deliberadamente pequeño y
#: ampliable: traduce lo que sabe y deja el resto tal cual, en vez de inventar.
#: Las frases se buscan **antes** que las palabras sueltas.
TOPIC_GLOSSARY: dict[str, str] = {
    # frases frecuentes
    "paso del tiempo": "the passing of time",
    "paso del dia": "the passing of the day",
    "medio ambiente": "the environment",
    "cambio climatico": "climate change",
    "inteligencia artificial": "artificial intelligence",
    "redes sociales": "social media",
    "vida cotidiana": "everyday life",
    "salud mental": "mental health",
    "primeros pasos": "first steps",
    "luz del amanecer": "dawn light",
    # naturaleza
    "tiempo": "time",
    "mar": "the sea",
    "oceano": "the ocean",
    "rio": "a river",
    "montana": "a mountain",
    "bosque": "a forest",
    "arbol": "a tree",
    "flor": "a flower",
    "lluvia": "rain",
    "niebla": "fog",
    "nieve": "snow",
    "tormenta": "a storm",
    "nube": "a cloud",
    "cielo": "the sky",
    "sol": "the sun",
    "luna": "the moon",
    "estrella": "a star",
    "noche": "night",
    "amanecer": "dawn",
    "atardecer": "sunset",
    "verano": "summer",
    "invierno": "winter",
    "otono": "autumn",
    "primavera": "spring",
    "agua": "water",
    "fuego": "fire",
    "tierra": "earth",
    "viento": "the wind",
    "paisaje": "a landscape",
    "campo": "the countryside",
    "playa": "a beach",
    "desierto": "a desert",
    # ciudad y gente
    "ciudad": "a city",
    "pueblo": "a village",
    "calle": "a street",
    "carretera": "a road",
    "camino": "a path",
    "tren": "a train",
    "coche": "a car",
    "barco": "a boat",
    "avion": "a plane",
    "casa": "a house",
    "ventana": "a window",
    "puerta": "a door",
    "puente": "a bridge",
    "plaza": "a square",
    "mercado": "a market",
    "trabajo": "work",
    "oficina": "an office",
    "escuela": "a school",
    "libro": "a book",
    "musica": "music",
    "arte": "art",
    "deporte": "sport",
    "viaje": "a journey",
    "familia": "family",
    "amigos": "friends",
    "amor": "love",
    "persona": "a person",
    "gente": "people",
    "nino": "a child",
    "manos": "hands",
    "silencio": "silence",
    "memoria": "memory",
    "recuerdo": "a memory",
    "historia": "a story",
    "vida": "life",
    "muerte": "death",
    "miedo": "fear",
    "alegria": "joy",
    "tristeza": "sadness",
    "esperanza": "hope",
    "tecnologia": "technology",
    "futuro": "the future",
    "pasado": "the past",
    "presente": "the present",
    "energia": "energy",
    "luz": "light",
    "sombra": "shadow",
    "color": "colour",
    "manana": "the morning",
    "reloj": "a clock",
    "espejo": "a mirror",
    # adjetivos y verbos útiles
    "rapido": "fast",
    "lento": "slow",
    "grande": "vast",
    "pequeno": "small",
    "viejo": "old",
    "nuevo": "new",
    "moderno": "modern",
    "urbano": "urban",
    "natural": "natural",
    "oscuro": "dark",
    "brillante": "bright",
    "dormido": "sleeping",
    "crecer": "growing",
    "pasar": "passing",
    "paso": "the passing",
    "avanzar": "moving forward",
    "cambiar": "changing",
    "empezar": "beginning",
    "terminar": "ending",
    "fluir": "flowing",
    "respirar": "breathing",
    "caminar": "walking",
    "mirar": "looking",
    "esperar": "waiting",
    "recordar": "remembering",
    "olvidar": "forgetting",
}

#: Artículos y preposiciones que se comen al principio del tema («el mar» → «sea»).
_LEADING_WORDS = frozenset(
    {"el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "mi", "tu", "su"}
)

#: Palabras vacías que se tiran cuando aparecen en medio («of», «the» del original).
_DROPPED_WORDS = frozenset({"de", "del", "a", "al", "en", "con", "para", "por", "y", "o", "que"})


class VisualBeat(BaseModel):
    """Un plano descrito con campos explícitos, en inglés.

    Attributes:
        camera: Movimiento y tipo de plano («slow push in», «aerial drone sweep»).
        subject: Qué se ve («a lone figure», «a weathered facade»).
        action: Qué hace el sujeto (el modelo de vídeo necesita movimiento).
        setting: Dónde ocurre.
        light: Luz de la escena (lo que antes imponía el sufijo de estilo).
    """

    camera: str
    subject: str
    action: str = ""
    setting: str = ""
    light: str = ""

    def describe(self) -> str:
        """El plano en una frase («camera: subject action, setting, light»)."""
        head = f"{self.camera}: " if self.camera else ""
        subject = " ".join(part for part in (self.subject, self.action) if part)
        rest = ", ".join(part for part in (self.setting, self.light) if part)
        text = f"{head}{subject}".strip()
        return f"{text}, {rest}" if rest else text


#: Cuatro encuadres por papel de escena. Se recorren en ciclo y **desfasados**
#: por escena (:func:`beat_for`), de forma que los tres bloques de contenido no
#: repitan el mismo plano (el fallo del criterio anterior).
BEATS_BY_SCENE: dict[SceneType, tuple[VisualBeat, ...]] = {
    SceneType.HOOK: (
        VisualBeat(
            camera="slow push in",
            subject="a lone figure",
            action="standing still while the world rushes past",
            setting="an empty city bridge at first light",
            light="cold dawn light mixed with warm street lamps",
        ),
        VisualBeat(
            camera="aerial drone sweep",
            subject="a vast landscape",
            action="unfolding below as the clouds drift",
            setting="a mountain ridge above a sea of fog",
            light="golden rim light at sunrise",
        ),
        VisualBeat(
            camera="handheld close up",
            subject="a pair of hands",
            action="slowly opening around something small",
            setting="a dim workshop table",
            light="a single warm lamp against deep shadow",
        ),
        VisualBeat(
            camera="low angle wide shot",
            subject="a towering structure",
            action="looming over the viewer",
            setting="a deserted square at dawn",
            light="blue hour haze",
        ),
    ),
    SceneType.INTRO: (
        VisualBeat(
            camera="medium tracking shot",
            subject="a person",
            action="walking unhurried through the scene",
            setting="a quiet neighbourhood street",
            light="soft overcast daylight",
        ),
        VisualBeat(
            camera="observational documentary shot",
            subject="everyday details of the place",
            action="revealing themselves one by one",
            setting="a lived-in interior in the morning",
            light="warm window light",
        ),
        VisualBeat(
            camera="wide shot with layered foreground",
            subject="the main setting",
            action="opening up in depth as the camera drifts",
            setting="a valley seen through tall grass",
            light="low sun and long shadows",
        ),
        VisualBeat(
            camera="slow tilt up",
            subject="a weathered facade",
            action="rising out of the frame",
            setting="an old building against open sky",
            light="pale morning light",
        ),
    ),
    SceneType.CONTENT: (
        VisualBeat(
            camera="close up",
            subject="a textured surface",
            action="changing as the light moves across it",
            setting="a weathered wall with fine cracks",
            light="raking side light that reveals texture",
        ),
        VisualBeat(
            camera="macro shot",
            subject="small drifting details",
            action="passing in and out of focus",
            setting="dust and fibres floating in the air",
            light="a narrow beam of light",
        ),
        VisualBeat(
            camera="over the shoulder",
            subject="hands at work",
            action="moving with quiet routine",
            setting="a cluttered desk by a window",
            light="soft daylight with gentle contrast",
        ),
        VisualBeat(
            camera="static medium shot",
            subject="an ordinary object",
            action="sitting still while the light around it changes",
            setting="an empty room with a view outside",
            light="light sliding slowly across the wall",
        ),
    ),
    SceneType.CLIMAX: (
        VisualBeat(
            camera="low angle under a dramatic sky",
            subject="the horizon",
            action="opening up in a burst of light",
            setting="a storm breaking over open land",
            light="high contrast backlight with glowing clouds",
        ),
        VisualBeat(
            camera="slow motion silhouette",
            subject="a figure",
            action="turning towards the light",
            setting="a windswept ridge at sunset",
            light="blazing backlight and airborne haze",
        ),
        VisualBeat(
            camera="fast push in",
            subject="the heart of the scene",
            action="arriving at the key moment",
            setting="a crowded space falling quiet",
            light="strong directional light with deep shadows",
        ),
        VisualBeat(
            camera="crane up",
            subject="the whole landscape",
            action="revealing itself at once",
            setting="city lights switching on at dusk",
            light="amber and blue tones",
        ),
    ),
    SceneType.CTA: (
        VisualBeat(
            camera="wide serene shot",
            subject="an open road",
            action="leading towards a bright horizon",
            setting="empty countryside at sunrise",
            light="hopeful warm light",
        ),
        VisualBeat(
            camera="static composition with negative space",
            subject="a calm interior",
            action="holding still for a moment",
            setting="a room with a single window",
            light="soft even light",
        ),
        VisualBeat(
            camera="slow pull back",
            subject="a person",
            action="turning to look towards the viewer",
            setting="the same place as the opening shot",
            light="gentle daylight",
        ),
        VisualBeat(
            camera="soft focus ending",
            subject="light through leaves",
            action="flickering gently",
            setting="a quiet garden",
            light="dappled warm light",
        ),
    ),
}

#: Encuadres de reserva (planos sin escena o tipo desconocido).
GENERIC_BEATS: tuple[VisualBeat, ...] = (
    BEATS_BY_SCENE[SceneType.HOOK][0],
    BEATS_BY_SCENE[SceneType.CONTENT][0],
    BEATS_BY_SCENE[SceneType.CONTENT][1],
    BEATS_BY_SCENE[SceneType.CLIMAX][0],
    BEATS_BY_SCENE[SceneType.INTRO][0],
    BEATS_BY_SCENE[SceneType.CTA][0],
)


def beat_for(scene_type: SceneType | None, index: int) -> VisualBeat:
    """Encuadre para el plano ``index`` de una escena.

    El índice se usa **desfasado por escena** (lo pasa ``build_shot_plan``):
    así los tres bloques de contenido reciben encuadres distintos en vez de
    repetir el primero.
    """
    beats = BEATS_BY_SCENE.get(scene_type) if scene_type is not None else None
    if not beats:
        beats = GENERIC_BEATS
    return beats[index % len(beats)]


def _words(topic: str) -> list[str]:
    """Palabras del tema, en minúsculas y sin signos."""
    cleaned = "".join(
        char if (char.isalnum() or char.isspace()) else " " for char in topic.lower()
    )
    return cleaned.split()


def describe_topic(topic: str) -> str:
    """Describe el tema en inglés con el léxico local (best-effort).

    Traduce las frases y palabras que conoce, se come artículos y preposiciones
    y deja en paz lo que no sabe (mejor una palabra sin traducir que una
    invención). Si no traduce nada, devuelve el tema tal cual.
    """
    words = _words(topic)
    while words and words[0] in _LEADING_WORDS:
        words.pop(0)
    if not words:
        return topic.strip()
    out: list[str] = []
    index = 0
    while index < len(words):
        matched = False
        for size in (4, 3, 2):
            if index + size <= len(words):
                phrase = " ".join(words[index : index + size])
                if phrase in TOPIC_GLOSSARY:
                    out.append(TOPIC_GLOSSARY[phrase])
                    index += size
                    matched = True
                    break
        if matched:
            continue
        word = words[index]
        if word in TOPIC_GLOSSARY:
            out.append(TOPIC_GLOSSARY[word])
        elif word not in _DROPPED_WORDS:
            out.append(word)
        index += 1
    text = " ".join(out).strip()
    return text or topic.strip()


def topic_theme(topic: str) -> str:
    """El tema para el prompt: inglés y, si se ha traducido, el original detrás.

    Mantener el original entre paréntesis deja traza de dónde sale el tema
    (útil al revisar el guion) sin cargar al modelo con una frase en un idioma
    que no lee bien.
    """
    original = topic.strip()
    translated = describe_topic(original)
    if not original or translated.lower() == original.lower():
        return original
    return f'{translated} ("{original}")'


def compose_prompt(
    beat: VisualBeat,
    *,
    topic: str | None = None,
    keywords: Sequence[str] = (),
    atmosphere: str | None = None,
    tone: str | None = None,
    style_suffix: str | None = None,
) -> str:
    """Compone el prompt final de un plano.

    Orden: descripción visual (cámara, sujeto, acción, escena, luz) → atmósfera
    del mood → términos de contenido → tema (traducido) → tono → sufijo de
    estilo. Todo en inglés salvo el original del tema, que va entre paréntesis.
    """
    parts = [beat.describe()]
    if atmosphere:
        parts.append(atmosphere)
    terms = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    if terms:
        parts.append("featuring " + ", ".join(terms))
    prompt = ", ".join(part for part in parts if part)
    extras: list[str] = []
    if topic:
        extras.append(f"theme: {topic_theme(topic)}")
    if tone:
        extras.append(f"tone: {tone}")
    if extras:
        prompt = f"{prompt}; " + "; ".join(extras)
    if style_suffix:
        prompt = f"{prompt}; {style_suffix}"
    return prompt


def beat_from_template(template: str, topic: str) -> VisualBeat:
    """Encuadre a partir de una plantilla antigua con ``{topic}``.

    Se mantiene para no romper a quien pase una plantilla suelta a
    :func:`youber.visuals.prompts.shot_prompt`.
    """
    return VisualBeat(camera="", subject=template.format(topic=topic))
