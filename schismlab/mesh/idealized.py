"""Mallas idealizadas (sin costa real) para casos tipo: cuenca rectangular, canal, ..."""
from __future__ import annotations
import numpy as np
from ..io.gr3 import Mesh


R_EARTH = 6371e3


def rectangular_basin(Lx: float, Ly: float, dx: float, depth=50.0,
                      open_sides: tuple[str, ...] = (), name: str = "cuenca rectangular",
                      lon: tuple[float, float] | None = None, lat: tuple[float, float] | None = None) -> Mesh:
    """Cuenca rectangular mallada con triangulos regulares de lado ~dx [m].

    Cartesiana: [0,Lx]x[0,Ly] en metros. Geografica: si se dan lon=(lon0,lon1) y lat=(lat0,lat1) la malla
    se construye en grados (dx se convierte a grados con la latitud media; Lx, Ly se ignoran).
    depth : escalar o funcion depth(x, y) -> array (profundidad positiva, m); x, y en las unidades de la malla.
    open_sides : lados con contorno abierto entre 'W', 'E', 'S', 'N'; el resto son pared.
    """
    if lon is not None and lat is not None:
        lat0 = np.deg2rad(0.5 * (lat[0] + lat[1]))
        dlat = np.rad2deg(dx / R_EARTH); dlon = dlat / np.cos(lat0)
        nx, ny = int(round((lon[1] - lon[0]) / dlon)) + 1, int(round((lat[1] - lat[0]) / dlat)) + 1
        xs, ys = np.linspace(lon[0], lon[1], nx), np.linspace(lat[0], lat[1], ny)
    else:
        nx, ny = int(round(Lx / dx)) + 1, int(round(Ly / dx)) + 1
        xs, ys = np.linspace(0, Lx, nx), np.linspace(0, Ly, ny)
    X, Y = np.meshgrid(xs, ys)                      # (ny, nx)
    x, y = X.ravel(), Y.ravel()
    idx = np.arange(nx * ny).reshape(ny, nx)
    d = depth(x, y) if callable(depth) else np.full(x.size, float(depth))

    elements = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, dd = idx[j, i], idx[j, i + 1], idx[j + 1, i + 1], idx[j + 1, i]
            if (i + j) % 2 == 0:                       # alternar la diagonal: malla mas isotropa
                elements += [[a, b, c], [a, c, dd]]
            else:
                elements += [[a, b, dd], [b, c, dd]]

    # Perimetro en sentido antihorario (dominio a la izquierda), por lados
    sides = {
        "S": idx[0, :], "E": idx[:, -1], "N": idx[-1, ::-1], "W": idx[::-1, 0],
    }
    mesh = Mesh(x, y, d, elements, name=name)
    order = ["S", "E", "N", "W"]
    open_sides = tuple(s.upper() for s in open_sides)
    # Agrupamos lados consecutivos cerrados en un unico contorno de tierra
    land_run: list[int] = []
    for s in order:
        nodes = sides[s]
        if s in open_sides:
            if land_run:
                mesh.land_boundaries.append((np.array(land_run), 0)); land_run = []
            mesh.open_boundaries.append(nodes.copy())
        else:
            land_run += [n for n in nodes if not land_run or n != land_run[-1]]
    if land_run:
        if not open_sides:
            land_run.append(land_run[0])                 # contorno cerrado: repetir el primer nodo
        mesh.land_boundaries.append((np.array(land_run), 0))
    return mesh
