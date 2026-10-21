"""Generacion de param.nml a partir de la plantilla oficial de SCHISM con sobreescrituras."""
from __future__ import annotations
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def write_param(path: str | Path, overrides: dict, template: str | Path | None = None) -> None:
    """Copia la plantilla param.nml y sustituye los valores de `overrides` (clave -> valor).

    Las claves deben existir en la plantilla (asi evitamos errores de tecleo silenciosos).
    """
    template = Path(template or TEMPLATES / "param.nml.v5.13")
    text = template.read_text()
    for key, value in overrides.items():
        pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)([^!\n]*)", re.MULTILINE)
        if not pattern.search(text):
            # algunas claves vienen comentadas en la plantilla (p.ej. iof_hydro(25)): se descomentan
            commented = re.compile(rf"^\s*!\s*({re.escape(key)}\s*=\s*)([^!\n]*)", re.MULTILINE)
            if not commented.search(text):
                raise KeyError(f"'{key}' no existe en la plantilla {template.name}")
            text = commented.sub(lambda m: f"  {m.group(1)}{_fmt(value)} ", text, count=1)
            continue
        text = pattern.sub(lambda m: f"{m.group(1)}{_fmt(value)} ", text, count=1)
    Path(path).write_text(text)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return repr(v)
    return str(v)
