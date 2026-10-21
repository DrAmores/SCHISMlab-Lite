"""Profundidad de una isosuperficie (isoterma, isohalina, isopicna...) en mapa, serie temporal y sección: la forma de
medir el espesor h(x, t) de una capa (p. ej. la isoterma de 15 °C que separa dos capas, o la isopicna que sigue la
termoclina). Núcleo sin interfaz, usado por el explorador y por los cuadernos.

Convenciones: columnas (n, nvrt) con nivel 0 = fondo y último nivel = superficie; la profundidad devuelta es
positiva hacia abajo (m) y NaN donde la isosuperficie no corta la columna (aflora o está bajo el fondo).
Si hay varias intersecciones, `which` elige la más somera (por defecto) o la más profunda.
"""
from __future__ import annotations
import numpy as np
import xarray as xr
from .sections import FILL


def iso_depth_columns(v: np.ndarray, z: np.ndarray, value: float, which: str = "shallowest") -> np.ndarray:
    """Profundidad (m, +abajo) en la que v = value en cada columna (n, nvrt), por interpolación lineal en z."""
    v = np.asarray(v, float); z = np.asarray(z, float)
    ok = np.isfinite(v) & np.isfinite(z)
    d = np.where(ok, v - float(value), np.nan)
    d0, d1 = d[:, :-1], d[:, 1:]                                   # intervalo [k, k+1], de fondo a superficie
    cross = np.isfinite(d0) & np.isfinite(d1) & (d0 * d1 <= 0) & ~((d0 == 0) & (d1 == 0))
    n, m = cross.shape
    idx = np.arange(m)
    if which == "shallowest":
        k = np.where(cross, idx, -1).max(axis=1)
    elif which == "deepest":
        k = np.where(cross, idx, m).min(axis=1); k = np.where(k == m, -1, k)
    else:
        raise ValueError("which: 'shallowest' o 'deepest'")
    out = np.full(n, np.nan)
    hit = k >= 0
    r = np.arange(n)[hit]; kk = k[hit]
    a, b = d[r, kk], d[r, kk + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(b != a, a / (a - b), 0.0)
    zc = z[r, kk] + f * (z[r, kk + 1] - z[r, kk])
    out[hit] = -zc
    return out


def _column_z(ds: xr.Dataset, it: int, vg=None) -> np.ndarray:
    if "zCoordinates" in ds:
        z = ds.zCoordinates.isel(time=it).values.astype(float); return np.where(z < FILL, np.nan, z)
    if vg is None:
        raise ValueError("hace falta la malla vertical (vg) o la salida zCoordinates")
    eta = ds.elevation.isel(time=it).values if "elevation" in ds else np.zeros(ds.sizes["node"])
    return vg.zcor(np.nan_to_num(ds.depth.values, nan=1.0), np.nan_to_num(eta))


def _column_v(ds: xr.Dataset, var: str, it: int) -> np.ndarray:
    da = ds[var]
    if "layer" not in da.dims:
        raise ValueError(f"{var} no es una variable 3D: no tiene isosuperficies")
    v = da.isel(time=it).values.astype(float)
    return np.where(v < FILL, np.nan, v)


def isosurface_depth(ds: xr.Dataset, var: str, value: float, it: int | None = None, vg=None, which: str = "shallowest") -> xr.DataArray:
    """Mapa nodal (node) de la profundidad (m) de la isosuperficie var = value en el instante `it`, o (time, node) si
    it es None. Ejemplos: isoterma de 15 °C (var='temperature'), isohalina de 37 (var='salinity'), isopicna de 27
    (var='density', σt calculada con sigma_t si no se guardó waterDensity)."""
    its = range(ds.time.size) if it is None else [it]
    out = np.stack([iso_depth_columns(_column_v(ds, var, i), _column_z(ds, i, vg), value, which) for i in its])
    dims = ("time", "node") if it is None else ("node",)
    da = xr.DataArray(out if it is None else out[0], dims=dims, name=f"iso_{var}", attrs=dict(units="m", long_name=f"profundidad de {var} = {value:g}"))
    if it is None:
        da = da.assign_coords(time=ds.time)
    return da


def isosurface_series(ds: xr.Dataset, var: str, value: float, node: int, vg=None, which: str = "shallowest") -> np.ndarray:
    """Serie temporal (time,) de la profundidad (m) de la isosuperficie en un nodo."""
    da = ds[var].isel(node=node)
    v = np.where(da.values < FILL, np.nan, da.values.astype(float))          # (time, nvrt)
    if "zCoordinates" in ds:
        z = ds.zCoordinates.isel(node=node).values.astype(float); z = np.where(z < FILL, np.nan, z)
    else:
        if vg is None:
            raise ValueError("hace falta la malla vertical (vg) o la salida zCoordinates")
        h = float(np.nan_to_num(ds.depth.values[node], nan=1.0))
        eta = ds.elevation.isel(node=node).values if "elevation" in ds else np.zeros(ds.time.size)
        z = np.stack([vg.zcor(np.array([h]), np.array([float(np.nan_to_num(e))]))[0] for e in eta])
    return iso_depth_columns(v, z, value, which)


def section_iso_depth(sec, var: str, value: float, it: int, which: str = "shallowest") -> np.ndarray:
    """Profundidad (m) de la isosuperficie a lo largo de una Section (npts,) en el instante `it`."""
    return iso_depth_columns(sec.scalar(var, it), sec.z(it), value, which)


def section_iso_hovmoller(sec, var: str, value: float, which: str = "shallowest") -> np.ndarray:
    """Matriz (tiempo, distancia) de la profundidad de la isosuperficie a lo largo de una Section: h(x, t)."""
    return np.stack([section_iso_depth(sec, var, value, it, which) for it in range(sec.ds.time.size)])


def sigma_t(T, S):
    """Densidad σt = ρ(S, T, p=0) − 1000 (kg/m³), ecuación de estado UNESCO (1983). Vale para xarray (perezoso) y numpy."""
    rw = (999.842594 + 6.793952e-2 * T - 9.095290e-3 * T ** 2 + 1.001685e-4 * T ** 3 - 1.120083e-6 * T ** 4 + 6.536332e-9 * T ** 5)
    b = 8.24493e-1 - 4.0899e-3 * T + 7.6438e-5 * T ** 2 - 8.2467e-7 * T ** 3 + 5.3875e-9 * T ** 4
    c = -5.72466e-3 + 1.0227e-4 * T - 1.6546e-6 * T ** 2
    rho = rw + b * S + c * S * abs(S) ** 0.5 + 4.8314e-4 * S ** 2
    return rho - 1000.0


def add_density(ds: xr.Dataset, name: str = "density") -> xr.Dataset:
    """Añade σt (de temperature y salinity, cálculo perezoso) si no está ya ni se guardó waterDensity. Devuelve ds."""
    if name in ds or "waterDensity" in ds or not ("temperature" in ds and "salinity" in ds):
        return ds
    T, S = ds.temperature, ds.salinity
    bad = (T < FILL) | (S < FILL)
    ds[name] = sigma_t(T.where(~bad), S.where(~bad)).assign_attrs(units="kg/m3", long_name="sigma-t (UNESCO 1983, p=0)")
    return ds
