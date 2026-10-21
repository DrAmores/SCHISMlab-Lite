"""Explorador de resultados (Mapas, Espectro, Comparar) y robustez de la página de resultados con una simulación
sintética escrita en tmp_path con el formato scribed de SCHISM (out2d_N.nc + <variable>_N.nc), sin depender de
~/.schismlab/runs. También las guardas de app.py (safe_select, YAML inválido, vgrid_of, read_stations archivadas)."""
from pathlib import Path
import numpy as np
import pytest
import xarray as xr
import yaml

pytest.importorskip("nicegui")
from nicegui import ui                      # noqa: E402
from nicegui.testing import User            # noqa: E402
from schismlab.mesh import rectangular_basin  # noqa: E402
from schismlab.io.gr3 import write_gr3        # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]
NODE, LAYER, FACE = "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers", "nSCHISM_hgrid_face"


def write_outputs(out: Path, mesh, nvrt: int = 6, nt: int = 8, stations: bool = True, start="2020-01-01"):
    """Escribe out2d_1.nc, temperature_1.nc, horizontalVel{X,Y}_1.nc y zCoordinates_1.nc (y staout) como SCHISM."""
    out.mkdir(parents=True, exist_ok=True)
    x, y, h = mesh.x, mesh.y, mesh.depth
    nn = x.size
    t = np.datetime64(start) + np.arange(nt) * np.timedelta64(1, "h")
    faces = np.full((len(mesh.elements), 4), np.nan)
    faces[:, :3] = np.asarray(mesh.elements)[:, :3] + 1                         # 1-based, 4ª columna vacía (triángulos)
    tt = np.arange(nt)[:, None]
    eta = 0.3 * np.sin(2 * np.pi * tt / 12.42) * np.cos(np.pi * (x - x.min()) / np.ptp(x))[None, :]
    ds2 = xr.Dataset({"SCHISM_hgrid_node_x": (NODE, x), "SCHISM_hgrid_node_y": (NODE, y), "depth": (NODE, h),
                      "SCHISM_hgrid_face_nodes": ((FACE, "nMaxSCHISM_hgrid_face_nodes"), faces),
                      "elevation": (("time", NODE), eta), "dryFlagNode": (("time", NODE), np.zeros((nt, nn), np.int8))},
                     coords={"time": t})
    ds2.to_netcdf(out / "out2d_1.nc")
    sig = np.linspace(-1, 0, nvrt)
    Z = (eta[:, :, None] + h[None, :, None]) * sig[None, None, :] + eta[:, :, None]
    T = 10 + 10 * (Z > -50) + 0.5 * np.sin(2 * np.pi * tt / 24)[:, :, None]
    U = 0.5 * np.ones((nt, nn, nvrt)) * (sig[None, None, :] + 1.2); V = 0.2 * np.ones((nt, nn, nvrt))
    for name, arr in (("temperature", T), ("horizontalVelX", U), ("horizontalVelY", V), ("zCoordinates", Z)):
        xr.Dataset({name: (("time", NODE, LAYER), arr)}, coords={"time": t}).to_netcdf(out / f"{name}_1.nc")
    if stations:
        ts = np.arange(0, nt * 3600, 600.0)
        np.savetxt(out / "staout_1", np.column_stack([ts, 0.3 * np.sin(2 * np.pi * ts / 44714)]))
        for k in range(2, 10):
            (out / f"staout_{k}").write_bytes(b"")                            # como una simulación que solo guardó η


