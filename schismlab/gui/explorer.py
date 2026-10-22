"""Explorador de resultados (pestaña Mapas y series): mapa con flechas, reproducción en el tiempo, puntos múltiples
con series y perfiles, secciones arrastrables (y presets transversal/longitudinal) con flechas, Hovmöller,
animaciones y exportación. Pestaña Espectro: Welch, rotatorio y wavelet de los puntos o de las estaciones."""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from nicegui import run, ui
from .figures import (LAYOUT, LABELS, label, layout, themed, NodeSampler, _aspect, dataset_range, _values, map_arrows, arrows_trace, profile_figure,
                      section_figure2, hovmoller_figure, iso_hovmoller_figure, psd_figure, rotary_figure, wavelet_figure, land_polygons, land_traces, boundary_traces)
from ..analysis.sections import Section, preset_section, field_at_depth, is_geographic
from ..analysis.signal import point_series, psd_welch, rotary_spectrum, wavelet_morlet, reference_periods, regularize, resolvable_periods

from ..edition import default_generator
from .brand import SERIES as COLORS   # colores de puntos y secciones: los de la marca
PLOTLY_CONFIG = {"modeBarButtonsToAdd": ["drawline", "eraseshape"], "displaylogo": False, "scrollZoom": True}
# plotly_click lleva la traza entera (z del mapa de calor, >1 MB) y el websocket lo rechaza: solo se envían x, y de los puntos
CLICK_JS = "(e) => emit({points: (e.points || []).map(p => ({x: p.x, y: p.y}))})"


class ExplorerState:
    def __init__(self, ds, vg):
        from ..analysis.isosurface import add_density
        add_density(ds)                                    # σt de T y S (perezoso) si no se guardó waterDensity
        self.ds, self.vg = ds, vg
        self.vars = sorted({v[:-1] if v.endswith(("X", "Y")) else v for v in ds.data_vars if "time" in ds[v].dims and not v.startswith("dryFlag")})
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

    def is3d(self, var: str) -> bool:
        ds = self.ds
        name = var + "X" if var + "X" in ds else var
        return name in ds and "layer" in ds[name].dims

    def iso_ok(self, var: str | None = None) -> bool:
        """True si el modo isosuperficie se aplica: variable 3D escalar."""
        var = self.var if var is None else var
        return self.depth_mode == "iso" and self.is3d(var) and var + "X" not in self.ds

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
        """Campo nodal 2D de la variable en el instante: capa, profundidad fija o profundidad de la isosuperficie."""
        ds = self.ds
        if self.iso_ok(var):
            from ..analysis.isosurface import isosurface_depth
            return isosurface_depth(ds, var, self.iso_value, it, self.vg).values
        if self.is3d(var) and self.depth_mode == "depth":
            if var + "X" in ds:
                return np.hypot(field_at_depth(ds, var + "X", it, self.depth_m, self.vg), field_at_depth(ds, var + "Y", it, self.depth_m, self.vg))
            return field_at_depth(ds, var, it, self.depth_m, self.vg)
        return _values(ds, var, it, self.layer)

    def add_point(self, x: float, y: float, name: str | None = None, station: bool = False) -> dict:
        from ..analysis import nearest_node
        p = dict(name=name or f"P{len(self.points) + 1}", x=float(x), y=float(y), node=nearest_node(self.ds, x, y), color=COLORS[len(self.points) % len(COLORS)], station=station)
        self.points.append(p); return p

    def add_section(self, p0, p1, name: str | None = None) -> dict:
        s = dict(name=name or f"S{len(self.sections) + 1}", p0=(float(p0[0]), float(p0[1])), p1=(float(p1[0]), float(p1[1])), color=COLORS[len(self.sections) % len(COLORS)])
        s["sec"] = Section(self.ds, s["p0"], s["p1"], vg=self.vg, tri=self.tri)
        self.sections.append(s); return s


