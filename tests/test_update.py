"""Comprobación y aplicación de actualizaciones con un repositorio git de prueba (sin red)."""
import subprocess
from pathlib import Path
import pytest
from schismlab import update


def _git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo_pair(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"; subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = tmp_path / "work"; subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    for d in (work,):
        _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    (work / "schismlab").mkdir(); (work / "schismlab" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (work / "CHANGELOG.md").write_text("# Cambios\n\n## 0.1.0\n- inicial\n")
    _git(work, "add", "."); _git(work, "commit", "-q", "-m", "inicial"); _git(work, "push", "-q", "origin", "HEAD")
    other = tmp_path / "other"; subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    _git(other, "config", "user.email", "t@t"); _git(other, "config", "user.name", "t")
    monkeypatch.setattr(update, "REPO", work); monkeypatch.setattr(update, "STATE", tmp_path / "state.json")
    return work, other


def test_check_and_apply(repo_pair):
    work, other = repo_pair
    st = update.check(force=True)
    assert st["behind"] == 0 and st["error"] is None and not st["dirty"]
    (other / "schismlab" / "__init__.py").write_text('__version__ = "0.2.0"\n'); (other / "pixi.lock").write_text("x")
    (other / "CHANGELOG.md").write_text("# Cambios\n\n## 0.2.0\n- novedad\n\n## 0.1.0\n- inicial\n")
    _git(other, "add", "."); _git(other, "commit", "-q", "-m", "novedad"); _git(other, "push", "-q", "origin", "HEAD")
    st = update.check(force=True)
    assert st["behind"] == 1 and st["needs_env"] and not st["needs_build"] and st["version_remote"] == "0.2.0"
    assert st["commits"][0][2] == "novedad"
    assert "novedad" in update.changelog_since("0.2.0", local_version="0.1.0") and "inicial" not in update.changelog_since("0.2.0", local_version="0.1.0")
    # cambios locales: se niega a actualizar
    (work / "CHANGELOG.md").write_text("local\n")
    r = update.apply(log_fn=lambda s: None); assert not r["ok"] and "locales" in r["message"]
    _git(work, "checkout", "--", "CHANGELOG.md")
    # pixi simulado: la actualización no debe lanzar instalaciones reales en los tests
    import subprocess as _sp
    real_run = _sp.run
    def fake_run(cmd, *a, **k):
        if cmd and cmd[0] == "pixi":
            return _sp.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    monkeypatch_ = pytest.MonkeyPatch(); monkeypatch_.setattr(update.subprocess, "run", fake_run)
    try:
        r = update.apply(log_fn=lambda s: None)
    finally:
        monkeypatch_.undo()
    assert r["ok"] and r["restart"]
    assert _git(work, "rev-parse", "HEAD") == _git(other, "rev-parse", "HEAD")
    assert update.check(force=True)["behind"] == 0
