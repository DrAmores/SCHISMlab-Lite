"""Figuras estandar sobre las salidas de SCHISM: mapas, series, perfiles, secciones y animaciones."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import xarray as xr
from .output import nearest_node

LABELS = {"elevation": "elevacion (m)", "temperature": "temperatura (C)", "salinity": "salinidad (psu)",
          "depthAverageVel": "|U| media (m/s)", "horizontalVel": "|u| (m/s)", "verticalVelocity": "w (m/s)"}


def _tri(ds):
    return mtri.Triangulation(ds.x.values, ds.y.values, ds.attrs["elements"])


def _field(ds: xr.Dataset, var: str, time, layer=-1) -> np.ndarray:
    """Campo nodal 1D para `var` (escalar o modulo del vector X/Y) en un instante y capa."""
    if var + "X" in ds:
        u, v = ds[var + "X"], ds[var + "Y"]
        u, v = (u.isel(time=time), v.isel(time=time)) if isinstance(time, int) else (u.sel(time=time, method="nearest"), v.sel(time=time, method="nearest"))
        if "layer" in u.dims:
            u, v = u.isel(layer=layer), v.isel(layer=layer)
        return np.hypot(u.values, v.values)
    da = ds[var]
    da = da.isel(time=time) if isinstance(time, int) else da.sel(time=time, method="nearest")
    if "layer" in da.dims:
        da = da.isel(layer=layer)
    return da.values


def plot_map(ds: xr.Dataset, var: str = "elevation", time=-1, layer=-1, ax=None, vectors: bool = False,
             cmap=None, vmin=None, vmax=None, title=None, **kw):
    """Mapa de `var` (p.ej. elevation, depthAverageVel, temperature) en un instante; vectors=True anade flechas."""
    if ax is None:
        _, ax = plt.subplots(figsize=kw.pop("figsize", (9, 7)))
    tri = _tri(ds)
    f = _field(ds, var, time, layer)
    if cmap is None:
        cmap = "RdBu_r" if var == "elevation" else "viridis"
    if var == "elevation" and vmin is None and vmax is None:
        vmax = float(np.nanmax(np.abs(f))); vmin = -vmax
    c = ax.tripcolor(tri, f, cmap=cmap, vmin=vmin, vmax=vmax, shading="gouraud")
    plt.colorbar(c, ax=ax, label=LABELS.get(var, var), shrink=0.8)
    if vectors and var + "X" in ds:
        u = _field(ds, var + "X", time, layer) if var + "X" + "X" in ds else ds[var + "X"].isel(time=time).values
        v = ds[var + "Y"].isel(time=time).values
        if u.ndim == 2: u, v = u[:, layer], v[:, layer]
        step = max(1, ds.x.size // 1500)
        ax.quiver(ds.x.values[::step], ds.y.values[::step], u[::step], v[::step], color="k", scale=kw.get("scale"), width=0.002)
    geographic = np.ptp(ds.x.values) < 360 and np.ptp(ds.y.values) < 180
    ax.set_aspect(1 / np.cos(np.deg2rad(ds.y.values.mean())) if geographic else "equal")
    t = ds.time.values[time] if isinstance(time, int) else time
    ax.set_title(title or f"{var}  {np.datetime_as_string(np.datetime64(t), 'm')}")
    return ax


def plot_timeseries(ds: xr.Dataset, var: str, x: float, y: float, layer=-1, ax=None, label=None):
    """Serie temporal de `var` en el nodo mas cercano a (x, y)."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.5))
    n = nearest_node(ds, x, y)
    if var + "X" in ds:
        u, v = ds[var + "X"].isel(node=n), ds[var + "Y"].isel(node=n)
        if "layer" in u.dims: u, v = u.isel(layer=layer), v.isel(layer=layer)
        da = np.hypot(u, v)
    else:
        da = ds[var].isel(node=n)
        if "layer" in da.dims: da = da.isel(layer=layer)
    ax.plot(ds.time.values, da.values, label=label or f"({x:g}, {y:g})")
    ax.set_ylabel(LABELS.get(var, var)); ax.grid(alpha=0.3); ax.legend()
    return ax


