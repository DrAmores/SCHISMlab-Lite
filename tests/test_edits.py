"""Retoques locales de batimetría (mesh.bathymetry_edits)."""
import numpy as np
from schismlab.io.gr3 import Mesh, write_gr3, read_gr3
from schismlab.mesh.edits import apply_edits, edits_cfg, sync_edits, applied_edits


def _mesh(n=11):
    x, y = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    k = lambda i, j: i * n + j
    els = []
    for i in range(n - 1):
        for j in range(n - 1):
            els += [[k(i, j), k(i, j + 1), k(i + 1, j + 1)], [k(i, j), k(i + 1, j + 1), k(i + 1, j)]]
    return Mesh(x.ravel(), y.ravel(), 10.0 + 5 * x.ravel(), els)


BOX = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]


def test_ops():
    m = _mesh(); inside = (m.x > 0.25) & (m.x < 0.75) & (m.y > 0.25) & (m.y < 0.75)
    d0 = m.depth.copy()
    apply_edits(m, edits_cfg({"bathymetry_edits": [{"polygon": BOX, "op": "set", "value": 3}]}))
    assert np.allclose(m.depth[inside], 3) and np.allclose(m.depth[~inside], d0[~inside])
    apply_edits(m, edits_cfg({"bathymetry_edits": [{"polygon": BOX, "op": "min_depth", "value": 8}, {"polygon": BOX, "op": "offset", "value": -1}]}))
    assert np.allclose(m.depth[inside], 7)
    m = _mesh(); m.depth[60] = 100.0                      # pozo espurio en el centro
    apply_edits(m, edits_cfg({"bathymetry_edits": [{"polygon": BOX, "op": "smooth", "iterations": 5}]}))
    assert m.depth[60] < 30


def test_sync_reverts_and_keeps_slr(tmp_path):
    m = _mesh(); write_gr3(tmp_path / "hgrid.gr3", m); d0 = m.depth.copy()
    cfg = {"bathymetry_edits": [{"polygon": BOX, "op": "set", "value": 2}]}
    sync_edits(tmp_path, cfg)
    assert (read_gr3(tmp_path / "hgrid.gr3").depth == 2).any() and applied_edits(tmp_path)
    # escenario de subida del nivel del mar aplicado despues (como hace setup)
    (tmp_path / "slr_applied").write_text("0.5\n"); mm = read_gr3(tmp_path / "hgrid.gr3"); mm.depth += 0.5; write_gr3(tmp_path / "hgrid.gr3", mm)
    sync_edits(tmp_path, {})                              # quitar los retoques: vuelve la batimetria original + 0.5
    assert np.allclose(read_gr3(tmp_path / "hgrid.gr3").depth, d0 + 0.5, atol=1e-6)
    assert applied_edits(tmp_path) == []
