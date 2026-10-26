"""Figuras interactivas (Plotly) para la interfaz: mallas, campos, series, perfiles, secciones y animaciones."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
import matplotlib.tri as mtri
import xarray as xr
from ..io.gr3 import Mesh

LAYOUT = dict(margin=dict(l=40, r=20, t=40, b=40), template="plotly_white", font=dict(family="Space Grotesk, Helvetica, Arial, sans-serif"),
              colorway=["#0e9aa7", "#2b2b2b", "#d8542b", "#7a4fb8", "#4d8f2f", "#b8860b", "#b5536a", "#4a7fb0"])
LABELS_BY_LANG = {
    "es": {"elevation": "elevación (m)", "depthAverageVel": "|U| (m/s)", "horizontalVel": "|u| (m/s)", "temperature": "T (°C)",
           "salinity": "S (psu)", "verticalVelocity": "w (m/s)", "windStress": "τ (m²/s²)", "windSpeed": "viento (m/s)",
           "sigWaveHeight": "Hs (m)", "depth": "profundidad (m)", "airPressure": "presión (Pa)", "waterDensity": "ρ (kg/m³)", "density": "σt (kg/m³)",
           "vorticity": "ζ (1/s)", "vorticity_f": "ζ/f", "transport": "|T| (m²/s)", "streamfunction": "ψ (Sv)", "viscosity": "viscosidad (m²/s)",
           "diffusivity": "difusividad (m²/s)"},
    "en": {"elevation": "elevation (m)", "depthAverageVel": "|U| (m/s)", "horizontalVel": "|u| (m/s)", "temperature": "T (°C)",
           "salinity": "S (psu)", "verticalVelocity": "w (m/s)", "windStress": "τ (m²/s²)", "windSpeed": "wind (m/s)",
           "sigWaveHeight": "Hs (m)", "depth": "depth (m)", "airPressure": "pressure (Pa)", "waterDensity": "ρ (kg/m³)", "density": "σt (kg/m³)",
           "vorticity": "ζ (1/s)", "vorticity_f": "ζ/f", "transport": "|T| (m²/s)", "streamfunction": "ψ (Sv)", "viscosity": "viscosity (m²/s)",
           "diffusivity": "diffusivity (m²/s)"},
}
# componentes con signo de las variables vectoriales: (nombre corto, unidades)
VECTOR_PARTS = {"horizontalVel": ("u", "v", "m/s"), "depthAverageVel": ("U", "V", "m/s"), "windStress": ("τx/ρ0", "τy/ρ0", "m²/s²"),
                "transport": ("Tx", "Ty", "m²/s"), "windSpeed": ("u10", "v10", "m/s")}
LABELS = LABELS_BY_LANG["es"]          # compatibilidad (analysis/video.py): etiquetas en español


def label(var: str, lang: str = "es", comp: str = "mag") -> str:
    """Etiqueta (con unidad) de una variable de salida en el idioma pedido; el nombre de la variable si no hay.
    comp: componente de una variable vectorial («u» este, «v» norte, «normal», «tangential»)."""
    if comp != "mag" and var in VECTOR_PARTS:
        a, b, un = VECTOR_PARTS[var]
        txt = {"u": f"{a} ({'este' if lang == 'es' else 'east'})", "v": f"{b} ({'norte' if lang == 'es' else 'north'})",
               "normal": "normal" if lang != "es" else "normal", "tangential": "tangencial" if lang == "es" else "tangential"}.get(comp, comp)
        if comp in ("normal", "tangential"):
            txt = f"{var} {txt}"
        return f"{txt} ({un})"
    if comp != "mag" and var not in VECTOR_PARTS:
        return f"{var} {comp}"
    return LABELS_BY_LANG.get(lang, LABELS).get(var, var)


def layout(dark: bool = False) -> dict:
    """Disposición común de las figuras; en modo oscuro, plantilla oscura con fondos transparentes."""
    if dark:
        return dict(LAYOUT, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return dict(LAYOUT)


def themed(fig, dark: bool = False):
    """Aplica el tema oscuro a una figura (go.Figure o dict de plotly) ya construida; devuelve la misma figura."""
    if not dark or fig is None:
        return fig
    lay = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    if isinstance(fig, dict):
        fig.setdefault("layout", {}).update(lay)
    else:
        fig.update_layout(**lay)
    return fig


class NodeSampler:
    """Campo nodal -> rejilla regular por interpolación lineal en el triángulo que contiene cada celda (como un pcolor
    sobre la malla): continuo dentro del dominio y NaN fuera. La búsqueda de triángulos se hace una vez; cada campo
    nuevo cuesta una suma ponderada, así que sirve para animar mallas grandes."""

    def __init__(self, mesh, n: int = 150, tri=None):
        """`mesh`: Mesh (x, y, elements) o Dataset de open_run (x, y, attrs["elements"]); `tri`: Triangulation ya hecha."""
        x = np.asarray(getattr(mesh.x, "values", mesh.x), float); y = np.asarray(getattr(mesh.y, "values", mesh.y), float)
        e = np.asarray(mesh.attrs["elements"] if hasattr(mesh, "attrs") and "elements" in mesh.attrs else mesh.elements)[:, :3]
        self.xi = np.linspace(x.min(), x.max(), n)
        ny = max(int(n * np.ptp(y) / max(np.ptp(x), 1e-12) * (1 / np.cos(np.deg2rad(y.mean())) if np.ptp(y) < 180 else 1)), 30)
        self.yi = np.linspace(y.min(), y.max(), min(ny, 400))
        X, Y = np.meshgrid(self.xi, self.yi); px, py = X.ravel(), Y.ravel()
        tri = tri if tri is not None else mtri.Triangulation(x, y, e)
        ie = tri.get_trifinder()(px, py)
        self.inside = ie >= 0
        self.idx = np.where(self.inside[:, None], tri.triangles[np.maximum(ie, 0)], 0)      # (celdas, 3) nodos del triángulo
        xa, ya = x[self.idx], y[self.idx]
        det = (ya[:, 1] - ya[:, 2]) * (xa[:, 0] - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (ya[:, 0] - ya[:, 2])
        det = np.where(np.abs(det) < 1e-300, 1.0, det)
        w0 = ((ya[:, 1] - ya[:, 2]) * (px - xa[:, 2]) + (xa[:, 2] - xa[:, 1]) * (py - ya[:, 2])) / det
        w1 = ((ya[:, 2] - ya[:, 0]) * (px - xa[:, 2]) + (xa[:, 0] - xa[:, 2]) * (py - ya[:, 2])) / det
        self.w = np.clip(np.stack([w0, w1, 1 - w0 - w1], 1), 0, 1)
        self.w /= np.maximum(self.w.sum(1, keepdims=True), 1e-12)

    def grid(self, values: np.ndarray) -> np.ndarray:
        v = np.asarray(values, float)
        Z = (v[self.idx] * self.w).sum(1)
        Z[~self.inside] = np.nan
        return Z.reshape(self.yi.size, self.xi.size)


def color_range(values, zmin=None, zmax=None, min_rel: float = 1e-6):
    """(zmin, zmax, tickformat) de una barra de color legible: con un campo constante (o casi) fija un rango mínimo
    alrededor del valor, para que el redondeo (diferencias de 1e-16) no pinte ruido; las marcas llevan los decimales
    que pide el rango (p. ej. 1025.53–1027.56 en vez de «1.03e+3» repetido)."""
    a = np.asarray(values, float); a = a[np.isfinite(a)]
    if a.size == 0:
        return zmin, zmax, ".3g"
    lo = float(a.min()) if zmin is None else float(zmin); hi = float(a.max()) if zmax is None else float(zmax)
    mid = 0.5 * (lo + hi); span = hi - lo
    floor = max(abs(mid) * 1e-3, 1e-6)
    if span <= max(min_rel * max(abs(mid), 1.0), 1e-12):         # campo constante: rango ±0.1 % del valor (mín. ±1e-6)
        lo, hi, span = mid - floor, mid + floor, 2 * floor
    d = int(np.clip(np.ceil(-np.log10(span / 5.0)) + 1, 0, 6))
    fmt = f".{d}f" if abs(mid) < 1e5 else ".4g"
    return lo, hi, fmt


def _aspect(y):
    return 1 / np.cos(np.deg2rad(np.mean(y))) if np.ptp(y) < 180 else 1.0


def grid_field(x, y, elements, values, n=350):
    """Interpola valores nodales a una rejilla regular (NaN fuera de la malla) para un mapa de calor."""
    tri = mtri.Triangulation(x, y, np.asarray(elements))
    xi = np.linspace(x.min(), x.max(), n); yi = np.linspace(y.min(), y.max(), int(n * _aspect(y) * np.ptp(y) / np.ptp(x)) or 50)
    X, Y = np.meshgrid(xi, yi)
    Z = mtri.LinearTriInterpolator(tri, np.asarray(values, float))(X, Y).filled(np.nan)
    return xi, yi, Z


def field_figure(x, y, elements, values, label: str, title: str = "", cmap="Viridis", zmin=None, zmax=None,
                 boundaries=None, symmetric=False, n=350) -> go.Figure:
    xi, yi, Z = grid_field(x, y, elements, values, n)
    if symmetric and zmin is None:
        zmax = float(np.nanmax(np.abs(Z))); zmin = -zmax
    geo = bool(np.nanmax(np.abs(x)) <= 360 and np.nanmax(np.abs(y)) <= 90.5)    # lon/lat o metros (dominios idealizados)
    hov = "lon %{x:.3f}<br>lat %{y:.3f}<br>%{z:.3f}<extra></extra>" if geo else "x %{x:.0f} m<br>y %{y:.0f} m<br>%{z:.3f}<extra></extra>"
    fig = go.Figure(go.Heatmap(x=xi, y=yi, z=Z, colorscale=cmap, zmin=zmin, zmax=zmax, zsmooth="best",
                               colorbar=dict(title=label, thickness=14, tickformat=".3g"), hovertemplate=hov))
    if boundaries:
        for (bx, by, color) in boundaries:
            fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", line=dict(color=color, width=2), hoverinfo="skip", showlegend=False))
    fig.update_layout(title=title, xaxis=dict(title="longitud" if geo else "x (m)", constrain="domain"),
                      yaxis=dict(title="latitud" if geo else "y (m)", scaleanchor="x", scaleratio=_aspect(y)), **LAYOUT)
    return fig


def mesh_figure(mesh: Mesh, title: str = "") -> go.Figure:
    """Profundidad interpolada + aristas de la malla (submuestreadas si es grande) + contornos."""
    bnds = [(mesh.x[b], mesh.y[b], "#d8542b") for b in mesh.open_boundaries] + \
           [(mesh.x[b], mesh.y[b], "#222" if f == 0 else "#777") for b, f in mesh.land_boundaries]
    fig = field_figure(mesh.x, mesh.y, mesh.elements, mesh.depth, LABELS["depth"], title, cmap="Viridis_r", boundaries=bnds)
    e = np.asarray(mesh.elements)
    if len(e) <= 40000:
        step = max(1, len(e) // 15000)
        tri = e[::step]
        xs = np.column_stack([mesh.x[tri[:, 0]], mesh.x[tri[:, 1]], mesh.x[tri[:, 2]], mesh.x[tri[:, 0]], np.full(len(tri), np.nan)]).ravel()
        ys = np.column_stack([mesh.y[tri[:, 0]], mesh.y[tri[:, 1]], mesh.y[tri[:, 2]], mesh.y[tri[:, 0]], np.full(len(tri), np.nan)]).ravel()
        fig.add_trace(go.Scattergl(x=xs, y=ys, mode="lines", line=dict(color="rgba(0,0,0,0.25)", width=0.5), hoverinfo="skip", showlegend=False))
    return fig


def _values(ds: xr.Dataset, var: str, it: int, layer: int):
    if var + "X" in ds:
        u, v = ds[var + "X"].isel(time=it), ds[var + "Y"].isel(time=it)
        if "layer" in u.dims:
            u, v = u.isel(layer=layer), v.isel(layer=layer)
        return np.hypot(u.values, v.values)
    da = ds[var].isel(time=it)
    if "layer" in da.dims:
        da = da.isel(layer=layer)
    return da.values


def dataset_map(ds: xr.Dataset, var: str, it: int, layer: int = -1, zrange=None) -> go.Figure:
    vals = _values(ds, var, it, layer)
    t = np.datetime_as_string(ds.time.values[it], "m").replace("T", " ")
    sym = var == "elevation"
    cmap = "RdBu_r" if sym else "Viridis"
    zmin, zmax = (zrange if zrange else (None, None))
    return field_figure(ds.x.values, ds.y.values, ds.attrs["elements"], vals, LABELS.get(var, var), f"{var} · {t}",
                        cmap=cmap, zmin=zmin, zmax=zmax, symmetric=sym and zrange is None)


def dataset_range(ds: xr.Dataset, var: str, layer: int = -1) -> tuple[float, float]:
    sample = [_values(ds, var, i, layer) for i in range(0, ds.time.size, max(1, ds.time.size // 8))]
    a = np.stack(sample)
    if var == "elevation":
        m = float(np.nanpercentile(np.abs(a), 99)); return -m, m
    return float(np.nanpercentile(a, 1)), float(np.nanpercentile(a, 99))


def series_figure(ds: xr.Dataset, var: str, node: int, layer: int = -1, extra: dict | None = None) -> go.Figure:
    if var + "X" in ds:
        u, v = ds[var + "X"].isel(node=node), ds[var + "Y"].isel(node=node)
        if "layer" in u.dims:
            u, v = u.isel(layer=layer), v.isel(layer=layer)
        y = np.hypot(u.values, v.values)
    else:
        da = ds[var].isel(node=node)
        if "layer" in da.dims:
            da = da.isel(layer=layer)
        y = da.values
    fig = go.Figure(go.Scatter(x=ds.time.values, y=y, mode="lines", name=LABELS.get(var, var), line=dict(color="#0e9aa7", width=2)))
    for name, (tt, yy) in (extra or {}).items():
        fig.add_trace(go.Scatter(x=tt, y=yy, mode="lines", name=name, line=dict(color="#555", width=1)))
    fig.update_layout(yaxis_title=LABELS.get(var, var), hovermode="x unified", **LAYOUT)
    return fig


def profile_figure(ds: xr.Dataset, var: str, node: int, z: np.ndarray, it: int = -1, lang: str = "es") -> go.Figure:
    fig = go.Figure()
    if var + "X" in ds:                                   # vector: u (hacia el este) continua, v (hacia el norte) discontinua
        fig.add_trace(go.Scatter(x=ds[var + "X"].isel(node=node, time=it).values, y=z, mode="lines+markers", name="u"))
        fig.add_trace(go.Scatter(x=ds[var + "Y"].isel(node=node, time=it).values, y=z, mode="lines+markers", name="v", line=dict(dash="dash")))
        xt = "u (este), v (norte) (m/s)" if lang == "es" else "u (east), v (north) (m/s)"
    else:
        fig.add_trace(go.Scatter(x=ds[var].isel(node=node, time=it).values, y=z, mode="lines+markers", name=var))
        xt = label(var, lang)
    fig.update_layout(xaxis_title=xt, yaxis_title="z (m)", **LAYOUT)
    return fig


def profile_figure2(z, prof: dict, xlabel: str, lang: str = "es") -> go.Figure:
    """Perfil vertical ya calculado: prof = {"u", "v"} (vector: también |v|) o {"y"}; z del fondo a la superficie."""
    fig = go.Figure()
    if "u" in prof:
        u, v = np.asarray(prof["u"], float), np.asarray(prof["v"], float)
        fig.add_trace(go.Scatter(x=u, y=z, mode="lines+markers", name="u", marker=dict(size=4)))
        fig.add_trace(go.Scatter(x=v, y=z, mode="lines+markers", name="v", line=dict(dash="dash"), marker=dict(size=4)))
        fig.add_trace(go.Scatter(x=np.hypot(u, v), y=z, mode="lines", name="|v|", line=dict(dash="dot", color="#888")))
        un = xlabel.rsplit("(", 1)[-1].rstrip(")") if "(" in xlabel else "m/s"
        xt = (f"u (este), v (norte), |v| ({un})" if lang == "es" else f"u (east), v (north), |v| ({un})")
    else:
        fig.add_trace(go.Scatter(x=np.asarray(prof["y"], float), y=z, mode="lines+markers", name=xlabel, marker=dict(size=4)))
        xt = xlabel
    fig.update_layout(xaxis_title=xt, yaxis_title="z (m)", legend=dict(orientation="h"), **LAYOUT)
    return fig


def section_figure(ds: xr.Dataset, var: str, p0, p1, vg, it: int = -1, npts: int = 120) -> go.Figure:
    tri = mtri.Triangulation(ds.x.values, ds.y.values, ds.attrs["elements"])
    xs = np.linspace(p0[0], p1[0], npts); ys = np.linspace(p0[1], p1[1], npts)
    lat0 = np.deg2rad(ys.mean())
    dist = np.hypot(np.deg2rad(xs - xs[0]) * 6371e3 * np.cos(lat0), np.deg2rad(ys - ys[0]) * 6371e3) / 1e3
    da = ds[var].isel(time=it) if var in ds else np.hypot(ds[var + "X"].isel(time=it), ds[var + "Y"].isel(time=it))
    vals = da.values
    depth = mtri.LinearTriInterpolator(tri, ds.depth.values)(xs, ys).filled(np.nan)
    z = vg.zcor(np.nan_to_num(depth, nan=1.0))
    sec = np.column_stack([mtri.LinearTriInterpolator(tri, vals[:, k])(xs, ys).filled(np.nan) for k in range(vals.shape[1])])
    # rejilla regular en z para el mapa de calor
    zi = np.linspace(np.nanmin(-depth), 0, 80)
    S = np.full((zi.size, npts), np.nan)
    for i in range(npts):
        if np.isfinite(depth[i]):
            S[:, i] = np.interp(zi, z[i], sec[i], left=np.nan, right=np.nan)
    fig = go.Figure(go.Heatmap(x=dist, y=zi, z=S, colorscale="RdYlBu_r" if var == "temperature" else "Viridis", zsmooth="best",
                               colorbar=dict(title=LABELS.get(var, var)), hovertemplate="%{x:.0f} km<br>z %{y:.0f} m<br>%{z:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=dist, y=-depth, mode="lines", line=dict(color="#333"), fill="tozeroy", fillcolor="rgba(120,120,120,0.6)", hoverinfo="skip", showlegend=False))
    fig.update_layout(xaxis_title="distancia (km)", yaxis_title="z (m)", **LAYOUT)
    return fig


def animation_figure(ds: xr.Dataset, var: str, layer: int = -1, step: int = 1, n: int = 250) -> go.Figure:
    zmin, zmax = dataset_range(ds, var, layer)
    frames = []
    for it in range(0, ds.time.size, step):
        xi, yi, Z = grid_field(ds.x.values, ds.y.values, ds.attrs["elements"], _values(ds, var, it, layer), n)
        frames.append(go.Frame(data=[go.Heatmap(x=xi, y=yi, z=Z, colorscale="RdBu_r" if var == "elevation" else "Viridis", zmin=zmin, zmax=zmax, zsmooth="best")],
                               name=str(it), layout=go.Layout(title=np.datetime_as_string(ds.time.values[it], "m").replace("T", " "))))
    fig = go.Figure(data=frames[0].data, frames=frames)
    fig.update_layout(title=frames[0].layout.title, yaxis=dict(scaleanchor="x", scaleratio=_aspect(ds.y.values)), **LAYOUT,
                      updatemenus=[dict(type="buttons", showactive=False, x=0.05, y=1.12, buttons=[
                          dict(label="▶", method="animate", args=[None, dict(frame=dict(duration=150, redraw=True), fromcurrent=True)]),
                          dict(label="⏸", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
                      sliders=[dict(steps=[dict(method="animate", args=[[f.name], dict(mode="immediate", frame=dict(duration=0, redraw=True))], label=f.layout.title.text[5:16]) for f in frames],
                                    currentvalue=dict(visible=False), pad=dict(t=30))])
    return fig


def comparison_figure(t_model, y_model, t_obs, y_obs, name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_obs, y=y_obs, mode="lines", name=f"IOC {name}", line=dict(color="#777", width=1)))
    fig.add_trace(go.Scatter(x=t_model, y=y_model, mode="lines", name="SCHISM", line=dict(color="#0e9aa7", width=2)))
    fig.update_layout(yaxis_title="m", hovermode="x unified", **LAYOUT)
    return fig


def particles_figure(ds: xr.Dataset, var: str, it: int, layer: int, tracks, title: str = "") -> go.Figure:
    """Mapa del campo `var` en `it` con las trayectorias de las partículas (líneas) y su posición final (puntos)."""
    fig = dataset_map(ds, var, it, layer)
    n = tracks.x.shape[1]
    for j in range(n):
        fig.add_trace(go.Scatter(x=tracks.x[:, j], y=tracks.y[:, j], mode="lines", line=dict(width=1, color="white"), opacity=0.7, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=tracks.x[0], y=tracks.y[0], mode="markers", marker=dict(size=4, color="black"), name="inicio"))
    fig.add_trace(go.Scatter(x=tracks.x[-1], y=tracks.y[-1], mode="markers", marker=dict(size=6, color="red"), name="final"))
    if title:
        fig.update_layout(title=title)
    return fig


def particles_animation(ds: xr.Dataset, var: str, layer: int, tracks, n: int = 250) -> go.Figure:
    """Animación de las partículas (una imagen por posición guardada) sobre el campo `var`."""
    import numpy as np
    from .figures import grid_field
    nt = tracks.x.shape[0]
    its = [int(np.argmin(np.abs(ds.time.values - t))) for t in tracks.time]
    fig = dataset_map(ds, var, its[0], layer)
    fig.add_trace(go.Scatter(x=tracks.x[0], y=tracks.y[0], mode="markers", marker=dict(size=6, color="red"), name="partículas"))
    frames = []
    for k in range(nt):
        frames.append(go.Frame(data=[go.Scatter(x=tracks.x[k], y=tracks.y[k], mode="markers", marker=dict(size=6, color="red"))],
                               traces=[len(fig.data) - 1], name=str(k)))
    fig.frames = frames
    fig.update_layout(updatemenus=[dict(type="buttons", showactive=False, y=1.08, x=0, buttons=[
        dict(label="▶", method="animate", args=[None, dict(frame=dict(duration=120, redraw=False), fromcurrent=True)]),
        dict(label="⏸", method="animate", args=[[None], dict(frame=dict(duration=0), mode="immediate")])])],
        sliders=[dict(steps=[dict(method="animate", args=[[str(k)], dict(mode="immediate", frame=dict(duration=0, redraw=False))],
                                  label=np.datetime_as_string(tracks.time[k], "h")) for k in range(nt)], currentvalue=dict(prefix=""))])
    return fig


def _on_nodes(ds2: xr.Dataset, ds: xr.Dataset, values2):
    """Lleva un campo nodal de ds2 a los nodos de ds (vecino más cercano; si la malla es la misma, identidad)."""
    import numpy as np
    if ds2.sizes["node"] == ds.sizes["node"] and np.allclose(ds2.x.values, ds.x.values) and np.allclose(ds2.y.values, ds.y.values):
        return values2
    from scipy.spatial import cKDTree
    _, idx = cKDTree(np.column_stack([ds2.x.values, ds2.y.values])).query(np.column_stack([ds.x.values, ds.y.values]))
    return values2[idx]


def _nearest_time(ds2: xr.Dataset, t) -> int:
    import numpy as np
    return int(np.argmin(np.abs(ds2.time.values - t)))


def difference_figure(ds: xr.Dataset, ds2: xr.Dataset, var: str, it: int, layer: int, other_name: str) -> go.Figure:
    """Mapa de (este caso − otro caso) para `var` en el instante `it` (el otro, en su instante más cercano)."""
    import numpy as np
    from plotly.subplots import make_subplots
    v1 = _values(ds, var, it, layer); it2 = _nearest_time(ds2, ds.time.values[it])
    v2 = _on_nodes(ds2, ds, _values(ds2, var, it2, min(layer, ds2.sizes.get("layer", 1) - 1)))
    d = v1 - v2; lim = float(np.nanmax(np.abs(d))) or 1.0
    fig = field_figure(ds.x.values, ds.y.values, ds.attrs["elements"], d, f"Δ {var}", f"{var}: este caso − {other_name} · {np.datetime_as_string(ds.time.values[it], 'm')}",
                       cmap="RdBu", zmin=-lim, zmax=lim)
    return fig


def series_compare_figure(ds: xr.Dataset, ds2: xr.Dataset, var: str, node: int, layer: int, name1: str, name2: str) -> go.Figure:
    import numpy as np
    from .figures import series_figure
    fig = series_figure(ds, var, node, layer)
    fig.data[0].name = name1; fig.data[0].showlegend = True
    x, y = float(ds.x.values[node]), float(ds.y.values[node])
    n2 = int(np.argmin((ds2.x.values - x) ** 2 + (ds2.y.values - y) ** 2))
    f2 = series_figure(ds2, var, n2, min(layer, ds2.sizes.get("layer", 1) - 1))
    tr = f2.data[0]; tr.name = name2; tr.showlegend = True; tr.line = dict(color="#1fa2c4", dash="dash")
    fig.add_trace(tr); fig.update_layout(showlegend=True, legend=dict(orientation="h"))
    return fig


def sst_compare_figure(ds: xr.Dataset, res: dict, lang: str = "es") -> go.Figure:
    """Tres mapas: SST satélite, SST modelo y diferencia (modelo − satélite)."""
    import numpy as np
    from plotly.subplots import make_subplots
    x, y, el = ds.x.values, ds.y.values, ds.attrs["elements"]
    fig = make_subplots(rows=1, cols=3, subplot_titles=("satélite" if lang == "es" else "satellite", "modelo" if lang == "es" else "model", "modelo − satélite" if lang == "es" else "model − satellite"), horizontal_spacing=0.06)
    lo = float(np.nanmin([np.nanmin(res["obs"]), np.nanmin(res["model"])])); hi = float(np.nanmax([np.nanmax(res["obs"]), np.nanmax(res["model"])]))
    d = res["model"] - res["obs"]; lim = float(np.nanmax(np.abs(d[np.isfinite(d)]))) if np.isfinite(d).any() else 1.0
    for col, (vals, cmap, zmin, zmax) in enumerate(((res["obs"], "Viridis", lo, hi), (res["model"], "Viridis", lo, hi), (d, "RdBu", -lim, lim)), 1):
        gx, gy, gz = grid_field(x, y, el, np.nan_to_num(vals, nan=np.nan), n=220)
        fig.add_trace(go.Heatmap(x=gx, y=gy, z=gz, colorscale=cmap, zmin=zmin, zmax=zmax, showscale=(col != 2), colorbar=dict(x=0.63 if col == 1 else 1.0, len=0.9)), row=1, col=col)
        fig.update_yaxes(scaleanchor=f"x{col if col > 1 else ''}", scaleratio=_aspect(y), row=1, col=col)
    fig.update_layout(height=420, margin=dict(l=30, r=30, t=50, b=30), title=f"SST {res['date']} · {'sesgo' if lang == 'es' else 'bias'} {res['bias']:+.2f} °C · RMSE {res['rmse']:.2f} °C · r = {res['corr']:.2f}")
    return fig


def argo_figure(profiles: list[dict], lang: str = "es") -> go.Figure:
    """Perfiles Argo (puntos) frente al modelo (líneas) de T y S, un color por perfil."""
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=1, cols=2, subplot_titles=("T (°C)", "S"), shared_yaxes=True)
    colors = ["#0e9aa7", "#2b2b2b", "#d8542b", "#7a4fb8", "#4d8f2f", "#b8860b", "#b5536a", "#4a7fb0"]
    for k, p in enumerate(profiles):
        c = colors[k % len(colors)]; name = f"{p['platform']} {str(p['time'])[:10]}"
        for col, var in ((1, "temp"), (2, "psal")):
            if f"{var}_obs" in p:
                fig.add_trace(go.Scatter(x=p[f"{var}_obs"], y=p["z_obs"], mode="markers", marker=dict(size=4, color=c), name=name + (" Argo" if col == 1 else ""), showlegend=(col == 1)), row=1, col=col)
                fig.add_trace(go.Scatter(x=p[f"{var}_model"], y=p["z_obs"], mode="lines", line=dict(color=c, width=2), name=name + (" modelo" if lang == "es" else " model"), showlegend=(col == 1)), row=1, col=col)
    fig.update_yaxes(title_text="z (m)", row=1, col=1)
    fig.update_layout(height=520, margin=dict(l=40, r=20, t=40, b=30), legend=dict(orientation="h", y=-0.15))
    return fig


def runup_figure(rs: dict, lang: str = "es"):
    """Transectos del run-up: R2% por transecto (barras) y perfil del transecto con mayor nivel."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    trs = [r for r in rs.get("transects", []) if "r2" in r and r.get("r2") == r.get("r2")]
    fig = make_subplots(rows=1, cols=2, column_widths=[0.45, 0.55], subplot_titles=(("R2% por transecto" if lang == "es" else "R2% per transect"), ("Perfil del transecto más expuesto" if lang == "es" else "Most exposed transect profile")))
    if trs:
        fig.add_trace(go.Bar(x=[r["name"] for r in trs], y=[r["r2"] for r in trs], name="R2%", marker_color="#1fa2c4",
                             hovertext=[f"Hs {r['hs']:.2f} m · Tp {r['tp']:.1f} s · η {r['eta']:.2f} m · β {r['beta_f']:.3f}" for r in trs]), row=1, col=1)
        if any("stockdon" in r for r in trs):
            fig.add_trace(go.Scatter(x=[r["name"] for r in trs], y=[r["stockdon"]["r2"] for r in trs], mode="markers", name="Stockdon", marker=dict(color="#f4a261", size=7)), row=1, col=1)
        best = max(trs, key=lambda r: r.get("level", -9))
        pr = best.get("profile", {})
        if pr:
            fig.add_trace(go.Scatter(x=pr["s"], y=pr["z"], mode="lines", name=("fondo / terreno" if lang == "es" else "bed / ground"), line=dict(color="#6b4f2a", width=2), fill="tozeroy", fillcolor="rgba(160,120,70,0.3)"), row=1, col=2)
            fig.add_trace(go.Scatter(x=[pr["s"][0], pr["s"][-1]], y=[best["eta"], best["eta"]], mode="lines", name=("nivel (SCHISM)" if lang == "es" else "level (SCHISM)"), line=dict(color="#0b3d91", dash="dot")), row=1, col=2)
            fig.add_trace(go.Scatter(x=[pr["s"][0], pr["s"][-1]], y=[best["level"], best["level"]], mode="lines", name=f"{best['name']}: R2% {best['r2']:.2f} m", line=dict(color="#d8542b")), row=1, col=2)
    fig.update_yaxes(title_text="m", row=1, col=1); fig.update_xaxes(title_text="s (m)", row=1, col=2); fig.update_yaxes(title_text="z (m)", row=1, col=2)
    fig.update_layout(margin=dict(l=40, r=20, t=40, b=40), legend=dict(orientation="h"))
    return fig


