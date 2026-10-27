"""Explorador de resultados (pestaña Mapas y series): mapa con flechas, reproducción en el tiempo, puntos múltiples
con series y perfiles, secciones arrastrables (y presets transversal/longitudinal) con flechas, Hovmöller,
animaciones y exportación. Pestaña Espectro: Welch, rotatorio y wavelet de los puntos o de las estaciones."""
from __future__ import annotations
import re
from html import escape as html_escape
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from nicegui import run, ui
from .figures import (LAYOUT, LABELS, label, zero_ticks, color_range, elevation_range, layout, themed, NodeSampler, _aspect, dataset_range, _values, map_arrows, arrow_field, arrow_units, arrows_trace, profile_figure, profile_figure2,
                      section_figure2, section_line_figure, hovmoller_figure, iso_hovmoller_figure, psd_figure, rotary_figure, wavelet_figure, land_polygons, land_traces, boundary_traces)
from ..analysis.sections import Section, preset_section, field_at_depth, is_geographic
from ..analysis.signal import point_series, psd_welch, rotary_spectrum, wavelet_morlet, reference_periods, regularize, resolvable_periods

from ..edition import default_generator
from .brand import SERIES as _SERIES
# colores de los puntos: los 8 de la marca y 8 más, distintos entre sí (P4 usa 11 puntos: no se repiten hasta el 17)
COLORS = list(_SERIES) + ["#e6a100", "#1f77b4", "#c2185b", "#00897b", "#8d6e63", "#9e9d24", "#5c6bc0", "#f06292"]
PLOTLY_CONFIG = {"modeBarButtonsToAdd": ["drawline", "eraseshape"], "displaylogo": False, "scrollZoom": True}
# plotly_click lleva la traza entera (z del mapa de calor, >1 MB) y el websocket lo rechaza: solo se envían x, y de los puntos
CLICK_JS = "(e) => emit({points: (e.points || []).map(p => ({x: p.x, y: p.y}))})"
# secciones: colores vivos (se ven sobre cualquier mapa de color, con un halo blanco debajo)
SECTION_COLORS = ["#0e9aa7", "#e4572e", "#f3a712", "#a23cff", "#29bf12", "#ff4fa3", "#00b4ff"]


