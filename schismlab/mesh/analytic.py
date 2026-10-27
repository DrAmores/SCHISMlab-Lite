"""Fondos analíticos de las mallas idealizadas: formas predefinidas y fórmula numpy libre."""
from __future__ import annotations
import numpy as np

# Descripción de cada fondo para la interfaz: nombre, fórmula, parámetros (con su significado) y valores de ejemplo
# según el dominio (x0, x1, y0, y1 en las coordenadas de la malla: metros desde la esquina SW, o grados en lon/lat).
BOTTOMS = {
    "flat": dict(es="plano", en="flat", formula="h",
                 params={"h": ("profundidad (m)", "depth (m)")},
                 example=lambda x0, x1, y0, y1: {"h": 50.0}),
    "slope": dict(es="pendiente", en="slope", formula="h0 + s·(x − x0)",
                  params={"h0": ("profundidad en x0 (m)", "depth at x0 (m)"),
                          "s": ("pendiente (m de profundidad por unidad de x: m/m, o m/grado en lon/lat)", "slope (m of depth per unit of x: m/m, or m/degree in lon/lat)"),
                          "x0": ("donde la profundidad vale h0", "where the depth equals h0"),
                          "axis": ("\"x\" (por defecto) o \"y\": dirección de la pendiente", "\"x\" (default) or \"y\": direction of the slope")},
                  example=lambda x0, x1, y0, y1: {"h0": 10.0, "s": round(190.0 / (x1 - x0), 8), "x0": x0}),
    "step": dict(es="escalón", en="step", formula="h_shallow si x < x_step; h_deep si no",
                 params={"h_shallow": ("profundidad del lado somero (m)", "depth of the shallow side (m)"),
                         "h_deep": ("profundidad del lado profundo (m)", "depth of the deep side (m)"),
                         "x_step": ("posición del escalón", "position of the step"),
                         "axis": ("\"x\" o \"y\"", "\"x\" or \"y\"")},
                 example=lambda x0, x1, y0, y1: {"h_shallow": 20.0, "h_deep": 200.0, "x_step": 0.5 * (x0 + x1)}),
    "channel": dict(es="canal", en="channel", formula="h_center − (h_center − h_side)·(2·(y − yc)/W)²",
                    params={"h_center": ("profundidad en el eje del canal (m)", "depth on the channel axis (m)"),
                            "h_side": ("profundidad en las orillas (m)", "depth at the banks (m)"),
                            "yc": ("y del eje del canal", "y of the channel axis"),
                            "W": ("anchura del canal (de orilla a orilla)", "channel width (bank to bank)")},
                    example=lambda x0, x1, y0, y1: {"h_center": 50.0, "h_side": 5.0, "yc": 0.5 * (y0 + y1), "W": y1 - y0}),
    "shelf": dict(es="plataforma y talud", en="shelf and slope", formula="h_shelf hasta x_shelf; talud lineal hasta h_deep en x_shelf + L_slope",
                  params={"h_shelf": ("profundidad de la plataforma (m)", "shelf depth (m)"),
                          "h_deep": ("profundidad de la llanura abisal (m)", "deep-ocean depth (m)"),
                          "x_shelf": ("borde de la plataforma", "shelf edge"),
                          "L_slope": ("anchura del talud", "width of the slope"),
                          "axis": ("\"x\" o \"y\"", "\"x\" or \"y\"")},
                  example=lambda x0, x1, y0, y1: {"h_shelf": 50.0, "h_deep": 1000.0, "x_shelf": x0 + 0.3 * (x1 - x0), "L_slope": 0.2 * (x1 - x0)}),
    "seamount": dict(es="monte submarino (seamount)", en="seamount", formula="h − A·exp(−((x − x0)² + (y − y0)²) / (2·r²))",
                     params={"h": ("profundidad lejos del monte (m)", "depth away from the seamount (m)"),
                             "A": ("altura del monte sobre el fondo (m); h − A es la profundidad en la cima", "seamount height above the bottom (m); h − A is the depth at the top"),
                             "x0": ("x del centro", "x of the centre"), "y0": ("y del centro", "y of the centre"),
                             "r": ("radio (desviación de la gaussiana, en unidades de x)", "radius (Gaussian width, in units of x)")},
                     example=lambda x0, x1, y0, y1: {"h": 1000.0, "A": 800.0, "x0": 0.5 * (x0 + x1), "y0": 0.5 * (y0 + y1), "r": 0.1 * (x1 - x0)}),
    "expression": dict(es="fórmula libre", en="free formula", formula="cualquier expresión numpy en x, y (y lon, lat en dominios lon/lat)",
                       params={}, example=lambda x0, x1, y0, y1: {}),
}


def bottom_example(kind: str, x0: float, x1: float, y0: float, y1: float) -> dict:
    """Parámetros de ejemplo del fondo `kind` para un dominio [x0, x1] × [y0, y1] (redondeados)."""
    ex = BOTTOMS.get(kind, BOTTOMS["flat"])["example"](float(x0), float(x1), float(y0), float(y1))
    return {k: (float(f"{v:.4g}") if isinstance(v, float) else v) for k, v in ex.items()}