def vgrid_figure(vg, hmax: float, lang: str = "es", npts: int = 200) -> go.Figure:
    """Malla vertical sobre un fondo que baja linealmente de ~0 a hmax: una línea por nivel (eta = 0)."""
    es = lang == "es"
    hmax = max(float(hmax), 5.0)
    h = np.linspace(min(1.0, hmax / 10), hmax, npts)
    z = vg.zcor(h)                                   # (npts, nvrt): nivel 0 = fondo
    x = np.linspace(0, 1, npts)
    fig = go.Figure()
    for k in range(vg.nvrt):
        zk = np.where(z[:, k] < -h + 1e-6, np.nan, z[:, k])
        fig.add_trace(go.Scatter(x=x, y=zk, mode="lines", line=dict(width=1, color="#1565c0"), hovertemplate=f"nivel {k + 1}: %{{y:.1f}} m<extra></extra>", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=-h, mode="lines", line=dict(width=2, color="#5d4037"), name="fondo" if es else "bottom", hoverinfo="skip"))
    if 0 < vg.h_c < hmax:
        fig.add_hline(y=-vg.h_c, line=dict(color="#e65100", dash="dot"), annotation_text=f"h_c = {vg.h_c:g} m", annotation_position="top left")
    if vg.kz > 1 and vg.h_s < hmax:
        fig.add_hline(y=-vg.h_s, line=dict(color="#6a1b9a", dash="dash"), annotation_text=f"h_s = {vg.h_s:g} m (sigma → z)", annotation_position="bottom left")
    ns = vg.nvrt - vg.kz + 1
    title = (f"{vg.nvrt} niveles ({ns} sigma" + (f" + {vg.kz - 1} z" if vg.kz > 1 else "") + f"), h_c = {vg.h_c:g} m, θ_f = {vg.theta_f:g}") if es else \
            (f"{vg.nvrt} levels ({ns} sigma" + (f" + {vg.kz - 1} z" if vg.kz > 1 else "") + f"), h_c = {vg.h_c:g} m, θ_f = {vg.theta_f:g}")
    fig.update_layout(title=title, margin=dict(l=40, r=10, t=50, b=40), height=420,
                      xaxis=dict(title=("fondo creciente (sin escala) →" if es else "increasing depth (no scale) →"), showticklabels=False),
                      yaxis=dict(title="z (m)"), legend=dict(orientation="h", y=1.02, x=1, xanchor="right"))
    return fig


