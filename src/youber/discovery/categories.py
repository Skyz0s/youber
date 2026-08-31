"""Categorías predefinidas y temas para el buscador de canales (uso educativo).

Define las 20 categorías de contenido de YouTube (:class:`ChannelCategory`) y
los temas asociados a cada una (:data:`CATEGORY_TOPICS`), que se usan para
construir búsquedas, clasificar canales descubiertos y calcular similitudes.

Límites éticos: esto es **descubrimiento para investigación de mercado** con
datos públicos; no manipula métricas ni evade sistemas de seguridad.
"""

from __future__ import annotations

from enum import StrEnum


class ChannelCategory(StrEnum):
    """Categorías de contenido de YouTube (valores en español)."""

    TECHNOLOGY = "tecnología"
    EDUCATION = "educación"
    GAMING = "gaming"
    MUSIC = "música"
    LIFESTYLE = "estilo_de_vida"
    SCIENCE = "ciencia"
    BUSINESS = "negocios"
    HEALTH = "salud"
    TRAVEL = "viajes"
    FOOD = "cocina"
    FASHION = "moda"
    SPORTS = "deportes"
    NEWS = "noticias"
    ENTERTAINMENT = "entretenimiento"
    FILM = "cine"
    ANIMATION = "animación"
    PODCAST = "podcast"
    DIY = "manualidades"
    PHOTOGRAPHY = "fotografía"
    MARKETING = "marketing"


# Temas relacionados por categoría (para construir consultas y clasificar).
CATEGORY_TOPICS: dict[ChannelCategory, list[str]] = {
    ChannelCategory.TECHNOLOGY: [
        "python",
        "javascript",
        "ia",
        "machine learning",
        "programación",
        "software",
        "hardware",
        "inteligencia artificial",
        "cybersecurity",
    ],
    ChannelCategory.EDUCATION: [
        "tutorial",
        "curso",
        "aprender",
        "educación",
        "universidad",
        "matemáticas",
        "física",
        "historia",
        "idiomas",
    ],
    ChannelCategory.GAMING: [
        "gameplay",
        "minecraft",
        "fortnite",
        "valorant",
        "lol",
        "zelda",
        "nintendo",
        "pc gaming",
        "retro gaming",
    ],
    ChannelCategory.MUSIC: [
        "música",
        "instrumentos",
        "piano",
        "guitarra",
        "canto",
        "composición",
        "producción musical",
        "beat",
        "armonía",
    ],
    ChannelCategory.LIFESTYLE: [
        "vlog",
        "rutina",
        "bienestar",
        "productividad",
        "minimalismo",
        "organización",
        "viajes",
        "estilo de vida",
    ],
    ChannelCategory.SCIENCE: [
        "ciencia",
        "física",
        "química",
        "biología",
        "astronomía",
        "divulgación",
        "curiosidades",
        "experimentos",
    ],
    ChannelCategory.BUSINESS: [
        "emprendimiento",
        "negocios",
        "finanzas",
        "marketing",
        "ventas",
        "startup",
        "inversiones",
        "liderazgo",
    ],
    ChannelCategory.HEALTH: [
        "salud",
        "fitness",
        "nutrición",
        "meditación",
        "yoga",
        "ejercicio",
        "bienestar",
        "mental health",
    ],
    ChannelCategory.TRAVEL: [
        "viajes",
        "aventura",
        "destinos",
        "mochilero",
        "vlogs de viaje",
        "cultura",
        "explorar",
        "turismo",
    ],
    ChannelCategory.FOOD: [
        "cocina",
        "recetas",
        "gastronomía",
        "comida",
        "chef",
        "hornear",
        "cocinar",
        "restaurante",
    ],
    ChannelCategory.FASHION: [
        "moda",
        "estilo",
        "lookbook",
        "tendencias",
        "outfit",
        "diseño",
        "complementos",
    ],
    ChannelCategory.SPORTS: [
        "deportes",
        "fútbol",
        "baloncesto",
        "tenis",
        "atletismo",
        "entrenamiento",
        "fitness",
    ],
    ChannelCategory.NEWS: [
        "noticias",
        "actualidad",
        "política",
        "economía",
        "internacional",
        "análisis",
    ],
    ChannelCategory.ENTERTAINMENT: [
        "entretenimiento",
        "comedia",
        "sketch",
        "humor",
        "entrevistas",
        "reality",
    ],
    ChannelCategory.FILM: [
        "cine",
        "películas",
        "reseña",
        "crítica",
        "análisis cinematográfico",
        "producción audiovisual",
    ],
    ChannelCategory.ANIMATION: [
        "animación",
        "dibujo",
        "cartoon",
        "3d",
        "blender",
        "stop motion",
        "arte digital",
    ],
    ChannelCategory.PODCAST: [
        "podcast",
        "entrevistas",
        "conversaciones",
        "análisis",
        "actualidad",
    ],
    ChannelCategory.DIY: [
        "manualidades",
        "bricolaje",
        "decoración",
        "reciclaje",
        "proyectos",
        "crear",
    ],
    ChannelCategory.PHOTOGRAPHY: [
        "fotografía",
        "cámara",
        "edición",
        "composición",
        "revelado",
        "analógica",
        "digital",
    ],
    ChannelCategory.MARKETING: [
        "marketing",
        "publicidad",
        "social media",
        "seo",
        "branding",
        "estrategia",
        "comunicación",
    ],
}


def topics_for(category: ChannelCategory) -> list[str]:
    """Devuelve los temas asociados a una categoría (copia, no referencia)."""
    return list(CATEGORY_TOPICS.get(category, []))


def all_categories() -> list[ChannelCategory]:
    """Devuelve todas las categorías en orden de definición."""
    return list(ChannelCategory)


def topic_scores(text: str) -> dict[ChannelCategory, int]:
    """Cuenta cuántos temas de cada categoría aparecen en ``text``.

    Args:
        text: Texto libre (título, descripción, etc.).

    Returns:
        Mapa categoría → número de temas encontrados (solo las que tienen ≥ 1).
    """
    lowered = text.lower()
    scores: dict[ChannelCategory, int] = {}
    for category, topics in CATEGORY_TOPICS.items():
        count = sum(1 for topic in topics if topic.lower() in lowered)
        if count:
            scores[category] = count
    return scores


def infer_category(text: str) -> ChannelCategory | None:
    """Infiere la categoría más probable a partir de un texto.

    Devuelve la categoría con más temas coincidentes, o ``None`` si no hay
    ninguna coincidencia. En caso de empate gana la primera en orden de
    definición (determinista).
    """
    scores = topic_scores(text)
    if not scores:
        return None
    return max(scores, key=lambda category: scores[category])
