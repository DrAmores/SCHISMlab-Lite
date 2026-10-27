"""Lecturas de un perfil vertical de velocidad (espiral de Ekman) y de un perfil a lo largo de una sección (ajustes e
integrales). Núcleo sin interfaz: la GUI de Puntos y Secciones los usa para contestar sin cuaderno.

Perfiles: z crece del fondo a la superficie (como SCHISM); u hacia el este y v hacia el norte. Los ángulos respecto al
viento son positivos a la DERECHA del viento (sentido horario), que es hacia donde gira la corriente en el hemisferio
norte."""
from __future__ import annotations
import numpy as np

G = 9.81


def angle_right(u, v, wx, wy) -> float:
    """Ángulo (grados, −180..180) de (u, v) respecto a la dirección (wx, wy), positivo a la derecha (horario)."""
    return float(np.degrees(np.arctan2(wy, wx) - np.arctan2(v, u) + np.pi) % 360.0 - 180.0)


def geostrophic(ds, node: int, its, f: float):
    """Velocidad geostrófica (ug, vg) en el nodo a partir de la pendiente de la superficie media en `its`:
    ug = −(g/f) ∂η/∂y, vg = (g/f) ∂η/∂x (gradiente P1 sobre la malla)."""
    from .dynamics import gradient_operators
    eta = np.nanmean(np.asarray(ds.elevation.isel(time=list(np.atleast_1d(its))).values, float), axis=0)
    Gx, Gy = gradient_operators(ds)
    dex, dey = float((Gx @ np.nan_to_num(eta))[node]), float((Gy @ np.nan_to_num(eta))[node])
    return -G / f * dey, G / f * dex


def ekman_readouts(z, u, v, wind=None, ref=None, fit=(-28.0, 0.0), integ=None, f=None) -> dict:
    """Lecturas de la espiral en un perfil (z, u, v) (del fondo a la superficie).

    ref:   (ur, vr) que se resta a cada nivel (corriente de un nivel profundo o geostrófica); None = nada.
    wind:  (τx, τy) o dirección del viento (cualquier vector paralelo); sin él no hay ángulos respecto al viento.
    fit:   rango de z (m, negativo abajo) del ajuste de ln|v_E| frente a z: pendiente 1/De.
    integ: rango de z de la integral de u_E, v_E (None = toda la columna).
    En los dos rangos, un extremo superior >= 0 significa «hasta la superficie libre» (con η > 0 el nivel de superficie
    está por encima de z = 0) y uno inferior None, «desde el fondo».
    f:     parámetro de Coriolis (para Az = |f| De² / 2).

    Devuelve: uE, vE (perfiles), surface (|v_E(0)|), surface_angle (respecto al viento, + a la derecha),
    z_reverse (primera profundidad, m negativa, donde la corriente va en sentido contrario a la de superficie),
    De, Az, V0_fit, Tx, Ty, T_angle (ángulo del transporte respecto al viento) y n_fit (niveles del ajuste)."""
    z = np.asarray(z, float); u = np.asarray(u, float); v = np.asarray(v, float)
    ok = np.isfinite(z) & np.isfinite(u) & np.isfinite(v)
    z, u, v = z[ok], u[ok], v[ok]
    o = np.argsort(z); z, u, v = z[o], u[o], v[o]
    ur, vr = (0.0, 0.0) if ref is None else (float(ref[0]), float(ref[1]))
    uE, vE = u - ur, v - vr
    out = dict(z=z, uE=uE, vE=vE, surface=float(np.hypot(uE[-1], vE[-1])), surface_u=float(uE[-1]), surface_v=float(vE[-1]),
               bottom_still=bool(np.hypot(u[0], v[0]) == 0.0))                 # nivel del fondo de SCHISM: u = v = 0
    def rng(r):
        lo, hi = (min(r), max(r)) if None not in r else (r[0], r[1])
        lo = -np.inf if lo is None else float(lo); hi = np.inf if (hi is None or float(hi) >= 0) else float(hi)
        return lo, hi
    if wind is not None and np.hypot(*wind) > 0:
        out["surface_angle"] = angle_right(uE[-1], vE[-1], *wind)
    # inversión: el ángulo relativo a la corriente de superficie llega a 180° (de la superficie hacia abajo)
    a0 = np.arctan2(vE[-1], uE[-1])
    rel = np.degrees(np.unwrap(np.arctan2(vE, uE)[::-1] - a0)); zz = z[::-1]
    k = np.where(np.abs(rel) >= 180.0)[0]
    out["z_reverse"] = float(np.interp(180.0, [abs(rel[k[0] - 1]), abs(rel[k[0]])], [zz[k[0] - 1], zz[k[0]]])) if len(k) and k[0] > 0 else None
    # ajuste ln|v_E| = ln V0 + z/De en el rango pedido
    mod = np.hypot(uE, vE)
    lo, hi = rng(tuple(fit))
    m = (z >= lo) & (z <= hi) & (mod > 0)
    out["n_fit"] = int(m.sum())
    if m.sum() >= 2:
        p = np.polyfit(z[m], np.log(mod[m]), 1)
        out["De"] = float(1.0 / p[0]) if p[0] != 0 else None
        out["V0_fit"] = float(np.exp(p[1]))
        if f is not None and out["De"]:
            out["Az"] = float(abs(f) * out["De"] ** 2 / 2.0)
    # transporte: integral (trapecios) en el rango
    if integ is None:
        mi = np.ones_like(z, bool)
    else:
        a, b = rng(tuple(integ)); mi = (z >= a) & (z <= b)
    if mi.sum() >= 2:
        out["Tx"] = float(np.trapezoid(uE[mi], z[mi])); out["Ty"] = float(np.trapezoid(vE[mi], z[mi]))
        if wind is not None and np.hypot(*wind) > 0 and np.hypot(out["Tx"], out["Ty"]) > 0:
            out["T_angle"] = angle_right(out["Tx"], out["Ty"], *wind)
    return out


