"""Ayuda contextual (icono i): textos completos en es/en y asociados a etiquetas reales de la interfaz."""
import ast
import re
from collections import Counter
from pathlib import Path
import pytest
from schismlab.gui.help import HELP, _label_map
from schismlab.gui.i18n import TEXT
from schismlab.edition import is_pro as _is_pro
requires_pro = pytest.mark.skipif(not _is_pro(), reason="necesita SCHISMlab Pro")

GUI = Path(__file__).resolve().parents[1] / "schismlab" / "gui"
APP = (GUI / "app.py").read_text()
LITERALS = set(re.findall(r'ui\.(?:number|input|select|switch|checkbox|textarea)\(\s*"([^"]+)"', APP)) | set(re.findall(r'label="([^"]+)"', APP))


def test_same_keys_in_both_languages():
    assert set(HELP["es"]) == set(HELP["en"])
    assert set(TEXT["es"]) == set(TEXT["en"])


def test_i18n_has_no_duplicate_keys():
    """Una clave repetida en el literal de TEXT la pisa la última definición sin aviso: se detecta en el fuente (ast)."""
    tree = ast.parse((GUI / "i18n.py").read_text(encoding="utf-8"))
    dicts = [n for n in ast.walk(tree) if isinstance(n, ast.Dict) and len(n.keys) > 20]
    assert len(dicts) >= 2
    for d in dicts:
        keys = [k.value for k in d.keys if isinstance(k, ast.Constant)]
        dup = sorted(k for k, n in Counter(keys).items() if n > 1)
        assert not dup, f"claves repetidas en i18n.TEXT: {dup}"


def test_help_labels_do_not_collide():
    """La ayuda se asocia por etiqueta visible: dos claves de HELP con la misma etiqueta se pisan (gana la última)."""
    for lang in ("es", "en"):
        tx = TEXT[lang]
        labels = [str(tx.get(k, k)) for k in HELP[lang]]
        dup = sorted(k for k, n in Counter(labels).items() if n > 1)
        assert not dup, f"{lang}: etiquetas visibles repetidas en HELP: {dup}"


def test_keys_are_real_labels():
    for key in HELP["es"]:
        assert key in TEXT["es"] or key in LITERALS or key in ("Manning n", "T (°C)", "S (psu)") \
            or key.startswith("drawopt_"), f"ayuda sin campo: {key}"   # drawopt_: opciones de «Dibujar» (toggle_help)


def test_references_resolve_and_are_short():
    for lang in ("es", "en"):
        for key, txt in HELP[lang].items():
            if txt.startswith("@"):
                assert TEXT[lang].get(txt[1:]), f"{lang}:{key} -> {txt} no existe"
            else:
                assert len(txt.split()) <= 40, f"{lang}:{key} demasiado largo"
        assert len(_label_map(lang)) >= len(HELP[lang]) - 5


def test_every_tunable_field_has_help():
    """Todos los campos de las paginas guiadas tienen ayuda, salvo los de busqueda, credenciales y nombres libres."""
    keys = set(re.findall(r'ui\.(?:number|input|select|switch|checkbox|textarea)\(\s*t\["(\w+)"\]', APP)) | set(re.findall(r'label=t\["(\w+)"\]', APP))
    exempt = {"search", "only_changed", "show_all", "key", "user", "password", "upload_mesh", "ic_source", "import_dialog"}
    missing = sorted(k for k in keys - exempt if k not in HELP["es"])
    assert not missing, f"campos sin ayuda: {missing}"


pytest.importorskip("nicegui")
from nicegui.testing import User  # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.mark.parametrize("path,needle,case", [
    pytest.param("/mesh", "Tamaño del elemento más pequeño", "prueba_real", marks=requires_pro),
    ("/mesh", "Tamaño de los elementos del dominio idealizado", "prueba_2d"),
    ("/model", "Paso de tiempo (s). SCHISM es implícito", "prueba_2d")])
async def test_pages_show_help_icons(user: User, path: str, needle: str, case: str):
    await user.open(path + f"?case=cases/tests/{case}.yaml")
    await user.should_see("paso a paso")
    await user.should_see(needle)


def test_shared_labels_have_generic_text():
    """Etiquetas usadas en varios campos (nombre, lon, lat, zona) no deben describir solo uno de ellos."""
    for key in ("name", "lon", "lat", "regions"):
        assert "estación" not in HELP["es"][key] or key == "name"
        assert not HELP["es"][key].startswith("Nombre del caso")
