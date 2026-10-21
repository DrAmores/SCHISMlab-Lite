"""Recetas de condiciones iniciales (frente, capas, ...) -> expresiones del YAML, y hotstart con velocidad inicial."""
from pathlib import Path
import numpy as np
import pytest
import yaml
from schismlab.initial import (recipe_expression, recipe_matches, recipe_from_value, recipe_uses_z, density,
                               domain_frame, expression_vars, domain_extent, evaluate_field)
from schismlab.expressions import evaluate
from schismlab.mesh import rectangular_basin


def test_layers_recipe_reproduces_teaching_case():
    # ajuste geostrófico clásico: where(z > -50 - 20*tanh((x-100e3)/10e3), 20, 12) en un dominio de 200 km
    r = dict(mode="layers", v_top=20, v_bot=12, depth=50, slope_m=20, axis="x", pos=0.5, width_km=10)
    e = recipe_expression(r, 200e3, 100e3)
    x = np.linspace(0, 200e3, 41)[:, None] + np.zeros((1, 11)); z = np.linspace(-100, 0, 11)[None, :] + 0 * x
    ref = evaluate("where(z > -50 - 20*tanh((x-100e3)/10e3), 20, 12)", x=x, y=0 * x, z=z)
    assert np.array_equal(evaluate(e, x=x, y=0 * x, z=z), ref)
    assert recipe_uses_z(r) and recipe_matches(r, e, 200e3, 100e3) and not recipe_matches(r, e, 150e3, 100e3)


def test_front_gauss_gradient_values():
    Lx, Ly = 100e3, 50e3
    x = np.array([0.0, 50e3, 100e3]); y = np.array([25e3, 25e3, 25e3])
    f = evaluate(recipe_expression(dict(mode="front", v1=10, v2=20, axis="x", pos=0.5, width_km=1), Lx, Ly), x=x, y=y)
    assert f[0] == pytest.approx(10, abs=1e-6) and f[1] == pytest.approx(15) and f[2] == pytest.approx(20, abs=1e-6)
    g = evaluate(recipe_expression(dict(mode="gauss", base=0, amp=1, cx=0.5, cy=0.5, radius_km=10), Lx, Ly), x=x, y=y)
    assert g[1] == pytest.approx(1) and g[0] < 1e-4
    lin = evaluate(recipe_expression(dict(mode="gradient", v1=35, v2=37, axis="x"), Lx, Ly), x=x, y=y)
    assert np.allclose(lin, [35, 36, 37])
    assert recipe_expression(dict(mode="constant", value=3), Lx, Ly) == 3.0
    assert recipe_from_value("z*2")["mode"] == "expr" and recipe_from_value(4)["value"] == 4
    assert recipe_uses_z(dict(mode="gauss", depth=30)) and not recipe_uses_z(dict(mode="gauss", depth=0))


def test_density_eos80():
    assert density(20.0, 35.0) == pytest.approx(1024.763, abs=0.01)      # valor tabulado (UNESCO 1983)
    assert density(12.0, 36.0) > density(20.0, 36.0) > density(20.0, 35.0)


def test_frame_geographic_vs_cartesian():
    m = rectangular_basin(0, 0, 5000, depth=100, lon=(0, 1), lat=(40, 40.5))
    fr = domain_frame(m, {"mesh": {"generator": "idealized", "lon": [0, 1], "lat": [40, 40.5]}})
    Lx, Ly = domain_extent(fr)
    assert Lx == pytest.approx(111.2e3 * np.cos(np.deg2rad(40.25)), rel=0.01) and Ly == pytest.approx(55.6e3, rel=0.01)
    assert fr["x"].min() == 0 and np.allclose(fr["lon"], m.x)
    mc = rectangular_basin(20e3, 10e3, 5000, depth=100)
    fc = domain_frame(mc, {"mesh": {"generator": "idealized"}, "reference": {"lon0": 2, "lat0": 39}})
    assert np.allclose(fc["x"], mc.x) and fc["lat"].min() == pytest.approx(39)
    z = np.linspace(-100, 0, 4)[None, :] + np.zeros((mc.nnodes, 1))
    v = expression_vars(fc, mc.depth, z)
    assert v["x"].shape == z.shape and v["z"] is z
    assert evaluate_field("where(z > -50, 1, 0)", fc, mc.depth, z).shape == z.shape