class ExplorerState:
    def __init__(self, ds, vg, cfg: dict | None = None):
        from ..analysis.isosurface import add_density
        from ..analysis.derived import Fields
        from ..analysis.dynamics import case_coriolis
        add_density(ds)                                    # σt de T y S (perezoso) si no se guardó waterDensity
        self.ds, self.vg, self.cfg = ds, vg, (cfg or {})
        self.vars = sorted({v[:-1] if v.endswith(("X", "Y")) else v for v in ds.data_vars if "time" in ds[v].dims and not v.startswith("dryFlag")})
        geo0 = is_geographic(ds)
        # f del caso (para ζ/f): lon/lat, plano f o plano β; sin rotación no hay ζ/f
        self.fcor = case_coriolis(self.cfg, ds.x.values, ds.y.values, geo0) if (cfg is not None or geo0) else None
        self.F = Fields(ds, vg, self.fcor)                 # variables derivadas, componentes y promedios
        self.vars += [v for v in self.F.available if v not in self.vars]
        self.mcomp = "mag"                                 # componente del mapa: mag | u | v
        self.window = None                                 # promedio temporal: índices de las salidas (None = instante)
        self.on_window = None                              # aviso a otras pestañas (Puntos: perfil y hodógrafa)
        self.var = "elevation" if "elevation" in self.vars else self.vars[0]
        self.it = ds.time.size - 1
        self.nvrt = ds.sizes.get("layer", 1)
        self.layer = self.nvrt - 1
        self.depth_mode = "layer"; self.depth_m = 10.0     # layer | depth | iso (profundidad de la isosuperficie var = iso_value)
        self.iso_value = 15.0
        self.arrows = False; self.fixed = True; self.zr = None
        self.click_mode = "point"
        self.points: list[dict] = []
        self.sections: list[dict] = []
        self.pending: tuple | None = None
        self.geo = is_geographic(ds)
        import matplotlib.tri as mtri
        self.tri = mtri.Triangulation(ds.x.values, ds.y.values, ds.attrs["elements"]); self.tri.get_trifinder()
        self.sampler = NodeSampler(ds, n=220, tri=self.tri)
        self.land: list = []; self.bmesh = None           # contexto geográfico (dominios reales): tierra GSHHG y contornos de la malla
        self.show_mesh = False; self.background = "field"  # field | resolution | depth
        self.cmap = "auto"; self.zmanual = None            # escala de colores y rango manual (min, max)
        self.contour = ""; self.contour_step = 0.0          # isolíneas encima del color: "" | "depth" | una variable; intervalo (0 = auto)
        self._edges = None; self._res = None
        self.dark = False                                  # tema oscuro de la interfaz (figuras con plotly_dark)

    def mesh_edges(self):
        """Aristas de la malla como una traza (x, y con NaN); submuestreadas si hay más de ~120 000."""
        if self._edges is None:
            e = np.asarray(self.ds.attrs["elements"])[:, :3]
            a = np.concatenate([e[:, [0, 1]], e[:, [1, 2]], e[:, [2, 0]]]); a.sort(axis=1)
            a = np.unique(a, axis=0)
            step = max(1, a.shape[0] // 120_000)
            a = a[::step]
            x, y = self.ds.x.values, self.ds.y.values
            self._edges = (np.column_stack([x[a[:, 0]], x[a[:, 1]], np.full(a.shape[0], np.nan)]).ravel(),
                           np.column_stack([y[a[:, 0]], y[a[:, 1]], np.full(a.shape[0], np.nan)]).ravel(), step)
        return self._edges

    def resolution(self) -> np.ndarray:
        """Tamaño medio de arista (m) en cada nodo: mapa de resolución de la malla."""
        if self._res is None:
            from ..mesh.quality import edge_lengths_m
            from ..io.gr3 import Mesh
            e = np.asarray(self.ds.attrs["elements"])[:, :3]
            m = Mesh(self.ds.x.values, self.ds.y.values, self.ds.depth.values, e)
            L = edge_lengths_m(m, geographic=self.geo).mean(1)
            acc = np.zeros(self.ds.sizes["node"]); cnt = np.zeros(self.ds.sizes["node"])
            for k in range(3):
                np.add.at(acc, e[:, k], L); np.add.at(cnt, e[:, k], 1)
            self._res = acc / np.maximum(cnt, 1)
        return self._res

    def load_context(self, c: dict, wd):
        """Tierra y contornos para los mapas (solo dominios reales en lon/lat)."""
        from .figures import cached_mesh
        if (c.get("mesh", {}) or {}).get("generator", default_generator()) != "idealized" and self.geo:
            x, y = self.ds.x.values, self.ds.y.values
            self.land = land_polygons((float(x.min()), float(x.max())), (float(y.min()), float(y.max())))
        hg = wd / "hgrid.gr3"
        try:
            if hg.exists() and self.ds.sizes["node"] <= 600_000:
                m = cached_mesh(hg)
                if m.nnodes == self.ds.sizes["node"]:
                    self.bmesh = m
        except Exception:   # noqa: BLE001
            self.bmesh = None

    def context_traces(self) -> list:
        return land_traces(self.land) + (boundary_traces(self.bmesh) if self.bmesh is not None else [])

    def layer_text(self, k: int, t: dict) -> str:
        """Nombre del nivel k (0 = fondo): el mismo en el deslizador, el título del mapa y Partículas."""
        if k >= self.nvrt - 1:
            return t["surface"]
        if k == 0:
            return t["bottom_zero"]
        return f"{t['layer']} {k + 1}"

    def is3d(self, var: str) -> bool:
        return self.F.is3d(var)

    def is_vector(self, var: str) -> bool:
        return self.F.is_vector(var)

    def its(self, it: int | None = None) -> list:
        """Instantes que se usan: los del promedio si está activo; si no, el instante pedido (o el del mapa)."""
        if self.window is not None and len(self.window):
            return [int(i) for i in self.window]
        return [self.it if it is None else int(it)]

    def window_text(self, lang: str = "es") -> str:
        from ..analysis.derived import describe_window
        return describe_window(self.ds.time.values, self.window, lang) if self.window is not None else ""

    def signed(self, var: str) -> bool:
        """Campo con signo (escala centrada en 0): elevación, w, vorticidad, ψ y componentes."""
        return var in ("elevation", "verticalVelocity", "vorticity", "vorticity_f", "streamfunction") or (self.is_vector(var) and self.mcomp != "mag")

    def value_range(self, var: str):
        """Rango de colores fijo en toda la simulación (percentiles 1–99 de unos instantes), con derivadas y componentes."""
        if self.iso_ok(var):
            return self.iso_range()
        simple = (not self.F.is_derived(var)) and self.mcomp == "mag" and self.depth_mode == "layer" and self.window is None
        if simple:
            return dataset_range(self.ds, var, self.layer)
        if self.window is not None:
            a = self.field(var, self.it)
        else:
            its = list(range(0, self.ds.time.size, max(1, self.ds.time.size // 6)))
            a = np.stack([np.ravel(self.field(var, i)) for i in its])
        a = np.asarray(a, float)
        if var == "elevation" and np.isfinite(a).any():
            r = elevation_range(a, per_instant=a.ndim > 1); return r if r[1] > r[0] else None
        a = a[np.isfinite(a)]
        if a.size == 0:
            return None
        if self.signed(var):
            m = float(np.nanpercentile(np.abs(a), 99)); return (-m, m) if m > 0 else None
        lo, hi = float(np.nanpercentile(a, 1)), float(np.nanpercentile(a, 99))
        return (lo, hi) if hi > lo else None

    def iso_ok(self, var: str | None = None) -> bool:
        """True si el modo isosuperficie se aplica: variable 3D escalar."""
        var = self.var if var is None else var
        return self.depth_mode == "iso" and var in self.ds and self.is3d(var) and var + "X" not in self.ds

    def iso_label(self, lang: str = "es") -> str:
        v = label(self.var, lang).split(" (")[0]
        return (f"prof. de {v} = {self.iso_value:g} (m)" if lang == "es" else f"depth of {v} = {self.iso_value:g} (m)")

    def iso_range(self) -> tuple[float, float] | None:
        """Rango (percentiles 1-99) de la profundidad de la isosuperficie en unos pocos instantes, para la escala fija."""
        from ..analysis.isosurface import isosurface_depth
        its = range(0, self.ds.time.size, max(1, self.ds.time.size // 6))
        a = np.concatenate([isosurface_depth(self.ds, self.var, self.iso_value, i, self.vg).values for i in its])
        if not np.isfinite(a).any():
            return None
        return float(np.nanpercentile(a, 1)), float(np.nanpercentile(a, 99))

    def field(self, var: str, it: int) -> np.ndarray:
        """Campo nodal 2D de la variable en el instante (o media de la ventana): capa, profundidad fija o profundidad de
        la isosuperficie; variables derivadas y componentes con signo de los vectores."""
        ds = self.ds
        if self.iso_ok(var):
            from ..analysis.isosurface import isosurface_depth
            return np.nanmean([isosurface_depth(ds, var, self.iso_value, i, self.vg).values for i in self.its(it)], axis=0)
        if self.F.is_derived(var) or self.window is not None or (self.is_vector(var) and self.mcomp != "mag"):
            depth = self.depth_m if (self.is3d(var) and self.depth_mode == "depth") else None
            return self.F.nodal(var, self.its(it), layer=self.layer if self.is3d(var) else None, depth=depth,
                                comp=self.mcomp if self.is_vector(var) else "mag")
        if self.is3d(var) and self.depth_mode == "depth":
            if var + "X" in ds:
                return np.hypot(field_at_depth(ds, var + "X", it, self.depth_m, self.vg), field_at_depth(ds, var + "Y", it, self.depth_m, self.vg))
            return field_at_depth(ds, var, it, self.depth_m, self.vg)
        return _values(ds, var, it, self.layer)

    def contour_grid(self, it: int):
        """Campo de las isolíneas en la rejilla del mapa (None si no hay): profundidad (fija) o una variable en el instante."""
        c = self.contour
        if not c:
            return None
        if c == "depth":
            return self.sampler.grid(self.ds.depth.values)
        if c not in self.vars:
            return None
        return self.sampler.grid(self.field(c, it))

    def add_point(self, x: float, y: float, name: str | None = None, station: bool = False) -> dict:
        from ..analysis import nearest_node
        p = dict(name=name or f"P{len(self.points) + 1}", x=float(x), y=float(y), node=nearest_node(self.ds, x, y), color=COLORS[len(self.points) % len(COLORS)], station=station)
        self.points.append(p); return p

    def add_section(self, p0, p1, name: str | None = None) -> dict:
        s = dict(name=name or f"S{len(self.sections) + 1}", p0=(float(p0[0]), float(p0[1])), p1=(float(p1[0]), float(p1[1])),
                 color=SECTION_COLORS[len(self.sections) % len(SECTION_COLORS)], visible=True)
        s["sec"] = Section(self.ds, s["p0"], s["p1"], vg=self.vg, tri=self.tri)
        self.sections.append(s); return s


DERIVED_NAMES = {"es": {"vorticity": "vorticity (ζ)", "vorticity_f": "vorticity / f (ζ/f)", "transport": "transport (Tx, Ty)",
                         "streamfunction": "streamfunction (ψ, Sv; cuencas cerradas)"},
                  "en": {"vorticity": "vorticity (ζ)", "vorticity_f": "vorticity / f (ζ/f)", "transport": "transport (Tx, Ty)",
                         "streamfunction": "streamfunction (ψ, Sv; closed basins)"}}


def var_name(v: str, lang: str = "es") -> str:
    """Nombre en los selectores: el de SCHISM o, para las derivadas, con su símbolo."""
    return DERIVED_NAMES.get(lang, DERIVED_NAMES["es"]).get(v, v)


def nearest_output(times, text) -> int | None:
    """Índice de la salida más próxima a una fecha escrita («2020-01-10 06:00», «2020-01-10T06», «2020-01-10»)."""
    try:
        t = np.datetime64(str(text).strip().replace(" ", "T"), "s")
    except (ValueError, TypeError):
        return None
    tt = np.asarray(times).astype("datetime64[s]")
    return int(np.argmin(np.abs((tt - t).astype("int64"))))


def default_cmap(var: str) -> str:
    return "RdBu_r" if var == "elevation" else ("RdYlBu_r" if var == "temperature" else ("RdBu_r" if var == "verticalVelocity" else "Viridis"))


def _nice_step(span: float, n: int = 10) -> float:
    """Intervalo «redondo» (1, 2, 2.5 o 5 × 10^k) para unas `n` isolíneas en un rango `span`."""
    if not np.isfinite(span) or span <= 0:
        return 0.0
    raw = span / n; k = np.floor(np.log10(raw)); b = raw / 10 ** k
    return float(next(m for m in (1, 2, 2.5, 5, 10) if b <= m) * 10 ** k)


def contour_levels(C, step: float = 0.0):
    """(inicio, fin, intervalo) de las isolíneas DENTRO del rango del campo (sin los extremos: en un fondo plano el valor
    extremo es casi todo el dominio y su isolínea dibujaría el ruido de la interpolación). None si el campo es constante."""
    C = np.asarray(C, float); C = C[np.isfinite(C)]
    if C.size == 0:
        return None
    lo, hi = float(np.nanpercentile(C, 0.5)), float(np.nanpercentile(C, 99.5))
    if not hi > lo:
        return None
    step = float(step) if step and step > 0 else _nice_step(hi - lo)
    eps = 1e-6 * (hi - lo)
    a = np.ceil((lo + eps) / step) * step; b = np.floor((hi - eps) / step) * step
    if b < a:
        return None
    return float(a), float(b), step


def contour_trace(C, xi, yi, step: float = 0.0, dark: bool = False, name: str = ""):
    """Isolíneas con etiquetas sobre el mapa de color (None si el campo es constante)."""
    lv = contour_levels(C, step)
    if lv is None:
        return None
    C = np.asarray(C, float)
    col = "rgba(255,255,255,0.85)" if dark else "rgba(20,20,20,0.8)"
    return go.Contour(x=xi, y=yi, z=np.where(np.isfinite(C), C, None).tolist(), showscale=False, hoverinfo="skip", name=name, showlegend=False,
                      autocontour=False, contours=dict(start=lv[0], end=lv[1], size=lv[2], coloring="none", showlabels=True,
                                                       labelfont=dict(size=10, color=col)),
                      line=dict(color=col, width=1))


def map_figure(st: ExplorerState, t: dict, lang: str):
    ds = st.ds; var, it = st.var, st.it
    when = np.datetime_as_string(ds.time.values[it], "m").replace("T", " ")
    if st.background == "resolution":                      # fondo: tamaño de elemento (m), escala logarítmica
        Z = st.sampler.grid(st.resolution()); label_ = t["bg_resolution"]; cs = "Turbo"; zmin = zmax = None
        Z = np.log10(np.maximum(Z, 1e-3)); tickvals = None
        title = f"{label_} · log10(m)"
    elif st.background == "depth":
        Z = st.sampler.grid(ds.depth.values); label_ = label("depth", lang); cs = "deep"; zmin, zmax = float(min(0.0, np.nanmin(Z))), None; title = label_
    elif st.iso_ok():                                      # profundidad de la isosuperficie var = iso_value
        Z = st.sampler.grid(st.field(var, it)); label_ = st.iso_label(lang)
        zmin, zmax = (st.zr if (st.fixed and st.zr) else (None, None))
        if st.zmanual is not None:
            zmin, zmax = st.zmanual
        cs = "deep" if st.cmap == "auto" else st.cmap
        title = f"{label_} · {st.window_text(lang) if st.window is not None else when}"
    else:
        f = st.field(var, it); Z = st.sampler.grid(f); label_ = label(var, lang, st.mcomp if st.is_vector(var) else "mag")
        sym = st.signed(var)
        zmin, zmax = (st.zr if (st.fixed and st.zr) else (None, None))
        if st.zmanual is not None:
            zmin, zmax = st.zmanual
        elif sym and zmin is None and np.isfinite(Z).any():
            if var == "elevation":
                zmin, zmax = elevation_range(Z)
            else:
                m = float(np.nanmax(np.abs(Z))); zmin, zmax = -m, m
        cs = ("RdBu_r" if sym else default_cmap(var)) if st.cmap == "auto" else st.cmap
        lvl = (f"{st.depth_m:g} m" if st.depth_mode == "depth" else st.layer_text(st.layer, t)) if st.is3d(var) else ""
        title = f"{label_} · {st.window_text(lang) if st.window is not None else when}" + (f" · {lvl}" if lvl else "")
    _fin = Z[np.isfinite(Z)] if np.size(Z) else np.array([])
    _lo = zmin if zmin is not None else (float(_fin.min()) if _fin.size else None)
    _hi = zmax if zmax is not None else (float(_fin.max()) if _fin.size else None)
    ticks = zero_ticks(_lo, _hi)
    tfmt = ".3g"
    if _lo is not None and _hi is not None and max(abs(_lo), abs(_hi)) >= 100:      # densidad 1025–1027: decimales, no «1.03e+3»
        tfmt = color_range(_fin, _lo, _hi)[2]
    fig = go.Figure(go.Heatmap(x=st.sampler.xi, y=st.sampler.yi, z=Z, colorscale=cs, zmin=zmin, zmax=zmax, zsmooth="best",
                               colorbar=dict(title=label_, thickness=14, tickformat=tfmt, tickvals=ticks),
                               hovertemplate=("%{x:.4f}, %{y:.4f}" if st.geo else "x %{x:.0f} m, y %{y:.0f} m") + "<br>%{z:.4g}<extra></extra>"))
    C = st.contour_grid(it)
    st._frame = dict(z=Z, zmin=zmin, zmax=zmax, title=title, C=C, ticks=ticks)   # para la vía rápida (Plotly 6 codifica z en binario)
    ctr = contour_trace(C, st.sampler.xi, st.sampler.yi, st.contour_step, st.dark) if C is not None else None
    if ctr is not None:                                    # isolíneas: siempre la traza 1 (refresh_map_time la actualiza)
        fig.add_trace(ctr)
        lv = contour_levels(C, st.contour_step)
        cname = label("depth", lang).split(" (")[0] if st.contour == "depth" else label(st.contour, lang).split(" (")[0]
        title += f" · {t['isolines'].lower()}: {cname} {lv[2]:g}"
        st._frame["title"] = title
    if st.show_mesh:
        ex, ey, step = st.mesh_edges()
        fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="rgba(0,0,0,0.35)", width=0.5), hoverinfo="skip", showlegend=False))
        if step > 1:
            fig.add_annotation(x=0.01, y=0.02, xref="paper", yref="paper", showarrow=False, xanchor="left", font=dict(size=10, color="#333"), bgcolor="rgba(255,255,255,0.7)",
                               text=(f"malla: 1 de cada {step} aristas" if lang == "es" else f"mesh: 1 in {step} edges"))
    if st.arrows and (arrow_field(ds, var) or st.is_vector(var)):
        try:
            aname = var if st.is_vector(var) else arrow_field(ds, var)
            uv = None
            if st.window is not None or st.F.is_derived(var):            # media de la ventana o transporte: u, v del propio campo
                avar = var if st.is_vector(var) else aname
                dep = st.depth_m if (st.depth_mode == "depth" and st.is3d(avar)) else None
                lay = st.layer if st.is3d(avar) else None
                uv = (st.F.nodal(avar, st.its(it), layer=lay, depth=dep, comp="u"), st.F.nodal(avar, st.its(it), layer=lay, depth=dep, comp="v"))
                aname = avar
            tr, vmax = map_arrows(ds, it, st.layer, depth_m=st.depth_m if st.depth_mode == "depth" else None, vg=st.vg, var=var, uv=uv)
            fig.add_trace(tr)
            lvl_a = ""
            if st.is3d(aname):
                lvl_a = f" ({st.depth_m:g} m)" if st.depth_mode == "depth" else f" ({st.layer_text(st.layer, t)})"
            what = ("flechas: " if lang == "es" else "arrows: ") + aname + lvl_a
            fig.add_annotation(x=0.99, y=0.02, xref="paper", yref="paper", showarrow=False, xanchor="right",
                               text=f"{what} · {'máx' if lang == 'es' else 'max'} {vmax:.3g} {arrow_units(aname)}",
                               font=dict(size=10), bgcolor="rgba(255,255,255,0.7)")
        except Exception:   # noqa: BLE001  (sin ese campo en esa capa)
            pass
    for tr in st.context_traces():
        fig.add_trace(tr)
    for p in st.points:
        fig.add_trace(go.Scatter(x=[p["x"]], y=[p["y"]], mode="markers+text", text=[p["name"]], textposition="top right", marker=dict(color=p["color"], size=11, line=dict(color="#fff", width=1.5)),
                                 hovertemplate=f"{p['name']}<extra></extra>", showlegend=False))
    vis = [s for s in st.sections if s.get("visible", True)]
    st.shape_index = [i for i, s in enumerate(st.sections) if s.get("visible", True)]   # forma k -> sección shape_index[k]
    for s in vis:                                          # halo blanco: la sección se ve sobre cualquier fondo
        fig.add_trace(go.Scatter(x=[s["p0"][0], s["p1"][0]], y=[s["p0"][1], s["p1"][1]], mode="lines", line=dict(color="rgba(255,255,255,0.9)", width=7),
                                 hoverinfo="skip", showlegend=False))
    shapes = [dict(type="line", x0=s["p0"][0], y0=s["p0"][1], x1=s["p1"][0], y1=s["p1"][1], line=dict(color=s["color"], width=3), editable=True) for s in vis]
    for s in vis:
        fig.add_annotation(x=s["p1"][0], y=s["p1"][1], text=f"<b>{s['name']}</b>", showarrow=False, font=dict(color=s["color"], size=13), xanchor="left",
                           bgcolor="rgba(255,255,255,0.85)", borderpad=2)
    if st.pending is not None:
        fig.add_trace(go.Scatter(x=[st.pending[0]], y=[st.pending[1]], mode="markers", marker=dict(symbol="x", color="#000", size=12), showlegend=False, hoverinfo="skip"))
    # dragmode siempre «zoom»: en «drawline» Plotly no emite plotly_click y los dos clics de la pestaña Secciones no llegarían;
    # la herramienta de línea sigue disponible en la barra del mapa (modeBarButtonsToAdd)
    fig.update_layout(title=title, shapes=shapes, dragmode="zoom", uirevision="map",
                      newshape=dict(line=dict(color="#000", width=3)), xaxis=dict(title="lon" if st.geo else "x (m)", constrain="domain"),
                      yaxis=dict(title="lat" if st.geo else "y (m)", scaleanchor="x", scaleratio=_aspect(ds.y.values)), **LAYOUT)
    d = fig.to_plotly_json(); d["config"] = PLOTLY_CONFIG
    return d


STAOUT_VAR = {"elevation": ("elev",), "temperature": ("T",), "salinity": ("S",), "verticalVelocity": ("w",), "horizontalVel": ("u", "v"), "depthAverageVel": ("u", "v")}


def station_series(wd: Path, var: str, name: str):
    """Serie de la estación `name` en staout (muestreo fino) para la variable del explorador, o None si no está."""
    from ..analysis import read_stations
    keys = STAOUT_VAR.get(var)
    if not keys or wd is None:
        return None
    try:
        ds_ = [read_stations(wd, k) for k in keys]
        if any(name not in d.columns for d in ds_):
            return None
        if len(ds_) == 2:                                # vector: componentes (u hacia el este, v hacia el norte)
            return ds_[0].index.values, {"u": ds_[0][name].values.astype(float), "v": ds_[1][name].values.astype(float)}
        return ds_[0].index.values, ds_[0][name].values
    except (FileNotFoundError, OSError, ValueError):
        return None


def series_figure_multi(st: ExplorerState, var: str, lang: str, wd: Path | None = None) -> go.Figure:
    """Series de los puntos con un marcador en el instante del mapa (st.it) y una línea vertical; `series_cursor`
    los mueve sin redibujar las series."""
    fig = go.Figure(); used_sta = False; lines = []
    if st.iso_ok(var):                                     # profundidad de la isosuperficie en cada punto
        from ..analysis.isosurface import isosurface_series
        for p in st.points:
            y = isosurface_series(st.ds, var, st.iso_value, p["node"], st.vg)
            fig.add_trace(go.Scatter(x=st.ds.time.values, y=y, mode="lines", name=p["name"], line=dict(color=p["color"], width=2)))
            lines.append((np.asarray(st.ds.time.values), np.asarray(y, float), p["color"]))
        fig.update_layout(yaxis=dict(title=st.iso_label(lang), autorange="reversed"), hovermode="x unified", **layout(st.dark))
    else:
        comp = getattr(st, "component", "uv")
        dash = {"u": "solid", "v": "dash", "mag": "dot"}
        vector = False
        # estaciones: staout (muestreo fino) solo para variables 2D o en la capa de superficie; en otra capa, a una
        # profundidad fija o para las derivadas, la serie sale del netCDF en el nivel elegido
        surface = st.depth_mode == "layer" and st.layer >= st.nvrt - 1
        use_sta = (not st.F.is_derived(var)) and (not st.is3d(var) or surface)
        depth = st.depth_m if (st.is3d(var) and st.depth_mode == "depth") else None
        for p in st.points:
            sta = station_series(wd, var, p["name"]) if (p.get("station") and use_sta) else None
            if sta is not None:
                t_, y = sta; used_sta = True; suffix = " (staout)"
                comps = y if isinstance(y, dict) else None
            else:
                s = st.F.series(var, p["node"], layer=st.layer if st.is3d(var) else None, depth=depth); t_ = s["t"]; suffix = ""
                comps = {"u": s["u"], "v": s["v"]} if "u" in s else None
                y = s.get("y")
            if comps is None:
                fig.add_trace(go.Scatter(x=t_, y=y, mode="lines", name=p["name"] + suffix, line=dict(color=p["color"], width=2)))
                lines.append((np.asarray(t_), np.asarray(y, float), p["color"]))
                continue
            vector = True
            comps = {**comps, "mag": np.hypot(comps["u"], comps["v"])}
            for k in ({"uv": ("u", "v"), "u": ("u",), "v": ("v",), "mag": ("mag",)}[comp if comp in ("uv", "u", "v", "mag") else "uv"]):
                nm = {"u": "u", "v": "v", "mag": "|u|"}[k]
                fig.add_trace(go.Scatter(x=t_, y=comps[k], mode="lines", name=f"{p['name']} {nm}{suffix}",
                                         line=dict(color=p["color"], width=2, dash=dash[k])))
                lines.append((np.asarray(t_), np.asarray(comps[k], float), p["color"]))
        ytitle = label(var, lang)
        if vector and comp != "mag":
            un = VECTOR_UNITS.get(var) or st.F.units(var) or "m/s"                  # transporte: m²/s
            ytitle = f"u (este), v (norte) ({un})" if lang == "es" else f"u (east), v (north) ({un})"
        fig.update_layout(yaxis_title=ytitle, hovermode="x unified", **layout(st.dark))
        if vector and comp in ("uv", "u", "v"):
            fig.add_hline(y=0, line=dict(color="#999", width=1))
        if used_sta:
            fig.add_annotation(x=0.01, y=0.98, xref="paper", yref="paper", showarrow=False, xanchor="left", font=dict(size=10, color="#555"),
                               text=("estaciones: serie fina de staout" + (" (serie de superficie)" if st.is3d(var) else "")) if lang == "es"
                               else ("stations: fine staout series" + (" (surface series)" if st.is3d(var) else "")))
    if st.window is not None and len(st.window) and lines:              # promedio entre t1 y t2: banda y media de cada serie
        tt = np.asarray(st.ds.time.values); a, b = tt[st.window[0]], tt[st.window[-1]]
        fig.add_vrect(x0=a, x1=b, fillcolor="rgba(120,120,120,0.12)", line_width=0)
        notes = []; means = []
        for (t_, y_, col), tr in zip(lines, [d for d in fig.data]):
            t_ = np.asarray(t_); m = (t_ >= a) & (t_ <= b)
            if m.any():
                mu = float(np.nanmean(np.asarray(y_, float)[m]))
                fig.add_trace(go.Scatter(x=[a, b], y=[mu, mu], mode="lines", line=dict(color=col, width=2, dash="dot"), showlegend=False,
                                         hovertemplate=f"{tr.name}: {'media' if lang == 'es' else 'mean'} %{{y:.4g}}<extra></extra>"))
                notes.append(f"{tr.name} {mu:.4g}"); means.append((tr.name, mu, col))
        lines_mean = len(notes)
        if notes:                                  # el título solo dice la ventana; las medias van en la tabla bajo la figura
            fig.update_layout(title=dict(text=("media " if lang == "es" else "mean ") + st.window_text(lang).split("(", 1)[-1].rstrip(")"),
                                         font=dict(size=11)))
        st._mean_traces = lines_mean
        st.series_means = means
    else:
        st._mean_traces = 0
        st.series_means = []
    st.series_lines = lines
    shapes0 = list(fig.layout.shapes or []); fig.layout.shapes = ()
    xs, ys, tc = series_cursor(st)
    for (_, _, col), x_, y_ in zip(lines, xs, ys):        # marcador del instante actual en cada serie
        fig.add_trace(go.Scatter(x=[x_], y=[y_], mode="markers", showlegend=False, hoverinfo="skip",
                                 marker=dict(color=col, size=11, line=dict(color="white", width=2))))
    if lines:                                              # la línea del instante es la forma 0 (la mueve series_cursor)
        fig.add_shape(type="line", xref="x", yref="paper", x0=tc, x1=tc, y0=0, y1=1, line=dict(color="#888", width=1, dash="dot"))
    for sh in shapes0:
        fig.add_shape(sh)
    return fig


def section_values(st: ExplorerState, s: dict, var: str, its, comp: str = "mag", layer: int | None = None):
    """Valores de `var` en la sección (media de los instantes `its`): (F, z, vel). F es (npts, nvrt) en las variables
    3D y (npts,) en las 2D (o en la capa `layer` si se pide). comp: mag | u | v | normal | tangential (vectores).
    vel = (u_s, w) medios para las flechas, o None."""
    sec = s["sec"]; F_ = st.F
    its = [int(i) for i in np.atleast_1d(its)]
    if F_.is_vector(var) and comp != "mag":
        u, v = F_.columns(var, its, "uv")
        ui_, vi_ = sec.interp(u), sec.interp(v)
        F = {"u": ui_, "v": vi_, "normal": ui_ * sec.normal[0] + vi_ * sec.normal[1],
             "tangential": ui_ * sec.tangent[0] + vi_ * sec.tangent[1]}.get(comp, np.hypot(ui_, vi_))
    elif var == "streamfunction":
        F = sec.interp(F_.nodal(var, its))
    else:
        F = sec.interp(F_.columns(var, its, "mag"))
    if F.ndim == 2 and layer is not None:
        F = F[:, int(layer)]
    z = vel = None
    if F.ndim == 2:
        z = sec.interp(F_.mean_z(its)) if len(its) > 1 else sec.z(its[0])
        if len(its) > 1 and F_.velocity_name():
            u, v = F_.columns(F_.velocity_name(), its, "uv")
            us = sec.interp(u) * sec.tangent[0] + sec.interp(v) * sec.tangent[1]
            w = sec.interp(np.nanmean([_clean_w(st.ds, i) for i in its], axis=0)) if "verticalVelocity" in st.ds else None
            if us.ndim == 2:
                vel = (us, w)
    return F, z, vel


def _clean_w(ds, it):
    a = np.asarray(ds.verticalVelocity.isel(time=it).values, float)
    return np.where(a < -9000, np.nan, a)


def section_hovmoller(st: ExplorerState, s: dict, var: str, comp: str = "mag") -> np.ndarray:
    """H (tiempo, distancia) de `var` (componente, derivada o 2D) en la capa del mapa o a la profundidad fija."""
    rows = []
    for i in range(st.ds.time.size):
        if st.is3d(var) and st.depth_mode == "depth":
            F, z, _ = section_values(st, s, var, [i], comp)
            from ..analysis.sections import interp_at_depth
            rows.append(interp_at_depth(F, z, st.depth_m))
        else:
            F, _, _ = section_values(st, s, var, [i], comp, layer=st.layer if st.is3d(var) else None)
            rows.append(F)
    return np.stack(rows)


def ekman_profile(st: ExplorerState, node: int, its, ref_mode: str = "level", k: int = 7, fit=(-28.0, 0.0), integ=None, lang: str = "es") -> dict:
    """Perfil medio (z, u, v, viscosidad) en el nodo y lecturas de la espiral: resta la velocidad del nivel k o la
    geostrófica de la pendiente de η (necesaria con k-kl, donde el nivel profundo no está fuera de la capa de Ekman)."""
    from ..analysis.profiles import ekman_readouts, geostrophic
    ds = st.ds; its = [int(i) for i in np.atleast_1d(its)]
    u, v = st.F.columns("horizontalVel", its, "uv")
    u, v = u[node], v[node]
    z = (st.F.mean_z(its) if len(its) > 1 else st.F.zcor(its[0]))[node]
    f = float(st.fcor[node]) if st.fcor is not None else None
    wind = None
    if "windStressX" in ds:
        wind = (float(np.nanmean(ds.windStressX.isel(node=node, time=its).values)), float(np.nanmean(ds.windStressY.isel(node=node, time=its).values)))
    ref = None; ref_txt = ""
    if ref_mode == "level":
        kk = int(np.clip(k, 0, len(z) - 1)); ref = (float(u[kk]), float(v[kk])); ref_txt = f"{'nivel' if lang == 'es' else 'level'} {kk} (z = {z[kk]:.1f} m)"
    elif ref_mode == "geo":
        if f is None or "elevation" not in ds:
            raise ValueError("la geostrófica necesita Coriolis y la elevación / geostrophic velocity needs Coriolis and elevation")
        ref = geostrophic(ds, node, its, f); ref_txt = "geostrófica de η" if lang == "es" else "geostrophic from η"
    r = ekman_readouts(z, u, v, wind=wind, ref=ref, fit=fit, integ=integ, f=f)
    visc = None
    if "viscosity" in ds:
        a = np.asarray(ds.viscosity.isel(node=node, time=its).values, float)
        visc = np.nanmean(np.where(a < -9000, np.nan, a), axis=0) if a.ndim == 2 else a
    vr = None
    if visc is not None and r.get("De"):                     # viscosidad en el tramo del ajuste: ¿es constante?
        lo, hi = min(fit), max(fit); hi = np.inf if hi >= 0 else hi
        vv = np.asarray(visc, float)[(z >= lo) & (z <= hi)]; vv = vv[np.isfinite(vv) & (vv > 0)]
        if vv.size >= 2:
            vr = (float(vv.min()), float(vv.max()))
    return dict(r, u=u, v=v, zraw=z, visc=visc, visc_range=vr, wind=wind, f=f, ref=ref, ref_txt=ref_txt, n=len(its))


def ekman_figures(d: dict, lang: str = "es", theory=None):
    """(perfil, hodógrafa): u, v, |v| (y viscosidad en otro eje) frente a z; v_E frente a u_E con la misma escala."""
    from plotly.subplots import make_subplots
    es = lang == "es"
    has_v = d.get("visc") is not None
    pf = make_subplots(rows=1, cols=2 if has_v else 1, shared_yaxes=True, column_widths=[0.62, 0.38] if has_v else None, horizontal_spacing=0.04)
    z = d["zraw"]; u, v = d["u"], d["v"]
    pf.add_trace(go.Scatter(x=u, y=z, mode="lines+markers", name="u", marker=dict(size=4)), 1, 1)
    pf.add_trace(go.Scatter(x=v, y=z, mode="lines+markers", name="v", line=dict(dash="dash"), marker=dict(size=4)), 1, 1)
    pf.add_trace(go.Scatter(x=np.hypot(u, v), y=z, mode="lines", name="|v|", line=dict(dash="dot", color="#888")), 1, 1)
    pf.update_xaxes(title_text="u (este), v (norte), |v| (m/s)" if es else "u (east), v (north), |v| (m/s)", row=1, col=1)
    if has_v:
        pf.add_trace(go.Scatter(x=d["visc"], y=z, mode="lines+markers", name="viscosity", line=dict(color="#7a4fb8"), marker=dict(size=4)), 1, 2)
        vm = float(np.nanmax(d["visc"])) if np.isfinite(d["visc"]).any() else 0.0
        pf.update_xaxes(title_text="viscosidad (m²/s)" if es else "viscosity (m²/s)", row=1, col=2,
                        range=[0, vm * 1.15] if vm > 0 else None, tickformat=".2g")
    pf.update_yaxes(title_text="z (m)", row=1, col=1)
    pf.update_layout(**LAYOUT)
    pf.update_layout(legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom"), margin=dict(l=50, r=20, t=70, b=50))
    hf = go.Figure()
    uE, vE, zE = d["uE"], d["vE"], d["z"]
    if d.get("bottom_still") and len(zE) > 2:          # el nivel del fondo (u = v = 0) restado sería un punto suelto (−u_ref, −v_ref)
        uE, vE, zE = uE[1:], vE[1:], zE[1:]
    hf.add_trace(go.Scatter(x=uE, y=vE, mode="lines+markers", name="modelo" if es else "model", marker=dict(size=5),
                            text=[f"z = {zz:.1f} m" for zz in zE], hovertemplate="%{text}<br>u_E %{x:.4f}<br>v_E %{y:.4f}<extra></extra>"))
    if theory is not None and theory[0] > 0 and theory[1] > 0:
        from ..analysis.profiles import theoretical_spiral
        wd_ = d["wind"] if d.get("wind") and np.hypot(*d["wind"]) > 0 else (1.0, 0.0)
        zt, ut, vt = theoretical_spiral(theory[0], theory[1], d.get("f") or 1.0, wind_dir=wd_, zmin=float(np.nanmin(d["z"])))
        hf.add_trace(go.Scatter(x=ut, y=vt, mode="lines", name="teoría" if es else "theory", line=dict(color="#111", dash="dash")))
    if d.get("wind") and np.hypot(*d["wind"]) > 0:
        w = np.asarray(d["wind"], float); L = float(np.nanmax(np.hypot(uE, vE)) or 1.0) * 0.6; w = w / np.hypot(*w) * L
        hf.add_annotation(x=w[0], y=w[1], ax=0, ay=0, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=2, arrowcolor="#d8542b", text="")
        hf.add_annotation(x=w[0], y=w[1], xref="x", yref="y", showarrow=False, text="viento" if es else "wind", font=dict(color="#d8542b"),
                          xanchor="left" if w[0] >= 0 else "right", yanchor="bottom")
    hf.add_hline(y=0, line=dict(color="#999", width=1)); hf.add_vline(x=0, line=dict(color="#999", width=1))
    hf.update_layout(xaxis=dict(title="u_E (m/s)", zeroline=False), yaxis=dict(title="v_E (m/s)", scaleanchor="x", scaleratio=1, zeroline=False),
                     title=dict(text=("hodógrafa (un punto por nivel)" if es else "hodograph (one point per level)") +
                                (f" · {'restando' if es else 'minus'} {d['ref_txt']}" if d.get("ref_txt") else ""), font=dict(size=12)),
                     **LAYOUT)
    hf.update_layout(legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom"), margin=dict(l=60, r=20, t=70, b=50))
    return pf, hf


def ekman_text(d: dict, lang: str = "es") -> str:
    """Lecturas automáticas de la espiral, en una caja de texto."""
    es = lang == "es"; L = []
    L.append((f"Promedio de {d['n']} salida{'s' if d['n'] != 1 else ''}" if es else f"Mean of {d['n']} output{'s' if d['n'] != 1 else ''}")
             + (f" · {'restando' if es else 'minus'} {d['ref_txt']}" if d.get("ref_txt") else ""))
    s = f"|v_E(0)| = {d['surface']:.4g} m/s"
    if d.get("surface_angle") is not None:
        s += (f", a {d['surface_angle']:.1f}° a la derecha del viento" if es else f", {d['surface_angle']:.1f}° to the right of the wind")
    L.append(("Corriente en superficie: " if es else "Surface current: ") + s)
    if d.get("z_reverse") is not None:
        L.append((f"Va en sentido contrario a la de superficie a {abs(d['z_reverse']):.1f} m" if es else f"Opposite to the surface current at {abs(d['z_reverse']):.1f} m"))
    if d.get("De"):
        az = f" → Az = |f| De²/2 = {d['Az']:.4g} m²/s" if d.get("Az") else ""
        L.append((f"Ajuste de ln|v_E| ({d['n_fit']} niveles): De = {d['De']:.3g} m, V0 = {d['V0_fit']:.4g} m/s{az}" if es
                  else f"Fit of ln|v_E| ({d['n_fit']} levels): De = {d['De']:.3g} m, V0 = {d['V0_fit']:.4g} m/s{az}"))
        vr = d.get("visc_range")
        if vr and vr[1] > 1.5 * vr[0]:                     # k-kl: A_z cambia en el tramo; De y Az del ajuste no son los de la teoría
            L.append((f"Aviso: el ajuste supone A_z constante, y en ese tramo la viscosidad va de {vr[0]:.2g} a {vr[1]:.2g} m²/s" if es
                      else f"Warning: the fit assumes constant A_z, but in that range the viscosity goes from {vr[0]:.2g} to {vr[1]:.2g} m²/s"))
    if d.get("Tx") is not None:
        a = (f", a {d['T_angle']:.1f}° a la derecha del viento" if es else f", {d['T_angle']:.1f}° to the right of the wind") if d.get("T_angle") is not None else ""
        L.append((f"Transporte (∫ u_E dz, ∫ v_E dz): Tx = {d['Tx']:.4g} m²/s, Ty = {d['Ty']:.4g} m²/s{a}" if es
                  else f"Transport (∫ u_E dz, ∫ v_E dz): Tx = {d['Tx']:.4g} m²/s, Ty = {d['Ty']:.4g} m²/s{a}"))
    return "\n".join(L)


VECTOR_UNITS = {"horizontalVel": "m/s", "depthAverageVel": "m/s", "windStress": "m²/s²", "transport": "m²/s", "windSpeed": "m/s"}


def line_readout(info: dict, units: str, lang: str = "es") -> str:
    """Texto de las lecturas del perfil a lo largo de la sección: ajuste (α, 1/α), integral y cruces por cero."""
    es = lang == "es"; out = []
    r = info.get("fit")
    if r:
        kind = "ln|y − ref|" if r["log"] else "y − ref"
        sc = f"{r['scale_km']:.4g} km" if r.get("scale_km") is not None else "∞"
        out.append((f"Ajuste de {kind} entre {r['x0_km']:g} y {r['x1_km']:g} km ({r['n']} puntos): pendiente α = {r['alpha']:.4g} 1/m · 1/α = {sc}")
                   if es else (f"Fit of {kind} between {r['x0_km']:g} and {r['x1_km']:g} km ({r['n']} points): slope α = {r['alpha']:.4g} 1/m · 1/α = {sc}"))
    elif "fit" in info:
        out.append("Ajuste: no hay datos en ese tramo" if es else "Fit: no data in that range")
    if info.get("integral") is not None:
        I = info["integral"]; u = info.get("integral_units", "")
        extra = f" = {I / 1e6:.4g} Sv" if u == "m³/s" else ""
        out.append((f"Integral a lo largo de la sección: {I:.4g} {u}{extra}") if es else (f"Integral along the section: {I:.4g} {u}{extra}"))
    if info.get("zeros"):
        z = ", ".join(f"{x:.1f}" for x in info["zeros"][:6]); r0 = info.get("zeros_ref") or 0.0
        if r0:
            out.append((f"Cruces con y = {r0:g} en: {z} km") if es else (f"Crossings of y = {r0:g} at: {z} km"))
        else:
            out.append((f"Cambios de signo en: {z} km") if es else (f"Sign changes at: {z} km"))
    return "\n".join(out)


def series_cursor(st: ExplorerState):
    """(x, y de cada marcador, instante) en st.it: el valor de cada serie más próximo al instante del mapa."""
    tc = np.asarray(st.ds.time.values)[st.it]
    xs, ys = [], []
    for t_, y, _ in getattr(st, "series_lines", []):
        if t_.size == 0:
            xs.append(None); ys.append(None); continue
        k = int(np.argmin(np.abs(t_.astype("datetime64[s]").astype("int64") - np.datetime64(tc, "s").astype("int64"))))
        xs.append(np.datetime_as_string(np.datetime64(t_[k], "s"))); v = y[k]
        ys.append(float(v) if np.isfinite(v) else None)
    return xs, ys, np.datetime_as_string(np.datetime64(tc, "s"))


def animation_figure2(st: ExplorerState, t: dict, lang: str, step: int = 1, progress=None) -> go.Figure:
    """Animación del mapa (mapa de calor + flechas en cada fotograma, escala fija)."""
    ds = st.ds; var = st.var
    zr = st.zr or st.value_range(var) or dataset_range(ds, "elevation", -1)
    frames = []
    its = list(range(0, ds.time.size, step))
    for k, it in enumerate(its):
        Z = st.sampler.grid(st.field(var, it))
        data = [go.Heatmap(x=st.sampler.xi, y=st.sampler.yi, z=Z, colorscale="RdBu_r" if var == "elevation" else ("RdYlBu_r" if var == "temperature" else "Viridis"), zmin=zr[0], zmax=zr[1], zsmooth="best")]
        if st.arrows and arrow_field(ds, var):
            data.append(map_arrows(ds, it, st.layer, depth_m=st.depth_m if st.depth_mode == "depth" else None, vg=st.vg, var=var)[0])
        data += st.context_traces()
        frames.append(go.Frame(data=data, name=str(it), layout=go.Layout(title=np.datetime_as_string(ds.time.values[it], "m").replace("T", " "))))
        if progress:
            progress((k + 1) / len(its))
    fig = go.Figure(data=frames[0].data, frames=frames)
    fig.update_layout(title=frames[0].layout.title, yaxis=dict(scaleanchor="x", scaleratio=_aspect(ds.y.values)), **LAYOUT,
                      updatemenus=[dict(type="buttons", showactive=False, x=0.05, y=1.12, buttons=[
                          dict(label="▶", method="animate", args=[None, dict(frame=dict(duration=150, redraw=True), fromcurrent=True)]),
                          dict(label="⏸", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
                      sliders=[dict(steps=[dict(method="animate", args=[[f.name], dict(mode="immediate", frame=dict(duration=0, redraw=True))], label=f.layout.title.text[5:16]) for f in frames],
                                    currentvalue=dict(visible=False), pad=dict(t=30))])
    return fig


def section_animation(st: ExplorerState, s: dict, var: str, lang: str, step: int = 1, progress=None) -> go.Figure:
    sec = s["sec"]
    its = list(range(0, st.ds.time.size, step))
    # rango fijo de colores en toda la animación
    comp = getattr(st, "sec_comp", "mag") if st.is_vector(var) else "mag"
    vals = [section_values(st, s, var, [it], comp)[0] for it in its[:: max(1, len(its) // 6)]]
    zr = (float(np.nanmin([np.nanmin(v) for v in vals])), float(np.nanmax([np.nanmax(v) for v in vals])))
    frames = []
    for k, it in enumerate(its):
        F, z, _ = section_values(st, s, var, [it], comp)
        f = section_figure2(sec, var, it, arrows=st.arrows, contours=False, zrange=zr, lang=lang, F=F, z=z, clabel=label(var, lang, comp))
        frames.append(go.Frame(data=f.data, name=str(it), layout=go.Layout(title=np.datetime_as_string(st.ds.time.values[it], "m").replace("T", " "))))
        if progress:
            progress((k + 1) / len(its))
    base = frames[0]
    fig = go.Figure(data=base.data, frames=frames)
    fig.update_layout(title=base.layout.title, xaxis_title="distancia (km)" if lang == "es" else "distance (km)", yaxis_title="z (m)", **LAYOUT,
                      updatemenus=[dict(type="buttons", showactive=False, x=0.05, y=1.12, buttons=[
                          dict(label="▶", method="animate", args=[None, dict(frame=dict(duration=150, redraw=True), fromcurrent=True)]),
                          dict(label="⏸", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
                      sliders=[dict(steps=[dict(method="animate", args=[[f.name], dict(mode="immediate", frame=dict(duration=0, redraw=True))], label=f.layout.title.text[5:16]) for f in frames],
                                    currentvalue=dict(visible=False), pad=dict(t=30))])
    return fig


# ----------------------------------------------------------------------------- pestaña Mapas y series
def explorer_tab(ds, c: dict, wd: Path, t: dict, lang: str, vg, dark: bool = False) -> ExplorerState:
    st = ExplorerState(ds, vg, c); st.dark = bool(dark)
    st.load_context(c, wd)
    st.zr = dataset_range(ds, st.var, st.layer)
    if not (c.get("stations") or []):                            # sin estaciones: un punto inicial en el centro
        st.add_point(float(ds.x.mean()), float(ds.y.mean()))
    for s_ in (c.get("stations") or []):                        # estaciones del caso como puntos iniciales
        x_, y_ = (s_.get("lon"), s_.get("lat")) if "lon" in s_ else (s_.get("x"), s_.get("y"))
        if x_ is not None and y_ is not None:
            st.add_point(float(x_), float(y_), str(s_.get("name", f"E{len(st.points)}")), station=True)
    initial_points = [dict(p) for p in st.points]                # para poder recuperar las estaciones borradas
    has_vel = any(v + "X" in ds for v in st.vars)                 # flechas: la velocidad o la variable vectorial elegida
    # --- controles: encima del mapa solo variable, capa y tiempo; el estilo va en un acordeón plegado bajo el mapa
    def layer_text(k: int) -> str:
        return st.layer_text(k, t)
    iso_opts = {"": t["iso_none"], "depth": label("depth", lang).split(" (")[0], **{v: v for v in st.vars}}
    with ui.row().classes("w-full items-start").style("gap:16px;flex-wrap:wrap"):
        # ------------------------------------------------------------------ controles (columna izquierda)
        with ui.card().classes("q-pa-md").style("flex:0 0 300px;max-width:100%"):
            ui.label(t["m_color"]).classes("text-subtitle2")
            var = ui.select({v: var_name(v, lang) for v in st.vars}, value=st.var, label=t["variable"]).classes("w-full").mark("var_select")
            mcomp = ui.select({"mag": t["comp_mag"], "u": t["comp_u"], "v": t["comp_v"]}, value="mag", label=t["component_map"]) \
                .classes("w-full").mark("map_component")
            dmode = ui.select({"layer": t["by_layer"], "depth": t["by_depth"], "iso": t["by_iso"]}, value="layer", label=t["level"]).classes("w-full")
            with ui.column().classes("w-full q-pt-md") as lsl_box:
                lsl = ui.slider(min=0, max=max(0, st.nvrt - 1), value=st.layer).props(f'label-always label-value="{layer_text(st.layer)}"').classes("w-full").mark("layer_slider")
            ldep = ui.number(t["depth_fixed"], value=st.depth_m, min=0, step=5).classes("w-full")
            ival = ui.number(t["iso_value"], value=st.iso_value, step=0.5).classes("w-full").mark("iso_value")
            # promedio temporal: la media de las salidas entre t1 y t2 en el mapa, las secciones, los perfiles y las lecturas
            _t0 = np.datetime_as_string(ds.time.values[0], "m").replace("T", " "); _t1 = np.datetime_as_string(ds.time.values[-1], "m").replace("T", " ")
            avg_sw = ui.switch(t["avg_window"], value=False).mark("avg_switch")
            with ui.column().classes("w-full q-gutter-xs") as avg_box:
                avg_a = ui.input(t["avg_from"], value=_t0).props("dense outlined").classes("w-full").mark("avg_from")
                avg_b = ui.input(t["avg_to"], value=_t1).props("dense outlined").classes("w-full").mark("avg_to")
                avg_n = ui.label().classes("text-caption text-grey-7").mark("avg_text")
            avg_box.set_visibility(False)
            with ui.expansion(t["map_style"], icon="palette", value=True).classes("sl-exp w-full q-mt-sm"):
                bg = ui.select({"field": t["bg_field"], "resolution": t["bg_resolution"], "depth": t["bg_depth"]}, value="field", label=t["background"]).classes("w-full")
                iso_sel = ui.select(iso_opts, value="", label=t["isolines"]).classes("w-full").mark("isolines_select")
                iso_step = ui.number(t["iso_step"], value=0, min=0, step=1, format="%g").classes("w-full").mark("isolines_step")
                iso_step.bind_visibility_from(iso_sel, "value", backward=bool)
                arr = ui.switch(t["arrows"], value=False); arr.set_visibility(has_vel)
                cmap = ui.select({"auto": t["cmap_auto"], "Viridis": "Viridis", "RdBu_r": "RdBu", "RdYlBu_r": "RdYlBu", "Turbo": "Turbo", "Cividis": "Cividis", "deep": "deep", "thermal": "thermal", "haline": "haline"}, value="auto", label=t["cmap"]).classes("w-full")
                with ui.row().classes("w-full no-wrap items-end q-gutter-sm"):
                    zlo = ui.number(t["zmin"], value=None).classes("col"); zhi = ui.number(t["zmax"], value=None).classes("col")
                    ui.button(icon="autorenew", on_click=lambda: (zlo.set_value(None), zhi.set_value(None), set_manual())).props("flat dense round").tooltip(t["zauto"])
                fixed = ui.switch(t["fixed_scale"], value=True)
                mesh_sw = ui.switch(t["show_mesh"], value=False)
                speed = ui.select({2: "2 fps", 5: "5 fps", 10: "10 fps"}, value=5, label="▶").classes("w-full")
        # ------------------------------------------------------------------ mapa (derecha)
        with ui.column().style("flex:1 1 600px;min-width:0") as rcol:
            with ui.row().classes("items-center w-full no-wrap q-gutter-sm"):
                with ui.element("div"):                              # el relleno de la fila no entra en el botón
                    play = ui.button(icon="play_arrow").props("round dense color=accent").mark("play_button")
                tsl = ui.slider(min=0, max=ds.time.size - 1, value=st.it).classes("col").mark("time_slider")
                tlabel = ui.input(t["goto_time"]).props("dense outlined").classes("sl-w-md").style("min-width:11.5rem").mark("time_input") \
                    .tooltip(t["goto_time_tip"])
            _ratio = float(np.ptp(ds.y.values) * _aspect(ds.y.values) / max(np.ptp(ds.x.values), 1e-12))
            _h = int(min(720, max(440, 220 + 620 * _ratio)))                 # alto según la forma del dominio
            plot = ui.plotly(themed(map_figure(st, t, lang), st.dark)).classes("w-full").style(f"height:{_h}px").mark("map_plot")
            st.plot = plot

    # --- paneles inferiores
    with rcol, ui.tabs().classes("w-full").props("dense no-caps mobile-arrows").mark("explorer_subtabs") as subtabs:   # debajo del mapa: se traza y se ve a la vez
        tp = ui.tab("tab_points", label=t["points"]); tsec = ui.tab("tab_sections", label=t["sections"]); tan = ui.tab("tab_anim", label=t["animate"])
    with rcol:
        panels = ui.tab_panels(subtabs, value=tp).classes("w-full")
    with panels, ui.tab_panel(tp):
        with ui.row().classes("w-full"):
            plist = ui.column().classes("col-12 col-md-3 q-gutter-xs")
            with ui.column().classes("col-12 col-md-9"):
                st.component = "uv"
                comp_sel = ui.select({"uv": t["comp_uv"], "u": t["comp_u"], "v": t["comp_v"], "mag": t["comp_mag"]}, value="uv",
                                     label=t["component_series"]).props("dense").classes("sl-w-md").mark("component_select")
                sfig = ui.plotly(series_figure_multi(st, st.var, lang, wd)).classes("w-full").style("height:320px").mark("series_plot")
                smeans = ui.html("").classes("w-full text-body2").mark("series_means")
                pfig = ui.plotly(go.Figure()).classes("w-full").style("height:300px")
        with ui.row().classes("q-gutter-sm"):
            ui.button(t["download_series"], icon="download", on_click=lambda: export_series()).props("flat dense")
        # --- perfil y hodógrafa (espiral de Ekman) del último punto, en el instante o en la ventana de promedio
        has_3dvel = "horizontalVelX" in ds and st.nvrt > 2
        with ui.expansion(t["ek_title"], icon="cyclone", value=False).classes("sl-exp w-full q-mt-sm").mark("ekman_panel") as ek_exp:
            ui.label(t["ek_hint"]).classes("text-caption text-grey-7")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                ek_ref = ui.select({"none": t["ek_ref_none"], "level": t["ek_ref_level"], "geo": t["ek_ref_geo"]}, value="level",
                                   label=t["ek_ref"]).classes("sl-w-lg").mark("ek_ref")
                ek_k = ui.number(t["ek_level"], value=min(7, max(0, st.nvrt - 1)), min=0, max=max(0, st.nvrt - 1), step=1, format="%d") \
                    .props("dense").classes("sl-w-sm").mark("ek_level")
                ek_f1 = ui.number(t["ek_fit_from"], value=-28.0, format="%g").props("dense").classes("sl-w-sm").mark("ek_fit_from")
                ek_f2 = ui.number(t["ek_fit_to"], value=0.0, format="%g").props("dense").classes("sl-w-sm").mark("ek_fit_to")
                ek_i1 = ui.number(t["ek_int_from"], value=None, format="%g").props("dense clearable").classes("sl-w-sm").mark("ek_int_from")
                ek_i2 = ui.number(t["ek_int_to"], value=None, format="%g").props("dense clearable").classes("sl-w-sm").mark("ek_int_to")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                ek_th = ui.switch(t["ek_theory"], value=False).mark("ek_theory")
                ek_v0 = ui.number("V0 (m/s)", value=0.2, format="%g", step=0.01).props("dense").classes("sl-w-sm").mark("ek_V0")
                ek_de = ui.number("De (m)", value=14.0, format="%g", step=1).props("dense").classes("sl-w-sm").mark("ek_De")
                ui.button(t["ek_update"], icon="refresh", on_click=lambda: refresh_ekman()).props("flat dense")
            ek_info = ui.label().classes("text-body2 text-weight-medium").style("white-space:pre-line").mark("ek_readout")
            # las figuras se crean al abrir el panel: Plotly toma el ancho del contenedor al dibujar (cerrado, sería 0)
            ek_figbox = ui.row().classes("w-full no-wrap items-start").style("gap:12px;flex-wrap:wrap")
            ek_figs = {}
        ek_exp.set_visibility(has_3dvel)
    with panels, ui.tab_panel(tsec):
        with ui.row().classes("w-full items-start"):
            slist = ui.column().classes("col-12 col-md-4 q-gutter-xs")
            with ui.column().classes("col-12 col-md-8"):
                ui.label(t["explorer_hint"]).classes("text-caption text-grey-7")
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    armed = {"mode": None}
                    def arm(mode):                                   # el siguiente clic en el mapa traza la sección (sin herramienta de línea)
                        armed["mode"] = mode; st.pending = None; st.click_mode = "armed"; refresh_map(); ui.notify(t["sec_click_wait"], timeout=2500)
                    ui.button(t["sec_transversal"], icon="swap_vert", on_click=lambda: arm("transversal")).props("outline dense color=primary").mark("sec_transversal")
                    ui.button(t["sec_longitudinal"], icon="swap_horiz", on_click=lambda: arm("longitudinal")).props("outline dense color=primary").mark("sec_longitudinal")
                    sec_vars = list(st.vars)                                      # 3D: corte vertical; 2D y derivadas: perfil a lo largo del corte
                    svar = ui.select({v: var_name(v, lang) for v in sec_vars}, value=st.var if st.var in sec_vars else sec_vars[0], label=t["variable"]).classes("sl-w-md").mark("sec_var")
                    scomp = ui.select({"mag": t["comp_mag"], "u": t["comp_u"], "v": t["comp_v"], "normal": t["comp_normal"], "tangential": t["comp_tangential"]},
                                      value="mag", label=t["component_sec"]).classes("sl-w-md").mark("sec_component")
                    scont = ui.switch(t["contours"], value=True)
                    slev = ui.switch(t["sec_atlevel"], value=False).mark("sec_atlevel")
                    wf = ui.number(t["wfactor"], value=200, min=1, step=50).classes("sl-w-sm")
                    ui.button(t["hovmoller"], icon="view_timeline", on_click=lambda: show_hov()).props("flat dense")
                with ui.row().classes("row wrap q-col-gutter-sm items-center") as line_box:   # herramientas del perfil 2D
                    llog = ui.switch(t["sec_log"], value=False).mark("sec_log")
                    lref = ui.number(t["sec_ref"], value=0.0, format="%g").props("dense").classes("sl-w-sm").mark("sec_ref")
                    lfit = ui.switch(t["sec_fit"], value=False).mark("sec_fit")
                    lf1 = ui.number(t["from_km"], value=0.0, format="%g").props("dense").classes("sl-w-sm").mark("sec_fit_from")
                    lf2 = ui.number(t["to_km"], value=100.0, format="%g").props("dense").classes("sl-w-sm").mark("sec_fit_to")
                    lint = ui.switch(t["sec_integral"], value=False).mark("sec_integral")
                    li1 = ui.number(t["from_km"], value=0.0, format="%g").props("dense").classes("sl-w-sm").mark("sec_int_from")
                    li2 = ui.number(t["to_km"], value=100.0, format="%g").props("dense").classes("sl-w-sm").mark("sec_int_to")
                line_info = ui.label().classes("text-body2 text-weight-medium").style("white-space:pre-line").mark("sec_readout")
                secfig = ui.plotly(go.Figure()).classes("w-full").style("height:430px").mark("sec_plot")
                hovfig = ui.plotly(go.Figure()).classes("w-full").style("height:380px"); hovfig.set_visibility(False)
    with panels, ui.tab_panel(tan):
        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
            astep = ui.number(t["anim_step"], value=max(1, ds.time.size // 60), min=1, step=1).classes("sl-w-sm")
            ui.button(t["anim_map"], icon="public", on_click=lambda: make_anim("map")).props("color=secondary")
            ui.button(t["anim_section"], icon="straighten", on_click=lambda: make_anim("section")).props("color=secondary outline")
            ui.button(t["export_mp4"], icon="movie", on_click=lambda: export_mp4()).props("outline")
            aprog = ui.linear_progress(value=0, show_value=False).classes("w-64"); aprog.set_visibility(False)
        anim = ui.column().classes("w-full")

    # --- lógica
    def refresh_map():
        plot.update_figure(themed(map_figure(st, t, lang), st.dark))
    def refresh_map_time():
        """Cambio de instante: solo se reenvían los datos del mapa de calor (traza 0) y el título, con Plotly.restyle /
        relayout en el navegador (~tamaño de z en vez de la figura entera). Si no es posible, la figura completa."""
        if st.arrows or st.background != "field" or st.pending is not None or (st.contour and st.contour != "depth"):
            refresh_map(); return                                       # isolíneas de una variable: niveles nuevos en cada instante
        try:
            map_figure(st, t, lang); f = st._frame
            z = np.asarray(f["z"], float)
            zl = np.where(np.isfinite(z), z, None).tolist()
            plot.figure["data"][0]["z"] = zl                                # el servidor conserva la figura coherente
            plot.figure["layout"]["title"] = f["title"]
            upd = {"z": [zl]}
            for k in ("zmin", "zmax"):
                if f.get(k) is not None:
                    upd[k] = [float(f[k])]
            upd["colorbar.tickvals"] = [f.get("ticks")]
            plot.run_plot_method("restyle", upd, [0])
            plot.run_plot_method("relayout", {"title.text": f["title"]})
        except Exception:   # noqa: BLE001  (sin navegador o cliente antiguo: ruta de respaldo)
            refresh_map()
    def refresh_time_label():
        tlabel.set_value(np.datetime_as_string(ds.time.values[st.it], "m").replace("T", " "))
    def goto_time():
        """Salta a la salida más próxima a la fecha escrita (AAAA-MM-DD HH:MM)."""
        k = nearest_output(ds.time.values, tlabel.value)
        if k is None:
            ui.notify(t["goto_time_bad"], type="warning"); refresh_time_label(); return
        tsl.set_value(k)
        if k == st.it:
            refresh_time_label()
    def refresh_points_list():
        plist.clear()
        with plist:
            ui.label(t["points"]).classes("text-subtitle2")
            for i, p in enumerate(st.points):
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    ui.icon("sensors" if p.get("station") else "place").style(f"color:{p['color']}")
                    ui.input(value=p["name"]).props("dense outlined").classes("text-weight-bold").style("width:7rem").tooltip(t["point_name_tip"]) \
                        .on_value_change(lambda e, p=p: (p.update(name=e.value), refresh_map(), refresh_series()))
                    xy = f"{p['x']:.4f}, {p['y']:.4f}" if st.geo else f"{p['x'] / 1e3:.1f}, {p['y'] / 1e3:.1f} km"
                    ui.label(xy).classes("text-caption text-grey-7 text-no-wrap")
                    ui.button(icon="close", on_click=lambda i=i: remove_point(i)).props("flat dense round size=sm")
            with ui.row().classes("items-center q-gutter-xs"):
                nx = ui.number("lon" if st.geo else "x", value=round(float(ds.x.mean()), 4)).props("dense").classes("sl-w-sm")
                ny = ui.number("lat" if st.geo else "y", value=round(float(ds.y.mean()), 4)).props("dense").classes("sl-w-sm")
                ui.button(icon="add", on_click=lambda: (st.add_point(float(nx.value), float(ny.value)), refresh_points_list(), refresh_map(), refresh_series())).props("flat dense round")
            have = {(p["name"], p["node"]) for p in st.points}
            missing = [p for p in initial_points if (p["name"], p["node"]) not in have]
            if missing:
                ui.button(t["restore_stations"].format(n=len(missing)), icon="restore", on_click=lambda: restore_points()) \
                    .props("flat dense no-caps color=primary").mark("restore_stations")
    def restore_points():
        have = {(p["name"], p["node"]) for p in st.points}
        for p in initial_points:
            if (p["name"], p["node"]) not in have:
                st.add_point(float(p["x"]), float(p["y"]), p["name"], station=bool(p.get("station")))
        recolor(); refresh_points_list(); refresh_map(); refresh_series()
    def recolor():
        """Un color distinto por punto en el orden de la lista (al quitar puntos no se repiten colores)."""
        for k, p in enumerate(st.points):
            p["color"] = COLORS[k % len(COLORS)]
    def remove_point(i):
        st.points.pop(i); recolor(); refresh_points_list(); refresh_map(); refresh_series()
    def is_vector(v):
        return (v + "X") in ds
    def update_series_fig():
        sfig.update_figure(series_figure_multi(st, st.var, lang, wd))
        mm = getattr(st, "series_means", [])
        if not mm:
            smeans.set_content(""); smeans.set_visibility(False); return
        head = t["series_means"].format(w=st.window_text(lang))
        cells = "".join(f'<span style="display:inline-block;margin:2px 14px 2px 0;white-space:nowrap"><span style="color:{c}">●</span> '
                        f'{html_escape(str(n))}: <b>{mu:.4g}</b></span>' for n, mu, c in mm)
        smeans.set_content(f'<div><span class="text-grey-7">{html_escape(head)}</span><br>{cells}</div>'); smeans.set_visibility(True)
    def refresh_series():
        comp_sel.set_visibility(is_vector(st.var))
        update_series_fig()
        refresh_profile(); refresh_ekman()
    prof_range = {}
    def refresh_profile():
        """Perfil vertical del último punto en el instante del mapa (o medio en la ventana), con el eje x fijo en toda la
        simulación. Vectores: u, v y |v|; escalares (también la viscosidad): con su unidad en el eje."""
        if not (st.points and st.is3d(st.var)) or st.iso_ok():
            pfig.set_visibility(False); return
        p = st.points[-1]; node = p["node"]; its = st.its()
        z = (st.F.mean_z(its) if len(its) > 1 else st.F.zcor(its[0]))[node]
        if st.is_vector(st.var):
            u, v = st.F.columns(st.var, its, "uv"); prof = {"u": u[node], "v": v[node]}
        else:
            prof = {"y": st.F.columns(st.var, its)[node]}
        key = (st.var, node)
        if key not in prof_range:
            if st.var + "X" in ds:
                arrs = [ds[st.var + "X"].isel(node=node).values, ds[st.var + "Y"].isel(node=node).values]
            elif st.var in ds:
                arrs = [ds[st.var].isel(node=node).values]
            else:
                arrs = list(prof.values())
            a = np.concatenate([np.ravel(x) for x in arrs]).astype(float); a = a[np.isfinite(a) & (a > -9000)]
            lo, hi = (float(a.min()), float(a.max())) if a.size else (0.0, 1.0)
            if st.is_vector(st.var):
                lo = min(lo, -hi * 0.05); hi = max(hi, float(np.hypot(*[np.nanmax(np.abs(x)) for x in arrs[:2]])) if len(arrs) > 1 else hi)
            pad = 0.05 * (hi - lo or 1.0); prof_range[key] = (lo - pad, hi + pad)
        when = st.window_text(lang) if st.window is not None else np.datetime_as_string(ds.time.values[st.it], "m").replace("T", " ")
        f = profile_figure2(z, prof, label(st.var, lang, "u") if st.is_vector(st.var) else label(st.var, lang), lang)
        f.update_layout(xaxis_range=list(prof_range[key]) if st.window is None else None, title=f"{p['name']} · {when}")
        if st.is_vector(st.var):
            f.add_vline(x=0, line=dict(color="#999", width=1))
        pfig.update_figure(themed(f, st.dark)); pfig.set_visibility(True)
    def refresh_ekman():
        """Perfil (u, v, |v| y viscosidad) y hodógrafa del último punto, con las lecturas de la espiral."""
        if not (has_3dvel and st.points and ek_exp.value):
            return
        try:
            p = st.points[-1]; node = p["node"]; its = st.its()
            # vacío: «desde el fondo» / «hasta la superficie»; hasta 0 (o más) también es hasta la superficie libre
            i1 = None if ek_i1.value is None else float(ek_i1.value); i2 = None if ek_i2.value is None else float(ek_i2.value)
            d = ekman_profile(st, node, its, ek_ref.value, int(ek_k.value or 0), (float(ek_f1.value if ek_f1.value is not None else -28), float(ek_f2.value or 0)),
                              None if (i1 is None and i2 is None) else (i1, i2), lang=lang)
            theory = (float(ek_v0.value or 0), float(ek_de.value or 1)) if ek_th.value else None
            pf, hf = ekman_figures(d, lang, theory)
            when = st.window_text(lang) if st.window is not None else np.datetime_as_string(ds.time.values[st.it], "m").replace("T", " ")
            pf.update_layout(title=dict(text=f"{p['name']} · {when}", font=dict(size=12)))
            if not ek_figs:
                with ek_figbox:
                    ek_figs["p"] = ui.plotly(themed(pf, st.dark)).style("flex:1 1 520px;min-width:320px;height:420px").mark("ek_profile")
                    ek_figs["h"] = ui.plotly(themed(hf, st.dark)).style("flex:1 1 420px;min-width:320px;height:420px").mark("ek_hodograph")
            else:
                ek_figs["p"].update_figure(themed(pf, st.dark)); ek_figs["h"].update_figure(themed(hf, st.dark))
            ek_info.set_text(ekman_text(d, lang))
        except Exception as ex:   # noqa: BLE001
            ek_info.set_text(f"{t['ek_title']}: {ex}")
    def refresh_sections_list():
        slist.clear()
        with slist:
            ui.label(t["sections"]).classes("text-subtitle2")
            for i, s in enumerate(st.sections):
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    ui.icon("straighten").style(f"color:{s['color']}")
                    ui.input(value=s["name"]).props("dense borderless").style("width:4.5rem").on_value_change(lambda e, s=s: (s.update(name=e.value), refresh_map()))
                    ui.label(f"({s['p0'][0]:.2f}, {s['p0'][1]:.2f}) → ({s['p1'][0]:.2f}, {s['p1'][1]:.2f})").classes("text-caption text-no-wrap")
                    active = state_sec["active"] == i
                    ui.button(icon="show_chart", on_click=lambda i=i: (show_section(i), refresh_sections_list())) \
                        .props(f"dense round size=sm {'unelevated color=primary' if active else 'flat'}").tooltip(t["sec_plot"]).mark(f"sec_plot_{i}")
                    ui.button(icon="visibility" if s.get("visible", True) else "visibility_off", on_click=lambda i=i: toggle_section(i)) \
                        .props("flat dense round size=sm").tooltip(t["sec_toggle"]).mark(f"sec_eye_{i}")
                    ui.button(icon="close", on_click=lambda i=i: remove_section(i)).props("flat dense round size=sm")
            if not st.sections:
                ui.label(t["no_sections"]).classes("text-caption text-grey-7")
    state_sec = {"active": None}
    def toggle_section(i):
        """Muestra u oculta la sección i en el mapa (sigue en la lista y se puede representar)."""
        st.sections[i]["visible"] = not st.sections[i].get("visible", True)
        refresh_sections_list(); refresh_map()
    def remove_section(i):
        st.sections.pop(i); state_sec["active"] = None if not st.sections else min(i, len(st.sections) - 1)
        refresh_map(); show_section(state_sec["active"]); refresh_sections_list()
    def show_section(i, switch: bool = True):
        """Dibuja la sección i; `switch` lleva a la pestaña Secciones (solo cuando lo pide el usuario, no al reproducir)."""
        if i is None or i >= len(st.sections):
            secfig.update_figure(go.Figure()); return
        state_sec["active"] = i
        s = st.sections[i]
        sv = svar.value; comp = scomp.value if st.is_vector(sv) else "mag"; st.sec_comp = comp
        scomp.set_visibility(st.is_vector(sv))
        try:
            F, z, vel = section_values(st, s, sv, st.its(), comp)
            clabel = label(sv, lang, comp)
            slev.set_visibility(F.ndim == 2)
            iso_curve = False
            if F.ndim == 2 and slev.value:                         # curva en el nivel del mapa (capa, profundidad fija o isosuperficie)
                if st.iso_ok():                                    # h(x): profundidad de la isosuperficie del mapa (media de la ventana)
                    from ..analysis.isosurface import section_iso_depth
                    with np.errstate(all="ignore"):
                        F = np.nanmean([section_iso_depth(s["sec"], st.var, st.iso_value, i) for i in st.its()], axis=0)
                    clabel = st.iso_label(lang); iso_curve = True
                elif st.depth_mode == "depth":
                    from ..analysis.sections import interp_at_depth
                    F = interp_at_depth(F, z, st.depth_m); clabel += f" · {st.depth_m:g} m"
                else:
                    F = F[:, st.layer]; clabel += f" · {st.layer_text(st.layer, t)}"
            when = st.window_text(lang) if st.window is not None else np.datetime_as_string(ds.time.values[st.it], "m").replace("T", " ")
            title = f"{s['name']} · {clabel} · {when}"
            line_box.set_visibility(F.ndim == 1)
            if F.ndim == 1:                                       # variable 2D o derivada: perfil con ajuste e integral
                units = "m" if iso_curve else ((VECTOR_UNITS.get(sv) if st.is_vector(sv) else None) or st.F.units(sv))
                fig, info = section_line_figure(s["sec"], F, clabel, lang, st.dark, log=bool(llog.value), ref=float(lref.value or 0.0),
                                                fit=(float(lf1.value or 0), float(lf2.value or 0)) if lfit.value else None,
                                                integ=(float(li1.value or 0), float(li2.value or 0)) if lint.value else None,
                                                units=units, title=title)
                line_info.set_text(line_readout(info, units, lang)); secfig.update_figure(fig)
            else:
                line_info.set_text("")
                zr = None
                if fixed.value:
                    zr = (float(np.nanmin(F)), float(np.nanmax(F))) if np.isfinite(F).any() else None
                    if zr and (comp != "mag" or sv in ("verticalVelocity", "vorticity", "vorticity_f")):
                        m = max(abs(zr[0]), abs(zr[1])); zr = (-m, m)
                    # la escala del mapa solo vale si es la de la misma variable (en modo isosuperficie st.zr es de profundidad)
                    zr = st.zr if (sv == st.var and st.zr and st.depth_mode == "layer" and comp == st.mcomp and st.window is None) else zr
                iso = (st.var, st.iso_value) if st.iso_ok() else None
                cs = "RdBu_r" if (comp != "mag" or sv in ("vorticity", "vorticity_f")) else None
                secfig.update_figure(section_figure2(s["sec"], sv, st.it, arrows=arr.value, contours=scont.value, wfactor=float(wf.value or 200), zrange=zr,
                                                     lang=lang, dark=st.dark, iso=iso, F=F, z=z, vel=vel, clabel=clabel, cs=cs, title=title))
        except Exception as ex:   # noqa: BLE001
            ui.notify(f"{t['sections']}: {ex}", type="warning")
        if switch:
            panels.set_value(tsec)
    def show_hov():
        i = state_sec["active"]
        if i is None:
            return
        if st.iso_ok():                                   # h(x, t): profundidad de la isosuperficie a lo largo del corte
            hovfig.update_figure(iso_hovmoller_figure(st.sections[i]["sec"], st.var, st.iso_value, st.iso_label(lang), lang, dark=st.dark))
        else:
            sv = svar.value; comp = scomp.value if st.is_vector(sv) else "mag"
            H = section_hovmoller(st, st.sections[i], sv, comp)
            hovfig.update_figure(hovmoller_figure(st.sections[i]["sec"], sv, st.layer, lang, dark=st.dark, H=H, clabel=label(sv, lang, comp),
                                                  signed=comp != "mag" or sv in ("elevation", "vorticity", "vorticity_f", "verticalVelocity", "streamfunction")))
        hovfig.set_visibility(True)
    def move_cursor():
        """Mueve los marcadores y la línea del instante en las series (restyle/relayout, sin redibujar)."""
        n = len(getattr(st, "series_lines", []))
        if not n:
            return
        xs, ys, tc = series_cursor(st)
        off = n + int(getattr(st, "_mean_traces", 0))                 # trazas: series, medias de la ventana, marcadores
        try:
            data = sfig.figure["data"]
            for k in range(n):
                data[off + k]["x"] = [xs[k]]; data[off + k]["y"] = [ys[k]]
            if sfig.figure["layout"].get("shapes"):
                sfig.figure["layout"]["shapes"][0].update(x0=tc, x1=tc)
            sfig.run_plot_method("restyle", {"x": [[x_] for x_ in xs], "y": [[y_] for y_ in ys]}, list(range(off, off + n)))
            sfig.run_plot_method("relayout", {"shapes[0].x0": tc, "shapes[0].x1": tc})
        except Exception:   # noqa: BLE001  (figura cambiada mientras tanto: se redibuja)
            update_series_fig()
    pend = {"it": None}
    def on_time(e):
        """Al arrastrar la barra llegan decenas de valores: se guarda el último y un temporizador dibuja solo ese
        (si se dibujaran todos, los mensajes saturan la conexión y el navegador recarga la página)."""
        pend["it"] = int(e.value)
    def render_time():
        if pend["it"] is None:
            return
        st.it = pend["it"]; pend["it"] = None
        refresh_time_label(); refresh_map_time(); move_cursor()
        if not in_sections():
            refresh_profile()                                      # el perfil vertical sigue al tiempo
            if st.window is None:
                refresh_ekman()
        if state_sec["active"] is not None and in_sections():     # la sección sigue al tiempo solo si se está viendo
            show_section(state_sec["active"], switch=False)
    def refresh_range():
        try:
            st.zr = st.value_range(st.var)
        except Exception:   # noqa: BLE001  (campo vacío en esa capa o ventana)
            st.zr = None
    def on_var(e):
        st.var = e.value
        if not st.is_vector(st.var):
            st.mcomp = "mag"
        mcomp.set_visibility(st.is_vector(st.var))
        refresh_range()
        refresh_map(); refresh_series(); follow_map_var()
        if state_sec["active"] is not None and st.depth_mode == "iso":
            show_section(state_sec["active"], switch=False)
    def on_layer(e):
        st.layer = int(e.value); refresh_range()
        lsl.props(f'label-value="{layer_text(st.layer)}"'); refresh_map(); refresh_series()
    def on_dmode(e):
        st.depth_mode = e.value; lsl_box.set_visibility(e.value == "layer"); ldep.set_visibility(e.value == "depth"); ival.set_visibility(e.value == "iso")
        if e.value == "iso" and not st.iso_ok():
            ui.notify(t["iso_needs_3d"], type="warning")
        refresh_range(); refresh_map(); refresh_series()
        if state_sec["active"] is not None:
            show_section(state_sec["active"], switch=False)
    def on_iso(e):
        st.iso_value = float(e.value if e.value is not None else 0.0); refresh_range(); refresh_map(); refresh_series()
        if state_sec["active"] is not None:
            show_section(state_sec["active"], switch=False)
    def on_click(e):
        pts = e.args.get("points", [])
        if not pts:
            return
        x, y = float(pts[0]["x"]), float(pts[0]["y"])
        m = armed["mode"] or ("section" if in_sections() else "point"); armed["mode"] = None
        st.click_mode = "section" if in_sections() else "point"
        if m == "point":
            st.add_point(x, y); refresh_points_list(); refresh_map(); refresh_series(); panels.set_value(tp)
        elif m == "section":
            if st.pending is None:
                st.pending = (x, y); refresh_map(); ui.notify(t["section_second_click"], timeout=2000)
            else:
                st.add_section(st.pending, (x, y)); st.pending = None; refresh_map(); show_section(len(st.sections) - 1); refresh_sections_list()
        else:
            p0, p1 = preset_section(ds, (x, y), m)
            st.add_section(p0, p1, f"{'T' if m == 'transversal' else 'L'}{len(st.sections) + 1}"); refresh_map(); show_section(len(st.sections) - 1); refresh_sections_list()
    def on_relayout(e):
        a = e.args or {}
        if "shapes" in a:                                            # línea nueva dibujada (drawline) o lista completa
            shapes = [sh for sh in a["shapes"] if sh.get("type") == "line"]
            if len(shapes) > len(getattr(st, "shape_index", st.sections)):
                sh = shapes[-1]; st.add_section((sh["x0"], sh["y0"]), (sh["x1"], sh["y1"])); refresh_map(); show_section(len(st.sections) - 1); refresh_sections_list()
            return
        changed = set()
        for k, v in a.items():
            mm = re.match(r"shapes\[(\d+)\]\.(x0|x1|y0|y1)", k)
            if mm:
                k_, key = int(mm.group(1)), mm.group(2)
                idx = getattr(st, "shape_index", list(range(len(st.sections))))
                i = idx[k_] if k_ < len(idx) else len(st.sections)
                if i < len(st.sections):
                    s = st.sections[i]; p0, p1 = list(s["p0"]), list(s["p1"])
                    {"x0": lambda: p0.__setitem__(0, float(v)), "y0": lambda: p0.__setitem__(1, float(v)), "x1": lambda: p1.__setitem__(0, float(v)), "y1": lambda: p1.__setitem__(1, float(v))}[key]()
                    s["p0"], s["p1"] = tuple(p0), tuple(p1); changed.add(i)
        for i in changed:                                             # extremos arrastrados: recalcular el corte
            s = st.sections[i]; s["sec"] = Section(ds, s["p0"], s["p1"], vg=st.vg, tri=st.tri)
            show_section(i); refresh_sections_list()
        if changed:
            refresh_map()                                             # el halo y la etiqueta siguen a la sección
    def export_series():
        import pandas as pd
        cols = {}
        if st.iso_ok():
            from ..analysis.isosurface import isosurface_series
            cols = {p["name"]: isosurface_series(ds, st.var, st.iso_value, p["node"], st.vg) for p in st.points}
            df = pd.DataFrame(cols, index=pd.DatetimeIndex(ds.time.values)); f = wd / f"iso_{st.var}_{st.iso_value:g}.csv"; df.to_csv(f); ui.download(f); return
        depth = st.depth_m if (st.is3d(st.var) and st.depth_mode == "depth") else None
        for p in st.points:
            s = st.F.series(st.var, p["node"], layer=st.layer if st.is3d(st.var) else None, depth=depth)   # también derivadas
            if "u" in s:
                cols[p["name"] + "_u"] = s["u"]; cols[p["name"] + "_v"] = s["v"]
            else:
                cols[p["name"]] = s["y"]
        df = pd.DataFrame(cols, index=pd.DatetimeIndex(ds.time.values)); f = wd / f"series_{st.var}.csv"; df.to_csv(f); ui.download(f)
    async def make_anim(kind):
        anim.clear(); aprog.set_visibility(True); aprog.set_value(0)
        step = int(astep.value or 1)
        def prog(v):
            aprog.set_value(v)
        try:
            if kind == "map":
                fig = await run.io_bound(lambda: animation_figure2(st, t, lang, step, prog))
            else:
                if state_sec["active"] is None:
                    ui.notify(t["no_sections"], type="warning"); aprog.set_visibility(False); return
                s = st.sections[state_sec["active"]]
                fig = await run.io_bound(lambda: section_animation(st, s, svar.value, lang, step, prog))
        except Exception as ex:   # noqa: BLE001
            ui.notify(str(ex), type="negative"); aprog.set_visibility(False); return
        aprog.set_visibility(False)
        with anim:
            ui.plotly(themed(fig, st.dark)).classes("w-full").style("height:600px")
    async def export_mp4():
        from ..analysis.video import field_video, section_video
        aprog.set_visibility(True); aprog.set_value(0)
        def prog(v):
            aprog.set_value(v)
        try:
            if state_sec["active"] is not None and str(panels.value) in ("tab_sections", str(tsec)):
                s = st.sections[state_sec["active"]]
                out = await run.io_bound(lambda: section_video(ds, s["sec"], svar.value, wd / f"seccion_{s['name']}_{svar.value}.mp4", arrows=arr.value, wfactor=float(wf.value or 200), fps=int(speed.value), progress=prog, lang=lang))
            else:
                out = await run.io_bound(lambda: field_video(ds, st.var, wd / f"mapa_{st.var}.mp4", layer=st.layer, depth_m=st.depth_m if st.depth_mode == "depth" else None, vg=st.vg,
                                                             arrows=arr.value, fps=int(speed.value), progress=prog, lang=lang, land=st.land))
        except Exception as ex:   # noqa: BLE001
            ui.notify(str(ex), type="negative"); aprog.set_visibility(False); return
        aprog.set_visibility(False); ui.notify(str(out), type="positive"); ui.download(out)
    # reproducción
    def tick():
        nxt = st.it + 1
        if nxt >= ds.time.size:
            nxt = 0
        tsl.set_value(nxt)
    timer = ui.timer(1 / 5, tick, active=False)
    def toggle_play():
        timer.interval = 1 / float(speed.value); timer.active = not timer.active
        play.props(f"icon={'pause' if timer.active else 'play_arrow'}")
    play.on_click(toggle_play)
    speed.on_value_change(lambda e: setattr(timer, "interval", 1 / float(e.value)))
    var.on_value_change(on_var); lsl.on_value_change(on_layer); dmode.on_value_change(on_dmode); ldep.on_value_change(lambda e: (setattr(st, "depth_m", float(e.value or 0)), refresh_map())); ival.on_value_change(on_iso)
    arr.on_value_change(lambda e: (setattr(st, "arrows", bool(e.value)), refresh_map(), show_section(state_sec["active"], switch=False) if state_sec["active"] is not None else None))
    fixed.on_value_change(lambda e: (setattr(st, "fixed", bool(e.value)), refresh_map()))
    mesh_sw.on_value_change(lambda e: (setattr(st, "show_mesh", bool(e.value)), refresh_map()))
    bg.on_value_change(lambda e: (setattr(st, "background", e.value), refresh_map()))
    cmap.on_value_change(lambda e: (setattr(st, "cmap", e.value), refresh_map()))
    iso_sel.on_value_change(lambda e: (setattr(st, "contour", e.value or ""), refresh_map()))
    iso_step.on_value_change(lambda e: (setattr(st, "contour_step", float(e.value or 0)), refresh_map()))
    def set_manual():
        lo, hi = zlo.value, zhi.value
        st.zmanual = (float(lo), float(hi)) if (lo is not None and hi is not None and float(hi) > float(lo)) else None
        refresh_map()
    zlo.on_value_change(lambda e: set_manual()); zhi.on_value_change(lambda e: set_manual())
    def on_mcomp(e):
        st.mcomp = e.value or "mag"; refresh_range(); refresh_map()
    def typed(w, e):
        """Copia en el campo el texto que hay en el navegador al pulsar Intro o salir: si el servidor reenvía el campo
        mientras se escribe, la última tecla puede no llegarle, y la media o el salto usarían la fecha anterior."""
        v = e.args[0] if isinstance(e.args, list) and e.args else e.args
        if isinstance(v, str) and v != w.value:
            w.set_value(v)
    def set_window(typed_in: bool = False):
        """Activa o actualiza el promedio entre las dos fechas (índices de las salidas incluidas). typed_in (Intro o
        salir de t1/t2): no recalcula si la ventana no cambia, porque Intro y luego salir del campo lo harían dos veces."""
        from ..analysis.derived import time_window
        if not avg_sw.value:
            st.window = None; avg_n.set_text("")
        else:
            try:
                w = time_window(ds.time.values, avg_a.value, avg_b.value)
            except (ValueError, TypeError):
                ui.notify(t["goto_time_bad"], type="warning"); return
            if typed_in and st.window is not None and np.array_equal(w, st.window):
                return
            if w.size == 0:
                ui.notify(t["avg_empty"], type="warning"); st.window = None; avg_n.set_text(t["avg_empty"])
            else:
                st.window = w; avg_n.set_text(st.window_text(lang))
        avg_box.set_visibility(bool(avg_sw.value))
        refresh_range(); refresh_map(); refresh_series()
        if state_sec["active"] is not None:
            show_section(state_sec["active"], switch=False)
        if callable(st.on_window):
            st.on_window()
    def in_sections() -> bool:
        return str(panels.value) in ("tab_sections", str(tsec))
    def on_subtab(e):
        st.click_mode = "section" if in_sections() else "point"; st.pending = None; armed["mode"] = None; refresh_map()
    panels.on_value_change(on_subtab)
    mcomp.on_value_change(on_mcomp); mcomp.set_visibility(st.is_vector(st.var))
    for w_ in (ek_ref, ek_k, ek_f1, ek_f2, ek_i1, ek_i2, ek_th, ek_v0, ek_de):
        w_.on_value_change(lambda e: refresh_ekman())
    ek_exp.on_value_change(lambda e: refresh_ekman())
    ek_k.bind_visibility_from(ek_ref, "value", backward=lambda v: v == "level")
    avg_sw.on_value_change(lambda e: set_window())
    for w_ in (avg_a, avg_b):
        for ev in ("keydown.enter", "blur"):
            w_.on(ev, lambda e, w=w_: (typed(w, e), set_window(typed_in=True)), js_handler="(e) => emit(e.target.value)")
    tsl.on_value_change(on_time)
    for ev in ("keydown.enter", "blur"):
        tlabel.on(ev, lambda e: (typed(tlabel, e), goto_time()), js_handler="(e) => emit(e.target.value)")
    ui.timer(0.08, render_time)
    comp_sel.on_value_change(lambda e: (setattr(st, "component", e.value), update_series_fig()))
    sec_follow = {"on": True, "prog": False}
    def on_svar(e):
        if not sec_follow["prog"]:                                  # elegida a mano: deja de seguir al mapa (vuelve si coincide)
            sec_follow["on"] = e.value == st.var
        if state_sec["active"] is not None:
            show_section(state_sec["active"], switch=not sec_follow["prog"])
    def follow_map_var():
        if sec_follow["on"] and st.var in sec_vars and svar.value != st.var:
            sec_follow["prog"] = True
            try:
                svar.set_value(st.var)
            finally:
                sec_follow["prog"] = False
    svar.on_value_change(on_svar); scont.on_value_change(lambda e: show_section(state_sec["active"])); wf.on_value_change(lambda e: show_section(state_sec["active"]))
    for w_ in (scomp, slev, llog, lref, lfit, lf1, lf2, lint, li1, li2):
        w_.on_value_change(lambda e: show_section(state_sec["active"], switch=False) if state_sec["active"] is not None else None)
    scomp.set_visibility(st.is_vector(svar.value)); line_box.set_visibility(False)
    plot.on("plotly_click", on_click, js_handler=CLICK_JS); plot.on("plotly_relayout", on_relayout)
    lsl_box.set_visibility(st.nvrt > 1); ldep.set_visibility(False); ival.set_visibility(False); dmode.set_visibility(st.nvrt > 1)
    refresh_time_label(); refresh_points_list(); refresh_sections_list(); refresh_series()
    return st


# ----------------------------------------------------------------------------- pestaña Espectro
_STA_IDX = {"elev": 1, "airP": 2, "windx": 3, "windy": 4, "T": 5, "S": 6, "u": 7, "v": 8, "w": 9}


def station_vars(wd: Path) -> dict:
    """Variables de estación con fichero staout_k no vacío en la simulación (outputs/ o la raíz de una archivada)."""
    names = {"elev": "η", "T": "T", "S": "S", "u": "u", "v": "v", "w": "w"}
    out = {}
    for k, lab in names.items():
        f = wd / "outputs" / f"staout_{_STA_IDX[k]}"
        if not f.exists():
            f = wd / f"staout_{_STA_IDX[k]}"
        if f.exists() and f.stat().st_size > 0:
            out[k] = lab
    if "u" in out and "v" in out:
        out["uv"] = "u+iv"
    return out


def case_tides(c) -> list[str]:
    """Constituyentes de marea que fuerzan el caso (bloques `tides:` en cualquier parte del YAML); [] si no hay marea."""
    out: list[str] = []; pot: list = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "tides" and v:
                    cons = v.get("constituents", ["M2"]) if isinstance(v, dict) else (v if isinstance(v, list) else ["M2"])
                    out.extend(str(x).upper() for x in cons if str(x).upper() not in out)
                elif k == "tidal_potential" and v:
                    pot.append(True)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(c or {})
    return out or (["M2", "S2", "N2", "K1", "O1"] if pot else [])


def spectrum_tab(ds, c: dict, wd: Path, t: dict, lang: str, st: ExplorerState):
    from ..analysis import read_stations
    sta_vars = station_vars(wd) if (wd / "station.in").exists() else {}
    has_sta = "elev" in sta_vars
    sta_names: list[str] = []
    if has_sta:
        try:
            sta_names = list(read_stations(wd, "elev").columns)
        except Exception:   # noqa: BLE001  (staout ilegible)
            has_sta = False
    tides = case_tides(c)
    ui.label(t["spectrum_hint"]).classes("text-caption text-grey-7")
    with ui.row().classes("row wrap q-col-gutter-sm items-center w-full"):
        src = ui.select({"points": t["src_points"], "stations": t["src_stations"]}, value="points", label=t["ic_source"]).classes("sl-w-lg").mark("spectrum_src"); src.set_visibility(has_sta)
        pvar = ui.select(st.vars, value=st.var, label=t["variable"]).classes("sl-w-md")
        svar = ui.select(sta_vars or {"elev": "η"}, value="elev", label=t["variable"]).classes("sl-w-sm").mark("spectrum_svar"); svar.set_visibility(False)
        psel = ui.select({}, label=t["points"], multiple=True).classes("sl-w-lg")
        nper = ui.number(t["nperseg_frac"], value=0.5, min=0.05, max=1, step=0.05).classes("sl-w-sm")
        w0 = ui.number("ω₀", value=6, min=3, max=12, step=1).classes("sl-w-sm")
    if (wd / "station.in").exists() and not has_sta:
        ui.label(t["no_staout"]).classes("text-caption text-grey-7")
    warn = ui.label().classes("text-caption text-orange-9")
    with ui.row().classes("w-full q-col-gutter-sm"):
        with ui.column().classes("col-12 col-md-6"):
            sfig = ui.plotly(go.Figure()).classes("w-full").style("height:320px")
        with ui.column().classes("col-12 col-md-6"):
            pfig = ui.plotly(go.Figure()).classes("w-full").style("height:320px")
    rfig = ui.plotly(go.Figure()).classes("w-full").style("height:300px"); rfig.set_visibility(False)
    wcol = ui.column().classes("w-full")                         # una wavelet por punto o estación seleccionada
    ui.button(t["download_psd"], icon="download", on_click=lambda: export_psd()).props("flat dense")
    cache = {}

    def fill_points():
        if src.value == "stations" and has_sta:
            psel.set_options({n: n for n in sta_names}, value=sta_names[:1])
        else:
            psel.set_options({p["name"]: p["name"] for p in st.points}, value=[st.points[-1]["name"]] if st.points else [])
        pvar.set_visibility(src.value == "points"); svar.set_visibility(src.value == "stations")
    def get_series(name):
        """(t, y) o (t, u, v) de un punto o estación."""
        if src.value == "stations":
            try:
                if svar.value == "uv":
                    du, dv = read_stations(wd, "u"), read_stations(wd, "v"); return dict(t=du.index.values, u=du[name].values, v=dv[name].values)
                d = read_stations(wd, svar.value); return dict(t=d.index.values, y=d[name].values)
            except (FileNotFoundError, OSError, ValueError, KeyError):
                ui.notify(t["stations_old"], type="warning"); return None
        p = next((p for p in st.points if p["name"] == name), None)
        if p is None:
            return None
        return st.F.series(pvar.value, p["node"], layer=st.layer if st.is3d(pvar.value) else None)   # también derivadas
    def _cart_lat(y_m):
        """Dominio cartesiano: latitud con el periodo inercial del f del modelo (plano f: lat0; plano β: f0 + β y)."""
        from ..analysis.dynamics import case_coriolis, inertial_lat
        f = case_coriolis(c, 0.0, 0.0 if y_m is None else float(y_m), geographic=False)
        return None if f is None else inertial_lat(float(np.ravel(f)[0]))
    def lat_of(name):
        if src.value == "stations":
            for s_ in (c.get("stations") or []):
                if str(s_.get("name")) == name and "lat" in s_:
                    return float(s_["lat"])
            if st.geo:
                return float(ds.y.mean())
            s_ = next((s_ for s_ in (c.get("stations") or []) if str(s_.get("name")) == name), None)
            return _cart_lat(s_.get("y") if s_ else None)
        p = next((p for p in st.points if p["name"] == name), None)
        if not p:
            return None
        return p["y"] if st.geo else _cart_lat(p["y"])
    def refresh():
        names = list(psel.value or [])
        sf, pf, rf = go.Figure(), None, None; wfs = []; msg = []
        cache.clear()
        for k, name in enumerate(names):
            s = get_series(name)
            if s is None:
                continue
            color = COLORS[k % len(COLORS)]
            if "u" in s:
                tu, uu, dt = regularize(s["t"], s["u"]); _, vv, _ = regularize(s["t"], s["v"]); y = np.hypot(uu, vv)
            else:
                tu, y, dt = regularize(s["t"], s["y"]); uu = vv = None
            n = y.size
            tmin, tmax = resolvable_periods(dt, n)
            msg.append(t["resolvable"].format(name=name, n=n, dt=dt / 60, tmin=tmin / 3600, tmax=tmax / 3600))
            t0 = s["t"][0]
            tt = (np.datetime64(t0) + (tu * 1e9).astype("timedelta64[ns]")) if np.issubdtype(np.asarray(s["t"]).dtype, np.datetime64) else tu / 3600
            sf.add_trace(go.Scatter(x=tt, y=y, mode="lines", name=name, line=dict(color=color, width=1.5)))
            refs = reference_periods(lat_of(name), tides=tides)               # mareas: solo si fuerzan el caso
            refs = {k_: v_ for k_, v_ in refs.items() if tmin / 3600 <= v_ <= tmax / 3600 * 1.5}
            if n < 16:
                continue
            r = psd_welch(y, dt, nperseg=max(16, int(float(nper.value or 0.5) * n)))
            cache[name] = r
            pf = pf or psd_figure(r, refs, name, lang, resolvable=(tmin, tmax), dark=st.dark)
            if k > 0:
                pf.add_trace(go.Scatter(x=r["period_h"], y=r["P"], mode="lines", name=name, line=dict(color=color, width=2)))
            if uu is not None:
                rr = rotary_spectrum(uu, vv, dt, nperseg=max(16, int(float(nper.value or 0.5) * n)))
                rf = rf or rotary_figure(rr, refs, lang, dark=st.dark)
            w = wavelet_morlet(y, dt, omega0=float(w0.value or 6))
            wf_ = wavelet_figure(w, t0 if np.issubdtype(np.asarray(s["t"]).dtype, np.datetime64) else None, refs, lang, dark=st.dark, global_name=t["global_spectrum"])
            wf_.update_layout(title=dict(text=f"wavelet · {name}", font=dict(color=color)))
            wfs.append(wf_)
        sf.update_layout(hovermode="x unified", **layout(st.dark))
        sfig.update_figure(sf); pfig.update_figure(pf or go.Figure())
        wcol.clear()
        with wcol:
            for wf_ in wfs:
                ui.plotly(wf_).classes("w-full").style("height:420px")
        rfig.set_visibility(rf is not None)
        if rf is not None:
            rfig.update_figure(rf)
        warn.set_text(" · ".join(msg))
    def export_psd():
        import pandas as pd
        if not cache:
            return
        cols = {}
        for name, r in cache.items():
            cols[f"{name}_period_h"] = r["period_h"]; cols[f"{name}_PSD"] = r["P"]
        n = min(len(v) for v in cols.values())
        f = wd / "espectro.csv"; pd.DataFrame({k: v[:n] for k, v in cols.items()}).to_csv(f, index=False); ui.download(f)
    for w in (pvar, svar, psel, nper, w0):
        w.on_value_change(lambda e: refresh())
    src.on_value_change(lambda e: (fill_points(), refresh()))
    fill_points(); refresh()
    return refresh