# ----------------------------------------------------------------------------- flechas, secciones, Hovmöller, espectros
def arrows_trace(x, y, dx, dy, color="#222", width=1.0, head=0.3, name="", hover=None) -> go.Scatter:
    """Flechas como una sola traza de líneas (separadas por None): (x, y) origen y (dx, dy) en unidades de los ejes."""
    x, y, dx, dy = (np.asarray(a, float).ravel() for a in (x, y, dx, dy))
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(dx) & np.isfinite(dy) & ((dx != 0) | (dy != 0))
    x, y, dx, dy = x[ok], y[ok], dx[ok], dy[ok]
    xe, ye = x + dx, y + dy
    ang = np.arctan2(dy, dx); L = np.hypot(dx, dy) * head
    a1, a2 = ang + np.pi - 0.45, ang - np.pi + 0.45
    xs = np.column_stack([x, xe, xe + L * np.cos(a1), xe, xe + L * np.cos(a2), np.full_like(x, np.nan)]).ravel()
    ys = np.column_stack([y, ye, ye + L * np.sin(a1), ye, ye + L * np.sin(a2), np.full_like(y, np.nan)]).ravel()
    return go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=color, width=width), hoverinfo="skip", showlegend=bool(name), name=name)


def arrow_field(ds, var: str | None = None) -> str | None:
    """Campo vectorial de las flechas del mapa: la propia variable si es vectorial (windStress, depthAverageVel...);
    si no, la velocidad (horizontalVel o depthAverageVel). None si no hay ninguno."""
    if var and var + "X" in ds:
        return var
    return "horizontalVel" if "horizontalVelX" in ds else ("depthAverageVel" if "depthAverageVelX" in ds else None)


