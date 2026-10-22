"""Esfuerzo del viento <-> viento (fórmulas de SCHISM), fondo por fórmula y diagnósticos (vorticidad, transporte, psi)."""
import numpy as np
import pytest
import xarray as xr
import yaml
from schismlab.mesh import rectangular_basin
from schismlab.forcing.windstress import stress_from_wind, wind_from_stress, drag_coefficient, kinematic_stress
from schismlab.mesh.analytic import analytic_depth
from schismlab.analysis import dynamics as dyn


# --- esfuerzo del viento ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("formula", [1, -1])
def test_stress_roundtrip(formula):
    u = np.array([0.0, 1.0, 5.0, 12.0, -20.0, 40.0]); v = np.array([0.0, -3.0, 0.0, 8.0, 15.0, 0.5])
    tx, ty = stress_from_wind(u, v, formula)
    uu, vv = wind_from_stress(tx, ty, formula)
    assert np.allclose(uu, u, atol=1e-5) and np.allclose(vv, v, atol=1e-5)
    # monótono creciente y valores conocidos: Hwang Cd(10) = 1e-4*(-1.6+9.67+8.058)
    w = np.linspace(0, 100, 1001)
    assert np.all(np.diff(kinematic_stress(w, formula)) > 0)
    if formula == 1:
        assert np.isclose(drag_coefficient(10.0, 1), 1.6128e-3)
    else:
        assert np.isclose(drag_coefficient(2.0, -1), drag_coefficient(6.0, -1))   # acotado por debajo de 6 m/s
    # tau = Cd * rho_a * |W| W con rho_a = 1.293 kg/m3 (la constante 0.001293 de SCHISM)
    tx1, _ = stress_from_wind(10.0, 0.0, formula)
    assert np.isclose(tx1, drag_coefficient(10.0, formula) * 1.293 * 100)


def test_stress_not_invertible_formula():
    with pytest.raises(ValueError):
        wind_from_stress(0.1, 0.0, 0)


def test_setup_wind_as_stress(tmp_path):
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    cfg = {"name": "tau", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50, "open_sides": []},
           "vertical": {"type": "2d"}, "time": {"start": "2020-01-01", "days": 1, "dt": 60, "ramp_days": 0},
           "physics": {"baroclinic": False}, "initial": {"elevation": 0, "temperature": 20, "salinity": 36},
           "forcing": {"wind": {"stress": {"x": 0.1, "y": 0.0}, "formula": -1}},
           "output": {"interval_minutes": 30, "variables": ["elevation"]}}
    p = tmp_path / "tau.yaml"; p.write_text(yaml.safe_dump(cfg))
    rs = RunSetup(Case(p)); rs.build()
    w = np.loadtxt(rs.dir / "wind.th")
    assert rs.param["nws"] == 1 and rs.param["iwind_form"] == -1 and rs.param["drampwind"] == 0
    assert rs.param["iof_hydro(15)"] == 1                                 # windStress se añade sola a las salidas
    tx, ty = stress_from_wind(w[:, 1], w[:, 2], -1)
    assert np.allclose(tx, 0.1, atol=1e-3) and np.allclose(ty, 0.0)      # wind.th se escribe con 3 decimales
    cfg["forcing"]["wind"]["formula"] = 0; p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):
        RunSetup(Case(p)).build()


# --- fondo por fórmula ------------------------------------------------------------------------------------------------
def test_expression_bathymetry_matches_seamount():
    x, y = np.meshgrid(np.linspace(0, 300e3, 31), np.linspace(0, 120e3, 13))
    ref = analytic_depth("seamount", h=1000, A=800, x0=150e3, y0=60e3, r=20e3)(x, y)
    f = analytic_depth("expression", formula="1000 - 800*exp(-((x-150e3)**2 + (y-60e3)**2)/(2*20e3**2))")
    assert np.allclose(f(x, y), ref)
    with pytest.raises(ValueError):
        analytic_depth("expression", formula="lon*0 + 100")(x, y)          # cartesiano: lon no existe
    with pytest.raises(ValueError):
        analytic_depth("expression", formula="__import__('os')")
    with pytest.raises(ValueError):
        analytic_depth("expression", formula="log(x - 150e3)")(x, y)      # no finito


