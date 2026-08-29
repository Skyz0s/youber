"""Recomendaciones automáticas y recursos de aprendizaje por regla.

Cada violación de axe-core se puede acompañar de una sugerencia de
corrección concreta y de enlaces a recursos educativos (MDN, WebAIM, W3C)
para que el framework también sirva como herramienta de aprendizaje.
"""

from __future__ import annotations

_FIX_SUGGESTIONS: dict[str, str] = {
    "color-contrast": (
        "Aumenta el contraste entre texto y fondo hasta al menos 4.5:1 "
        "(3:1 para texto grande). Elemento afectado: {element}"
    ),
    "image-alt": (
        "Añade un atributo `alt` descriptivo y equivalente al contenido "
        "de la imagen. Elemento afectado: {element}"
    ),
    "input-image-alt": (
        "Añade un `alt` descriptivo al input de imagen. Elemento: {element}"
    ),
    "svg-img-alt": (
        "Añade una etiqueta accesible al SVG (`<title>` dentro del SVG o "
        "`role=\"img\"` + `aria-label`). Elemento: {element}"
    ),
    "html-has-lang": (
        "Añade el atributo `lang` al elemento `<html>` (p. ej. "
        "`<html lang=\"es\">`). Elemento: {element}"
    ),
    "html-lang-valid": (
        "Corrige el valor del atributo `lang` para que use un código de "
        "idioma BCP 47 válido (p. ej. `es`, `en-US`). Elemento: {element}"
    ),
    "document-title": (
        "Añade un `<title>` descriptivo en el `<head>` de la página. "
        "Elemento: {element}"
    ),
    "link-name": (
        "Da un nombre accesible al enlace (texto visible o `aria-label` "
        "descriptivo). Elemento: {element}"
    ),
    "button-name": (
        "Da un nombre accesible al botón (texto visible o `aria-label`). "
        "Elemento: {element}"
    ),
    "empty-button-name": (
        "Añade texto o `aria-label` al botón vacío. Elemento: {element}"
    ),
    "label": (
        "Asocia una etiqueta al campo de formulario (`<label for>`, "
        "`aria-labelledby` o `aria-label`). Elemento: {element}"
    ),
    "select-name": (
        "Asocia una etiqueta al `<select>` con `<label>` o `aria-label`. "
        "Elemento: {element}"
    ),
    "frame-title": (
        "Añade un `title` descriptivo al `<iframe>`. Elemento: {element}"
    ),
    "region": (
        "Agrupa el contenido en landmarks (`<main>`, `<nav>`, `<header>`, "
        "`<footer>`) o usa `role=\"region\"` con `aria-label`. Elemento: {element}"
    ),
    "landmark-one-main": (
        "Añade un único `<main>` a la página. Elemento: {element}"
    ),
    "heading-order": (
        "Reordena los encabezados para que no salten niveles "
        "(h1 → h2 → h3...). Elemento: {element}"
    ),
    "page-has-heading-one": (
        "Añade un `<h1>` que describa el propósito de la página. "
        "Elemento: {element}"
    ),
    "p-as-heading": (
        "Sustituye el párrafo con estilos de título por un encabezado real "
        "(`<h1>`-`<h6>`). Elemento: {element}"
    ),
    "list": (
        "Marca las listas con `<ul>`/`<ol>` en lugar de párrafos o `<div>`. "
        "Elemento: {element}"
    ),
    "duplicate-id": (
        "Elimina o cambia el `id` duplicado; los `id` deben ser únicos en "
        "la página. Elemento: {element}"
    ),
    "tabindex": (
        "Elimina `tabindex` con valores positivos (rompen el orden de "
        "tabulación natural). Elemento: {element}"
    ),
    "nested-interactive": (
        "Evita elementos interactivos anidados (p. ej. un botón dentro de "
        "un enlace). Elemento: {element}"
    ),
    "aria-allowed-attr": (
        "Usa únicamente atributos ARIA permitidos por el rol del elemento. "
        "Elemento: {element}"
    ),
    "aria-required-attr": (
        "Añade los atributos ARIA obligatorios del rol "
        "(p. ej. `aria-controls` en `role=\"combobox\"`). Elemento: {element}"
    ),
    "aria-valid-attr-value": (
        "Corrige el valor del atributo ARIA para que sea uno de los "
        "permitidos (p. ej. `aria-expanded=\"true\"`). Elemento: {element}"
    ),
    "meta-viewport": (
        "Permite hacer zoom: usa `maximum-scale>=2` o elimina "
        "`user-scalable=no`. Elemento: {element}"
    ),
    "skip-link": (
        "Añade un enlace de salto al contenido principal al inicio de la "
        "página. Elemento: {element}"
    ),
    "target-size": (
        "Aumenta el área de interacción del elemento a al menos 24x24 CSS px "
        "(objetivo táctil). Elemento: {element}"
    ),
    "video-caption": (
        "Añade subtítulos sincronizados (WebVTT) al vídeo. Elemento: {element}"
    ),
    "td-has-header": (
        "Asocia cada celda de datos (`<td>`) con su cabecera (`<th>` con "
        "`scope` o `headers`). Elemento: {element}"
    ),
    "autocomplete-valid": (
        "Usa valores válidos de `autocomplete` para los campos de "
        "formulario. Elemento: {element}"
    ),
}