def arrow_units(name: str) -> str:
    return {"windStress": "m²/s²", "transport": "m²/s"}.get(name, "m/s")


def map_arrows(ds, it: int, layer: int = -1, n: int = 28, depth_m: float | None = None, vg=None, frac: float = 0.05,
               var: str | None = None, uv=None):
    """Traza de flechas submuestreada en una rejilla n×n sobre el mapa; devuelve (traza, módulo máximo). Las flechas son
    de `var` si es vectorial (ver arrow_field) o de la velocidad; `uv=(u, v)` da directamente las componentes nodales."""
    from scipy.spatial import cKDTree
    from ..analysis.sections import field_at_depth
    x, y = ds.x.values, ds.y.values
    name = arrow_field(ds, var) or "horizontalVel"
    if uv is not None:
        u, v = (np.asarray(a, float) for a in uv)
    elif depth_m is not None and "layer" in ds[name + "X"].dims:
        u = field_at_depth(ds, name + "X", it, depth_m, vg); v = field_at_depth(ds, name + "Y", it, depth_m, vg)
    else:
        u, v = ds[name + "X"].isel(time=it), ds[name + "Y"].isel(time=it)
        if "layer" in u.dims:
            u, v = u.isel(layer=layer), v.isel(layer=layer)
        u, v = u.values.astype(float), v.values.astype(float)
    u = np.where(u < -9000, np.nan, u); v = np.where(v < -9000, np.nan, v)      # niveles bajo el fondo (relleno de SCHISM)
    xi = np.linspace(x.min(), x.max(), n); yi = np.linspace(y.min(), y.max(), int(n * np.ptp(y) * _aspect(y) / max(np.ptp(x), 1e-12)) or 10)
    X, Y = np.meshgrid(xi, yi)
    tree = cKDTree(np.c_[x, y]); d, idx = tree.query(np.c_[X.ravel(), Y.ravel()])
    cell = max(np.ptp(x) / n, 1e-12)
    ok = d < 0.9 * cell
    U, V = u[idx], v[idx]
    vmax = float(np.nanmax(np.hypot(U[ok], V[ok]))) if ok.any() else 0.0
    if vmax <= 0:
        return arrows_trace([], [], [], []), 0.0
    L = frac * np.ptp(x) / vmax                                                 # m/s -> unidades del eje x
    asp = _aspect(y)
    dx = np.where(ok, U * L, np.nan); dy = np.where(ok, V * L / asp, np.nan)
    return arrows_trace(X.ravel(), Y.ravel(), dx, dy, color="#111", width=1), vmax


