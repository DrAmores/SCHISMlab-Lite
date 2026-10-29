"""Pruebas de la interfaz NiceGUI sin navegador (nicegui.testing.User)."""
from pathlib import Path
import pytest

pytest.importorskip("nicegui")
from nicegui.testing import User

pytest_plugins = ["nicegui.testing.user_plugin"]
REPO = Path(__file__).resolve().parents[1]
CASE = REPO / "cases" / "tests" / "prueba_2d.yaml"
from schismlab.edition import is_pro as _is_pro
requires_pro = pytest.mark.skipif(not _is_pro(), reason="necesita SCHISMlab Pro")


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


async def test_params_search_opens_matching_sections(user: User):
    """Buscar un parámetro abre la sección que lo tiene y dice cuántos coinciden (thetai está en &OPT, que empieza cerrada)."""
    import asyncio
    from nicegui import ui
    await user.open("/params?case=cases/tests/prueba_2d.yaml")
    await user.should_see("rnday")
    search = next(e for e in user.find(ui.input).elements if e._props.get("label") == "Buscar parámetro")
    search.set_value("thetai"); await asyncio.sleep(0.2)
    exps = {e._props["label"].split()[0]: e for e in user.find(ui.expansion).elements if str(e._props.get("label", "")).startswith("&")}
    assert exps["&OPT"].value and "de" in exps["&OPT"]._props["label"] and not exps["&CORE"].value
    assert exps["&CORE"]._props["label"].startswith("&CORE  (0 de")
    search.set_value(""); await asyncio.sleep(0.2)
    assert " de " not in exps["&OPT"]._props["label"]


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


async def test_results_play_button_restore_stations_and_tabs(user: User, tmp_path, monkeypatch):
    """Botón de reproducción centrado (sin el relleno de la fila), estaciones borradas recuperables y la reproducción
    no salta a la pestaña Secciones."""
    import asyncio
    from nicegui import ui
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    play = next(iter(user.find(marker="play_button").elements))
    assert play.parent_slot.parent.tag == "div" and "q-col-gutter-sm" not in play.parent_slot.parent.classes
    # borrar la estación y recuperarla
    def names():
        try:
            return [e.value for e in user.find(ui.input).elements if e.value in ("centro",)]
        except AssertionError:                        # en Lite, sin la estación no queda ningún campo de texto
            return []
    assert names() == ["centro"]
    close = [b for b in user.find(ui.button).elements if b._props.get("icon") == "close"]
    next(h.handler for h in close[0]._event_listeners.values() if h.type == "click")(None)
    await asyncio.sleep(0.1)
    assert names() == []
    await user.should_see("Recuperar estaciones borradas (1)")
    rb = next(iter(user.find(marker="restore_stations").elements))
    next(h.handler for h in rb._event_listeners.values() if h.type == "click")(None)
    await asyncio.sleep(0.1)
    assert names() == ["centro"]
    # una sección vista y vuelta a Puntos: mover el tiempo no cambia de pestaña
    plot = next(iter(user.find(marker="map_plot").elements))
    tp = [e for e in user.find(ui.tab_panels).elements if any(getattr(c, "_props", {}).get("name") == "tab_points" for c in e.default_slot.children)]
    panels = tp[0]
    tr = next(iter(user.find(marker="sec_transversal").elements))
    next(h.handler for h in tr._event_listeners.values() if h.type == "click")(None)

    class E:
        args = {"points": [{"x": 1.0, "y": 40.25}]}
    next(h.handler for h in plot._event_listeners.values() if h.type == "plotly_click")(E())
    assert "tab_sections" in str(panels.value)
    panels.set_value("tab_points")
    tsl = next(iter(user.find(marker="time_slider").elements))
    tsl.set_value(3); tsl.set_value(4)
    await asyncio.sleep(0.4)
    assert "tab_points" in str(panels.value)