def default_cmap(var: str) -> str:
    return "RdBu_r" if var == "elevation" else ("RdYlBu_r" if var == "temperature" else ("RdBu_r" if var == "verticalVelocity" else "Viridis"))


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
        title = f"{label_} · {when}"
    else:
        f = st.field(var, it); Z = st.sampler.grid(f); label_ = label(var, lang)
        sym = var == "elevation"
        zmin, zmax = (st.zr if (st.fixed and st.zr) else (None, None))
        if st.zmanual is not None:
            zmin, zmax = st.zmanual
        elif sym and zmin is None and np.isfinite(Z).any():
            m = float(np.nanmax(np.abs(Z))); zmin, zmax = -m, m
        cs = default_cmap(var) if st.cmap == "auto" else st.cmap
        lvl = (f"{st.depth_m:g} m" if st.depth_mode == "depth" else (t["surface"] if st.layer == st.nvrt - 1 else f"{t['layer']} {st.layer + 1}")) if st.is3d(var) else ""
        title = f"{label_} · {when}" + (f" · {lvl}" if lvl else "")
    fig = go.Figure(go.Heatmap(x=st.sampler.xi, y=st.sampler.yi, z=Z, colorscale=cs, zmin=zmin, zmax=zmax, zsmooth="best",
                               colorbar=dict(title=label_, thickness=14, tickformat=".3g"), hovertemplate="%{x:.4f}, %{y:.4f}<br>%{z:.3f}<extra></extra>"))
    if st.show_mesh:
        ex, ey, step = st.mesh_edges()
        fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="rgba(0,0,0,0.35)", width=0.5), hoverinfo="skip", showlegend=False))
        if step > 1:
            fig.add_annotation(x=0.01, y=0.02, xref="paper", yref="paper", showarrow=False, xanchor="left", font=dict(size=10, color="#333"), bgcolor="rgba(255,255,255,0.7)",
                               text=(f"malla: 1 de cada {step} aristas" if lang == "es" else f"mesh: 1 in {step} edges"))
    if st.arrows and ("horizontalVelX" in ds or "depthAverageVelX" in ds):
        try:
            tr, vmax = map_arrows(ds, it, st.layer, depth_m=st.depth_m if st.depth_mode == "depth" else None, vg=st.vg)
            fig.add_trace(tr)
            fig.add_annotation(x=0.99, y=0.02, xref="paper", yref="paper", showarrow=False, xanchor="right", text=f"|u| máx {vmax:.2f} m/s" if lang == "es" else f"|u| max {vmax:.2f} m/s",
                               font=dict(size=10), bgcolor="rgba(255,255,255,0.7)")
        except Exception:   # sin velocidades en esa capa
            pass
    for tr in st.context_traces():
        fig.add_trace(tr)
    for p in st.points:
        fig.add_trace(go.Scatter(x=[p["x"]], y=[p["y"]], mode="markers+text", text=[p["name"]], textposition="top right", marker=dict(color=p["color"], size=11, line=dict(color="#fff", width=1.5)),
                                 hovertemplate=f"{p['name']}<extra></extra>", showlegend=False))
    shapes = [dict(type="line", x0=s["p0"][0], y0=s["p0"][1], x1=s["p1"][0], y1=s["p1"][1], line=dict(color=s["color"], width=3), editable=True) for s in st.sections]
    for s in st.sections:
        fig.add_annotation(x=s["p1"][0], y=s["p1"][1], text=s["name"], showarrow=False, font=dict(color=s["color"], size=12), xanchor="left")
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
        y = np.hypot(ds_[0][name].values, ds_[1][name].values) if len(ds_) == 2 else ds_[0][name].values
        return ds_[0].index.values, y
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
        for p in st.points:
            sta = station_series(wd, var, p["name"]) if p.get("station") else None
            if sta is not None:
                t_, y = sta; used_sta = True
                fig.add_trace(go.Scatter(x=t_, y=y, mode="lines", name=f"{p['name']} (staout)", line=dict(color=p["color"], width=1.5)))
                lines.append((np.asarray(t_), np.asarray(y, float), p["color"]))
                continue
            s = point_series(st.ds, var, p["node"], st.layer)
            y = np.hypot(s["u"], s["v"]) if "u" in s else s["y"]
            fig.add_trace(go.Scatter(x=s["t"], y=y, mode="lines", name=p["name"], line=dict(color=p["color"], width=2)))
            lines.append((np.asarray(s["t"]), np.asarray(y, float), p["color"]))
        fig.update_layout(yaxis_title=label(var, lang), hovermode="x unified", **layout(st.dark))
        if used_sta:
            fig.add_annotation(x=0.01, y=0.98, xref="paper", yref="paper", showarrow=False, xanchor="left", font=dict(size=10, color="#555"),
                               text="estaciones: serie fina de staout (en superficie)" if lang == "es" else "stations: fine staout series (surface)")
    st.series_lines = lines
    xs, ys, tc = series_cursor(st)
    for (_, _, col), x_, y_ in zip(lines, xs, ys):        # marcador del instante actual en cada serie
        fig.add_trace(go.Scatter(x=[x_], y=[y_], mode="markers", showlegend=False, hoverinfo="skip",
                                 marker=dict(color=col, size=11, line=dict(color="white", width=2))))
    if lines:
        fig.add_shape(type="line", xref="x", yref="paper", x0=tc, x1=tc, y0=0, y1=1, line=dict(color="#888", width=1, dash="dot"))
    return fig


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
    zr = st.zr or dataset_range(ds, var, st.layer)
    frames = []
    its = list(range(0, ds.time.size, step))
    for k, it in enumerate(its):
        Z = st.sampler.grid(st.field(var, it))
        data = [go.Heatmap(x=st.sampler.xi, y=st.sampler.yi, z=Z, colorscale="RdBu_r" if var == "elevation" else ("RdYlBu_r" if var == "temperature" else "Viridis"), zmin=zr[0], zmax=zr[1], zsmooth="best")]
        if st.arrows and ("horizontalVelX" in ds or "depthAverageVelX" in ds):
            data.append(map_arrows(ds, it, st.layer, depth_m=st.depth_m if st.depth_mode == "depth" else None, vg=st.vg)[0])
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
    vals = [sec.scalar(var, it) for it in its[:: max(1, len(its) // 6)]]
    zr = (float(np.nanmin([np.nanmin(v) for v in vals])), float(np.nanmax([np.nanmax(v) for v in vals])))
    frames = []
    for k, it in enumerate(its):
        f = section_figure2(sec, var, it, arrows=st.arrows, contours=False, zrange=zr, lang=lang)
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
    st = ExplorerState(ds, vg); st.dark = bool(dark)
    st.load_context(c, wd)
    st.zr = dataset_range(ds, st.var, st.layer)
    if not (c.get("stations") or []):                            # sin estaciones: un punto inicial en el centro
        st.add_point(float(ds.x.mean()), float(ds.y.mean()))
    for s_ in (c.get("stations") or []):                        # estaciones del caso como puntos iniciales
        x_, y_ = (s_.get("lon"), s_.get("lat")) if "lon" in s_ else (s_.get("x"), s_.get("y"))
        if x_ is not None and y_ is not None:
            st.add_point(float(x_), float(y_), str(s_.get("name", f"E{len(st.points)}")), station=True)
    initial_points = [dict(p) for p in st.points]                # para poder recuperar las estaciones borradas
    has_vel = "horizontalVelX" in ds or "depthAverageVelX" in ds
    # --- controles: encima del mapa solo variable, capa y tiempo; el estilo va en un acordeón plegado bajo el mapa
    def layer_text(k: int) -> str:
        return t["surface"] if k >= st.nvrt - 1 else (t["bottom"] if k == 0 else f"{t['layer']} {k + 1}")
    with ui.row().classes("row wrap q-col-gutter-sm items-center w-full"):
        var = ui.select(st.vars, value=st.var, label=t["variable"]).classes("sl-w-md").mark("var_select")
        dmode = ui.select({"layer": t["by_layer"], "depth": t["by_depth"], "iso": t["by_iso"]}, value="layer", label=t["level"]).classes("sl-w-md")
        with ui.column().style("min-width:150px;max-width:190px;flex:1 1 150px;padding-top:10px") as lsl_box:
            lsl = ui.slider(min=0, max=max(0, st.nvrt - 1), value=st.layer).props(f'label-always label-value="{layer_text(st.layer)}"').classes("w-full")
        ldep = ui.number(t["depth_fixed"], value=st.depth_m, min=0, step=5).classes("sl-w-sm")
        ival = ui.number(t["iso_value"], value=st.iso_value, step=0.5).classes("sl-w-sm").mark("iso_value")
        with ui.element("div").classes("q-ml-sm"):                # el relleno de q-col-gutter va al envoltorio, no al botón
            play = ui.button(icon="play_arrow").props("round dense color=accent").mark("play_button")
        with ui.column().style("flex:3 1 220px;min-width:180px;padding-top:2px"):
            tsl = ui.slider(min=0, max=ds.time.size - 1, value=st.it).classes("w-full").mark("time_slider")
        tlabel = ui.label().classes("text-caption text-no-wrap")
    plot = ui.plotly(themed(map_figure(st, t, lang), st.dark)).classes("w-full").style("height:560px").mark("map_plot")
    st.plot = plot
    with ui.expansion(t["map_style"], icon="palette", value=False).classes("sl-exp w-full"):
        with ui.row().classes("row wrap q-col-gutter-sm items-center w-full"):
            bg = ui.select({"field": t["bg_field"], "resolution": t["bg_resolution"], "depth": t["bg_depth"]}, value="field", label=t["background"]).classes("sl-w-lg")
            cmap = ui.select({"auto": t["cmap_auto"], "Viridis": "Viridis", "RdBu_r": "RdBu", "RdYlBu_r": "RdYlBu", "Turbo": "Turbo", "Cividis": "Cividis", "deep": "deep", "thermal": "thermal", "haline": "haline"}, value="auto", label=t["cmap"]).classes("sl-w-sm")
            zlo = ui.number(t["zmin"], value=None).classes("sl-w-sm"); zhi = ui.number(t["zmax"], value=None).classes("sl-w-sm")
            ui.button(t["zauto"], icon="autorenew", on_click=lambda: (zlo.set_value(None), zhi.set_value(None), set_manual())).props("flat dense")
            arr = ui.switch(t["arrows"], value=False); arr.set_visibility(has_vel)
            fixed = ui.switch(t["fixed_scale"], value=True)
            mesh_sw = ui.switch(t["show_mesh"], value=False)
            speed = ui.select({2: "2 fps", 5: "5 fps", 10: "10 fps"}, value=5, label="▶").classes("sl-w-sm")

    # --- paneles inferiores
    with ui.tabs().classes("w-full").props("dense no-caps mobile-arrows") as subtabs:
        tp = ui.tab("tab_points", label=t["points"]); tsec = ui.tab("tab_sections", label=t["sections"]); tan = ui.tab("tab_anim", label=t["animate"])
    panels = ui.tab_panels(subtabs, value=tp).classes("w-full")
    with panels, ui.tab_panel(tp):
        with ui.row().classes("w-full"):
            plist = ui.column().classes("col-12 col-md-3 q-gutter-xs")
            with ui.column().classes("col-12 col-md-9"):
                sfig = ui.plotly(series_figure_multi(st, st.var, lang, wd)).classes("w-full").style("height:320px")
                pfig = ui.plotly(go.Figure()).classes("w-full").style("height:300px")
        with ui.row().classes("q-gutter-sm"):
            ui.button(t["download_series"], icon="download", on_click=lambda: export_series()).props("flat dense")
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
                    ui.button(t["sec_longitudinal"], icon="swap_horiz", on_click=lambda: arm("longitudinal")).props("outline dense color=primary")
                    sec_vars = [v for v in st.vars if st.is3d(v)] or list(st.vars)        # en 2D: cualquier variable (perfil a lo largo del corte)
                    svar = ui.select(sec_vars, value=st.var if st.var in sec_vars else sec_vars[0], label=t["variable"]).classes("sl-w-md")
                    scont = ui.switch(t["contours"], value=True)
                    wf = ui.number(t["wfactor"], value=200, min=1, step=50).classes("sl-w-sm")
                    ui.button(t["hovmoller"], icon="view_timeline", on_click=lambda: show_hov()).props("flat dense")
                secfig = ui.plotly(go.Figure()).classes("w-full").style("height:430px")
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
        if st.arrows or st.background != "field" or st.pending is not None:
            refresh_map(); return
        try:
            fig = map_figure(st, t, lang)
            h = fig["data"][0]
            z = np.asarray(h["z"], float)
            plot.figure["data"][0]["z"] = z                                 # el servidor conserva la figura coherente
            plot.figure["layout"]["title"] = fig["layout"].get("title")
            zl = np.where(np.isfinite(z), z, None).tolist()
            upd = {"z": [zl]}
            for k in ("zmin", "zmax"):
                if h.get(k) is not None:
                    upd[k] = [float(h[k])]
            plot.run_plot_method("restyle", upd, [0])
            plot.run_plot_method("relayout", {"title.text": fig["layout"]["title"] if isinstance(fig["layout"].get("title"), str) else (fig["layout"].get("title") or {}).get("text", "")})
        except Exception:   # noqa: BLE001  (sin navegador o cliente antiguo: ruta de respaldo)
            refresh_map()
    def refresh_time_label():
        tlabel.set_text(np.datetime_as_string(ds.time.values[st.it], "m").replace("T", " "))
    def refresh_points_list():
        plist.clear()
        with plist:
            ui.label(t["points"]).classes("text-subtitle2")
            for i, p in enumerate(st.points):
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    ui.icon("sensors" if p.get("station") else "place").style(f"color:{p['color']}")
                    ui.input(value=p["name"]).props("dense borderless").style("width:4.5rem").on_value_change(lambda e, p=p: (p.update(name=e.value), refresh_map(), refresh_series()))
                    ui.label(f"{p['x']:.4f}, {p['y']:.4f}").classes("text-caption text-no-wrap")
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
        refresh_points_list(); refresh_map(); refresh_series()
    def remove_point(i):
        st.points.pop(i); refresh_points_list(); refresh_map(); refresh_series()
    def refresh_series():
        sfig.update_figure(series_figure_multi(st, st.var, lang, wd))
        if st.points and st.is3d(st.var):
            p = st.points[-1]
            z = st.vg.zcor(np.array([float(ds.depth.isel(node=p["node"]))]), np.array([float(ds.elevation.isel(node=p["node"], time=st.it))]))[0] if "elevation" in ds else st.vg.zcor(np.array([float(ds.depth.isel(node=p["node"]))]))[0]
            if "zCoordinates" in ds:
                z = ds.zCoordinates.isel(node=p["node"], time=st.it).values
            pfig.update_figure(themed(profile_figure(ds, st.var, p["node"], z, st.it, lang), st.dark)); pfig.set_visibility(True)
        else:
            pfig.set_visibility(False)
    def refresh_sections_list():
        slist.clear()
        with slist:
            ui.label(t["sections"]).classes("text-subtitle2")
            for i, s in enumerate(st.sections):
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    ui.icon("straighten").style(f"color:{s['color']}")
                    ui.input(value=s["name"]).props("dense borderless").style("width:4.5rem").on_value_change(lambda e, s=s: (s.update(name=e.value), refresh_map()))
                    ui.label(f"({s['p0'][0]:.2f}, {s['p0'][1]:.2f}) → ({s['p1'][0]:.2f}, {s['p1'][1]:.2f})").classes("text-caption text-no-wrap")
                    ui.button(icon="visibility", on_click=lambda i=i: show_section(i)).props("flat dense round size=sm")
                    ui.button(icon="close", on_click=lambda i=i: remove_section(i)).props("flat dense round size=sm")
            if not st.sections:
                ui.label(t["no_sections"]).classes("text-caption text-grey-7")
    state_sec = {"active": None}
    def remove_section(i):
        st.sections.pop(i); state_sec["active"] = None if not st.sections else min(i, len(st.sections) - 1)
        refresh_sections_list(); refresh_map(); show_section(state_sec["active"])
    def show_section(i, switch: bool = True):
        """Dibuja la sección i; `switch` lleva a la pestaña Secciones (solo cuando lo pide el usuario, no al reproducir)."""
        if i is None or i >= len(st.sections):
            secfig.update_figure(go.Figure()); return
        state_sec["active"] = i
        s = st.sections[i]
        try:
            zr = None
            if fixed.value:
                v = s["sec"].scalar(svar.value, st.it); zr = (float(np.nanmin(v)), float(np.nanmax(v))) if np.isfinite(v).any() else None
                zr = st.zr if svar.value == st.var and st.zr else zr
            iso = (st.var, st.iso_value) if st.iso_ok() else None
            secfig.update_figure(section_figure2(s["sec"], svar.value, st.it, arrows=arr.value, contours=scont.value, wfactor=float(wf.value or 200), zrange=zr, lang=lang, dark=st.dark, iso=iso))
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
            hovfig.update_figure(hovmoller_figure(st.sections[i]["sec"], svar.value, st.layer, lang, dark=st.dark))
        hovfig.set_visibility(True)
    def move_cursor():
        """Mueve los marcadores y la línea del instante en las series (restyle/relayout, sin redibujar)."""
        n = len(getattr(st, "series_lines", []))
        if not n:
            return
        xs, ys, tc = series_cursor(st)
        try:
            data = sfig.figure["data"]
            for k in range(n):
                data[n + k]["x"] = [xs[k]]; data[n + k]["y"] = [ys[k]]
            if sfig.figure["layout"].get("shapes"):
                sfig.figure["layout"]["shapes"][0].update(x0=tc, x1=tc)
            sfig.run_plot_method("restyle", {"x": [[x_] for x_ in xs], "y": [[y_] for y_ in ys]}, list(range(n, 2 * n)))
            sfig.run_plot_method("relayout", {"shapes[0].x0": tc, "shapes[0].x1": tc})
        except Exception:   # noqa: BLE001  (figura cambiada mientras tanto: se redibuja)
            sfig.update_figure(series_figure_multi(st, st.var, lang, wd))
    def on_time(e):
        st.it = int(e.value); refresh_time_label(); refresh_map_time(); move_cursor()
        if state_sec["active"] is not None and in_sections():     # la sección sigue al tiempo solo si se está viendo
            show_section(state_sec["active"], switch=False)
    def refresh_range():
        st.zr = dataset_range(ds, st.var, st.layer) if st.depth_mode == "layer" else (st.iso_range() if st.iso_ok() else None)
    def on_var(e):
        st.var = e.value; refresh_range()
        refresh_map(); refresh_series()
        if state_sec["active"] is not None and st.depth_mode == "iso":
            show_section(state_sec["active"], switch=False)
    def on_layer(e):
        st.layer = int(e.value); st.zr = dataset_range(ds, st.var, st.layer)
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
                st.add_section(st.pending, (x, y)); st.pending = None; refresh_sections_list(); refresh_map(); show_section(len(st.sections) - 1)
        else:
            p0, p1 = preset_section(ds, (x, y), m)
            st.add_section(p0, p1, f"{'T' if m == 'transversal' else 'L'}{len(st.sections) + 1}"); refresh_sections_list(); refresh_map(); show_section(len(st.sections) - 1)
    def on_relayout(e):
        a = e.args or {}
        if "shapes" in a:                                            # línea nueva dibujada (drawline) o lista completa
            shapes = [sh for sh in a["shapes"] if sh.get("type") == "line"]
            if len(shapes) > len(st.sections):
                sh = shapes[-1]; st.add_section((sh["x0"], sh["y0"]), (sh["x1"], sh["y1"])); refresh_sections_list(); refresh_map(); show_section(len(st.sections) - 1)
            return
        changed = set()
        for k, v in a.items():
            mm = re.match(r"shapes\[(\d+)\]\.(x0|x1|y0|y1)", k)
            if mm:
                i, key = int(mm.group(1)), mm.group(2)
                if i < len(st.sections):
                    s = st.sections[i]; p0, p1 = list(s["p0"]), list(s["p1"])
                    {"x0": lambda: p0.__setitem__(0, float(v)), "y0": lambda: p0.__setitem__(1, float(v)), "x1": lambda: p1.__setitem__(0, float(v)), "y1": lambda: p1.__setitem__(1, float(v))}[key]()
                    s["p0"], s["p1"] = tuple(p0), tuple(p1); changed.add(i)
        for i in changed:                                             # extremos arrastrados: recalcular el corte
            s = st.sections[i]; s["sec"] = Section(ds, s["p0"], s["p1"], vg=st.vg, tri=st.tri)
            refresh_sections_list(); show_section(i)
    def export_series():
        import pandas as pd
        cols = {}
        if st.iso_ok():
            from ..analysis.isosurface import isosurface_series
            cols = {p["name"]: isosurface_series(ds, st.var, st.iso_value, p["node"], st.vg) for p in st.points}
            df = pd.DataFrame(cols, index=pd.DatetimeIndex(ds.time.values)); f = wd / f"iso_{st.var}_{st.iso_value:g}.csv"; df.to_csv(f); ui.download(f); return
        for p in st.points:
            s = point_series(ds, st.var, p["node"], st.layer)
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
    def set_manual():
        lo, hi = zlo.value, zhi.value
        st.zmanual = (float(lo), float(hi)) if (lo is not None and hi is not None and float(hi) > float(lo)) else None
        refresh_map()
    zlo.on_value_change(lambda e: set_manual()); zhi.on_value_change(lambda e: set_manual())
    def in_sections() -> bool:
        return str(panels.value) in ("tab_sections", str(tsec))
    def on_subtab(e):
        st.click_mode = "section" if in_sections() else "point"; st.pending = None; armed["mode"] = None; refresh_map()
    panels.on_value_change(on_subtab)
    tsl.on_value_change(on_time)
    svar.on_value_change(lambda e: show_section(state_sec["active"])); scont.on_value_change(lambda e: show_section(state_sec["active"])); wf.on_value_change(lambda e: show_section(state_sec["active"]))
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
    wfig = ui.plotly(go.Figure()).classes("w-full").style("height:420px")
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
        return point_series(ds, pvar.value, p["node"], st.layer)
    def _cart_lat(y_m):
        """Dominio cartesiano: latitud equivalente para el periodo inercial (plano f: lat0; plano β: lat0 + y/R)."""
        cor = (c.get("physics") or {}).get("coriolis", "f-plane")
        if cor in ("none", False, 0, None):
            return None
        lat0 = float((c.get("reference") or {}).get("lat0", 45.0))
        if cor == "beta" and y_m is not None:
            return lat0 + float(np.rad2deg(float(y_m) / 6371e3))
        return lat0
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
        sf, pf, rf = go.Figure(), None, None; wf_ = None; msg = []
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
            refs = reference_periods(lat_of(name))
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
            if k == 0:
                w = wavelet_morlet(y, dt, omega0=float(w0.value or 6))
                wf_ = wavelet_figure(w, t0 if np.issubdtype(np.asarray(s["t"]).dtype, np.datetime64) else None, refs, lang, dark=st.dark, global_name=t["global_spectrum"])
                wf_.update_layout(title=f"wavelet · {name}")
        sf.update_layout(hovermode="x unified", **layout(st.dark))
        sfig.update_figure(sf); pfig.update_figure(pf or go.Figure()); wfig.update_figure(wf_ or go.Figure())
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