def section_ends(fig, sec, lang: str = "es", heatmap: bool = True):
    """Rotula los extremos de una sección (O/E, S/N... según su rumbo) y el eje «distancia (km) desde O»."""
    from ..analysis.sections import compass
    tx, ty = sec.tangent
    a, b = compass(-tx, -ty, lang), compass(tx, ty, lang)
    for x_, txt, anc in ((0.0, a, "left"), (1.0, b, "right")):
        fig.add_annotation(x=x_, y=1.0, xref="paper", yref="paper", text=f"<b>{txt}</b>", showarrow=False, xanchor=anc, yanchor="bottom",
                           font=dict(size=12, color="#555"))
    fig.update_xaxes(title_text=(f"distancia desde el extremo {a} (km)" if lang == "es" else f"distance from the {a} end (km)"))
    return fig


def section_line_figure(sec, y, ylabel: str, lang: str = "es", dark: bool = False, log: bool = False, ref: float = 0.0,
                        fit=None, integ=None, units: str = "", title: str | None = None):
    """Perfil de una variable 2D (o de una componente) a lo largo de la sección, con eje Y logarítmico opcional (de
    |y − ref|), ajuste lineal en un tramo (pendiente α y escala 1/α) e integral entre dos distancias. Devuelve
    (figura, lecturas: dict con fit, integral, unidades y cruces por cero)."""
    from ..analysis.profiles import line_fit, line_integral, zero_crossings
    y = np.asarray(y, float); d = np.asarray(sec.dist, float)
    info = dict(zeros=zero_crossings(d, y))
    yy = np.abs(y - ref) if log else y - ref
    fig = go.Figure(go.Scatter(x=d, y=yy, mode="lines", line=dict(width=2, color="#0e9aa7"), name=ylabel,
                               hovertemplate="%{x:.1f} km<br>%{y:.4g}<extra></extra>"))
    if fit is not None:
        r = line_fit(d, y, fit[0], fit[1], log=log, ref=ref)
        info["fit"] = r
        if r is not None:
            xs = np.linspace(r["x0_km"], r["x1_km"], 50)
            yl = r["alpha"] * xs * 1e3 + r["intercept"]
            fig.add_trace(go.Scatter(x=xs, y=np.exp(yl) if log else yl, mode="lines", line=dict(color="#d8542b", width=2, dash="dash"),
                                     name="ajuste" if lang == "es" else "fit", hoverinfo="skip"))
    if integ is not None:
        I = line_integral(d, y, integ[0], integ[1])
        info["integral"] = I; info["integral_units"] = (units + "·m").replace("m²/s·m", "m³/s") if units else "·m"
        if I is not None:
            a, b = min(integ), max(integ)
            fig.add_vrect(x0=a, x1=b, fillcolor="rgba(216,84,43,0.10)", line_width=0)
    if not log and np.nanmin(yy) < 0 < np.nanmax(yy):
        fig.add_hline(y=0, line=dict(color="#999", width=1))
    ytitle = (f"|{ylabel} − {ref:g}|" if ref else f"|{ylabel}|") if log else (f"{ylabel} − {ref:g}" if ref else ylabel)
    fig.update_layout(yaxis=dict(title=ytitle, type="log" if log else "linear"), showlegend=False, **layout(dark))
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=12)))
    return section_ends(fig, sec, lang), info


