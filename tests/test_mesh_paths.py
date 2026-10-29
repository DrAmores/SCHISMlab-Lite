"""Rutas relativas del bloque mesh: se resuelven desde la carpeta del YAML (en el clúster se ejecuta desde otra)."""
from pathlib import Path
from schismlab.mesh.build import case_files_absolute


def test_rutas_relativas_desde_la_carpeta_del_yaml(tmp_path, monkeypatch):
    (tmp_path / "_ext").mkdir(); tif = tmp_path / "_ext" / "0_bat.tif"; tif.write_bytes(b"x"); dem = tmp_path / "mdt.tif"; dem.write_bytes(b"x")
    cfg = {"bathymetry": [{"source": "gebco2021"}, {"source": "_ext/0_bat.tif", "blend_km": 1}],
           "inundation": {"dem": "mdt.tif", "size": 3}}
    monkeypatch.chdir(Path("/"))
    out = case_files_absolute(cfg, tmp_path)
    assert out["bathymetry"][0]["source"] == "gebco2021" and out["bathymetry"][1]["source"] == str(tif.resolve())
    assert out["bathymetry"][1]["blend_km"] == 1 and out["inundation"]["dem"] == str(dem.resolve())
    assert cfg["bathymetry"][1]["source"] == "_ext/0_bat.tif"                       # no toca el original
    assert case_files_absolute({"bathymetry": "gebco2021", "inundation": {"dem": "mdt02"}}, tmp_path)["inundation"]["dem"] == "mdt02"