def analytic_depth(kind: str = "flat", **p):
    """Fondo analitico. Devuelve depth(x, y) con profundidad positiva [m].

    kind = 'flat'   : h
         = 'slope'  : h0 + s*(x - x0)        (talud lineal en x; usa 'axis'='y' para y)
         = 'step'   : h_shallow si x < x_step, h_deep si no
         = 'channel': h_center - (h_center - h_side) * (2*(y - yc)/W)**2  (canal parabolico en y)
         = 'shelf'  : plataforma h_shelf hasta x_shelf, talud lineal hasta h_deep en x_shelf + L_slope
         = 'seamount': h - A*exp(-((x-x0)^2+(y-y0)^2)/(2 r^2))
         = 'expression': formula numpy libre (cadena) con x, y en metros desde la esquina SW y, en dominios lon/lat,
                         también lon, lat en grados.
    `origin=(lon0, lat0, lat_media)` indica que la malla está en grados: en todos los tipos x, y (y x0, x_step, r…) van
    en metros desde la esquina SW.
    """
    origin = p.pop("origin", None)
    if origin is not None and kind != "expression":   # malla en grados: el fondo se evalúa en m desde la esquina SW
        f_m = analytic_depth(kind, **p)
        lon0, lat0, latm = (float(v) for v in origin)
        R = 6371e3
        return lambda x, y: f_m(np.deg2rad(np.asarray(x, float) - lon0) * R * np.cos(np.deg2rad(latm)),
                                np.deg2rad(np.asarray(y, float) - lat0) * R)
    def coord(x, y):
        return y if p.get("axis", "x") == "y" else x
    if kind == "flat":
        h = float(p.get("h", 50.0)); return lambda x, y: np.full(np.shape(x), h)
    if kind == "slope":
        h0, s, x0 = p.get("h0", 10.0), p.get("s", 1e-3), p.get("x0", 0.0)
        return lambda x, y: h0 + s * (coord(x, y) - x0)
    if kind == "step":
        return lambda x, y: np.where(coord(x, y) < p.get("x_step", 0.0), p.get("h_shallow", 20.0), p.get("h_deep", 200.0))
    if kind == "channel":
        hc, hs, yc, W = p.get("h_center", 50.0), p.get("h_side", 5.0), p.get("yc", 0.0), p.get("W", 1.0)
        return lambda x, y: hc - (hc - hs) * np.clip(2 * (y - yc) / W, -1, 1) ** 2
    if kind == "shelf":
        hs, hd, xs, L = p.get("h_shelf", 50.0), p.get("h_deep", 1000.0), p.get("x_shelf", 0.0), p.get("L_slope", 1.0)
        return lambda x, y: hs + (hd - hs) * np.clip((coord(x, y) - xs) / L, 0, 1)
    if kind == "seamount":
        h, A, x0, y0, r = p.get("h", 1000.0), p.get("A", 800.0), p.get("x0", 0.0), p.get("y0", 0.0), p.get("r", 1.0)
        return lambda x, y: h - A * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * r ** 2))
    if kind == "expression":
        return _expression_depth(p.get("formula"), origin)
    raise ValueError(f"fondo analitico desconocido: {kind}")


def _expression_depth(formula, origin=None):
    """depth(x, y) evaluando una expresión numpy (ver schismlab.expressions). Con `origin` (lon0, lat0, lat_media) la
    malla está en grados: se ofrecen lon, lat y x, y en metros desde la esquina SW (misma conversión que el viento)."""
    import logging
    from ..expressions import validate
    if not isinstance(formula, str) or not formula.strip():
        raise ValueError("bathymetry {kind: expression} necesita 'formula' (cadena numpy en x, y, lon, lat)")
    validate(formula, ("x", "y", "lon", "lat") if origin is not None else ("x", "y"))
    R = 6371e3

    def f(x, y):
        from ..expressions import evaluate
        x = np.asarray(x, float); y = np.asarray(y, float)
        if origin is not None:
            lon0, lat0, latm = (float(v) for v in origin)
            xm = np.deg2rad(x - lon0) * R * np.cos(np.deg2rad(latm)); ym = np.deg2rad(y - lat0) * R
            with np.errstate(all="ignore"):
                d = evaluate(formula, x=xm, y=ym, lon=x, lat=y)
        else:
            with np.errstate(all="ignore"):
                d = evaluate(formula, x=x, y=y)
        d = d * np.ones(np.shape(x))
        if not np.all(np.isfinite(d)):
            raise ValueError(f"la fórmula del fondo da valores no finitos: {formula!r}")
        if np.any(d <= 0):
            logging.getLogger(__name__).warning("fórmula del fondo: %d nodos con profundidad <= 0 (tierra o costa seca)", int((d <= 0).sum()))
        return d
    return f
