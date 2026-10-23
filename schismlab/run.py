"""Ejecucion local de SCHISM con mpirun."""
from __future__ import annotations
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)
HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))


def schism_env() -> dict:
    """Entorno para lanzar pschism: los binarios descargados de una release buscan OpenMPI/NetCDF en el entorno pixi.

    (No se pone en la activacion de pixi porque rompe el ssh del sistema: OpenSSL distinto.)
    """
    env = dict(os.environ)
    prefix = env.get("CONDA_PREFIX")
    if prefix:
        for var in ("LD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
            env[var] = f"{prefix}/lib" + (":" + env[var] if env.get(var) else "")
    return env


def run_local(rundir: Path, variant: str = "hydro", ncores: int | None = None, nscribes: int | None = None) -> int:
    rundir = Path(rundir)
    if (rundir / "variant").exists():                       # el setup decide la variante (wwm si hay oleaje)
        variant = (rundir / "variant").read_text().strip() or variant
    exe = HOME / "bin" / f"pschism_{variant}"
    if not exe.exists():
        raise FileNotFoundError(f"no existe {exe}: ejecuta 'pixi run build-schism {variant}'")
    nscribes = nscribes or int((rundir / "nscribes").read_text()) if (rundir / "nscribes").exists() else (nscribes or 1)
    ncores = ncores or max(1, (os.cpu_count() or 2) - nscribes - 1)
    archive_outputs(rundir)                                 # la simulación anterior queda guardada (outputs_<fecha>/)
    (rundir / "outputs").mkdir(exist_ok=True)
    for f in (rundir / "outputs").glob("*"):
        try:
            f.unlink() if f.is_file() else shutil.rmtree(f)
        except OSError as ex:                               # fichero bloqueado (Dropbox, disco de Windows): SCHISM lo sobrescribe
            log.warning("no se pudo borrar %s: %s", f.name, ex)
    cmd = ["mpirun", "--oversubscribe", "-np", str(ncores + nscribes), str(exe), str(nscribes)]
    log.info("ejecutando: %s  (en %s)", " ".join(cmd), rundir)
    t0 = time.time()
    (rundir / "run.stop").unlink(missing_ok=True)
    with open(rundir / "run.log", "w") as logf:
        p = subprocess.Popen(cmd, cwd=rundir, stdout=logf, stderr=subprocess.STDOUT, env=schism_env(), start_new_session=True)
        (rundir / "run.pid").write_text(f"{p.pid}\n")           # para poder detenerla desde la interfaz (stop_local)
        mirror = rundir / "outputs" / "mirror.out"
        last = ""
        while p.poll() is None:
            time.sleep(2)
            if mirror.exists():
                try:
                    lines = [l for l in mirror.read_text(errors="ignore").splitlines() if "TIME STEP" in l]
                    if lines and lines[-1] != last:
                        last = lines[-1]; log.info(last.strip())
                except OSError:
                    pass
    dt = time.time() - t0
    (rundir / "run.pid").unlink(missing_ok=True)
    if (rundir / "run.stop").exists():
        (rundir / "run.stop").unlink(missing_ok=True)
        log.warning("simulación detenida por el usuario tras %.0f s; las salidas escritas hasta ahora quedan en %s", dt, rundir / "outputs")
        return 130
    fatal = rundir / "outputs" / "fatal.error"
    aborted = "ABORT" in (rundir / "run.log").read_text(errors="ignore")[-20000:] or not (rundir / "outputs" / "mirror.out").exists() \
        or "Run completed successfully" not in (rundir / "outputs" / "mirror.out").read_text(errors="ignore")[-2000:]
    if p.returncode != 0 or (fatal.exists() and fatal.stat().st_size > 0) or aborted:
        log.error("SCHISM ha fallado (%.0f s). fatal.error:\n%s", dt, fatal.read_text() if fatal.exists() else "")
        for name in ("outputs/mirror.out", "run.log"):
            txt = (rundir / name).read_text(errors="ignore") if (rundir / name).exists() else ""
            if txt.strip():
                log.error("ultimas lineas de %s:\n%s", name, "\n".join(txt.splitlines()[-15:]))
        return p.returncode or 1
    log.info("SCHISM terminado en %.0f s; salidas en %s", dt, rundir / "outputs")
    from .estimate import record_run
    record_run(rundir, dt, ncores)                            # calibra la estimacion de tiempo de este ordenador
    write_run_info(rundir, machine="local", host=os.uname().nodename, ncores=ncores, nscribes=nscribes, seconds=round(dt), exe=str(exe),
                   started=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)))
    return 0


