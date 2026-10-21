"""Edición de SCHISMlab: Lite (solo este paquete) o Pro (con la extensión privada `schismlab_pro`).

La extensión no forma parte de SCHISMlab Lite: vive en un repositorio privado y solo está en los equipos que la han
activado con un token. Se busca, por este orden, en:
  1. $SCHISMLAB_PRO_PATH (carpeta que contiene el paquete `schismlab_pro`);
  2. <repositorio>/pro (repositorio de desarrollo, con las dos partes);
  3. ~/.schismlab/pro (clon hecho por «Activar SCHISMlab Pro»).
SCHISMLAB_NO_PRO=1 fuerza la edición Lite (solo para desarrollo y pruebas).

Uso en el código de la base: `is_pro()` para mostrar u ocultar, y `pro("data.era5")` para usar una función de la
extensión; sin la extensión, `pro()` lanza ProRequired con un mensaje claro en vez de un ImportError.
"""
from __future__ import annotations
import importlib
import os
import sys
from pathlib import Path

from . import __version__

REPO = Path(__file__).resolve().parents[1]
PRO_HOME = Path(os.environ.get("SCHISMLAB_PRO_HOME", Path.home() / ".schismlab" / "pro")).expanduser()   # variable: pruebas

_state: dict = {}


class ProRequired(RuntimeError):
    """Una función de SCHISMlab Pro pedida en SCHISMlab Lite."""

    def __init__(self, feature: str):
        self.feature = feature
        super().__init__(f"«{feature}» necesita SCHISMlab Pro / «{feature}» requires SCHISMlab Pro")


def _candidates() -> list[Path]:
    out = []
    if os.environ.get("SCHISMLAB_PRO_PATH"):
        out.append(Path(os.environ["SCHISMLAB_PRO_PATH"]).expanduser())
    out += [REPO / "pro", PRO_HOME]
    return out


def _load() -> dict:
    if _state:
        return _state
    _state.update(pro=False, module=None, path=None, problem=None)
    if os.environ.get("SCHISMLAB_NO_PRO"):
        return _state
    for d in _candidates():
        if (d / "schismlab_pro" / "__init__.py").exists():
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            _state["path"] = d
            break
    try:
        mod = importlib.import_module("schismlab_pro")
    except ImportError:
        return _state
    except Exception as ex:   # noqa: BLE001  (extensión rota: se trabaja como Lite y se avisa)
        _state["problem"] = f"{type(ex).__name__}: {ex}"
        return _state
    need = getattr(mod, "REQUIRES_BASE", __version__)
    if need != __version__:
        _state["problem"] = (f"SCHISMlab Pro {getattr(mod, '__version__', '?')} necesita la base {need} y esta es la {__version__}: "
                             f"actualiza las dos partes / Pro needs base {need}, this is {__version__}: update both")
        return _state
    _state.update(pro=True, module=mod)
    return _state


def is_pro() -> bool:
    return bool(_load()["pro"])


def edition() -> str:
    """'pro' o 'lite'."""
    return "pro" if is_pro() else "lite"


def edition_name() -> str:
    return "SCHISMlab Pro" if is_pro() else "SCHISMlab Lite"


def problem() -> str | None:
    """Motivo por el que la extensión está presente pero no se ha cargado (versiones distintas, error al importar)."""
    return _load()["problem"]


def pro_path() -> Path | None:
    return _load()["path"]


def default_generator() -> str:
    """Generador de malla cuando el YAML no lo dice: OCSMesh en Pro; en Lite solo existe el idealizado."""
    return "ocsmesh" if is_pro() else "idealized"


def pro(module: str, feature: str | None = None):
    """Módulo `schismlab_pro.<module>`; ProRequired si esta instalación es Lite."""
    if not is_pro():
        raise ProRequired(feature or module)
    return importlib.import_module(f"schismlab_pro.{module}")
