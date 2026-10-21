"""Deteccion y asignacion de contornos (abiertos / tierra / islas) a partir de la triangulacion."""
from __future__ import annotations
import numpy as np
from ..io.gr3 import Mesh


def boundary_edges(elements) -> np.ndarray:
    """Aristas que pertenecen a un solo elemento (frontera), como array (nb, 2) orientado como en el elemento."""
    e = np.asarray(elements)
    edges = np.concatenate([e[:, [0, 1]], e[:, [1, 2]], e[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    _, idx, cnt = np.unique(key, axis=0, return_index=True, return_counts=True)
    return edges[idx[cnt == 1]]


def hull_rings(mesh: Mesh) -> list[np.ndarray]:
    """Anillos cerrados de la frontera. El primero es el exterior (antihorario), el resto islas (horario).

    Con elementos orientados antihorario, las aristas frontera ya recorren el dominio por la izquierda:
    el exterior sale antihorario y las islas horario, que es el convenio de hgrid.gr3 de SCHISM.
    """
    edges = boundary_edges(mesh.elements)
    nxt = dict(zip(edges[:, 0].tolist(), edges[:, 1].tolist()))
    rings = []
    while nxt:
        start = next(iter(nxt)); ring = [start]; n = nxt.pop(start)
        while n != start and n in nxt:
            ring.append(n); n = nxt.pop(n)
        rings.append(np.array(ring))
    # anillo exterior = mayor area absoluta
    def area(r):
        x, y = mesh.x[r], mesh.y[r]
        return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    rings.sort(key=lambda r: -abs(area(r)))
    return rings


def assign_boundaries(mesh: Mesh, open_where=None, tol: float | None = None) -> Mesh:
    """Rellena mesh.open_boundaries y mesh.land_boundaries.

    open_where : None  -> todo tierra (cuenca cerrada)
                 'bbox' -> nodos del anillo exterior sobre el rectangulo envolvente son abiertos
                 callable(x, y) -> bool array: nodos abiertos
    Los tramos abiertos se parten en contornos distintos cuando no son contiguos; cada tramo abierto y
    cada tramo de tierra del anillo exterior se escribe como un contorno. Las islas van con flag 1.
    """
    rings = hull_rings(mesh)
    outer, islands = rings[0], rings[1:]
    mesh.open_boundaries, mesh.land_boundaries = [], []
    if open_where is None:
        is_open = np.zeros(outer.size, bool)
    elif hasattr(open_where, "exterior"):          # poligono shapely: abiertos los nodos sobre su borde
        from shapely.geometry import Point
        ring = open_where.exterior
        tol = tol if tol is not None else 1e-3 * max(np.ptp(mesh.x), np.ptp(mesh.y))
        is_open = np.array([ring.distance(Point(mesh.x[n], mesh.y[n])) < tol for n in outer])
    elif open_where == "bbox":
        x, y = mesh.x[outer], mesh.y[outer]
        tol = tol if tol is not None else 1e-3 * max(np.ptp(mesh.x), np.ptp(mesh.y))
        is_open = ((np.abs(x - mesh.x.min()) < tol) | (np.abs(x - mesh.x.max()) < tol) |
                   (np.abs(y - mesh.y.min()) < tol) | (np.abs(y - mesh.y.max()) < tol))
    else:
        is_open = np.asarray(open_where(mesh.x[outer], mesh.y[outer]), bool)

    if is_open.all():
        # anillo exterior entero abierto (dominio sin costa en el borde): SCHISM no admite un contorno abierto
        # cerrado ("Looped open bnd"), asi que se parte en dos mitades que comparten los nodos de union
        h = outer.size // 2
        mesh.open_boundaries.append(outer[:h + 1])
        mesh.open_boundaries.append(np.append(outer[h:], outer[0]))
    elif not is_open.any():
        mesh.land_boundaries.append((np.append(outer, outer[0]), 0))
    else:
        # rotar el anillo para empezar en un cambio tierra->abierto
        k = next(i for i in range(outer.size) if is_open[i] and not is_open[i - 1])
        outer, is_open = np.roll(outer, -k), np.roll(is_open, -k)
        # segmentos consecutivos; los nodos de union pertenecen a ambos contornos
        cuts = [0] + [i for i in range(1, outer.size) if is_open[i] != is_open[i - 1]] + [outer.size]
        for a, b in zip(cuts[:-1], cuts[1:]):
            seg = outer[a:b + 1] if b < outer.size else np.append(outer[a:], outer[0])
            if is_open[a]:
                mesh.open_boundaries.append(seg)
            else:
                mesh.land_boundaries.append((seg, 0))
    for isl in islands:
        mesh.land_boundaries.append((np.append(isl, isl[0]), 1))
    return mesh


EDGE_TYPES = ("forced", "radiation", "wall")


def edge_types_cfg(mesh_cfg: dict, npoly: int) -> list[str]:
    """Tipo de cada lado del polígono del dominio (lado i: vértice i -> i+1): forced | radiation | wall (por defecto forced)."""
    et = mesh_cfg.get("edge_types") or {}
    return [str(et.get(i, et.get(str(i), "forced"))) for i in range(npoly)]


def assign_edge_types(mesh: Mesh, polygon, types: list[str], tol: float) -> list[str]:
    """Contornos abiertos según el tipo de cada lado del polígono: los lados «wall» son tierra; los tramos abiertos se
    parten donde cambia el tipo. Devuelve el tipo (forced | radiation) de cada contorno abierto, en el orden de hgrid."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    xy = list(polygon.exterior.coords)[:-1]
    edges = [LineString([xy[i], xy[(i + 1) % len(xy)]]) for i in range(len(xy))]
    openg = unary_union([e for e, t in zip(edges, types) if t != "wall"]) if any(t != "wall" for t in types) else None
    if openg is None:
        assign_boundaries(mesh, open_where=None)
        return []
    assign_boundaries(mesh, open_where=lambda xs, ys: np.array([openg.distance(Point(a, b)) < tol for a, b in zip(xs, ys)]))
    new_open, kinds = [], []
    for seg in mesh.open_boundaries:
        lab = []
        for n in seg:                                      # tipo del lado más cercano (sin contar paredes)
            p = Point(mesh.x[n], mesh.y[n])
            d = [e.distance(p) if t != "wall" else np.inf for e, t in zip(edges, types)]
            lab.append(types[int(np.argmin(d))])
        start = 0
        for i in range(1, len(seg) + 1):
            if i == len(seg) or lab[i] != lab[start]:
                if i - start >= 2:
                    new_open.append(np.asarray(seg[start:i])); kinds.append(lab[start])
                start = i
    mesh.open_boundaries = new_open
    return kinds