def _write_case(d: Path, **extra) -> Path:
    cfg = {"name": "ic_test", "mesh": {"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50, "open_sides": []},
           "vertical": {"type": "2d"}, "time": {"start": "2020-01-01", "days": 0.01, "dt": 60, "ramp_days": 0},
           "physics": {"baroclinic": False}, "initial": {"elevation": 0, "temperature": 20, "salinity": 36},
           "output": {"interval_minutes": 10, "variables": ["elevation"]}}
    cfg.update(extra)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ic_test.yaml"; p.write_text(yaml.safe_dump(cfg)); return p


def test_setup_velocity_hotstart(tmp_path):
    import xarray as xr
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    p = _write_case(tmp_path / "a", initial={"elevation": 0, "temperature": 20, "salinity": 36, "velocity": {"u": "0.2 + 0*x", "v": -0.1}})
    rs = RunSetup(Case(p)); rs.build()
    assert rs.param["ihot"] == 1
    ds = xr.open_dataset(rs.dir / "hotstart.nc")
    assert np.allclose(ds.su2, 0.2) and np.allclose(ds.sv2, -0.1)
    # sin velocidad y barotropo: arranque en frio sin hotstart
    rs2 = RunSetup(Case(_write_case(tmp_path / "b"))); rs2.build()
    assert rs2.param["ihot"] == 0 and not (rs2.dir / "hotstart.nc").exists()


def test_setup_front_baroclinic(tmp_path):
    import xarray as xr
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    T = recipe_expression(dict(mode="layers", v_top=20, v_bot=12, depth=25, slope_m=10, axis="x", pos=0.5, width_km=2), 20e3, 10e3)
    p = _write_case(tmp_path, vertical={"type": "sigma", "nvrt": 6, "h_c": 5, "theta_f": 0.001}, physics={"baroclinic": True, "turbulence": 0},
                    initial={"elevation": 0, "temperature": T, "salinity": 36})
    rs = RunSetup(Case(p)); rs.build()
    assert rs.param["ihot"] == 1 and rs.param["flag_ic(1)"] == 1
    ds = xr.open_dataset(rs.dir / "hotstart.nc")
    Tn = ds.tr_nd[:, :, 0].values
    assert Tn.max() == 20 and Tn.min() == 12 and Tn[:, -1].min() == 20       # superficie caliente en todo el dominio
    assert np.allclose(ds.su2, 0)


def test_toplayer_rossby_adjustment():
    # capa ligera de espesor H solo a un lado (x < x0) sobre un fluido uniforme: figura clasica del ajuste de Rossby
    r = dict(mode="toplayer", v1=20, v2=12, v_bot=12, depth=50, axis="x", pos=0.5, width_km=0.5)
    e = recipe_expression(r, 200e3, 100e3)
    x = np.array([[20e3], [180e3]]) + np.zeros((1, 3)); z = np.array([[-80, -30, 0]]) + 0 * x
    f = evaluate(e, x=x, y=0 * x, z=z)
    assert np.allclose(f[0], [12, 20, 20]) and np.allclose(f[1], [12, 12, 12])
    assert recipe_uses_z(r) and recipe_matches(r, e, 200e3, 100e3)


def test_idealized_side_types_radiation(tmp_path):
    import json
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    p = _write_case(tmp_path, mesh={"generator": "idealized", "Lx": 20e3, "Ly": 10e3, "dx": 2000, "bathymetry": 50,
                                    "open_sides": ["S", "N", "E"], "side_types": {"S": "radiation", "N": "radiation"}})
    rs = RunSetup(Case(p)); rs.build()
    assert json.loads((rs.dir / "open_boundary_types.json").read_text()) == ["radiation", "forced", "radiation"]   # orden S, E, N
    lines = (rs.dir / "bctides.in").read_text().splitlines()
    flags = [l.split()[1:3] for l in lines if l.endswith(tuple("0123456789")) and len(l.split()) == 5]
    assert flags[0][1] == "-1" and flags[2][1] == "-1" and flags[1][1] == "0"       # Flather en S y N, forzado (sin nivel) en E
    assert "eta_mean" in lines and "vn_mean" in lines


def test_outputs_stack_hotstart_station_flags(tmp_path):
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    p = _write_case(tmp_path, time={"start": "2020-01-01", "days": 2, "dt": 60, "ramp_days": 0},
                    output={"interval_minutes": 30, "stack_hours": 6, "hotstart_hours": 12, "variables": ["elevation", "depthAverageVel"],
                            "station_interval_minutes": 5, "station_variables": ["elev", "u", "v"]},
                    stations=[{"name": "c", "x": 10e3, "y": 5e3}])
    rs = RunSetup(Case(p)); rs.build()
    assert rs.param["nspool"] == 30 and rs.param["ihfskip"] == 360 and rs.param["nhot"] == 1 and rs.param["nhot_write"] == 720
    assert rs.param["nhot_write"] % rs.param["nspool_sta"] == 0 and rs.param["nspool_sta"] == 5
    assert (rs.dir / "station.in").read_text().splitlines()[0].startswith("1 0 0 0 0 0 1 1 0")
    assert rs.nscribes == 1                                    # 2D: solo el scribe de out2d


def test_crop_outputs_dev_run():
    from pathlib import Path
    import shutil
    from schismlab.analysis.output import crop_outputs, open_run
    src = Path.home() / ".schismlab" / "runs" / "dev_geo" / "dev_geo"
    if not (src / "outputs").exists():
        pytest.skip("sin simulación de desarrollo")
    out = crop_outputs(src, (0.5, 1.5), (40.2, 40.8), out_name="outputs_test_crop")
    try:
        ds = open_run(out); full = open_run(src)
        assert 0 < ds.sizes["node"] < full.sizes["node"] and ds.x.min() >= 0.5 and ds.x.max() <= 1.5
        e = ds.attrs["elements"]; assert e.min() >= 0 and e.max() < ds.sizes["node"]
        assert ds.sizes["time"] == full.sizes["time"] and "temperature" in ds
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_stop_local_kills_process_group(tmp_path):
    import subprocess, time, os
    from schismlab.run import stop_local, local_pid
    assert local_pid(tmp_path) is None
    p = subprocess.Popen(["bash", "-c", "sleep 300 & sleep 300"], start_new_session=True)
    (tmp_path / "run.pid").write_text(f"{p.pid}\n")
    assert local_pid(tmp_path) == p.pid
    assert stop_local(tmp_path, grace=5)
    time.sleep(0.5)
    assert p.poll() is not None and (tmp_path / "run.stop").exists()
    assert local_pid(tmp_path) is None


def test_archive_and_list_runs(tmp_path):
    from schismlab.run import archive_outputs, list_runs
    wd = tmp_path / "caso"; (wd / "outputs").mkdir(parents=True)
    assert archive_outputs(wd) is None and list_runs(wd) == []
    (wd / "outputs" / "out2d_1.nc").write_bytes(b"x"); (wd / "param.nml").write_text("dt = 1\n")
    runs = list_runs(wd); assert len(runs) == 1 and runs[0]["current"]
    dst = archive_outputs(wd)
    assert dst is not None and dst.name.startswith("outputs_") and (dst / "out2d_1.nc").exists() and (dst / "param.nml").exists()
    assert not (wd / "outputs").exists()
    (wd / "outputs").mkdir(); (wd / "outputs" / "out2d_1.nc").write_bytes(b"y")
    runs = list_runs(wd); assert [r["current"] for r in runs] == [True, False]


def test_archive_is_self_contained_and_case_from_run(tmp_path):
    import yaml
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    from schismlab.run import archive_outputs, list_runs, case_from_run, write_run_info
    p = _write_case(tmp_path / "a")
    rs = RunSetup(Case(p)); rs.build()
    assert (rs.dir / "caso.yaml").exists()
    (rs.dir / "outputs" / "out2d_1.nc").write_bytes(b"x"); write_run_info(rs.dir, machine="local", ncores=4, seconds=12)
    dst = archive_outputs(rs.dir)
    for f in ("hgrid.gr3", "param.nml", "bctides.in", "caso.yaml", "vgrid.in", "out2d_1.nc", "run_info.json"):
        assert (dst / f).exists(), f
    runs = list_runs(rs.dir)
    assert len(runs) == 1 and runs[0]["reproducible"] and runs[0]["info"]["ncores"] == 4
    newp = case_from_run(dst, "repro", tmp_path / "cases")
    cfg = yaml.safe_load(newp.read_text()); assert cfg["name"] == "repro"
    wd = tmp_path / "cases" / "repro"
    assert (wd / "hgrid.gr3").exists() and (wd / "param.nml").exists() and not (wd / "out2d_1.nc").exists()
    rs2 = RunSetup(Case(newp)); rs2.build()                       # el setup reutiliza la malla copiada
    assert (rs2.dir / "bctides.in").exists()


def test_export_import_case(tmp_path):
    import zipfile, yaml
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    from schismlab.gui.state import export_case, import_case
    p = _write_case(tmp_path / "a"); rs = RunSetup(Case(p)); rs.build()
    (rs.dir / "outputs" / "out2d_1.nc").write_bytes(b"x")
    z = export_case(p, include_inputs=True, include_outputs=False, out=tmp_path / "caso.zip")
    names = zipfile.ZipFile(z).namelist()
    assert "caso.yaml" in names and "manifest.json" in names and "workdir/hgrid.gr3" in names and "workdir/outputs/out2d_1.nc" not in names
    z2 = export_case(p, include_inputs=False, include_outputs=True, out=tmp_path / "caso2.zip")
    assert "workdir/outputs/out2d_1.nc" in zipfile.ZipFile(z2).namelist() and "workdir/hgrid.gr3" not in zipfile.ZipFile(z2).namelist()
    dest = tmp_path / "cases"
    q = import_case(z, folder=dest)
    assert q.name == "ic_test.yaml" and (dest / "ic_test" / "hgrid.gr3").exists() and yaml.safe_load(q.read_text())["name"] == "ic_test"
    q2 = import_case(z, folder=dest)                       # mismo nombre: sufijo
    assert q2.name == "ic_test_2.yaml" and yaml.safe_load(q2.read_text())["name"] == "ic_test_2"
    rs2 = RunSetup(Case(q)); rs2.build()                   # el caso importado se prepara usando la malla incluida
    assert (rs2.dir / "bctides.in").exists()


def test_2d_turbulence_flag_and_mixing_files(tmp_path):
    # en 2D el cierre turbulento no aplica (itur=0) y diffmin/diffmax existen siempre: evita el fallo de arranque de SCHISM
    from schismlab.case import Case
    from schismlab.setup import RunSetup
    p = _write_case(tmp_path / "a", physics={"baroclinic": False, "turbulence": 3})
    rs = RunSetup(Case(p)); rs.build()
    assert rs.param["itur"] == 0 and (rs.dir / "diffmin.gr3").exists() and (rs.dir / "diffmax.gr3").exists()
