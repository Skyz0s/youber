"""Mapeo de reglas de axe-core a criterios WCAG 2.1/2.2.

El mapeo es orientativo y educativo: una regla de axe puede cubrir varios
criterios; aquí se indica el criterio principal (el más directamente
relacionado con la comprobación que hace la regla).
"""

from __future__ import annotations

from typing import NamedTuple


class WcagCriteria(NamedTuple):
    """Criterio de éxito WCAG.

    Attributes:
        version: Versión de WCAG ("WCAG 2.1" o "WCAG 2.2").
        sc: Número del criterio (p. ej. "1.4.3").
        name: Nombre del criterio.
        level: Nivel de conformidad (A, AA o AAA).
    """

    version: str
    sc: str
    name: str
    level: str


wcag_map: dict[str, WcagCriteria] = {
    # --- Perceptible (1.x) ---
    "image-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "input-image-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "object-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "area-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "role-img-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "svg-img-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "image-redundant-alt": WcagCriteria("WCAG 2.1", "1.1.1", "Non-text Content", "A"),
    "audio-caption": WcagCriteria("WCAG 2.1", "1.2.1", "Audio-only and Video-only", "A"),
    "video-caption": WcagCriteria("WCAG 2.1", "1.2.2", "Captions (Prerecorded)", "A"),
    "video-description": WcagCriteria("WCAG 2.1", "1.2.5", "Audio Description (Prerecorded)", "AA"),
    "no-autoplay-audio": WcagCriteria("WCAG 2.1", "1.4.2", "Audio Control", "A"),
    "color-contrast": WcagCriteria("WCAG 2.1", "1.4.3", "Contrast (Minimum)", "AA"),
    "color-contrast-enhanced": WcagCriteria("WCAG 2.1", "1.4.6", "Contrast (Enhanced)", "AAA"),
    "link-in-text-block": WcagCriteria("WCAG 2.1", "1.4.1", "Use of Color", "A"),
    "meta-viewport": WcagCriteria("WCAG 2.1", "1.4.4", "Resize Text", "AA"),
    "meta-viewport-large": WcagCriteria("WCAG 2.1", "1.4.4", "Resize Text", "AA"),
    "css-orientation-lock": WcagCriteria("WCAG 2.1", "1.3.4", "Orientation", "AA"),
    "autocomplete-valid": WcagCriteria("WCAG 2.1", "1.3.5", "Identify Input Purpose", "AA"),
    "label": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "label-title-only": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "fieldset": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "legend": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "list": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "definition-list": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "dlitem": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "listitem": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "table-duplicate-name": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "table-fake-caption": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "td-has-header": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "th-has-data-cells": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "td-headers-attr": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "scope-attr-valid": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "caption": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "form-field-multiple-labels": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "region": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "landmark-one-main": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "landmark-no-duplicate-main": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "landmark-unique": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "heading-order": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "page-has-heading-one": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "p-as-heading": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "empty-heading": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "aria-required-children": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "aria-required-parent": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "presentation-role-conflict": WcagCriteria("WCAG 2.1", "1.3.1", "Info and Relationships", "A"),
    "focus-order-semantics": WcagCriteria("WCAG 2.1", "1.3.2", "Meaningful Sequence", "A"),
    # --- Operable (2.x) ---
    "bypass": WcagCriteria("WCAG 2.1", "2.4.1", "Bypass Blocks", "A"),
    "skip-link": WcagCriteria("WCAG 2.1", "2.4.1", "Bypass Blocks", "A"),
    "frame-title": WcagCriteria("WCAG 2.1", "2.4.1", "Bypass Blocks", "A"),
    "frame-title-unique": WcagCriteria("WCAG 2.1", "2.4.1", "Bypass Blocks", "A"),
    "empty-frame-title": WcagCriteria("WCAG 2.1", "2.4.1", "Bypass Blocks", "A"),
    "document-title": WcagCriteria("WCAG 2.1", "2.4.2", "Page Titled", "A"),
    "meta-refresh": WcagCriteria("WCAG 2.1", "2.2.1", "Timing Adjustable", "A"),
    "marquee": WcagCriteria("WCAG 2.1", "2.2.2", "Pause, Stop, Hide", "A"),
    "tabindex": WcagCriteria("WCAG 2.1", "2.4.3", "Focus Order", "A"),
    "link-name": WcagCriteria("WCAG 2.1", "2.4.4", "Link Purpose", "A"),
    "link-purpose": WcagCriteria("WCAG 2.1", "2.4.4", "Link Purpose", "A"),
    "identical-links-same-purpose": WcagCriteria("WCAG 2.1", "2.4.4", "Link Purpose", "A"),
    "label-content-name-mismatch": WcagCriteria("WCAG 2.1", "2.5.3", "Label in Name", "A"),
    "scrollable-region-focusable": WcagCriteria("WCAG 2.1", "2.1.1", "Keyboard", "A"),
    "target-size": WcagCriteria("WCAG 2.2", "2.5.8", "Target Size (Minimum)", "AA"),
    "target-size-minimum": WcagCriteria("WCAG 2.2", "2.5.8", "Target Size (Minimum)", "AA"),
    "focus-not-obscured": WcagCriteria("WCAG 2.2", "2.4.11", "Focus Not Obscured (Minimum)", "AA"),
    "focus-not-obscured-minimum": WcagCriteria("WCAG 2.2", "2.4.11", "Focus Not Obscured (Minimum)", "AA"),
    # --- Comprensible (3.x) ---
    "html-has-lang": WcagCriteria("WCAG 2.1", "3.1.1", "Language of Page", "A"),
    "html-lang-valid": WcagCriteria("WCAG 2.1", "3.1.1", "Language of Page", "A"),
    "html-xml-lang-mismatch": WcagCriteria("WCAG 2.1", "3.1.1", "Language of Page", "A"),
    "valid-lang": WcagCriteria("WCAG 2.1", "3.1.2", "Language of Parts", "AA"),
    "lang": WcagCriteria("WCAG 2.1", "3.1.2", "Language of Parts", "AA"),
    # --- Robusto (4.x) ---
    "duplicate-id": WcagCriteria("WCAG 2.1", "4.1.1", "Parsing", "A"),
    "duplicate-id-active": WcagCriteria("WCAG 2.1", "4.1.1", "Parsing", "A"),
    "duplicate-id-aria": WcagCriteria("WCAG 2.1", "4.1.1", "Parsing", "A"),
    "aria-allowed-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-allowed-role": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-conditional-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-deprecated-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-deprecated-role": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-hidden-body": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-hidden-focus": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-input-field-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-meter-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-progressbar-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-required-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-roles": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-toggle-field-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-tooltip-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-unsupported-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-valid-attr": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-valid-attr-value": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "aria-prohibited-attr": WcagCriteria("WCAG 2.2", "4.1.2", "Name, Role, Value", "A"),
    "aria-command-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "button-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "empty-button-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "input-button-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "select-name": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
    "nested-interactive": WcagCriteria("WCAG 2.1", "4.1.2", "Name, Role, Value", "A"),
}

UNKNOWN_GUIDELINE = "No mapeada - revisar manualmente"


def get_wcag_guideline(rule_id: str) -> str:
    """Devuelve la guía WCAG asociada a una regla de axe-core.

    Args:
        rule_id: Identificador de la regla (p. ej. ``"color-contrast"``).

    Returns:
        Cadena formateada, p. ej. ``"WCAG 2.1 - 1.4.3 - Contrast (Minimum)"``.
    """
    entry = wcag_map.get(rule_id)
    if entry is None:
        return UNKNOWN_GUIDELINE
    return f"{entry.version} - {entry.sc} - {entry.name}"


def wcag_quickref_url(rule_id: str) -> str:
    """Devuelve la URL de la quickref W3C para el criterio de la regla."""
    entry = wcag_map.get(rule_id)
    if entry is None:
        return "https://www.w3.org/WAI/WCAG21/quickref/"
    base = (
        "https://www.w3.org/WAI/WCAG22/quickref/"
        if entry.version == "WCAG 2.2"
        else "https://www.w3.org/WAI/WCAG21/quickref/"
    )
    return f"{base}#{entry.sc}"
