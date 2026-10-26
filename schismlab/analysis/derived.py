"""Variables derivadas y promedios temporales para la interfaz (Mapas, Secciones, Puntos): vorticidad ζ y ζ/f,
transporte integrado en la vertical y función de corriente, componentes con signo (u, v; normal y tangencial en las
secciones) y promedio de las salidas entre dos instantes. Núcleo sin interfaz: la GUI solo elige qué pedir.

Convenciones:
- `its` es una lista de índices de tiempo; con varios, el campo es la media de esos instantes (promedio temporal).
- Variables 3D: `layer` (índice, 0 = fondo, -1 = superficie) o `depth` (m, positiva hacia abajo).
- Componentes: "mag" (módulo), "u" (este), "v" (norte). La GUI proyecta u, v sobre una sección para normal/tangencial.
- Unidades: vorticidad 1/s; ζ/f adimensional; transporte m²/s; función de corriente Sv (10⁶ m³/s).
"""
from __future__ import annotations
import numpy as np
import xarray as xr
from .sections import FILL

# nombre -> (es vector, unidades, descripción corta)
DERIVED = {
    "vorticity": (False, "1/s", "ζ = ∂v/∂x − ∂u/∂y"),
    "vorticity_f": (False, "", "ζ/f"),
    "transport": (True, "m²/s", "transporte (U, V) = ∫ (u, v) dz"),
    "streamfunction": (False, "Sv", "ψ del transporte (U = −∂ψ/∂y, V = ∂ψ/∂x)"),
}
COMPONENTS = ("mag", "u", "v")


def time_window(times, t1, t2) -> np.ndarray:
    """Índices de las salidas con t1 <= t <= t2 (fechas en texto o datetime64). Vacío si no hay ninguna."""
    tt = np.asarray(times).astype("datetime64[s]")
    a = np.datetime64(str(t1).strip().replace(" ", "T"), "s"); b = np.datetime64(str(t2).strip().replace(" ", "T"), "s")
    if b < a:
        a, b = b, a
    return np.where((tt >= a) & (tt <= b))[0]


def _clean(a):
    a = np.asarray(a, float)
    return np.where(a < FILL, np.nan, a)


