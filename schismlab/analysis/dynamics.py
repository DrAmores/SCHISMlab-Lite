"""Diagnósticos dinámicos sobre la malla no estructurada: gradiente, vorticidad, divergencia, transporte integrado en
la vertical y función de corriente. Núcleo sin interfaz, pensado para los cuadernos (los alumnos pueden calcularlos a
mano y contrastar con estas funciones) y reutilizable en la GUI.

Convenciones: los campos son DataArrays con dimensión `node` (y opcionalmente `time`); los gradientes se calculan
por elemento con las funciones de forma lineales (P1) y se promedian a los nodos ponderando por el área. En mallas en
lon/lat las distancias se miden en metros con la proyección equirrectangular local de `sections.metric_xy`.
Las salidas de SCHISM van en unidades SI: `windStress` es tau/rho_w (m²/s²); `stress_pa` lo pasa a Pa.
"""
from __future__ import annotations
import logging
import numpy as np
import xarray as xr
from scipy import sparse
from .sections import metric_xy, FILL

log = logging.getLogger(__name__)
RHO_WATER = 1000.0


def _elements(ds: xr.Dataset) -> np.ndarray:
    return np.asarray(ds.attrs["elements"], int)[:, :3]


def _geometry(ds: xr.Dataset):
    """(xm, ym, el, area, bx, by): coordenadas en m, elementos y, por elemento, área y derivadas de las funciones de forma
    (dphi_i/dx = bx[:, i], dphi_i/dy = by[:, i])."""
    xm, ym = metric_xy(ds, ds.x.values, ds.y.values)
    el = _elements(ds)
    x0, x1, x2 = (xm[el[:, i]] for i in range(3)); y0, y1, y2 = (ym[el[:, i]] for i in range(3))
    twoA = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    bx = np.column_stack([y1 - y2, y2 - y0, y0 - y1]) / twoA[:, None]
    by = np.column_stack([x2 - x1, x0 - x2, x1 - x0]) / twoA[:, None]
    return xm, ym, el, 0.5 * np.abs(twoA), bx, by


def gradient_operators(ds: xr.Dataset) -> tuple[sparse.csr_matrix, sparse.csr_matrix]:
    """Matrices dispersas (Gx, Gy) nodo→nodo: Gx @ f = df/dx en los nodos (promedio ponderado por área de los
    gradientes P1 de los elementos que rodean cada nodo)."""
    xm, ym, el, area, bx, by = _geometry(ds)
    n, ne = xm.size, el.shape[0]
    rows = np.repeat(np.arange(ne), 3); cols = el.ravel()
    Dx = sparse.csr_matrix((bx.ravel(), (rows, cols)), shape=(ne, n))     # elemento <- nodos
    Dy = sparse.csr_matrix((by.ravel(), (rows, cols)), shape=(ne, n))
    W = sparse.csr_matrix((np.repeat(area, 3), (cols, rows)), shape=(n, ne))   # nodo <- elementos (área)
    inv = 1.0 / np.maximum(np.asarray(W.sum(axis=1)).ravel(), 1e-30)
    A = sparse.diags(inv) @ W
    return (A @ Dx).tocsr(), (A @ Dy).tocsr()


def _nodal(ds: xr.Dataset, f) -> xr.DataArray:
    if isinstance(f, str):
        f = ds[f]
    return f if isinstance(f, xr.DataArray) else xr.DataArray(np.asarray(f, float), dims=("node",))


def _apply(G: sparse.csr_matrix, f: xr.DataArray) -> xr.DataArray:
    """Aplica un operador nodal a lo largo de la dimensión `node` (admite dimensiones extra, p. ej. time o layer)."""
    v = np.nan_to_num(np.moveaxis(f.values.astype(float), f.dims.index("node"), -1))
    out = (G @ v.reshape(-1, v.shape[-1]).T).T.reshape(v.shape)
    out = np.moveaxis(out, -1, f.dims.index("node"))
    return xr.DataArray(out, dims=f.dims, coords={k: c for k, c in f.coords.items() if set(c.dims) <= set(f.dims)})


