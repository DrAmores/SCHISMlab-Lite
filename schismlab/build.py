"""Compilaciones de SCHISM por módulos: catálogo de módulos, nombre de la variante y registro de ejecutables.

Cada combinación de módulos se compila como un ejecutable distinto en ~/.schismlab/bin/pschism_<variante> y se
anota en ~/.schismlab/bin/variants.json (módulos, fecha). `hydro` y `wwm` son los nombres clásicos.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))
REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Module:
    key: str            # nombre corto (en el YAML y en el nombre de la variante)
    cmake: str          # opción de CMake de SCHISM
    es: str
    en: str
    namelist: str | None = None    # fichero .nml adicional que exige el módulo (plantilla en schismlab/templates)
    stable: bool = True            # probado en SCHISMlab


# Orden canónico (fija el nombre de la variante). Solo los módulos que no necesitan librerías externas.
MODULES: list[Module] = [
    Module("prec_evap", "PREC_EVAP", "Precipitación y evaporación (balance de agua dulce con ERA5)",
           "Precipitation and evaporation (freshwater balance with ERA5)"),
    Module("wwm", "USE_WWM", "Oleaje acoplado (WWM III)", "Coupled waves (WWM III)", namelist="wwminput.nml"),
    Module("sed", "USE_SED", "Sedimentos 3D (SED3D)", "3D sediment transport (SED3D)", namelist="sediment.nml", stable=False),
    Module("sed2d", "USE_SED2D", "Sedimentos 2D (fondo móvil)", "2D sediment transport (morphodynamics)", stable=False),
    Module("ice", "USE_ICE", "Hielo marino", "Sea ice", namelist="ice.nml", stable=False),
    Module("gen", "USE_GEN", "Trazadores genéricos (pasivos)", "Generic passive tracers", stable=False),
    Module("age", "USE_AGE", "Edad del agua", "Water age tracers", stable=False),
    Module("ha", "USE_HA", "Análisis armónico en línea (harm.in)", "On-line harmonic analysis (harm.in)", stable=False),
    Module("analysis", "USE_ANALYSIS", "Salidas de análisis (balances de momento)", "Analysis outputs (momentum balances)", stable=False),
    Module("icm", "USE_ICM", "Biogeoquímica ICM", "ICM biogeochemistry", namelist="icm.nml", stable=False),
    Module("cosine", "USE_COSINE", "Biogeoquímica CoSiNE", "CoSiNE biogeochemistry", namelist="cosine.nml", stable=False),
    Module("marsh", "USE_MARSH", "Marismas", "Marsh module", stable=False),
]
BY_KEY = {m.key: m for m in MODULES}
LEGACY = {"hydro": ["prec_evap"], "wwm": ["prec_evap", "wwm"]}     # nombres clásicos de las variantes


def normalize(modules) -> list[str]:
    """Lista de módulos en orden canónico (acepta claves cortas o nombres de CMake)."""
    keys = set()
    for m in modules or []:
        m = str(m).strip()
        if m in BY_KEY:
            keys.add(m)
        else:
            hit = next((x.key for x in MODULES if x.cmake == m.upper()), None)
            if hit is None:
                raise KeyError(f"módulo desconocido: {m} (válidos: {', '.join(BY_KEY)})")
            keys.add(hit)
    return [m.key for m in MODULES if m.key in keys]


def variant_name(modules) -> str:
    """hydro | wwm | combinación de claves unida por '+' (p.ej. wwm+sed, hydro+ice, wwm-noprec)."""
    keys = normalize(modules)
    for name, mods in LEGACY.items():
        if keys == mods:
            return name
    rest = [k for k in keys if k != "prec_evap"]
    base = "wwm" if "wwm" in rest else "hydro"
    rest = [k for k in rest if k != "wwm"]
    name = "+".join([base] + rest)
    return name if "prec_evap" in keys else name + "-noprec"


def registry_path() -> Path:
    return HOME / "bin" / "variants.json"


def installed() -> dict[str, dict]:
    """Variantes compiladas: nombre -> {modules, exe, built}. Incluye las clásicas aunque no estén en el registro."""
    reg = {}
    if registry_path().exists():
        try:
            reg = json.loads(registry_path().read_text())
        except json.JSONDecodeError:
            reg = {}
    out = {}
    for exe in sorted((HOME / "bin").glob("pschism_*")) if (HOME / "bin").exists() else []:
        name = exe.name[len("pschism_"):]
        info = reg.get(name, {})
        mods = info.get("modules") or LEGACY.get(name) or _guess_modules(name)
        out[name] = {"modules": mods, "exe": str(exe), "built": info.get("built") or time.strftime("%Y-%m-%d", time.localtime(exe.stat().st_mtime))}
    return out


def _guess_modules(name: str) -> list[str]:
    noprec = name.endswith("-noprec"); name = name.removesuffix("-noprec")
    keys = [k for k in name.split("+") if k in BY_KEY]
    if not noprec:
        keys.append("prec_evap")
    return normalize(keys)


def register(name: str, modules) -> None:
    reg = json.loads(registry_path().read_text()) if registry_path().exists() else {}
    reg[name] = {"modules": normalize(modules), "built": time.strftime("%Y-%m-%d %H:%M")}
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    registry_path().write_text(json.dumps(reg, indent=1))


def build(modules, log=None) -> str:
    """Compila la variante con esos módulos (install/build_schism.sh) y la registra. Devuelve el nombre."""
    keys = normalize(modules); name = variant_name(keys)
    env = dict(os.environ, SCHISM_MODULES=" ".join(BY_KEY[k].cmake for k in keys))
    cmd = ["bash", str(REPO / "install" / "build_schism.sh"), name]
    if not os.environ.get("CONDA_PREFIX"):          # fuera de pixi: entrar en el entorno
        cmd = ["pixi", "run", "--manifest-path", str(REPO / "pixi.toml")] + cmd
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if log is not None:
        log(p.stdout[-4000:] + p.stderr[-4000:])
    if p.returncode != 0:
        raise RuntimeError("error de compilación:\n" + (p.stdout + p.stderr)[-3000:])
    register(name, keys)
    build_wave_models(log)
    return name


def wave_models() -> dict:
    """Estado de los modelos de run-up: {'swash': ruta|None, 'xbeach': ruta|None}."""
    b = HOME / "bin"
    return {"swash": b / "swash.exe" if (b / "swash.exe").exists() else None, "xbeach": b / "xbeach" if (b / "xbeach").exists() else None}


def build_wave_models(log=None) -> dict:
    """Compila SWASH y XBeach (install/build_wave_models.sh) si faltan; nunca falla (XBeach es opcional)."""
    cmd = ["bash", str(REPO / "install" / "build_wave_models.sh")]
    if not os.environ.get("CONDA_PREFIX"):
        cmd = ["pixi", "run", "--manifest-path", str(REPO / "pixi.toml")] + cmd
    p = subprocess.run(cmd, capture_output=True, text=True)
    if log is not None:
        log(p.stdout[-3000:] + p.stderr[-3000:])
    return wave_models()


def required_namelists(modules) -> list[str]:
    """Ficheros .nml adicionales (además de param.nml) que exige esa combinación de módulos."""
    return [BY_KEY[k].namelist for k in normalize(modules) if BY_KEY[k].namelist]


def implied_modules(cfg: dict) -> list[str]:
    """Modulos que exige la configuracion del caso (oleaje -> wwm, precipitacion -> prec_evap)."""
    mods = []
    if (cfg.get("waves") or {}).get("enabled"):
        mods.append("wwm")
    atm = (cfg.get("forcing") or {}).get("atmosphere") or {}
    if atm.get("precipitation") or ((cfg.get("physics") or {}).get("baroclinic") and atm.get("heat")):
        mods.append("prec_evap")
    return normalize(mods)


def effective_build(cfg: dict) -> tuple[str, list[str], bool]:
    """(variante a usar, sus modulos, True si existe compilada).

    Si el caso fija `build`, se usa esa compilacion mas lo que exija la configuracion; si no, la minima
    que cubre lo exigido (hydro, o wwm con oleaje). Si la variante exacta no esta compilada pero hay otra
    instalada que contiene todos los modulos necesarios, se elige esa.
    """
    need = set(implied_modules(cfg)) | {"prec_evap"}
    reg = installed()
    build = cfg.get("build")
    if build:
        info = reg.get(build)
        mods = set(info["modules"] if info else (LEGACY.get(build) or _guess_modules(build)))
        if need <= mods:
            return build, normalize(mods), build in reg
        need |= mods
    name = variant_name(need)
    if name in reg:
        return name, normalize(need), True
    for other, info in reg.items():                      # otra compilacion que contenga lo necesario
        if need <= set(info["modules"]):
            return other, normalize(info["modules"]), True
    return name, normalize(need), False