async def test_particles_tab_own_controls_and_animated_field(user: User, tmp_path, monkeypatch):
    """Partículas: variable y capa propias, un solo mapa, y al avanzar el tiempo cambian a la vez el campo y las partículas."""
    import asyncio
    from nicegui import ui
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=particles")
    await user.should_see("Campo de fondo")
    var = next(iter(user.find(marker="p_var").elements)); lay = next(iter(user.find(marker="p_layer").elements))
    plot = next(iter(user.find(marker="p_plot").elements))
    assert plot.figure["data"][0]["type"] == "heatmap"
    v2 = [o for o in var.options if o != var.value][0]
    var.set_value(v2); lay.set_value(0)
    await asyncio.sleep(0.2)
    assert v2 in plot.figure["layout"]["title"]["text"]
    rb = next(iter(user.find(marker="p_release").elements))
    next(h.handler for h in rb._event_listeners.values() if h.type == "click")(None)
    for _ in range(100):
        await asyncio.sleep(0.1)
        if len(plot.figure["data"]) >= 4:
            break
    assert [d["type"] for d in plot.figure["data"]][:4] == ["heatmap", "scatter", "scatter", "scatter"]
    calls = []
    monkeypatch.setattr(type(plot), "run_plot_method", lambda self, name, *a, **k: calls.append((name, a)))
    tsl = next(iter(user.find(marker="p_time").elements)); tsl.set_value(2)
    await asyncio.sleep(0.4)
    assert any(n == "restyle" and "z" in a[0] for n, a in calls)                 # el campo cambia con el fotograma
    assert any(n == "restyle" and a[1] == [1, 3] for n, a in calls)              # trayectorias y partículas


def test_bottom_examples_are_valid_and_documented():
    """Cada fondo idealizado tiene fórmula, parámetros explicados y un ejemplo que da profundidades positivas en el dominio."""
    import inspect
    import numpy as np
    from schismlab.mesh.analytic import BOTTOMS, bottom_example, analytic_depth
    src = inspect.getsource(analytic_depth)
    X, Y = np.meshgrid(np.linspace(0, 100e3, 21), np.linspace(0, 50e3, 11))
    for k, d in BOTTOMS.items():
        if k == "expression":
            continue
        ex = bottom_example(k, 0, 100e3, 0, 50e3)
        assert set(ex) <= set(d["params"]) and all(f'"{p}"' in src for p in d["params"]), k
        z = analytic_depth(k, **ex)(X, Y)
        assert np.all(np.isfinite(z)) and z.min() > 0, k
    sm = analytic_depth("seamount", **bottom_example("seamount", 0, 100e3, 0, 50e3))(np.array([50e3]), np.array([25e3]))
    assert sm[0] == pytest.approx(200.0)                                   # cima en el centro: h - A


async def test_mesh_page_bottom_parameters_explained(user: User, tmp_path):
    import asyncio, json
    import yaml
    from nicegui import ui
    cfg = {"name": "fondo", "mesh": {"generator": "idealized", "Lx": 80000, "Ly": 40000, "dx": 4000, "bathymetry": 50, "open_sides": []}}
    p = tmp_path / "fondo.yaml"; p.write_text(yaml.safe_dump(cfg))
    await user.open(f"/mesh?case={p}")
    kind = next(e for e in user.find(ui.select).elements if e._props.get("label") == "Fondo")
    kind.set_value("seamount"); await asyncio.sleep(0.1)
    params = next(e for e in user.find(ui.input).elements if e._props.get("label", "") == "parámetros (JSON)")
    assert json.loads(params.value) == {"h": 1000.0, "A": 800.0, "x0": 40000.0, "y0": 20000.0, "r": 8000.0}
    doc = next(iter(user.find(marker="bottom_doc").elements)).content
    assert "monte submarino" in doc and "`A`" in doc and "`r`" in doc and "esquina SW" in doc


@requires_pro
async def test_mesh_page_opens_with_dict_bottom(user: User, tmp_path):
    """En Pro, un caso idealizado con fondo {kind: seamount, ...} abre la página de malla (antes: error 500)."""
    import yaml
    cfg = {"name": "sm", "mesh": {"generator": "idealized", "Lx": 100000, "Ly": 60000, "dx": 5000, "open_sides": [],
                                  "bathymetry": {"kind": "seamount", "h": 1000, "A": 800, "x0": 50000, "y0": 30000, "r": 10000}}}
    p = tmp_path / "sm.yaml"; p.write_text(yaml.safe_dump(cfg))
    await user.open(f"/mesh?case={p}")
    await user.should_see("monte submarino")


