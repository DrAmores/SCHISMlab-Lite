"""Bloque 3 de las prácticas con Lite: errores de presentación (secciones de borde a borde y orientadas, flechas de la
variable, barra de color, espectro rotatorio, ejes en metros, Hovmöller de isosuperficie, salto a una fecha, f del caso)."""
import numpy as np
import pytest
import xarray as xr
from schismlab.mesh import rectangular_basin
from schismlab.analysis.sections import Section, preset_section, compass


def cart_ds(Lx=100e3, Ly=40e3, dx=5e3, nt=3, nvrt=5):
    """Dominio cartesiano (metros) con T en dos capas, velocidad uniforme y viento."""
    m = rectangular_basin(Lx, Ly, dx, depth=100.0)
    x, y = m.x, m.y; t = np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h")
    sig = np.linspace(-1, 0, nvrt); Z = np.broadcast_to(100 * sig, (nt, x.size, nvrt)).copy()
    T = 10 + 10 * (Z > -50)
    one = np.ones((nt, x.size, nvrt))
    ds = xr.Dataset({"elevation": (("time", "node"), np.zeros((nt, x.size))), "temperature": (("time", "node", "layer"), T),
                     "horizontalVelX": (("time", "node", "layer"), 0.5 * one), "horizontalVelY": (("time", "node", "layer"), 0.2 * one),
                     "windStressX": (("time", "node"), np.zeros((nt, x.size))), "windStressY": (("time", "node"), 1e-4 * np.ones((nt, x.size))),
                     "zCoordinates": (("time", "node", "layer"), Z), "depth": ("node", m.depth)},
                    coords={"time": t, "x": ("node", x), "y": ("node", y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    return ds


def test_preset_de_borde_a_borde_y_orientado():
    ds = cart_ds()
    for kind in ("transversal", "longitudinal", "x", "y"):
        p0, p1 = preset_section(ds, (30e3, 20e3), kind)
        s = Section(ds, p0, p1, npts=60)
        assert s.inside[0] and s.inside[-1], kind                         # los extremos caen dentro de la malla
        if abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1]):
            assert p0[0] < p1[0] and p0[0] < 1.0 and p1[0] > 100e3 - 1.0      # de oeste a este, de pared a pared
        else:
            assert p0[1] < p1[1] and p0[1] < 1.0 and p1[1] > 40e3 - 1.0       # de sur a norte
    assert compass(1, 0) == "E" and compass(-1, 0) == "O" and compass(-1, 0, "en") == "W" and compass(0, -1) == "S"


def test_rotary_mismo_tamano_con_nperseg_par():
    from schismlab.analysis.signal import rotary_spectrum
    t = np.arange(512) * 600.0
    r = rotary_spectrum(np.cos(2 * np.pi * t / 61000), -np.sin(2 * np.pi * t / 61000), 600.0, nperseg=128)
    assert r["cw"].size == r["ccw"].size == r["period_h"].size
    assert r["cw"].max() > 10 * r["ccw"].max()                            # giro horario


def test_color_range_constante_y_densidad():
    from schismlab.gui.figures import color_range
    lo, hi, fmt = color_range(np.full(50, 0.3) + 1e-16 * np.arange(50))
    assert lo < 0.3 < hi and hi - lo > 1e-4                               # rango mínimo: no se pinta el ruido de redondeo
    lo, hi, fmt = color_range(np.linspace(1025.53, 1027.56, 30))
    assert fmt in (".1f", ".2f", ".3f") and f"{1025.53:{fmt}}" != f"{1027.56:{fmt}}"


def test_flechas_de_la_variable():
    from schismlab.gui.figures import arrow_field, map_arrows
    ds = cart_ds()
    assert arrow_field(ds, "windStress") == "windStress" and arrow_field(ds, "temperature") == "horizontalVel"
    tr, vmax = map_arrows(ds, 0, -1, var="windStress")
    assert vmax == pytest.approx(1e-4)
    tr, vmax = map_arrows(ds, 0, -1, var="temperature")
    assert vmax == pytest.approx(np.hypot(0.5, 0.2))


def test_ejes_en_metros_en_cartesianas():
    from schismlab.gui.figures import field_figure
    ds = cart_ds()
    f = field_figure(ds.x.values, ds.y.values, ds.attrs["elements"], ds.depth.values, "h")
    assert f.layout.xaxis.title.text == "x (m)" and f.layout.yaxis.title.text == "y (m)"


def test_hovmoller_isosuperficie_sin_cero():
    from schismlab.gui.figures import iso_hovmoller_figure
    ds = cart_ds()
    s = Section(ds, (1.0, 20e3), (99e3, 20e3), npts=20)
    f = iso_hovmoller_figure(s, "temperature", 5.0, "h", "es")            # 5 °C no existe: todo NaN, nunca 0
    z = np.array(f.data[0].z, dtype=float)
    assert np.isnan(z).all() and f.layout.plot_bgcolor == "#9e9e9e"
    assert any("gris" in (a.text or "") for a in f.layout.annotations)
    f = iso_hovmoller_figure(s, "temperature", 15.0, "h", "es")
    assert np.allclose(np.array(f.data[0].z, dtype=float), 37.5)                 # entre los niveles de -50 (10 °C) y -25 m (20 °C)


def test_salto_a_una_fecha():
    from schismlab.gui.explorer import nearest_output
    times = np.datetime64("2020-01-01") + np.arange(10) * np.timedelta64(3, "h")
    assert nearest_output(times, "2020-01-01 07:00") == 2 and nearest_output(times, "2020-01-02") == 8
    assert nearest_output(times, "mañana") is None


def test_coriolis_del_caso():
    from schismlab.analysis.dynamics import case_coriolis, inertial_lat
    cfg = {"physics": {"coriolis": "f-plane"}, "reference": {"lat0": 45.0}}
    f = case_coriolis(cfg, [0, 1], [0, 1e6], geographic=False)
    assert np.allclose(f, 2 * 7.292115e-5 * np.sin(np.deg2rad(45))) and inertial_lat(f[0]) == pytest.approx(45.0)
    fb = case_coriolis({**cfg, "physics": {"coriolis": "beta"}}, [0, 0], [0, 1e6], geographic=False)
    assert fb[1] - fb[0] == pytest.approx(2 * 7.292115e-5 * np.cos(np.deg2rad(45)) * 1e6 / 6371e3)
    assert case_coriolis({"physics": {"coriolis": "none"}}, [0], [0], geographic=False) is None


def test_arista_mas_corta_en_rejilla(tmp_path):
    from schismlab.io.gr3 import write_gr3
    from schismlab.mesh.view import load, stats
    m = rectangular_basin(20e3, 10e3, 2500.0, depth=50.0)
    write_gr3(tmp_path / "hgrid.gr3", m)
    st = stats(load(tmp_path))
    assert st["short_p50"] == pytest.approx(2500.0, rel=1e-3) and st["size_p50"] > 2500.0
