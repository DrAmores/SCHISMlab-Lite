import numpy as np
from schismlab.io import read_gr3, write_gr3
from schismlab.mesh import rectangular_basin


def test_rectangular_basin_roundtrip(tmp_path):
    m = rectangular_basin(10e3, 5e3, 1e3, depth=20.0, open_sides=("E",))
    assert m.nnodes == 11 * 6 and m.nelements == 2 * 10 * 5
    # orientacion antihoraria de todos los elementos
    e = np.array(m.elements)
    a = (m.x[e[:, 1]] - m.x[e[:, 0]]) * (m.y[e[:, 2]] - m.y[e[:, 0]]) - (m.x[e[:, 2]] - m.x[e[:, 0]]) * (m.y[e[:, 1]] - m.y[e[:, 0]])
    assert (a > 0).all()
    assert len(m.open_boundaries) == 1 and len(m.open_boundaries[0]) == 6
    write_gr3(tmp_path / "hgrid.gr3", m)
    m2 = read_gr3(tmp_path / "hgrid.gr3")
    assert m2.nnodes == m.nnodes and m2.nelements == m.nelements
    assert np.allclose(m2.depth, 20.0)
    assert [len(b) for b, _ in m2.land_boundaries] == [len(b) for b, _ in m.land_boundaries]