async def test_results_isolines_over_colour(user: User, tmp_path, monkeypatch):
    """Isolíneas de la profundidad (o de otra variable) encima del campo de color; las de una variable siguen al tiempo."""
    import asyncio
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Campo de color")
    plot = next(iter(user.find(marker="map_plot").elements))
    iso = next(iter(user.find(marker="isolines_select").elements))
    iso.set_value("depth"); await asyncio.sleep(0.1)
    assert plot.figure["data"][0]["type"] == "heatmap" and plot.figure["data"][1]["type"] == "contour"
    assert plot.figure["data"][1]["contours"]["coloring"] == "none" and "isolíneas" in plot.figure["layout"]["title"]["text"]
    step = next(iter(user.find(marker="isolines_step").elements)); step.set_value(5); await asyncio.sleep(0.1)
    assert plot.figure["data"][1]["contours"]["size"] == 5.0
    calls = []
    monkeypatch.setattr(type(plot), "run_plot_method", lambda self, name, *a, **k: calls.append((name, a)))
    tsl = next(iter(user.find(marker="time_slider").elements)); tsl.set_value(1)
    await asyncio.sleep(0.4)
    assert any(n == "restyle" and a[1] == [0] for n, a in calls)          # profundidad: vía rápida, solo el campo de color
    iso.set_value("elevation"); await asyncio.sleep(0.1)
    tsl.set_value(3); await asyncio.sleep(0.4)
    assert plot.figure["data"][1]["type"] == "contour" and "03:00" in plot.figure["layout"]["title"]["text"]   # redibujado con niveles nuevos


def test_contour_levels_skip_flat_extremes():
    """Fondo plano de 200 m con un monte: las isolíneas van entre la cima y el fondo, sin la de 200 m (ruido)."""
    import numpy as np
    from schismlab.gui.explorer import contour_levels
    x, y = np.meshgrid(np.linspace(0, 500e3, 101), np.linspace(0, 200e3, 41))
    h = 200 - 150 * np.exp(-((x - 150e3) ** 2 + (y - 100e3) ** 2) / (2 * 20e3 ** 2)) + 1e-9 * np.random.default_rng(0).normal(size=x.shape)
    a, b, step = contour_levels(h)
    assert step in (10.0, 20.0, 25.0) and a > 50 and b < 200
    assert contour_levels(np.full((5, 5), 7.0)) is None
    assert contour_levels(h, 50)[2] == 50 and contour_levels(h, 50)[1] == 150


async def test_sections_visible_toggle_and_plot_button(user: User, tmp_path, monkeypatch):
    """Secciones: colores vivos con halo; el ojo las oculta o muestra en el mapa; el botón de gráfico elige cuál se
    representa (antes el ojo solo redibujaba y parecía no hacer nada)."""
    import asyncio
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    plot = next(iter(user.find(marker="map_plot").elements))
    clk = next(h.handler for h in plot._event_listeners.values() if h.type == "plotly_click")

    class E:
        def __init__(s, x, y): s.args = {"points": [{"x": x, "y": y}]}
    tr = next(iter(user.find(marker="sec_transversal").elements))
    next(h.handler for h in tr._event_listeners.values() if h.type == "click")(None); clk(E(1.0, 40.25))
    clk(E(0.8, 40.1)); clk(E(1.2, 40.4))
    await asyncio.sleep(0.2)
    lay = plot.figure["layout"]
    assert len(lay["shapes"]) == 2 and lay["shapes"][1]["line"]["color"] != "#2b2b2b"
    eye = lambda i: next(iter(user.find(marker=f"sec_eye_{i}").elements))
    next(h.handler for h in eye(0)._event_listeners.values() if h.type == "click")(None)
    await asyncio.sleep(0.1)
    assert len(plot.figure["layout"]["shapes"]) == 1 and eye(0)._props["icon"] == "visibility_off"
    next(h.handler for h in eye(0)._event_listeners.values() if h.type == "click")(None)
    await asyncio.sleep(0.1)
    assert len(plot.figure["layout"]["shapes"]) == 2
    b0 = next(iter(user.find(marker="sec_plot_0").elements))
    next(h.handler for h in b0._event_listeners.values() if h.type == "click")(None)
    await asyncio.sleep(0.1)
    assert "primary" in next(iter(user.find(marker="sec_plot_0").elements))._props.get("color", "")


async def test_particles_depth_background_drag_and_reload(user: User, tmp_path, monkeypatch):
    """Partículas: batimetría de fondo e isobatas; al arrastrar la barra de tiempo solo se dibuja el último instante
    (antes cada valor intermedio mandaba un fotograma y la página se recargaba); al recargar, las partículas siguen."""
    import asyncio
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=particles")
    await user.should_see("Campo de fondo")
    plot = next(iter(user.find(marker="p_plot").elements))
    next(iter(user.find(marker="p_bg").elements)).set_value("depth"); next(iter(user.find(marker="p_isobaths").elements)).set_value(True)
    await asyncio.sleep(0.1)
    assert plot.figure["layout"]["title"]["text"].startswith("profundidad")      # (fondo plano: sin isobatas que dibujar)
    rb = next(iter(user.find(marker="p_release").elements))
    next(h.handler for h in rb._event_listeners.values() if h.type == "click")(None)
    for _ in range(100):
        await asyncio.sleep(0.1)
        if len(plot.figure["data"]) >= 4:
            break
    calls = []
    monkeypatch.setattr(type(plot), "run_plot_method", lambda self, name, *a, **k: calls.append((name, a)))
    tsl = next(iter(user.find(marker="p_time").elements))
    for k in range(1, 7):                                   # arrastre: muchos valores seguidos
        tsl.set_value(k)
    await asyncio.sleep(0.4)
    assert 1 <= sum(1 for n, a in calls if n == "restyle" and a[1] == [1, 3]) <= 2
    assert not any(n == "restyle" and a[1] == [0] for n, a in calls)          # con batimetría de fondo no se reenvía el campo
    await user.open(f"/results?case={p}&tab=particles")                    # recargar la página
    await user.should_see("distancia media recorrida")


