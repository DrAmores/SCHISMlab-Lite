"""Funciones de SCHISMlab Pro que usa un caso (YAML). SCHISMlab Lite las rechaza con un mensaje claro antes de
preparar los ficheros, en vez de fallar a mitad de camino."""
from __future__ import annotations

_NAMES = {
    "mesh_real": ("malla con costa real", "real-coastline mesh"),
    "mesh_lonlat": ("malla en lon/lat", "lon/lat mesh"),
    "inundation": ("inundación", "flooding"),
    "era5": ("atmósfera real (ERA5 o ficheros propios)", "real atmosphere (ERA5 or own files)"),
    "pressure": ("perturbación de presión (meteotsunami)", "pressure disturbance (meteotsunami)"),
    "rain": ("lluvia sobre la malla", "rain over the mesh"),
    "rivers": ("ríos", "rivers"),
    "bc3d": ("contornos 3D o anidamiento", "3D boundaries or nesting"),
    "tides_global": ("mareas globales (GOT, FES)", "global tides (GOT, FES)"),
    "ic_cmems": ("condiciones iniciales de Copernicus", "Copernicus initial conditions"),
    "waves": ("oleaje (WWM)", "waves (WWM)"),
    "landcover": ("rugosidad por usos del suelo", "land-cover roughness"),
    "slr": ("subida del nivel del mar", "sea-level rise"),
    "runs": ("proyecto con varias simulaciones", "project with several simulations"),
}


def _uses_global_tides(bc) -> bool:
    for b in (bc if isinstance(bc, list) else [bc]):
        e = (b or {}).get("elevation") if isinstance(b, dict) else None
        if isinstance(e, dict) and isinstance(e.get("tides"), dict) and e["tides"].get("source", "idealized") != "idealized":
            return True
    return False


def pro_feature_keys(cfg: dict) -> list[str]:
    from .edition import default_generator
    m = cfg.get("mesh") or {}
    fc = cfg.get("forcing") or {}
    bc = cfg.get("boundaries") or {}
    ic = cfg.get("initial") or {}
    out = []
    if m.get("generator", default_generator()) != "idealized":
        out.append("mesh_real")
    elif "lon" in m and "lat" in m:
        out.append("mesh_lonlat")
    if m.get("inundation"):
        out.append("inundation")
    if fc.get("atmosphere"):
        out.append("era5")
    if fc.get("pressure_disturbance"):
        out.append("pressure")
    if fc.get("rivers"):
        out.append("rivers")
    if fc.get("rain"):
        out.append("rain")
    if isinstance(bc, dict) and bc.get("source") not in (None, "none", {}, False):
        out.append("bc3d")
    if _uses_global_tides(bc):
        out.append("tides_global")
    src = ic.get("source")
    name = src.get("name", "") if isinstance(src, dict) else str(src or "")
    if name.startswith(("medsea", "global", "cmems")):     # mismo criterio que schismlab.setup
        out.append("ic_cmems")
    if (cfg.get("waves") or {}).get("enabled"):
        out.append("waves")
    if (cfg.get("friction") or {}).get("landcover"):
        out.append("landcover")
    if float((cfg.get("scenario") or {}).get("sea_level_rise", 0) or 0):
        out.append("slr")
    if cfg.get("runs"):
        out.append("runs")
    return out


def pro_features(cfg: dict, lang: str = "es") -> list[str]:
    """Nombres legibles de las funciones de SCHISMlab Pro que usa el caso (vacío si es un caso de SCHISMlab Lite)."""
    k = 0 if lang == "es" else 1
    return [_NAMES[f][k] for f in pro_feature_keys(cfg)]


def require_lite_compatible(cfg: dict) -> None:
    """En SCHISMlab Lite, ProRequired si el caso usa funciones de Pro."""
    from .edition import is_pro, ProRequired
    if is_pro():
        return
    used = pro_features(cfg)
    if used:
        raise ProRequired(", ".join(used))