def section_figure2(sec, var: str, it: int, arrows: bool = True, contours: bool = True, wfactor: float = 200.0,
                    zrange=None, lang: str = "es", nx_arrows: int = 24, nz_arrows: int = 12, dark: bool = False, iso=None,
                    F=None, z=None, vel=None, clabel: str | None = None, cs: str | None = None, title: str | None = None) -> go.Figure:
    """Sección vertical de `var` con isolíneas y flechas (u_s, w·wfactor) a partir de un objeto Section.
    `iso=(variable, valor)` superpone la isosuperficie (p. ej. la isoterma de 15 °C) como línea gruesa: espesor h(x).
    F, z, vel: valores ya calculados (npts, nvrt) — media de una ventana, una componente o una variable derivada — y
    (u_s, w) de las flechas; sin ellos, los del instante `it`."""
    F = sec.scalar(var, it) if F is None else np.asarray(F, float)
    if F.ndim == 1:                                                    # variable 2D: nada que cortar en vertical
        fig = go.Figure(go.Scatter(x=sec.dist, y=F, mode="lines"))
        fig.update_layout(xaxis_title="distancia (km)" if lang == "es" else "distance (km)", yaxis_title=clabel or label(var, lang), **layout(dark))
        return section_ends(fig, sec, lang)
    z = sec.z(it) if z is None else z
    zi, Z = sec.regular(F, z)
    zmin, zmax = (zrange if zrange else (float(np.nanmin(Z)), float(np.nanmax(Z))))
    cs = cs or ("RdYlBu_r" if var == "temperature" else ("RdBu_r" if var in ("verticalVelocity",) else "Viridis"))
    fig = go.Figure(go.Heatmap(x=sec.dist, y=zi, z=Z, colorscale=cs, zmin=zmin, zmax=zmax, zsmooth="best",
                               colorbar=dict(title=clabel or label(var, lang), thickness=14, tickformat=".3g"),
                               hovertemplate="%{x:.1f} km<br>z %{y:.1f} m<br>%{z:.3f}<extra></extra>"))
    if contours and np.isfinite(Z).any() and zmax > zmin:
        fig.add_trace(go.Contour(x=sec.dist, y=zi, z=Z, showscale=False, contours=dict(coloring="none", start=zmin, end=zmax, size=(zmax - zmin) / 10),
                                 line=dict(color="rgba(0,0,0,0.45)", width=1), hoverinfo="skip", showlegend=False))
    if arrows:
        try:
            us, un, w = sec.velocity(it) if vel is None else (vel[0], None, vel[1])
            W = np.zeros_like(us) if w is None else w * wfactor
            zi2, US = sec.regular(us, z, nz=nz_arrows); _, WW = sec.regular(W, z, nz=nz_arrows)
            cols = np.linspace(0, sec.dist.size - 1, nx_arrows).astype(int)
            X, Y = np.meshgrid(sec.dist[cols], zi2); U, V = US[:, cols], WW[:, cols]
            vmax = float(np.nanmax(np.hypot(U, V))) or 1.0
            small = np.hypot(U, V) < 0.04 * vmax
            U = np.where(small, np.nan, U); V = np.where(small, np.nan, V)
            Lx = 0.05 * max(np.ptp(sec.dist), 1e-9); Lz = 0.08 * max(np.ptp(zi), 1e-9)
            fig.add_trace(arrows_trace(X, Y, U / vmax * Lx, V / vmax * Lz, color="#111"))
            fig.add_annotation(x=0.99, y=0.02, xref="paper", yref="paper", showarrow=False, xanchor="right",
                               text=(f"flechas: u‖ (máx {vmax:.2f} m/s), w×{wfactor:g}" if lang == "es" else f"arrows: u‖ (max {vmax:.2f} m/s), w×{wfactor:g}") if w is not None else
                                    (f"flechas: u‖ (máx {vmax:.2f} m/s)" if lang == "es" else f"arrows: u‖ (max {vmax:.2f} m/s)"),
                               font=dict(size=10, color="#333"), bgcolor="rgba(255,255,255,0.7)")
        except KeyError:
            pass
    # fondo: relleno gris solo por debajo del lecho (hasta el borde inferior del dibujo), nunca sobre el agua
    ymin = float(zi.min()) - 0.02 * max(np.ptp(zi), 1.0)
    fig.add_trace(go.Scatter(x=sec.dist, y=np.full(sec.dist.size, ymin), mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=sec.dist, y=-sec.depth, mode="lines", line=dict(color="#333", width=1.5), fill="tonexty", fillcolor="rgba(120,120,120,0.8)", hoverinfo="skip", showlegend=False))
    if iso is not None:
        ivar, ival = iso
        try:
            hz = sec.iso_depth(ivar, float(ival), it)
            nm = f"{label(ivar, lang).split(' (')[0]} = {float(ival):g}"
            fig.add_trace(go.Scatter(x=sec.dist, y=-hz, mode="lines", line=dict(color="#d81b60", width=3), name=nm,
                                     hovertemplate="%{x:.1f} km<br>" + nm + "<br>z %{y:.1f} m<extra></extra>", showlegend=False))
            fig.add_annotation(x=0.01, y=0.98, xref="paper", yref="paper", showarrow=False, xanchor="left", text=nm, font=dict(size=11, color="#d81b60"), bgcolor="rgba(255,255,255,0.7)")
        except (KeyError, ValueError):
            pass
    fig.update_layout(xaxis_title="distancia (km)" if lang == "es" else "distance (km)", yaxis=dict(title="z (m)", range=[ymin, float(zi.max())]), showlegend=False, **layout(dark))
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=12)))
    return section_ends(fig, sec, lang)


