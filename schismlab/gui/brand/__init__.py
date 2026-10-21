"""Identidad visual de SCHISMlab (dirección «Rejilla», octubre de 2026): colores, tipografías y logotipos.

Símbolo: nueve puntos que crecen hacia una esquina (la resolución variable de la malla), el mayor en turquesa.
Paleta casi monocroma: el color lo ponen los datos en los mapas, no la interfaz. Guía completa en docs/marca.md.
"""
from __future__ import annotations
from pathlib import Path

DIR = Path(__file__).resolve().parent

COLORS = {
    "grafito": "#2b2b2b",      # primario: texto, cabecera, botones principales
    "turquesa": "#0e9aa7",     # acento: lo activo, lo seleccionado, «lab»
    "blanco": "#ffffff",       # fondo
    "gris": "#efefef",         # paneles y fondos secundarios
    "gris_texto": "#6a6a6a",   # texto secundario (contraste 5.7:1 sobre blanco)
    "naranja": "#d8542b",      # avisos y errores
    "verde": "#2f8f5b",        # estados correctos
    "oscuro": "#1c1c1c",       # fondo en modo oscuro
    "oscuro_panel": "#262626",
    "claro_texto": "#ececec",  # texto en modo oscuro
}
FONT_SANS = "'Space Grotesk', Helvetica, Arial, sans-serif"
FONT_MONO = "'JetBrains Mono', Menlo, Consolas, monospace"
FONTS_LINK = ("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700"
              "&family=JetBrains+Mono:wght@400;500&display=swap")
# series de figuras (distinguibles también por luminosidad; la primera es el acento)
SERIES = ["#0e9aa7", "#2b2b2b", "#d8542b", "#7a4fb8", "#4d8f2f", "#b8860b", "#b5536a", "#4a7fb0"]

SYMBOL = (DIR / "symbol.svg").read_text(encoding="utf-8")
ICON = (DIR / "icon.svg").read_text(encoding="utf-8")
FAVICON = DIR / "favicon.svg"


def symbol_svg(size: int = 32, dark: bool = False) -> str:
    """Símbolo en línea para la cabecera: puntos en grafito (o claros en oscuro) y el grande en turquesa."""
    dots = COLORS["claro_texto"] if dark else COLORS["grafito"]
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 112 112" aria-hidden="true">'
            f'<circle cx="22" cy="22" r="7" fill="{dots}"/><circle cx="56" cy="22" r="7" fill="{dots}"/>'
            f'<circle cx="22" cy="56" r="7" fill="{dots}"/><circle cx="56" cy="56" r="11" fill="{dots}"/>'
            f'<circle cx="84" cy="84" r="22" fill="{COLORS["turquesa"]}"/></svg>')


def edition_badge(edition: str, dark: bool = False, size: int = 12) -> str:
    """Distintivo «Lite» (contorno turquesa) o «Pro» (relleno turquesa) que acompaña a la palabra SCHISMlab."""
    pro = edition == "pro"
    bg = COLORS["turquesa"] if pro else "transparent"
    fg = COLORS["blanco"] if pro else COLORS["turquesa"]
    return (f'<span class="sl-edition" style="display:inline-block;margin-left:8px;padding:1px 7px;border:1.5px solid {COLORS["turquesa"]};'
            f'border-radius:5px;background:{bg};color:{fg};font-size:{size}px;font-weight:700;letter-spacing:.02em;'
            f'line-height:1.35;vertical-align:4px">{"Pro" if pro else "Lite"}</span>')
