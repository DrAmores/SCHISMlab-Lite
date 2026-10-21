import numpy as np
from schismlab.mesh import rectangular_basin, assign_boundaries, hull_rings, mesh_quality


def test_hull_rings_and_bbox_open():
    m = rectangular_basin(10e3, 5e3, 1e3, depth=20.0)
    rings = hull_rings(m)
    assert len(rings) == 1 and rings[0].size == 2 * (11 + 6) - 4
    assign_boundaries(m, open_where="bbox")
    assert len(m.open_boundaries) == 2 and len(m.land_boundaries) == 0   # anillo entero abierto: dos mitades
    assign_boundaries(m, open_where=lambda x, y: x > 9.9e3)   # solo el lado este
    assert len(m.open_boundaries) == 1 and len(m.open_boundaries[0]) == 7   # 6 nodos + el de union con tierra
    assert len(m.land_boundaries) == 1
    # el contorno de tierra cierra el anillo: empieza y acaba en los nodos extremos del abierto
    land = m.land_boundaries[0][0]
    assert land[0] == m.open_boundaries[0][-1] and land[-1] == m.open_boundaries[0][0]


def test_quality_regular():
    m = rectangular_basin(10e3, 5e3, 1e3, depth=20.0)
    q = mesh_quality(m)
    assert abs(q["min_angle_deg"] - 45) < 1e-6 and q["elements_angle_lt_20"] == 0
    assert abs(q["edge_min_m"] - 1000) < 1e-6


def test_geographic_basin():
    m = rectangular_basin(0, 0, 10e3, depth=100.0, lon=(2.0, 3.0), lat=(39.0, 39.5), open_sides=("N",))
    assert m.x.min() == 2.0 and m.y.max() == 39.5 and len(m.open_boundaries) == 1
    q = mesh_quality(m)
    assert 8e3 < q["edge_min_m"] < 12e3


def test_fully_open_ring_is_split():
    """Un anillo exterior totalmente abierto se parte en dos contornos (SCHISM rechaza un contorno abierto cerrado)."""
    from schismlab.mesh.idealized import rectangular_basin
    from schismlab.mesh.boundaries import assign_boundaries
    m = rectangular_basin(10e3, 10e3, 1e3, depth=100.0)
    assign_boundaries(m, "bbox")
    assert len(m.open_boundaries) == 2
    assert m.open_boundaries[0][-1] == m.open_boundaries[1][0] and m.open_boundaries[1][-1] == m.open_boundaries[0][0]


def test_edge_types_split_and_walls():
    from shapely.geometry import Polygon
    from schismlab.mesh.idealized import rectangular_basin
    from schismlab.mesh.boundaries import assign_edge_types
    m = rectangular_basin(0, 0, 500.0, lon=(0.0, 0.1), lat=(40.0, 40.1))
    pg = Polygon([(0.0, 40.0), (0.1, 40.0), (0.1, 40.1), (0.0, 40.1)])     # lados: 0 S, 1 E, 2 N, 3 W
    kinds = assign_edge_types(m, pg, ["radiation", "wall", "radiation", "forced"], tol=0.002)
    assert sorted(kinds) == ["forced", "radiation", "radiation"]
    import numpy as np
    for b, k in zip(m.open_boundaries, kinds):
        xs, ys = m.x[b], m.y[b]
        assert not np.any(np.isclose(xs, 0.1) & (ys > 40.005) & (ys < 40.095))    # el lado este (pared) no es abierto
        if k == "forced":
            assert np.allclose(xs, 0.0)


def test_tsunami_series_and_flather_bctides(tmp_path):
    from schismlab.setup import tsunami_series
    s = tsunami_series({"height": 1.5, "period_min": 10, "arrival_h": 0.5}, 0.1)
    import numpy as np
    a = np.asarray(s); assert abs(a[:, 1].max() - 1.5) < 0.01 and abs(a[np.argmax(a[:, 1]), 0] - 0.5) < 0.01
    from schismlab.mesh.idealized import rectangular_basin
    from schismlab.forcing.bctides import write_bctides
    m = rectangular_basin(0, 0, 500.0, lon=(0.0, 0.05), lat=(40.0, 40.05), open_sides=("W", "E"))
    write_bctides(tmp_path / "bctides.in", m, [dict(elev="th1"), dict(elev="none", vel="flather", nvrt=2)])
    txt = (tmp_path / "bctides.in").read_text()
    assert " 1 0 0 0" in txt and " 0 -1 0 0" in txt and "eta_mean" in txt and "vn_mean" in txt


def test_tsunami_train():
    import numpy as np
    from schismlab.setup import tsunami_series
    a = np.asarray(tsunami_series({"shape": "n_wave", "height": 3.0, "period_min": 20, "arrival_h": 0.25, "waves": 3}, 0.2))
    pk = np.where(np.diff(np.sign(np.diff(a[:, 1]))) < 0)[0] + 1; crests = int((a[pk, 1] > 1.0).sum())
    assert crests == 3 and abs(a[:, 1].max() - 3.0) < 0.05 and abs(a[:, 1].min() + 3.0) < 0.05
    assert abs(a[a[:, 1] != 0, 0].max() - (0.25 + 1.0)) < 0.02               # el tren dura 3 periodos (1 h)
