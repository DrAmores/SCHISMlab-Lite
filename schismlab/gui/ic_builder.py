"""Constructor interactivo de condiciones iniciales (página Modelo): una fila por variable (elevación, T, S, u, v)
con una receta (constante, frente, dos capas, gaussiana, gradiente o expresión libre) y una previsualización en
planta y en sección sobre la malla del caso. Guarda en el YAML la expresión resultante y la receta."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from nicegui import ui
from ..initial import (VARIABLES, recipe_expression, recipe_matches, recipe_from_value, recipe_uses_z, density,
                       domain_frame, domain_extent, evaluate_field)
from ..expressions import is_expression
from .figures import LAYOUT, layout as _layout, NodeSampler as _Sampler


_MODE_FIELDS = {
    "constant": ("value",),
    "front": ("v1", "v2", "axis", "pos", "width_km"),
    "layers": ("v_top", "v_bot", "depth", "slope_m", "axis", "pos", "width_km"),
    "toplayer": ("v1", "v2", "v_bot", "depth", "axis", "pos", "width_km"),
    "gauss": ("base", "amp", "cx", "cy", "radius_km", "gdepth"),
    "gradient": ("v1", "v2", "axis"),
    "expr": ("expression",),
}
_DEFAULTS = {"elevation": 0.0, "temperature": 20.0, "salinity": 36.0, "u": 0.0, "v": 0.0}
_UNITS = {"elevation": "m", "temperature": "°C", "salinity": "psu", "u": "m/s", "v": "m/s"}


def preview_mesh(c: dict, wd: Path):
    """Malla para previsualizar: la del caso si existe; si no, un rectángulo grueso del dominio idealizado; o None."""
    from .figures import cached_mesh
    hg = wd / "hgrid.gr3"
    if hg.exists():
        try:
            return cached_mesh(hg)
        except Exception:
            pass
    mc = c.get("mesh", {}) or {}
    if mc.get("generator") == "idealized":
        from ..mesh.idealized import rectangular_basin
        b = mc.get("bathymetry", 50); h = float(b) if isinstance(b, (int, float)) else 50.0
        if "lon" in mc and "lat" in mc:
            lon, lat = [float(v) for v in mc["lon"]], [float(v) for v in mc["lat"]]
            L = max(111.2e3 * (lat[1] - lat[0]), 111.2e3 * (lon[1] - lon[0]) * np.cos(np.deg2rad(np.mean(lat))))
            return rectangular_basin(0, 0, max(float(mc.get("dx", 2000)), L / 60), depth=h, lon=tuple(lon), lat=tuple(lat))
        Lx, Ly = float(mc.get("Lx", 100e3)), float(mc.get("Ly", 50e3))
        return rectangular_basin(Lx, Ly, max(float(mc.get("dx", 2000)), max(Lx, Ly) / 60), depth=h)
    return None


class _VarRow:
    """Controles de una variable: modo + parámetros (se muestran los del modo elegido)."""

    def __init__(self, var: str, recipe: dict, t: dict, on_change):
        self.var, self.t, self.on_change = var, t, on_change
        self.w: dict = {}
        with ui.row().classes("q-gutter-sm items-center w-full"):
            ui.label(t["icv_" + var]).classes("text-weight-medium").style("width:110px")
            self.mode = ui.select({m: t["icm_" + m] for m in _MODE_FIELDS}, value=recipe.get("mode", "constant"), label=t["ic_mode"]).classes("w-44")
            n = lambda key, dflt, **kw: ui.number(t["icp_" + key], value=float(recipe.get(key, dflt)), **kw).props("dense").classes("w-28")
            d = _DEFAULTS[var]
            self.w["value"] = n("value", recipe.get("value", d))
            self.w["v1"] = n("v1", d); self.w["v2"] = n("v2", d)
            self.w["v_top"] = n("v_top", d); self.w["v_bot"] = n("v_bot", d)
            self.w["base"] = n("base", d); self.w["amp"] = n("amp", 1.0)
            self.w["axis"] = ui.select({"x": t["icp_axis_x"], "y": t["icp_axis_y"]}, value=recipe.get("axis", "x"), label=t["icp_axis"]).props("dense").classes("w-36")
            self.w["pos"] = n("pos", 0.5, min=0, max=1, step=0.05); self.w["width_km"] = n("width_km", 10.0, min=0.01)
            self.w["cx"] = n("cx", 0.5, min=0, max=1, step=0.05); self.w["cy"] = n("cy", 0.5, min=0, max=1, step=0.05)
            self.w["radius_km"] = n("radius_km", 20.0, min=0.01)
            self.w["depth"] = n("depth", 50.0, min=0)
            self.w["gdepth"] = ui.number(t["icp_gdepth"], value=float(recipe.get("depth", 0.0)) if recipe.get("mode") == "gauss" else 0.0, min=0).props("dense").classes("w-28")
            self.w["slope_m"] = n("slope_m", 0.0)
            self.w["expression"] = ui.input(t["icp_expression"], value=str(recipe.get("expression", ""))).props("dense").classes("w-96")
            self.out = ui.label().classes("text-caption text-grey-7")
        self.mode.on_value_change(lambda e: self._changed())
        for w in self.w.values():
            w.on_value_change(lambda e: self._changed())
        self._vis()

    def _vis(self):
        shown = _MODE_FIELDS[self.mode.value]
        for k, w in self.w.items():
            w.set_visibility(k in shown)

    def _changed(self):
        self._vis(); self.on_change()

    def recipe(self) -> dict:
        r = {"mode": self.mode.value}
        for k in _MODE_FIELDS[self.mode.value]:
            v = self.w[k].value
            r["depth" if k == "gdepth" else k] = v if k in ("axis", "expression") else float(v if v is not None else 0.0)
        return r

    def set_position(self, fx: float, fy: float):
        """Clic en el mapa: posición del frente/interfaz o centro de la gaussiana."""
        m = self.mode.value
        if m in ("front", "layers", "toplayer"):
            self.w["pos"].set_value(round(fx if self.w["axis"].value == "x" else fy, 3))
        elif m == "gauss":
            self.w["cx"].set_value(round(fx, 3)); self.w["cy"].set_value(round(fy, 3))


def _section(frame: dict, depth: np.ndarray, vg, axis: str, npts: int = 120, tree=None):
    """Puntos de una sección por el centro del dominio a lo largo del eje: (s, marco, profundidad, z)."""
    from scipy.spatial import cKDTree
    x, y = frame["x"], frame["y"]
    if axis == "x":
        s = np.linspace(x.min(), x.max(), npts); px, py = s, np.full(npts, 0.5 * (y.min() + y.max()))
    else:
        s = np.linspace(y.min(), y.max(), npts); px, py = np.full(npts, 0.5 * (x.min() + x.max())), s
    idx = (tree or cKDTree(np.c_[x, y])).query(np.c_[px, py])[1]
    fr = {k: a[idx] for k, a in frame.items()}
    fr["x"], fr["y"] = px, py
    h = depth[idx]
    return s, fr, h, vg.zcor(h)


def section_figure(frame: dict, depth: np.ndarray, vg, fields: dict, axis: str, label: str, lang: str, tree=None, dark: bool = False) -> go.Figure:
    """Sección vertical: `fields` es {"value": expr} o {"T": expr, "S": expr} (densidad)."""
    s, fr, h, z = _section(frame, depth, vg, axis, tree=tree)
    if "T" in fields:
        f = density(evaluate_field(fields["T"], fr, h, z), evaluate_field(fields["S"], fr, h, z))
    else:
        f = evaluate_field(fields["value"], fr, h, z)
    zi = np.linspace(-float(h.max()), 0.0, 80)
    Z = np.full((zi.size, s.size), np.nan)
    for i in range(s.size):
        Z[:, i] = np.interp(zi, z[i], f[i], left=np.nan, right=np.nan)
    fig = go.Figure(go.Heatmap(x=s / 1e3, y=zi, z=Z, colorscale="Viridis", colorbar=dict(title=label, thickness=14, tickformat=".3g"),
                               hovertemplate="%{x:.1f} km<br>z %{y:.1f} m<br>%{z:.3f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=s / 1e3, y=-h, mode="lines", line=dict(color="#5d4037", width=2), hoverinfo="skip", showlegend=False))
    dirn = ("O→E" if axis == "x" else "S→N") if lang == "es" else ("W→E" if axis == "x" else "S→N")
    fig.update_layout(xaxis=dict(title=("distancia (km) " if lang == "es" else "distance (km) ") + dirn), yaxis=dict(title="z (m)"), **_layout(dark))
    return fig


def ic_builder(c: dict, wd: Path, t: dict, lang: str, get_vgrid, is_baroclinic, is_3d, dark: bool = False):
    """Construye los controles y devuelve (collect, refresh): collect() -> dict para c["initial"] (sin `source`)."""
    ic = c.get("initial", {}) or {}
    mesh = preview_mesh(c, wd)
    frame = domain_frame(mesh, c) if mesh is not None else None
    Lx, Ly = domain_extent(frame) if frame is not None else (100e3, 50e3)
    saved = ic.get("recipe") or {}
    vel = ic.get("velocity") or {}
    current = {"elevation": ic.get("elevation", 0.0), "temperature": ic.get("temperature", 20.0), "salinity": ic.get("salinity", 36.0),
               "u": vel.get("u", 0.0), "v": vel.get("v", 0.0)}

    def initial_recipe(var):
        r = saved.get(var)
        return r if r and recipe_matches(r, current[var], Lx, Ly) else recipe_from_value(current[var])

    rows: dict[str, _VarRow] = {}
    state = {"ready": False, "pending": False}
    def schedule():                    # retardo: una sola actualización tras dejar de teclear
        if not state["pending"]:
            state["pending"] = True
            ui.timer(0.4, lambda: (state.update(pending=False), refresh()), once=True)
    warn = ui.label(t["ic_warn_tracers"]).classes("text-caption text-orange-9")
    info_v = ui.label(t["ic_info_vel"]).classes("text-caption text-grey-7")
    with ui.column().classes("w-full q-gutter-xs"):
        for var in VARIABLES:
            rows[var] = _VarRow(var, initial_recipe(var), t, schedule)
    with ui.row().classes("items-center q-gutter-md"):
        pv = ui.select({**{v: t["icv_" + v] for v in VARIABLES}, "density": t["icv_density"]}, value="temperature", label=t["ic_preview"]).classes("w-44")
        ui.label(t["ic_click_hint"]).classes("text-caption text-grey-7")
    plan = sect = None
    if mesh is None:
        ui.label(t["ic_no_mesh"]).classes("text-caption text-orange-9")
    else:
        with ui.row().classes("w-full"):
            plan = ui.plotly(go.Figure()).classes("col-6").style("height:360px")
            sect = ui.plotly(go.Figure()).classes("col-6").style("height:360px")
    geo = frame is not None and frame["x"] is not mesh.x
    sampler = _Sampler(mesh) if mesh is not None else None
    frame_tree = None
    if frame is not None:
        from scipy.spatial import cKDTree
        frame_tree = cKDTree(np.c_[frame["x"], frame["y"]])

    def values():
        return {var: recipe_expression(rows[var].recipe(), Lx, Ly) for var in VARIABLES}

    def refresh():
        if not state["ready"]:
            return
        for var in VARIABLES:                                           # expresión vacía: aviso propio, sin evaluar
            if rows[var].mode.value == "expr" and not str(rows[var].w["expression"].value or "").strip():
                rows[var].out.set_text(t["ic_expr_empty"]); return
        vals = values()
        for var in VARIABLES:
            v = vals[var]; rows[var].out.set_text(v if is_expression(v) else f"{v:g} {_UNITS[var]}")
        nonconst = any(is_expression(vals[k]) for k in ("temperature", "salinity"))
        warn.set_visibility(nonconst and not (is_baroclinic() and is_3d()))
        info_v.set_visibility(any(is_expression(vals[k]) or float(vals[k]) != 0.0 for k in ("u", "v")))
        if mesh is None:
            return
        try:
            vg = get_vgrid()
            sel = pv.value
            keys = ("temperature", "salinity") if sel == "density" else (sel,)
            uses_z = any(recipe_uses_z(rows[k].recipe()) for k in keys)
            zsurf = np.zeros((mesh.nnodes, 1))
            surf = {k: evaluate_field(vals[k], frame, mesh.depth, zsurf)[:, 0] for k in keys}
            if sel == "density":
                f = density(surf["temperature"], surf["salinity"]); label = "ρ (kg/m³)"
            else:
                f = surf[sel]; label = t["icv_" + sel]                       # la etiqueta ya lleva la unidad
            Z = sampler.grid(f)
            fig = go.Figure(go.Heatmap(x=sampler.xi, y=sampler.yi, z=Z, colorscale="Viridis", zsmooth="best", colorbar=dict(title=label, thickness=14, tickformat=".3g"),
                                       hovertemplate="%{x:.3f}, %{y:.3f}<br>%{z:.3f}<extra></extra>"))
            fig.update_layout(title=t["ic_surface"], xaxis=dict(title="lon" if geo else "x (m)"), yaxis=dict(title="lat" if geo else "y (m)"), **_layout(dark))
            plan.update_figure(fig)
            if uses_z and vg.nvrt > 2:
                r = rows[keys[0]].recipe()
                axis = r.get("axis", "x") if r.get("mode") in ("front", "layers", "toplayer", "gradient") else "x"
                fields = {"T": vals["temperature"], "S": vals["salinity"]} if sel == "density" else {"value": vals[sel]}
                sect.update_figure(section_figure(frame, mesh.depth, vg, fields, axis, label, lang, tree=frame_tree, dark=dark))
                sect.set_visibility(True)
            else:
                sect.set_visibility(False)
        except Exception as ex:   # expresión incompleta mientras se escribe
            ui.notify(f"{t['ic_preview']}: {ex}", type="warning", timeout=2500)

    def on_click(e):
        pts = e.args.get("points", [])
        if not pts or mesh is None or pv.value == "density":
            return
        px, py = float(pts[0]["x"]), float(pts[0]["y"])
        fx = (px - mesh.x.min()) / max(np.ptp(mesh.x), 1e-9); fy = (py - mesh.y.min()) / max(np.ptp(mesh.y), 1e-9)
        rows[pv.value].set_position(float(np.clip(fx, 0, 1)), float(np.clip(fy, 0, 1)))
        refresh()
    if plan is not None:
        plan.on("plotly_click", on_click, js_handler="(e) => emit({points: (e.points || []).map(p => ({x: p.x, y: p.y}))})")
    pv.on_value_change(lambda e: refresh())
    state["ready"] = True
    refresh()

    def collect() -> dict:
        vals = values()
        out = {"elevation": vals["elevation"], "temperature": vals["temperature"], "salinity": vals["salinity"],
               "recipe": {var: rows[var].recipe() for var in VARIABLES}}
        if any(is_expression(vals[k]) or float(vals[k]) != 0.0 for k in ("u", "v")):
            out["velocity"] = {"u": vals["u"], "v": vals["v"]}
        return out
    return collect, refresh
