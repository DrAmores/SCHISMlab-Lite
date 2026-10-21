"""Pruebas de la interfaz NiceGUI sin navegador (nicegui.testing.User)."""
from pathlib import Path
import pytest

pytest.importorskip("nicegui")
from nicegui.testing import User

pytest_plugins = ["nicegui.testing.user_plugin"]
REPO = Path(__file__).resolve().parents[1]
CASE = REPO / "cases" / "tests" / "prueba_2d.yaml"


@pytest.mark.parametrize("path", ["/", "/install", "/mesh", "/model", "/forcing", "/outputs", "/update", "/params", "/run", "/results", "/results?tab=validate", "/analyse", "/validate", "/impacts"])
async def test_pages_render(user: User, path: str):
    await user.open("/")
    await user.should_see("paso a paso")
    # abrir el caso de Ekman desde la galeria
    user.find("prueba_2d").click()
    await user.open(path)
    await user.should_see("paso a paso")


async def test_params_page_lists_catalog(user: User):
    await user.open("/params?case=cases/tests/prueba_2d.yaml")
    await user.should_see("param.nml")
    await user.should_see("rnday")


async def test_model_page_ic_builder_restores_recipe(user: User):
    # caso con receta guardada: la fila de temperatura regenera la misma expresion
    await user.open("/model?case=cases/tests/prueba_3d_xy.yaml")
    await user.should_see("Condiciones iniciales")
    await user.should_see("where(z > -50, 20, 15)")


async def test_model_page_ic_builder_free_expression(user: User):
    # caso con expresion sin receta: se muestra como "expresion" con el texto original
    await user.open("/model?case=cases/tests/prueba_2d.yaml")
    await user.should_see("0.5*cos(pi*x/20000)")


# El explorador de resultados (3D con estaciones, 2D, espectro, comparar) se prueba en tests/test_explorer.py con una
# simulación sintética escrita en tmp_path, sin depender de ~/.schismlab/runs.


async def test_results_explorer_synthetic(user: User, tmp_path, monkeypatch):
    from schismlab.gui import state                   # tras el fixture `user` (main.py reimporta el paquete)
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    for tab, needle in (("maps", "Puntos"), ("spectrum", "ventana")):
        await user.open(f"/results?case={p}&tab={tab}")
        await user.should_see(needle)


async def test_import_case_upload(user: User, tmp_path, monkeypatch):
    # subir un paquete exportado desde la galería crea el caso (API de subida de NiceGUI 3: e.file)
    import io, zipfile
    from nicegui.elements.upload import Upload
    from schismlab.gui import state as st_
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("caso.yaml", "name: importado_test\nmesh: {generator: idealized, Lx: 1000, Ly: 1000, dx: 500, bathymetry: 10}\n")
    cases_dir = tmp_path / "cases"; monkeypatch.setattr(st_, "USER_CASES", cases_dir)

    class _F(Upload.FileUpload):
        def __init__(self, data): super().__init__(name="caso.zip", content_type="application/zip"); self._d = data
        async def read(self): return self._d
        async def text(self, encoding="utf-8"): return self._d.decode(encoding)
        def iterate(self, *, chunk_size=1024 * 1024):
            async def _it():
                yield self._d
            return _it()
        async def save(self, path): Path(path).write_bytes(self._d)
        def size(self): return len(self._d)
    await user.open("/")
    up = user.find(Upload).elements.pop()
    await up.handle_uploads([_F(buf.getvalue())])
    await user.should_see("Caso importado")
    assert (cases_dir / "importado_test.yaml").exists()


# --- páginas reorganizadas (acordeones en Física y Forzamientos, tabla de estaciones, explorador con «Estilo del mapa»)
def _n_elements(user: User, kind) -> int:
    """Número de elementos de ese tipo en la página (user.find lanza AssertionError si no hay ninguno)."""
    try:
        return len(user.find(kind).elements)
    except AssertionError:
        return 0


async def test_forcing_page_uses_expansions_not_tabs(user: User):
    from nicegui import ui
    await user.open("/forcing?case=cases/tests/prueba_2d.yaml")
    await user.should_see("Atmósfera")
    await user.should_see("Mareas y nivel")
    from schismlab.edition import is_pro
    if is_pro():
        await user.should_see("Ríos")
    else:                                              # SCHISMlab Lite: sin contornos 3D, oleaje ni ríos
        await user.should_not_see("Ríos")
    assert _n_elements(user, ui.tabs) == 0
    exps = user.find(ui.expansion).elements
    assert len(exps) >= (5 if is_pro() else 2) and any(e._props.get("caption") for e in exps)


async def test_forcing_tab_param_opens_expansion(user: User):
    from nicegui import ui
    from schismlab.edition import is_pro
    tab, label = ("rivers", "Ríos") if is_pro() else ("tides", "Mareas y nivel")
    await user.open(f"/forcing?case=cases/tests/prueba_2d.yaml&tab={tab}")
    await user.should_see(label)
    opened = [e._props.get("label") for e in user.find(ui.expansion).elements if e.value]
    assert opened and opened[0].startswith(label) and "Atmósfera" not in opened


