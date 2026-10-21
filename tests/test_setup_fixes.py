"""Correcciones de la auditoría del 19/10/2026 en setup.py, expressions.py y run.py."""
import numpy as np
import pytest
import yaml
from pathlib import Path
from schismlab.edition import is_pro as _is_pro
requires_pro = pytest.mark.skipif(not _is_pro(), reason="necesita SCHISMlab Pro")


def _case(d: Path, **extra) -> Path:
    cfg = {"name": "fix", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50, "open_sides": []},
           "vertical": {"type": "2d"}, "time": {"start": "2020-01-01T06:30", "days": 2, "dt": 60, "ramp_days": 0},
           "physics": {"baroclinic": False}, "initial": {"elevation": 0, "temperature": 20, "salinity": 36},
           "output": {"interval_minutes": 30, "variables": ["elevation", "depthAverageVel"]}}
    cfg.update(extra); d.mkdir(parents=True, exist_ok=True)
    p = d / "fix.yaml"; p.write_text(yaml.safe_dump(cfg)); return p


def _build(p):
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    rs = RunSetup(Case(p)); rs.build(); return rs


def test_hotstart_stack_station_7min_consistent(tmp_path):
    # intervalo de estación de 7 min (no divide a la pila): antes nhot_write dejaba de ser múltiplo de ihfskip y SCHISM abortaba
    rs = _build(_case(tmp_path, output={"interval_minutes": 30, "stack_hours": 6, "hotstart_hours": 12, "variables": ["elevation"],
                                        "station_interval_minutes": 7}, stations=[{"name": "c", "x": 10e3, "y": 5e3}]))
    p = rs.param
    assert p["ihfskip"] % p["nspool"] == 0 and p["ihfskip"] % p["nspool_sta"] == 0
    assert p["nhot"] == 1 and p["nhot_write"] % p["ihfskip"] == 0 and p["nhot_write"] % p["nspool_sta"] == 0
    assert p["nspool_sta"] == 7 and p["start_hour"] == 6.5


def test_scribes_count_only_3d(tmp_path):
    rs = _build(_case(tmp_path))                                   # 2D: solo el scribe de out2d
    assert rs.nscribes == 1
    rs3 = _build(_case(tmp_path / "b", vertical={"type": "sigma", "nvrt": 5, "h_c": 5, "theta_f": 0.001},
                       output={"interval_minutes": 30, "variables": ["elevation", "horizontalVel", "temperature"]}))
    assert rs3.nscribes == 4                                       # u, v, T + out2d


def test_wind_fractional_dt_hours(tmp_path):
    rs = _build(_case(tmp_path, forcing={"wind": {"u": 5, "v": 0, "dt_hours": 0.5}}))
    t = np.loadtxt(rs.dir / "wind.th")[:, 0]
    assert np.all(np.diff(t) > 0) and np.isclose(t[1] - t[0], 1800)


@requires_pro
def test_stations_in_metres_converted_on_geographic(tmp_path):
    rs = _build(_case(tmp_path, mesh={"generator": "idealized", "lon": [0, 0.5], "lat": [40, 40.25], "dx": 4000, "bathymetry": 50, "open_sides": []},
                      stations=[{"name": "c", "x": 20e3, "y": 10e3}]))
    line = (rs.dir / "station.in").read_text().splitlines()[2].split()
    assert 0 < float(line[1]) < 0.5 and 40 < float(line[2]) < 40.25


def test_baroclinic_in_2d_runs_barotropic(tmp_path):
    rs = _build(_case(tmp_path, physics={"baroclinic": True}))
    assert rs.param["ibc"] == 1 and not rs.baroclinic


@requires_pro
def test_boundaries_list_length_and_source_without_open(tmp_path):
    with pytest.raises(ValueError, match="contornos abiertos"):
        _build(_case(tmp_path, mesh={"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50, "open_sides": ["E"]},
                     boundaries=[{"elevation": "none"}, {"elevation": "none"}]))
    with pytest.raises(ValueError, match="contornos abiertos forzados"):
        _build(_case(tmp_path / "b", boundaries={"elevation": "none", "source": {"name": "medsea"}}))


def test_null_sections_tolerated(tmp_path):
    rs = _build(_case(tmp_path, scenario=None, physics=None, forcing=None, initial={"source": "none", "elevation": 0}))
    assert rs.param["ihot"] == 0


def test_expressions_validation():
    from schismlab.expressions import evaluate, validate
    x = np.array([0.0, 1.0])
    assert np.allclose(evaluate("2*x + sin(x)", x=x), 2 * x + np.sin(x))
    for bad in ("().__class__.__bases__[0]", "__import__('os')", "x.real", "lambda: 1", "open('f')", "x[0]", "'a'", "y"):
        with pytest.raises(ValueError):
            evaluate(bad, x=x)
    with pytest.raises(ValueError, match="vacía"):
        validate("")
