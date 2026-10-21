"""Metricas de calidad de malla y paso de tiempo recomendado."""
from __future__ import annotations
import numpy as np
from ..io.gr3 import Mesh

R_EARTH = 6371e3


def edge_lengths_m(mesh: Mesh, geographic: bool | None = None) -> np.ndarray:
    e = np.asarray(mesh.elements)
    x, y = mesh.x, mesh.y
    if geographic is None:
        geographic = np.ptp(x) < 360 and np.ptp(y) < 180
    if geographic:
        lat0 = np.deg2rad(y.mean())
        x = np.deg2rad(x) * R_EARTH * np.cos(lat0); y = np.deg2rad(y) * R_EARTH
    L = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        L.append(np.hypot(x[e[:, i]] - x[e[:, j]], y[e[:, i]] - y[e[:, j]]))
    return np.array(L).T   # (ne, 3)


def mesh_quality(mesh: Mesh) -> dict:
    """Resumen: tamanos, angulos minimos, y dt maximo por CFL de onda larga (sqrt(gh)) por elemento."""
    L = edge_lengths_m(mesh)
    e = np.asarray(mesh.elements)
    a, b, c = L[:, 0], L[:, 1], L[:, 2]
    cosang = np.stack([(b**2 + c**2 - a**2) / (2*b*c), (a**2 + c**2 - b**2) / (2*a*c), (a**2 + b**2 - c**2) / (2*a*b)], 1)
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    h = np.maximum(mesh.depth[e].mean(1), 0.1)
    dt_cfl = L.min(1) / np.sqrt(9.81 * h)          # SCHISM es implicito; esto es orientativo
    return dict(nodes=mesh.nnodes, elements=mesh.nelements,
                edge_min_m=float(L.min()), edge_median_m=float(np.median(L)), edge_max_m=float(L.max()),
                min_angle_deg=float(ang.min()), elements_angle_lt_20=int((ang.min(1) < 20).sum()),
                depth_min=float(mesh.depth.min()), depth_max=float(mesh.depth.max()),
                dt_cfl_min_s=float(dt_cfl.min()), dt_cfl_p5_s=float(np.percentile(dt_cfl, 5)))
