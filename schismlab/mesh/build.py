"""Construye la malla de un caso a partir de su seccion `mesh` del YAML.

La base hace la malla idealizada (rectángulo con fondo analítico); los generadores con costa real (OCSMesh,
OceanMesh2D, malla desde fichero), las capas de batimetría y la inundación son de SCHISMlab Pro.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import numpy as np
from ..case import Case
from ..edition import is_pro, pro, ProRequired, default_generator
from ..io.gr3 import Mesh, write_gr3
from .analytic import analytic_depth
from .idealized import rectangular_basin
from .quality import mesh_quality

log = logging.getLogger(__name__)

def build_mesh(case: Case, outdir: Path | None = None, plot: bool = True) -> Mesh:
    cfg = case_files_absolute(case.section("mesh"), case.dir)
    outdir = Path(outdir or case.workdir); outdir.mkdir(parents=True, exist_ok=True)
    gen = cfg.get("generator", default_generator())
    if gen == "idealized":
        if "lon" in cfg and "lat" in cfg and not is_pro():
            raise ProRequired("malla idealizada en lon/lat / idealised lon/lat mesh")
        mesh = _idealized(cfg, case.name)
        geographic = "lon" in cfg and "lat" in cfg
    elif gen in ("ocsmesh", "oceanmesh2d", "file"):
        real = pro("mesh.realistic", f"generador de malla {gen} / mesh generator {gen}")
        mesh, geographic = real.generate(gen, cfg, case, outdir)
    else:
        raise ValueError(f"generador de malla desconocido: {gen}")
    if gen != "idealized":
        mesh = real.after_generate(gen, cfg, mesh, outdir)   # nodos sobre curvas de nivel, tipos de contorno, capas, inundación
    elif cfg.get("open_sides"):
        # lados abiertos en el orden en que rectangular_basin crea los contornos (S, E, N, W); tipo por lado: forced | radiation
        st = {str(k).upper(): v for k, v in (cfg.get("side_types") or {}).items()}
        opened = [s.upper() for s in cfg["open_sides"]]
        kinds = [st.get(s, "forced") for s in ("S", "E", "N", "W") if s in opened]
        (outdir / "open_boundary_types.json").write_text(json.dumps(kinds))
        if any(k != "forced" for k in kinds):
            log.info("contornos abiertos: %s", ", ".join(f"{s}: {st.get(s, 'forced')}" for s in ("S", "E", "N", "W") if s in opened))
    else:
        (outdir / "open_boundary_types.json").unlink(missing_ok=True)
    (outdir / "slr_applied").unlink(missing_ok=True)      # malla nueva: sin escenario de nivel del mar aplicado
    from .edits import edits_cfg, apply_edits, save_unedited
    edits = edits_cfg(cfg)
    save_unedited(outdir, mesh.depth.copy(), edits)       # batimetria original, para poder cambiar los retoques sin remallar
    apply_edits(mesh, edits)                              # retoques locales de batimetria (mesh.bathymetry_edits)
    write_gr3(outdir / "hgrid.gr3", mesh)
    if geographic:
        write_gr3(outdir / "hgrid.ll", mesh)          # SCHISM con ics=2 usa hgrid.ll para lon/lat
    q = mesh_quality(mesh)
    (outdir / "mesh_quality.json").write_text(json.dumps(q, indent=2))
    log.info("malla: %d nodos, %d elementos; aristas %.0f-%.0f m; angulo min %.1f",
             q["nodes"], q["elements"], q["edge_min_m"], q["edge_max_m"], q["min_angle_deg"])
    if plot:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from ..plot import plot_mesh
        plot_mesh(mesh); plt.savefig(outdir / "mesh.png", dpi=120); plt.close()
    return mesh


def _depth_callable(b, cfg: dict | None = None):
    """`bathymetry` idealizada: numero (fondo plano) o {kind: ..., params}; {kind: expression, formula: "..."} evalúa una
    fórmula numpy. En todos los tipos x, y van en m desde la esquina SW, también si el dominio está en lon/lat (las
    expresiones reciben además lon, lat en grados)."""
    if isinstance(b, (int, float)):
        return analytic_depth("flat", h=float(b))
    if not isinstance(b, dict):
        raise ValueError("mesh.bathymetry idealizada: número o {kind: flat|slope|step|channel|shelf|seamount|expression, ...}")
    b = dict(b); kind = b.pop("kind", "flat")
    if cfg and cfg.get("lon") is not None and cfg.get("lat") is not None:   # malla en grados: x, y en m desde la esquina SW
        lon, lat = cfg["lon"], cfg["lat"]
        b["origin"] = (float(lon[0]), float(lat[0]), 0.5 * (float(lat[0]) + float(lat[1])))
    return analytic_depth(kind, **b)


def _idealized(cfg: dict, name: str) -> Mesh:
    geo = "lon" in cfg and "lat" in cfg
    return rectangular_basin(Lx=float(cfg.get("Lx", 0)), Ly=float(cfg.get("Ly", 0)), dx=float(cfg["dx"]),
                             depth=_depth_callable(cfg.get("bathymetry", 50.0), cfg),
                             open_sides=tuple(cfg.get("open_sides", ())), name=name,
                             lon=tuple(map(float, cfg["lon"])) if geo else None,
                             lat=tuple(map(float, cfg["lat"])) if geo else None)


def domain_polygon(cfg: dict):
    """Poligono del dominio (shapely) si el YAML trae `polygon: [[lon, lat], ...]`; None si es un rectangulo."""
    if cfg.get("polygon"):
        from shapely.geometry import Polygon
        return Polygon([(float(p[0]), float(p[1])) for p in cfg["polygon"]])
    return None


def bbox(cfg: dict):
    """(lon, lat) del rectangulo envolvente: del YAML o del poligono."""
    poly = domain_polygon(cfg)
    if poly is not None and not ("lon" in cfg and "lat" in cfg):
        x0, y0, x1, y1 = poly.bounds
        return (x0, x1), (y0, y1)
    return tuple(map(float, cfg["lon"])), tuple(map(float, cfg["lat"]))


def case_files_absolute(cfg: dict, base: Path) -> dict:
    """Copia de mesh con las rutas relativas de las capas de batimetría y del DEM de inundación resueltas desde la
    carpeta del YAML (si existen allí), y no desde la carpeta en la que se ejecuta (en el clúster no coinciden)."""
    import copy
    cfg = copy.deepcopy(cfg); base = Path(base)
    def fix(v):
        if isinstance(v, str) and v.strip() and not Path(v).expanduser().is_absolute() and (base / v).exists():
            return str((base / v).resolve())
        return v
    b = cfg.get("bathymetry")
    if isinstance(b, list):
        cfg["bathymetry"] = [dict(l, source=fix(l.get("source"))) if isinstance(l, dict) else fix(l) for l in b]
    elif isinstance(b, str):
        cfg["bathymetry"] = fix(b)
    if isinstance(cfg.get("inundation"), dict) and "dem" in cfg["inundation"]:
        cfg["inundation"] = dict(cfg["inundation"], dem=fix(cfg["inundation"]["dem"]))
    return cfg


def bathymetry_layers(cfg: dict) -> tuple:
    """(fuente base, capas adicionales) a partir de mesh.bathymetry: cadena, o lista [{source, region, ...}, ...]."""
    b = cfg.get("bathymetry", "gebco2021")
    if isinstance(b, list):
        base = b[0]["source"] if isinstance(b[0], dict) else b[0]
        return base, [l for l in b[1:] if isinstance(l, dict)]
    return b, []


def build_mesh_from_yaml(case_path: str) -> None:
    """Punto de entrada para el proceso de mallado de la interfaz (se puede detener): construye la malla del caso."""
    from ..case import Case
    build_mesh(Case(case_path))
