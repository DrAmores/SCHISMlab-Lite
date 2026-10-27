"""Mejoras de 0.7.4 pedidas al repetir las prácticas con Lite 0.7.3 (mejoras_herramienta.md, 26/10/2026)."""
import sys
from pathlib import Path
import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))


def test_integral_hasta_la_superficie_libre():
    # con η > 0 el nivel de superficie está en z > 0: «hasta 0» lo incluye (P6: Tx 3.51 en vez de 4.08)
    from schismlab.analysis.profiles import ekman_readouts
    z = np.array([-50.0, -30.0, -10.0, 0.3]); u = np.array([0.0, 0.1, 0.2, 0.3]); v = np.zeros(4)
    r = ekman_readouts(z, u, v, integ=(-50.0, 0.0))
    assert r["Tx"] == pytest.approx(np.trapezoid(u, z))
    assert ekman_readouts(z, u, v, integ=(None, 0.0))["Tx"] == pytest.approx(r["Tx"])     # «desde» vacío: el fondo
    assert ekman_readouts(z, u, v, integ=(-30.0, -10.0))["Tx"] == pytest.approx(0.15 * 20)
    assert r["bottom_still"]


def test_hodografa_sin_el_fondo_y_aviso_de_viscosidad():
    from schismlab.gui.explorer import ekman_figures, ekman_text
    from schismlab.analysis.profiles import ekman_readouts
    z = np.linspace(-100, 0, 11); u = np.exp(z / 14) * 0.2; u[0] = 0.0; v = np.zeros(11)
    d = dict(ekman_readouts(z, u, v, ref=(0.01, 0.0), fit=(-28, 0), f=1e-4), u=u, v=v, zraw=z, visc=None, wind=None, f=1e-4,
             ref_txt="", n=1, visc_range=(0.001, 0.02))
    _, hf = ekman_figures(d, "es")
    assert len(hf.data[0].x) == 10                                        # sin el punto (−u_ref, −v_ref) del fondo
    assert "supone A_z constante" in ekman_text(d, "es")
    d["visc_range"] = (0.01, 0.011)
    assert "supone A_z constante" not in ekman_text(d, "es")


def test_cruces_con_referencia_unidades_y_rango_minimo():
    from schismlab.gui.figures import section_line_figure, times_m
    from schismlab.gui.explorer import line_readout
    from schismlab.analysis.sections import Section
    from test_practicas_gui import gyre_ds
    ds = gyre_ds(); sec = Section(ds, (0.0, 50e3), (100e3, 50e3))
    T = 12 + 8 / (1 + np.exp((sec.dist - 40) / 3))                         # frente de 20 → 12 °C en 40 km
    _, info = section_line_figure(sec, T, "T", ref=16.0, units="°C")
    assert info["zeros"][0] == pytest.approx(40.0, abs=0.5) and "Cruces con y = 16" in line_readout(info, "°C")
    assert times_m("m/s") == "m²/s" and times_m("m²/s") == "m³/s" and times_m("°C") == "°C·m"
    fig, _ = section_line_figure(sec, 0.1002738 + 1e-9 * sec.dist, "u")    # casi constante: no se dibuja como una forma
    lo, hi = fig.layout.yaxis.range
    assert hi - lo > 1e-4
    assert "extremo oeste (O)" in fig.layout.xaxis.title.text


def test_marcas_de_color_y_escala_de_elevacion():
    from schismlab.gui.figures import zero_ticks, elevation_range
    tv = zero_ticks(-0.06, 0.06); assert 0.0 in tv and all(abs(x) < 1e-12 or abs(x) > 1e-3 for x in tv)
    a = 0.46 + 0.05 * np.sin(np.linspace(0, 6, 500))                       # nivel medio grande: no se centra en 0
    lo, hi = elevation_range(a); assert lo > 0.4 and hi < 0.52
    lo, hi = elevation_range(np.sin(np.linspace(0, 6, 500))); assert lo == pytest.approx(-hi)


def test_puntos_de_la_seccion_segun_la_malla():
    from schismlab.analysis.sections import Section
    from schismlab.mesh import rectangular_basin
    import xarray as xr
    m = rectangular_basin(1000e3, 50e3, 2e3, depth=100.0)
    ds = xr.Dataset({"depth": ("node", m.depth)}, coords={"x": ("node", m.x), "y": ("node", m.y)}); ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    s = Section(ds, (0.0, 25e3), (1000e3, 25e3))
    assert s.dist.size >= 700                                              # antes 120 (un punto cada 8 km)
    assert Section(ds, (0.0, 25e3), (10e3, 25e3)).dist.size == 120


def test_batimetria_analitica_en_lon_lat():
    from schismlab.mesh.build import _depth_callable
    cfg = {"lon": [0.0, 2.0], "lat": [40.0, 41.0]}
    f = _depth_callable({"kind": "shelf", "h_shelf": 50, "h_deep": 1000, "x_shelf": 50e3, "L_slope": 20e3}, cfg)
    h = f(np.array([0.1, 1.5]), np.array([40.5, 40.5]))                   # 0.1° ≈ 8.5 km (plataforma), 1.5° ≈ 127 km (fondo)
    assert h[0] == pytest.approx(50) and h[1] == pytest.approx(1000)


