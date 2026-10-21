"""Borrar casos de «Mis casos»: van a la papelera y se pueden recuperar; los de ejemplo no se borran."""
import pytest
from schismlab.gui import state


def test_delete_moves_to_trash(tmp_path, monkeypatch):
    mine = tmp_path / "cases"; monkeypatch.setattr(state, "USER_CASES", mine); monkeypatch.setattr(state, "TRASH", tmp_path / "papelera")
    p = state.new_case("prueba_borrar", folder=mine)
    (mine / "prueba_borrar").mkdir(); (mine / "prueba_borrar" / "hgrid.gr3").write_text("x")
    dest = state.delete_case(p)
    assert not p.exists() and not (mine / "prueba_borrar").exists()
    assert (dest / "prueba_borrar.yaml").exists() and (dest / "prueba_borrar" / "hgrid.gr3").exists()


def test_cannot_delete_examples(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "USER_CASES", tmp_path / "cases")
    with pytest.raises(PermissionError):
        state.delete_case(state.REPO / "cases" / "examples" / "baleares.yaml")


def test_workdir_root_new_copy_import_delete(tmp_path, monkeypatch):
    """Carpeta de simulación elegida por el usuario: workdir absoluto en el YAML, no se hereda al duplicar, la importación
    desempaqueta allí y borrar se lleva también esa carpeta (solo la propia del caso)."""
    import io, zipfile
    from schismlab.case import Case
    mine = tmp_path / "cases"; sims = tmp_path / "simulaciones"
    monkeypatch.setattr(state, "USER_CASES", mine); monkeypatch.setattr(state, "TRASH", tmp_path / "papelera")
    root = state.workdir_root(str(sims)); assert root == sims.resolve() and sims.is_dir()
    assert state.workdir_root(None) is None and state.workdir_root(str(mine)) is None
    with pytest.raises(ValueError):
        state.workdir_root("relativa/carpeta")
    p = state.new_case("ekman_x", workdir_root=root)
    assert Case(p).workdir == sims.resolve() / "ekman_x" and p.parent == mine
    # duplicar: no hereda la carpeta del original
    q = state.copy_case(p, "ekman_y")
    assert Case(q).workdir == mine / "ekman_y" and "workdir" not in state.load_cfg(q)
    q2 = state.copy_case(p, "ekman_z", workdir_root=root); assert Case(q2).workdir == sims.resolve() / "ekman_z"
    # importar en la carpeta elegida
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("caso.yaml", "name: importado\nmesh: {generator: idealized, Lx: 1000, Ly: 1000, dx: 500, bathymetry: 10}\n")
        z.writestr("workdir/hgrid.gr3", "malla")
    zp = tmp_path / "importado.zip"; zp.write_bytes(buf.getvalue())
    pi = state.import_case(zp, workdir_root=root)
    assert pi.parent == mine and (sims / "importado" / "hgrid.gr3").read_text() == "malla" and Case(pi).workdir == sims.resolve() / "importado"
    # borrar: la carpeta externa propia del caso va a la papelera
    (sims / "ekman_x").mkdir(); (sims / "ekman_x" / "param.nml").write_text("x")
    dest = state.delete_case(p)
    assert not (sims / "ekman_x").exists() and (dest / "ekman_x" / "param.nml").exists() and sims.exists()
