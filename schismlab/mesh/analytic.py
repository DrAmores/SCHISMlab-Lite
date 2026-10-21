"""Fondos analíticos de las mallas idealizadas: formas predefinidas y fórmula numpy libre."""
from __future__ import annotations
import numpy as np

def analytic_depth(kind: str = "flat", **p):
    """Fondo analitico. Devuelve depth(x, y) con profundidad positiva [m].

    kind = 'flat'   : h
         = 'slope'  : h0 + s*(x - x0)        (talud lineal en x; usa 'axis'='y' para y)
         = 'step'   : h_shallow si x < x_step, h_deep si no
         = 'channel': h_center - (h_center - h_side) * (2*(y - yc)/W)**2  (canal parabolico en y)
         = 'shelf'  : plataforma h_shelf hasta x_shelf, talud lineal hasta h_deep en x_shelf + L_slope
         = 'seamount': h - A*exp(-((x-x0)^2+(y-y0)^2)/(2 r^2))
         = 'expression': formula numpy libre (cadena) con x, y en metros desde la esquina SW y, en dominios lon/lat,
                         también lon, lat en grados; `origin=(lon0, lat0, lat_media)` indica que la malla está en grados.
    """
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
        return _expression_depth(p.get("formula"), p.get("origin"))
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
