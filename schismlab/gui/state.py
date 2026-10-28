"""Estado de la interfaz: caso actual, galeria de casos, estado del flujo, miniaturas."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
import yaml

HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))
REPO = Path(__file__).resolve().parents[2]
USER_CASES = HOME / "cases"
THEMES = {  # caso docente -> tema de los apuntes
    "ekman": "Tema 4 · Capa de Ekman", "wbc": "Tema 4 · Sverdrup y Stommel", "tsunami": "Tema 3 · Ondas largas",
    "ajuste_geostrofico": "Tema 3 · Ajuste geostrófico", "estabilidad": "Tema 2 · Estabilidad estática",
    "doble_difusion": "Tema 2 · Doble difusión", "afloramiento": "Tema 4 · Afloramiento costero",
    "kelvin": "Tema 3 · Ondas de Kelvin", "munk": "Tema 4 · Stommel frente a Munk", "tsunami_boumerdes": "Tema 3 · Tsunami real", "canal_talud": "Dominio idealizado",
}


# caso -> guion de practica en la documentacion (docs/practicas; en la GUI se sirve en /docs/practicas/<caso>/)
PRACTICAS = {k: f"practicas/{k}.md" for k in ("ekman", "wbc", "munk", "kelvin", "tsunami", "tsunami_boumerdes", "ajuste_geostrofico",
                                                "estabilidad", "doble_difusion", "afloramiento", "canal_talud")}


@dataclass
class CaseInfo:
    path: Path
    name: str
    title: str
    group: str          # mine | tests
    theme: str = ""

    @property
    def workdir(self) -> Path:
        from ..case import Case
        return Case(self.path).workdir

    def valid(self) -> bool:
        """False si el YAML del caso no se puede leer (editado a mano con un error de sintaxis)."""
        try:
            load_cfg(self.path); return True
        except (yaml.YAMLError, OSError):
            return False

    def thumbnail(self) -> Path | None:
        try:
            wd = self.workdir
        except (yaml.YAMLError, OSError):
            return None
        for cand in (wd / "mesh.png", REPO / "docs" / "img" / "cases" / f"{self.name}.png"):
            if cand.exists():
                return cand
        return None

    def status(self) -> dict:
        try:
            wd = self.workdir
        except (yaml.YAMLError, OSError):                      # YAML inválido: sin estado (la página lo avisa)
            return {"mesh": False, "setup": False, "run": False}
        return {"mesh": (wd / "hgrid.gr3").exists(), "setup": (wd / "param.nml").exists(),
                "run": bool(list((wd / "outputs").glob("out2d_*.nc"))) if (wd / "outputs").exists() else False}


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") and "schismlab" not in line.lower():
            return line.lstrip("# ").strip()
        if not line.startswith("#"):
            break
    return path.stem


def gallery() -> list[CaseInfo]:
    out = []
    # "mine": los casos del usuario; "tests": los mínimos de comprobación de la instalación (los únicos que trae el
    # repositorio: las prácticas las construyen los estudiantes). Si existen carpetas antiguas de ejemplos, se ignoran.
    for group, d in (("mine", USER_CASES), ("tests", REPO / "cases" / "tests")):
        if d.exists():
            for p in sorted(d.glob("*.yaml")):
                out.append(CaseInfo(p, p.stem, _title(p), group, THEMES.get(p.stem, "")))
    return out


def workdir_root(root: str | Path | None) -> Path | None:
    """Carpeta elegida por el usuario para los ficheros de la simulación: absoluta, creada y comprobada (escritura).
    None (o la carpeta de «Mis casos») significa el sitio por defecto, junto al YAML."""
    if root in (None, ""):
        return None
    r = Path(str(root)).expanduser()
    if not r.is_absolute():
        raise ValueError(f"la carpeta de la simulación debe ser una ruta absoluta: {root}")
    r = r.resolve()
    if r == USER_CASES.resolve():
        return None
    r.mkdir(parents=True, exist_ok=True)
    try:
        probe = r / ".schismlab_escritura"; probe.write_text("ok"); probe.unlink()
    except OSError as ex:
        raise PermissionError(f"no se puede escribir en {r}: {ex}") from None
    return r


def _set_workdir(cfg: dict, name: str, root: Path | None) -> dict:
    """Fija cfg['workdir'] = root/name (absoluta) o la quita (carpeta por defecto junto al YAML). Nunca se hereda la
    del caso de origen: dos casos no deben compartir carpeta de trabajo."""
    cfg.pop("workdir", None)
    if root is not None:
        cfg["workdir"] = str(Path(root) / name)
    return cfg


def copy_case(src: Path, name: str, folder: Path | None = None, workdir_root: Path | None = None) -> Path:
    """Duplica un caso (su YAML, con el nombre nuevo) en la carpeta de casos del usuario; `workdir_root` es la carpeta
    donde irán los ficheros de la simulación del caso nuevo (por defecto, junto al YAML)."""
    folder = Path(folder or USER_CASES); folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()) or "caso"
    p = folder / f"{name}.yaml"
    if not p.exists():
        c = load_cfg(src); c["name"] = name
        c.get("mesh", {}).pop("rebuild", None)
        save_cfg(p, _set_workdir(c, name, workdir_root))
    return p


TRASH = HOME / "papelera"


def delete_case(path: Path) -> Path:
    """Mueve un caso del usuario (su YAML y su carpeta de trabajo) a ~/.schismlab/papelera/<fecha>_<nombre>/.

    Solo casos de «Mis casos»; los de ejemplo y los docentes no se borran. Se niega si hay una simulación en marcha
    (salida escrita hace menos de 2 minutos). Devuelve la carpeta de la papelera (para recuperarlo, se devuelve a su sitio).
    """
    import shutil, time
    from ..case import Case
    path = Path(path).resolve()
    if path.parent != USER_CASES.resolve():
        raise PermissionError("solo se pueden borrar los casos de «Mis casos»")
    wd = Case(path).workdir.resolve()
    recent = [f for f in (wd / "outputs").glob("*") if f.is_file() and time.time() - f.stat().st_mtime < 120] if (wd / "outputs").exists() else []
    if recent:
        raise RuntimeError("el caso tiene una simulación en marcha; espera a que termine")
    dest = TRASH / f"{time.strftime('%Y%m%d-%H%M%S')}_{path.stem}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest / path.name)
    # la carpeta de trabajo: dentro de «Mis casos» o la elegida por el usuario (workdir), siempre que sea la carpeta
    # propia del caso (se llama como él) y no una carpeta general (home, Mis casos o un antecesor de ellas)
    protected = {Path.home().resolve(), HOME.resolve(), USER_CASES.resolve()}
    own = wd.is_dir() and wd.name == path.stem and wd not in protected and not any(wd in q.parents for q in protected)
    if own and (USER_CASES.resolve() in wd.parents or "workdir" in (load_cfg(dest / path.name) or {})):
        shutil.move(str(wd), dest / wd.name)
    return dest


def load_cfg(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def save_cfg(path: Path, cfg: dict) -> None:
    Path(path).write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def new_case(name: str, folder: Path | None = None, workdir_root: Path | None = None) -> Path:
    """Caso nuevo: YAML en «Mis casos» (o `folder`); los ficheros de la simulación en `workdir_root`/<name> si se da."""
    folder = Path(folder or USER_CASES); folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()) or "caso"
    p = folder / f"{name}.yaml"
    if not p.exists():
        from ..edition import is_pro
        mesh = ({"generator": "ocsmesh", "polygon": [[0.5, 37.8], [5.0, 37.8], [5.0, 41.0], [0.5, 41.0]],
                 "bathymetry": "gebco2021", "resolution": {"min": 1500, "max": 10000, "max_nearshore": 4000},
                 "open_boundaries": "bbox", "min_depth": 3} if is_pro() else
                {"generator": "idealized", "Lx": 100000.0, "Ly": 100000.0, "dx": 2500.0, "bathymetry": 200.0, "open_sides": []})
        extra = {} if is_pro() else {"reference": {"lon0": 0.0, "lat0": 40.5}}   # Lite: cuenca en metros, plano f a 40.5° N
        save_cfg(p, _set_workdir({"name": name, "mesh": mesh, **extra,
                     "vertical": {"type": "2d"}, "time": {"start": "2020-01-01", "days": 2, "dt": 60, "ramp_days": 0.5},
                     "physics": {"baroclinic": False}, "initial": {"elevation": 0, "temperature": 20, "salinity": 36},
                     "forcing": {}, "boundaries": {"elevation": "none"},
                     "output": {"interval_minutes": 60, "variables": ["elevation", "depthAverageVel"]}}, name, workdir_root))
    return p


def run_progress(workdir: Path) -> tuple[int, int]:
    """(paso actual, pasos totales) leyendo outputs/mirror.out y param.nml."""
    m = workdir / "outputs" / "mirror.out"; p = workdir / "param.nml"
    if not (m.exists() and p.exists()):
        return 0, 1
    try:
        txt = p.read_text()
        g = lambda k: float(re.search(rf"^\s*{k}\s*=\s*([\d.eE+-]+)", txt, re.M).group(1))
        total = int(round(g("rnday") * 86400 / g("dt")))
        lines = [l for l in m.read_text(errors="ignore").splitlines() if "TIME STEP" in l]
        mm = re.search(r"TIME STEP=\s*(\d+)", lines[-1]) if lines else None
        step = int(mm.group(1)) if mm else 0
    except (OSError, AttributeError, ValueError, ZeroDivisionError):     # param.nml editado a mano sin rnday/dt, mirror.out raro
        return 0, 1
    return step, max(total, 1)


# ----------------------------------------------------------------------------- exportar / importar casos
EXPORT_DIR = HOME / "exportados"
_SKIP_INPUT = ("mesh_view.npz", "depth_unedited.npz", "run.pid", "run.stop", "jobid", "run.log")


def export_case(path: Path, include_inputs: bool = True, include_outputs: bool = False, out: Path | None = None) -> Path:
    """Empaqueta un caso en un .zip: caso.yaml (configuración) y, opcionalmente, su carpeta de trabajo (malla,
    forzamientos y ficheros de SCHISM) y sus resultados (outputs/). Otro SCHISMlab lo carga con import_case."""
    import json, time, zipfile
    from ..case import Case
    from .. import __version__
    case = Case(path); wd = case.workdir
    out = Path(out or EXPORT_DIR / f"{case.name}.schismlab.zip"); out.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(case.cfg); cfg.pop("workdir", None)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("caso.yaml", yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        z.writestr("manifest.json", json.dumps({"schismlab": __version__, "name": case.name, "exported": time.strftime("%Y-%m-%d %H:%M"),
                                               "inputs": include_inputs, "outputs": include_outputs}, ensure_ascii=False))
        if wd.exists() and (include_inputs or include_outputs):
            for f in sorted(wd.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(wd)
                top = rel.parts[0]
                is_out = top == "outputs" or top.startswith("outputs_")
                if (is_out and not include_outputs) or (not is_out and not include_inputs) or top in _SKIP_INPUT or f.suffix == ".mp4":
                    continue
                z.write(f, f"workdir/{rel.as_posix()}")
    return out


def import_case(zip_path: Path, name: str | None = None, folder: Path | None = None, workdir_root: Path | None = None) -> Path:
    """Carga un caso exportado: crea <name>.yaml en «Mis casos» y su carpeta de trabajo (en `workdir_root` si se da) con
    lo que traiga el paquete. Si ya existe un caso con ese nombre, añade un sufijo numérico."""
    import re, zipfile
    folder = Path(folder or USER_CASES); folder.mkdir(parents=True, exist_ok=True)
    wroot = Path(workdir_root) if workdir_root is not None else folder
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "caso.yaml" not in names:
            raise ValueError("el paquete no es un caso de SCHISMlab (falta caso.yaml)")
        cfg = yaml.safe_load(z.read("caso.yaml").decode("utf-8")) or {}
        base = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or cfg.get("name") or Path(zip_path).stem.replace(".schismlab", "")).strip()) or "caso"
        nm, k = base, 1
        while (folder / f"{nm}.yaml").exists() or (folder / nm).exists() or (wroot / nm).exists():
            k += 1; nm = f"{base}_{k}"
        cfg["name"] = nm
        p = folder / f"{nm}.yaml"; save_cfg(p, _set_workdir(cfg, nm, workdir_root))
        wd = wroot / nm
        for member in names:
            if not member.startswith("workdir/") or member.endswith("/"):
                continue
            rel = Path(member[len("workdir/"):])
            if ".." in rel.parts or rel.is_absolute():
                continue                                                 # seguridad: nada fuera de la carpeta
            dst = wd / rel; dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(member))
    return p