def iso_hovmoller_figure(sec, var: str, value: float, title: str, lang: str = "es", dark: bool = False) -> go.Figure:
    """h(x, t): profundidad (m) de la isosuperficie var = value a lo largo de la sección, distancia × tiempo."""
    H = sec.iso_hovmoller(var, float(value))
    # donde la isosuperficie no corta la columna (aflora o queda bajo el fondo) H es NaN: se pinta en gris, no como h = 0
    Z = np.where(np.isfinite(H), H, None).tolist()
    fig = go.Figure(go.Heatmap(x=sec.dist, y=sec.ds.time.values, z=Z, colorscale="deep", zsmooth=False, connectgaps=False,
                               colorbar=dict(title=title, thickness=14, tickformat=".3g"), hovertemplate="%{x:.1f} km<br>%{y}<br>%{z:.1f} m<extra></extra>"))
    lay = layout(dark); lay["plot_bgcolor"] = "#9e9e9e"
    fig.update_layout(xaxis_title="distancia (km)" if lang == "es" else "distance (km)", yaxis_title="tiempo" if lang == "es" else "time", **lay)
    if not np.isfinite(H).all():
        fig.add_annotation(x=0.5, y=-0.16, xref="paper", yref="paper", showarrow=False, font=dict(size=10, color="#555"),
                           text=("gris: la isosuperficie no corta la columna (aflora o queda bajo el fondo)" if lang == "es"
                                 else "grey: the isosurface does not cross the water column (outcrops or lies below the bottom)"))
    return section_ends(fig, sec, lang)


def hovmoller_figure(sec, var: str, layer: int = -1, lang: str = "es", dark: bool = False, H=None, clabel: str | None = None,
                     signed: bool = False) -> go.Figure:
    """Diagrama distancia–tiempo de `var` en la capa `layer`; H (tiempo, distancia) ya calculado para componentes,
    variables 2D o derivadas. signed: escala de colores centrada en 0."""
    H = sec.hovmoller(var, layer) if H is None else np.asarray(H, float)
    zr = {}
    if signed and np.isfinite(H).any():
        m = float(np.nanpercentile(np.abs(H), 99)); zr = dict(zmin=-m, zmax=m) if m > 0 else {}
    cs = "RdBu_r" if signed else ("RdYlBu_r" if var == "temperature" else "Viridis")
    fig = go.Figure(go.Heatmap(x=sec.dist, y=sec.ds.time.values, z=H, colorscale=cs, zsmooth="best", **zr,
                               colorbar=dict(title=clabel or label(var, lang), thickness=14, tickformat=".3g"), hovertemplate="%{x:.1f} km<br>%{y}<br>%{z:.4g}<extra></extra>"))
    fig.update_layout(xaxis_title="distancia (km)" if lang == "es" else "distance (km)", yaxis_title="tiempo" if lang == "es" else "time", **layout(dark))
    return section_ends(fig, sec, lang)


def _ref_lines(fig, refs: dict, xaxis_period: bool = True, xr: tuple | None = None):
    """Líneas de los periodos de referencia (inercial, mareas) en un eje x logarítmico. En Plotly las anotaciones de un
    eje log van en log10: con add_vline(annotation_text=...) la etiqueta de 12,4 h acababa en 10^12,4 h y el eje se
    estiraba hasta 10^24. Solo se dibujan las que caen dentro del rango `xr` (en h)."""
    for k, ph in refs.items():
        if not (ph and np.isfinite(ph) and ph > 0) or (xr and not (xr[0] <= ph <= xr[1])):
            continue
        fig.add_shape(type="line", xref="x", yref="paper", x0=ph, x1=ph, y0=0, y1=1, line=dict(color="#888", dash="dot", width=1))
        fig.add_annotation(x=float(np.log10(ph)), xref="x", y=1, yref="paper", yanchor="bottom", text=k, showarrow=False, font=dict(size=9))


def _log_range(v, pad: float = 0.05) -> list:
    """Rango de un eje log (en log10) ajustado a los valores positivos y finitos de `v`."""
    v = np.asarray(v, float); v = v[np.isfinite(v) & (v > 0)]
    if not v.size:
        return None
    lo, hi = np.log10(v.min()), np.log10(v.max())
    d = (hi - lo) * pad if hi > lo else 0.1
    return [float(lo - d), float(hi + d)]


def psd_figure(r: dict, refs: dict | None = None, name: str = "", lang: str = "es", resolvable=None, dark: bool = False) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r["period_h"], y=r["hi"], mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=r["period_h"], y=r["lo"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(14,154,167,0.15)", hoverinfo="skip", name="IC 95 %"))
    fig.add_trace(go.Scatter(x=r["period_h"], y=r["P"], mode="lines", line=dict(color="#0e9aa7", width=2), name=name or "PSD",
                             hovertemplate="T %{x:.2f} h<br>%{y:.3g}<extra></extra>"))
    xr = _log_range(r["period_h"])
    if refs:
        _ref_lines(fig, refs, xr=(10 ** xr[0], 10 ** xr[1]) if xr else None)
    if resolvable:
        fig.add_vrect(x0=resolvable[1] / 3600, x1=max(r["period_h"].max(), resolvable[1] / 3600 * 1.01), fillcolor="rgba(0,0,0,0.08)", line_width=0)
    fig.update_layout(xaxis=dict(title="periodo (h)" if lang == "es" else "period (h)", type="log", range=xr),
                      yaxis=dict(title="PSD (unidades²/cph)" if lang == "es" else "PSD (units²/cph)", type="log", range=_log_range(r["P"], 0.08)), **layout(dark))
    return fig


def rotary_figure(r: dict, refs: dict | None = None, lang: str = "es", dark: bool = False) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r["period_h"], y=r["cw"], mode="lines", name="horario (CW)" if lang == "es" else "clockwise (CW)", line=dict(color="#2b2b2b", width=2)))
    fig.add_trace(go.Scatter(x=r["period_h"], y=r["ccw"], mode="lines", name="antihorario (CCW)" if lang == "es" else "counter-clockwise (CCW)", line=dict(color="#0e9aa7", width=2)))
    xr = _log_range(r["period_h"])
    if refs:
        _ref_lines(fig, refs, xr=(10 ** xr[0], 10 ** xr[1]) if xr else None)
    fig.update_layout(xaxis=dict(title="periodo (h)" if lang == "es" else "period (h)", type="log", range=xr),
                      yaxis=dict(title="PSD (unidades²/cph)" if lang == "es" else "PSD (units²/cph)", type="log",
                                 range=_log_range(np.concatenate([np.ravel(r["cw"]), np.ravel(r["ccw"])]), 0.08)), **layout(dark))
    return fig