@requires_pro
async def test_mesh_page_keeps_flood_zone_from_yaml(user: User, tmp_path):
    """Una zona inundable escrita en el YAML como rectángulo se conserva al guardar (antes pasaba a «toda la malla» y
    la tierra baja de todo el dominio, a 3 m, agotó la memoria en Ciutadella)."""
    import yaml
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction
    zona = {"lon": [3.823, 3.839], "lat": [39.995, 40.007]}
    cfg = {"name": "inu", "mesh": {"generator": "ocsmesh", "polygon": [[3.0, 39.45], [4.45, 39.45], [4.45, 40.25], [3.0, 40.25]],
                                   "bathymetry": [{"source": "gebco2021"}], "resolution": {"min": 250, "max": 2500, "regions": []},
                                   "inundation": {"region": zona, "max_elevation": 4.0, "dem": "mdt02", "size": 3.0}}}
    p = tmp_path / "inu.yaml"; p.write_text(yaml.safe_dump(cfg))
    await user.open(f"/mesh?case={p}")
    await user.should_see("zona del YAML")
    btn = [b for b in user.find(ui.button).elements if getattr(b, "text", "") == "Guardar"]
    UserInteraction(user, {btn[0]}, None).click()
    await user.should_see("Guardado")
    assert yaml.safe_load(p.read_text())["mesh"]["inundation"]["region"] == zona


@requires_pro
async def test_mesh_page_keeps_layer_zone_from_yaml(user: User, tmp_path):
    """Una capa de batimetría con zona lon/lat del YAML se muestra como «zona del YAML» y se conserva al guardar."""
    import yaml
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction
    zona = {"lon": [3.78, 4.0], "lat": [39.93, 40.07]}
    cfg = {"name": "capa", "mesh": {"generator": "ocsmesh", "polygon": [[3.0, 39.45], [4.45, 39.45], [4.45, 40.25], [3.0, 40.25]],
                                    "bathymetry": [{"source": "gebco2021"}, {"source": "emodnet2024", "region": zona, "blend_km": 1}],
                                    "resolution": {"min": 250, "max": 2500, "regions": []}}}
    p = tmp_path / "capa.yaml"; p.write_text(yaml.safe_dump(cfg))
    await user.open(f"/mesh?case={p}")
    sel = [e for e in user.find(ui.select).elements if e._props.get("label") == "Zonas de alta resolución" and e.value == "__yaml__"]
    assert sel, "la capa debería mostrar «zona del YAML»"
    btn = [b for b in user.find(ui.button).elements if getattr(b, "text", "") == "Guardar"]
    UserInteraction(user, {btn[0]}, None).click()
    await user.should_see("Guardado")
    assert yaml.safe_load(p.read_text())["mesh"]["bathymetry"][1]["region"] == zona


async def test_case_card_refreshes_when_files_appear(user: User, tmp_path):
    """La tarjeta del caso marca «malla» sola cuando aparece hgrid.gr3 (antes había que recargar la página)."""
    import asyncio, shutil, yaml
    from nicegui import ui
    cfg = yaml.safe_load(open("cases/tests/prueba_2d.yaml"))
    p = tmp_path / "tarjeta.yaml"; p.write_text(yaml.safe_dump(cfg))
    await user.open(f"/model?case={p}")
    await user.should_see("Física")
    n_ok = lambda: sum(1 for e in user.find(ui.icon).elements if e._props.get("name") == "check_circle" and "16px" in str(e._props.get("size", "")))
    before = n_ok()
    wd = tmp_path / cfg["name"]; wd.mkdir(exist_ok=True); (wd / "hgrid.gr3").write_text("x")
    await asyncio.sleep(4.6)
    assert n_ok() == before + 1