def gradient(ds: xr.Dataset, f) -> tuple[xr.DataArray, xr.DataArray]:
    """(df/dx, df/dy) nodales de un campo escalar (nombre de variable, DataArray o array por nodo). Unidades: [f]/m."""
    Gx, Gy = gradient_operators(ds)
    f = _nodal(ds, f)
    return _apply(Gx, f), _apply(Gy, f)


def _vector(ds: xr.Dataset, var: str, layer=None, time=None) -> tuple[xr.DataArray, xr.DataArray]:
    """Componentes (X, Y) de una variable vectorial de SCHISM ('depthAverageVel', 'horizontalVel', 'windStress'...)."""
    if var + "X" not in ds:
        raise KeyError(f"no hay variable vectorial {var} (hacen falta {var}X y {var}Y en las salidas)")
    u, v = ds[var + "X"], ds[var + "Y"]
    if "layer" in u.dims:
        if layer is None:
            raise ValueError(f"{var} es 3D: indica layer (índice sigma, -1 = superficie) o usa transport()")
        u, v = u.isel(layer=layer), v.isel(layer=layer)
    if time is not None and "time" in u.dims:
        u, v = u.isel(time=time), v.isel(time=time)
    bad = (u.values < FILL) | (v.values < FILL)
    return u.where(~bad), v.where(~bad)


def curl(ds: xr.Dataset, u, v) -> xr.DataArray:
    """dv/dx - du/dy de un campo vectorial nodal (arrays, DataArrays o nombres)."""
    Gx, Gy = gradient_operators(ds)
    return _apply(Gx, _nodal(ds, v)) - _apply(Gy, _nodal(ds, u))


def div(ds: xr.Dataset, u, v) -> xr.DataArray:
    """du/dx + dv/dy de un campo vectorial nodal."""
    Gx, Gy = gradient_operators(ds)
    return _apply(Gx, _nodal(ds, u)) + _apply(Gy, _nodal(ds, v))


def vorticity(ds: xr.Dataset, var: str = "depthAverageVel", layer=None, time=None) -> xr.DataArray:
    """Vorticidad relativa zeta = dv/dx - du/dy (1/s) de la velocidad promediada ('depthAverageVel') o de una capa de
    'horizontalVel' (layer). Para el rotacional del esfuerzo del viento usa curl(ds, 'windStressX', 'windStressY')."""
    u, v = _vector(ds, var, layer, time)
    out = curl(ds, u, v)
    return out.rename("vorticity").assign_attrs(units="1/s", long_name=f"vorticidad relativa de {var}")


def divergence(ds: xr.Dataset, var: str = "depthAverageVel", layer=None, time=None) -> xr.DataArray:
    u, v = _vector(ds, var, layer, time)
    return div(ds, u, v).rename("divergence").assign_attrs(units="1/s", long_name=f"divergencia de {var}")


def stress_pa(ds: xr.Dataset) -> tuple[xr.DataArray, xr.DataArray]:
    """(tau_x, tau_y) en Pa a partir de la salida windStress (tau/rho_w)."""
    u, v = _vector(ds, "windStress")
    return (u * RHO_WATER).assign_attrs(units="Pa"), (v * RHO_WATER).assign_attrs(units="Pa")


def ekman_pumping(ds: xr.Dataset, rho: float = RHO_WATER) -> xr.DataArray:
    """w_E = rot(tau)/(rho f) (m/s), con f de la latitud de cada nodo (dominios lon/lat) o de ds.attrs['coriolis']."""
    tx, ty = stress_pa(ds)
    c = curl(ds, tx, ty)
    f = coriolis(ds)
    return (c / (rho * f)).rename("ekman_pumping").assign_attrs(units="m/s")


