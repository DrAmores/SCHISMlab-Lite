"""Visor de mallas: mapas de resolución, profundidad y calidad como imágenes para superponer en el mapa (Leaflet).

Las imágenes se dibujan en proyección Mercator, la del mapa, para que encajen exactamente al estirarlas entre los
límites lon/lat. Solo se dibujan los triángulos visibles, así que el zoom es rápido aunque la malla tenga 1 millón
de elementos; con pocos triángulos a la vista se dibujan también sus aristas.
"""
from __future__ import annotations
import base64
import io
from pathlib import Path
import numpy as np

LAYERS = ("size", "depth", "quality", "mesh")
EDGES_BELOW = 25000                       # triángulos visibles por debajo de los cuales se dibujan las aristas


def _merc(lat):
    return np.log(np.tan(np.pi / 4 + np.deg2rad(np.clip(lat, -85, 85)) / 2))


def load(wd: Path) -> dict:
    """Malla y campos por elemento (tamaño medio de arista en m, ángulo mínimo en grados), con caché en mesh_view.npz."""
    wd = Path(wd); hg = wd / "hgrid.gr3"; cache = wd / "mesh_view.npz"
    if cache.exists() and cache.stat().st_mtime >= hg.stat().st_mtime:
        z = np.load(cache)
        if "short" in z.files:                            # cachés anteriores a la arista más corta: se recalculan
            return {k: z[k] for k in z.files}
    from ..io.gr3 import read_gr3
    from .quality import edge_lengths_m
    m = read_gr3(hg)
    tri = np.asarray([e[:3] for e in m.elements], dtype=np.int32)
    L = edge_lengths_m(m)
    a, b, c = L[:, 0], L[:, 1], L[:, 2]
    cosang = np.stack([(b**2 + c**2 - a**2) / (2*b*c), (a**2 + c**2 - b**2) / (2*a*c), (a**2 + b**2 - c**2) / (2*a*b)], 1)
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1))).min(1)
    d = dict(x=np.asarray(m.x, float), y=np.asarray(m.y, float), depth=np.asarray(m.depth, float), tri=tri,
             size=L.mean(1).astype("float32"), short=L.min(1).astype("float32"), minang=ang.astype("float32"))
    np.savez(cache, **d)
    return d


def stats(d: dict) -> dict:
    """Estadísticas de resolución para el panel: percentiles e histograma (bins logarítmicos) del tamaño de elemento."""
    s = d["size"]
    s = np.asarray(s, float)
    edges = np.logspace(np.log10(max(float(s.min()) * 0.999, 1e-3)), np.log10(float(s.max()) * 1.001), 25)   # márgenes: redondeo float32
    h, _ = np.histogram(s, bins=edges)
    return dict(size_p5=float(np.percentile(s, 5)), size_p50=float(np.median(s)), size_p95=float(np.percentile(s, 95)),
                size_min=float(s.min()), size_max=float(s.max()), hist_edges=edges.tolist(), hist_counts=h.tolist(),
                angle_lt20=int((d["minang"] < 20).sum()), angle_min=float(d["minang"].min()),
                short_p50=float(np.median(d["short"])) if "short" in d else None)   # arista más corta: dx en una rejilla regular


CFL_MIN = 0.4                               # documentación de SCHISM (grid-generation): CFL inverso > 0.4 (0.2 en tsunamis)


def cfl(d: dict, dt: float | None = None) -> np.ndarray:
    """CFL por elemento como en la documentación de SCHISM: sqrt(g h) dt / dx, sin |u|; con h < 0.1 m, dt / dx (|u| ~ 1 m/s).

    SCHISM es semiimplícito: no hay límite superior, pero con CFL < 0.4 la advección euleriana-lagrangiana (ELM)
    introduce difusión numérica (ruido o disipación).
    """
    dt = float(dt if dt is not None else d.get("dt", 100.0))
    h = d["depth"][d["tri"]].mean(1)
    c = np.where(h < 0.1, 1.0, np.sqrt(9.81 * np.maximum(h, 0.1)))
    return c * dt / np.maximum(d["size"], 1e-6)


