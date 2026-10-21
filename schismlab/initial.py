"""Condiciones iniciales analíticas: marco de coordenadas de las expresiones, recetas (frente, capas, gaussiana, ...)
que se traducen a expresiones numpy del YAML, y una densidad aproximada para previsualizar.

Las recetas son la forma "interactiva" de definir el estado inicial en la interfaz; el YAML sigue guardando la
expresión resultante en `initial.temperature`, `initial.salinity`, ... (el setup no necesita saber de recetas) y la
receta en `initial.recipe` para poder volver a editarla con los mismos controles.
Posiciones dentro de la receta: fracción 0-1 del dominio (x de oeste a este, y de sur a norte); anchuras en km.
"""
from __future__ import annotations
import numpy as np
from .io.gr3 import Mesh
from .mesh.idealized import R_EARTH
from .expressions import evaluate, is_expression

VARIABLES = ("elevation", "temperature", "salinity", "u", "v")
MODES = ("constant", "front", "layers", "toplayer", "gauss", "gradient", "expr")


def is_geographic(cfg: dict) -> bool:
    mc = cfg.get("mesh", {}) or {}
    from .edition import default_generator
    return mc.get("generator", default_generator()) != "idealized" or ("lon" in mc and "lat" in mc)


def domain_frame(m: Mesh, cfg: dict) -> dict:
    """Coordenadas que ven las expresiones del YAML: x, y en metros desde la esquina SO; lon, lat en grados.

    Dominio geográfico: x, y se miden sobre la esfera desde (lon_min, lat_min). Cartesiano: lon, lat se derivan de la
    referencia (lon0, lat0). Es la misma convención para el setup y para la previsualización de la interfaz.
    """
    if is_geographic(cfg):
        lon, lat = m.x, m.y
        lat0 = np.deg2rad(lat.mean())
        xm = np.deg2rad(m.x - m.x.min()) * R_EARTH * np.cos(lat0)
        ym = np.deg2rad(m.y - m.y.min()) * R_EARTH
    else:
        ref = cfg.get("reference", {"lon0": 0.0, "lat0": 45.0}) or {}
        lon0, lat0 = float(ref.get("lon0", 0.0)), float(ref.get("lat0", 45.0))
        xm, ym = m.x, m.y
        lon = lon0 + np.rad2deg(m.x / (R_EARTH * np.cos(np.deg2rad(lat0))))
        lat = lat0 + np.rad2deg(m.y / R_EARTH)
    return dict(x=xm, y=ym, lon=lon, lat=lat)


def expression_vars(frame: dict, depth: np.ndarray, z: np.ndarray | None = None, t=None) -> dict:
    """Variables disponibles en las expresiones (en nodos; con z, matrices (nodo, nivel))."""
    v = dict(x=frame["x"], y=frame["y"], lon=frame["lon"], lat=frame["lat"], depth=depth, h=depth)
    if z is not None:
        v.update(z=z, **{k: v[k][:, None] + 0 * z for k in ("x", "y", "lon", "lat", "depth", "h")})
    if t is not None:
        v["t"] = t
    return v


def domain_extent(frame: dict) -> tuple[float, float]:
    """(Lx, Ly) en metros del marco de expresiones."""
    return float(np.ptp(frame["x"])), float(np.ptp(frame["y"]))


# ----------------------------------------------------------------------------- recetas -> expresiones
def _f(v) -> str:
    return f"{float(v):g}"