def coriolis(ds: xr.Dataset) -> xr.DataArray:
    """Parámetro de Coriolis por nodo: 2 Omega sin(lat) en lon/lat; en cartesiano, ds.attrs['coriolis'] (número)."""
    from .sections import is_geographic
    if is_geographic(ds):
        return xr.DataArray(2 * 7.292115e-5 * np.sin(np.deg2rad(ds.y.values)), dims=("node",))
    if "coriolis" in ds.attrs:
        return xr.DataArray(np.full(ds.sizes["node"], float(ds.attrs["coriolis"])), dims=("node",))
    raise ValueError("dominio cartesiano: indica f en ds.attrs['coriolis'] (1/s)")


def transport(ds: xr.Dataset, time=None, vg=None) -> tuple[xr.DataArray, xr.DataArray]:
    """Transporte integrado en la vertical (U, V) en m²/s: integral de horizontalVel en z (zCoordinates o malla vertical
    vg; sin ellas, la de la simulación) o, si solo hay depthAverageVel, velocidad media por (h + eta)."""
    if vg is None and "horizontalVelX" in ds and "zCoordinates" not in ds:
        from .output import auto_vgrid
        vg = auto_vgrid(ds)
    if "horizontalVelX" in ds and ("zCoordinates" in ds or vg is not None):
        u, v = ds.horizontalVelX, ds.horizontalVelY
        if time is not None:
            u, v = u.isel(time=time), v.isel(time=time)
        z = _zcor(ds, time, vg)
        bad = (u.values < FILL) | (v.values < FILL) | ~np.isfinite(z)
        uu = np.where(bad, np.nan, u.values); vv = np.where(bad, np.nan, v.values); zz = np.where(bad, np.nan, z)
        dz = np.diff(zz, axis=-1)                                     # (…, node, nvrt-1)
        U = np.nansum(0.5 * (uu[..., 1:] + uu[..., :-1]) * dz, axis=-1)
        V = np.nansum(0.5 * (vv[..., 1:] + vv[..., :-1]) * dz, axis=-1)
        dims = tuple(d for d in u.dims if d != "layer")
    elif "depthAverageVelX" in ds:
        u, v = _vector(ds, "depthAverageVel", time=time)
        eta = ds.elevation.isel(time=time) if (time is not None and "elevation" in ds) else ds.get("elevation", 0.0)
        H = (ds.depth + eta).clip(min=0.0)
        U, V, dims = (u * H).values, (v * H).values, u.dims
    else:
        raise KeyError("hacen falta horizontalVel (+ zCoordinates o vg) o depthAverageVel en las salidas")
    co = {k: c for k, c in ds.coords.items() if set(c.dims) <= set(dims)}
    return (xr.DataArray(U, dims=dims, coords=co, name="transportX").assign_attrs(units="m2/s"),
            xr.DataArray(V, dims=dims, coords=co, name="transportY").assign_attrs(units="m2/s"))


def _zcor(ds: xr.Dataset, time, vg) -> np.ndarray:
    if "zCoordinates" in ds:
        z = ds.zCoordinates.isel(time=time).values if time is not None else ds.zCoordinates.values
        return np.where(z < FILL, np.nan, z.astype(float))
    eta = ds.elevation.values if "elevation" in ds else np.zeros(ds.sizes["node"])
    if time is not None and eta.ndim == 2:
        eta = eta[time]
    h = np.nan_to_num(ds.depth.values, nan=1.0)
    if eta.ndim == 2:
        return np.stack([vg.zcor(h, np.nan_to_num(e)) for e in eta])
    return vg.zcor(h, np.nan_to_num(eta))


def boundary_nodes(ds: xr.Dataset) -> np.ndarray:
    """Índices de los nodos del contorno (aristas que pertenecen a un solo elemento)."""
    el = _elements(ds)
    e = np.sort(np.concatenate([el[:, [0, 1]], el[:, [1, 2]], el[:, [2, 0]]]), axis=1)
    _, idx, cnt = np.unique(e, axis=0, return_index=True, return_counts=True)
    return np.unique(e[idx[cnt == 1]].ravel())


