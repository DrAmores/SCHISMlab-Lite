"""Secciones verticales sobre la malla (cortes arbitrarios, transversales y longitudinales), con velocidad proyectada
y diagramas de Hovmöller. Núcleo sin interfaz: lo usan la GUI y los notebooks.

Convenciones: nivel 0 = fondo, último nivel = superficie (como en las salidas de SCHISM). Los valores de los
niveles por debajo del fondo (mallas SZ) se tratan como NaN."""
from __future__ import annotations
import numpy as np
import xarray as xr
import matplotlib.tri as mtri

R_EARTH = 6371e3
FILL = -9000.0                      # SCHISM rellena con -9999 los niveles bajo el fondo


def is_geographic(ds: xr.Dataset) -> bool:
    return bool(np.abs(ds.x.values).max() <= 360 and np.abs(ds.y.values).max() <= 90.5)


def metric_xy(ds: xr.Dataset, x, y):
    """Coordenadas en metros (equirrectangular local) para medir distancias y direcciones."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if is_geographic(ds):
        lat0 = np.deg2rad(float(ds.y.values.mean()))
        return np.deg2rad(x) * R_EARTH * np.cos(lat0), np.deg2rad(y) * R_EARTH
    return x, y


def principal_axis(ds: xr.Dataset) -> float:
    """Dirección (radianes desde el este) de máxima varianza de los nodos: eje largo de un canal o estuario."""
    xm, ym = metric_xy(ds, ds.x.values, ds.y.values)
    c = np.cov(np.vstack([xm - xm.mean(), ym - ym.mean()]))
    w, v = np.linalg.eigh(c)
    ax = v[:, np.argmax(w)]
    return float(np.arctan2(ax[1], ax[0]))


def preset_section(ds: xr.Dataset, point, kind: str = "transversal", pad: float = 0.0):
    """Recta por `point` (lon/lat o x/y) a lo largo del eje principal (longitudinal) o perpendicular (transversal),
    recortada al rectángulo del dominio (de borde a borde: llega a la costa o a la pared). Devuelve (p0, p1) en las
    coordenadas de la malla, orientada de oeste a este si es más zonal que meridiana y de sur a norte si no (así la
    distancia 0 es siempre el extremo oeste o sur)."""
    th = principal_axis(ds)
    if kind == "transversal":
        th += np.pi / 2
    elif kind == "x":
        th = 0.0
    elif kind == "y":
        th = np.pi / 2
    x0, y0 = float(point[0]), float(point[1])
    xmn, xmx, ymn, ymx = float(ds.x.min()), float(ds.x.max()), float(ds.y.min()), float(ds.y.max())
    ex, ey = np.cos(th), np.sin(th)
    if is_geographic(ds):                            # dirección en grados: misma dirección geométrica en metros
        ex = ex / np.cos(np.deg2rad(y0))
    ts = []
    for lim, c0, e in ((xmn, x0, ex), (xmx, x0, ex), (ymn, y0, ey), (ymx, y0, ey)):
        if abs(e) > 1e-12:
            ts.append((lim - c0) / e)
    tneg = max(t for t in ts if t <= 0) if any(t <= 0 for t in ts) else 0.0
    tpos = min(t for t in ts if t >= 0) if any(t >= 0 for t in ts) else 0.0
    L = tpos - tneg
    pad = max(float(pad), 1e-6)                      # un pelo hacia dentro: el extremo cae en un triángulo de la malla
    p0 = (x0 + ex * (tneg + pad * L), y0 + ey * (tneg + pad * L))
    p1 = (x0 + ex * (tpos - pad * L), y0 + ey * (tpos - pad * L))
    xm, ym = metric_xy(ds, [p0[0], p1[0]], [p0[1], p1[1]])
    dx, dy = xm[1] - xm[0], ym[1] - ym[0]
    if (abs(dx) >= abs(dy) and dx < 0) or (abs(dy) > abs(dx) and dy < 0):
        p0, p1 = p1, p0
    return p0, p1


def compass(dx: float, dy: float, lang: str = "es") -> str:
    """Rumbo de 8 puntos (N, NE, E, SE, S, SO/SW, O/W, NO/NW) de un vector (este, norte)."""
    names = ["E", "NE", "N", "NO", "O", "SO", "S", "SE"] if lang == "es" else ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]
    k = int(np.round(np.arctan2(dy, dx) / (np.pi / 4))) % 8
    return names[k]


def auto_npts(ds, tri, p0, p1, nmin: int = 120, nmax: int = 2000) -> int:
    """Puntos de una sección: dos por elemento en el tramo de malla más fino que cruza (aristas en m), entre nmin y nmax.
    Con 120 fijos, una sección de 1000 km sobre una plataforma de 2 km recortaba un pulso de 20 km de ancho."""
    xs = np.linspace(p0[0], p1[0], 400); ys = np.linspace(p0[1], p1[1], 400)
    ie = tri.get_trifinder()(xs, ys); ie = np.unique(ie[ie >= 0])
    if ie.size == 0:
        return nmin
    vx, vy = metric_xy(ds, ds.x.values[tri.triangles[ie]].ravel(), ds.y.values[tri.triangles[ie]].ravel())
    vx = vx.reshape(-1, 3); vy = vy.reshape(-1, 3)
    edge = np.max(np.hypot(vx - np.roll(vx, 1, axis=1), vy - np.roll(vy, 1, axis=1)), axis=1)
    h = float(np.percentile(edge, 5))
    mx, my = metric_xy(ds, np.array([p0[0], p1[0]]), np.array([p0[1], p1[1]]))
    L = float(np.hypot(mx[1] - mx[0], my[1] - my[0]))
    return int(np.clip(np.ceil(2.0 * L / max(h, 1e-6)) + 1, nmin, nmax))


class Section:
    """Corte vertical a lo largo de la recta p0-p1 con `npts` puntos (interpolación lineal en cada triángulo)."""

    def __init__(self, ds: xr.Dataset, p0, p1, npts: int | None = None, vg=None, tri=None):
        """`tri`: Triangulation de matplotlib ya construida (con su buscador) para reutilizarla entre secciones.
        `npts`: puntos del corte; None = según la longitud y la malla (dos por elemento del tramo más fino, 120–2000)."""
        self.ds, self.vg = ds, vg
        self.p0, self.p1 = (float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1]))
        tri = tri if tri is not None else mtri.Triangulation(ds.x.values, ds.y.values, ds.attrs["elements"])
        if npts is None:
            npts = auto_npts(ds, tri, self.p0, self.p1)
        self.xs = np.linspace(self.p0[0], self.p1[0], npts); self.ys = np.linspace(self.p0[1], self.p1[1], npts)
        xm, ym = metric_xy(ds, self.xs, self.ys)
        self.dist = np.hypot(xm - xm[0], ym - ym[0]) / 1e3                      # km
        dx, dy = xm[-1] - xm[0], ym[-1] - ym[0]
        L = max(np.hypot(dx, dy), 1e-9)
        self.tangent = (dx / L, dy / L)                                           # (este, norte)
        self.normal = (-dy / L, dx / L)                                           # a la izquierda del avance
        finder = tri.get_trifinder()                                              # matplotlib lo cachea en la triangulación
        ie = finder(self.xs, self.ys)
        self.inside = ie >= 0
        self.idx = np.where(self.inside[:, None], tri.triangles[np.maximum(ie, 0)], 0)
        # pesos baricéntricos
        xa, ya = ds.x.values[self.idx], ds.y.values[self.idx]
        det = (ya[:, 1] - ya[:, 2]) * (xa[:, 0] - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (ya[:, 0] - ya[:, 2])
        det = np.where(np.abs(det) < 1e-30, 1.0, det)
        w0 = ((ya[:, 1] - ya[:, 2]) * (self.xs - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (self.ys - ya[:, 2])) / det
        w1 = ((ya[:, 2] - ya[:, 0]) * (self.xs - xa[:, 2]) + (xa[:, 0] - xa[:, 2]) * (self.ys - ya[:, 2])) / det
        self.w = np.clip(np.stack([w0, w1, 1 - w0 - w1], 1), 0, 1)
        self.w /= np.maximum(self.w.sum(1, keepdims=True), 1e-12)
        self.depth = self.interp(ds.depth.values)
        self.depth[~self.inside] = np.nan

    # ---------------------------------------------------------------- interpolación
    def interp(self, values: np.ndarray) -> np.ndarray:
        """Interpola un campo nodal (nodos) o (nodos, niveles) a los puntos de la sección."""
        v = np.asarray(values, float)
        v = np.where(v < FILL, np.nan, v)
        if v.ndim == 1:
            out = (v[self.idx] * self.w).sum(1)
        else:
            out = (v[self.idx] * self.w[:, :, None]).sum(1)
        out[~self.inside] = np.nan
        return out

    def _node_field(self, var: str, it: int) -> np.ndarray:
        ds = self.ds
        if var in ds:
            return ds[var].isel(time=it).values
        if var + "X" in ds:
            return np.hypot(ds[var + "X"].isel(time=it).values, ds[var + "Y"].isel(time=it).values)
        raise KeyError(var)

    def z(self, it: int) -> np.ndarray:
        """Cotas z (npts, nvrt) en el instante `it`: de zCoordinates si se guardó; si no, de la malla vertical y η."""
        ds = self.ds
        if "zCoordinates" in ds:
            return self.interp(ds.zCoordinates.isel(time=it).values)
        if self.vg is None:
            from .output import auto_vgrid
            self.vg = auto_vgrid(ds)                          # la de la simulación (caso.yaml / vgrid.in)
        if self.vg is None:
            raise ValueError("hace falta la malla vertical (vg) o la salida zCoordinates")
        eta = self.interp(ds.elevation.isel(time=it).values) if "elevation" in ds else np.zeros_like(self.depth)
        return self.vg.zcor(np.nan_to_num(self.depth, nan=1.0), np.nan_to_num(eta))

    def scalar(self, var: str, it: int) -> np.ndarray:
        """Valores (npts, nvrt) de `var` (o módulo si es vector); (npts,) si la variable es 2D."""
        return self.interp(self._node_field(var, it))

    def velocity(self, it: int):
        """(u_s, u_n, w) en (npts, nvrt): componente a lo largo de la sección, normal (positiva a la izquierda) y
        vertical (None si no se guardó verticalVelocity)."""
        ds = self.ds
        name = "horizontalVel" if "horizontalVelX" in ds else "depthAverageVel"
        u = self.interp(ds[name + "X"].isel(time=it).values); v = self.interp(ds[name + "Y"].isel(time=it).values)
        us = u * self.tangent[0] + v * self.tangent[1]
        un = u * self.normal[0] + v * self.normal[1]
        w = self.interp(ds.verticalVelocity.isel(time=it).values) if "verticalVelocity" in ds else None
        return us, un, w

    def regular(self, F: np.ndarray, z: np.ndarray, nz: int = 80):
        """Remuestrea (npts, nvrt) sobre una rejilla regular en z: (zi, Z[nz, npts]) con NaN bajo el fondo."""
        zmin = float(np.nanmin(-self.depth)) if np.isfinite(self.depth).any() else -1.0
        zmax = float(np.nanmax(z)) if np.isfinite(z).any() else 0.0
        zi = np.linspace(zmin, max(zmax, 0.0), nz)
        Z = np.full((nz, F.shape[0]), np.nan)
        for i in range(F.shape[0]):
            if not self.inside[i] or not np.isfinite(F[i]).any():
                continue
            ok = np.isfinite(z[i]) & np.isfinite(F[i])
            if ok.sum() >= 2:
                zk, fk = z[i][ok], F[i][ok]
                Z[:, i] = np.interp(np.clip(zi, zk.min(), zk.max()), zk, fk)
                Z[zi < zk.min() - 1e-3, i] = np.nan      # bajo el fondo (sobre la superficie se repite el valor superficial)
        return zi, Z

    def iso_depth(self, var: str, value: float, it: int, which: str = "shallowest") -> np.ndarray:
        """Profundidad (m, +abajo) de la isosuperficie var = value a lo largo de la sección (npts,)."""
        from .isosurface import section_iso_depth
        return section_iso_depth(self, var, value, it, which)

    def iso_hovmoller(self, var: str, value: float, which: str = "shallowest") -> np.ndarray:
        """h(x, t): matriz (tiempo, distancia) de la profundidad de la isosuperficie var = value."""
        from .isosurface import section_iso_hovmoller
        return section_iso_hovmoller(self, var, value, which)

    def hovmoller(self, var: str, layer: int = -1) -> np.ndarray:
        """Matriz (tiempo, distancia) de `var` en la capa `layer` (o 2D)."""
        ds = self.ds
        if var in ds:
            da = ds[var]
        else:
            da = np.hypot(ds[var + "X"], ds[var + "Y"])
        if "layer" in da.dims:
            da = da.isel(layer=layer)
        return np.stack([self.interp(da.isel(time=it).values) for it in range(ds.time.size)])

    def at_depth(self, F: np.ndarray, z: np.ndarray, depth_m: float) -> np.ndarray:
        """Valor de un campo (npts, nvrt) a la profundidad fija `depth_m` (m, positiva hacia abajo)."""
        return interp_at_depth(F, z, depth_m)


def interp_at_depth(v: np.ndarray, z: np.ndarray, depth_m: float) -> np.ndarray:
    """Interpola columnas (n, nvrt) con cotas z crecientes (fondo -> superficie) a la cota -depth_m; NaN donde el
    fondo es más somero. Vectorizado: O(n·nvrt)."""
    v = np.asarray(v, float); z = np.asarray(z, float)
    zt = -float(depth_m)
    zz = np.where(np.isfinite(z) & np.isfinite(v), z, -np.inf)          # niveles inválidos bajo el fondo: fuera
    k = np.clip((zz <= zt).sum(1), 1, z.shape[1] - 1)                    # primer nivel por encima del objetivo
    r = np.arange(z.shape[0])
    z0, z1, v0, v1 = zz[r, k - 1], zz[r, k], v[r, k - 1], v[r, k]
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.clip((zt - z0) / (z1 - z0), 0.0, 1.0)
    out = v0 + f * (v1 - v0)
    valid = np.isfinite(zz).any(1)
    zmin = np.where(valid, np.min(np.where(np.isfinite(zz), zz, np.inf), axis=1), np.nan)
    zmax = np.nanmax(np.where(np.isfinite(zz), zz, -np.inf), axis=1)
    out[(zt < zmin) | (zt > zmax) | ~valid | ~np.isfinite(out)] = np.nan
    return out


def field_at_depth(ds: xr.Dataset, var: str, it: int, depth_m: float, vg=None) -> np.ndarray:
    """Campo nodal 3D interpolado a la profundidad fija `depth_m` en el instante `it` (NaN donde el fondo es más somero)."""
    v = ds[var].isel(time=it).values.astype(float)
    v = np.where(v < FILL, np.nan, v)
    if "zCoordinates" in ds:
        z = ds.zCoordinates.isel(time=it).values.astype(float); z = np.where(z < FILL, np.nan, z)
    else:
        if vg is None:
            from .output import auto_vgrid
            vg = auto_vgrid(ds)
        if vg is None:
            raise ValueError("hace falta la malla vertical (vg) o la salida zCoordinates")
        eta = ds.elevation.isel(time=it).values if "elevation" in ds else np.zeros(ds.sizes["node"])
        z = vg.zcor(ds.depth.values, eta)
    return interp_at_depth(v, z, depth_m)