def cfl_stats(d: dict, dt: float) -> dict:
    c = cfl(d, dt); wet = d["depth"][d["tri"]].mean(1) > 0.1
    cw = c[wet] if wet.any() else c
    return dict(cfl_min=float(cw.min()), cfl_p5=float(np.percentile(cw, 5)), cfl_lt04=float(100 * (cw < CFL_MIN).mean()),
                cfl_lt02=float(100 * (cw < 0.2).mean()), dt_needed=float(np.percentile(CFL_MIN * d["size"][wet] / np.sqrt(9.81 * np.maximum(d["depth"][d["tri"]].mean(1)[wet], 0.1)), 95)) if wet.any() else 0.0)


CFL_MAX = 8.0                               # orientativo: con CFL muy alto el ELM retrocede muchos elementos y pierde precisión


def dt_range(d: dict) -> tuple[float, float]:
    """(Δt mínimo, Δt máximo) recomendados: CFL > CFL_MIN en el 95 % de los elementos mojados y CFL < CFL_MAX en el 95 %."""
    h = d["depth"][d["tri"]].mean(1); wet = h > 0.1
    if not wet.any():
        wet = np.ones_like(h, bool)
    c = np.where(h < 0.1, 1.0, np.sqrt(9.81 * np.maximum(h, 0.1)))
    tau = (d["size"] / c)[wet]                           # tiempo de cruce de cada elemento (s)
    lo, hi = float(np.percentile(CFL_MIN * tau, 95)), float(np.percentile(CFL_MAX * tau, 5))
    return lo, max(hi, lo)


def _style(layer: str, d: dict):
    if layer == "cfl":
        from matplotlib.colors import BoundaryNorm, ListedColormap
        c = cfl(d); top = max(2.0, float(np.percentile(c, 99)))
        cmap = ListedColormap(["#d7191c", "#fdae61", "#a6d96a", "#1a9641"])
        return c, cmap, BoundaryNorm([0, 0.2, CFL_MIN, 1.0, top], 4), f"CFL (Δt = {float(d.get('dt', 100)):g} s; SCHISM pide > {CFL_MIN:g})"
    from matplotlib.colors import LogNorm, Normalize
    if layer == "size":
        lo, hi = np.percentile(d["size"], [1, 99.5])
        return d["size"], "turbo", LogNorm(max(lo, 1), max(hi, lo * 1.01)), "tamaño de elemento (m)"
    if layer == "depth":
        de = d["depth"][d["tri"]].mean(1)
        hi = float(np.percentile(de, 99))
        land = -de[de < 0]
        if land.size > 0.001 * de.size and land.max() > 0.5:   # malla con tierra (inundación): cota, mar en azules y tierra en ocres
            from matplotlib.colors import TwoSlopeNorm, ListedColormap
            import matplotlib
            sea = matplotlib.colormaps["Blues"](np.linspace(0.95, 0.25, 128)); terr = matplotlib.colormaps["YlOrBr"](np.linspace(0.1, 0.95, 128))
            top = max(float(np.percentile(land, 99.5)), 1.0)
            return -de, ListedColormap(np.vstack([sea, terr])), TwoSlopeNorm(vmin=-max(hi, 1.0), vcenter=0.0, vmax=top), "cota (m): mar < 0 < tierra"
        lo, hi = float(de.min()), float(np.percentile(de, 99.5))      # rango de los datos: un escalón de 1 m sobre 200 m se ve
        if not hi > lo:
            lo, hi = lo - 0.5, lo + 0.5                               # fondo plano
        return de, "viridis_r", Normalize(lo, hi), "profundidad (m)"
    if layer == "quality":
        return d["minang"], "RdYlGn", Normalize(10, 60), "ángulo mínimo (°)"
    return None, None, None, ""