def streamfunction(ds: xr.Dataset, U, V, check: bool = True) -> xr.DataArray:
    """Función de corriente psi (m³/s) del transporte (U, V) con U = -dpsi/dy, V = dpsi/dx: resuelve
    lap(psi) = dV/dx - dU/dy por elementos finitos P1 con psi = 0 en todo el contorno.

    Solo tiene sentido en cuencas CERRADAS y sin islas (psi constante en cada trozo de contorno, aquí 0): con contornos
    abiertos o flujo neto a través del borde se avisa, porque el resultado no es la función de corriente real.
    U, V admiten dimensión time (una resolución por instante)."""
    U, V = _nodal(ds, U), _nodal(ds, V)
    xm, ym, el, area, bx, by = _geometry(ds)
    n, ne = xm.size, el.shape[0]
    rows = np.repeat(el, 3, axis=1).ravel(); cols = np.tile(el, (1, 3)).ravel()
    K = np.einsum("ei,ej->eij", bx, bx) + np.einsum("ei,ej->eij", by, by)       # rigidez P1
    K = sparse.csr_matrix(((K * area[:, None, None]).ravel(), (rows, cols)), shape=(n, n))
    bnd = boundary_nodes(ds); interior = np.setdiff1d(np.arange(n), bnd)
    Kii = K[interior][:, interior].tocsc()
    extra = [d for d in U.dims if d != "node"]
    Ust = U.stack(_k=extra) if extra else U.expand_dims("_k", -1)
    Vst = V.stack(_k=extra) if extra else V.expand_dims("_k", -1)
    out = np.zeros((n, Ust.sizes["_k"]))
    from scipy.sparse.linalg import spsolve
    for k in range(Ust.sizes["_k"]):
        u = np.nan_to_num(Ust.isel(_k=k).values); v = np.nan_to_num(Vst.isel(_k=k).values)
        ue, ve = u[el].mean(axis=1), v[el].mean(axis=1)                        # valor medio por elemento
        # forma débil (phi = 0 en el contorno): ∫ lap(psi) phi = -K psi  y  ∫ (dV/dx - dU/dy) phi = -∫ (V dphi/dx - U dphi/dy)
        #   => K psi = ∫ (V dphi/dx - U dphi/dy)
        rhs = np.zeros(n)
        np.add.at(rhs, el.ravel(), ((ve[:, None] * bx - ue[:, None] * by) * area[:, None]).ravel())
        if check:
            _warn_open(ds, u, v, bnd, xm, ym, el)
        out[interior, k] = spsolve(Kii, rhs[interior])
    psi = xr.DataArray(out.reshape((n,) + tuple(Ust.sizes[d] for d in ["_k"])), dims=("node", "_k"))
    if extra:
        psi = psi.assign_coords(_k=Ust["_k"]).unstack("_k")
    else:
        psi = psi.isel(_k=0)
    co = {k: c for k, c in U.coords.items() if set(c.dims) <= set(psi.dims)}
    return psi.transpose(*U.dims).assign_coords(co).rename("streamfunction").assign_attrs(units="m3/s")


def _warn_open(ds, u, v, bnd, xm, ym, el):
    """Aviso si hay flujo neto apreciable a través del contorno (dominio abierto): psi = 0 en el borde no es válido."""
    e = np.sort(np.concatenate([el[:, [0, 1]], el[:, [1, 2]], el[:, [2, 0]]]), axis=1)
    _, idx, cnt = np.unique(e, axis=0, return_index=True, return_counts=True)
    be = e[idx[cnt == 1]]
    dx, dy = xm[be[:, 1]] - xm[be[:, 0]], ym[be[:, 1]] - ym[be[:, 0]]
    ub, vb = 0.5 * (u[be[:, 0]] + u[be[:, 1]]), 0.5 * (v[be[:, 0]] + v[be[:, 1]])
    flux = np.abs(ub * dy - vb * dx)                                            # |U·n| ds por arista (signo aparte)
    scale = np.hypot(u, v).max() * np.hypot(dx, dy).sum() + 1e-30
    if flux.sum() / scale > 0.05:
        log.warning("streamfunction: flujo a través del contorno (%.0f %% de la escala): el dominio parece abierto y "
                    "psi = 0 en el borde no es válido", 100 * flux.sum() / scale)