def wavelet_figure(w: dict, t0=None, refs: dict | None = None, lang: str = "es", dark: bool = False, global_name: str = "global") -> go.Figure:
    """Escalograma (periodo en h, escala log) con cono de influencia sombreado, contorno de significación 95 % y
    espectro global a la derecha."""
    from plotly.subplots import make_subplots
    ph = w["period"] / 3600
    tt = (np.datetime64(t0) + (w["t"] * 1e9).astype("timedelta64[ns]")) if t0 is not None else w["t"] / 3600
    fig = make_subplots(rows=1, cols=2, column_widths=[0.78, 0.22], shared_yaxes=True, horizontal_spacing=0.03)
    P = np.log2(np.maximum(w["power"], 1e-30))
    fig.add_trace(go.Heatmap(x=tt, y=ph, z=P, colorscale="Viridis", colorbar=dict(title="log₂ P", thickness=12, x=1.02, len=0.9),
                             hovertemplate="%{x}<br>T %{y:.2f} h<br>log2 P %{z:.2f}<extra></extra>"), row=1, col=1)
    ratio = w["power"] / w["signif"][:, None]
    fig.add_trace(go.Contour(x=tt, y=ph, z=ratio, showscale=False, contours=dict(coloring="none", start=1, end=1, size=1),
                             line=dict(color="#fff", width=1.5), hoverinfo="skip"), row=1, col=1)
    coi = np.maximum(w["coi"] / 3600, ph.min())
    fig.add_trace(go.Scatter(x=np.concatenate([tt, tt[::-1]]), y=np.concatenate([coi, np.full(coi.size, ph.max())]),
                             fill="toself", fillcolor="rgba(255,255,255,0.45)", line=dict(color="rgba(255,255,255,0.8)", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=w["glob"], y=ph, mode="lines", line=dict(color="#0e9aa7", width=2), name=global_name, showlegend=False,
                             hovertemplate="T %{y:.2f} h<br>P %{x:.3g}<extra>" + global_name + "</extra>"), row=1, col=2)
    fig.add_trace(go.Scatter(x=w["glob_signif"], y=ph, mode="lines", line=dict(color="#888", dash="dash"), name="95 %", showlegend=False), row=1, col=2)
    yr = _log_range(ph, 0.0)
    if refs:                                               # en eje log las anotaciones van en log10 (ver _ref_lines)
        for k, p in refs.items():
            if not (p and np.isfinite(p) and ph.min() <= p <= ph.max()):
                continue
            fig.add_shape(type="line", xref="x domain", yref="y", x0=0, x1=1, y0=p, y1=p, line=dict(color="#fff", dash="dot", width=1))
            fig.add_annotation(x=1, xref="x domain", y=float(np.log10(p)), yref="y", xanchor="left", text=k, showarrow=False, font=dict(size=9))
    fig.update_yaxes(type="log", title_text="periodo (h)" if lang == "es" else "period (h)", range=yr, row=1, col=1)
    fig.update_yaxes(type="log", range=yr, row=1, col=2)
    gl = np.concatenate([np.ravel(w["glob"]), np.ravel(w["glob_signif"])])
    fig.update_xaxes(type="log", title_text="P global", range=_log_range(gl, 0.08), row=1, col=2)
    fig.update_layout(**{**layout(dark), "margin": dict(l=40, r=70, t=40, b=40), "showlegend": False})
    return fig


# ----------------------------------------------------------------------------- contexto geográfico: tierra (GSHHG) y contornos
_LAND_CACHE: dict = {}


_MESH_CACHE: dict = {}


def cached_mesh(path):
    """read_gr3 con caché por (ruta, fecha, tamaño): una malla grande tarda segundos en leerse y las páginas la releen."""
    from ..io.gr3 import read_gr3
    p = Path(path); st = p.stat(); key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _MESH_CACHE:
        _MESH_CACHE.clear(); _MESH_CACHE[key] = read_gr3(p)
    return _MESH_CACHE[key]


def land_polygons(lon, lat, pad: float = 0.05) -> list:
    """Polígonos de tierra GSHHG (costa de alta resolución) en la caja [lon] x [lat] con margen, como listas de
    (x, y) de cada anillo (exterior e interiores separados por NaN). Vacío si no hay datos o no hay red."""
    key = (round(float(lon[0]) - pad, 3), round(float(lon[1]) + pad, 3), round(float(lat[0]) - pad, 3), round(float(lat[1]) + pad, 3))
    if key in _LAND_CACHE:
        return _LAND_CACHE[key]
    out = []
    try:
        import geopandas as gpd, shapely
        from ..edition import pro as _pro
        _pro_mesh_coastline = _pro("mesh.coastline")
        OSM_LAND_SHP = _pro_mesh_coastline.OSM_LAND_SHP
        if OSM_LAND_SHP.exists():                                 # costa OSM global (mejor detalle, sin red)
            shp = OSM_LAND_SHP
        else:
            from ..edition import pro as _pro
            _pro_mesh_oceanmesh2d = _pro("mesh.oceanmesh2d")
            ensure_gshhg = _pro_mesh_oceanmesh2d.ensure_gshhg
            shp = ensure_gshhg("f").with_suffix(".shp")
        land = gpd.read_file(shp, bbox=(key[0], key[2], key[1], key[3]))
        clip = shapely.box(key[0], key[2], key[1], key[3])
        # la costa OSM tiene millones de puntos en un dominio grande: se simplifica a ~1/3000 del ancho de la caja
        # (un Mediterráneo de 22° -> ~800 m; una cala de 0.2° -> ~7 m) y se descartan los islotes menores que eso
        tol = max(key[1] - key[0], key[3] - key[2]) / 3000.0
        for g in land.geometry:
            if g is None:
                continue
            g = shapely.make_valid(g).intersection(clip)
            if tol > 1e-5:
                g = shapely.simplify(g, tol, preserve_topology=True)
            for poly in shapely.get_parts(g):
                if poly.geom_type != "Polygon" or poly.is_empty or poly.area < (4 * tol) ** 2:
                    continue
                xs, ys = [], []
                for ring in [poly.exterior, *poly.interiors]:
                    cx, cy = np.asarray(ring.coords).T
                    xs += [*cx, np.nan]; ys += [*cy, np.nan]
                out.append((np.array(xs), np.array(ys)))
    except Exception as ex:   # noqa: BLE001  (sin GSHHG, sin red, sin geopandas)
        import logging
        logging.getLogger(__name__).warning("sin línea de costa para el mapa: %s", ex)
    _LAND_CACHE[key] = out
    return out


def land_traces(polys: list, fill: str = "rgba(222,222,215,0.95)", line: str = "#6d6d6d") -> list:
    """Trazas Plotly de tierra (relleno + costa) para superponer a un mapa de calor."""
    return [go.Scatter(x=x, y=y, mode="lines", fill="toself", fillcolor=fill, line=dict(color=line, width=1),
                       hoverinfo="skip", showlegend=False) for x, y in polys]


def boundary_traces(mesh) -> list:
    """Contornos de la malla: abiertos en rojo, tierra exterior en negro, islas en gris."""
    tr = []
    for b in getattr(mesh, "open_boundaries", []):
        tr.append(go.Scatter(x=mesh.x[b], y=mesh.y[b], mode="lines", line=dict(color="#d8542b", width=2.5), hoverinfo="skip", showlegend=False))
    for b, f in getattr(mesh, "land_boundaries", []):
        tr.append(go.Scatter(x=mesh.x[b], y=mesh.y[b], mode="lines", line=dict(color="#222" if f == 0 else "#777", width=1), hoverinfo="skip", showlegend=False))
    return tr
