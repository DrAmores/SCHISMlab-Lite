"""Visor de mallas, estimacion de tiempo e importacion de mallas ya hechas."""
from pathlib import Path
import pytest
import numpy as np
from schismlab.estimate import estimate, work_units, effective_cores, fmt_range, case_params
from schismlab.io.gr3 import write_gr3, Mesh
from schismlab.mesh.idealized import rectangular_basin
from schismlab.edition import is_pro as _is_pro
requires_pro = pytest.mark.skipif(not _is_pro(), reason="necesita SCHISMlab Pro")


def test_estimate_scales_and_ranges():
    cfg = {"time": {"days": 2, "dt": 60}, "vertical": {"type": "2d"}}
    a = estimate(cfg, 10000, 8); b = estimate(cfg, 20000, 8); c = estimate(cfg, 10000, 16)
    assert b["seconds"] > 1.8 * (a["seconds"] - 30) and c["seconds"] < a["seconds"]
    assert a["low"] < a["seconds"] < a["high"]
    w = estimate({**cfg, "waves": {"enabled": True, "nstep": 3}}, 10000, 8)
    assert w["seconds"] > 3 * a["seconds"]                        # el oleaje acoplado domina con nstep pequeno
    v3 = case_params({"time": {"days": 1, "dt": 60}, "vertical": {"type": "sz", "nsigma": 20, "zlevels": [-1000, -500]}})
    assert v3["nvrt"] == 22 and v3["steps"] == 1440
    assert effective_cores(128, cluster=True) > 128
    assert "–" in fmt_range(a)


def test_estimate_matches_reference_runs():
    """Dentro del rango para dos simulaciones reales del ordenador de referencia (Ryzen 9 3950X, 16 nucleos)."""
    import schismlab.estimate as E
    old = E.physical_cores
    E.physical_cores = lambda: 16
    try:
        mareas = E.work_units(12854, 7200, 2) / E.effective_cores(16) + E.T0           # baleares_mareas: 142-202 s reales
        afl = E.work_units(4141, 4320, 25) / E.effective_cores(10) + E.T0              # afloramiento: 746 s real
        assert E.LOW * mareas < 202 and 142 < E.HIGH * mareas
        assert E.LOW * afl < 746 < E.HIGH * afl
    finally:
        E.physical_cores = old


def _mesh(tmp_path: Path, geographic=True) -> Path:
    m = rectangular_basin(Lx=20000, Ly=10000, dx=1000, depth=50.0)
    if geographic:
        m.x = 2.0 + m.x / 85000.0; m.y = 39.0 + m.y / 111000.0
    wd = tmp_path / "caso"; wd.mkdir()
    write_gr3(wd / "hgrid.gr3", m)
    return wd


def test_view_load_stats_render(tmp_path):
    from schismlab.mesh.view import load, stats, render, legend
    wd = _mesh(tmp_path)
    d = load(wd); assert (wd / "mesh_view.npz").exists() and d["size"].size == d["tri"].shape[0]
    s = stats(d); assert 500 < s["size_p50"] < 2000 and sum(s["hist_counts"]) == d["tri"].shape[0]
    for layer in ("size", "depth", "quality", "mesh"):
        r = render(d, layer, (1.9, 38.9, 2.4, 39.2), 400)
        assert r and r[0].startswith("data:image/png;base64,") and r[1][0][0] >= 38.9
    assert legend(d, "size") and legend(d, "mesh") is None
    assert render(d, "size", (10, 10, 11, 11), 400) is None             # fuera de la malla
    wd2 = _mesh(tmp_path / "b", geographic=False) if (tmp_path / "b").mkdir() is None else None
    d2 = load(wd2); assert render(d2, "size", (0, 0, 20000, 10000), 400, merc=False)


@requires_pro
def test_file_generator_keeps_or_assigns_boundaries(tmp_path):
    import yaml
    from schismlab.case import Case
    from schismlab.mesh.build import build_mesh
    src = _mesh(tmp_path, geographic=False) / "hgrid.gr3"
    cfgp = tmp_path / "imp.yaml"
    cfgp.write_text(yaml.safe_dump({"name": "imp", "mesh": {"generator": "file", "file": str(src), "open_boundaries": "bbox"}}))
    m = build_mesh(Case(cfgp), tmp_path / "out", plot=False)
    assert m.nnodes > 100 and len(m.open_boundaries) >= 1 and (tmp_path / "out" / "hgrid.gr3").exists()


def test_probe_inside_outside():
    import numpy as np
    from schismlab.mesh.view import probe
    x = np.array([0.0, 1.0, 0.0, 1.0]); y = np.array([0.0, 0.0, 1.0, 1.0])
    d = dict(x=x, y=y, depth=np.array([10.0, 20.0, 30.0, 40.0]), tri=np.array([[0, 1, 2], [1, 3, 2]]),
             size=np.array([1000.0, 1000.0]), minang=np.array([45.0, 45.0]), dt=100.0)
    v = probe(d, 0.1, 0.1)
    assert v["element"] == 1 and v["node"] == 1 and 10 < v["depth"] < 20
    assert probe(d, 2.0, 2.0) is None