def recipe_expression(r: dict | None, Lx: float, Ly: float):
    """Expresión numpy (cadena) o número de la receta `r` en un dominio de Lx x Ly metros.

    modos:
      constant: value
      front:    v1, v2, axis (x|y), pos (0-1), width_km            -> v1 al oeste/sur, v2 al este/norte (tanh)
      layers:   v_top, v_bot, depth (m), slope_m (0 = plana), axis, pos, width_km
                -> interfaz en -depth - slope_m*tanh(...): más gruesa la capa superior hacia el este/norte
      toplayer: v1, v2, v_bot, depth (m), axis, pos, width_km   -> capa superior con frente (v1 | v2) sobre v_bot
      gauss:    base, amp, cx, cy (0-1), radius_km, depth (0 = toda la columna; >0 solo por encima de -depth)
      gradient: v1, v2, axis                                        -> lineal de v1 a v2 a lo largo del eje
      expr:     expression
    """
    if not r:
        return 0.0
    mode = r.get("mode", "constant")
    axis = "x" if r.get("axis", "x") == "x" else "y"
    L = Lx if axis == "x" else Ly
    if mode == "constant":
        return float(r.get("value", 0.0))
    if mode == "expr":
        e = r.get("expression", "0")
        try:
            return float(e)
        except (TypeError, ValueError):
            return str(e)
    if mode == "front":
        v1, v2 = float(r.get("v1", 0.0)), float(r.get("v2", 0.0))
        x0, w = float(r.get("pos", 0.5)) * L, max(float(r.get("width_km", 10.0)), 1e-3) * 1e3
        return f"{_f(v1)} + {_f(v2 - v1)}*0.5*(1 + tanh(({axis} - {_f(x0)})/{_f(w)}))"
    if mode == "layers":
        vt, vb, d = float(r.get("v_top", 0.0)), float(r.get("v_bot", 0.0)), float(r.get("depth", 50.0))
        s = float(r.get("slope_m", 0.0))
        if s == 0.0:
            return f"where(z > {_f(-d)}, {_f(vt)}, {_f(vb)})"
        x0, w = float(r.get("pos", 0.5)) * L, max(float(r.get("width_km", 10.0)), 1e-3) * 1e3
        return f"where(z > {_f(-d)} - {_f(s)}*tanh(({axis} - {_f(x0)})/{_f(w)}), {_f(vt)}, {_f(vb)})"
    if mode == "toplayer":
        # capa superior (hasta -depth) con un frente: v1 a un lado, v2 al otro; capa inferior uniforme v_bot.
        # Con v2 = v_bot la capa ligera solo existe a un lado (ajuste geostrofico de Rossby).
        v1, v2, vb, d = float(r.get("v1", 0.0)), float(r.get("v2", 0.0)), float(r.get("v_bot", 0.0)), float(r.get("depth", 50.0))
        x0, w = float(r.get("pos", 0.5)) * L, max(float(r.get("width_km", 10.0)), 1e-3) * 1e3
        return f"where(z > {_f(-d)}, {_f(v1)} + {_f(v2 - v1)}*0.5*(1 + tanh(({axis} - {_f(x0)})/{_f(w)})), {_f(vb)})"
    if mode == "gauss":
        base, amp = float(r.get("base", 0.0)), float(r.get("amp", 1.0))
        cx, cy = float(r.get("cx", 0.5)) * Lx, float(r.get("cy", 0.5)) * Ly
        rad = max(float(r.get("radius_km", 20.0)), 1e-3) * 1e3
        g = f"gauss(sqrt((x - {_f(cx)})**2 + (y - {_f(cy)})**2), {_f(rad)})"
        d = float(r.get("depth", 0.0))
        if d > 0:
            g = f"{g}*where(z > {_f(-d)}, 1, 0)"
        return f"{_f(base)} + {_f(amp)}*{g}"
    if mode == "gradient":
        v1, v2 = float(r.get("v1", 0.0)), float(r.get("v2", 0.0))
        return f"{_f(v1)} + {_f(v2 - v1)}*{axis}/{_f(L)}"
    raise ValueError(f"modo de receta desconocido: {mode}")


def recipe_uses_z(r: dict | None) -> bool:
    if not r:
        return False
    if r.get("mode") in ("layers", "toplayer"):
        return True
    if r.get("mode") == "gauss":
        return float(r.get("depth", 0.0)) > 0
    if r.get("mode") == "expr":
        from .expressions import uses
        return uses(r.get("expression", ""), "z")
    return False


def recipe_matches(r: dict | None, value, Lx: float, Ly: float) -> bool:
    """True si la receta regenera exactamente el valor guardado en el YAML (número o expresión)."""
    try:
        gen = recipe_expression(r, Lx, Ly)
    except (ValueError, TypeError):
        return False
    if is_expression(value) or is_expression(gen):
        return str(gen) == str(value)
    return float(gen) == float(value)


def recipe_from_value(value) -> dict:
    """Receta equivalente a un valor del YAML sin receta guardada: constante o expresión libre."""
    if is_expression(value):
        return {"mode": "expr", "expression": value}
    return {"mode": "constant", "value": float(value)}


# ----------------------------------------------------------------------------- densidad aproximada
def density(T, S):
    """Densidad del agua de mar (kg/m3) a presión atmosférica, EOS-80 (Millero & Poisson 1981). T en °C, S en psu."""
    T = np.asarray(T, float); S = np.asarray(S, float)
    rho_w = (999.842594 + 6.793952e-2 * T - 9.095290e-3 * T**2 + 1.001685e-4 * T**3 - 1.120083e-6 * T**4 + 6.536332e-9 * T**5)
    A = 8.24493e-1 - 4.0899e-3 * T + 7.6438e-5 * T**2 - 8.2467e-7 * T**3 + 5.3875e-9 * T**4
    B = -5.72466e-3 + 1.0227e-4 * T - 1.6546e-6 * T**2
    C = 4.8314e-4
    return rho_w + A * S + B * S**1.5 + C * S**2


def evaluate_field(value, frame: dict, depth: np.ndarray, z: np.ndarray | None = None) -> np.ndarray:
    """Evalúa un valor/expresión del YAML en los nodos (z=None) o en (nodo, nivel)."""
    v = expression_vars(frame, depth, z)
    out = evaluate(value, **v)
    shape = depth.shape if z is None else z.shape
    return np.broadcast_to(np.asarray(out, float), shape).copy()
