"""Lectura/escritura de ficheros en formato gr3 de SCHISM (hgrid.gr3, *.gr3, *.ic)."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np


@dataclass
class Mesh:
    """Malla horizontal de SCHISM.

    x, y, depth : arrays (np,)   coordenadas y profundidad (positiva hacia abajo)
    elements    : array (ne, 3) o lista de listas, indices 0-based
    open_boundaries : lista de arrays de indices de nodo (0-based), cada uno un contorno abierto
    land_boundaries : lista de (indices, flag) con flag 0 = tierra exterior, 1 = isla
    """
    x: np.ndarray
    y: np.ndarray
    depth: np.ndarray
    elements: list
    open_boundaries: list = field(default_factory=list)
    land_boundaries: list = field(default_factory=list)
    name: str = "schismlab mesh"

    @property
    def nnodes(self) -> int:
        return len(self.x)

    @property
    def nelements(self) -> int:
        return len(self.elements)


def write_gr3(path: str | Path, mesh: Mesh, values: np.ndarray | None = None,
              boundaries: bool = True, comment: str | None = None) -> None:
    """Escribe un fichero gr3. Si `values` es None escribe la profundidad (hgrid.gr3)."""
    vals = mesh.depth if values is None else np.broadcast_to(np.asarray(values, float), (mesh.nnodes,))
    with open(path, "w") as f:
        f.write(f"{comment or mesh.name}\n{mesh.nelements} {mesh.nnodes}\n")
        for i in range(mesh.nnodes):
            f.write(f"{i+1} {mesh.x[i]:.9f} {mesh.y[i]:.9f} {vals[i]:.6f}\n")   # 1e-9 grados ~ 0.1 mm (mallas urbanas de metros)
        for k, el in enumerate(mesh.elements):
            f.write(f"{k+1} {len(el)} " + " ".join(str(n + 1) for n in el) + "\n")
        if boundaries:
            nob = len(mesh.open_boundaries)
            f.write(f"{nob} = Number of open boundaries\n")
            f.write(f"{sum(len(b) for b in mesh.open_boundaries)} = Total number of open boundary nodes\n")
            for j, b in enumerate(mesh.open_boundaries):
                f.write(f"{len(b)} = Number of nodes for open boundary {j+1}\n")
                f.writelines(f"{n+1}\n" for n in b)
            nlb = len(mesh.land_boundaries)
            f.write(f"{nlb} = Number of land boundaries\n")
            f.write(f"{sum(len(b) for b, _ in mesh.land_boundaries)} = Total number of land boundary nodes\n")
            for j, (b, flag) in enumerate(mesh.land_boundaries):
                f.write(f"{len(b)} {flag} = Number of nodes for land boundary {j+1}\n")
                f.writelines(f"{n+1}\n" for n in b)


def read_gr3(path: str | Path) -> Mesh:
    """Lee hgrid.gr3 (nodos, elementos y, si existen, contornos)."""
    with open(path) as f:
        name = f.readline().strip()
        ne, npt = map(int, f.readline().split()[:2])
        x = np.empty(npt); y = np.empty(npt); d = np.empty(npt)
        for i in range(npt):
            parts = f.readline().split()
            x[i], y[i], d[i] = float(parts[1]), float(parts[2]), float(parts[3])
        elements = []
        for _ in range(ne):
            parts = f.readline().split()
            elements.append([int(p) - 1 for p in parts[2:2 + int(parts[1])]])
        mesh = Mesh(x, y, d, elements, name=name)
        try:
            nob = int(f.readline().split()[0]); f.readline()
            for _ in range(nob):
                n = int(f.readline().split()[0])
                mesh.open_boundaries.append(np.array([int(f.readline().split()[0]) - 1 for _ in range(n)]))
            nlb = int(f.readline().split()[0]); f.readline()
            for _ in range(nlb):
                parts = f.readline().split()
                n, flag = int(parts[0]), int(parts[1])
                mesh.land_boundaries.append((np.array([int(f.readline().split()[0]) - 1 for _ in range(n)]), flag))
        except (ValueError, IndexError):
            pass
    return mesh


def write_vgrid_2d(path: str | Path) -> None:
    """vgrid.in estandar para simulaciones 2D (barotropicas) en SCHISM."""
    Path(path).write_text("2 !ivcor\n2 1 1.e6 !nvrt, kz, h_s\nZ levels\n1 -1.e6\nS levels\n40. 1. 1.e-4 !h_c, theta_b, theta_f\n-1.\n0.\n")


def write_prop(path: str | Path, mesh: Mesh, value) -> None:
    """Fichero *.prop (un valor por elemento), p.ej. tvd.prop."""
    vals = np.broadcast_to(np.asarray(value, float), (mesh.nelements,))
    with open(path, "w") as f:
        f.writelines(f"{k+1} {v:g}\n" for k, v in enumerate(vals))
