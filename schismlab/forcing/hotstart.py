"""hotstart.nc: estado inicial 3D completo (eta, T, S, velocidades) para ihot=1."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import xarray as xr
from ..io.gr3 import Mesh
from .vgrid import VGrid


def side_table(mesh: Mesh) -> np.ndarray:
    """Lados (ns, 2) en el mismo orden interno que SCHISM (compute_nside de UtilLib)."""
    e = np.asarray(mesh.elements)
    seen, sides = {}, []
    for ie, tri in enumerate(e):
        for j in range(3):
            n1, n2 = tri[(j + 1) % 3], tri[(j + 2) % 3]
            key = (min(n1, n2), max(n1, n2))
            if key not in seen:                      # primer elemento que visita el lado -> lado nuevo
                seen[key] = ie; sides.append((n1, n2))
    return np.array(sides)


def turbulence_state(itur: int, depth, dfv0: float = 1e-2, dfh0: float = 1e-4, turb_met: str = "KL", h0: float = 0.01) -> dict:
    """Viscosidad, difusividad y variables del cierre que SCHISM pondría en un arranque en frío (schism_init.F90).

    SCHISM lee q2, xl, dfv y dfh del hotstart y sustituye lo que puso al iniciarse: con itur = 0 no los vuelve a
    calcular, así que si el hotstart lleva ceros la viscosidad vertical es nula toda la simulación (dfv0 no actúa).
      itur = 0:  dfv = dfv0, dfh = dfh0 (constantes).
      itur = 3+: q2 = q2min, xl = 2·q2min·0.1·max(h0, h) (mínimos del cierre), dfv = dfh = 0 (los calcula el cierre).
    Devuelve escalares o arrays por nodo con las claves q2, xl, dfv, dfh."""
    depth = np.asarray(depth, float)
    if int(itur) == 0:
        return dict(q2=0.0, xl=0.0, dfv=float(dfv0), dfh=float(dfh0))
    if int(itur) >= 3:
        q2min = 5e-6 if str(turb_met).strip("'\" ").upper() in ("MY", "KL") else 7.6e-6
        return dict(q2=q2min, xl=2.0 * q2min * 0.1 * np.maximum(float(h0), depth), dfv=0.0, dfh=0.0)
    return dict(q2=0.0, xl=0.0, dfv=0.0, dfh=0.0)      # itur < 0: perfiles leídos de ficheros (vvd.in, hvd.*): SCHISMlab no los usa


def write_hotstart(path, mesh: Mesh, vg: VGrid, temp, salt, eta=0.0, u=0.0, v=0.0, turb: dict | None = None) -> Path:
    """temp, salt: escalar, array (nnodes, nvrt) o funcion f(x, y, z)->valor. eta: escalar/array/funcion f(x,y).
    u, v: escalar o funcion f(x, y, z). Los niveles bajo el fondo se rellenan con el valor del fondo.
    turb: q2, xl, dfv, dfh (escalar o por nodo) de `turbulence_state`; sin él, los de itur = 0 con los valores por
    defecto de SCHISM (dfv0 = 1e-2, dfh0 = 1e-4), nunca ceros."""
    npn, nvrt = mesh.nnodes, vg.nvrt
    eta_n = np.asarray(eta(mesh.x, mesh.y) if callable(eta) else np.broadcast_to(np.asarray(eta, float), npn), float)
    z = vg.zcor(mesh.depth, eta_n)                              # (np, nvrt)
    X, Y = np.repeat(mesh.x[:, None], nvrt, 1), np.repeat(mesh.y[:, None], nvrt, 1)

    def field(f):
        return np.asarray(f(X, Y, z) if callable(f) else np.broadcast_to(np.asarray(f, float), (npn, nvrt)), float)
    T, S = field(temp), field(salt)
    e = np.asarray(mesh.elements)
    tr_nd = np.stack([T, S], -1)                                 # (np, nvrt, 2)
    tr_el = tr_nd[e].mean(1)                                     # (ne, nvrt, 2)
    sides = side_table(mesh)
    ns = len(sides)
    zs = 0.5 * (z[sides[:, 0]] + z[sides[:, 1]])
    xs, ys = 0.5 * (mesh.x[sides[:, 0]] + mesh.x[sides[:, 1]]), 0.5 * (mesh.y[sides[:, 0]] + mesh.y[sides[:, 1]])
    XS, YS = np.repeat(xs[:, None], nvrt, 1), np.repeat(ys[:, None], nvrt, 1)
    su = np.asarray(u(XS, YS, zs) if callable(u) else np.broadcast_to(np.asarray(u, float), (ns, nvrt)), float)
    sv = np.asarray(v(XS, YS, zs) if callable(v) else np.broadcast_to(np.asarray(v, float), (ns, nvrt)), float)
    ne = mesh.nelements
    z2 = lambda n: np.zeros((n, nvrt))
    turb = turb if turb is not None else turbulence_state(0, mesh.depth)
    def nodal(a):                                                 # escalar o array por nodo -> (np, nvrt)
        a = np.asarray(a, float)
        return np.repeat(a[:, None], nvrt, 1) if a.ndim == 1 else np.full((npn, nvrt), float(a))
    ds = xr.Dataset({
        "time": ("one", [0.0]), "iths": ("one", np.array([0], "int32")), "ifile": ("one", np.array([1], "int32")),
        "nsteps_from_cold": ("one", np.array([0], "int32")),
        "idry_e": ("elem", np.zeros(ne, "int32")), "idry_s": ("side", np.zeros(ns, "int32")), "idry": ("node", np.zeros(npn, "int32")),
        "eta2": ("node", eta_n), "cumsum_eta": ("node", np.zeros(npn)),
        "we": (("elem", "nVert"), z2(ne)), "tr_el": (("elem", "nVert", "ntracers"), tr_el),
        "tr_nd": (("node", "nVert", "ntracers"), tr_nd), "tr_nd0": (("node", "nVert", "ntracers"), tr_nd.copy()),
        "su2": (("side", "nVert"), su), "sv2": (("side", "nVert"), sv),
        "q2": (("node", "nVert"), nodal(turb["q2"])), "xl": (("node", "nVert"), nodal(turb["xl"])),
        "dfv": (("node", "nVert"), nodal(turb["dfv"])), "dfh": (("node", "nVert"), nodal(turb["dfh"])),
        "dfq1": (("node", "nVert"), z2(npn)), "dfq2": (("node", "nVert"), z2(npn)),
    })
    ds.to_netcdf(path, format="NETCDF4")
    return Path(path)