def render(d: dict, layer: str, bounds: tuple[float, float, float, float], width_px: int = 1400, merc: bool = True) -> tuple[str, list] | None:
    """PNG (data URL) de la capa en la ventana (oeste, sur, este, norte) y sus límites para el imageOverlay."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    w, s, e, n = bounds
    w, e = max(w, float(d["x"].min())), min(e, float(d["x"].max())); s, n = max(s, float(d["y"].min())), min(n, float(d["y"].max()))
    if e <= w or n <= s:
        return None
    tri = d["tri"]; cx = d["x"][tri].mean(1); cy = d["y"][tri].mean(1)
    padx, pady = 0.05 * (e - w), 0.05 * (n - s)
    vis = (cx > w - padx) & (cx < e + padx) & (cy > s - pady) & (cy < n + pady)
    if not vis.any():
        return None
    if merc:
        ym = _merc(d["y"]); y0, y1 = float(_merc(s)), float(_merc(n)); xr = np.deg2rad(e - w)
    else:                                       # malla idealizada en metros: ejes iguales
        ym = d["y"]; y0, y1 = s, n; xr = e - w
    width = int(width_px); height = int(max(80, min(2400, width * (y1 - y0) / xr)))
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    vals, cmap, norm, _ = _style(layer, d)
    t = tri[vis]
    if vals is not None:
        ax.tripcolor(d["x"], ym, t, facecolors=vals[vis], cmap=cmap, norm=norm, edgecolors="none", rasterized=True)
    if layer == "mesh" or vis.sum() < EDGES_BELOW:
        ax.triplot(d["x"], ym, t, lw=0.25 if vals is not None else 0.4, color="k" if vals is None else (0, 0, 0, 0.45))
    ax.set_xlim(w, e); ax.set_ylim(y0, y1)
    buf = io.BytesIO(); fig.savefig(buf, format="png", transparent=True); plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), [[s, w], [n, e]]


def legend(d: dict, layer: str, lang: str = "es") -> str | None:
    """Barra de color (data URL PNG) de la capa."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    vals, cmap, norm, label = _style(layer, d)
    if vals is None:
        return None
    if lang == "en":
        label = {"tamaño de elemento (m)": "element size (m)", "profundidad (m)": "depth (m)", "ángulo mínimo (°)": "minimum angle (°)", "cota (m): mar < 0 < tierra": "elevation (m): sea < 0 < land"}.get(
            label, label.replace("SCHISM pide", "SCHISM requires"))
    fig = plt.figure(figsize=(6, 0.75), dpi=100); ax = fig.add_axes([0.04, 0.55, 0.92, 0.3])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=ax, orientation="horizontal"); cb.set_label(label, fontsize=9); cb.ax.tick_params(labelsize=8)
    from matplotlib.colors import LogNorm
    if isinstance(norm, LogNorm) and norm.vmax / norm.vmin > 8:          # varias decadas: sin etiquetas en las marcas menores
        from matplotlib.ticker import NullFormatter
        cb.ax.xaxis.set_minor_formatter(NullFormatter())
    buf = io.BytesIO(); fig.savefig(buf, format="png", transparent=True); plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def probe(d: dict, x: float, y: float) -> dict | None:
    """Valores bajo el cursor: elemento que contiene (x, y) y su nodo más cercano; None fuera de la malla."""
    from scipy.spatial import cKDTree
    tri = d["tri"]
    if "_tree" not in d:
        d["_cx"] = d["x"][tri].mean(1); d["_cy"] = d["y"][tri].mean(1)
        d["_k"] = float(np.cos(np.deg2rad(np.mean(d["y"])))) if float(np.abs(d["y"]).max()) <= 90 else 1.0
        d["_tree"] = cKDTree(np.column_stack([d["_cx"] * d["_k"], d["_cy"]]))
    _, cand = d["_tree"].query([x * d["_k"], y], k=min(12, len(tri)))
    for e in np.atleast_1d(cand):
        a, b, c = tri[e]
        x1, y1, x2, y2, x3, y3 = d["x"][a], d["y"][a], d["x"][b], d["y"][b], d["x"][c], d["y"][c]
        den = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if den == 0:
            continue
        l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / den; l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / den
        if min(l1, l2, 1 - l1 - l2) < -1e-9:
            continue
        nodes = tri[e]; dist = np.hypot((d["x"][nodes] - x) * d["_k"], d["y"][nodes] - y); n = int(nodes[np.argmin(dist)])
        depth = float(l1 * d["depth"][a] + l2 * d["depth"][b] + (1 - l1 - l2) * d["depth"][c])
        out = dict(element=int(e) + 1, node=n + 1, node_depth=float(d["depth"][n]), depth=depth, size=float(d["size"][e]),
                   minang=float(d["minang"][e]))
        out["cfl"] = float(cfl({**d, "tri": tri[[e]], "size": d["size"][[e]]})[0])
        return out
    return None