def write_run_inputs(wd: Path, mesh, cfg: dict):
    """station.in, param.nml, vgrid.in, hgrid.gr3 y caso.yaml en la carpeta de la simulación (como el setup)."""
    wd.mkdir(parents=True, exist_ok=True)
    sta = cfg.get("stations") or []
    (wd / "station.in").write_text("1 0 0 0 0 0 0 0 0\n" + f"{len(sta)}\n" + "".join(f"{i} {s['lon']} {s['lat']} 0.0 !{s['name']}\n" for i, s in enumerate(sta, 1)))
    (wd / "param.nml").write_text("&CORE\n  rnday = 0.3333\n  dt = 60.\n/\n&OPT\n  start_year = 2020\n  start_month = 1\n  start_day = 1\n  start_hour = 0.\n/\n")
    from schismlab.forcing import VGrid
    v = cfg.get("vertical") or {}
    VGrid.sigma(int(v.get("nvrt", 6)), float(v.get("h_c", 5)), 0.0, float(v.get("theta_f", 0.001))).write(wd / "vgrid.in")
    write_gr3(wd / "hgrid.gr3", mesh)
    (wd / "caso.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def make_case(root: Path, name: str = "caso", nvrt: int = 6, nt: int = 8, stations=True, archived: bool = False) -> Path:
    """Caso idealizado en lon/lat con su simulación sintética; devuelve la ruta del YAML (workdir = root/name)."""
    mesh = rectangular_basin(0, 0, 10e3, depth=100.0, lon=(0, 2), lat=(40, 40.5))
    cfg = {"name": name, "mesh": {"generator": "idealized", "lon": [0, 2], "lat": [40, 40.5], "dx": 10000, "bathymetry": 100, "open_sides": []},
           "vertical": {"type": "sigma", "nvrt": nvrt, "h_c": 5, "theta_b": 0, "theta_f": 0.001},
           "time": {"start": "2020-01-01", "days": 0.3333, "dt": 60}, "physics": {"baroclinic": True, "turbulence": 0},
           "initial": {"elevation": 0, "temperature": 20, "salinity": 36}, "forcing": {}, "boundaries": {"elevation": "none"},
           "output": {"interval_minutes": 60, "variables": ["elevation", "horizontalVel", "temperature", "zCoordinates"], "station_variables": ["elev"]},
           "stations": [{"name": "centro", "lon": 1.0, "lat": 40.25}] if stations else []}
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{name}.yaml"; p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    wd = root / name
    write_run_inputs(wd, mesh, cfg)
    write_outputs(wd / "outputs", mesh, nvrt=nvrt, nt=nt, stations=stations)
    if archived:                                                   # como run.archive_outputs: outputs_<fecha>/ autocontenida
        arc = wd / "outputs_20200101-0000"
        write_outputs(arc, mesh, nvrt=nvrt, nt=nt, stations=stations)
        write_run_inputs(arc, mesh, cfg)
    return p


@pytest.fixture
def case(tmp_path, monkeypatch):
    from schismlab.gui import state
    cases = tmp_path / "cases"
    monkeypatch.setattr(state, "USER_CASES", cases)
    return make_case(cases)


@pytest.fixture
def gui_app():
    """schismlab.gui.app para pruebas sin simulador. Al acabar se quita de sys.modules: el simulador de NiceGUI
    registra las páginas al ejecutar main.py y, si el módulo ya estuviera importado, se quedaría sin rutas (404)."""
    import sys
    import schismlab.gui.app as app
    yield app
    for k in [k for k in sys.modules if k == "schismlab.gui.app"]:
        sys.modules.pop(k, None)


# ----------------------------------------------------------------------------- lectura
def test_open_run_synthetic(case):
    from schismlab.analysis import open_run, read_stations
    ds = open_run(case.parent / "caso")
    assert ds.sizes["node"] > 10 and ds.sizes["layer"] == 6 and ds.sizes["time"] == 8
    assert {"elevation", "temperature", "horizontalVelX", "zCoordinates", "depth"} <= set(ds.data_vars)
    assert ds.attrs["elements"].shape[1] == 3 and ds.attrs["elements"].min() == 0
    d = read_stations(case.parent / "caso", "elev")
    assert list(d.columns) == ["centro"] and d.shape[0] == 48
    with pytest.raises(ValueError):
        read_stations(case.parent / "caso", "T")                   # staout_5 vacío


def test_read_stations_archived_run(tmp_path, monkeypatch):
    """Simulación archivada (outputs_<fecha>/): los staout están en la raíz, sin subcarpeta outputs/."""
    from schismlab.gui import state
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases", archived=True)
    from schismlab.analysis import read_stations
    arc = p.parent / "caso" / "outputs_20200101-0000"
    assert not (arc / "outputs").exists() and (arc / "staout_1").exists()
    assert list(read_stations(arc, "elev").columns) == ["centro"]


def test_vgrid_of_reads_run_dir_and_falls_back(case, gui_app):
    vgrid_of = gui_app.vgrid_of
    from schismlab.analysis import open_run
    wd = case.parent / "caso"; ds = open_run(wd)
    c = yaml.safe_load(case.read_text())
    assert vgrid_of(c, wd, ds).nvrt == 6
    c2 = dict(c); c2["vertical"] = {"type": "sigma", "nvrt": 30}      # el caso cambió después de la simulación
    assert vgrid_of(c2, wd, ds).nvrt == 6                              # manda caso.yaml / el dataset de la carpeta
    (wd / "vgrid.in").write_text("1 !ivcor\n6 \n")                     # LSC2: no se parsea, se deduce del dataset
    c3 = dict(c); c3["vertical"] = {"type": "sz", "nsigma": 5, "zlevels": [-80, -60]}
    (wd / "caso.yaml").write_text(yaml.safe_dump(c3))
    assert vgrid_of(c3, wd, ds).nvrt == 6
    (wd / "vgrid.in").unlink(); (wd / "caso.yaml").unlink()
    assert vgrid_of({"vertical": {"type": "2d"}}, wd, ds).nvrt == 6    # sin vgrid: nvrt del dataset
    assert vgrid_of({"vertical": {"type": "2d"}}, wd, None).nvrt == 2


# ----------------------------------------------------------------------------- guardas de la interfaz
def test_safe_select(gui_app):
    safe_select = gui_app.safe_select
    assert safe_select({0: "a", 3: "b"}, 3, 0) == 3
    assert safe_select({0: "a", 3: "b"}, 2, 0) == 0
    assert safe_select(["f-plane", "beta", "none"], False, "f-plane") == "f-plane"
    assert safe_select(["f-plane", "beta", "none"], None, "none") == "none"
    assert safe_select(["M2", "S2"], ["m2", "x1", "S2"], ["M2"], multiple=True) == ["M2", "S2"]
    assert safe_select(["M2", "S2"], ["x1"], ["M2"], multiple=True) == ["M2"]
    opts = {"a": "A"}
    assert safe_select(opts, "zz", "a", keep_unknown=True) == "zz" and "zz" in opts


async def test_pages_tolerate_odd_yaml_values(user: User, case):
    """Valores válidos para setup pero fuera de las listas de la interfaz no deben dar un error 500."""
    c = yaml.safe_load(case.read_text())
    c["physics"] = {"baroclinic": True, "turbulence": 2, "coriolis": False}
    c["initial"]["source"] = {"name": "cmems"}; c["friction"] = {"landcover": "/tmp/usos.tif", "manning": 0.02}
    c["boundaries"] = {"elevation": "th", "source": {"name": "medsea"}}
    c["waves"] = {"enabled": True, "boundary": {"type": "spectral", "source": "otro"}}
    c["runup"] = {"method": "xbeach"}
    case.write_text(yaml.safe_dump(c, sort_keys=False))
    for path in ("/model", "/forcing", "/results?tab=validate"):
        await user.open(f"{path}?case={case}")
        await user.should_see("paso a paso")
    c["boundaries"] = {"elevation": {"tides": {"source": "tpxo", "constituents": ["m2", "zz"]}}}
    case.write_text(yaml.safe_dump(c, sort_keys=False))
    await user.open(f"/forcing?case={case}")
    await user.should_see("paso a paso")


async def test_invalid_yaml_shows_message(user: User, case):
    case.write_text("name: caso\nmesh: [unclosed\n  generator: idealized\n")
    for path in ("/", "/model", "/results"):
        await user.open(f"{path}?case={case}")
        await user.should_see("paso a paso")
    await user.should_see("YAML")


# ----------------------------------------------------------------------------- explorador
async def test_results_maps_renders_and_time_slider(user: User, case):
    await user.open(f"/results?case={case}&tab=maps")
    await user.should_see("Puntos")
    await user.should_see("centro")                                    # la estación del caso es un punto; sin P1 automático
    plots = user.find(ui.plotly).elements
    assert plots
    names = [str(p.get("text")) for p in user.find(marker="map_plot").elements.pop().figure["data"] if p.get("mode") == "markers+text"]
    assert names and all("P1" not in n for n in names)
    tsl = user.find(marker="time_slider").elements.pop()
    tsl.set_value(2); tsl.set_value(5)                                 # ruta rápida (restyle) o respaldo: sin excepción
    var = user.find(marker="var_select").elements.pop()
    var.set_value("temperature")
    await user.should_see("Puntos")


async def test_results_maps_2d(user: User, tmp_path, monkeypatch):
    """Simulación 2D (solo elevación, una capa): sin deslizador de capa y sin fallo en el selector de secciones."""
    from schismlab.gui import state
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases", name="plano", nvrt=1, stations=False)
    wd = p.parent / "plano"
    for f in wd.glob("outputs/*_1.nc"):
        if f.name != "out2d_1.nc":
            f.unlink()
    c = yaml.safe_load(p.read_text()); c["vertical"] = {"type": "2d"}; p.write_text(yaml.safe_dump(c)); (wd / "caso.yaml").write_text(yaml.safe_dump(c))
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")


async def test_results_spectrum_stations(user: User, case):
    """Espectro: fuente «estaciones» solo ofrece las variables con staout no vacío y no revienta al cambiarla."""
    await user.open(f"/results?case={case}&tab=spectrum")
    await user.should_see("ventana")
    src = user.find(marker="spectrum_src").elements.pop()
    src.set_value("stations")
    svar = user.find(marker="spectrum_svar").elements.pop()
    assert list(svar.options) == ["elev"]
    await user.should_see("centro")


async def test_results_outputs_unreadable(user: User, case):
    """Pila corrupta: la página avisa en vez de dar un error 500."""
    (case.parent / "caso" / "outputs" / "out2d_1.nc").write_bytes(b"corrupto")
    await user.open(f"/results?case={case}&tab=maps")
    await user.should_see("paso a paso")


async def test_compare_warns_on_disjoint_domains(user: User, tmp_path, monkeypatch):
    from schismlab.gui import state
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases", name="a")
    mesh2 = rectangular_basin(0, 0, 10e3, depth=100.0, lon=(10, 12), lat=(45, 45.5))
    cfg2 = yaml.safe_load(p.read_text()); cfg2["name"] = "b"; cfg2["mesh"].update(lon=[10, 12], lat=[45, 45.5])
    p2 = tmp_path / "cases" / "b.yaml"; p2.write_text(yaml.safe_dump(cfg2))
    write_run_inputs(tmp_path / "cases" / "b", mesh2, cfg2); write_outputs(tmp_path / "cases" / "b" / "outputs", mesh2)
    await user.open(f"/results?case={p}&tab=compare")
    await user.should_see("Comparar")
    user.find(marker="compare_btn").click()
    await user.should_see("no se solapan")


# ----------------------------------------------------------------------------- figuras y tema
def test_figures_lang_and_dark():
    from schismlab.gui.figures import label, layout, themed, LABELS
    import plotly.graph_objects as go
    assert label("elevation", "en") == "elevation (m)" and label("elevation", "es") == LABELS["elevation"]
    assert label("desconocida", "en") == "desconocida"
    assert layout(True)["template"] == "plotly_dark" and "template" in layout(False)
    f = themed(go.Figure(), True); assert f.layout.template.layout.paper_bgcolor is not None or f.layout.paper_bgcolor == "rgba(0,0,0,0)"
    d = themed({"data": [], "layout": {}}, True); assert d["layout"]["template"] == "plotly_dark"
