"""Figuras rapidas de mallas y campos sobre malla."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from .io.gr3 import Mesh


def triangulation(mesh: Mesh) -> mtri.Triangulation:
    return mtri.Triangulation(mesh.x, mesh.y, np.asarray(mesh.elements))


def plot_mesh(mesh: Mesh, ax=None, depth: bool = True, edges: bool = True, boundaries: bool = True,
              cmap: str = "viridis_r", geographic: bool | None = None, **kw):
    """Dibuja la malla (aristas), la profundidad y los contornos abiertos (rojo) / tierra (negro) / islas (gris)."""
    if ax is None:
        _, ax = plt.subplots(figsize=kw.pop("figsize", (9, 7)))
    tri = triangulation(mesh)
    if depth:
        c = ax.tripcolor(tri, mesh.depth, cmap=cmap, shading="gouraud")
        plt.colorbar(c, ax=ax, label="profundidad (m)", shrink=0.8)
    if edges:
        ax.triplot(tri, color="k", lw=0.15, alpha=0.6)
    if boundaries:
        for b in mesh.open_boundaries:
            ax.plot(mesh.x[b], mesh.y[b], "r-", lw=1.5)
        for b, flag in mesh.land_boundaries:
            ax.plot(mesh.x[b], mesh.y[b], "-", color="k" if flag == 0 else "0.5", lw=0.8)
    if geographic is None:
        geographic = np.ptp(mesh.x) < 360 and np.ptp(mesh.y) < 180
    if geographic:
        ax.set_aspect(1 / np.cos(np.deg2rad(mesh.y.mean())))
        ax.set_xlabel("longitud"); ax.set_ylabel("latitud")
    else:
        ax.set_aspect("equal"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.set_title(f"{mesh.name}\n{mesh.nnodes} nodos, {mesh.nelements} elementos", fontsize=9)
    return ax
