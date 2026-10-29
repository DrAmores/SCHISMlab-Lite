"""Actualizaciones de SCHISMlab: cada instalación es un clon de git, así que comprobar si hay novedades es `git fetch` y
actualizar es `git pull --ff-only` (+ `pixi install` si cambiaron las dependencias, + recompilar SCHISM si cambió su
script). La interfaz avisa en la cabecera y ofrece un botón que lo hace todo y se reinicia."""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))
STATE = HOME / "update_check.json"
CHECK_EVERY_S = 24 * 3600
REBUILD_TRIGGERS = ("install/build_schism.sh", "install/build_wave_models.sh")
ENV_TRIGGERS = ("pixi.toml", "pixi.lock", "pyproject.toml")


def _git(*args, timeout: int = 60) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"git {' '.join(args)} ha fallado")
    return r.stdout.strip()


def is_git_repo() -> bool:
    return (REPO / ".git").exists()


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text()) if STATE.exists() else {}
    except (OSError, ValueError):
        return {}


def _write_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def check(force: bool = False) -> dict:
    """Consulta el repositorio remoto (como mucho una vez al día salvo `force`). Devuelve y guarda:
    {checked, behind, ahead, local, remote, commits: [(hash, fecha, mensaje)], needs_env, needs_build, dirty, error}."""
    st = read_state()
    if not force and time.time() - float(st.get("checked", 0)) < CHECK_EVERY_S:
        return st
    out = dict(checked=time.time(), behind=0, ahead=0, commits=[], needs_env=False, needs_build=False, dirty=False, error=None)
    if not is_git_repo():
        out["error"] = "no es un clon de git"; _write_state(out); return out
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        # refspec explícito: funciona aunque el remoto se añadiera sin refspec de fetch (solo push)
        _git("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=90)
        out["local"], out["remote"] = _git("rev-parse", "--short", "HEAD"), _git("rev-parse", "--short", f"origin/{branch}")
        counts = _git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}").split()
        out["ahead"], out["behind"] = int(counts[0]), int(counts[1])
        if out["behind"]:
            lines = _git("log", "--format=%h%x09%ad%x09%s", "--date=short", f"HEAD..origin/{branch}").splitlines()
            out["commits"] = [l.split("\t", 2) for l in lines[:50]]
            changed = _git("diff", "--name-only", f"HEAD..origin/{branch}").splitlines()
            out["needs_env"] = any(f in ENV_TRIGGERS for f in changed)
            out["needs_build"] = any(f in REBUILD_TRIGGERS for f in changed)
        dirty = [l for l in _git("status", "--porcelain", "--untracked-files=no").splitlines() if ".nicegui/" not in l]
        out["dirty"] = bool(dirty)
        out["version_remote"] = _remote_version(branch)
    except Exception as ex:   # noqa: BLE001  (sin red, sin credenciales, ...)
        out["error"] = str(ex).splitlines()[-1] if str(ex) else "error"
    try:                                                 # SCHISMlab Pro activado con token: su clon cuenta como novedad
        from .activate import fetch_behind
        out["pro_behind"] = fetch_behind()
        if out["pro_behind"]:
            out["behind"] = int(out.get("behind") or 0) + out["pro_behind"]
            out["commits"] = out.get("commits", []) + [["Pro", "", f"SCHISMlab Pro: {out['pro_behind']} cambios"]]
    except Exception:   # noqa: BLE001
        out["pro_behind"] = 0
    _write_state(out)
    return out


def _remote_version(branch: str) -> str | None:
    try:
        txt = _git("show", f"origin/{branch}:schismlab/__init__.py")
        for line in txt.splitlines():
            if line.startswith("__version__"):
                return line.split("=")[1].strip().strip("'\"")
    except Exception:   # noqa: BLE001
        return None
    return None