def test_expression_bathymetry_geographic():
    from schismlab.mesh.build import _depth_callable
    cfg = {"lon": [0, 1], "lat": [40, 40.5]}
    m = rectangular_basin(0, 0, 10e3, depth=_depth_callable({"kind": "expression", "formula": "50 + x/1e3 + 0*lat"}, cfg), lon=(0, 1), lat=(40, 40.5))
    xm = np.deg2rad(m.x) * 6371e3 * np.cos(np.deg2rad(40.25))
    assert np.allclose(m.depth, 50 + xm / 1e3) and m.depth.max() > 130


# --- diagnósticos -----------------------------------------------------------------------------------------------------
def _ds(u, v, lonlat=False):
    if lonlat:
        m = rectangular_basin(0, 0, 5e3, depth=100.0, lon=(0, 1), lat=(40, 40.5))
    else:
        m = rectangular_basin(100e3, 60e3, 4e3, depth=100.0)
    x, y = m.x, m.y
    ds = xr.Dataset({"depthAverageVelX": (("time", "node"), u(x, y)[None]), "depthAverageVelY": (("time", "node"), v(x, y)[None]),
                     "elevation": (("time", "node"), np.zeros((1, x.size))), "depth": ("node", m.depth)},
                    coords={"time": [np.datetime64("2020-01-01")], "x": ("node", x), "y": ("node", y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    return ds, m


def test_vorticity_solid_body_and_uniform():
    om = 1e-4
    ds, m = _ds(lambda x, y: -om * (y - 30e3), lambda x, y: om * (x - 50e3))
    z = dyn.vorticity(ds)
    assert z.dims == ("time", "node") and np.allclose(z.values, 2 * om, rtol=1e-6)
    assert np.allclose(dyn.divergence(ds).values, 0.0, atol=1e-12)
    ds2, _ = _ds(lambda x, y: 0.3 + 0 * x, lambda x, y: -0.1 + 0 * x)
    assert np.allclose(dyn.vorticity(ds2).values, 0.0, atol=1e-15)
    gx, gy = dyn.gradient(ds2, 2.0 * ds2.x + 3.0 * ds2.y)
    assert np.allclose(gx, 2.0) and np.allclose(gy, 3.0)


def test_gradient_geographic_in_metres():
    ds, m = _ds(lambda x, y: 0 * x, lambda x, y: 0 * x, lonlat=True)
    gx, gy = dyn.gradient(ds, ds.x)                         # d(lon)/dx en 1/m
    assert np.allclose(gx, 1 / (np.deg2rad(1) * 6371e3 * np.cos(np.deg2rad(40.25))), rtol=1e-6)
    assert np.allclose(dyn.coriolis(ds).values, 2 * 7.292115e-5 * np.sin(np.deg2rad(ds.y.values)))


def test_transport_2d_and_3d():
    ds, m = _ds(lambda x, y: 0.5 + 0 * x, lambda x, y: 0 * x)
    U, V = dyn.transport(ds)
    assert np.allclose(U, 50.0) and np.allclose(V, 0.0) and U.attrs["units"] == "m2/s"
    nv = 5; z = np.linspace(-100, 0, nv)
    ds3 = ds.assign(horizontalVelX=(("time", "node", "layer"), np.broadcast_to(z / 100.0, (1, m.nnodes, nv)).copy()),
                    horizontalVelY=(("time", "node", "layer"), np.zeros((1, m.nnodes, nv))),
                    zCoordinates=(("time", "node", "layer"), np.broadcast_to(z, (1, m.nnodes, nv)).copy()))
    U3, V3 = dyn.transport(ds3)                                 # u = z/100 de -1 (fondo) a 0: integral = -50
    assert np.allclose(U3, -50.0) and U3.dims == ("time", "node")
    from schismlab.forcing import VGrid
    U4, _ = dyn.transport(ds3.drop_vars("zCoordinates"), vg=VGrid.sigma(nv, h_c=5, theta_f=1e-4))
    assert np.allclose(U4, -50.0, rtol=1e-6)


def test_streamfunction_closed_gyre():
    # psi = A sin(pi x/L) sin(pi y/W): U = -dpsi/dy, V = dpsi/dx, psi = 0 en el borde
    L, W, A = 100e3, 60e3, 1e4
    ds, m = _ds(lambda x, y: -A * np.pi / W * np.sin(np.pi * x / L) * np.cos(np.pi * y / W),
                lambda x, y: A * np.pi / L * np.cos(np.pi * x / L) * np.sin(np.pi * y / W))
    psi = dyn.streamfunction(ds, ds.depthAverageVelX, ds.depthAverageVelY)
    ref = A * np.sin(np.pi * ds.x.values / L) * np.sin(np.pi * ds.y.values / W)
    assert psi.dims == ("time", "node")
    assert np.abs(psi.values[0] - ref).max() < 0.02 * A
    assert np.allclose(psi.values[0][dyn.boundary_nodes(ds)], 0.0)
    gx, gy = dyn.gradient(ds, psi)                             # U = -dpsi/dy, V = dpsi/dx en los nodos interiores
    inner = np.setdiff1d(np.arange(m.nnodes), dyn.boundary_nodes(ds))
    umax = np.abs(ds.depthAverageVelX.values).max()
    assert np.abs(-gy.values[0][inner] - ds.depthAverageVelX.values[0][inner]).max() < 0.05 * umax
    assert np.abs(gx.values[0][inner] - ds.depthAverageVelY.values[0][inner]).max() < 0.05 * umax


def test_streamfunction_warns_open(caplog):
    ds, m = _ds(lambda x, y: 0.5 + 0 * x, lambda x, y: 0 * x)
    import logging
    with caplog.at_level(logging.WARNING, logger="schismlab.analysis.dynamics"):
        dyn.streamfunction(ds, ds.depthAverageVelX, ds.depthAverageVelY)
    assert any("abierto" in r.message for r in caplog.records)


# --- isosuperficies ---------------------------------------------------------------------------------------------------
def test_iso_depth_columns_and_dataset():
    from schismlab.analysis.isosurface import iso_depth_columns, isosurface_depth, isosurface_series, sigma_t, add_density
    z = np.array([[-100, -75, -50, -25, 0.0]] * 3)
    v = np.array([[10, 10, 15, 20, 20.0],            # cruza 17.5 entre -50 (15) y -25 (20) -> 37.5 m
                  [10, 10, 10, 10, 10.0],            # nunca
                  [10, 20, 10, 20, 20.0]])           # tres cruces de 17.5: el más somero entre -50 y -25 -> 31.25 m
    d = iso_depth_columns(v, z, 17.5)
    assert np.isclose(d[0], 37.5) and np.isnan(d[1]) and np.isclose(d[2], 31.25)
    assert np.isclose(iso_depth_columns(v, z, 17.5, which="deepest")[2], 81.25)
    assert np.isclose(iso_depth_columns(v, z, 15.0, which="deepest")[2], 87.5)
    m = rectangular_basin(40e3, 20e3, 4e3, depth=100.0)
    nt, nv = 3, 6; zz = np.linspace(-100, 0, nv)
    Z = np.broadcast_to(zz, (nt, m.nnodes, nv)).copy()
    T = 15 + 0.2 * (Z + 50 - 10 * np.arange(nt)[:, None, None])         # T = 15 en z = -50 + 10 t: la isoterma sube 10 m por instante
    S = 36 + 0 * T
    ds = xr.Dataset({"temperature": (("time", "node", "layer"), T), "salinity": (("time", "node", "layer"), S), "zCoordinates": (("time", "node", "layer"), Z),
                     "elevation": (("time", "node"), np.zeros((nt, m.nnodes))), "depth": ("node", m.depth)},
                    coords={"time": np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h"), "x": ("node", m.x), "y": ("node", m.y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    h = isosurface_depth(ds, "temperature", 15.0, it=0)
    assert h.dims == ("node",) and np.allclose(h, 50.0)
    ht = isosurface_depth(ds, "temperature", 15.0)
    assert ht.dims == ("time", "node") and np.allclose(ht.isel(node=0), [50, 40, 30])
    assert np.allclose(isosurface_series(ds, "temperature", 15.0, node=3), [50, 40, 30])
    assert np.isnan(isosurface_depth(ds, "temperature", 40.0, it=0)).all()
    # sin zCoordinates: con la malla vertical
    from schismlab.forcing import VGrid
    assert np.allclose(isosurface_series(ds.drop_vars("zCoordinates"), "temperature", 15.0, node=3, vg=VGrid.sigma(nv, h_c=5, theta_f=1e-4)), [50, 40, 30], atol=1e-6)
    # sección: h(x) y h(x, t)
    from schismlab.analysis.sections import Section
    sec = Section(ds, (2e3, 10e3), (38e3, 10e3), npts=20)
    assert np.allclose(sec.iso_depth("temperature", 15.0, 1), 40.0) and sec.iso_hovmoller("temperature", 15.0).shape == (nt, 20)
    # densidad: UNESCO rho(35, 5, 0) = 1027.6755 kg/m3; add_density es perezosa y entra en el explorador
    assert np.isclose(sigma_t(5.0, 35.0), 27.6755, atol=2e-4) and np.isclose(sigma_t(25.0, 35.0), 23.3432, atol=2e-4)
    add_density(ds)
    assert "density" in ds and np.isclose(float(ds.density.isel(time=0, node=0, layer=-1)), sigma_t(25.0, 36.0))
    with pytest.raises(ValueError):
        isosurface_depth(ds, "elevation", 0.0, it=0)


def test_explorer_iso_mode():
    pytest.importorskip("nicegui")
    from schismlab.gui.explorer import ExplorerState, map_figure, series_figure_multi
    from schismlab.gui.figures import section_figure2, iso_hovmoller_figure
    from schismlab.gui.i18n import TEXT
    m = rectangular_basin(40e3, 20e3, 4e3, depth=100.0)
    nt, nv = 3, 6; zz = np.linspace(-100, 0, nv)
    Z = np.broadcast_to(zz, (nt, m.nnodes, nv)).copy(); T = 15 + 0.2 * (Z + 50 - 10 * np.arange(nt)[:, None, None])
    ds = xr.Dataset({"temperature": (("time", "node", "layer"), T), "salinity": (("time", "node", "layer"), 36 + 0 * T), "zCoordinates": (("time", "node", "layer"), Z),
                     "elevation": (("time", "node"), np.zeros((nt, m.nnodes))), "depth": ("node", m.depth)},
                    coords={"time": np.datetime64("2020-01-01") + np.arange(nt) * np.timedelta64(1, "h"), "x": ("node", m.x), "y": ("node", m.y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    st = ExplorerState(ds, None)
    assert "density" in st.vars                                        # σt derivada aparece como variable
    st.var = "temperature"; st.depth_mode = "iso"; st.iso_value = 15.0; st.it = 1
    assert st.iso_ok() and np.allclose(st.field("temperature", 1), 40.0)
    st.zr = st.iso_range(); assert st.zr == pytest.approx((30.0, 50.0), abs=0.5)
    d = map_figure(st, TEXT["es"], "es"); assert "15" in str(d["layout"]["title"]) and d["data"][0]["type"] == "heatmap"
    st.add_point(20e3, 10e3)
    f = series_figure_multi(st, "temperature", "es"); assert np.allclose(f.data[0].y, [50, 40, 30]) and f.layout.yaxis.autorange == "reversed"
    # marcador del instante del mapa en la serie, y su desplazamiento con el tiempo
    from schismlab.gui.explorer import series_cursor
    assert f.data[1].mode == "markers" and f.data[1].y[0] == pytest.approx(40.0) and len(f.layout.shapes) == 1
    st.it = 2; xs, ys, tc = series_cursor(st)
    assert ys == [pytest.approx(30.0)] and xs[0].startswith("2020-01-01T02:00") and tc.startswith("2020-01-01T02:00")
    st.it = 1
    s = st.add_section((2e3, 10e3), (38e3, 10e3))
    fig = section_figure2(s["sec"], "temperature", 1, arrows=False, iso=("temperature", 15.0))
    assert np.allclose(fig.data[-1].y, -40.0)                          # línea de la isoterma en la sección
    assert iso_hovmoller_figure(s["sec"], "temperature", 15.0, "h").data[0].z.shape[0] == nt
    st.depth_mode = "layer"; assert not st.iso_ok()


def test_explorer_series_velocity_components():
    """Práctica 1 (oscilaciones inerciales): las series muestran u y v por separado (no solo el módulo) para ver el giro."""
    pytest.importorskip("nicegui")
    from schismlab.gui.explorer import ExplorerState, series_figure_multi, series_cursor
    m = rectangular_basin(40e3, 20e3, 4e3, depth=100.0)
    nt = 9; tt = np.arange(nt) * np.timedelta64(1, "h"); ph = 2 * np.pi * np.arange(nt) / 8
    U = np.broadcast_to(np.cos(ph)[:, None], (nt, m.nnodes)).copy(); V = np.broadcast_to(-np.sin(ph)[:, None], (nt, m.nnodes)).copy()
    ds = xr.Dataset({"depthAverageVelX": (("time", "node"), U), "depthAverageVelY": (("time", "node"), V),
                     "elevation": (("time", "node"), np.zeros((nt, m.nnodes))), "depth": ("node", m.depth)},
                    coords={"time": np.datetime64("2020-01-01") + tt, "x": ("node", m.x), "y": ("node", m.y)})
    ds.attrs["elements"] = np.asarray(m.elements)[:, :3]
    st = ExplorerState(ds, None); st.var = "depthAverageVel"; st.add_point(20e3, 10e3); st.it = 2
    f = series_figure_multi(st, "depthAverageVel", "es")
    lines = [d for d in f.data if d.mode == "lines"]
    assert [d.name.split()[-1] for d in lines] == ["u", "v"]
    assert lines[0].y[0] == pytest.approx(1.0) and lines[1].y[2] == pytest.approx(-1.0)     # gira a la derecha: v < 0
    assert f.layout.shapes[0].x0.startswith("2020-01-01T02:00")                               # la forma 0 es la línea del instante
    st.component = "mag"
    g = series_figure_multi(st, "depthAverageVel", "es")
    assert [d.name.split()[-1] for d in g.data if d.mode == "lines"] == ["|u|"] and np.allclose(g.data[0].y, 1.0)
    assert series_cursor(st)[1] == [pytest.approx(1.0)]


def test_spectrum_axes_fit_the_data():
    """Espectro, rotatorio y wavelet: los ejes log se ajustan a los periodos de los datos y las etiquetas de las líneas
    de referencia van en log10 (antes la de M2 acababa en 10^12 h y el eje llegaba a 10^24)."""
    pytest.importorskip("plotly")
    from schismlab.analysis.signal import psd_welch, rotary_spectrum, wavelet_morlet
    from schismlab.gui.figures import psd_figure, rotary_figure, wavelet_figure
    dt = 1800.0; tt = np.arange(0, 6 * 86400, dt)
    u = np.cos(2 * np.pi * tt / (12.42 * 3600)) + 0.1 * np.random.default_rng(0).normal(size=tt.size); v = np.sin(2 * np.pi * tt / (17 * 3600))
    refs = {"M2": 12.42, "K1": 23.93, "inercial": 17.0, "O1": 25.82, "lejos": 1e6}
    r = psd_welch(u, dt, nperseg=128)
    f = psd_figure(r, refs, "x")
    lo, hi = f.layout.xaxis.range
    assert 10 ** lo >= r["period_h"].min() * 0.5 and 10 ** hi <= r["period_h"].max() * 2
    ann = {a.text: a.x for a in f.layout.annotations}
    assert ann["M2"] == pytest.approx(np.log10(12.42)) and "lejos" not in ann
    g = rotary_figure(rotary_spectrum(u, v, dt, nperseg=128), refs)
    assert 10 ** g.layout.xaxis.range[1] <= r["period_h"].max() * 2
    w = wavelet_morlet(u, dt)
    h = wavelet_figure(w, None, refs)
    yl, yh = h.layout.yaxis.range
    assert 10 ** yh <= (w["period"] / 3600).max() * 1.01 and all(abs(a.y) < 3 for a in h.layout.annotations)