def test_lineas_de_marea_solo_con_marea():
    from schismlab.gui.explorer import case_tides
    from schismlab.analysis.signal import reference_periods
    assert case_tides({"boundaries": {"elevation": "none"}}) == []
    assert case_tides({"boundaries": [{"sides": ["east"], "elevation": {"tides": {"constituents": ["m2", "K1"]}}}]}) == ["M2", "K1"]
    assert case_tides({"boundaries": {"tidal_potential": True}})
    r = reference_periods(45.0, tides=[]); assert set(r) == {"inercial"}
    assert set(reference_periods(45.0, tides=["M2"])) == {"M2", "inercial"}


pytest.importorskip("nicegui")
from nicegui.testing import User            # noqa: E402
pytest_plugins = ["nicegui.testing.user_plugin"]


async def test_seccion_sigue_al_mapa_y_medias_en_tabla(user: User, tmp_path, monkeypatch):
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    user.find(marker="var_select").elements.pop().set_value("temperature")
    assert user.find(marker="sec_var").elements.pop().value == "temperature"
    user.find(marker="sec_var").elements.pop().set_value("horizontalVel")          # elegida a mano: ya no sigue al mapa
    user.find(marker="var_select").elements.pop().set_value("elevation")
    assert user.find(marker="sec_var").elements.pop().value == "horizontalVel"
    user.find(marker="avg_switch").elements.pop().set_value(True)
    m = user.find(marker="series_means").elements.pop()
    assert m.visible and "centro" in m.content


async def test_cierre_turbulento_en_2d(user: User, tmp_path):
    from schismlab.edition import is_pro
    p = tmp_path / "c2d.yaml"
    p.write_text(yaml.safe_dump({"name": "c2d", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50},
                                 "vertical": {"type": "2d"}, "physics": {"turbulence": 3}}))
    await user.open(f"/model?case={p}")
    await user.should_see("Malla vertical")
    if is_pro():                                                                 # Pro deja elegir el cierre también en 2D
        await user.should_see(marker="turb_select"); await user.should_not_see(marker="turb_2d")
    else:                                                                        # Lite: en 2D se oculta (itur = 0)
        await user.should_see(marker="turb_2d"); await user.should_not_see(marker="turb_select")


# 0.7.5: repetición con Lite 0.7.4 (mejoras_herramienta.md, 27/10/2026)

async def test_promedio_lee_la_fecha_del_navegador(user: User, tmp_path, monkeypatch):
    """Intro en t2 aplica el texto que manda el navegador aunque el valor del campo en el servidor sea el anterior
    (la última tecla no llegó): antes la media seguía con la ventana vieja."""
    from schismlab.gui import state
    from test_explorer import make_case
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    p = make_case(tmp_path / "cases")
    await user.open(f"/results?case={p}&tab=maps")
    await user.should_see("Puntos")
    user.find(marker="avg_switch").elements.pop().set_value(True)
    a = user.find(marker="avg_from").elements.pop().value
    full = user.find(marker="avg_text").elements.pop().text
    t2 = a[:11] + "02:00"
    user.find(marker="avg_to").trigger("keydown.enter", args=t2)              # el servidor aún tiene la fecha final
    assert user.find(marker="avg_to").elements.pop().value == t2
    txt = user.find(marker="avg_text").elements.pop().text
    assert txt != full and "02:00)" in txt


def test_escalas_con_cero_y_elevacion_sin_reposo_inicial():
    from schismlab.gui.figures import elevation_range, _signed_ticks, difference_figure
    # instantes: reposo (η = 0), rampa y nivel 0.36–0.56 m: la escala fija no baja hasta 0
    a = np.stack([np.zeros(200), np.linspace(0.1, 0.2, 200)] + [np.linspace(0.36, 0.56, 200)] * 6)
    lo, hi = elevation_range(a, per_instant=True); assert lo > 0.3 and hi == pytest.approx(0.558, abs=0.01)
    assert elevation_range(np.linspace(0.36, 0.56, 200).reshape(10, 20))[0] == pytest.approx(0.362, abs=0.01)  # un instante en rejilla
    tv = _signed_ticks(np.array([[-4.4e-5, 3e-5]]), {}); assert 0.0 in tv
    assert _signed_ticks(np.array([[1.0, 2.0]]), {}) is None


def test_eje_de_la_vista_previa_de_fisica():
    from schismlab.gui.ic_builder import section_figure
    from schismlab.forcing.vgrid import VGrid
    X, Y = np.meshgrid(np.linspace(5e3, 105e3, 21), np.linspace(0, 50e3, 11))
    frame = {"x": X.ravel(), "y": Y.ravel(), "lon": X.ravel() * 0, "lat": Y.ravel() * 0 + 40}
    fig = section_figure(frame, np.full(X.size, 100.0), VGrid.sigma(10), {"value": "10 + z / 10"}, "x", "T", "es")
    assert fig.layout.xaxis.title.text == "distancia desde el extremo oeste (O) (km)"
    assert float(np.min(fig.data[0].x)) == 0.0 and float(np.max(fig.data[0].x)) == pytest.approx(100.0)
