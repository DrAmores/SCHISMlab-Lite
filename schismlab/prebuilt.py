"""Ejecutables precompilados de SCHISM desde las GitHub Releases del repositorio.

Los publica .github/workflows/release.yml con el nombre pschism_<variante>-<os>-<arch>-<lockhash>.tar.gz.
Solo vale el asset cuyo lockhash coincide con el pixi.lock local: el ejecutable enlaza con las librerias
(OpenMPI, NetCDF, gfortran) de ese entorno exacto. Si no hay asset valido, el instalador compila.

Uso: python -m schismlab.prebuilt [hydro|wwm]   (codigo de salida 0 si se descargo y pasa la prueba)
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))
GITHUB_REPO = os.environ.get("SCHISMLAB_GITHUB_REPO", "DrAmores/SCHISMlab-Lite")


def lock_hash() -> str:
    return hashlib.sha256((REPO / "pixi.lock").read_bytes()).hexdigest()[:12]


def os_tag() -> str:
    return {"Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system().lower())


def arch_tag() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def asset_name(variant: str = "hydro") -> str:
    return f"pschism_{variant}-{os_tag()}-{arch_tag()}-{lock_hash()}.tar.gz"


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
        tok = out.stdout.strip()
        if out.returncode == 0 and tok and " " not in tok:
            return tok
    except (OSError, subprocess.SubprocessError):
        pass
    for hosts in (Path.home() / ".config" / "gh" / "hosts.yml", Path(os.environ.get("APPDATA", "")) / "GitHub CLI" / "hosts.yml"):
        if hosts.exists():                       # versiones antiguas de gh sin 'auth token'
            for line in hosts.read_text(errors="ignore").splitlines():
                if "oauth_token:" in line:
                    return line.split("oauth_token:", 1)[1].strip() or None
    return None


def _get(url: str, token: str | None, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "schismlab", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def latest_assets(token: str | None) -> list[dict]:
    data = json.loads(_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", token))
    return data.get("assets", [])


def fetch(variant: str = "hydro", log=print) -> Path | None:
    """Descarga el ejecutable precompilado a ~/.schismlab/bin/pschism_<variante>. None si no hay asset valido."""
    token = _token()                       # None: acceso anónimo (repositorio público, p. ej. SCHISMlab Lite)
    name = asset_name(variant)
    try:
        assets = latest_assets(token)
    except Exception as ex:                # noqa: BLE001
        log(f">> no se pudo consultar las releases de {GITHUB_REPO}: {ex}")
        return None
    hit = next((a for a in assets if a.get("name") == name), None)
    if hit is None:
        log(f">> no hay binario precompilado {name} (disponibles: {', '.join(a['name'] for a in assets) or 'ninguno'})")
        return None
    log(f">> descargando {name} ({hit.get('size', 0) / 1e6:.1f} MB)")
    bin_dir = HOME / "bin"; bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / name
        tgz.write_bytes(_get(hit["url"], token, accept="application/octet-stream"))
        with tarfile.open(tgz) as tf:
            member = next((m for m in tf.getmembers() if m.name.endswith(f"pschism_{variant}")), None)
            if member is None:
                log(">> el paquete no contiene el ejecutable esperado"); return None
            member.name = f"pschism_{variant}.new"
            tf.extract(member, bin_dir, filter="data")
    new = bin_dir / f"pschism_{variant}.new"; final = bin_dir / f"pschism_{variant}"
    new.chmod(0o755); _fix_rpath(new, log); new.replace(final)
    log(f">> instalado {final}")
    return final


def fetch_swash(log=print) -> Path | None:
    """SWASH precompilado (swash-<os>-<arch>-<lockhash>.tar.gz) a ~/.schismlab/bin/swash.exe; None si no hay."""
    import tarfile, io
    bin_dir = HOME / "bin"; out = bin_dir / "swash.exe"
    if out.exists():
        return out
    token = _token(); name = f"swash-{os_tag()}-{arch_tag()}-{lock_hash()}.tar.gz"
    try:
        hit = next((a for a in latest_assets(token) if a.get("name") == name), None)
        if hit is None:
            return None
        bin_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(_get(hit["url"], token, accept="application/octet-stream")), mode="r:gz") as tf:
            tf.extractall(bin_dir)
        out.chmod(0o755); log(f">> SWASH precompilado descargado: {out}")
        return out
    except Exception as ex:   # noqa: BLE001
        log(f">> SWASH precompilado no disponible ({ex})"); return None


def _lib_dir() -> Path | None:
    prefix = os.environ.get("CONDA_PREFIX")
    return Path(prefix) / "lib" if prefix else None


def _fix_rpath(exe: Path, log=print) -> None:
    """El RPATH del binario apunta al entorno de la maquina que lo compilo: se reescribe al entorno local si hay
    patchelf (Linux) o install_name_tool (mac). Si no, hace falta LD_LIBRARY_PATH/DYLD_FALLBACK_LIBRARY_PATH."""
    import shutil
    lib = _lib_dir()
    if lib is None:
        return
    try:
        if platform.system() == "Linux" and shutil.which("patchelf"):
            subprocess.run(["patchelf", "--set-rpath", str(lib), str(exe)], check=True, capture_output=True)
            log(f">> rpath -> {lib}")
        elif platform.system() == "Darwin" and shutil.which("install_name_tool"):
            subprocess.run(["install_name_tool", "-add_rpath", str(lib), str(exe)], check=False, capture_output=True)
            log(f">> rpath += {lib}")
    except (OSError, subprocess.SubprocessError) as ex:
        log(f">> no se pudo ajustar el rpath: {ex}")


def runtime_env() -> dict:
    """Variables para que un binario precompilado encuentre las librerias del entorno pixi local."""
    lib = _lib_dir(); env = dict(os.environ)
    if lib is not None:
        key = "DYLD_FALLBACK_LIBRARY_PATH" if platform.system() == "Darwin" else "LD_LIBRARY_PATH"
        env[key] = str(lib) + (":" + env[key] if env.get(key) else "")
    return env


def smoke_test(exe: Path, variant: str = "hydro", log=print) -> bool:
    """Ejecuta install/run_test.sh (caso smoke_basin) con ese ejecutable; True si SCHISM termina correctamente."""
    exe = Path(exe)
    if not exe.exists():
        return False
    env = dict(runtime_env(), NP="2", SCHISMLAB_HOME=str(HOME))
    p = subprocess.run(["bash", str(REPO / "install" / "run_test.sh"), variant], env=env, capture_output=True, text=True)
    log(p.stdout[-1500:] + (p.stderr[-1500:] if p.returncode else ""))
    mirror = HOME / "runs" / "smoke_basin" / "outputs" / "mirror.out"
    return p.returncode == 0 and mirror.exists() and "Run completed successfully" in mirror.read_text(errors="ignore")[-2000:]


def fix_all_rpaths(log=print) -> int:
    """Reescribe el rpath de todos los ejecutables de ~/.schismlab/bin al entorno pixi local (tras actualizar o mover)."""
    n = 0
    for exe in sorted((HOME / "bin").glob("pschism_*")) if (HOME / "bin").exists() else []:
        _fix_rpath(exe, log); n += 1
    return n


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--fix-rpath" in args:
        print(f">> {fix_all_rpaths()} ejecutables revisados"); return 0
    variant = (args or ["hydro"])[0]
    exe = fetch(variant)
    fetch_swash()
    if exe is None:
        return 1
    if not smoke_test(exe, variant):
        print(">> el binario precompilado no funciona en esta maquina: se eliminara y se compilara")
        exe.unlink(missing_ok=True)
        return 2
    print(">> binario precompilado OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