def plot_profile(ds: xr.Dataset, var: str, x: float, y: float, vg, time=-1, ax=None, label=None):
    """Perfil vertical de `var` (3D) en el nodo mas cercano, con cotas z calculadas de la malla vertical `vg`."""
    if ax is None:
        _, ax = plt.subplots(figsize=(4, 6))
    n = nearest_node(ds, x, y)
    eta = float(ds.elevation.isel(node=n, time=time)) if "elevation" in ds else 0.0
    z = vg.zcor(np.array([float(ds.depth.isel(node=n))]), np.array([eta]))[0]
    if var + "X" in ds:
        u, v = ds[var + "X"].isel(node=n, time=time).values, ds[var + "Y"].isel(node=n, time=time).values
        ax.plot(u, z, label="u"); ax.plot(v, z, label="v"); ax.legend()
    else:
        ax.plot(ds[var].isel(node=n, time=time).values, z, label=label)
    ax.set_xlabel(LABELS.get(var, var)); ax.set_ylabel("z (m)"); ax.grid(alpha=0.3)
    return ax


def plot_section(ds: xr.Dataset, var: str, p0: tuple, p1: tuple, vg, time=-1, npts: int = 100, ax=None, cmap="viridis", **kw):
    """Seccion vertical de `var` a lo largo del segmento p0-p1 (interpolacion lineal en la malla)."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))
    tri = _tri(ds)
    xs = np.linspace(p0[0], p1[0], npts); ys = np.linspace(p0[1], p1[1], npts)
    geographic = np.ptp(ds.x.values) < 360
    if geographic:
        lat0 = np.deg2rad(ys.mean()); dist = np.hypot(np.deg2rad(xs - xs[0]) * 6371e3 * np.cos(lat0), np.deg2rad(ys - ys[0]) * 6371e3) / 1e3
    else:
        dist = np.hypot(xs - xs[0], ys - ys[0]) / 1e3
    da = ds[var].isel(time=time) if var in ds else np.hypot(ds[var + "X"].isel(time=time), ds[var + "Y"].isel(time=time))
    vals = da.values                                   # (node, layer)
    depth = mtri.LinearTriInterpolator(tri, ds.depth.values)(xs, ys).filled(np.nan)
    eta = mtri.LinearTriInterpolator(tri, ds.elevation.isel(time=time).values)(xs, ys).filled(0.0) if "elevation" in ds else np.zeros(npts)
    z = vg.zcor(np.nan_to_num(depth, nan=1.0), eta)
    sec = np.column_stack([mtri.LinearTriInterpolator(tri, vals[:, k])(xs, ys).filled(np.nan) for k in range(vals.shape[1])])
    c = ax.contourf(np.repeat(dist[:, None], z.shape[1], 1), z, sec, levels=kw.pop("levels", 20), cmap=cmap, extend="both")
    plt.colorbar(c, ax=ax, label=LABELS.get(var, var))
    ax.fill_between(dist, -depth, np.nanmin(-depth) - 5, color="0.7")
    ax.set_xlabel("distancia (km)"); ax.set_ylabel("z (m)")
    return ax


def animate(ds: xr.Dataset, var: str = "elevation", path: str | Path = "animacion.mp4", layer=-1, fps: int = 8,
            step: int = 1, vmin=None, vmax=None, cmap=None, dpi: int = 90):
    """Animacion (mp4 con ffmpeg si esta disponible, si no gif) del campo `var` en el tiempo."""
    from matplotlib import animation
    fig, ax = plt.subplots(figsize=(9, 7))
    f0 = _field(ds, var, 0, layer)
    if vmin is None and vmax is None:
        allv = np.stack([_field(ds, var, t, layer) for t in range(0, ds.time.size, max(1, ds.time.size // 10))])
        vmax = float(np.nanpercentile(np.abs(allv) if var == "elevation" else allv, 99)); vmin = -vmax if var == "elevation" else float(np.nanmin(allv))
    cmap = cmap or ("RdBu_r" if var == "elevation" else "viridis")
    tri = _tri(ds)
    coll = ax.tripcolor(tri, f0, cmap=cmap, vmin=vmin, vmax=vmax, shading="gouraud")
    plt.colorbar(coll, ax=ax, label=LABELS.get(var, var), shrink=0.8)
    geographic = np.ptp(ds.x.values) < 360 and np.ptp(ds.y.values) < 180
    ax.set_aspect(1 / np.cos(np.deg2rad(ds.y.values.mean())) if geographic else "equal")
    frames = list(range(0, ds.time.size, step))

    def update(i):
        coll.set_array(_field(ds, var, i, layer))
        ax.set_title(f"{var}  {np.datetime_as_string(ds.time.values[i], 'm')}")
        return (coll,)
    ani = animation.FuncAnimation(fig, update, frames=frames, blit=False)
    path = Path(path)
    if path.suffix == ".mp4" and animation.writers.is_available("ffmpeg"):
        ani.save(path, fps=fps, dpi=dpi, writer="ffmpeg")
    else:
        path = path.with_suffix(".gif"); ani.save(path, fps=fps, dpi=dpi, writer="pillow")
    plt.close(fig)
    return path
