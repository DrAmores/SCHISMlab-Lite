import numpy as np
from schismlab.forcing import VGrid, write_bctides, write_hotstart
from schismlab.forcing.hotstart import side_table
from schismlab.mesh import rectangular_basin, assign_boundaries


def test_vgrid_zcor_monotonic():
    vg = VGrid.sz(nsigma=10, zlevels=[-1000, -500, -200, -100], h_c=10, theta_f=4)
    assert vg.nvrt == 13 and vg.kz == 4 and vg.h_s == 100
    z = vg.zcor(np.array([20.0, 150.0, 2000.0]))
    assert np.all(np.diff(z, axis=1) >= 0)                 # de fondo a superficie
    assert np.allclose(z[:, -1], 0.0)                      # superficie en eta=0
    assert np.isclose(z[2, 0], -1000) and np.isclose(z[1, 3], -100)
    assert np.isclose(z[0, 3], -20)                        # nodo somero: sigma -1 en el fondo


def test_vgrid_2d_and_sigma():
    assert VGrid.two_d().nvrt == 2
    vg = VGrid.sigma(nvrt=5, h_c=5, theta_f=1e-4)
    z = vg.zcor(np.array([50.0]))
    assert np.allclose(z[0], np.linspace(-50, 0, 5))        # theta_f ~ 0 -> sigma lineal


def test_side_table_counts():
    m = rectangular_basin(4e3, 3e3, 1e3)
    s = side_table(m)
    # Euler: ns = ne + np - 1 para un dominio simplemente conexo
    assert len(s) == m.nelements + m.nnodes - 1
    assert len({tuple(sorted(x)) for x in s.tolist()}) == len(s)


def test_hotstart_and_bctides(tmp_path):
    m = rectangular_basin(4e3, 3e3, 1e3, depth=50.0, open_sides=("E",))
    vg = VGrid.sigma(nvrt=6)
    f = write_hotstart(tmp_path / "hotstart.nc", m, vg, temp=lambda x, y, z: 20 + z / 10, salt=36.0, eta=0.1)
    import xarray as xr
    ds = xr.open_dataset(f)
    assert ds.tr_nd.shape == (m.nnodes, 6, 2) and np.isclose(float(ds.eta2.mean()), 0.1)
    assert float(ds.tr_nd[:, -1, 0].mean()) > float(ds.tr_nd[:, 0, 0].mean())   # mas caliente arriba
    write_bctides(tmp_path / "bctides.in", m, [dict(elev={"tides": {"M2": (0.5, 0.0)}}, temp="ic", salt=36)],
                  constituents=["M2"])
    txt = (tmp_path / "bctides.in").read_text().splitlines()
    assert txt[2].startswith("1 !nbfr") and txt[6].startswith("4 3 0 3 2")
