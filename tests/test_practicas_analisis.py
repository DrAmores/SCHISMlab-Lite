"""Bloque 2 de las prácticas con Lite (núcleo): variables derivadas, promedio temporal, lecturas de la espiral de Ekman
y ajustes/integrales a lo largo de una sección."""
import numpy as np
import pytest
import xarray as xr
from schismlab.mesh import rectangular_basin
from schismlab.analysis.derived import Fields, time_window, describe_window
from schismlab.analysis.profiles import ekman_readouts, angle_right, line_fit, line_integral, zero_crossings, theoretical_spiral


def solid_body_ds(nt=4, omega=1e-5, Lx=100e3, dx=5e3):
    """Rotación de sólido rígido (ζ = 2ω) en 2D (depthAverageVel) con η variable en el tiempo."""
    m = rectangular_basin(Lx, Lx, dx, depth=100.0)
    x, y = m.x - Lx / 2, m.y - Lx / 2
    t = np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h")
    amp = np.arange(1, nt + 1)[:, None]                                    # el giro crece con el tiempo
    ds = xr.Dataset({"elevation": (("time", "node"), np.zeros((nt, x.size))),
                     "depthAverageVelX": (("time", "node"), -omega * y[None, :] * amp), "depthAverageVelY": (("time", "node"), omega * x[None, :] * amp),
                     "depth": ("node", m.depth)}, coords={"time": t, "x": ("node", m.x), "y": ("node", m.y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    return ds


def test_derivadas_vorticidad_y_promedio():
    ds = solid_body_ds()
    f = np.full(ds.sizes["node"], 1e-4)
    F = Fields(ds, f=f)
    assert set(F.available) == {"vorticity", "vorticity_f", "transport", "streamfunction"}
    assert not F.is3d("vorticity") and F.is_vector("transport") and not F.is_vector("vorticity")
    z = F.nodal("vorticity", [0]); inner = (np.abs(ds.x - 50e3) < 30e3) & (np.abs(ds.y - 50e3) < 30e3)
    assert np.allclose(z[inner.values], 2e-5, rtol=1e-6)
    zf = F.nodal("vorticity_f", [0, 1, 2, 3])                                # promedio: 2ω·(1+2+3+4)/4 / f
    assert np.allclose(zf[inner.values], 2e-5 * 2.5 / 1e-4, rtol=1e-6)
    U = F.nodal("transport", [1], comp="u")                                 # U = u·(h + η)
    assert np.allclose(U, ds.depthAverageVelX.isel(time=1).values * 100.0)
    mag = F.nodal("transport", [0, 1], comp="mag")                          # módulo de la media
    assert np.allclose(mag, np.hypot(ds.depthAverageVelX.isel(time=[0, 1]).mean("time"), ds.depthAverageVelY.isel(time=[0, 1]).mean("time")) * 100)
    psi = F.nodal("streamfunction", [0])                                    # giro antihorario: ψ mínimo en el centro (Sv)
    c = int(np.argmin(np.hypot(ds.x - 50e3, ds.y - 50e3).values))
    assert psi[c] < 0 and abs(psi[c]) > 0.5 * np.nanmax(np.abs(psi))
    s = F.series("vorticity", c)
    assert s["y"].shape == (4,) and np.allclose(s["y"], 2e-5 * np.arange(1, 5), rtol=1e-6)


def test_sin_rotacion_no_hay_zeta_f():
    F = Fields(solid_body_ds(), f=None)
    assert "vorticity_f" not in F.available and "vorticity" in F.available


def test_ventana_temporal():
    times = np.datetime64("2020-01-01T01") + np.arange(72) * np.timedelta64(1, "h")
    its = time_window(times, "2020-01-03 08:00", "2020-01-04 00:00")         # 56–72 h desde el inicio: 17 salidas
    assert its.size == 17
    assert "17 salidas" in describe_window(times, its) and time_window(times, "2021-01-01", "2021-01-02").size == 0


def test_espiral_de_ekman_teorica_recuperada():
    """Perfil con la espiral exacta (De = 14 m, V0 = 0.2 m/s) sobre una corriente de fondo: las lecturas la recuperan."""
    De, V0, f = 14.0, 0.2, 1.03e-4
    z = np.linspace(-200, 0, 101)
    zz, uE, vE = theoretical_spiral(V0, De, f, wind_dir=(1.0, 0.0), zmin=-200, n=101)
    u, v = uE + 0.01, vE - 0.003                                           # corriente de retorno uniforme
    r = ekman_readouts(z, u, v, wind=(1.0, 0.0), ref=(0.01, -0.003), fit=(-28, 0), f=f)
    assert r["surface"] == pytest.approx(V0, rel=1e-6) and r["surface_angle"] == pytest.approx(45.0, abs=1e-6)
    assert r["z_reverse"] == pytest.approx(-np.pi * De, rel=0.02)
    assert r["De"] == pytest.approx(De, rel=1e-6) and r["Az"] == pytest.approx(f * De ** 2 / 2, rel=1e-6)
    # transporte de Ekman: |T| = V0·De/√2, a 90° a la derecha del viento
    assert np.hypot(r["Tx"], r["Ty"]) == pytest.approx(V0 * De / np.sqrt(2), rel=0.02) and r["T_angle"] == pytest.approx(90.0, abs=1.0)


def test_angulos():
    assert angle_right(1, -1, 1, 0) == pytest.approx(45.0) and angle_right(1, 1, 1, 0) == pytest.approx(-45.0)
    assert angle_right(0, -1, 0, 1) == pytest.approx(180.0) or angle_right(0, -1, 0, 1) == pytest.approx(-180.0)


def test_ajuste_e_integral_en_seccion():
    d = np.linspace(0, 1000, 501)                                           # km
    y = 0.5 * np.exp(-d / 120.0) - 0.01
    r = line_fit(d, y, 0, 300, log=True, ref=-0.01)
    assert r["scale_km"] == pytest.approx(-120.0, rel=1e-3) and r["n"] > 100
    lin = line_fit(d, 2 * d * 1e3 + 3, 100, 200)
    assert lin["alpha"] == pytest.approx(2.0) and lin["intercept"] == pytest.approx(3.0)
    I = line_integral(d, np.ones_like(d), 100, 350)
    assert I == pytest.approx(250e3)
    zc = zero_crossings(d, y)
    assert len(zc) == 1 and zc[0] == pytest.approx(120 * np.log(50), rel=1e-3)


def test_malla_grande_sin_campos_completos(monkeypatch):
    """Mallas grandes (Pro): sin campos de todos los instantes en memoria y sin ψ; los resultados no cambian."""
    ds = solid_body_ds()
    F = Fields(ds, f=np.full(ds.sizes["node"], 1e-4))
    ref_T = F.nodal("transport", [1, 2], comp="u"); ref_z = F.series("vorticity", 5)["y"]
    G = Fields(ds, f=np.full(ds.sizes["node"], 1e-4)); G.all_ok = False; G.transport_all_ok = False
    assert np.allclose(G.nodal("transport", [1, 2], comp="u"), ref_T) and np.allclose(G.series("vorticity", 5)["y"], ref_z)
    assert "T_all" not in G._cache and not any(isinstance(k, tuple) and k[0] == "all" for k in G._cache)
    import schismlab.analysis.derived as D
    big = ds.assign_coords()                                              # sin ψ por encima de 200 000 nodos
    monkeypatch.setattr(D.xr.Dataset, "sizes", property(lambda self: {**dict(self.dims), "node": 300_000}))
    assert "streamfunction" not in Fields(big, f=None).available
