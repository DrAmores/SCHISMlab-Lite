"""Pestaña Partículas de Resultados: controles a la izquierda (variable, capa, instante y zona de suelta) y un mapa a
la derecha con el campo, las trayectorias y las partículas, que se reproduce como el explorador (el campo cambia con
el tiempo junto a las partículas). Cada fotograma solo reenvía el campo y las posiciones (Plotly.restyle)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.tri as mtri
import plotly.graph_objects as go
from nicegui import ui, run

from .figures import _values, _aspect, dataset_range, themed, LABELS, LAYOUT
from .explorer import CLICK_JS
from ..analysis.particles import track as track_particles, release_points, is_geographic

NGRID = 220
_TRACKS: dict = {}            # carpeta de la simulación -> (trayectorias, parámetros): se recuperan al recargar la página


class _Grid:
    """Rejilla regular para el mapa de calor, con la triangulación y su buscador hechos una sola vez."""

    def __init__(self, ds, n: int = NGRID):
        x, y = ds.x.values, ds.y.values
        self.tri = mtri.Triangulation(x, y, np.asarray(ds.attrs["elements"]))
        self.finder = self.tri.get_trifinder()
        self.xi = np.linspace(x.min(), x.max(), n)
        self.yi = np.linspace(y.min(), y.max(), max(30, int(n * _aspect(y) * np.ptp(y) / max(np.ptp(x), 1e-12))))
        self.X, self.Y = np.meshgrid(self.xi, self.yi)

    def z(self, values) -> np.ndarray:
        return mtri.LinearTriInterpolator(self.tri, np.asarray(values, float), trifinder=self.finder)(self.X, self.Y).filled(np.nan)


def _circle(x0, y0, r_km, geo):
    a = np.linspace(0, 2 * np.pi, 73)
    if geo:
        return x0 + r_km / (111.32 * np.cos(np.deg2rad(y0))) * np.cos(a), y0 + r_km / 111.32 * np.sin(a)
    return x0 + r_km * 1000 * np.cos(a), y0 + r_km * 1000 * np.sin(a)


def _trails(tr, k):
    """Trayectorias hasta el fotograma k en una sola traza (separadas por None)."""
    xs, ys = [], []
    for j in range(tr.x.shape[1]):
        xs += list(tr.x[: k + 1, j]) + [None]; ys += list(tr.y[: k + 1, j]) + [None]
    return [None if (v is not None and not np.isfinite(v)) else v for v in xs], [None if (v is not None and not np.isfinite(v)) else v for v in ys]


def _clean(a):
    a = np.asarray(a, float)
    return np.where(np.isfinite(a), a, None).tolist()


def particles_tab(ds, c: dict, wd: Path, t: dict, lang: str, est, dark: bool = False):
    geo = is_geographic(ds)
    nt = ds.time.size
    nvrt = int(ds.sizes.get("layer", 1))
    vars_ = [v for v in est.vars if (v in ds or (v + "X") in ds) and "node" in (ds[v].dims if v in ds else ds[v + "X"].dims)]
    g = _Grid(ds)
    S = {"var": est.var if est.var in vars_ else (vars_[0] if vars_ else None), "layer": nvrt - 1, "start": 0, "k": 0, "tr": None,
         "its": None, "zr": None, "bg": "field", "isob": False, "want": None}
    _o = Path(wd) / "outputs"
    _stamp = max((f.stat().st_mtime for f in _o.glob("out2d_*.nc")), default=0.0) if _o.is_dir() else 0.0
    key = f"{Path(wd).resolve()}:{nt}:{_stamp}"                  # otra simulación del caso: no se recuperan trayectorias viejas

    def layer_text(k: int) -> str:
        return t["surface"] if k >= nvrt - 1 else (t["bottom_zero"] if k == 0 else f"{t['layer']} {k + 1}")

    def tlabel(it):
        return np.datetime_as_string(ds.time.values[it], "m").replace("T", " ")

    ui.label(t["particles_hint"]).classes("text-caption text-grey-7")
    with ui.row().classes("w-full items-start no-wrap-md").style("gap:16px;flex-wrap:wrap"):
        # ------------------------------------------------------------------ controles
        with ui.card().classes("q-pa-md").style("flex:0 0 300px;max-width:100%"):
            ui.label(t["p_field"]).classes("text-subtitle2")
            var = ui.select(vars_, value=S["var"], label=t["variable"]).props("dense").classes("w-full").mark("p_var")
            lay_box = ui.column().classes("w-full q-mt-xs")
            with lay_box:
                ui.label(t["p_layer"]).classes("text-caption text-grey-7")
                lay = ui.slider(min=0, max=max(0, nvrt - 1), value=S["layer"]).props(f'label-always label-value="{layer_text(S["layer"])}"').classes("w-full").mark("p_layer")
            lay_box.set_visibility(nvrt > 1)
            bg = ui.select({"field": t["bg_field"], "depth": t["bg_depth"]}, value="field", label=t["background"]).props("dense").classes("w-full").mark("p_bg")
            isob = ui.switch(t["p_isobaths"], value=False).mark("p_isobaths")
            ui.separator().classes("q-my-sm")
            ui.label(t["p_release"]).classes("text-subtitle2")
            ui.label(t["p_start"]).classes("text-caption text-grey-7")
            start = ui.slider(min=0, max=max(0, nt - 2), value=0).classes("w-full")
            start_lbl = ui.label(tlabel(0)).classes("text-caption")
            with ui.row().classes("w-full no-wrap q-gutter-sm"):
                px0 = ui.number("lon" if geo else "x (m)", value=round(float(ds.x.mean()), 4 if geo else 0)).props("dense").classes("col")
                py0 = ui.number("lat" if geo else "y (m)", value=round(float(ds.y.mean()), 4 if geo else 0)).props("dense").classes("col")
            ui.label(t["p_click_hint"]).classes("text-caption text-grey-7")
            with ui.row().classes("w-full no-wrap q-gutter-sm"):
                npart = ui.number(t["n_particles"], value=100, min=1, max=5000).props("dense").classes("col")
                prad = ui.number(t["radius_km"], value=10.0, min=0).props("dense").classes("col")
            phours = ui.number(t["duration_h"], value=round(min(48.0, float((ds.time.values[-1] - ds.time.values[0]) / np.timedelta64(1, "h"))), 1),
                               min=0.1, step=1, format="%.1f").props("dense").classes("w-full")
            pvel = ui.select({"avg": t["vel_avg"], "layer": t["vel_layer"]}, value="avg", label=t["vel_source"]).props("dense").classes("w-full")
            pvel.set_visibility("horizontalVelX" in ds)
            rel_btn = ui.button(t["release"], icon="scatter_plot").props("color=secondary unelevated no-caps").classes("w-full q-mt-sm").mark("p_release")
            stats = ui.column().classes("w-full q-mt-sm")
        # ------------------------------------------------------------------ mapa y reproducción
        with ui.column().style("flex:1 1 560px;min-width:0"):
            with ui.row().classes("items-center w-full no-wrap q-gutter-sm"):
                with ui.element("div"):
                    play = ui.button(icon="play_arrow").props("round dense color=accent").mark("p_play")
                tsl = ui.slider(min=0, max=1, value=0).classes("col").mark("p_time")
                tlab = ui.label("").classes("text-caption text-no-wrap")
            plot = ui.plotly(go.Figure()).classes("w-full").style("height:640px").mark("p_plot")

    # ------------------------------------------------------------------ figura
    def field_it():
        if S["tr"] is not None and S["its"] is not None:
            return S["its"][min(S["k"], len(S["its"]) - 1)]
        return int(start.value)

    def zrange():
        if S["zr"] is None:
            S["zr"] = dataset_range(ds, S["var"], S["layer"])
        return S["zr"]

    depth_grid = {}
    def dgrid():
        if "z" not in depth_grid:
            depth_grid["z"] = g.z(ds.depth.values)
        return depth_grid["z"]

    def build():
        it = field_it(); v = S["var"]
        if S["bg"] == "depth":                                   # batimetría de fondo: se ven los efectos topográficos
            Zb = dgrid(); fin = Zb[np.isfinite(Zb)]
            lo, hi = (float(fin.min()), float(np.percentile(fin, 99.5))) if fin.size else (0.0, 1.0)
            heat = go.Heatmap(x=g.xi, y=g.yi, z=Zb, colorscale="deep", zmin=lo, zmax=hi if hi > lo else lo + 1, zsmooth="best",
                              colorbar=dict(title=LABELS.get("depth", "profundidad (m)"), thickness=14, tickformat=".3g"), hoverinfo="skip")
        else:
            lo, hi = zrange()
            cmap = "RdBu_r" if v == "elevation" else "Viridis"
            heat = go.Heatmap(x=g.xi, y=g.yi, z=g.z(_values(ds, v, it, S["layer"])), colorscale=cmap, zmin=lo, zmax=hi, zsmooth="best",
                              colorbar=dict(title=LABELS.get(v, v), thickness=14, tickformat=".3g"), hoverinfo="skip")
        fig = go.Figure(heat)
        tr, k = S["tr"], S["k"]
        if tr is not None:
            tx, ty = _trails(tr, k)
            fig.add_trace(go.Scatter(x=tx, y=ty, mode="lines", line=dict(width=1, color="rgba(255,255,255,0.75)"), hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=_clean(tr.x[0]), y=_clean(tr.y[0]), mode="markers", marker=dict(size=4, color="#222"), name=t["p_initial"], hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=_clean(tr.x[k]), y=_clean(tr.y[k]), mode="markers", marker=dict(size=7, color="#e4572e", line=dict(color="white", width=1)),
                                     name=t["p_now"], hoverinfo="skip"))
        cx, cy = _circle(float(px0.value or 0), float(py0.value or 0), float(prad.value or 0), geo)
        fig.add_trace(go.Scatter(x=cx, y=cy, mode="lines", line=dict(color="#e4572e", width=1.5, dash="dot"), name=t["p_zone"], hoverinfo="skip"))
        if S["isob"]:                                            # isobatas encima (después de las partículas: no cambian los índices)
            from .explorer import contour_trace
            ct = contour_trace(dgrid(), g.xi, g.yi, 0.0, dark)
            if ct is not None:
                fig.add_trace(ct)
        fig.update_layout(**{**LAYOUT, "margin": dict(l=50, r=20, t=30, b=40)},
                          title=title_text(it),
                          xaxis=dict(title="longitud" if geo else "x (m)", constrain="domain", range=[float(g.xi[0]), float(g.xi[-1])]),
                          yaxis=dict(title="latitud" if geo else "y (m)", scaleanchor="x", scaleratio=_aspect(ds.y.values), range=[float(g.yi[0]), float(g.yi[-1])]),
                          legend=dict(orientation="h", y=-0.08), uirevision="particulas")
        plot.update_figure(themed(fig, dark))
        tlab.set_text(tlabel(it))

    def title_text(it):
        if S["bg"] == "depth":
            return f"{t['bg_depth']} · {tlabel(it)}"
        return f"{S['var']} · {layer_text(S['layer']) + ' · ' if nvrt > 1 else ''}{tlabel(it)}"

    def frame():
        """Fotograma k: campo y partículas por restyle (sin reenviar la figura)."""
        tr, k = S["tr"], S["k"]
        if tr is None:
            build(); return
        it = field_it()
        try:
            tx, ty = _trails(tr, k)
            if S["bg"] != "depth":                               # la batimetría no cambia con el tiempo
                z = g.z(_values(ds, S["var"], it, S["layer"]))
                plot.run_plot_method("restyle", {"z": [_clean(z)]}, [0])
            plot.run_plot_method("restyle", {"x": [tx, _clean(tr.x[k])], "y": [ty, _clean(tr.y[k])]}, [1, 3])
            plot.run_plot_method("relayout", {"title.text": title_text(it)})
            tlab.set_text(tlabel(it))
        except Exception:   # noqa: BLE001
            build()

    # ------------------------------------------------------------------ acciones
    async def release():
        x0, y0, n, r, h = float(px0.value), float(py0.value), int(npart.value), float(prad.value), float(phours.value)
        st0, lay_ = int(start.value), (S["layer"] if pvel.value == "layer" else None)
        rel_btn.props("loading")
        try:
            tr = await run.io_bound(lambda: track_particles(ds, *release_points(x0, y0, n, r, geo), start=st0, hours=h, layer=lay_))
        except Exception as ex:   # noqa: BLE001
            ui.notify(str(ex), type="negative"); return
        finally:
            rel_btn.props(remove="loading")
        if tr is None:                                   # la página se cerró mientras se calculaba
            return
        _TRACKS[key] = tr
        show_tracks(tr)
    rel_btn.on_click(release)

    def show_tracks(tr):
        S["tr"] = tr; S["k"] = 0
        S["its"] = [int(np.argmin(np.abs(ds.time.values - tt))) for tt in tr.time]
        tsl.props(f"max={max(1, tr.x.shape[0] - 1)}"); tsl._props["max"] = max(1, tr.x.shape[0] - 1); tsl.set_value(0)
        d = tr.distance_km()
        stats.clear()
        with stats:
            ui.label(f"{t['mean_dist']}: {np.nanmean(d):.1f} km").classes("text-body2")
            ui.label(f"{t['max_dist']}: {np.nanmax(d):.1f} km").classes("text-body2")
            def dl():
                p = wd / "particulas.csv"; tr.to_csv(p); ui.download(p)
            ui.button(t["download_csv"], icon="download", on_click=dl).props("flat dense no-caps")
        build()

    def on_click(e):
        pts = e.args.get("points", [])
        if pts:
            px0.set_value(round(float(pts[0]["x"]), 4 if geo else 0)); py0.set_value(round(float(pts[0]["y"]), 4 if geo else 0))
    plot.on("plotly_click", on_click, js_handler=CLICK_JS)

    def on_var(e):
        S["var"] = e.value; S["zr"] = None; build()
    def on_layer(e):
        S["layer"] = int(e.value); S["zr"] = None
        lay.props(f'label-value="{layer_text(S["layer"])}"'); build()
    def on_start(e):
        start_lbl.set_text(tlabel(int(e.value)))
        if S["tr"] is None:
            build()
    def on_time(e):
        S["want"] = int(e.value)                                  # se dibuja solo el último valor (ver render_time)
    def render_time():
        if S["want"] is None or S["tr"] is None:
            return
        S["k"] = min(S["want"], S["tr"].x.shape[0] - 1); S["want"] = None; frame()
    ui.timer(0.08, render_time)

    def tick():
        if S["tr"] is None:
            return
        nk = S["k"] + 1
        if nk >= S["tr"].x.shape[0]:
            nk = 0
        tsl.set_value(nk)
    timer = ui.timer(0.2, tick, active=False)

    def toggle():
        if S["tr"] is None:
            ui.notify(t["p_release_first"], type="info"); return
        timer.active = not timer.active
        play.props(f"icon={'pause' if timer.active else 'play_arrow'}")
    play.on_click(toggle)
    var.on_value_change(on_var); lay.on_value_change(on_layer); start.on_value_change(on_start); tsl.on_value_change(on_time)
    bg.on_value_change(lambda e: (S.update(bg=e.value), build()))
    isob.on_value_change(lambda e: (S.update(isob=bool(e.value)), build()))
    for w_ in (px0, py0, prad):
        w_.on_value_change(lambda e: build() if S["tr"] is None or not timer.active else None)
    if key in _TRACKS:                                           # página recargada: las partículas ya calculadas siguen ahí
        show_tracks(_TRACKS[key])
    else:
        build()
    return S
