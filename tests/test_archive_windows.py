"""Archivar la simulación anterior en discos de Windows (/mnt/d) con otro usuario de WSL: sin renombrar y sin poder
cambiar permisos ni fechas (antes: «Operation not permitted» y la simulación nueva no arrancaba)."""
import errno
import os
import shutil
from pathlib import Path


def test_archive_outputs_without_rename_or_metadata(tmp_path, monkeypatch):
    from schismlab import run as R
    rd = tmp_path / "caso"; out = rd / "outputs"; out.mkdir(parents=True)
    (out / "out2d_1.nc").write_bytes(b"datos"); (out / "mirror.out").write_text("log")
    (rd / "param.nml").write_text("&CORE /"); (rd / "sflux").mkdir(); (rd / "sflux" / "a.nc").write_bytes(b"x")
    real_rename = os.rename

    def no_rename(a, b):
        if Path(a).name == "outputs":
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return real_rename(a, b)

    def no_stat(*a, **k):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(os, "rename", no_rename)
    monkeypatch.setattr(shutil, "copystat", no_stat)
    dst = R.archive_outputs(rd)
    assert dst is not None and (dst / "out2d_1.nc").read_bytes() == b"datos" and (dst / "param.nml").exists() and (dst / "sflux" / "a.nc").exists()
    assert not (rd / "outputs").exists() or not any((rd / "outputs").iterdir())
