"""Retoques locales de la batimetría de la malla, sin remallar.

Configuración en el YAML (mesh.bathymetry_edits), aplicados en orden:
    bathymetry_edits:
      - name: canal          # opcional
        polygon: [[lon, lat], ...]
        op: set              # set | min_depth | max_depth | offset | smooth
        value: 8             # m (profundidad positiva hacia abajo; negativo = cota sobre el mar)
        iterations: 5        # solo smooth: pasadas del suavizado laplaciano
- set: profundidad fija (dragado de un canal, relleno de un puerto, cota de un dique con valor negativo).
- min_depth: al menos esa profundidad (abre un paso estrecho que el DEM cierra).
- max_depth: como mucho esa profundidad (elimina un pozo espurio del DEM).
- offset: suma (m) a la profundidad actual (dragado uniforme; negativo = recrecimiento).
- smooth: media con los nodos vecinos, `iterations` veces (suaviza un talud o un escalón entre fuentes).

Los retoques se aplican al construir la malla y también a una malla ya hecha: la profundidad sin retoques se guarda en
depth_unedited.npz (junto con la subida del nivel del mar aplicada en ese momento), de modo que cambiar o quitar un
retoque parte siempre de la batimetría original.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import numpy as np

log = logging.getLogger(__name__)

OPS = ("set", "min_depth", "max_depth", "offset", "smooth")


def edits_cfg(mesh_cfg: dict) -> list[dict]:
    out = []
    for e in mesh_cfg.get("bathymetry_edits") or []:
        op = e.get("op", "set")
        if op not in OPS:
            raise ValueError(f"bathymetry_edits: operación '{op}' desconocida ({', '.join(OPS)})")
        if not e.get("polygon") or len(e["polygon"]) < 3:
            raise ValueError("bathymetry_edits: cada retoque necesita un polígono de al menos 3 vértices")
        out.append(dict(name=e.get("name", ""), polygon=[list(map(float, p)) for p in e["polygon"]], op=op,
                        value=float(e.get("value", 0.0)), iterations=int(e.get("iterations", 5))))
    return out


def _inside(x, y, polygon) -> np.ndarray:
    from matplotlib.path import Path as MPath
    return MPath(np.asarray(polygon, float)).contains_points(np.column_stack([x, y]))


def _neighbours(elements, n: int):
    """Matriz dispersa de adyacencia nodo-nodo (incluye el propio nodo) a partir de los elementos."""
    from scipy.sparse import coo_matrix
    rows, cols = [], []
    for el in elements:
        k = len(el)
        for i in range(k):
            rows.append(el[i]); cols.append(el[(i + 1) % k])
            rows.append(el[(i + 1) % k]); cols.append(el[i])
    rows += list(range(n)); cols += list(range(n))
    a = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)).tocsr()
    a.data[:] = 1.0
    return a


def apply_edits(mesh, edits: list[dict]):
    """Aplica los retoques a mesh.depth (in situ) y devuelve la malla; registra cuántos nodos toca cada uno."""
    adj = None
    for e in edits:
        sel = _inside(mesh.x, mesh.y, e["polygon"])
        if not sel.any():
            log.warning("retoque %s: ningún nodo dentro del polígono", e["name"] or e["op"])
            continue
        d = mesh.depth
        if e["op"] == "set":
            d[sel] = e["value"]
        elif e["op"] == "min_depth":
            d[sel] = np.maximum(d[sel], e["value"])
        elif e["op"] == "max_depth":
            d[sel] = np.minimum(d[sel], e["value"])
        elif e["op"] == "offset":
            d[sel] = d[sel] + e["value"]
        elif e["op"] == "smooth":
            if adj is None:
                adj = _neighbours(mesh.elements, mesh.nnodes)
            deg = np.asarray(adj.sum(1)).ravel()
            for _ in range(max(1, e["iterations"])):
                avg = adj @ d / deg
                d[sel] = avg[sel]
        mesh.depth = d
        log.info("retoque %s (%s %g): %d nodos", e["name"] or e["op"], e["op"], e["value"], int(sel.sum()))
    return mesh


def _slr_applied(wd: Path) -> float:
    f = wd / "slr_applied"
    return float(f.read_text()) if f.exists() else 0.0


def save_unedited(wd: Path, depth, edits: list[dict]):
    """Guarda la profundidad sin retoques (tras construir la malla) y los retoques aplicados."""
    np.savez(Path(wd) / "depth_unedited.npz", depth=np.asarray(depth, float), slr=_slr_applied(Path(wd)), edits=json.dumps(edits))


def applied_edits(wd: Path) -> list[dict] | None:
    f = Path(wd) / "depth_unedited.npz"
    if not f.exists():
        return None
    with np.load(f) as z:
        return json.loads(str(z["edits"]))


def sync_edits(wd: Path, mesh_cfg: dict, mesh=None, force: bool = False):
    """Deja hgrid.gr3 (y hgrid.ll) con los retoques del YAML aplicados sobre la batimetría original.

    Devuelve la malla (leída de disco si no se pasa) o None si no hay malla. No hace nada si ya coinciden.
    """
    from ..io.gr3 import read_gr3, write_gr3
    wd = Path(wd); hg = wd / "hgrid.gr3"
    if not hg.exists():
        return None
    edits = edits_cfg(mesh_cfg)
    prev = applied_edits(wd)
    if mesh is None:
        mesh = read_gr3(hg)
    if prev is None:
        if not edits:
            return mesh
        save_unedited(wd, mesh.depth, [])                 # malla anterior a esta función: su profundidad es la original
        prev = []
    if prev == edits and not force:
        return mesh
    with np.load(wd / "depth_unedited.npz") as z:
        base = z["depth"].astype(float); slr0 = float(z["slr"])
    if base.size != mesh.nnodes:                          # la malla ha cambiado por otra vía: se toma la actual como original
        base = mesh.depth.astype(float).copy(); slr0 = _slr_applied(wd)
    mesh.depth = base + (_slr_applied(wd) - slr0)         # el escenario de subida del nivel del mar se mantiene
    apply_edits(mesh, edits)
    write_gr3(hg, mesh)
    if (wd / "hgrid.ll").exists():
        ll = read_gr3(wd / "hgrid.ll"); ll.depth = mesh.depth; write_gr3(wd / "hgrid.ll", ll)
    np.savez(wd / "depth_unedited.npz", depth=base, slr=slr0, edits=json.dumps(edits))
    log.info("retoques de batimetría aplicados a la malla: %d", len(edits))
    return mesh