async def test_model_page_expansions_with_captions(user: User):
    from nicegui import ui
    await user.open("/model?case=cases/tests/prueba_3d_xy.yaml")
    await user.should_see("Malla vertical")
    caps = {e._props.get("label"): e._props.get("caption") for e in user.find(ui.expansion).elements}
    assert "niveles" in (caps.get("Malla vertical") or "")
    assert "Δt" in (caps.get("Instante") or "")


async def test_params_single_file_has_no_tabs(user: User):
    from nicegui import ui
    await user.open("/params?case=cases/tests/prueba_2d.yaml")
    await user.should_see("param.nml")
    await user.should_see("rnday")
    assert _n_elements(user, ui.tabs) == 0


async def test_outputs_page_station_table(user: User):
    from nicegui import ui
    await user.open("/outputs?case=cases/tests/prueba_2d.yaml")
    await user.should_see("Estaciones definidas")
    tables = list(user.find(ui.table).elements)
    assert tables and [c["name"] for c in tables[0].columns][:3] == ["name", "x", "y"]
    assert _n_elements(user, ui.grid) >= 4                      # un ui.grid(columns=4) por grupo de variables
    # el nombre tecleado se usa al añadir (por clic o por coordenadas) y se puede renombrar en la tabla
    tbl = tables[0]
    name_in = next(e for e in user.find(ui.input).elements if e._props.get("label") == "Nombre" and str(e.value).startswith("E"))
    name_in.set_value("Palma")
    add = next(b for b in user.find(ui.button).elements if b._props.get("label") == "Añadir" and b._props.get("icon") == "add")
    for h in add._event_listeners.values():
        if h.type == "click":
            h.handler(None)
    assert any(r["name"] == "Palma" for r in tbl.rows) and name_in.value.startswith("E")
    class E:
        args = {"i": [r["i"] for r in tbl.rows if r["name"] == "Palma"][0], "name": "Palma_puerto"}
    for h in tbl._event_listeners.values():
        if h.type == "rename":
            h.handler(E())
    assert any(r["name"] == "Palma_puerto" for r in tbl.rows) and "body-cell-name" in tbl.slots


async def test_results_explorer_style_expansion_and_presets(user: User, tmp_path, monkeypatch):
    from nicegui import ui
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    labels = [e._props.get("label") for e in user.find(ui.expansion).elements]
    assert any(l and l.startswith("Estilo del mapa") for l in labels)
    assert user.find(marker="sec_transversal").elements
    assert not any(e._props.get("label") == "clic en el mapa" for e in user.find(ui.select).elements)


async def test_folder_picker_dialog(user: User, tmp_path):
    """El botón de carpeta abre el explorador de carpetas del servidor: lista subcarpetas, crea una y devuelve la ruta."""
    import asyncio
    from nicegui import ui
    from schismlab.gui.folder_picker import _subdirs
    (tmp_path / "simulaciones").mkdir(); (tmp_path / ".oculta").mkdir()
    assert [d.name for d in _subdirs(tmp_path)] == ["simulaciones"]
    await user.open("/")
    flds = [e for e in user.find(ui.input).elements if e._props.get("label") == "Carpeta de la simulación"]   # caso nuevo e importar
    assert len(flds) >= 2
    for f_ in flds:
        f_.set_value(str(tmp_path))
    user.find(marker="browse_folder").click()
    await asyncio.sleep(0.3)
    await user.should_see("Elegir esta carpeta")
    await user.should_see("simulaciones")
    new = next(e for e in user.find(ui.input).elements if e._props.get("label") == "Nueva carpeta"); new.set_value("nueva")
    mk = next(b for b in user.find(ui.button).elements if b._props.get("icon") == "create_new_folder")
    next(h.handler for h in mk._event_listeners.values() if h.type == "click")(None)
    assert (tmp_path / "nueva").is_dir()
    user.find("Elegir esta carpeta").click()
    await asyncio.sleep(0.3)
    assert any(f_.value == str(tmp_path / "nueva") for f_ in flds)


async def test_new_case_matches_edition(user: User, tmp_path):
    """Un caso nuevo nace con la malla de su edición: en Lite, cuenca idealizada en metros y sin aviso de Pro."""
    from schismlab.edition import is_pro
    from schismlab.gui.state import new_case, load_cfg
    p = new_case("nuevo_edicion", folder=tmp_path, workdir_root=tmp_path / "sim")
    gen = load_cfg(p)["mesh"]["generator"]
    assert gen == ("ocsmesh" if is_pro() else "idealized")
    await user.open(f"/mesh?case={p}")
    await user.should_see("Generar malla")
    if not is_pro():
        await user.should_not_see("Este caso usa una malla con costa real")
