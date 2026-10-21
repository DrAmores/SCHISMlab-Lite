"""Trazado de partículas (lagrangiano, post-proceso) sobre las salidas de SCHISM.

No requiere recompilar: integra dx/dt = u(x, t) con las velocidades guardadas (promediadas en vertical o de una
capa), interpoladas linealmente en el elemento y en el tiempo, con un Runge-Kutta de orden 2 y subpasos.
Las partículas que salen del dominio (o tocan tierra) se quedan quietas.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import xarray as xr
from matplotlib.tri import Triangulation

R_EARTH = 6371000.0


@dataclass
class Tracks:
    time: np.ndarray        # (nt,) datetime64
    x: np.ndarray           # (nt, np)
    y: np.ndarray           # (nt, np)
    geographic: bool

    def to_csv(self, path) -> None:
        import pandas as pd
        rows = []
        for j in range(self.x.shape[1]):
            for i in range(self.x.shape[0]):
                rows.append((j, self.time[i], self.x[i, j], self.y[i, j]))
        pd.DataFrame(rows, columns=["particula", "tiempo", "x", "y"]).to_csv(path, index=False)

    def distance_km(self) -> np.ndarray:
        """Distancia recorrida por cada partícula (km)."""
        dx = np.diff(self.x, axis=0); dy = np.diff(self.y, axis=0)
        if self.geographic:
            lat = np.deg2rad(self.y[:-1])
            dx = dx * np.cos(lat) * R_EARTH * np.pi / 180; dy = dy * R_EARTH * np.pi / 180
        return np.nansum(np.hypot(dx, dy), axis=0) / 1000


def is_geographic(ds: xr.Dataset) -> bool:
    return bool(np.abs(ds.x.values).max() <= 360 and np.abs(ds.y.values).max() <= 90.5)


def velocity_fields(ds: xr.Dataset, layer: int | None = None) -> tuple[str, str]:
    """Nombres (u, v) a usar: capa `layer` de horizontalVel si existe y se pide, si no la velocidad promediada."""
    if layer is not None and "horizontalVelX" in ds:
        return "horizontalVelX", "horizontalVelY"
    if "depthAverageVelX" in ds:
        return "depthAverageVelX", "depthAverageVelY"
    if "horizontalVelX" in ds:
        return "horizontalVelX", "horizontalVelY"
    raise KeyError("la simulación no guardó velocidades (depthAverageVel u horizontalVel)")


def release_points(x0: float, y0: float, n: int, radius_km: float, geographic: bool, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """n puntos uniformes en un disco de radio radius_km centrado en (x0, y0)."""
    rng = np.random.default_rng(seed)
    r = radius_km * 1000 * np.sqrt(rng.random(n)); th = 2 * np.pi * rng.random(n)
    dx, dy = r * np.cos(th), r * np.sin(th)
    if geographic:
        dx = dx / (R_EARTH * np.cos(np.deg2rad(y0))) * 180 / np.pi; dy = dy / R_EARTH * 180 / np.pi
    return x0 + dx, y0 + dy


def track(ds: xr.Dataset, x0, y0, start: int = 0, hours: float | None = None, layer: int | None = None,
          substeps: int = 6, every: int = 1) -> Tracks:
    """Trayectorias desde (x0, y0) (arrays) a partir del índice temporal `start`, durante `hours` (por defecto hasta el final).

    `layer`: capa de la velocidad 3D (None = promediada en vertical). `substeps`: subpasos RK2 por intervalo de salida.
    `every`: guardar una posición cada `every` intervalos de salida.
    """
    geo = is_geographic(ds)
    tri = Triangulation(ds.x.values, ds.y.values, ds.attrs["elements"]); finder = tri.get_trifinder()
    uname, vname = velocity_fields(ds, layer)
    tvals = ds.time.values
    nt = ds.time.size
    stop = nt - 1 if hours is None else min(nt - 1, start + int(round(hours * 3600 / (float(np.diff(tvals[:2])[0]) / 1e9))))
    def field(it):
        u = ds[uname].isel(time=it); v = ds[vname].isel(time=it)
        if "layer" in u.dims:
            u = u.isel(layer=layer if layer is not None else -1); v = v.isel(layer=layer if layer is not None else -1)
        return np.nan_to_num(u.values.astype(float)), np.nan_to_num(v.values.astype(float))
    elems = tri.triangles
    def interp(u, v, px, py):
        ie = finder(px, py); inside = ie >= 0
        out_u = np.zeros_like(px); out_v = np.zeros_like(py)
        if inside.any():
            e = elems[ie[inside]]; xa, ya = tri.x[e], tri.y[e]       # (n, 3)
            # coordenadas baricentricas
            det = (ya[:, 1] - ya[:, 2]) * (xa[:, 0] - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (ya[:, 0] - ya[:, 2])
            l1 = ((ya[:, 1] - ya[:, 2]) * (px[inside] - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (py[inside] - ya[:, 2])) / det
            l2 = ((ya[:, 2] - ya[:, 0]) * (px[inside] - xa[:, 2]) + (xa[:, 0] - xa[:, 2]) * (py[inside] - ya[:, 2])) / det
            l3 = 1 - l1 - l2
            w = np.stack([l1, l2, l3], 1)
            out_u[inside] = (u[e] * w).sum(1); out_v[inside] = (v[e] * w).sum(1)
        return out_u, out_v, inside
    px = np.asarray(x0, float).copy(); py = np.asarray(y0, float).copy()
    xs = [px.copy()]; ys = [py.copy()]; times = [tvals[start]]
    u0, v0 = field(start); alive = np.ones(px.size, bool)
    for it in range(start, stop):
        u1, v1 = field(it + 1)
        dt = float(tvals[it + 1] - tvals[it]) / 1e9 / substeps
        for k in range(substeps):
            a = (k + 0.5) / substeps
            ua = (1 - a) * u0 + a * u1; va = (1 - a) * v0 + a * v1
            def to_deg(u, v, lat):
                if not geo:
                    return u, v
                return u / (R_EARTH * np.cos(np.deg2rad(lat))) * 180 / np.pi, v / R_EARTH * 180 / np.pi
            uu, vv, ins = interp(ua, va, px, py); uu, vv = to_deg(uu, vv, py)
            xm, ym = px + 0.5 * dt * uu, py + 0.5 * dt * vv
            uu2, vv2, ins2 = interp(ua, va, xm, ym); uu2, vv2 = to_deg(uu2, vv2, ym)
            alive &= ins & ins2
            px = np.where(alive, px + dt * uu2, px); py = np.where(alive, py + dt * vv2, py)
        u0, v0 = u1, v1
        if (it + 1 - start) % every == 0 or it + 1 == stop:
            xs.append(px.copy()); ys.append(py.copy()); times.append(tvals[it + 1])
    return Tracks(np.array(times), np.array(xs), np.array(ys), geo)