def post_run(rundir: Path, cfg: dict) -> Path | None:
    """Tareas tras la simulación: recorte de las salidas al subdominio pedido en `output.subdomain` ({lon, lat})."""
    sd = (cfg.get("output") or {}).get("subdomain") or {}
    if sd.get("lon") and sd.get("lat"):
        from .analysis.output import crop_outputs
        out = crop_outputs(rundir, tuple(map(float, sd["lon"])), tuple(map(float, sd["lat"])))
        log.info("salidas recortadas al subdominio en %s", out)
        return out
    return None


def local_pid(rundir: Path) -> int | None:
    """PID de mpirun si hay una simulación local en marcha en `rundir` (None si no)."""
    f = Path(rundir) / "run.pid"
    if not f.exists():
        return None
    try:
        pid = int(f.read_text().strip()); os.kill(pid, 0); return pid
    except (ValueError, ProcessLookupError, PermissionError):
        f.unlink(missing_ok=True); return None


def stop_local(rundir: Path, grace: float = 10.0) -> bool:
    """Detiene la simulación local de `rundir` (mpirun y todos sus procesos: SIGTERM al grupo, SIGKILL si no acaba)."""
    import signal
    rundir = Path(rundir); pid = local_pid(rundir)
    if pid is None:
        return False
    (rundir / "run.stop").write_text("stop\n")
    def children(ppid):
        out = subprocess.run(["ps", "-o", "pid=", "--ppid", str(ppid)], capture_output=True, text=True).stdout.split()
        return [int(c) for c in out]
    kids = children(pid)                                     # los rangos MPI van en grupos de procesos propios (prterun)
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return False
    for k in kids:
        try:
            os.kill(k, signal.SIGTERM)
        except ProcessLookupError:
            pass
    t0 = time.time()
    while time.time() - t0 < grace:
        try:
            os.kill(pid, 0); time.sleep(0.5)
        except ProcessLookupError:
            return True
    for k in [pid] + kids:
        try:
            os.kill(k, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return True


def write_run_info(rundir: Path, **info) -> Path:
    """outputs/run_info.json: cómo y dónde se ejecutó (máquina, núcleos, duración, binario, versión de SCHISMlab)."""
    import json
    rundir = Path(rundir); f = rundir / "outputs" / "run_info.json"
    f.parent.mkdir(exist_ok=True)
    data = json.loads(f.read_text()) if f.exists() else {}
    try:
        repo = Path(__file__).resolve().parents[1]
        info.setdefault("schismlab_commit", subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip())
    except Exception:   # noqa: BLE001
        pass
    data.update({k: v for k, v in info.items() if v is not None})
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return f


# todo lo que hace falta para reproducir la simulación: entradas de SCHISM, instantánea del caso, registros
_SKIP_ARCHIVE = ("outputs", "mesh_view.npz", "depth_unedited.npz", "run.pid", "run.stop")


def _copy_file(src: Path, dst: Path) -> None:
    """Copia solo el contenido: en discos de Windows montados en WSL (/mnt/c, /mnt/d) un usuario que no es el dueño
    no puede cambiar permisos ni fechas, y shutil.copy2 falla con «Operation not permitted»."""
    shutil.copyfile(src, dst)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def _copy_tree(src: Path, dst: Path) -> None:
    """Copia una carpeta solo con el contenido (sin permisos ni fechas, ver _copy_file)."""
    for f in sorted(Path(src).rglob("*")):
        t = Path(dst) / f.relative_to(src)
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
        else:
            t.parent.mkdir(parents=True, exist_ok=True); _copy_file(f, t)


def _move_dir(src: Path, dst: Path) -> None:
    """Mueve una carpeta: renombrar y, si el sistema no deja (Dropbox, ficheros aún abiertos, /mnt/d), copiar y borrar."""
    try:
        os.rename(src, dst); return
    except OSError as ex:
        log.info("no se pudo renombrar %s (%s): se copia", src.name, ex)
    _copy_tree(src, dst)
    shutil.rmtree(src, ignore_errors=True)


def archive_outputs(rundir: Path) -> Path | None:
    """Si outputs/ tiene resultados, los mueve a outputs_<fecha de la simulación>/ junto con una copia de todas las
    entradas (malla, vgrid, param.nml, bctides, hotstart, .gr3, .th, sflux/, caso.yaml, registros): la carpeta es
    autocontenida y permite reproducir o volver a analizar la simulación aunque el caso cambie después.

    Nunca impide lanzar la simulación nueva: si algo no se puede archivar, se avisa y outputs/ se vacía."""
    rundir = Path(rundir); out = rundir / "outputs"
    files = list(out.glob("out2d_*.nc")) if out.exists() else []
    if not files:
        return None
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(max(f.stat().st_mtime for f in files)))
    dst = rundir / f"outputs_{stamp}"
    k = 1
    while dst.exists():
        k += 1; dst = rundir / f"outputs_{stamp}_{k}"
    problems = []
    try:
        _move_dir(out, dst)
    except OSError as ex:
        problems.append(f"outputs: {ex}")
    for f in rundir.iterdir():
        if f.name in _SKIP_ARCHIVE or f.name.startswith("outputs") or f.suffix in (".mp4",):
            continue
        try:
            (_copy_tree if f.is_dir() else _copy_file)(f, dst / f.name)      # entradas: malla, sflux/, .th, param.nml...
        except OSError as ex:
            problems.append(f"{f.name}: {ex}")
    crop = rundir / "outputs_recorte"
    if crop.exists():
        try:
            _move_dir(crop, dst / "recorte")
        except OSError as ex:
            problems.append(f"recorte: {ex}")
    if problems:
        log.warning("no se pudo archivar del todo la simulación anterior en %s (%s); se sigue con la nueva", dst.name, "; ".join(problems)[:300])
    if out.exists():                                     # lo que no se pudo mover: fuera, para no mezclar simulaciones
        shutil.rmtree(out, ignore_errors=True)
    log.info("simulación anterior archivada en %s", dst)
    return dst


