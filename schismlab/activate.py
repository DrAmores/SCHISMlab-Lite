"""Activación de SCHISMlab Pro en una instalación de SCHISMlab Lite.

La extensión vive en un repositorio privado de GitHub. Quien tiene un token de acceso (de solo lectura, limitado a ese
repositorio) lo pega en Instalación: se comprueba contra GitHub, se clona el repositorio en ~/.schismlab/pro y el token
se guarda en ~/.schismlab/credentials/pro_token (permisos 600), nunca en el repositorio ni en la URL del remoto.
Las actualizaciones (botón Actualizar) usan ese mismo token. Si el token se revoca, lo ya descargado sigue en el equipo
pero no se actualiza más.
"""
from __future__ import annotations
import base64
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .edition import PRO_HOME

PRO_REPO = os.environ.get("SCHISMLAB_PRO_REPO", "DrAmores/SCHISMlab-Pro")
PRO_GIT_URL = os.environ.get("SCHISMLAB_PRO_GIT_URL", f"https://github.com/{PRO_REPO}.git")   # otra URL: espejo o pruebas
TOKEN_FILE = Path(os.environ.get("SCHISMLAB_PRO_TOKEN_FILE", Path.home() / ".schismlab" / "credentials" / "pro_token")).expanduser()


class ActivationError(RuntimeError):
    pass


def saved_token() -> str | None:
    try:
        t = TOKEN_FILE.read_text().strip()
        return t or None
    except OSError:
        return None


def _save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip() + "\n")
    os.chmod(TOKEN_FILE, 0o600)


def _header(token: str) -> str:
    """Cabecera HTTP para git: el token no aparece en la línea de órdenes de otros procesos ni en .git/config."""
    return "Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()


def _git(args: list[str], token: str, cwd: Path | None = None, timeout: int = 600) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader", "GIT_CONFIG_VALUE_0": _header(token)}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().replace(token, "***")
        raise ActivationError(msg.splitlines()[-1] if msg else f"git {args[0]} ha fallado")
    return r.stdout.strip()


def check_token(token: str) -> None:
    """Comprueba que el token da acceso de lectura al repositorio de SCHISMlab Pro (ActivationError si no)."""
    token = (token or "").strip()
    if not token:
        raise ActivationError("token vacío / empty token")
    req = urllib.request.Request(f"https://api.github.com/repos/{PRO_REPO}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "SCHISMlab"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex:
        if ex.code in (401, 403, 404):
            raise ActivationError("el token no da acceso a SCHISMlab Pro / the token gives no access to SCHISMlab Pro") from None
        raise ActivationError(f"GitHub ha respondido {ex.code} / GitHub answered {ex.code}") from None
    except urllib.error.URLError as ex:
        raise ActivationError(f"sin conexión con GitHub / no connection to GitHub: {ex.reason}") from None


def is_clone() -> bool:
    return (PRO_HOME / ".git").exists() and (PRO_HOME / "schismlab_pro" / "__init__.py").exists()


def install(token: str, log_fn=print) -> Path:
    """Comprueba el token, clona (o actualiza) SCHISMlab Pro en ~/.schismlab/pro y guarda el token."""
    token = (token or "").strip()
    url = PRO_GIT_URL
    if url.startswith("https://github.com/"):
        log_fn("comprobando el token / checking the token")
        check_token(token)
    if is_clone():
        log_fn(f"actualizando {PRO_HOME}")
        _git(["-C", str(PRO_HOME), "pull", "--ff-only", "--quiet"], token)
    else:
        tmp = PRO_HOME.with_name(PRO_HOME.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        log_fn(f"descargando SCHISMlab Pro en {PRO_HOME}")
        _git(["clone", "--quiet", "--depth", "1", url, str(tmp)], token)
        if PRO_HOME.exists():
            shutil.rmtree(PRO_HOME)
        tmp.rename(PRO_HOME)
    _save_token(token)
    log_fn("SCHISMlab Pro instalado / installed")
    return PRO_HOME


def fetch_behind() -> int:
    """Número de versiones de SCHISMlab Pro por descargar (0 si no hay clon o token)."""
    tok = saved_token()
    if not (tok and is_clone()):
        return 0
    _git(["-C", str(PRO_HOME), "fetch", "--quiet", "origin"], tok, timeout=90)
    out = _git(["-C", str(PRO_HOME), "rev-list", "--count", "HEAD..@{u}"], tok)
    return int(out or 0)


def update(log_fn=print) -> bool:
    """git pull de ~/.schismlab/pro con el token guardado. True si ha cambiado algo."""
    tok = saved_token()
    if not (tok and is_clone()):
        return False
    before = _git(["-C", str(PRO_HOME), "rev-parse", "HEAD"], tok)
    _git(["-C", str(PRO_HOME), "pull", "--ff-only", "--quiet"], tok)
    after = _git(["-C", str(PRO_HOME), "rev-parse", "HEAD"], tok)
    if before != after:
        log_fn(f"SCHISMlab Pro actualizado ({after[:7]})")
    return before != after