def changelog_since(version_remote: str | None, local_version: str | None = None) -> str:
    """Entradas del CHANGELOG remoto posteriores a la versión instalada (texto markdown), si se puede leer."""
    try:
        from . import __version__ as _v
        __version__ = local_version or _v
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        txt = _git("show", f"origin/{branch}:CHANGELOG.md")
    except Exception:   # noqa: BLE001
        return ""
    out, keep = [], False
    for line in txt.splitlines():
        if line.startswith("## "):
            keep = line[3:].split()[0] != __version__        # versión exacta: 0.7.1 no es 0.7.10
            if not keep:
                break
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def apply(log_fn=print) -> dict:
    """Actualiza: git pull --ff-only; pixi install si cambiaron las dependencias; build-schism si cambió el compilador.
    Devuelve dict(ok, restart, message)."""
    st = check(force=True)
    if st.get("error"):
        return dict(ok=False, restart=False, message=st["error"])
    if st.get("dirty"):
        return dict(ok=False, restart=False, message="hay cambios locales sin guardar en el repositorio: guárdalos (git stash o commit) antes de actualizar")
    if not st.get("behind"):
        return dict(ok=True, restart=False, message="ya está actualizado")
    env = {**os.environ, "PATH": f"{Path.home() / '.pixi' / 'bin'}:{os.environ.get('PATH', '')}"}
    if st.get("pro_behind"):
        from .activate import update as update_pro
        log_fn("SCHISMlab Pro: git pull --ff-only")
        update_pro(log_fn)
        if int(st["behind"]) == int(st["pro_behind"]):  # solo había cambios en Pro
            _write_state({**read_state(), "checked": 0})
            return dict(ok=True, restart=True, message="SCHISMlab Pro actualizado")
    log_fn("git pull --ff-only")
    log_fn(_git("pull", "--ff-only", "--quiet", timeout=300) or "ok")
    if st.get("needs_env"):
        log_fn("pixi install (dependencias cambiadas)")
        r = subprocess.run(["pixi", "install"], cwd=REPO, capture_output=True, text=True, env=env, timeout=3600)
        log_fn(r.stdout[-2000:] + r.stderr[-2000:])
        if r.returncode != 0:
            return dict(ok=False, restart=False, message="pixi install ha fallado; mira el registro")
    if st.get("needs_build"):
        log_fn("pixi run build-schism (SCHISM recompilado)")
        r = subprocess.run(["pixi", "run", "build-schism"], cwd=REPO, capture_output=True, text=True, env=env, timeout=7200)
        log_fn(r.stdout[-2000:] + r.stderr[-2000:])
        if r.returncode != 0:
            return dict(ok=False, restart=False, message="la compilación de SCHISM ha fallado; mira el registro")
    _retire_examples(log_fn)
    log_fn("rpath de los ejecutables de SCHISM")
    subprocess.run(["pixi", "run", "fix-rpath"], cwd=REPO, capture_output=True, text=True, env=env, timeout=600)
    log_fn("pixi run docs (ayuda local)")
    subprocess.run(["pixi", "run", "docs"], cwd=REPO, capture_output=True, text=True, env=env, timeout=1800)
    _write_state({**read_state(), "checked": 0})          # la próxima comprobación será inmediata
    return dict(ok=True, restart=True, message=f"actualizado a {_git('rev-parse', '--short', 'HEAD')}")


def restart_gui() -> None:
    """Reinicia el proceso de la interfaz con el mismo comando (los sockets no se heredan: el puerto queda libre)."""
    log.info("reiniciando la interfaz: %s", " ".join(sys.argv))
    os.execv(sys.executable, [sys.executable, *sys.argv])


def simulation_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "pschism_"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _retire_examples(log_fn=print) -> None:
    """Los casos de ejemplo (cases/teaching, cases/examples) dejaron de versionarse en 0.3.0: sus restos (carpetas de
    trabajo con mallas y salidas) se mueven a ~/.schismlab/papelera/ para que la galería solo muestre los casos del usuario."""
    import shutil
    for name in ("teaching", "examples"):
        d = REPO / "cases" / name
        if not d.exists():
            continue
        tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", str(d)], capture_output=True, text=True).stdout.strip()
        if tracked:
            continue                                     # todavía versionada (versión antigua): no tocar
        dst = HOME / "papelera" / f"{time.strftime('%Y%m%d-%H%M')}_cases_{name}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(dst))
        log_fn(f"casos de ejemplo retirados: cases/{name} -> {dst}")
