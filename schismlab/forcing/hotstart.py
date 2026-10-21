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


def write_hotstart(path, mesh: Mesh, vg: VGrid, temp, salt, eta=0.0, u=0.0, v=0.0) -> Path:
    """temp, salt: escalar, array (nnodes, nvrt) o funcion f(x, y, z)->valor. eta: escalar/array/funcion f(x,y).
    u, v: escalar o funcion f(x, y, z). Los niveles bajo el fondo se rellenan con el valor del fondo."""
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
    ds = xr.Dataset({
        "time": ("one", [0.0]), "iths": ("one", np.array([0], "int32")), "ifile": ("one", np.array([1], "int32")),
        "nsteps_from_cold": ("one", np.array([0], "int32")),
        "idry_e": ("elem", np.zeros(ne, "int32")), "idry_s": ("side", np.zeros(ns, "int32")), "idry": ("node", np.zeros(npn, "int32")),
        "eta2": ("node", eta_n), "cumsum_eta": ("node", np.zeros(npn)),
        "we": (("elem", "nVert"), z2(ne)), "tr_el": (("elem", "nVert", "ntracers"), tr_el),
        "tr_nd": (("node", "nVert", "ntracers"), tr_nd), "tr_nd0": (("node", "nVert", "ntracers"), tr_nd.copy()),
        "su2": (("side", "nVert"), su), "sv2": (("side", "nVert"), sv),
        "q2": (("node", "nVert"), z2(npn)), "xl": (("node", "nVert"), z2(npn)),
        "dfv": (("node", "nVert"), z2(npn)), "dfh": (("node", "nVert"), z2(npn)),
        "dfq1": (("node", "nVert"), z2(npn)), "dfq2": (("node", "nVert"), z2(npn)),
    })
    ds.to_netcdf(path, format="NETCDF4")
    return Path(path)