class Fields:
    """Campos nodales (originales y derivados) de una simulación, con componentes y promedios temporales.

    f: parámetro de Coriolis por nodo (1/s) o None (sin rotación: no hay ζ/f)."""

    def __init__(self, ds: xr.Dataset, vg=None, f=None):
        self.ds, self.vg = ds, vg
        self.f = None if f is None else np.asarray(f, float)
        self._ops = None; self._cache = {}
        vel = self.velocity_name()
        nn, nt, nl = ds.sizes.get("node", 0), ds.sizes.get("time", 1), max(1, ds.sizes.get("layer", 1))
        # mallas grandes (Pro, p. ej. 800 000 nodos): nada de campos de todos los instantes en memoria, y sin ψ (habría
        # que factorizar un sistema enorme y además los dominios reales son abiertos)
        self.all_ok = nn * nt <= 5e7
        self.transport_all_ok = nn * nt * nl <= 2e8
        self.available = []
        if vel:
            self.available += ["vorticity"] + (["vorticity_f"] if self.f is not None and np.all(np.abs(self.f) > 1e-12) else [])
            self.available += ["transport"] + (["streamfunction"] if nn <= 200_000 else [])

    # ------------------------------------------------------------------ descripción
    def velocity_name(self) -> str | None:
        ds = self.ds
        return "horizontalVel" if "horizontalVelX" in ds else ("depthAverageVel" if "depthAverageVelX" in ds else None)

    def is_derived(self, var: str) -> bool:
        return var in DERIVED

    def is_vector(self, var: str) -> bool:
        return DERIVED[var][0] if var in DERIVED else (var + "X") in self.ds

    def is3d(self, var: str) -> bool:
        if var in ("vorticity", "vorticity_f"):
            return self.velocity_name() == "horizontalVel"
        if var in DERIVED:
            return False
        name = var + "X" if var + "X" in self.ds else var
        return name in self.ds and "layer" in self.ds[name].dims

    def units(self, var: str) -> str:
        if var in DERIVED:
            return DERIVED[var][1]
        return str(self.ds[var + "X" if var + "X" in self.ds else var].attrs.get("units", ""))

    # ------------------------------------------------------------------ operadores (cacheados)
    def _grad_ops(self):
        if self._ops is None:
            from .dynamics import gradient_operators
            self._ops = gradient_operators(self.ds)
        return self._ops

    def _curl(self, u, v):
        Gx, Gy = self._grad_ops()
        u = np.nan_to_num(np.asarray(u, float)); v = np.nan_to_num(np.asarray(v, float))
        if u.ndim == 1:
            return Gx @ v - Gy @ u
        return (Gx @ v - Gy @ u)                                         # (node, nvrt): columnas por nivel

    # ------------------------------------------------------------------ campos de un instante
    def _raw(self, name: str, it: int):
        return _clean(self.ds[name].isel(time=it).values)

    def _level(self, a, layer, depth, it):
        """(node,) de un campo (node, nvrt) en el nivel `layer` o a la profundidad `depth`."""
        a = np.asarray(a, float)
        if a.ndim == 1:
            return a
        if depth is not None:
            from .sections import interp_at_depth
            return interp_at_depth(a, self.zcor(it), float(depth))
        return a[:, -1 if layer is None else int(layer)]

    def zcor(self, it: int) -> np.ndarray:
        ds = self.ds
        if "zCoordinates" in ds:
            return _clean(ds.zCoordinates.isel(time=it).values)
        if self.vg is None:
            from .output import auto_vgrid
            self.vg = auto_vgrid(ds)
        eta = ds.elevation.isel(time=it).values if "elevation" in ds else np.zeros(ds.sizes["node"])
        return self.vg.zcor(np.nan_to_num(ds.depth.values, nan=1.0), np.nan_to_num(eta))

    def _transport_all(self):
        """(U, V) de todos los instantes (time, node), calculado una vez con la integral vectorizada."""
        if "T_all" not in self._cache:
            from .dynamics import transport
            U, V = transport(self.ds, vg=self.vg)
            self._cache["T_all"] = (np.asarray(U.values, float), np.asarray(V.values, float))
        return self._cache["T_all"]

    def transport_uv(self, it: int):
        if self.transport_all_ok:
            U, V = self._transport_all()
            return U[int(it)], V[int(it)]
        key = ("T", int(it))                                             # malla grande: un instante cada vez
        if key not in self._cache:
            from .dynamics import transport
            for k in [k for k in self._cache if isinstance(k, tuple) and k[0] == "T"][:-8]:
                self._cache.pop(k)
            U, V = transport(self.ds, time=int(it), vg=self.vg)
            self._cache[key] = (np.asarray(U.values, float), np.asarray(V.values, float))
        return self._cache[key]

    def _all(self, var: str, layer=None, depth=None) -> np.ndarray:
        """Campo (time, node) de una variable derivada escalar en el nivel pedido, calculado una vez (series)."""
        key = ("all", var, layer, depth)
        if key not in self._cache:
            for k in [k for k in self._cache if isinstance(k, tuple) and k[0] == "all"][:-3]:
                self._cache.pop(k)                                       # memoria acotada: las últimas variables
            if var in ("vorticity", "vorticity_f") and depth is None:  # vía rápida: ζ es lineal, todos los instantes a la vez
                name = self.velocity_name()
                U, V = self.ds[name + "X"], self.ds[name + "Y"]
                if "layer" in U.dims:
                    U, V = U.isel(layer=-1 if layer is None else int(layer)), V.isel(layer=-1 if layer is None else int(layer))
                Gx, Gy = self._grad_ops()
                u = np.nan_to_num(_clean(U.values)); v = np.nan_to_num(_clean(V.values))   # (time, node)
                z = (Gx @ v.T - Gy @ u.T).T
                self._cache[key] = z / self.f[None, :] if var == "vorticity_f" else z
            else:
                self._cache[key] = np.stack([self._level(self.column(var, i), layer, depth, i) for i in range(self.ds.time.size)])
        return self._cache[key]

    def vector_uv(self, var: str, it: int):
        """(u, v) nodales del vector `var` en el instante: (node,) o (node, nvrt) si es 3D."""
        if var == "transport":
            return self.transport_uv(it)
        return self._raw(var + "X", it), self._raw(var + "Y", it)

    def column(self, var: str, it: int, comp: str = "mag"):
        """Campo de un instante: (node, nvrt) si es 3D, (node,) si es 2D. Vectores: módulo o componente."""
        if var in ("vorticity", "vorticity_f"):
            u, v = self.vector_uv(self.velocity_name(), it)
            z = self._curl(u, v)
            if var == "vorticity_f":
                z = z / (self.f if z.ndim == 1 else self.f[:, None])
            return z
        if var == "streamfunction":
            return self.streamfunction_of(*self.transport_uv(it))
        if self.is_vector(var):
            u, v = self.vector_uv(var, it)
            return {"u": u, "v": v}.get(comp, np.hypot(u, v)) if comp in ("u", "v") else np.hypot(u, v)
        return self._raw(var, it)

    def _psi_solver(self):
        """Factorización (una vez) del problema de ψ de dynamics.streamfunction: K ψ = ∫ (V ∂φ/∂x − U ∂φ/∂y), ψ = 0 en
        el contorno. Devuelve una función (U, V) -> ψ (m³/s)."""
        if getattr(self, "_psi", None) is None:
            from scipy import sparse
            from scipy.sparse.linalg import splu
            from .dynamics import _geometry, boundary_nodes
            xm, ym, el, area, bx, by = _geometry(self.ds)
            n = xm.size
            rows = np.repeat(el, 3, axis=1).ravel(); cols = np.tile(el, (1, 3)).ravel()
            K = np.einsum("ei,ej->eij", bx, bx) + np.einsum("ei,ej->eij", by, by)
            K = sparse.csr_matrix(((K * area[:, None, None]).ravel(), (rows, cols)), shape=(n, n))
            interior = np.setdiff1d(np.arange(n), boundary_nodes(self.ds))
            lu = splu(K[interior][:, interior].tocsc())

            def solve(U, V):
                U = np.nan_to_num(np.asarray(U, float)); V = np.nan_to_num(np.asarray(V, float))
                ue, ve = U[el].mean(axis=1), V[el].mean(axis=1)
                rhs = np.zeros(n)
                np.add.at(rhs, el.ravel(), ((ve[:, None] * bx - ue[:, None] * by) * area[:, None]).ravel())
                out = np.zeros(n); out[interior] = lu.solve(rhs[interior])
                return out
            self._psi = solve
        return self._psi

    def streamfunction_of(self, U, V) -> np.ndarray:
        """ψ (Sv) de un transporte nodal (U, V) con ψ = 0 en el contorno (cuencas cerradas): el mismo cálculo que
        dynamics.streamfunction, con la matriz factorizada una sola vez."""
        return self._psi_solver()(U, V) / 1e6

    def _psi_all(self) -> np.ndarray:
        """ψ (Sv) de todos los instantes (time, node), calculado una vez (series en los puntos)."""
        if "psi_all" not in self._cache:
            self._cache["psi_all"] = np.stack([self.streamfunction_of(*self.transport_uv(i)) for i in range(self.ds.time.size)])
        return self._cache["psi_all"]

    # ------------------------------------------------------------------ con promedio temporal
    def nodal(self, var: str, its, layer=None, depth=None, comp: str = "mag") -> np.ndarray:
        """Campo nodal (node,) de `var` en el nivel pedido, promediado en los instantes `its` (uno = sin promedio).
        Con promedio, el módulo de un vector es el de la media (|⟨v⟩|) y ψ se calcula del transporte medio."""
        its = [int(i) for i in np.atleast_1d(its)]
        if var == "streamfunction":
            U = np.mean([self.transport_uv(i)[0] for i in its], axis=0); V = np.mean([self.transport_uv(i)[1] for i in its], axis=0)
            return self.streamfunction_of(U, V)
        if self.is_vector(var) and comp == "mag":
            u = np.nanmean([self._level(self.column(var, i, "u"), layer, depth, i) for i in its], axis=0)
            v = np.nanmean([self._level(self.column(var, i, "v"), layer, depth, i) for i in its], axis=0)
            return np.hypot(u, v)
        if var in ("vorticity", "vorticity_f") and depth is None and self.all_ok and (len(its) > 1 or ("all", var, layer, None) in self._cache):
            return np.nanmean(self._all(var, layer)[its], axis=0)          # media de ζ = ζ de la media (lineal)
        if len(its) == 1:
            return self._level(self.column(var, its[0], comp), layer, depth, its[0])
        if (not self.is_derived(var) and depth is None and not self.is_vector(var)):          # vía rápida: xarray
            da = self.ds[var].isel(time=its)
            if "layer" in da.dims:
                da = da.isel(layer=-1 if layer is None else int(layer))
            return np.nanmean(_clean(da.values), axis=0)
        return np.nanmean([self._level(self.column(var, i, comp), layer, depth, i) for i in its], axis=0)

    def columns(self, var: str, its, comp: str = "mag"):
        """(node, nvrt) o (node,) promediado en `its`; para vectores con comp="uv" devuelve (u, v)."""
        its = [int(i) for i in np.atleast_1d(its)]
        if comp == "uv":
            return (np.nanmean([self.column(var, i, "u") for i in its], axis=0), np.nanmean([self.column(var, i, "v") for i in its], axis=0))
        if self.is_vector(var) and comp == "mag":
            u, v = self.columns(var, its, "uv")
            return np.hypot(u, v)
        if var == "streamfunction":
            return self.nodal(var, its)
        return np.nanmean([self.column(var, i, comp) for i in its], axis=0)

    def mean_z(self, its) -> np.ndarray:
        return np.nanmean([self.zcor(int(i)) for i in np.atleast_1d(its)], axis=0)

    def series(self, var: str, node: int, layer=None, depth=None, comp: str = "uv"):
        """Serie temporal en un nodo: dict(t, y) o dict(t, u, v) para vectores (comp = "uv")."""
        ds = self.ds; t = ds.time.values; nt = ds.time.size
        if not self.is_derived(var) and depth is None:
            from .signal import point_series
            s = point_series(ds, var, node, layer)
            for k in ("y", "u", "v"):
                if k in s:
                    s[k] = _clean(s[k])
            return s
        if var == "transport" and self.transport_all_ok:
            U, V = self._transport_all()
            return dict(t=t, u=U[:, node], v=V[:, node])
        if self.is_vector(var):
            uv = [self.vector_uv(var, i) for i in range(nt)]
            u = np.array([self._level(a, layer, depth, i)[node] for i, (a, _) in enumerate(uv)])
            v = np.array([self._level(b, layer, depth, i)[node] for i, (_, b) in enumerate(uv)])
            return dict(t=t, u=u, v=v)
        if var == "streamfunction":
            return dict(t=t, y=self._psi_all()[:, node])
        if self.is_derived(var) and self.all_ok:
            return dict(t=t, y=self._all(var, layer, depth)[:, node])
        y = np.array([self._level(self.column(var, i), layer, depth, i)[node] for i in range(nt)])
        return dict(t=t, y=y)


def describe_window(times, its, lang: str = "es") -> str:
    """Texto del título: «media de 17 salidas (2020-01-03 08:00 – 2020-01-04 00:00)»."""
    its = np.atleast_1d(its)
    if its.size == 0:
        return "sin salidas en el intervalo" if lang == "es" else "no outputs in the interval"
    f = lambda i: np.datetime_as_string(np.asarray(times)[int(i)], "m").replace("T", " ")
    n = int(its.size)
    if lang == "es":
        return f"media de {n} salida{'s' if n != 1 else ''} ({f(its[0])} – {f(its[-1])})"
    return f"mean of {n} output{'s' if n != 1 else ''} ({f(its[0])} – {f(its[-1])})"