_FALLBACK_SUGGESTION = (
    "Revisa manualmente la regla '{rule_id}' en el elemento: {element}."
)

_LEARNING_RESOURCES: dict[str, str] = {
    "color-contrast": "https://webaim.org/articles/contrast/",
    "color-contrast-enhanced": "https://webaim.org/articles/contrast/",
    "image-alt": "https://webaim.org/techniques/alttext/",
    "svg-img-alt": "https://developer.mozilla.org/es/docs/Web/SVG/Element/title",
    "html-has-lang": "https://developer.mozilla.org/es/docs/Web/HTML/Global_attributes/lang",
    "html-lang-valid": "https://www.rfc-editor.org/rfc/bcp/bcp47.txt",
    "document-title": "https://developer.mozilla.org/es/docs/Web/HTML/Element/title",
    "link-name": "https://webaim.org/techniques/hypertext/",
    "button-name": "https://developer.mozilla.org/es/docs/Web/Accessibility/ARIA/Attributes/aria-label",
    "label": "https://webaim.org/techniques/forms/",
    "frame-title": "https://developer.mozilla.org/es/docs/Web/HTML/Element/iframe",
    "region": "https://www.w3.org/WAI/ARIA/apg/patterns/landmarks/",
    "landmark-one-main": "https://www.w3.org/WAI/ARIA/apg/patterns/landmarks/examples/main.html",
    "heading-order": "https://webaim.org/techniques/semanticstructure/",
    "page-has-heading-one": "https://webaim.org/techniques/semanticstructure/",
    "p-as-heading": "https://webaim.org/techniques/semanticstructure/",
    "list": "https://developer.mozilla.org/es/docs/Web/HTML/Element/ul",
    "duplicate-id": "https://developer.mozilla.org/es/docs/Web/HTML/Global_attributes/id",
    "tabindex": "https://developer.mozilla.org/es/docs/Web/HTML/Global_attributes/tabindex",
    "nested-interactive": "https://developer.mozilla.org/es/docs/Web/HTML/Element/a",
    "aria-allowed-attr": "https://www.w3.org/WAI/ARIA/apg/",
    "aria-required-attr": "https://www.w3.org/WAI/ARIA/apg/",
    "aria-valid-attr-value": "https://www.w3.org/WAI/ARIA/apg/",
    "meta-viewport": "https://developer.mozilla.org/es/docs/Web/HTML/Viewport_meta_tag",
    "skip-link": "https://webaim.org/techniques/skipnav/",
    "target-size": "https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html",
    "video-caption": "https://www.w3.org/WAI/media/av/captions/",
    "td-has-header": "https://webaim.org/techniques/tables/data/",
    "autocomplete-valid": "https://developer.mozilla.org/es/docs/Web/HTML/Attributes/autocomplete",
}

DEFAULT_RESOURCE = "https://www.w3.org/WAI/WCAG21/quickref/"


def get_fix_suggestion(rule_id: str, element: str) -> str:
    """Devuelve una sugerencia de corrección para la regla indicada.

    Args:
        rule_id: Identificador de la regla de axe-core.
        element: Selector del elemento afectado (para contextualizar).

    Returns:
        Sugerencia de corrección con el elemento referenciado.
    """
    template = _FIX_SUGGESTIONS.get(rule_id)
    if template is None:
        return _FALLBACK_SUGGESTION.format(rule_id=rule_id, element=element)
    return template.format(element=element)


def get_learning_resource(rule_id: str) -> str:
    """Devuelve un enlace a un recurso educativo para la regla.

    Args:
        rule_id: Identificador de la regla de axe-core.

    Returns:
        URL del recurso (MDN, WebAIM, W3C o la quickref WCAG por defecto).
    """
    return _LEARNING_RESOURCES.get(rule_id, DEFAULT_RESOURCE)