def theoretical_spiral(V0: float, De: float, f: float = 1.0, wind_dir=(1.0, 0.0), zmin: float = -200.0, n: int = 300):
    """Espiral de Ekman teórica (u_E, v_E) para un viento en la dirección `wind_dir`: v_E(0) = V0 a 45° a la derecha
    (hemisferio norte, f > 0; a la izquierda si f < 0), con decaimiento e^{z/De}."""
    z = np.linspace(zmin, 0.0, n)
    s = 1.0 if f >= 0 else -1.0
    a = np.exp(z / De) * V0
    th = np.arctan2(wind_dir[1], wind_dir[0]) - s * (np.pi / 4 - z / De)      # gira a la derecha al bajar (HN)
    return z, a * np.cos(th), a * np.sin(th)


def line_fit(dist_km, y, d1: float, d2: float, log: bool = False, ref: float = 0.0) -> dict | None:
    """Ajuste lineal de y − ref (o ln|y − ref| si log) frente a la distancia (m) entre d1 y d2 (km).
    Devuelve pendiente α (1/m), escala 1/α (km), ordenada y número de puntos; None si no hay datos."""
    x = np.asarray(dist_km, float) * 1e3; yy = np.asarray(y, float) - float(ref)
    lo, hi = min(d1, d2) * 1e3, max(d1, d2) * 1e3
    m = (x >= lo) & (x <= hi) & np.isfinite(yy)
    if log:
        m &= np.abs(yy) > 0
        yy = np.log(np.abs(np.where(m, yy, 1.0)))
    if m.sum() < 2:
        return None
    p = np.polyfit(x[m], yy[m], 1)
    return dict(alpha=float(p[0]), scale_km=float(1.0 / p[0] / 1e3) if p[0] != 0 else None, intercept=float(p[1]), n=int(m.sum()),
                x0_km=lo / 1e3, x1_km=hi / 1e3, log=bool(log), ref=float(ref))


def line_integral(dist_km, y, d1: float, d2: float) -> float | None:
    """∫ y dx (x en m) entre d1 y d2 (km), con los extremos interpolados. Con y en m²/s (transporte) da m³/s."""
    x = np.asarray(dist_km, float) * 1e3; yy = np.asarray(y, float)
    ok = np.isfinite(yy)
    if ok.sum() < 2:
        return None
    x, yy = x[ok], yy[ok]
    a, b = min(d1, d2) * 1e3, max(d1, d2) * 1e3
    a, b = max(a, x[0]), min(b, x[-1])
    if b <= a:
        return 0.0
    xs = np.concatenate([[a], x[(x > a) & (x < b)], [b]])
    return float(np.trapezoid(np.interp(xs, x, yy), xs))


def zero_crossings(dist_km, y) -> list[float]:
    """Distancias (km) en las que y cambia de signo (interpoladas)."""
    x = np.asarray(dist_km, float); yy = np.asarray(y, float)
    out = []
    for i in range(len(x) - 1):
        a, b = yy[i], yy[i + 1]
        if np.isfinite(a) and np.isfinite(b) and a * b < 0:
            out.append(float(x[i] + (x[i + 1] - x[i]) * a / (a - b)))
    return out
