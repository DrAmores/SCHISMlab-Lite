"""Bloque 1 de las prácticas con Lite: el hotstart conserva la viscosidad del caso y shapiro0 por defecto de 0.1 en
dominios idealizados (filtro de Shapiro menos fuerte, que no frena las corrientes junto a las paredes)."""
import numpy as np
import xarray as xr
import yaml
from pathlib import Path


def _case(d: Path, **extra) -> Path:
    cfg = {"name": "fis", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50, "open_sides": []},
           "vertical": {"type": "sigma", "nvrt": 6, "h_c": 5, "theta_f": 0.001}, "time": {"start": "2020-01-01", "days": 1, "dt": 60, "ramp_days": 0},
           "physics": {"baroclinic": True, "turbulence": 0}, "initial": {"elevation": 0, "temperature": "where(z > -20, 20, 12)", "salinity": 36},
           "output": {"interval_minutes": 30, "variables": ["elevation"]}}
    cfg.update(extra); d.mkdir(parents=True, exist_ok=True)
    p = d / "fis.yaml"; p.write_text(yaml.safe_dump(cfg)); return p


def _build(p):
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    rs = RunSetup(Case(p)); rs.build(); return rs


def test_hotstart_itur0_lleva_dfv0(tmp_path):
    """itur = 0: SCHISM no recalcula dfv; el hotstart debe llevar dfv0 y dfh0 (antes, ceros: A_z = 0 siempre)."""
    rs = _build(_case(tmp_path, param={"dfv0": 1e-3, "dfh0": 2e-5}))
    assert rs.param["ihot"] == 1 and int(rs.param["itur"]) == 0
    ds = xr.open_dataset(rs.dir / "hotstart.nc")
    assert np.allclose(ds.dfv, 1e-3) and np.allclose(ds.dfh, 2e-5)


def test_hotstart_itur0_valor_plantilla(tmp_path):
    """Sin dfv0 en el YAML: el de la plantilla de SCHISM (1e-2), no cero."""
    rs = _build(_case(tmp_path))
    ds = xr.open_dataset(rs.dir / "hotstart.nc")
    assert np.allclose(ds.dfv, 1e-2) and np.allclose(ds.dfh, 1e-4)


def test_hotstart_itur3_minimos_del_cierre(tmp_path):
    """itur = 3: q2 y xl con los mínimos del cierre (como el arranque en frío de SCHISM), no cero."""
    rs = _build(_case(tmp_path, physics={"baroclinic": True, "turbulence": 3}))
    ds = xr.open_dataset(rs.dir / "hotstart.nc")
    assert np.allclose(ds.q2, 5e-6)
    assert np.allclose(ds.xl.isel(nVert=0), 2 * 5e-6 * 0.1 * np.maximum(0.01, rs.m.depth))
    assert np.allclose(ds.dfv, 0.0)


def test_turbulence_state_ke():
    from schismlab.forcing.hotstart import turbulence_state
    s = turbulence_state(3, np.array([10.0, 100.0]), turb_met="'KE'")
    assert s["q2"] == 7.6e-6 and np.allclose(s["xl"], 2 * 7.6e-6 * 0.1 * np.array([10.0, 100.0]))


def test_shapiro0_por_defecto_idealizado(tmp_path):
    rs = _build(_case(tmp_path))
    assert float(rs.param["shapiro0"]) == 0.1
    txt = (rs.dir / "param.nml").read_text()
    assert "shapiro0 = 0.1" in txt


def test_shapiro0_del_yaml(tmp_path):
    rs = _build(_case(tmp_path / "a", physics={"baroclinic": True, "turbulence": 0, "shapiro0": 0.3}))
    assert float(rs.param["shapiro0"]) == 0.3
    rs = _build(_case(tmp_path / "b", param={"shapiro0": 0.5}))   # sobreescritura directa: gana
    assert float(rs.param["shapiro0"]) == 0.5