def run_info(d: Path) -> dict:
    import json
    f = Path(d) / "run_info.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except (OSError, ValueError):
        return {}


def dir_size(d: Path) -> int:
    return sum(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())


def list_runs(rundir: Path) -> list[dict]:
    """Simulaciones disponibles del caso: la actual (outputs/) y las archivadas (outputs_<fecha>/), más recientes primero.
    Cada una con: path, current, when, stacks, info (run_info.json), size (bytes) y reproducible (malla + caso.yaml)."""
    rundir = Path(rundir); runs = []
    for d in [rundir / "outputs"] + sorted(rundir.glob("outputs_*")):
        if d.name == "outputs_recorte" or not d.is_dir():
            continue
        files = list(d.glob("out2d_*.nc"))
        if not files:
            continue
        mt = max(f.stat().st_mtime for f in files)
        current = d.name == "outputs"
        base = rundir if current else d
        runs.append(dict(path=d, current=current, when=time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)), mtime=mt, stacks=len(files),
                         info=run_info(d), size=dir_size(d) + (0 if current else 0),
                         reproducible=(base / "hgrid.gr3").exists() and (base / "caso.yaml").exists() and (base / "param.nml").exists()))
    runs.sort(key=lambda r: (not r["current"], -r["mtime"]))
    return runs


def case_from_run(run_dir: Path, name: str, folder: Path, workdir_root: Path | None = None) -> Path:
    """Crea un caso nuevo (YAML en `folder`) a partir de una simulación archivada: usa su caso.yaml y copia sus entradas
    (malla, forzamientos, parámetros) a la carpeta de trabajo nueva, de modo que el setup no tenga que regenerar nada."""
    import re, yaml
    run_dir = Path(run_dir); folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()) or "caso"
    src_yaml = run_dir / "caso.yaml"
    if not src_yaml.exists():
        raise FileNotFoundError("la simulación no guardó caso.yaml (es anterior a esta versión): no se puede reproducir automáticamente")
    cfg = yaml.safe_load(src_yaml.read_text(encoding="utf-8")) or {}
    cfg["name"] = name; cfg.pop("workdir", None); cfg.get("mesh", {}).pop("rebuild", None)
    if workdir_root is not None:
        cfg["workdir"] = str(Path(workdir_root) / name)
    p = folder / f"{name}.yaml"
    if p.exists():
        raise FileExistsError(f"ya existe el caso {p}")
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    wd = (Path(workdir_root) / name) if workdir_root is not None else folder / name; wd.mkdir(parents=True, exist_ok=True)
    for f in run_dir.iterdir():
        if f.name == "recorte" or f.suffix == ".nc" and (f.name.startswith("out2d_") or "_" in f.stem and f.stem.rsplit("_", 1)[-1].isdigit()):
            continue                                                     # salidas: no son entradas
        if f.name in ("run_info.json", "mirror.out", "fatal.error", "jobid"):
            continue
        if f.is_dir():
            shutil.copytree(f, wd / f.name, dirs_exist_ok=True)
        else:
            shutil.copy2(f, wd / f.name)
    return p
