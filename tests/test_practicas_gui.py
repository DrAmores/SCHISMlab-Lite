"""Bloque 2 de las prácticas con Lite (interfaz): las preguntas que pedían el cuaderno se contestan en Mapas y series
(variables derivadas, componentes con signo, promedio entre t1 y t2, secciones de variables 2D con ajuste e integral,
perfil y hodógrafa con las lecturas de la espiral de Ekman)."""
import sys
from pathlib import Path
import numpy as np
import pytest
import xarray as xr

pytest.importorskip("nicegui")
from nicegui import ui                      # noqa: E402
from nicegui.testing import User            # noqa: E402
from schismlab.mesh import rectangular_basin  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_explorer import make_case          # noqa: E402

pytest_plugins = ["nicegui.testing.user_plugin"]


def gyre_ds(nt=6, nv=11):
    """Cuenca cartesiana 3D: giro de sólido rígido que crece con el tiempo + espiral de Ekman en la vertical, viento
    hacia el este y η con pendiente (geostrófica conocida)."""
    from schismlab.analysis.profiles import theoretical_spiral
    m = rectangular_basin(100e3, 100e3, 10e3, depth=200.0)
    x, y = m.x - 50e3, m.y - 50e3
    t = np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h")
    zz = np.linspace(-200, 0, nv); Z = np.broadcast_to(zz, (nt, m.nnodes, nv)).copy()
    _, uE, vE = theoretical_spiral(0.2, 14.0, 1e-4, wind_dir=(1.0, 0.0), zmin=-200, n=nv)
    amp = np.arange(1, nt + 1)[:, None]
    U = (-1e-6 * y[None, :] * amp)[:, :, None] + uE[None, None, :] + 0.01
    V = (1e-6 * x[None, :] * amp)[:, :, None] + vE[None, None, :]
    eta = np.broadcast_to(1e-6 * m.x, (nt, m.nnodes)).copy()
    ds = xr.Dataset({"horizontalVelX": (("time", "node", "layer"), U), "horizontalVelY": (("time", "node", "layer"), V),
                     "zCoordinates": (("time", "node", "layer"), Z), "elevation": (("time", "node"), eta),
                     "windStressX": (("time", "node"), np.full((nt, m.nnodes), 1e-4)), "windStressY": (("time", "node"), np.zeros((nt, m.nnodes))),
                     "depthAverageVelX": (("time", "node"), U.mean(-1)), "depthAverageVelY": (("time", "node"), V.mean(-1)), "depth": ("node", m.depth)},
                    coords={"time": t, "x": ("node", m.x), "y": ("node", m.y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    return ds


CFG = {"physics": {"coriolis": "f-plane"}, "reference": {"lat0": 43.4}}


def test_estado_derivadas_promedio_y_componentes():
    from schismlab.gui.explorer import ExplorerState, map_figure, series_figure_multi
    from schismlab.gui.i18n import TEXT
    ds = gyre_ds(); st = ExplorerState(ds, None, CFG)
    assert {"vorticity", "vorticity_f", "transport", "streamfunction"} <= set(st.vars)
    assert st.is3d("vorticity") and not st.is3d("transport") and st.is_vector("transport")
    c = int(np.argmin(np.hypot(ds.x - 50e3, ds.y - 50e3).values))
    st.var = "vorticity"; st.layer = st.nvrt - 1; st.it = 0
    assert st.field("vorticity", 0)[c] == pytest.approx(2e-6, rel=1e-3)
    st.window = np.arange(6)                                            # media: 2e-6 · (1+…+6)/6
    assert st.field("vorticity", 0)[c] == pytest.approx(2e-6 * 3.5, rel=1e-3)
    d = map_figure(st, TEXT["es"], "es"); assert "media de 6 salidas" in str(d["layout"]["title"])
    st.window = None; st.var = "transport"; st.mcomp = "u"
    U = st.field("transport", 0)
    assert U[c] == pytest.approx(np.trapezoid(ds.horizontalVelX.isel(time=0, node=c).values, np.linspace(-200, 0, 11)), rel=1e-6)
    assert st.signed("transport") and st.value_range("transport")[0] < 0
    d = map_figure(st, TEXT["es"], "es"); assert "Tx" in str(d["layout"]["title"])
    st.mcomp = "mag"; st.var = "horizontalVel"; st.add_point(50e3, 50e3); st.window = np.arange(2, 5)
    f = series_figure_multi(st, "horizontalVel", "es")
    assert "media" in f.layout.title.text and st._mean_traces == 2           # media de u y de v en la ventana


def test_seccion_2d_integral_y_componentes():
    from schismlab.gui.explorer import ExplorerState, section_values, section_hovmoller, line_readout
    from schismlab.gui.figures import section_line_figure
    ds = gyre_ds(); st = ExplorerState(ds, None, CFG)
    s = st.add_section((0.0, 50e3), (100e3, 50e3))                       # de oeste a este por el centro
    F, z, _ = section_values(st, s, "transport", [0], "normal")          # normal (a la izquierda = norte): Ty
    assert F.ndim == 1
    V = section_values(st, s, "transport", [0], "v")[0]
    assert np.allclose(F, V, equal_nan=True)
    fig, info = section_line_figure(s["sec"], F, "Ty", "es", integ=(0, 100), units="m²/s", fit=(10, 90))
    assert info["integral_units"] == "m³/s" and info["integral"] is not None and info["fit"] is not None
    txt = line_readout(info, "m²/s", "es"); assert "Sv" in txt and "1/α" in txt
    F3, z3, _ = section_values(st, s, "horizontalVel", [0, 1], "tangential")
    assert F3.shape == z3.shape and F3.ndim == 2
    H = section_hovmoller(st, s, "elevation"); assert H.shape == (ds.time.size, s["sec"].dist.size)


def test_ekman_lecturas_en_la_interfaz():
    from schismlab.gui.explorer import ExplorerState, ekman_profile, ekman_figures, ekman_text
    ds = gyre_ds(); st = ExplorerState(ds, None, CFG)
    c = int(np.argmin(np.hypot(ds.x - 50e3, ds.y - 50e3).values))
    d = ekman_profile(st, c, [0], "level", 0, fit=(-28, 0))
    assert d["surface_angle"] == pytest.approx(45.0, abs=0.5) and d["De"] == pytest.approx(14.0, rel=0.02)
    pf, hf = ekman_figures(d, "es", theory=(0.2, 14.0))
    assert hf.layout.yaxis.scaleanchor == "x" and len(hf.data) == 2
    assert "a la derecha del viento" in ekman_text(d, "es")
    g = ekman_profile(st, c, [0, 1], "geo", 0)                            # geostrófica de η: ug = 0, vg = g/f ∂η/∂x
    f = 2 * 7.292115e-5 * np.sin(np.deg2rad(43.4))
    assert g["ref"][1] == pytest.approx(9.81 / f * 1e-6, rel=0.02) and abs(g["ref"][0]) < 1e-6


async def test_pagina_controles_nuevos(user: User, tmp_path, monkeypatch):
    from schismlab.gui import state
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    var = user.find(marker="var_select").elements.pop()
    assert "vorticity" in var.options and "transport" in var.options
    var.set_value("transport")
    user.find(marker="map_component").elements.pop().set_value("v")
    user.find(marker="avg_switch").elements.pop().set_value(True)
    await user.should_see("media de")
    var.set_value("vorticity")
    user.find(marker="ekman_panel").elements.pop().set_value(True)
    await user.should_see("Corriente en superficie")
    user.find(marker="ek_ref").elements.pop().set_value("none")
    tin = user.find(marker="time_input").elements.pop(); tin.set_value("2020-01-01 03:00")
    await user.should_see("Puntos")


async def test_seccion_en_el_nivel_del_mapa(user: User, tmp_path, monkeypatch):
    """Variable 3D en una sección como curva en la capa del mapa (P4: v en superficie a lo largo de la sección)."""
    from schismlab.gui import state
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    user.find(marker="explorer_subtabs").elements.pop().set_value("tab_sections")
    user.find(marker="map_plot").trigger("plotly_click", {"points": [{"x": 0.2, "y": 40.25}]})
    user.find(marker="map_plot").trigger("plotly_click", {"points": [{"x": 1.8, "y": 40.25}]})
    user.find(marker="sec_var").elements.pop().set_value("horizontalVel")
    user.find(marker="sec_component").elements.pop().set_value("v")
    user.find(marker="sec_atlevel").elements.pop().set_value(True)
    user.find(marker="sec_integral").elements.pop().set_value(True)
    await user.should_see("Integral a lo largo")
    fg = user.find(marker="sec_plot").elements.pop().figure
    fg = fg.to_plotly_json() if hasattr(fg, "to_plotly_json") else fg
    assert fg["data"][0]["type"] == "scatter"                          # curva, no mapa de calor


async def test_fisica_viscosidad_constante(user: User, tmp_path):
    # Física: dfv0 y dfh0 se ven solo sin cierre turbulento (itur = 0) y se guardan en param del YAML
    import yaml
    p = tmp_path / "visc.yaml"
    p.write_text(yaml.safe_dump({"name": "visc", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50},
                                 "vertical": {"type": "sigma", "nvrt": 6}, "physics": {"baroclinic": False, "turbulence": 0}}))
    await user.open(f"/model?case={p}")
    await user.should_see("Viscosidad vertical")
    user.find(marker="dfv0").elements.pop().set_value(0.05)
    user.find(marker="shapiro0").elements.pop().set_value(0.5)
    user.find("Guardar").click()
    c = yaml.safe_load(p.read_text())
    assert c["param"]["dfv0"] == 0.05 and "dfh0" not in c.get("param", {}) and c["physics"]["shapiro0"] == 0.5
    await user.open(f"/model?case={p}")
    assert user.find(marker="dfv0").elements.pop().value == 0.05
    from nicegui import ui as _ui
    turb = [e for e in user.find(_ui.select).elements if "Cierre" in str(e.props.get("label", ""))].pop()
    turb.set_value(3)
    await user.should_not_see("Viscosidad vertical")
