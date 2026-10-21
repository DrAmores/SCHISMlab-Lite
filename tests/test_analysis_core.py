"""Núcleo de análisis: secciones (interpolación, velocidad proyectada, presets) y señal (Welch, rotatorio, wavelet)."""
import numpy as np
import pytest
import xarray as xr
from schismlab.mesh import rectangular_basin
from schismlab.analysis.sections import Section, preset_section, principal_axis, field_at_depth
from schismlab.analysis.signal import psd_welch, rotary_spectrum, wavelet_morlet, reference_periods, regularize, resolvable_periods


def synthetic_ds(nvrt=6, nt=4):
    m = rectangular_basin(0, 0, 10e3, depth=100.0, lon=(0, 2), lat=(40, 40.5))
    x, y = m.x, m.y
    t = np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h")
    sig = np.linspace(-1, 0, nvrt)
    z = np.array([-100 * (1 - 0) * 0 + 100 * s for s in sig])                           # (nvrt,) de -100 a 0
    Z = np.broadcast_to(z, (nt, x.size, nvrt)).copy()
    T = 10 + 10 * (Z > -50) + 0.0 * x[None, :, None]                                    # dos capas
    U = np.broadcast_to(0.5 + 0 * x, (nt, x.size))[:, :, None] * np.ones((1, 1, nvrt))  # u = 0.5 este
    V = np.broadcast_to(0.2 + 0 * x, (nt, x.size))[:, :, None] * np.ones((1, 1, nvrt))  # v = 0.2 norte
    ds = xr.Dataset({"elevation": (("time", "node"), np.zeros((nt, x.size))), "temperature": (("time", "node", "layer"), T),
                     "horizontalVelX": (("time", "node", "layer"), U), "horizontalVelY": (("time", "node", "layer"), V),
                     "zCoordinates": (("time", "node", "layer"), Z), "depth": ("node", m.depth)},
                    coords={"time": t, "x": ("node", x), "y": ("node", y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    return ds


def test_section_interpolation_and_velocity():
    ds = synthetic_ds()
    s = Section(ds, (0.1, 40.25), (1.9, 40.25), npts=50)
    assert s.inside.all() and s.dist[-1] == pytest.approx(111.2 * 1.8 * np.cos(np.deg2rad(40.25)), rel=0.01)
    T = s.scalar("temperature", 0)
    assert T.shape == (50, 6) and np.allclose(T[:, -1], 20) and np.allclose(T[:, 0], 10)
    us, un, w = s.velocity(0)
    assert np.allclose(us, 0.5) and np.allclose(un, 0.2) and w is None          # sección hacia el este: u_s = u, u_n = v
    zi, Zg = s.regular(T, s.z(0))
    assert Zg.shape == (80, 50) and np.isfinite(Zg).all()
    hv = s.hovmoller("temperature", -1)
    assert hv.shape == (4, 50) and np.allclose(hv, 20)
    out = Section(ds, (-1, 40.25), (0.5, 40.25), npts=10)
    assert (~out.inside).sum() > 0 and np.isnan(out.scalar("temperature", 0)[0]).all()


def test_presets_and_depth_field():
    ds = synthetic_ds()
    assert abs(principal_axis(ds)) < 0.05                                             # dominio más largo en x
    p0, p1 = preset_section(ds, (1.0, 40.25), "transversal")
    assert abs(p0[0] - p1[0]) < 1e-6 and p0[1] < 40.25 < p1[1]
    p0, p1 = preset_section(ds, (1.0, 40.25), "longitudinal")
    assert abs(p0[1] - p1[1]) < 1e-6 and p0[0] < 1.0 < p1[0]
    f = field_at_depth(ds, "temperature", 0, 30.0)
    assert np.allclose(f, 20) and np.isnan(field_at_depth(ds, "temperature", 0, 150.0)).all()


def test_welch_peak_and_reference():
    dt = 600.0; t = np.arange(0, 10 * 86400, dt)
    y = np.sin(2 * np.pi * t / (12.42 * 3600)) + 0.1 * np.random.default_rng(0).standard_normal(t.size)
    r = psd_welch(y, dt)
    assert r["period_h"][np.argmax(r["P"])] == pytest.approx(12.42, rel=0.1)
    assert (r["lo"] <= r["P"]).all() and (r["hi"] >= r["P"]).all()
    p = reference_periods(40.0)
    assert p["M2"] == pytest.approx(12.42, abs=0.01) and p["inercial"] == pytest.approx(18.6, abs=0.2)
    assert resolvable_periods(dt, t.size) == (1200.0, 10 * 86400 / 4)


def test_rotary_clockwise():
    dt = 600.0; t = np.arange(0, 5 * 86400, dt); T = 18.6 * 3600
    u, v = np.cos(2 * np.pi * t / T), -np.sin(2 * np.pi * t / T)                        # giro horario (inercial, HN)
    r = rotary_spectrum(u, v, dt)
    assert r["cw"].max() > 20 * r["ccw"].max() and r["period_h"][np.argmax(r["cw"])] == pytest.approx(18.6, rel=0.15)


def test_wavelet_two_periods_and_coi():
    dt = 3600.0; n = 512; t = np.arange(n) * dt
    y = np.where(t < t[n // 2], np.sin(2 * np.pi * t / (12 * 3600)), np.sin(2 * np.pi * t / (48 * 3600)))
    w = wavelet_morlet(y, dt)
    ph = w["period"] / 3600
    p1 = ph[np.argmax(w["power"][:, n // 4])]; p2 = ph[np.argmax(w["power"][:, 3 * n // 4])]
    assert p1 == pytest.approx(12, rel=0.15) and p2 == pytest.approx(48, rel=0.15)
    assert w["coi"][0] == 0 and w["coi"][n // 2] == pytest.approx(w["coi"].max())
    sig_ratio = w["power"] / w["signif"][:, None]
    assert sig_ratio[np.argmin(abs(ph - 12)), n // 4] > 1 and sig_ratio[np.argmin(abs(ph - 48)), n // 4] < 1
    tu, yu, d = regularize(np.datetime64("2020-01-01") + (t * 1e9).astype("timedelta64[ns]"), y)
    assert d == 3600 and yu.size == n


def test_figures_build():
    from schismlab.gui.figures import arrows_trace, map_arrows, section_figure2, hovmoller_figure, psd_figure, rotary_figure, wavelet_figure
    ds = synthetic_ds()
    tr = arrows_trace([0, 1], [0, 0], [1, 0], [0, 1])
    assert len(tr.x) == 12 and np.isnan(tr.x[5])
    tr, vmax = map_arrows(ds, 0, -1)
    assert vmax == pytest.approx(np.hypot(0.5, 0.2)) and len(tr.x) > 0
    s = Section(ds, (0.1, 40.25), (1.9, 40.25), npts=40)
    f = section_figure2(s, "temperature", 0); assert len(f.data) == 5
    assert len(hovmoller_figure(s, "temperature").data) == 1
    dt = 3600.0; t = np.arange(400) * dt; y = np.sin(2 * np.pi * t / (12.42 * 3600))
    assert len(psd_figure(psd_welch(y, dt), reference_periods(40)).data) == 3
    assert len(rotary_figure(rotary_spectrum(y, y, dt)).data) == 2
    assert len(wavelet_figure(wavelet_morlet(y, dt), np.datetime64("2020-01-01")).data) == 5


def test_interp_at_depth_vectorized():
    from schismlab.analysis.sections import interp_at_depth
    z = np.array([[-100, -50, -10, 0.0], [-20, -10, -5, 0.0], [np.nan, -30, -10, 0.0]])
    v = np.array([[1, 2, 3, 4.0], [1, 2, 3, 4.0], [np.nan, 1, 2, 3.0]])
    out = interp_at_depth(v, z, 30.0)
    assert out[0] == pytest.approx(2.5) and np.isnan(out[1]) and out[2] == pytest.approx(1.0)
    assert interp_at_depth(v, z, 0.0)[0] == 4.0 and interp_at_depth(v, z, 100.0)[0] == 1.0
