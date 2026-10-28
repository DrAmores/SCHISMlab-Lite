"""SCHISMlab: interfaz web (NiceGUI). Lanzar con `schismlab gui` o `python -m schismlab.gui.app`."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
import numpy as np
import yaml
from nicegui import app, run, ui
from .i18n import TEXT, TEXT_LITE
from .state import HOME, REPO, CaseInfo, gallery, load_cfg, save_cfg, new_case, copy_case, delete_case, run_progress, PRACTICAS

from ..edition import is_pro, edition, edition_name, default_generator
from .brand import COLORS as BRAND, FONTS_LINK as BRAND_FONTS, FAVICON as BRAND_FAVICON, symbol_svg as brand_symbol, edition_badge
LOGO = brand_symbol(34)   # cabecera: símbolo de la marca (schismlab/gui/brand)
# flujo del caso: 6 pasos (Inicio e Instalación van en la cabecera, fuera del flujo)
STEPS = [("mesh", "/mesh", "grid_on"), ("model", "/model", "tune"), ("forcing", "/forcing", "air"), ("outputs", "/outputs", "save"),
         ("params", "/params", "list_alt"), ("run", "/run", "play_circle"), ("results", "/results", "insights")]


def steps() -> list:
    """Pasos del panel lateral; en Pro, «Simulaciones» (proyectos con varias simulaciones) antes de Ejecutar."""
    return STEPS[:5] + [("runs", "/runs", "account_tree")] + STEPS[5:] if is_pro() else STEPS


def next_step(step: str) -> str | None:
    st = steps(); keys = [k for k, _, _ in st]
    return st[keys.index(step) + 1][1] if step in keys and keys.index(step) + 1 < len(keys) else None


def case_summary(c: dict, t: dict) -> list[tuple[str, str]]:
    """Lineas del resumen del caso para la barra lateral."""
    from ..build import effective_build
    m = c.get("mesh", {}) or {}
    if "lon" in m and "lat" in m:
        dom = f"{m['lon'][0]}–{m['lon'][1]}°E, {m['lat'][0]}–{m['lat'][1]}°N"
    elif m.get("generator") == "idealized":
        dom = f"{m.get('Lx', '?')} × {m.get('Ly', '?')} m"
    elif m.get("polygon"):
        xs = [p[0] for p in m["polygon"]]; ys = [p[1] for p in m["polygon"]]
        dom = f"{min(xs):.1f}–{max(xs):.1f}°E, {min(ys):.1f}–{max(ys):.1f}°N"
    else:
        dom = "?"
    tm = c.get("time", {}) or {}
    try:
        lang = S().get("lang", "es")
    except Exception:   # noqa: BLE001  (fuera de una página)
        lang = "es"
    dur = f"{fmt_num(tm.get('days', '?'), lang, 1) if tm.get('days') is not None else '?'} d · dt {fmt_num(tm.get('dt', '?'), lang) if tm.get('dt') is not None else '?'} s · {str(tm.get('start', ''))[:10]}"
    vert = (c.get("vertical") or {}).get("type", "2d")
    try:
        name, mods, built = effective_build(c); bld = f"pschism_{name}" + ("" if built else f" ({t['not_compiled']})")
    except Exception:   # noqa: BLE001
        bld = "?"
    f = c.get("forcing", {}) or {}; b = c.get("boundaries", {}) or {}
    forc = []
    if f.get("atmosphere"): forc.append("ERA5")
    elif f.get("wind"): forc.append(t["w_stress"] if f["wind"].get("stress") is not None else t["w_uniform"] if not any(isinstance(f["wind"].get(k), str) for k in ("u", "v")) else t["w_expr"])
    if isinstance(b.get("elevation"), dict):
        ev = b["elevation"]; forc.append(t["bc_tsunami"] if "tsunami" in ev else t["bc_series"] if "series" in ev else t["bc_tides_s"])
    if b.get("source"): forc.append(t["bc_nest_s"] if (b["source"] or {}).get("name") == "schismlab" else "Copernicus")
    if (c.get("waves") or {}).get("enabled"): forc.append("WWM")
    if f.get("rivers"): forc.append(f"{len(f['rivers'])} " + t["rivers"].lower())
    if (c.get("mesh", {}) or {}).get("inundation"): forc.append(t["impacts"].lower())
    return [(t["domain_s"], dom), (t["duration_s"], dur + f" · {vert}"), (t["build_s"], bld), (t["forcings_s"], ", ".join(forc) or "—")]
_DS_CACHE: dict = {}


# ----------------------------------------------------------------------------- estado por usuario
def S():
    return app.storage.user


def T():
    lang = S().get("lang", "es")
    return TEXT[lang] if is_pro() else {**TEXT[lang], **TEXT_LITE[lang]}   # Lite: textos sin funciones de Pro


def case_path() -> Path | None:
    p = S().get("case")
    return Path(p) if p and Path(p).exists() else None


def case_info() -> CaseInfo | None:
    p = case_path()
    if not p:
        return None
    return next((c for c in gallery() if c.path == p), CaseInfo(p, p.stem, p.stem, "mine"))


def workdir() -> Path:
    """Carpeta del caso (en un proyecto, la del caso base: malla y páginas de edición)."""
    from ..case import Case
    return Case(case_path()).workdir


def active_member() -> str | None:
    """Simulación del proyecto elegida en la cabecera (Pro); None = el caso base."""
    if not is_pro():
        return None
    p = case_path()
    name = (S().get("members") or {}).get(str(p)) if p else None
    if not name:
        return None
    try:
        c = load_cfg(p)
        if c.get("runs"):
            from ..edition import pro as _pro
            if name in {m.name for m in _pro("runs.members").expand(c)}:
                return name
    except Exception:   # noqa: BLE001
        pass
    return None


def set_member(name: str | None) -> None:
    d = dict(S().get("members") or {}); d[str(case_path())] = name or None; S().update(members=d)


def run_workdir() -> Path:
    """Carpeta que se ejecuta y se ve en Resultados: la de la simulación elegida o la del caso."""
    m = active_member()
    return workdir() / "runs" / m if m else workdir()


def cfg_run() -> dict:
    """Configuración de lo que se ejecuta: la resuelta de la simulación elegida o la del caso."""
    m = active_member()
    if not m:
        return cfg()
    from ..case import Case
    from ..edition import pro as _pro
    return _pro("runs.project").member_case(Case(case_path()), m).cfg


def cfg() -> dict:
    return load_cfg(case_path())


def yaml_error(path: Path | None) -> str | None:
    """Mensaje «YAML inválido: línea N» si el fichero del caso no se puede leer; None si está bien."""
    if path is None:
        return None
    try:
        load_cfg(path)
    except yaml.YAMLError as ex:
        mark = getattr(ex, "problem_mark", None)
        return T()["yaml_invalid"].format(line=(mark.line + 1) if mark is not None else "?")
    except OSError as ex:
        return str(ex)
    return None


def safe_select(options, value, default, *, multiple: bool = False, keep_unknown: bool = False, label: str = ""):
    """Valor seguro para un ui.select: `value` si está entre las opciones y, si no, `default` (con aviso).

    `options` es la lista o el dict de opciones del select. Con `multiple`, filtra la lista de valores (constituyentes en
    minúsculas → mayúsculas) y devuelve `default` si no queda ninguno. Con `keep_unknown`, un valor desconocido se
    añade a `options` (dict) como opción propia para no perderlo al guardar (p. ej. un cierre turbulento no listado).
    NiceGUI lanza ValueError('Invalid value') al construir la página si el valor no está en las opciones (error 500)."""
    keys = list(options.keys()) if isinstance(options, dict) else list(options)
    if multiple:
        vals = [v for v in (value if isinstance(value, (list, tuple)) else ([value] if value else []))]
        up = {str(k).upper(): k for k in keys}
        out = [up[str(v).upper()] for v in vals if str(v).upper() in up]
        return out or list(default)
    if value is not None and value is not False and value in keys:
        return value
    if keep_unknown and value not in (None, False, "") and isinstance(options, dict):
        options[value] = str(value); return value
    if value not in (None, False, ""):
        try:
            ui.notify(T()["select_fallback"].format(value=value, label=label, default=options.get(default, default) if isinstance(options, dict) else default), type="warning", timeout=6000)
        except Exception:   # noqa: BLE001  (fuera de una página)
            pass
    return default


def save(c: dict):
    save_cfg(case_path(), c); ui.notify(T()["saved"], type="positive")


# ----------------------------------------------------------------------------- tareas largas con registro
class Job:
    def __init__(self):
        self.lines: list[str] = []; self.done = False; self.error: str | None = None; self.result = None


class _ListHandler(logging.Handler):
    def __init__(self, lines): super().__init__(); self.lines = lines
    def emit(self, record): self.lines.append(self.format(record))


_JOBS: dict[str, "Job"] = {}          # trabajos en marcha por directorio del caso: la página Ejecutar los recupera al volver


async def run_job(fn, log_el: ui.log, on_done=None, progress: ui.linear_progress | None = None, wd: Path | None = None, key: str | None = None):
    job = Job(); h = _ListHandler(job.lines); h.setFormatter(logging.Formatter("%(message)s"))
    if key:
        _JOBS[key] = job
    root = logging.getLogger(); root.setLevel(logging.INFO); root.addHandler(h)
    for noisy in ("ocsmesh", "rasterio", "fiona", "matplotlib", "cdsapi", "urllib3", "copernicusmarine", "paramiko", "pyTMD", "numba"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    shown = 0; t_start = time.time(); last_change = {"t": t_start, "beat": t_start}

    def poll():
        nonlocal shown
        if len(job.lines) > shown:
            last_change["t"] = time.time()
        for line in job.lines[shown:]:
            log_el.push(line)
        shown = len(job.lines)
        now = time.time()
        if now - last_change["t"] >= 10 and now - last_change["beat"] >= 10:      # sin novedades: decir que sigue trabajando
            last_change["beat"] = now
            last = next((l for l in reversed(job.lines) if l.strip() and not l.startswith("…")), "")
            beat = T()["still_working"].format(s=int(now - t_start), last=last[-90:])
            job.lines.append(beat); log_el.push(beat); shown = len(job.lines)
        if progress is not None and wd is not None:
            step, total = run_progress(wd); progress.value = step / total
    timer = ui.timer(0.7, poll)
    try:
        job.result = await run.io_bound(fn)
    except Exception as ex:                     # noqa: BLE001
        job.error = f"{type(ex).__name__}: {ex}"; log_el.push("ERROR " + job.error); ui.notify(T()["failed"], type="negative")
    finally:
        root.removeHandler(h); timer.active = False; poll(); job.done = True
    if job.error is None and on_done:
        on_done(job.result)
    return job


def _child_main(q, target: str, args: tuple):
    """Proceso hijo: ejecuta `modulo:funcion(*args)` enviando su registro a la cola (para tareas que se puedan detener)."""
    import importlib, logging as _lg, traceback
    from logging.handlers import QueueHandler
    root = _lg.getLogger(); root.handlers.clear(); root.setLevel(_lg.INFO); root.addHandler(QueueHandler(q))
    for noisy in ("ocsmesh", "rasterio", "fiona", "matplotlib", "urllib3", "numba", "shapely", "pyproj"):
        _lg.getLogger(noisy).setLevel(_lg.WARNING)
    try:
        mod, fn = target.split(":")
        getattr(importlib.import_module(mod), fn)(*args)
        q.put(("__done__", None))
    except Exception as ex:   # noqa: BLE001
        q.put(("__error__", f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1500:]}"))


async def run_job_process(target: str, args: tuple, log_el: ui.log, on_done=None, key: str | None = None):
    """Como run_job, pero en un proceso aparte que se puede detener (job.stop()). `target` = "modulo:funcion"."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    job = Job(); q = ctx.Queue()
    proc = ctx.Process(target=_child_main, args=(q, target, args), daemon=True); proc.start()
    job.proc = proc; job.stopped = False
    def stop():
        job.stopped = True
        if proc.is_alive():
            proc.terminate(); proc.join(5)
            if proc.is_alive():
                proc.kill()
    job.stop = stop
    if key:
        _JOBS[key] = job
    shown = 0; t_start = time.time(); last_change = {"t": t_start, "beat": t_start}
    def drain():
        while True:
            try:
                item = q.get_nowait()
            except Exception:   # noqa: BLE001  (cola vacía)
                return
            if isinstance(item, tuple) and item and item[0] in ("__done__", "__error__"):
                if item[0] == "__error__":
                    job.error = item[1]
                job.finished = True
            else:
                job.lines.append(item.getMessage() if hasattr(item, "getMessage") else str(item))
    def heartbeat():
        """Cada 10 s sin líneas nuevas, una línea «sigue trabajando» con la última fase real (no un latido anterior)."""
        now = time.time()
        if now - last_change["t"] >= 10 and now - last_change["beat"] >= 10:
            last_change["beat"] = now
            last = next((l for l in reversed(job.lines) if l.strip() and not l.startswith("…")), "")
            job.lines.append(T()["still_working"].format(s=int(now - t_start), last=last[-90:]))
    def poll():
        nonlocal shown
        for line in job.lines[shown:]:
            log_el.push(line)
        shown = len(job.lines)
    timer = ui.timer(0.7, poll)
    try:
        while proc.is_alive() and not getattr(job, "finished", False):
            n0 = len(job.lines); drain()                    # la cola se vacía aquí, aunque la página que creó el log ya no exista
            if len(job.lines) > n0:
                last_change["t"] = time.time()
            heartbeat()
            await asyncio.sleep(0.5)
        proc.join(2); drain()
        if job.stopped:
            job.error = T()["stopped_by_user"]
        elif proc.exitcode not in (0, None) and job.error is None and not getattr(job, "finished", False):
            job.error = f"proceso terminado con código {proc.exitcode}"
        if job.error:
            log_el.push(("ERROR " if not job.stopped else "") + job.error); ui.notify(job.error if job.stopped else T()["failed"], type="warning" if job.stopped else "negative")
    finally:
        timer.active = False; poll(); job.done = True
    if job.error is None and on_done:
        on_done(job.result)
    return job


# ----------------------------------------------------------------------------- formato y piezas comunes
def fmt_num(x, lang: str = "es", nd: int = 0) -> str:
    """Número para la interfaz: millares con espacio fino (9 139) y decimal según idioma (0,41 en es; 0.41 en en)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not np.isfinite(x):
        return "—"
    s = f"{x:,.{nd}f}"
    s = s.replace(",", " ")
    if lang == "es":
        s = s.replace(".", ",")
    return s


_CSS = """
body{font-family:'Space Grotesk',Helvetica,Arial,sans-serif;letter-spacing:.005em} .q-card{border-radius:10px}
.hero{background:#2b2b2b} .sl-mono,.q-field--outlined input[type=number],.q-slider__pin-text,.text-caption.sl-num{font-family:'JetBrains Mono',Menlo,monospace}
.sl-header{background:#fff;color:#2b2b2b;border-bottom:2px solid #2b2b2b} .body--dark .sl-header{background:#1c1c1c;color:#ececec;border-bottom-color:#0e9aa7}
.sl-header .q-btn{color:#2b2b2b} .body--dark .sl-header .q-btn{color:#ececec}
.q-btn{letter-spacing:.04em} .q-tab{letter-spacing:.03em}
.sl-step.sl-active{border-left:3px solid #0e9aa7;background:#efefef;color:#2b2b2b} .body--dark .sl-step.sl-active{background:#262626;color:#ececec}
.q-expansion-item{border:1px solid #d9dee2;border-radius:10px;margin:0 0 14px 0;overflow:hidden;background:#fff}
.q-expansion-item__container>.q-item{background:#f3f7f8} .q-expansion-item__container>.q-item .q-item__label:not(.q-item__label--caption){font-weight:600;font-size:15px}
.q-expansion-item--expanded{border-color:#0e9aa7;box-shadow:inset 4px 0 0 #0e9aa7}
.q-expansion-item--expanded>.q-expansion-item__container>.q-item{background:#e6f4f5;border-bottom:1px solid #c9e3e5}
.q-expansion-item__content{padding:10px 16px 16px 20px}
.q-expansion-item .q-expansion-item{border-radius:8px;margin:8px 0} .q-card .q-expansion-item .q-expansion-item__content,.q-expansion-item .q-expansion-item .q-expansion-item__content{padding:6px 4px 10px 8px!important} .q-card .q-expansion-item>.q-expansion-item__container>.q-item{padding-left:10px;padding-right:8px}
.body--dark .q-expansion-item{background:#1f1f1f;border-color:#3a4447} .body--dark .q-expansion-item__container>.q-item{background:#262b2c}
.body--dark .q-expansion-item--expanded{border-color:#0e9aa7} .body--dark .q-expansion-item--expanded>.q-expansion-item__container>.q-item{background:#1f3436;border-bottom-color:#2d4a4d}
.sl-curve-tools{display:grid;grid-template-columns:minmax(10.5rem,max-content) minmax(4.5rem,10rem) minmax(4.5rem,10rem);gap:0 16px;align-items:center;padding:8px 14px 10px;border:1px solid #d9dee2;border-radius:10px}
.sl-curve-title{grid-column:1/-1} .sl-curve-wide{grid-column:span 2;max-width:20.5rem;min-width:0} .sl-curve-tools>.q-field{min-width:0} .sl-curve-tools .q-toggle__label{white-space:nowrap} .body--dark .sl-curve-tools{border-color:#3a4447}
@media (max-width:600px){.sl-curve-tools{grid-template-columns:1fr 1fr}.sl-curve-tools>.q-row,.sl-curve-tools>.row{grid-column:1/-1}}
.body--dark body,.body--dark .q-page{background:#1c1c1c}
body.body--dark .q-chip.q-chip{border:1px solid #777;background:transparent!important;color:#eee}
.body--dark .text-grey-8,.body--dark .text-grey-9{color:#ccc!important} .body--dark .text-grey-7{color:#bbb!important}
.sl-w-sm{min-width:7.5rem;width:100%;max-width:11rem} .sl-w-md{min-width:11rem;width:100%;max-width:19rem}
.sl-w-lg{min-width:15rem;width:100%;max-width:27rem} .sl-w-xl{min-width:19rem;width:100%;max-width:34rem}
.row>.sl-w-sm{flex:1 1 7.5rem} .row>.sl-w-md{flex:1 1 11rem} .row>.sl-w-lg{flex:1 1 15rem} .row>.sl-w-xl{flex:1 1 19rem}
.sl-case-card{width:100%;max-width:100%;overflow:hidden} .sl-case-card .sl-val{flex:1 1 0;min-width:0;overflow-wrap:anywhere}
.q-drawer .q-scrollarea__content{width:100%;max-width:100%;padding:12px} .q-drawer .q-scrollarea__content>*{max-width:100%}
.sl-actions{position:sticky;bottom:0;z-index:1100;background:#fff;border-top:2px solid #2b2b2b}
.body--dark .sl-actions{background:#1c1c1c;border-top-color:#0e9aa7}
.sl-step{padding:6px 8px;margin-bottom:2px;border-radius:8px;cursor:pointer}
.sl-step:hover{background:rgba(127,127,127,.12)}
.sl-grid{gap:2px 12px} .sl-grid3{gap:12px} @media (max-width:1100px){ .sl-grid3{grid-template-columns:repeat(1,minmax(0,1fr))!important} } @media (max-width:1100px){ .sl-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important} } @media (max-width:700px){ .sl-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important} }
.sl-exp>.q-expansion-item__container>.q-item{min-height:52px} .sl-exp .q-item__label--caption{white-space:normal}
@media (max-width:1100px){ .sl-step{padding:3px 6px} .sl-case-card{padding:6px!important} .sl-case-card .text-caption{font-size:11px} }
"""


def action_bar(t: dict, collect, step: str, *, extra=None):
    """Barra fija al pie (como la de Malla): «Guardar» (outline) y «Guardar y continuar» (primario); `extra` añade botones."""
    with ui.row().classes("sl-actions q-gutter-sm q-py-sm q-px-md items-center w-full") as bar:
        ui.button(t["save"], icon="save", on_click=lambda: save(collect())).props("outline color=primary")
        nxt = next_step(step)
        if nxt:
            ui.button(t["save_next"], icon="arrow_forward", on_click=lambda: (save(collect()), ui.navigate.to(nxt))).props("color=accent unelevated")
        if extra:
            extra()
    return bar


def mod_chip(text: str):
    """Chip de un módulo de SCHISM (legible también en modo oscuro)."""
    dark = bool(S().get("dark"))
    return ui.chip(text, color="blue-10" if dark else "blue-1", text_color="white" if dark else "grey-9").props("dense")


def set_caption(exp, text: str):
    """Actualiza el resumen (caption) de un ui.expansion ya construido."""
    exp._props["caption"] = str(text); exp.update()


def export_dialog(c, t: dict):
    """Diálogo «Exportar» de un caso (galería y chip de la cabecera)."""
    from .state import export_case
    with ui.dialog() as dlg, ui.card().classes("q-pa-md"):
        ui.label(f"{t['export']}: {c.name}").classes("text-subtitle1")
        ui.label(t["export_hint"]).classes("text-caption text-grey-7")
        st_ = c.status()
        inc_in = ui.checkbox(t["export_inputs"], value=st_.get("mesh", False)); inc_in.set_enabled(st_.get("mesh", False) or st_.get("setup", False))
        inc_out = ui.checkbox(t["export_outputs"], value=False); inc_out.set_enabled(st_.get("run", False))
        async def go():
            dlg.close(); ui.notify(t["exporting"], type="info")
            try:
                out = await run.io_bound(lambda: export_case(c.path, bool(inc_in.value), bool(inc_out.value)))
            except Exception as ex:   # noqa: BLE001
                ui.notify(str(ex), type="negative"); return
            ui.notify(f"{t['done']}: {out.name} ({out.stat().st_size / 1e6:.1f} MB)", type="positive"); ui.download(out)
        with ui.row():
            ui.button(t["export"], icon="download", on_click=go).props("color=accent unelevated")
            ui.button(t["cancel"], on_click=dlg.close).props("flat")
    dlg.open()


def folder_input(t: dict):
    """Campo «Carpeta de la simulación» (malla, forzamientos, salidas) con botón que abre el explorador de carpetas del
    servidor; por defecto la última elegida o «Mis casos»."""
    from .state import USER_CASES
    from .folder_picker import pick_folder
    with ui.row().classes("items-center no-wrap w-full q-gutter-xs"):
        inp = ui.input(t["sim_folder"], value=str(S().get("workdir_root") or USER_CASES)).props("dense outlined").classes("col")
        async def browse():
            p = await pick_folder(inp.value, t)
            if p:
                inp.set_value(p)
        ui.button(icon="folder_open", on_click=browse).props("flat dense round").tooltip(t["browse_folder"]).mark("browse_folder")
    return inp


def chosen_root(value: str):
    """Valida la carpeta tecleada (absoluta, creada, escribible) y la recuerda; None = junto al YAML. Avisa con la ruta
    si está en un disco montado de Windows (/mnt): Dropbox/NTFS fallan a veces escribiendo ficheros grandes."""
    from .state import workdir_root
    root = workdir_root(value)
    S().update(workdir_root=str(root) if root is not None else None)
    if root is not None and str(root).startswith("/mnt/"):
        ui.notify(T()["sim_folder_mnt"].format(path=root), type="warning", timeout=8000)
    return root


def duplicate_dialog(c, t: dict):
    """Diálogo «Duplicar» de un caso (galería y chip de la cabecera)."""
    with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width:420px"):
        ui.label(f"{t['duplicate_as']}: {c.name}").classes("text-subtitle1")
        nm = ui.input(t["name"], value=f"{c.name}_copia").props("dense outlined")
        fld = folder_input(t)
        def go():
            try:
                p_ = copy_case(c.path, nm.value, workdir_root=chosen_root(fld.value))
            except (ValueError, PermissionError, OSError) as ex:
                ui.notify(str(ex), type="negative"); return
            S().update(case=str(p_)); dlg.close(); ui.navigate.to("/mesh")
        with ui.row():
            ui.button(t["create"], icon="content_copy", on_click=go).props("color=accent unelevated")
            ui.button(t["cancel"], on_click=dlg.close).props("flat")
    dlg.open()


# ----------------------------------------------------------------------------- esqueleto de pagina
def layout(step: str):
    try:                                                     # ?case=ruta.yaml selecciona el caso (enlaces y pruebas)
        q = ui.context.client.request.query_params.get("case")
        if q and Path(q).exists():
            S().update(case=str(Path(q).resolve()))
        elif q and (REPO / q).exists():
            S().update(case=str((REPO / q).resolve()))
    except Exception:                                        # noqa: BLE001
        pass
    t = T(); dark = bool(S().get("dark"))
    ui.colors(primary=BRAND["claro_texto"] if dark else BRAND["grafito"], secondary=BRAND["turquesa"], accent=BRAND["turquesa"],
              positive=BRAND["verde"], negative=BRAND["naranja"], warning=BRAND["naranja"], info=BRAND["turquesa"], dark=BRAND["oscuro"])
    ui.add_head_html(f'<link href="{BRAND_FONTS}" rel="stylesheet">'
                     f'<style>{_CSS}</style>')
    if dark:
        ui.dark_mode().enable()
    ci = case_info()
    from ..update import read_state as _upd_state, is_git_repo as _is_git
    git_ = _is_git(); _st = _upd_state() if git_ else {}; _n = int(_st.get("behind", 0) or 0) if git_ else 0
    with ui.header().classes("sl-header items-center q-px-md no-wrap").style("height:64px"):
        ui.html(brand_symbol(34, dark)).classes("q-mr-sm cursor-pointer").on("click", lambda: ui.navigate.to("/"))
        ui.html('<span style="font-size:22px;font-weight:700;letter-spacing:-.02em">SCHISM<span style="font-weight:400;color:#0e9aa7">lab</span></span>'
                + edition_badge(edition(), dark)).classes("cursor-pointer").on("click", lambda: ui.navigate.to("/")).tooltip(edition_name())
        ui.label(t["tagline"]).classes("text-subtitle2 q-ml-md gt-md")
        ui.space()
        ui.button(t["home"], icon="home", on_click=lambda: ui.navigate.to("/")).props("flat color=primary dense no-caps" + (" unelevated" if step == "home" else ""))
        if ci and step != "home":                            # chip del caso actual con su menú (en Inicio no hay caso)
            with ui.button(ci.name, icon="folder").props("flat color=primary dense no-caps").classes("q-ml-sm ellipsis").style("max-width:230px"):
                with ui.menu():
                    ui.menu_item(t["duplicate"], on_click=lambda: duplicate_dialog(ci, t))
                    ui.menu_item(t["export"], on_click=lambda: export_dialog(ci, t))
                    ui.separator()
                    ui.menu_item(t["change_case"], on_click=lambda: ui.navigate.to("/"))
            if is_pro():                                     # proyecto: qué simulación se ejecuta y se ve
                try:
                    _c = load_cfg(ci.path)
                    from ..edition import pro as _pro
                    _ms = [m.name for m in _pro("runs.members").expand(_c)] if _c.get("runs") else []
                except Exception:   # noqa: BLE001
                    _ms = []
                if _ms:
                    ui.select({"": t["base_case"], **{n: n for n in _ms}}, value=active_member() or "",
                              on_change=lambda e: (set_member(e.value or None), ui.navigate.reload())) \
                        .props("dense options-dense outlined").classes("q-ml-sm").style("min-width:130px").tooltip(t["member_select"])
        ui.toggle({"es": "ES", "en": "EN"}, value=S().get("lang", "es"), on_change=lambda e: (S().update(lang=e.value), ui.navigate.reload())).props("dense unelevated toggle-color=accent").classes("q-ml-sm")
        ui.button(icon="dark_mode" if not dark else "light_mode", on_click=lambda: (S().update(dark=not S().get("dark")), ui.navigate.reload())).props("flat round dense color=primary").tooltip(t["dark"])
        with ui.button(icon="more_vert").props("flat round dense color=primary").tooltip(t["more_menu"]):
            if _n:
                ui.badge(str(_n), color="accent").props("floating")
            with ui.menu():
                ui.menu_item(t["install"], on_click=lambda: ui.navigate.to("/install"))
                if git_:
                    with ui.menu_item(t["update"], on_click=lambda: ui.navigate.to("/update")):
                        if _n:
                            ui.badge(str(_n), color="accent").classes("q-ml-sm")
                ui.menu_item(t["report_problem"], on_click=lambda: report_problem_dialog(t))
                if (REPO / "site" / "index.html").exists():
                    ui.menu_item(t["help"], on_click=lambda: ui.navigate.to("/docs/index.html", new_tab=True))
    if git_:
        async def _daily_check():
            from ..update import check, CHECK_EVERY_S
            if os.environ.get("SCHISMLAB_NO_UPDATE_CHECK"):
                return
            if time.time() - float(_st.get("checked", 0)) >= CHECK_EVERY_S:
                r = await run.io_bound(check)
                if r.get("behind"):
                    ui.notify(t["update_available"].format(n=r["behind"]), type="info", timeout=8000)
        ui.timer(2.0, _daily_check, once=True)
    # Inicio (galería) no pertenece a ningún caso: sin panel lateral
    if step != "home":
        with ui.left_drawer(value=True).classes("bg-grey-10" if dark else "bg-grey-1").props("width=270"):
            with ui.scroll_area().classes("fit").style("height:calc(100vh - 64px)"):
                try:
                    st = ci.status() if ci else {}
                except Exception:   # noqa: BLE001  (YAML inválido: la página lo avisa en el cuerpo)
                    st = {}
                if ci:
                    with ui.card().classes("sl-case-card q-pa-sm q-mb-md " + ("bg-grey-9" if dark else "bg-white")):
                        with ui.row().classes("items-center no-wrap"):
                            ui.icon("folder").classes("text-primary"); ui.label(ci.name).classes("text-subtitle1 text-weight-bold").style("min-width:0;overflow-wrap:anywhere;line-height:1.2")
                        try:
                            for lab, val in case_summary(load_cfg(ci.path), t):
                                with ui.row().classes("no-wrap items-start q-gutter-xs"):
                                    ui.label(lab).classes("text-caption text-grey-6").style("min-width:78px"); ui.label(val).classes("text-caption sl-val")
                        except Exception:   # noqa: BLE001
                            pass
                        with ui.row().classes("items-center q-gutter-xs q-mt-xs"):
                            for k, lab in (("mesh", "status_mesh"), ("setup", "status_setup"), ("run", "status_run")):
                                status_chip(bool(st.get(k)), t[lab])
                else:
                    ui.label(t["no_case"]).classes("text-caption text-grey-7 q-mb-md")
                done = {"runs": None, "mesh": st.get("mesh"), "model": st.get("setup"), "forcing": st.get("setup"), "outputs": st.get("setup"), "params": st.get("setup"), "run": st.get("run"), "results": st.get("run")}
                for i, (key, path, icon) in enumerate(steps(), 1):
                    active = key == step
                    with ui.row().classes(("bg-primary text-white " if active else "text-grey-9 ") + "sl-step items-center full-width no-wrap") \
                            .on("click", lambda p=path: ui.navigate.to(p)):
                        ui.label(str(i)).classes("text-caption text-weight-bold").style("width:14px")
                        ui.icon(icon).classes("text-h6")
                        ui.label(t["step_" + key]).classes("text-subtitle2 q-ml-sm")
                        ui.space()
                        if done.get(key) is True:
                            ui.icon("check_circle").classes("text-positive" if not active else "text-white")
                    if active:                                           # una línea de ayuda bajo el paso activo
                        ui.label(t["step_help_" + key]).classes("text-caption text-grey-6 q-px-sm q-mb-sm")
                ui.separator().classes("q-my-sm")
                nxt = next_step(step)
                if nxt and ci:
                    ui.button(t["next_step_btn"], on_click=lambda: ui.navigate.to(nxt)).props("unelevated color=accent no-caps").classes("full-width q-mb-xs")
                ui.button(t["new_case"], icon="add", on_click=lambda: ui.navigate.to("/?new=1")).props("outline color=primary no-caps").classes("full-width")
    # ayuda contextual: icono (i) en cada campo ajustable, al cerrar la pagina y para los campos creados despues
    from .help import annotate
    lang_ = S().get("lang", "es"); client_ = ui.context.client
    ui.timer(2.0, lambda: annotate(client_, lang_))
    return _PageBody(ui.column().classes("q-pa-md q-pa-lg-lg full-width").style("max-width:1400px"), client_, lang_)


def pro_notice(t: dict, text: str | None = None):
    """Aviso de función de SCHISMlab Pro (en SCHISMlab Lite)."""
    with ui.row().classes("items-center no-wrap q-pa-sm rounded-borders q-mb-sm " + ("bg-blue-grey-10" if S().get("dark") else "bg-blue-grey-1")):
        ui.html(edition_badge("pro", bool(S().get("dark"))))
        ui.label(text or t["pro_feature"]).classes("text-body2")


def pro_card(t: dict):
    """Instalación: estado de SCHISMlab Pro y, en Lite, casilla para activarlo con un token."""
    from ..edition import problem, pro_path
    dark = bool(S().get("dark"))
    with ui.card().classes("q-pa-md w-full q-mb-md"):
        with ui.row().classes("items-center no-wrap"):
            ui.label("SCHISMlab").classes("text-subtitle1 text-weight-bold")
            ui.html(edition_badge("pro", dark))
        if is_pro():
            ui.label(t["pro_active"]).classes("text-body2")
            ui.label(str(pro_path() or "")).classes("text-caption text-grey-7")
            return
        if problem():
            ui.label(t["pro_problem"].format(msg=problem())).classes("text-body2 text-orange-9")
        ui.label(t["pro_activate_hint"]).classes("text-caption text-grey-7")
        with ui.row().classes("items-center q-gutter-sm w-full no-wrap"):
            tok = ui.input(t["pro_token"], password=True, password_toggle_button=True).props("dense outlined").classes("col")
            btn = ui.button(t["pro_activate_btn"], icon="key").props("color=accent unelevated no-caps")
        plog = ui.log(max_lines=50).classes("w-full h-24").style("display:none")

        async def activate_pro():
            from ..activate import install, ActivationError
            value = (tok.value or "").strip()
            plog.style("display:block"); plog.clear(); plog.push(t["pro_activating"]); btn.disable()
            try:
                await run.io_bound(lambda: install(value, log_fn=lambda m: None))
            except ActivationError as ex:
                plog.push(t["pro_bad_token"].format(msg=ex)); ui.notify(t["pro_bad_token"].format(msg=ex), type="negative"); btn.enable(); return
            except Exception as ex:   # noqa: BLE001
                plog.push(f"{type(ex).__name__}: {ex}"); ui.notify(t["failed"], type="negative"); btn.enable(); return
            tok.set_value("")
            plog.push(t["pro_installed_restart"]); ui.notify(t["pro_installed_restart"], type="positive", timeout=10000)
            from ..update import restart_gui, simulation_running
            if not simulation_running():
                ui.timer(2.0, restart_gui, once=True)
        btn.on_click(activate_pro)


def status_chip(ok: bool, text: str):
    """Estado (malla / ficheros / simulación) con un único estilo: icono + texto, en la tarjeta lateral y en la galería."""
    with ui.row().classes("items-center no-wrap").style("gap:2px"):
        ui.icon("check_circle" if ok else "radio_button_unchecked", size="16px").classes("text-positive" if ok else "text-grey-5")
        ui.label(text).classes("text-caption")


class _PageBody:
    """Cuerpo de pagina: al salir del `with layout(...)` se anaden los iconos de ayuda a los campos."""

    def __init__(self, col, client, lang):
        self.col, self.client, self.lang = col, client, lang

    def __enter__(self):
        self.col.__enter__(); return self.col

    def __exit__(self, *exc):
        r = self.col.__exit__(*exc)
        try:
            from .help import annotate
            annotate(self.client, self.lang)
        except Exception:   # noqa: BLE001
            pass
        return r


def need_case() -> bool:
    """True (y un aviso con botón Inicio) si no hay caso elegido o su YAML no se puede leer."""
    err = yaml_error(case_path()) if case_path() is not None else None
    if case_path() is None or err:
        with ui.card().classes("q-pa-lg " + ("bg-orange-10" if S().get("dark") else "bg-orange-1")):
            ui.label(err or T()["no_case"]).classes("text-h6")
            if err:
                ui.label(str(case_path())).classes("text-caption text-grey-7")
            ui.button(T()["home"], icon="home", on_click=lambda: ui.navigate.to("/"))
        return True
    return False


# ----------------------------------------------------------------------------- inicio: galeria
@ui.page("/")
def page_home():
    t = T()
    with layout("home"):
        try:
            want_new = ui.context.client.request.query_params.get("new")
        except Exception:   # noqa: BLE001
            want_new = None
        dark = bool(S().get("dark"))
        with ui.dialog() as imp_dlg, ui.card().classes("q-pa-md").style("min-width:380px"):
            ui.label(t["import_dialog"]).classes("text-subtitle1 text-weight-bold")
            ui.label(t["import_hint"]).classes("text-caption text-grey-7")
            imp_fld = folder_input(t)
            ui.upload(label=t["import_case"], on_upload=lambda e: on_import(e), auto_upload=True).props("accept=.zip").classes("w-full q-mt-sm")   # on_import se define más abajo
            ui.button(t["cancel"], on_click=imp_dlg.close).props("flat")
        with ui.card().classes("hero text-white q-pa-lg full-width"):
            with ui.row().classes("items-center w-full q-col-gutter-md"):
                with ui.column().classes("col-12 col-md"):
                    ui.label(t["gallery"]).classes("text-h4 text-weight-bold")
                    ui.label(t["gallery_sub"]).classes("text-subtitle1")
                with ui.column().classes("col-12 col-md-5"):
                    with ui.card().classes("q-pa-md w-full " + ("bg-grey-9 text-grey-3" if dark else "bg-white text-grey-9")):
                        ui.label(t["new_case_hero"]).classes("text-subtitle1 text-weight-bold text-primary")
                        ui.label(t["new_case_hint"]).classes("text-caption text-grey-7")
                        with ui.row().classes("items-center no-wrap q-gutter-sm"):
                            name = ui.input(t["name"], value="mi_caso").props("dense outlined").classes("col")
                            ui.button(t["create"], icon="add", on_click=lambda: create_new()).props("color=accent unelevated")
                        new_fld = folder_input(t)
                        ui.label(t["sim_folder_hint"]).classes("text-caption text-grey-7")
                        def create_new():
                            try:
                                p_ = new_case(name.value, workdir_root=chosen_root(new_fld.value))
                            except (ValueError, PermissionError, OSError) as ex:
                                ui.notify(str(ex), type="negative"); return
                            S().update(case=str(p_)); ui.navigate.to("/mesh")
                        ui.button(t["import_case"], icon="upload", on_click=imp_dlg.open).props("flat dense no-caps").classes("q-mt-xs")
                        if want_new:
                            name.run_method("focus")

        def open_case(c):
            S().update(case=str(c.path)); ui.navigate.to("/mesh")

        def export(c):
            export_dialog(c, t)

        async def on_import(e):
            from .state import import_case
            import tempfile
            try:
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    tmp = f.name
                await e.file.save(tmp)                      # NiceGUI 3: e.file (FileUpload) con lectura asíncrona
                root = chosen_root(imp_fld.value)
                p_ = await run.io_bound(lambda: import_case(Path(tmp), workdir_root=root))
                Path(tmp).unlink(missing_ok=True)
                imp_dlg.close(); ui.notify(f"{t['imported']}: {p_.stem}", type="positive"); S().update(case=str(p_)); ui.navigate.to("/mesh")
            except Exception as ex:   # noqa: BLE001
                ui.notify(f"{t['failed']}: {ex}", type="negative")

        def duplicate(c):
            duplicate_dialog(c, t)

        def remove(c):
            with ui.dialog() as dlg, ui.card().classes("q-pa-md"):
                ui.label(t["delete_q"].format(name=c.name)).classes("text-subtitle1 text-weight-bold")
                ui.label(t["delete_hint"]).classes("text-caption text-grey-8").style("max-width:420px")
                def do():
                    try:
                        dest = delete_case(c.path)
                    except Exception as ex:   # noqa: BLE001
                        ui.notify(str(ex), type="negative"); return
                    if S().get("case") == str(c.path):
                        S().pop("case", None)
                    dlg.close(); ui.notify(t["deleted"].format(name=c.name, dest=dest), type="positive", timeout=10000)
                    ui.navigate.reload()
                with ui.row():
                    ui.button(t["delete"], icon="delete", on_click=do).props("color=negative")
                    ui.button("✕", on_click=dlg.close).props("flat")
            dlg.open()

        for group, title in (("mine", t["mine"]), ("tests", t["tests_group"])):
            items = [c for c in gallery() if c.group == group]
            if not items:
                continue
            ui.label(title).classes("text-h6 q-mt-lg text-primary")
            with ui.row().classes("q-gutter-md"):
                for c in items:
                    with ui.card().classes("cursor-pointer hover-shadow").style("width:300px").on("click", lambda c=c: open_case(c)):
                        th = c.thumbnail()
                        if th:
                            ui.image(str(th)).classes("w-full").style("height:150px;object-fit:cover")
                        else:
                            with ui.element("div").classes("w-full hero").style("height:150px"):
                                ui.icon("waves").classes("text-white text-h2 absolute-center")
                        with ui.card_section():
                            ui.label(c.name).classes("text-subtitle1 text-weight-bold")
                            if c.theme:
                                ui.badge(c.theme, color="accent").classes("q-mb-xs")
                            if is_pro():                                 # proyecto: número de simulaciones
                                try:
                                    _rc = load_cfg(c.path).get("runs")
                                    if _rc:
                                        from ..edition import pro as _pro
                                        ui.badge(t["n_sims"].format(n=len(_pro("runs.members").expand(load_cfg(c.path)))), color="secondary").props("outline").classes("q-mb-xs")
                                except Exception:   # noqa: BLE001
                                    pass
                            if c.title != c.name:
                                ui.label(c.title).classes("text-caption text-grey-8").style("min-height:48px")
                            st = c.status()
                            with ui.row().classes("items-center q-gutter-xs no-wrap"):
                                if not c.valid():
                                    ui.badge("YAML", color="negative").props("outline").tooltip(t["yaml_invalid"].format(line="?"))
                                for k, v in st.items():
                                    status_chip(bool(v), t["status_" + k])
                            with ui.row().classes("q-gutter-xs items-center"):
                                ui.button(t["open_case"], icon="folder_open").props("flat dense size=sm color=primary").on("click.stop", lambda _, c=c: open_case(c))
                                ui.button(t["duplicate"], icon="content_copy").props("flat dense size=sm").on("click.stop", lambda _, c=c: duplicate(c))
                                ui.button(t["export"], icon="archive").props("flat dense size=sm").on("click.stop", lambda _, c=c: export(c))
                                if c.group == "mine":
                                    ui.button(icon="delete").props("flat dense round size=sm color=negative").on("click.stop", lambda _, c=c: remove(c)).tooltip(t["delete"])
                                if c.name in PRACTICAS and (REPO / "site" / "practicas" / c.name / "index.html").exists():
                                    ui.button(t["guide"], icon="menu_book").props("flat dense size=sm").on("click.stop", lambda _, n=c.name: ui.navigate.to(f"/docs/practicas/{n}/", new_tab=True))


# ----------------------------------------------------------------------------- instalacion y credenciales
@ui.page("/install")
def page_install():
    t = T()
    with layout("install"):
        ui.label(t["install"]).classes("text-h4 text-primary")
        exe = HOME / "bin" / "pschism_hydro"
        n_builds = len(list((HOME / "bin").glob("pschism_*"))) if (HOME / "bin").exists() else 0
        PRO = is_pro()
        cards = [(t["schism"], f"{n_builds} {t['installed_builds'].lower()}" if n_builds else t["not_compiled"], "memory", n_builds > 0),
                 (t["cores"], str(os.cpu_count()), "developer_board", True)]
        if PRO:                                                  # MATLAB (OceanMesh2D) y clúster: SCHISMlab Pro
            from ..edition import pro as _pro
            find_matlab = _pro("mesh.oceanmesh2d").find_matlab
            reachable = _pro("cluster.tramuntana").reachable
            cards[1:1] = [(t["matlab"], t["found"] if find_matlab() else t["notfound"], "functions", bool(find_matlab()))]
            cards.append((t["cluster"], t["reachable"] if reachable() else t["unreachable"], "dns", reachable()))
        pro_card(t)
        with ui.row().classes("q-gutter-md"):
            for label, value, icon, good in cards:
                with ui.card().classes("q-pa-md").style("width:230px"):
                    ui.icon(icon).classes("text-h4 " + ("text-positive" if good else "text-negative"))
                    ui.label(label).classes("text-caption text-grey-7"); ui.label(value).classes("text-subtitle1 text-weight-bold")
        if PRO:                                             # costa OSM: SCHISMlab Pro
            # --- línea de costa OSM global (descargada al instalar; actualizable)
            from ..edition import pro as _pro
            _pro_mesh_coastline = _pro("mesh.coastline")
            osm_land_info = _pro_mesh_coastline.osm_land_info
            osm_land_remote_modified = _pro_mesh_coastline.osm_land_remote_modified
            ensure_osm_land = _pro_mesh_coastline.ensure_osm_land
            with ui.card().classes("q-pa-md w-full q-mt-md"):
                ui.label(t["coast_card"]).classes("text-subtitle1 text-weight-bold")
                ui.label(t["coast_card_hint"]).classes("text-caption text-grey-7")
                info = osm_land_info()
                status = ui.label(t["coast_status"].format(size=info.get("size_mb", "?"), date=info.get("downloaded", "?")) if info else t["coast_missing"]).classes("text-body2")
                clog = ui.log(max_lines=50).classes("w-full h-24").style("display:none")
                with ui.row().classes("q-gutter-sm items-center"):
                    async def coast_check():
                        remote = await run.io_bound(osm_land_remote_modified)
                        have = (osm_land_info() or {}).get("last_modified")
                        if remote is None:
                            ui.notify(t["coast_nonet"], type="warning")
                        elif have == remote:
                            ui.notify(t["coast_uptodate"], type="positive")
                        else:
                            ui.notify(t["coast_newer"].format(date=remote), type="info", timeout=8000)
                    async def coast_get(update: bool):
                        clog.style("display:block"); clog.clear()
                        await run_job(lambda: ensure_osm_land(update=update, log_fn=lambda m: logging.getLogger("schismlab").info(m)), clog,
                                      on_done=lambda r: (status.set_text(t["coast_status"].format(**{"size": (osm_land_info() or {}).get("size_mb", "?"), "date": (osm_land_info() or {}).get("downloaded", "?")})), ui.notify(t["done"], type="positive")))
                    ui.button(t["coast_download"] if not info else t["coast_update"], icon="download", on_click=lambda: coast_get(bool(info))).props("color=accent unelevated")
                    ui.button(t["coast_check"], icon="update", on_click=coast_check).props("outline")
        from ..build import MODULES, installed, variant_name, build as build_variant
        ui.label(t["build"]).classes("text-h6 q-mt-lg text-primary")
        builds = installed()
        with ui.row().classes("q-gutter-md items-start"):
            with ui.card().classes("q-pa-md").style("flex:1 1 420px;max-width:600px"):
                ui.label(t["compile_modules"]).classes("text-subtitle1 text-weight-bold")
                boxes = {}
                for m in MODULES:
                    with ui.row().classes("items-center no-wrap"):
                        boxes[m.key] = ui.checkbox(getattr(m, S().get("lang", "es")), value=m.key in ("prec_evap",)).props("dense")
                        ui.label(m.cmake).classes("text-caption text-grey-6 q-ml-xs")
                        if not m.stable:
                            ui.label("*").classes("text-orange-9 text-weight-bold q-ml-xs").tooltip(t["experimental"])
                if any(not m.stable for m in MODULES):
                    ui.label(t["experimental_note"]).classes("text-caption text-grey-7")
                name_lbl = ui.label().classes("text-caption text-grey-8 q-mt-sm")
                def refresh_name():
                    mods = [k for k, b in boxes.items() if b.value]
                    name_lbl.text = f"{t['variant']}: pschism_{variant_name(mods)}"
                for b in boxes.values():
                    b.on_value_change(lambda e: refresh_name())
                refresh_name()
                log = ui.log(max_lines=200).classes("w-full h-40").style("display:none")
                async def compile_():
                    mods = [k for k, b in boxes.items() if b.value]
                    log.style("display:block"); log.push(t["compiling"])
                    await run_job(lambda: build_variant(mods, log=lambda txt: None), log, on_done=lambda r: ui.navigate.reload())
                ui.button(t["compile"], icon="build", on_click=compile_).props("color=accent")
            with ui.card().classes("q-pa-md").style("flex:1 1 320px"):
                ui.label(t["installed_builds"]).classes("text-subtitle1 text-weight-bold")
                if not builds:
                    ui.label(t["not_compiled"]).classes("text-negative")
                for name, info in builds.items():
                    with ui.row().classes("items-center q-mb-xs"):
                        ui.icon("memory").classes("text-positive")
                        ui.label(f"pschism_{name}").classes("text-weight-bold")
                        ui.label(f"{t['built_on']} {info['built']}").classes("text-caption text-grey-7")
                    with ui.row().classes("q-ml-lg q-gutter-xs"):
                        for k in info["modules"]:
                            mod_chip(k)
        if PRO:                                             # SWASH/XBeach y credenciales de datos: SCHISMlab Pro
            from ..build import wave_models, build_wave_models
            wm = wave_models()
            with ui.card().classes("q-pa-md q-mt-md w-full"):
                ui.label(t["wave_models"]).classes("text-subtitle1 text-weight-bold"); ui.label(t["wave_models_hint"]).classes("text-caption text-grey-7")
                with ui.row().classes("q-gutter-md items-center"):
                    for k, lab in (("swash", "SWASH"), ("xbeach", "XBeach")):
                        with ui.row().classes("items-center no-wrap"):
                            ui.icon("check_circle" if wm[k] else "cancel").classes("text-positive" if wm[k] else "text-negative"); ui.label(lab)
                    wlog = ui.log(max_lines=100).classes("w-full h-24").style("display:none")
                    async def build_wm():
                        wlog.style("display:block")
                        await run_job(lambda: build_wave_models(log=lambda txt: None), wlog, on_done=lambda r: ui.navigate.reload())
                    if not (wm["swash"] and wm["xbeach"]):
                        ui.button(t["build_wave_models"], icon="waves", on_click=build_wm).props("outline color=accent")
            ui.label(t["credentials"]).classes("text-h6 q-mt-lg text-primary")
            from ..edition import pro as _pro
            _pro_data_era5 = _pro("data.era5")
            era5_ok = _pro_data_era5.have_credentials
            era5_save = _pro_data_era5.save_credentials
            from ..edition import pro as _pro
            _pro_data_cmems = _pro("data.cmems")
            cmems_ok = _pro_data_cmems.have_credentials
            cmems_save = _pro_data_cmems.save_credentials
            from ..edition import pro as _pro
            _pro_data_fes = _pro("data.fes")
            fes_ok = _pro_data_fes.have_credentials
            fes_save = _pro_data_fes.save_credentials
            with ui.grid(columns=3).classes("w-full sl-grid3"):
                with ui.card().classes("q-pa-md h-full"):
                    ui.label(t["era5"]).classes("text-subtitle1 text-weight-bold"); ui.badge(t["ok"] if era5_ok() else t["missing"], color="positive" if era5_ok() else "negative")
                    k = ui.input(t["key"], password=True, password_toggle_button=True).classes("w-full")
                    ui.button(t["save"], on_click=lambda: (era5_save(k.value), ui.navigate.reload())).props("flat")
                    ui.link("cds.climate.copernicus.eu", "https://cds.climate.copernicus.eu/profile", new_tab=True).classes("text-caption")
                with ui.card().classes("q-pa-md h-full"):
                    ui.label(t["cmems"]).classes("text-subtitle1 text-weight-bold"); ui.badge(t["ok"] if cmems_ok() else t["missing"], color="positive" if cmems_ok() else "negative")
                    u = ui.input(t["user"]).classes("w-full"); p = ui.input(t["password"], password=True, password_toggle_button=True).classes("w-full")
                    ui.button(t["save"], on_click=lambda: (cmems_save(u.value, p.value), ui.navigate.reload())).props("flat")
                    ui.link("data.marine.copernicus.eu", "https://data.marine.copernicus.eu/register", new_tab=True).classes("text-caption")
                with ui.card().classes("q-pa-md h-full"):
                    ui.label(t["aviso"]).classes("text-subtitle1 text-weight-bold"); ui.badge(t["ok"] if fes_ok() else t["missing"], color="positive" if fes_ok() else "negative")
                    u2 = ui.input(t["user"]).classes("w-full"); p2 = ui.input(t["password"], password=True, password_toggle_button=True).classes("w-full")
                    ui.button(t["save"], on_click=lambda: (fes_save(u2.value, p2.value), ui.navigate.reload())).props("flat")
                    ui.link("aviso.altimetry.fr", "https://www.aviso.altimetry.fr/en/my-aviso-plus.html", new_tab=True).classes("text-caption")


# ----------------------------------------------------------------------------- malla con mapa
@ui.page("/mesh")
def page_mesh():
    t = T()
    with layout("mesh"):
        if need_case():
            return
        c = cfg(); m = c.setdefault("mesh", {})
        ui.label(t["step_mesh"]).classes("text-h4 text-primary")
        ui.label(t["mesh_intro"]).classes("text-body2 text-grey-8")

        def card_title(num, text, icon):
            with ui.row().classes("items-center q-gutter-sm no-wrap"):
                ui.label(str(num)).classes("bg-primary text-white text-weight-bold flex flex-center").style(
                    "width:28px;height:28px;border-radius:50%;font-size:15px")
                ui.icon(icon, color="primary", size="22px")
                ui.label(text).classes("text-h6 text-primary")

        # --- 1. generador --------------------------------------------------------------------
        PRO = is_pro()
        gens = {"ocsmesh": t["gen_ocsmesh"], "oceanmesh2d": t["gen_om2d"], "idealized": t["gen_ideal"], "file": t["gen_file"]} if PRO else {"idealized": t["gen_ideal"]}
        if not PRO and (m.get("generator", default_generator()) != "idealized" or ("lon" in m and "lat" in m)):
            pro_notice(t, t["pro_mesh"])
        with ui.card().classes("q-pa-md w-full"):
            card_title(1, t["generator"], "precision_manufacturing")
            gen = ui.toggle(gens, value=m.get("generator", default_generator()) if PRO else "idealized").props("no-caps unelevated toggle-color=primary")
            gen_desc = ui.label().classes("text-caption text-grey-7")
            filebox = ui.column().classes("w-full")
            with filebox:
                ui.label(t["file_hint"]).classes("text-caption text-grey-7")
                with ui.row().classes("items-center q-gutter-md w-full"):
                    mfile = ui.input(t["file_path"], value=str(m.get("file", ""))).props("dense clearable").classes("sl-w-lg")

                    async def on_upload(e):
                        dest = workdir() / "imported.gr3"; dest.parent.mkdir(parents=True, exist_ok=True)
                        await e.file.save(dest)             # NiceGUI 3: e.file (FileUpload) con escritura asíncrona
                        mfile.set_value(str(dest)); ui.notify(f"{e.file.name} → {dest.name}")
                    ui.upload(label=t["upload_mesh"], on_upload=on_upload, auto_upload=True).props("dense flat accept=.gr3,.14,.grd").classes("sl-w-lg")
        real = ui.column().classes("w-full q-gutter-md"); ideal = ui.column().classes("w-full")

        def _vis(v):
            real.set_visibility(v not in ("idealized", "file")); ideal.set_visibility(v == "idealized"); filebox.set_visibility(v == "file")
            gen_desc.set_text(t.get(f"gen_desc_{v}", ""))
        gen.on_value_change(lambda e: _vis(e.value))

        # --- dominio real ----------------------------------------------------------------------
        if PRO:                                             # costa real: SCHISMlab Pro
            with real:
                poly = m.get("polygon") or ([[m["lon"][0], m["lat"][0]], [m["lon"][1], m["lat"][0]], [m["lon"][1], m["lat"][1]], [m["lon"][0], m["lat"][1]]] if ("lon" in m and "lat" in m) else [])
                regions = (m.get("resolution", {}) or {}).get("regions", []) or []
                r = m.setdefault("resolution", {})
                from ..edition import pro as _pro
                _pro_data_bathymetry = _pro("data.bathymetry")
                SOURCES = _pro_data_bathymetry.SOURCES
                all_sources = _pro_data_bathymetry.all_sources
                from ..mesh.build import bathymetry_layers
                base_src, layers = bathymetry_layers(m)
                if not isinstance(base_src, str):                 # fondo idealizado (número o {kind: ...}): no es una fuente real
                    base_src, layers = "gebco2021", []
                layers = [dict(l) for l in layers]
                inu0 = m.get("inundation") or {}
                urb0 = inu0.get("urban") or {}
                edge_types = {int(k_): v_ for k_, v_ in (m.get("edge_types") or {}).items()}   # lado i del poligono -> forced | radiation | wall
                EDGE_STYLE = {"forced": {"color": "#e63946", "weight": 6}, "radiation": {"color": "#2a9d8f", "weight": 6, "dashArray": "10 7"},
                              "wall": {"color": "#4a4a4a", "weight": 6}}

                # --- 2. dominio y zonas: mapa ---------------------------------------------------
                with ui.card().classes("q-pa-md w-full"):
                    card_title(2, t["mesh_card_draw"], "draw")
                    with ui.row().classes("items-center q-gutter-sm w-full"):
                        ui.label(t["draw_what"]).classes("text-body2")
                        draw_target = ui.toggle({"domain": t["domain"], "region": t["regions"], "inu": t["draw_inu"], "edges": t["draw_edges"]}, value="domain").props("dense no-caps")
                        ui.space()
                        edit_btn = ui.button(t["edit_polys"], icon="edit_location_alt").props("outline dense")
                        clear_btn = ui.button(t["clear"], icon="delete").props("flat dense color=negative")
                    draw_help = ui.label().classes("text-caption text-grey-7")
                    draw_target.on_value_change(lambda e: (draw_help.set_text(t[{"domain": "draw_hint", "region": "draw_hint_region", "inu": "draw_hint_inu", "edges": "draw_hint_edges"}[e.value]]), redraw()))
                    draw_help.set_text(t["draw_hint"])
                    center = (float(np.mean([p[1] for p in poly])), float(np.mean([p[0] for p in poly]))) if poly else (39.5, 2.8)
                    lmap = ui.leaflet(center=center, zoom=7, draw_control={
                        "draw": {"polygon": True, "rectangle": True, "marker": False, "circle": False, "circlemarker": False, "polyline": False},
                        "edit": {"edit": False, "remove": False}}, hide_drawn_items=True).classes("w-full").style("height:480px")
                    legend_box = ui.row().classes("items-center q-gutter-md text-caption")
                    extent_lbl = ui.label().classes("text-caption text-grey-8")
                    extent_warn = ui.label().classes("text-caption text-orange-9")
                    ui.separator()
                    ui.label(t["zones_title"]).classes("text-subtitle2 q-mt-sm")
                    ui.label(t["zones_hint"]).classes("text-caption text-grey-7")
                    zones_box = ui.column().classes("w-full q-gutter-xs")
                    open_b = ui.switch(t["open_b"], value=m.get("open_boundaries", "bbox") != "none")

                # --- 3. costa y batimetria --------------------------------------------------------
                with ui.card().classes("q-pa-md w-full"):
                    card_title(3, t["mesh_card_data"], "layers")
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        from ..edition import pro as _pro
                        _pro_mesh_coastline = _pro("mesh.coastline")
                        _osm_info = _pro_mesh_coastline.osm_land_info
                        _cop = {"auto": t["coast_auto_on"] if _osm_info() else t["coast_auto_off"], "osm": t["coast_osm"], "gshhg": t["coast_gshhg"]}
                        coast = ui.select(_cop, value=m.get("coastline", "auto") if m.get("coastline", "auto") in _cop else "auto", label=t["coastline"]).classes("sl-w-lg")
                        creg0 = m.get("coastline_region")
                        _ropts = {"": t["whole_domain"], **{rg.get("name", f"zona{j + 1}"): rg.get("name", f"zona{j + 1}") for j, rg in enumerate(regions)}}
                        coast_reg = ui.select(_ropts, value=safe_select(_ropts, creg0 if isinstance(creg0, str) else "", "", label=t["coast_zone"]), label=t["coast_zone"]).props("dense").classes("sl-w-md")
                        coast_reg.bind_visibility_from(coast, "value", backward=lambda v: v == "osm")
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        bath = ui.select({k: v["desc"] for k, v in SOURCES.items()}, value=base_src if base_src in SOURCES else "gebco2021", label=t["bathy"], on_change=lambda e: show_extent()).classes("sl-w-lg")
                        bath_file = ui.input(t["bathy_file"], value=base_src if isinstance(base_src, str) and base_src not in SOURCES else "").props("dense clearable").classes("sl-w-lg")
                    with ui.expansion(t["bathy_layers"], icon="layers", value=bool(layers)).classes("w-full"):
                        ui.label(t["bathy_layers_hint"]).classes("text-caption text-grey-7")
                        @ui.refreshable
                        def layer_list():
                            for i, lay in enumerate(layers):
                                with ui.row().classes("items-center q-gutter-sm"):
                                    _srcs = dict(all_sources()); _lsrc = lay.get("source", "emodnet2024")
                                    if _lsrc not in _srcs:                              # ruta a un fichero propio: opción propia
                                        _srcs[_lsrc] = str(_lsrc)
                                    ui.select(_srcs, value=_lsrc, label=t["bathy"]).props("dense").classes("sl-w-lg").on_value_change(lambda e, lay=lay: lay.update(source=e.value))
                                    _lopts = {"": t["whole_domain"], **{rg.get("name", f"zona{j + 1}"): rg.get("name", f"zona{j + 1}") for j, rg in enumerate(regions)}}
                                    ui.select(_lopts, value=safe_select(_lopts, lay.get("region", "") if isinstance(lay.get("region", ""), str) else "", "", label=t["regions"]),
                                              label=t["regions"]).props("dense").classes("sl-w-md").on_value_change(lambda e, lay=lay: lay.update(region=e.value) if e.value else lay.pop("region", None))
                                    ui.switch(t["land_only"], value=bool(lay.get("land_only", lay.get("source") in ("fabdem", "copdem30")))).props("dense").on_value_change(lambda e, lay=lay: lay.update(land_only=bool(e.value)))
                                    ui.number(t["blend_km"], value=float(lay.get("blend_km", 1.0)), min=0, step=0.5).props("dense").classes("sl-w-sm").on_value_change(lambda e, lay=lay: lay.update(blend_km=float(e.value)))
                                    ui.button(icon="close", on_click=lambda _, i=i: (layers.pop(i), layer_list.refresh())).props("flat dense round")
                        layer_list()
                        ui.button(t["add_layer"], icon="add", on_click=lambda: (layers.append({"source": "emodnet2024", "blend_km": 1.0}), layer_list.refresh())).props("flat")

                # --- 4. resolucion ----------------------------------------------------------------
                with ui.card().classes("q-pa-md w-full"):
                    card_title(4, t["mesh_card_res"], "straighten")
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        res_min = ui.number(t["res_min"], value=float(r.get("min", 1000)), min=1, step=100)
                        res_max = ui.number(t["res_max"], value=float(r.get("max", 8000)), min=10, step=500)
                        res_ns = ui.number(t["res_ns"], value=float(r.get("max_nearshore", min(5 * float(r.get("min", 1000)), float(r.get("max", 8000))))), min=1, step=100)
                    with ui.expansion(t["res_advanced"], icon="tune").classes("w-full"):
                        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                            fs = ui.number(t["fs"], value=float(r.get("feature_size", 3)), min=0, step=1)
                            wl = ui.number(t["wl"], value=float(r.get("wavelength", 30)), min=0, step=5)
                            slp = ui.number(t["slp"], value=float(r.get("slope", 15)), min=0, step=5)
                            grade = ui.number(t["grade"], value=float(r.get("grade", 0.2)), min=0.05, max=0.5, step=0.05)
                            mindep = ui.number(t["min_depth_l"], value=float(m.get("min_depth", 1.0)), min=0, step=0.5)
                        dsz = ui.input(t["depth_sizes"], value=", ".join(f"{float(d_):g}:{float(s_):g}" for d_, s_ in (r.get("depth_sizes") or [])),
                                       placeholder="5:300, 50:1000, 500:5000, 2000:15000").classes("sl-w-xl")
                        ui.label(t["depth_sizes_hint"]).classes("text-caption text-grey-7")

                # --- 5. inundacion ----------------------------------------------------------------
                with ui.card().classes("q-pa-md w-full"):
                    with ui.row().classes("items-center w-full no-wrap"):
                        card_title(5, t["inundation"], "flood")
                        ui.space()
                        inu_on = ui.switch(t["inu_enable"], value=bool(inu0))
                    ui.label(t["inundation_hint"]).classes("text-caption text-grey-7")
                    inu_body = ui.column().classes("w-full q-gutter-sm")
                    with inu_body:
                        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                            _iopts = {"": t["whole_domain"], **{rg.get("name", f"zona{j + 1}"): rg.get("name", f"zona{j + 1}") for j, rg in enumerate(regions)}}
                            inu_region = ui.select(_iopts, value=safe_select(_iopts, inu0.get("region", "") if isinstance(inu0.get("region", ""), str) else "", "", label=t["inu_zone"]),
                                                   label=t["inu_zone"]).props("dense").classes("sl-w-md")
                            inu_elev = ui.number(t["inu_elev"], value=float(inu0.get("max_elevation", 10)), min=1, step=1).props("dense").classes("sl-w-sm")
                            inu_size = ui.number(t["inu_size"], value=float(inu0.get("size", 50)), min=1, step=5).props("dense").classes("sl-w-md")
                            inu_tr = ui.number(t["transition"], value=float(inu0.get("transition_km", 1.0)), min=0, step=0.5).props("dense").classes("sl-w-sm")
                            inu_ct = ui.number(t["inu_contours"], value=float(inu0.get("contours", 1.0)), min=0, step=0.5).props("dense").classes("sl-w-md")
                            inu_lo = ui.switch(t["inu_land_only"], value=bool(inu0.get("land_only", False))).props("dense")
                        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                            from ..edition import pro as _pro
                            _pro_data_dem = _pro("data.dem")
                            DEM_SOURCES = _pro_data_dem.DEM_SOURCES
                            mdt02_status = _pro_data_dem.mdt02_status
                            inu_dem = ui.select({k: v["desc"] for k, v in DEM_SOURCES.items()}, value=inu0.get("dem", "fabdem") if inu0.get("dem", "fabdem") in DEM_SOURCES else "fabdem", label=t["inu_dem"]).props("dense").classes("sl-w-lg")
                            inu_file = ui.input(t["inu_dem_file"], value=inu0.get("dem", "") if inu0.get("dem") and inu0.get("dem") not in DEM_SOURCES else "").props("dense clearable").classes("sl-w-lg")
                        mdt02_box = ui.column().classes("w-full")

                        def show_mdt02():
                            mdt02_box.clear()
                            if inu_dem.value != "mdt02" or (inu_file.value or "").strip():
                                return
                            st = mdt02_status()
                            with mdt02_box, ui.card().classes("q-pa-sm w-full " + ("bg-blue-10" if S().get("dark") else "bg-blue-1")):
                                ui.label(t["mdt02_how"].format(folder=st["folder"], n=st["tiles"])).classes("text-caption")
                                with ui.row().classes("q-gutter-sm"):
                                    ui.link(t["mdt02_link"], "https://centrodedescargas.cnig.es/CentroDescargas/modelo-digital-terreno-mdt02-segunda-cobertura", new_tab=True).classes("text-caption")
                        inu_dem.on_value_change(lambda e: show_mdt02()); inu_file.on_value_change(lambda e: show_mdt02()); show_mdt02()
                        with ui.expansion(t["urban_title"], icon="location_city", value=bool(urb0)).classes("w-full"):
                            ui.label(t["urban_hint"]).classes("text-caption text-grey-7")
                            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                                urb_on = ui.switch(t["urban_on"], value=bool(urb0))
                                urb_size = ui.number(t["urban_size"], value=float(urb0.get("size", 4.0)), min=1, step=1).props("dense").classes("sl-w-md")
                                urb_mesh = ui.select({"conform": t["urban_mesh_conform"], "snap": t["urban_mesh_snap"]}, value=safe_select(("conform", "snap"), urb0.get("mesh", "conform"), "conform", label=t["urban_mesh"]), label=t["urban_mesh"]).props("dense").classes("sl-w-lg")
                            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                                urb_bld = ui.select({"catastro": t["urban_bld_cat"], "osm": t["urban_bld_osm"], "none": t["urban_bld_none"]}, value=safe_select(("catastro", "osm", "none"), urb0.get("buildings", "catastro"), "catastro", label=t["urban_bld"]), label=t["urban_bld"]).props("dense").classes("sl-w-md")
                                urb_as = ui.select({"holes": t["urban_as_holes"], "blocks": t["urban_as_blocks"]}, value=safe_select(("holes", "blocks"), urb0.get("buildings_as", "holes"), "holes", label=t["urban_as"]), label=t["urban_as"]).props("dense").classes("sl-w-md")
                                urb_h = ui.number(t["urban_height"], value=float(urb0.get("building_height", 10.0)), min=0, step=1).props("dense").classes("sl-w-md")
                            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                                st0 = urb0.get("streets", "auto"); st0 = "auto" if st0 is True else ("none" if st0 in (False, None) else st0)
                                urb_streets = ui.select({"auto": t["urban_st_auto"], "catastro": t["urban_st_cat"], "osm": t["urban_st_osm"], "none": t["urban_st_none"]}, value=safe_select(("auto", "catastro", "osm", "none"), st0, "auto", label=t["urban_streets"]), label=t["urban_streets"]).props("dense").classes("sl-w-lg")
                                urb_curb = ui.number(t["urban_curb"], value=float(urb0.get("curb_m", 0.15)), min=0, step=0.05, format="%.2f").props("dense").classes("sl-w-md")
                                urb_brk = ui.switch(t["urban_breaklines"], value=bool(urb0.get("breaklines", True)))
                        inu_warn = ui.label().classes("text-caption text-orange-9")
                    inu_body.bind_visibility_from(inu_on, "value")

                def inu_check():
                    msg = t["inu_whole_warn"].format(s=float(inu_size.value or 50)) if inu_on.value and not inu_region.value else ""
                    inu_warn.set_text(msg)

                shapes = {}                                         # id de la capa de Leaflet -> poligono (dominio o zona)
                colors = {}                                         # id de la capa -> color (para pintar sus vertices al editar)
                region_color = {}                                   # nombre de zona -> color (mapa, leyenda y tabla de zonas)
                DOMAIN_COLOR = "#e63946"; INU_COLOR = "#0077b6"
                PALETTE = ["#f4a261", "#2a9d8f", "#7b2cbf", "#e9c46a", "#ff006e", "#8ac926", "#3a86ff", "#6d4c41"]

                def inu_name():
                    return inu_region.value or None

                def show_extent():
                    if not poly:
                        extent_lbl.set_text(""); extent_warn.set_text(""); return
                    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
                    w_km = (max(xs) - min(xs)) * 111.0 * float(np.cos(np.deg2rad(np.mean(ys)))); h_km = (max(ys) - min(ys)) * 111.0
                    extent_lbl.set_text(f"{t['extent']}: {min(xs):.2f}–{max(xs):.2f}°E · {min(ys):.2f}–{max(ys):.2f}°N · {w_km:.0f} × {h_km:.0f} km · {len(poly)} {t['polygon']}")
                    msgs = []
                    if w_km > 2500 or h_km > 2500:
                        msgs.append(t["extent_big"])
                    try:
                        from ..edition import pro as _pro
                        _pro_data_bathymetry = _pro("data.bathymetry")
                        covers = _pro_data_bathymetry.covers
                        if (bath.value or "").startswith("emodnet") and not covers(bath.value, (min(xs), max(xs)), (min(ys), max(ys))):
                            msgs.append(t["extent_emodnet"])
                    except Exception:   # noqa: BLE001
                        pass
                    extent_warn.set_text(" ".join(msgs))

                def redraw():
                    show_extent()
                    lmap.clear_layers(); shapes.clear(); colors.clear(); legend_box.clear(); region_color.clear()
                    lmap.tile_layer(url_template="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", options={"attribution": "© OpenStreetMap"})
                    items = []
                    show_edges = bool(poly) and (draw_target.value == "edges" or any(v_ != "forced" for v_ in edge_types.values()))
                    if poly:
                        lay_ = lmap.generic_layer(name="polygon", args=[[[p[1], p[0]] for p in poly], {"color": DOMAIN_COLOR, "weight": 1 if show_edges else 3, "fillOpacity": 0.06}])
                        shapes[lay_.id] = None; colors[lay_.id] = DOMAIN_COLOR; items.append((DOMAIN_COLOR, t["domain"], False))
                    if show_edges:                                  # lados del dominio por tipo de contorno
                        for i_ in range(len(poly)):
                            a_, b_ = poly[i_], poly[(i_ + 1) % len(poly)]
                            kd = edge_types.get(i_, "forced")
                            el_ = lmap.generic_layer(name="polyline", args=[[[a_[1], a_[0]], [b_[1], b_[0]]], EDGE_STYLE[kd]])
                            lmap.run_layer_method(el_.id, "bindTooltip", f"{t['edge']} {i_ + 1}: {t['edge_' + kd]}", {"sticky": True})
                        for kd in ("forced", "radiation", "wall"):
                            st_ = EDGE_STYLE[kd]; items.append((st_["color"], t["edge_" + kd], kd == "radiation"))
                    inu = inu_name(); k = 0
                    for rg_ in regions:
                        is_inu = rg_.get("name") == inu
                        col = INU_COLOR if is_inu else PALETTE[k % len(PALETTE)]; k += 0 if is_inu else 1
                        region_color[rg_.get("name")] = col
                        opts = {"color": col, "weight": 3 if is_inu else 2, "fillOpacity": 0.18, **({"dashArray": "6 4"} if is_inu else {})}
                        if rg_.get("polygon"):
                            lay_ = lmap.generic_layer(name="polygon", args=[[[p[1], p[0]] for p in rg_["polygon"]], opts])
                        else:
                            lay_ = lmap.generic_layer(name="rectangle", args=[[[rg_["lat"][0], rg_["lon"][0]], [rg_["lat"][1], rg_["lon"][1]]], opts])
                        shapes[lay_.id] = rg_; colors[lay_.id] = col
                        lmap.run_layer_method(lay_.id, "bindTooltip", rg_.get("name", ""), {"sticky": True})
                        items.append((col, f"{rg_.get('name', '')} · {float(rg_.get('size', 0)):g} m" + (f" · {t['draw_inu'].lower()}" if is_inu else ""), is_inu))
                    with legend_box:
                        for col, lab, dash in items:
                            with ui.row().classes("items-center no-wrap q-gutter-xs"):
                                ui.element("span").style(f"display:inline-block;width:22px;height:12px;background:{col}33;border:2px {'dashed' if dash else 'solid'} {col};border-radius:2px")
                                ui.label(lab)
                    region_list.refresh()

                @ui.refreshable
                def region_list():
                    if not regions:
                        ui.label(t["zones_none"]).classes("text-caption text-grey-6")
                    for rg in regions:
                        col = region_color.get(rg.get("name"), "#999")
                        with ui.row().classes("items-center q-gutter-sm no-wrap"):
                            ui.element("span").style(f"display:inline-block;width:14px;height:14px;background:{col};border-radius:3px")
                            def rename(e, rg=rg):
                                old = rg.get("name"); rg.update(name=e.value); sync_regions(renamed=(old, e.value))
                            ui.input(t["name"], value=rg.get("name", "")).on_value_change(rename).props("dense").classes("sl-w-md")
                            ui.number(t["region_size"], value=float(rg.get("size", 500))).on_value_change(lambda e, rg=rg: rg.update(size=float(e.value))).props("dense").classes("sl-w-sm")
                            ui.number(t["transition"], value=float(rg.get("transition_km", 0)), min=0, step=1).on_value_change(lambda e, rg=rg: rg.update(transition_km=float(e.value))).props("dense").classes("sl-w-md")
                            if rg.get("name") == inu_name():
                                ui.badge(t["draw_inu"], color="blue-8").props("outline")
                            if rg.get("polygon"):
                                ui.label(f"{t['polygon']} · {len(rg['polygon'])} {t['vertices']}").classes("text-caption text-grey-7")
                            else:
                                ui.label(f"lon {rg['lon'][0]:.2f}–{rg['lon'][1]:.2f}, lat {rg['lat'][0]:.2f}–{rg['lat'][1]:.2f}").classes("text-caption text-grey-7")
                            ui.button(icon="close", on_click=lambda rg=rg: (regions.remove(rg), sync_regions(), redraw())).props("flat dense round")
                with zones_box:
                    region_list()

                def region_opts():
                    return {"": t["whole_domain"], **{rg.get("name", f"zona{j + 1}"): rg.get("name", f"zona{j + 1}") for j, rg in enumerate(regions)}}

                def sync_regions(inu=None, renamed=None):
                    """Tras anadir, quitar o renombrar zonas: refresca la lista y los selectores que las usan."""
                    if renamed:
                        old, new = renamed
                        for lay in layers:
                            if lay.get("region") == old:
                                lay["region"] = new
                    else:
                        region_list.refresh()
                    layer_list.refresh()
                    opts = region_opts(); val = inu if inu is not None else inu_region.value
                    if renamed and val == renamed[0]:
                        val = renamed[1]
                    inu_region.set_options(opts, value=val if val in opts else "")
                    cv = coast_reg.value if not (renamed and coast_reg.value == renamed[0]) else renamed[1]
                    coast_reg.set_options(opts, value=cv if cv in opts else "")
                    if inu is not None:
                        inu_on.set_value(True)
                    inu_check()

                inu_region.on_value_change(lambda e: redraw())    # la zona inundable se pinta en azul discontinuo
                for w_ in (inu_on, inu_region, inu_size):
                    w_.on_value_change(lambda e: inu_check())
                redraw(); inu_check()

                editing = {"on": False}

                async def toggle_edit():
                    """Edición de los vértices con Leaflet.draw: arrastrar = mover, clic en un vértice = quitarlo, clic en un
                    punto intermedio = añadir uno. Al terminar se leen las coordenadas y se guardan en el dominio y las zonas."""
                    js_ids = json.dumps(list(shapes))
                    if not editing["on"]:
                        await ui.run_javascript(f"""const m = getElement({lmap.id}).map; const ids = {js_ids};
                            const cols = {json.dumps(colors)};
                            const paint = (l) => {{ const c = cols[l.id]; const g = (l.editing && (l.editing._markerGroup || (l.editing._verticesHandlers && l.editing._verticesHandlers[0] && l.editing._verticesHandlers[0]._markerGroup)));
                                if (!g) return; g.eachLayer(mk => {{ const el = mk._icon; if (!el) return;
                                    const mid = mk._middleLeft !== undefined || (mk.options && mk.options.opacity < 1);
                                    el.style.background = mid ? '#ffffff' : c; el.style.border = '2px solid ' + c; el.style.borderRadius = '3px'; }}); }};
                            m.eachLayer(l => {{ if (ids.includes(l.id) && l.editing) {{ l.editing.enable(); paint(l);
                                if (!l._schismlabPaint) {{ l._schismlabPaint = true; l.on('edit editdrag', () => setTimeout(() => paint(l), 0)); }} }} }});
                            m.on('draw:editvertex draw:editmove draw:editresize', () => m.eachLayer(l => {{ if (ids.includes(l.id)) setTimeout(() => paint(l), 0); }}));
                            return 1;""")
                        editing["on"] = True; edit_btn.props("color=accent"); edit_btn.set_text(t["edit_done"]); ui.notify(t["edit_poly_hint"], timeout=8000)
                        return
                    res = await ui.run_javascript(f"""const m = getElement({lmap.id}).map; const ids = {js_ids}; const out = {{}};
                        m.eachLayer(l => {{ if (ids.includes(l.id)) {{ if (l.editing) l.editing.disable();
                            let ll = l.getLatLngs(); while (Array.isArray(ll[0])) ll = ll[0];
                            out[l.id] = ll.map(p => [Math.round(p.lng * 1e5) / 1e5, Math.round(p.lat * 1e5) / 1e5]); }} }}); return out;""")
                    editing["on"] = False; edit_btn.props("color=primary"); edit_btn.set_text(t["edit_polys"])
                    for lid, pts in (res or {}).items():
                        tgt = shapes.get(lid, "missing")
                        if tgt == "missing" or len(pts) < 3:
                            continue
                        if tgt is None:
                            if len(pts) != len(poly):
                                edge_types.clear()                  # cambia el numero de lados: los tipos se reinician
                            poly.clear(); poly.extend(pts)
                        elif tgt.get("polygon"):
                            tgt["polygon"] = pts
                        else:
                            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                            tgt.update(lon=[min(xs), max(xs)], lat=[min(ys), max(ys)])
                    redraw(); ui.notify(t["polys_updated"], type="positive")
                edit_btn.on_click(toggle_edit)
                clear_btn.on_click(lambda: (poly.clear(), regions.clear(), sync_regions(), redraw()))

                async def fit_domain():
                    if poly:
                        try:
                            await lmap.run_map_method("fitBounds", [[min(p_[1] for p_ in poly), min(p_[0] for p_ in poly)], [max(p_[1] for p_ in poly), max(p_[0] for p_ in poly)]], {"padding": [30, 30]})
                        except Exception:   # noqa: BLE001
                            pass
                ui.timer(0.8, fit_domain, once=True); ui.timer(2.5, fit_domain, once=True)   # reintento: el mapa puede no estar listo

                def on_draw(e):
                    layer = e.args["layer"]; latlngs = layer.get("_latlngs", [[]])[0]
                    pts = [[round(p["lng"], 4), round(p["lat"], 4)] for p in latlngs]
                    if not pts:
                        return
                    if draw_target.value == "edges":
                        return
                    if draw_target.value == "domain":
                        poly.clear(); poly.extend(pts); edge_types.clear()
                    else:
                        lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
                        names = {r_.get("name") for r_ in regions}
                        if draw_target.value == "inu":                            # zona inundable: zona de detalle con el tamano en tierra
                            nm = next(n_ for n_ in ["inundacion"] + [f"inundacion{k}" for k in range(2, 99)] if n_ not in names)
                            rg = {"name": nm, "size": float(inu_size.value), "transition_km": float(inu_tr.value)}
                        else:
                            nm = next(f"zona{k}" for k in range(len(regions) + 1, 999) if f"zona{k}" not in names)
                            rg = {"name": nm, "size": float(res_min.value) / 2, "transition_km": 0}
                        if layer.get("_mRadius") is None and len(pts) != 4 or (len(pts) == 4 and len({round(p, 4) for p in lons}) > 2):
                            rg["polygon"] = pts                                   # poligono dibujado
                        else:
                            rg.update(lon=[min(lons), max(lons)], lat=[min(lats), max(lats)])
                        regions.append(rg)
                        sync_regions(inu=nm if draw_target.value == "inu" else None)
                        if draw_target.value == "inu":
                            ui.notify(t["inu_zone_drawn"], type="positive")
                    redraw()
                lmap.on("draw:created", on_draw)

                def on_edge_click(e):
                    """Modo «Tipo de contorno»: un clic junto a un lado del dominio cambia su tipo (forzado -> radiación -> pared)."""
                    if draw_target.value != "edges" or len(poly) < 3:
                        return
                    ll = (e.args or {}).get("latlng") or {}
                    if "lat" not in ll:
                        return
                    from shapely.geometry import LineString, Point
                    kk = float(np.cos(np.deg2rad(float(ll["lat"]))))
                    pt = Point(float(ll["lng"]) * kk, float(ll["lat"]))
                    d_ = [LineString([(poly[i_][0] * kk, poly[i_][1]), (poly[(i_ + 1) % len(poly)][0] * kk, poly[(i_ + 1) % len(poly)][1])]).distance(pt) for i_ in range(len(poly))]
                    i_ = int(np.argmin(d_)); span = max(max(p_[0] for p_ in poly) - min(p_[0] for p_ in poly), max(p_[1] for p_ in poly) - min(p_[1] for p_ in poly))
                    if d_[i_] > 0.08 * span:
                        return
                    order = ["forced", "radiation", "wall"]
                    edge_types[i_] = order[(order.index(edge_types.get(i_, "forced")) + 1) % 3]
                    ui.notify(f"{t['edge']} {i_ + 1}: {t['edge_' + edge_types[i_]]}", timeout=2500)
                    redraw()
                lmap.on("map-click", on_edge_click, ["latlng"])

        # --- dominio idealizado --------------------------------------------------------------
        with ideal, ui.card().classes("q-pa-md w-full"):
            card_title(2, t["gen_ideal"], "crop_square")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                geo = ui.switch(t["geo"], value=PRO and "lon" in m and "lat" in m)
                geo.set_visibility(PRO)                     # dominios en lon/lat: SCHISMlab Pro
                Lx = ui.number(t["Lx"], value=float(m.get("Lx", 100e3))); Ly = ui.number(t["Ly"], value=float(m.get("Ly", 50e3)))
                lon_i = ui.input(t["lon_rng"], value=",".join(map(str, m.get("lon", [0, 2])))); lat_i = ui.input(t["lat_rng"], value=",".join(map(str, m.get("lat", [39, 40]))))
                lon_i.set_visibility(PRO); lat_i.set_visibility(PRO)
                dx = ui.number(t["dx"], value=float(m.get("dx", 2000)))
            geo_size = ui.label().classes("text-caption text-grey-7")
            geo_warn = ui.label(t["geo_cor_warn"]).classes("text-caption text-orange-9")
            def _geo_vis():
                g = bool(geo.value)
                for w in (Lx, Ly): w.set_enabled(not g)
                for w in (lon_i, lat_i): w.set_enabled(g)
                geo_warn.set_visibility(not g); geo_size.set_visibility(g)
                if g:
                    try:
                        lo = [float(v) for v in lon_i.value.split(",")]; la = [float(v) for v in lat_i.value.split(",")]
                        ly = 111.2 * (la[1] - la[0]); lx = 111.2 * (lo[1] - lo[0]) * np.cos(np.deg2rad(0.5 * (la[0] + la[1])))
                        geo_size.set_text(t["geo_size"].format(lx=lx, ly=ly))
                    except (ValueError, IndexError):
                        geo_size.set_text("")
            geo.on_value_change(lambda e: _geo_vis()); lon_i.on_value_change(lambda e: _geo_vis()); lat_i.on_value_change(lambda e: _geo_vis()); _geo_vis()
            b = m.get("bathymetry", 50); b = 50.0 if isinstance(b, (str, list)) else b; kind0 = b.get("kind", "flat") if isinstance(b, dict) else "flat"
            from ..mesh.analytic import BOTTOMS, bottom_example
            _lg = S().get("lang", "es")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                _kinds = {k_: v_[_lg if _lg in ("es", "en") else "es"] for k_, v_ in BOTTOMS.items()}
                kind = ui.select(_kinds, value=safe_select(_kinds, kind0, "flat", label=t["depth"]), label=t["depth"]).classes("sl-w-md")
                h = ui.number(t["depth_h"], value=float(b if not isinstance(b, dict) else b.get("h", 50)))
                params = ui.input(t["bathy_params"], value=json.dumps({k: v for k, v in (b.items() if isinstance(b, dict) else []) if k not in ("kind", "formula")})).style("min-width:min(520px, 100%)")
                formula = ui.input(t["bathy_formula"], value=str((b.get("formula", "") if isinstance(b, dict) else "")), placeholder="100 - 80*exp(-((x-150e3)**2 + (y-60e3)**2)/(2*20e3**2))").classes("sl-w-lg")
            bdoc = ui.markdown().classes("text-caption sl-bottom-doc").mark("bottom_doc")
            def _domain():
                """Extensión del dominio en las coordenadas de la malla (m desde la esquina SW, o grados en lon/lat)."""
                try:
                    if geo.value:
                        lo = [float(v) for v in lon_i.value.split(",")]; la = [float(v) for v in lat_i.value.split(",")]
                        return lo[0], lo[1], la[0], la[1]
                    return 0.0, float(Lx.value), 0.0, float(Ly.value)
                except (ValueError, IndexError, TypeError):
                    return 0.0, 100e3, 0.0, 100e3
            def _bdoc():
                k_ = kind.value; d_ = BOTTOMS.get(k_, BOTTOMS["flat"]); i_ = 0 if _lg == "es" else 1
                units = t["bottom_units_geo"] if geo.value else t["bottom_units_m"]
                parts = [f"**{d_[_lg if _lg in ('es', 'en') else 'es']}**: `depth = {d_['formula']}` ({units})"]
                if d_["params"]:
                    parts.append("\n".join(f"- `{p_}`: {txt[i_]}" for p_, txt in d_["params"].items()))
                if k_ not in ("flat", "expression"):
                    parts.append(t["bottom_example"] + " `" + json.dumps(bottom_example(k_, *_domain())) + "`")
                if k_ == "expression":
                    parts.append(t["bottom_expr_help"])
                bdoc.set_content("\n\n".join(parts))
            def _bvis(): h.set_visibility(kind.value == "flat"); params.set_visibility(kind.value not in ("flat", "expression")); formula.set_visibility(kind.value == "expression"); _bdoc()
            def _on_kind(e):
                if e.value not in ("flat", "expression"):          # parámetros de ejemplo del fondo nuevo, ajustados al dominio
                    params.set_value(json.dumps(bottom_example(e.value, *_domain())))
                _bvis()
            kind.on_value_change(_on_kind); _bvis()
            for _w in (geo, lon_i, lat_i, Lx, Ly):                  # el ejemplo sigue al tamaño del dominio
                _w.on_value_change(lambda e: _bdoc())
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                ui.label(t["open_sides"]).classes("text-subtitle2")
                _open = [str(s_).upper() for s_ in (m.get("open_sides") or [])]; _st = {str(k_).upper(): v_ for k_, v_ in (m.get("side_types") or {}).items()}
                side_sel = {}
                for s_ in ("W", "E", "S", "N"):
                    side_sel[s_] = ui.select({"wall": t["edge_wall"], "forced": t["edge_forced"], "radiation": t["edge_radiation"]},
                                             value=(_st.get(s_, "forced") if s_ in _open else "wall"), label=t["side_" + s_]).classes("sl-w-md")
        _vis(gen.value)

        # --- guardar y generar -----------------------------------------------------------------
        def collect():
            c2 = cfg(); mm = c2.setdefault("mesh", {}); mm["generator"] = gen.value
            if gen.value == "file":
                mm["file"] = (mfile.value or "").strip()
                return c2
            if gen.value == "idealized":
                mm["dx"] = float(dx.value)
                mm["open_sides"] = [s_ for s_ in ("W", "E", "S", "N") if side_sel[s_].value != "wall"]
                st_ = {s_: side_sel[s_].value for s_ in mm["open_sides"] if side_sel[s_].value != "forced"}
                if st_: mm["side_types"] = st_
                else: mm.pop("side_types", None)
                if geo.value:
                    mm["lon"] = [float(v) for v in lon_i.value.split(",")]; mm["lat"] = [float(v) for v in lat_i.value.split(",")]; mm.pop("Lx", None); mm.pop("Ly", None)
                else:
                    mm["Lx"] = float(Lx.value); mm["Ly"] = float(Ly.value); mm.pop("lon", None); mm.pop("lat", None)
                try:
                    extra = json.loads(params.value or "{}") if kind.value != "flat" else {}
                    if not isinstance(extra, dict):
                        raise ValueError("JSON")
                except (ValueError, TypeError):
                    ui.notify(t["bathy_params_bad"], type="warning"); extra = {}
                if kind.value == "expression":
                    mm["bathymetry"] = {"kind": "expression", "formula": (formula.value or "").strip()}
                else:
                    mm["bathymetry"] = float(h.value) if kind.value == "flat" else {"kind": kind.value, **extra}
                mm.pop("polygon", None)
            else:
                mm["polygon"] = [list(p) for p in poly]; mm.pop("lon", None); mm.pop("lat", None)
                base = bath_file.value.strip() if (bath_file.value or "").strip() else bath.value

                mm["bathymetry"] = ([{"source": base}] + [dict(l) for l in layers]) if layers else base
                mm["resolution"] = {"min": float(res_min.value), "max": float(res_max.value), "max_nearshore": float(res_ns.value),
                                    "feature_size": float(fs.value), "wavelength": float(wl.value), "slope": float(slp.value), "grade": float(grade.value),
                                    "regions": [dict(rg) for rg in regions]}
                from ..edition import pro as _pro
                _pro_mesh_sizing = _pro("mesh.sizing")
                parse_depth_sizes = _pro_mesh_sizing.parse_depth_sizes
                ds_ = parse_depth_sizes(dsz.value or "")
                if ds_:
                    mm["resolution"]["depth_sizes"] = ds_
                mm["open_boundaries"] = "bbox" if open_b.value else "none"
                et_ = {i_: v_ for i_, v_ in sorted(edge_types.items()) if v_ != "forced" and i_ < len(poly)}
                if et_:
                    mm["edge_types"] = et_
                else:
                    mm.pop("edge_types", None)
                mm["min_depth"] = float(mindep.value if mindep.value is not None else 1.0)
                if coast.value == "osm":
                    mm["coastline"] = "osm"
                    if coast_reg.value:
                        mm["coastline_region"] = coast_reg.value
                    else:
                        mm.pop("coastline_region", None)
                elif coast.value == "gshhg":
                    mm["coastline"] = "gshhg"; mm.pop("coastline_region", None)
                elif mm.get("coastline") in ("osm", "gshhg", "auto"):
                    mm.pop("coastline", None); mm.pop("coastline_region", None)
                if inu_on.value:
                    mm["inundation"] = {"region": inu_region.value or None, "max_elevation": float(inu_elev.value),
                                        "dem": (inu_file.value or "").strip() or inu_dem.value, "size": float(inu_size.value), "transition_km": float(inu_tr.value),
                                        "contours": float(inu_ct.value or 0)}
                    if inu_lo.value:
                        mm["inundation"]["land_only"] = True
                    if urb_on.value:
                        mm["inundation"]["urban"] = {"buildings": urb_bld.value, "building_height": float(urb_h.value or 0),
                                                     "streets": urb_streets.value, "curb_m": float(urb_curb.value or 0), "size": float(urb_size.value or 4),
                                                     "mesh": urb_mesh.value, "buildings_as": urb_as.value, "breaklines": bool(urb_brk.value)}
                else:
                    mm.pop("inundation", None)
            return c2

        actions = ui.row().classes("sl-actions q-gutter-sm q-py-sm q-px-md items-center w-full")
        log = ui.log(max_lines=300).classes("w-full h-40").style("display:none")
        result = ui.column().classes("w-full")

        @ui.refreshable
        def show_result():
            wd = workdir()
            if not (wd / "hgrid.gr3").exists():
                return
            from ..mesh.view import load as load_view, stats as view_stats, render as render_view, legend as view_legend
            from ..estimate import estimate, fmt_range, default_local_cores
            lang = S().get("lang", "es")
            from ..mesh.view import cfl_stats, CFL_MIN
            d = load_view(wd); vs = view_stats(d)
            q = json.loads((wd / "mesh_quality.json").read_text()) if (wd / "mesh_quality.json").exists() else {}
            c_now = cfg(); nn = int(len(d["x"]))
            d["dt"] = float((c_now.get("time") or {}).get("dt", 100) or 100); cs = cfl_stats(d, d["dt"])
            geographic = float(np.abs(d["x"]).max()) <= 360 and float(np.abs(d["y"]).max()) <= 90
            with ui.element("div").classes("q-mt-md"):
                card_title({"idealized": 3, "file": 2}.get(gen.value, 6), t["mesh_view"], "insights")
            _sep = "." if lang == "es" else ","
            def _n(v):                                        # millares con espacio fino y decimal según idioma
                return fmt_num(v, lang)
            with ui.row().classes("q-gutter-sm q-mb-sm"):
                cards = [(t["nodes"], _n(nn)), (t["elements"], _n(len(d['tri']))),
                         (t["res_stats"], f"{_n(vs['size_p5'])} / {_n(vs['size_p50'])} / {_n(vs['size_p95'])} m"),
                         (t["res_range"], f"{_n(vs['size_min'])} – {_n(vs['size_max'])} m"),
                         *([(t["res_short"], f"{_n(vs['short_p50'])} m")] if vs.get("short_p50") else []),
                         (t["angle_stats"], f"{fmt_num(vs['angle_min'], lang, 1)}° · {vs['angle_lt20']} < 20°"),
                         (t["depth_range"], f"{_n(float(d['depth'].min()))} – {_n(float(d['depth'].max()))} m")]
                for lab, val in cards:
                    with ui.card().classes("q-pa-sm").style("min-width:140px"):
                        ui.label(lab).classes("text-caption text-grey-7"); ui.label(val).classes("text-subtitle1 text-weight-bold")
                bad = cs["cfl_lt04"]; dark_ = bool(S().get("dark"))
                col = ("green-10" if bad < 1 else ("orange-10" if bad < 10 else "red-10")) if dark_ else ("green-1" if bad < 1 else ("orange-1" if bad < 10 else "red-1"))
                dec = lambda v: fmt_num(v, lang, 2)
                with ui.card().classes(f"q-pa-sm bg-{col}").style("min-width:220px"):
                    ui.label(t["cfl_card"].format(dt=d["dt"])).classes("text-caption text-grey-8")
                    ui.label(t["cfl_val"].format(p5=dec(cs["cfl_p5"]), pct=fmt_num(bad, lang, 1), lim=dec(CFL_MIN))).classes("text-subtitle1 text-weight-bold")
                    ui.label(t["cfl_dt"].format(dt=f"{cs['dt_needed']:.0f}")).classes("text-caption")
                    ui.tooltip(t["cfl_tip"]).style("max-width:360px; font-size:12px")
            el_ = estimate(c_now, nn); ec_ = estimate(c_now, nn, 128, cluster=True)
            with ui.row().classes("q-gutter-sm q-mb-sm items-stretch"):
                for lab, e_ in ((f"{t['est_local']} ({el_['nprocs']} {t['est_procs']})", el_), (t["est_cluster"], ec_)):
                    with ui.card().classes("q-pa-sm " + ("bg-blue-10" if S().get("dark") else "bg-blue-1")).style("min-width:260px"):
                        ui.label(lab).classes("text-caption text-grey-8"); ui.label(fmt_range(e_, lang)).classes("text-h6 text-primary")
                with ui.column().classes("justify-center"):
                    ui.label(t["est_summary"].format(days=el_['days'], dt=el_['dt'], nvrt=el_['nvrt'], steps=_n(el_['steps'])) + (" · WWM" if el_["waves"] else "")).classes("text-caption")
                    ui.label(t["est_with"]).classes("text-caption text-grey-7")
                    ui.label(t["est_mine"].format(n=el_["calibrated_runs"]) if el_["calibrated_runs"] else t["est_ref"]).classes("text-caption text-grey-7")
            layer = ui.toggle({"size": t["layer_size"], "depth": t["layer_depth"], "quality": t["layer_quality"], "cfl": "CFL", "mesh": t["layer_mesh"]}, value="size").props("dense no-caps")
            with ui.row().classes("w-full items-start q-col-gutter-md"):
                with ui.column().classes("col-12 col-lg-8"):
                    leg = ui.image().style("width:100%;max-width:520px;height:66px").props("fit=contain")
                    imported = (c_now.get("mesh", {}) or {}).get("generator") == "file"
                    can_refine = (c_now.get("mesh", {}) or {}).get("generator", default_generator()) in ("ocsmesh", "oceanmesh2d")   # idealizado: la zona se perdería
                    if geographic:
                        ui.label(t["view_hint_file"] if imported else t["view_hint_edit"]).classes("text-caption text-grey-7")
                        cx, cy = float(d["x"].mean()), float(d["y"].mean())
                        with ui.element("div").classes("w-full").style("position:relative"):
                            vmap = ui.leaflet(center=(cy, cx), zoom=6, draw_control={
                                "draw": {"polygon": True, "rectangle": True, "marker": False, "circle": False, "circlemarker": False, "polyline": False},
                                "edit": {"edit": False, "remove": False}}, hide_drawn_items=True).classes("w-full").style("height:600px")
                            probe_box = ui.html("").style("position:absolute; top:10px; right:10px; z-index:1000; background:rgba(255,255,255,0.93); "
                                                          "padding:6px 10px; border-radius:6px; font-size:12px; line-height:1.45; "
                                                          "box-shadow:0 1px 4px rgba(0,0,0,.3); pointer-events:none; min-width:190px; display:none")
                    else:
                        static = ui.image().classes("w-full")
                with ui.column().classes("col-12 col-lg-4"):
                    import plotly.graph_objects as go
                    from .figures import themed as _themed
                    ed = vs["hist_edges"]; mid = [float(np.sqrt(ed[i] * ed[i + 1])) for i in range(len(ed) - 1)]
                    hfig = go.Figure(go.Bar(x=mid, y=vs["hist_counts"], marker_color="#1fa2c4", width=[ed[i + 1] - ed[i] for i in range(len(ed) - 1)]))
                    hfig.update_layout(title=dict(text=t["hist_title"], font=dict(size=13)), xaxis=dict(type="log", title="m"), yaxis_title=t["elements"],
                                       margin=dict(l=40, r=10, t=36, b=36), height=300, bargap=0)
                    ui.plotly(_themed(hfig, dark_)).classes("w-full").style("height:300px")
            vstate = {"ov": None, "seq": 0}

            def _set_legend():
                leg.set_source(view_legend(d, layer.value, lang) or "")

            if geographic:
                async def refresh_overlay(*_):
                    vstate["seq"] += 1; my = vstate["seq"]
                    try:
                        b = await vmap.run_map_method("getBounds")
                        sw, ne_ = b["_southWest"], b["_northEast"]
                        bounds = (float(sw["lng"]), float(sw["lat"]), float(ne_["lng"]), float(ne_["lat"]))
                    except Exception:   # noqa: BLE001
                        bounds = (float(d["x"].min()), float(d["y"].min()), float(d["x"].max()), float(d["y"].max()))
                    r = await run.io_bound(render_view, d, layer.value, bounds, 1200)
                    if my != vstate["seq"]:
                        return                                  # llegó otra vista mientras se dibujaba
                    if vstate["ov"] is not None:
                        vmap.remove_layer(vstate["ov"]); vstate["ov"] = None
                    if r:
                        vstate["ov"] = vmap.image_overlay(url=r[0], bounds=r[1], options={"opacity": 0.85})

                async def fit():
                    try:
                        await vmap.run_map_method("fitBounds", [[float(d["y"].min()), float(d["x"].min())], [float(d["y"].max()), float(d["x"].max())]])
                    except Exception:   # noqa: BLE001
                        pass
                    await refresh_overlay()
                vmap.on("map-moveend", refresh_overlay)
                from ..mesh.view import probe as probe_at

                def on_hover(e):
                    ll = (e.args or {}).get("latlng") or {}
                    if "lat" not in ll:
                        return
                    v = probe_at(d, float(ll["lng"]), float(ll["lat"]))
                    if v is None:
                        probe_box.style("display:none"); return
                    fd = (lambda x, n=1: f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")) if lang == "es" else (lambda x, n=1: f"{x:,.{n}f}")
                    sel = layer.value
                    rows = [(t["layer_size"], f"{fd(v['size'], 0)} m", sel == "size"),
                            (t["layer_depth"], f"{fd(v['depth'])} m" + (f" ({t['land_s']})" if v["depth"] < 0 else ""), sel == "depth"),
                            (t["layer_quality"], f"{fd(v['minang'])}°", sel == "quality"),
                            ("CFL", fd(v["cfl"], 2) + (" ⚠" if v["cfl"] < 0.4 else ""), sel == "cfl")]
                    html_ = f"<div style='color:#555'>{float(ll['lat']):.5f}° N, {float(ll['lng']):.5f}° E</div>"
                    html_ += "".join(f"<div{' style=\"font-weight:700;color:#0d47a1\"' if b_ else ''}>{a_}: {c_}</div>" for a_, c_, b_ in rows)
                    html_ += f"<div style='color:#777'>{t['node_s']} {v['node']} ({fd(v['node_depth'])} m) · {t['element_s']} {v['element']}</div>"
                    probe_box.set_content(html_); probe_box.style("display:block")
                vmap.on("map-mousemove", on_hover, ["latlng"], throttle=0.12)
                vmap.on("map-mouseout", lambda e: probe_box.style("display:none"))
                ui.timer(0.8, fit, once=True); ui.timer(2.5, fit, once=True)   # reintento: el mapa puede no estar listo

                edits = c_now.setdefault("mesh", {}).setdefault("bathymetry_edits", [])
                ops = {"set": t["edit_set"], "min_depth": t["edit_min"], "max_depth": t["edit_max"], "offset": t["edit_offset"], "smooth": t["edit_smooth"]}

                def save_edits():
                    c2 = cfg(); c2.setdefault("mesh", {})["bathymetry_edits"] = [dict(e_) for e_ in edits]
                    if not edits:
                        c2["mesh"].pop("bathymetry_edits", None)
                    save_cfg(case_path(), c2); edit_list.refresh()

                async def apply_edits_now():
                    from ..mesh.edits import sync_edits
                    mc = (cfg().get("mesh") or {})
                    try:
                        await run.io_bound(sync_edits, workdir(), mc)
                    except Exception as ex:   # noqa: BLE001
                        ui.notify(str(ex), type="negative"); return
                    ui.notify(t["edits_applied"], type="positive"); show_result.refresh()

                def draw_edits():
                    for e_ in edits:
                        vmap.generic_layer(name="polygon", args=[[[p_[1], p_[0]] for p_ in e_["polygon"]], {"color": "#7b2cbf", "weight": 2, "fill": False, "dashArray": "4 4"}])

                def on_view_draw(e):
                    lyr = e.args.get("layer", {}); latlngs = (lyr.get("_latlngs") or [[]])[0]
                    pts = [[round(pp["lng"], 5), round(pp["lat"], 5)] for pp in latlngs]
                    if len(pts) < 3:
                        return
                    from ..mesh.edits import _inside
                    inside = _inside(d["x"], d["y"], pts); dep = d["depth"][inside]
                    with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width:460px"):
                        if dep.size:
                            ui.label(t["edit_inside"].format(n=f"{int(inside.sum()):,}".replace(",", _sep), a=float(dep.min()), b=float(np.median(dep)), c=float(dep.max()))).classes("text-caption text-grey-7")
                        else:
                            ui.label(f"0 {t['nodes']}").classes("text-caption text-orange-9")
                        with ui.tabs().props("dense no-caps align=left") as tabs:
                            tab_edit = ui.tab(t["edit_tab"], icon="landscape")
                            tab_ref = ui.tab(t["refine_tab"], icon="grid_on") if can_refine else None
                        with ui.tab_panels(tabs, value=tab_ref or tab_edit).classes("w-full"):
                            with ui.tab_panel(tab_edit):
                                eop = ui.select(ops, value="set", label=t["edit_op"]).props("dense").classes("sl-w-lg")
                                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                                    evl = ui.number(t["edit_value"], value=round(float(np.median(dep)), 1) if dep.size else 5.0, step=0.5).props("dense").classes("sl-w-sm")
                                    eit = ui.number(t["edit_iter"], value=5, min=1, max=100, step=1).props("dense").classes("sl-w-sm")
                                eit.bind_visibility_from(eop, "value", backward=lambda v: v == "smooth")
                                evl.bind_visibility_from(eop, "value", backward=lambda v: v != "smooth")

                                def add_edit():
                                    ed_ = {"name": f"retoque{len(edits) + 1}", "op": eop.value, "polygon": pts}
                                    if eop.value == "smooth":
                                        ed_["iterations"] = int(eit.value or 5)
                                    else:
                                        ed_["value"] = float(evl.value or 0.0)
                                    edits.append(ed_); save_edits(); dlg.close(); ui.notify(t["edit_added"], type="positive")
                                    return ed_
                                async def add_and_apply():
                                    add_edit(); await apply_edits_now()
                                with ui.row().classes("q-mt-sm"):
                                    ui.button(t["edits_apply"], icon="check", on_click=add_and_apply).props("color=accent")
                                    ui.button(t["save"], icon="add", on_click=add_edit).props("outline")
                                    ui.button("✕", on_click=dlg.close).props("flat")
                            if tab_ref is not None:
                                with ui.tab_panel(tab_ref):
                                    rn = ui.input(t["name"], value=f"zona{len(regions) + 1}").props("dense")
                                    rsz = ui.number(t["region_size"], value=float(max(10.0, round(vs["size_p5"] / 2, -1))), min=5, step=10).props("dense")
                                    rtr = ui.number(t["transition"], value=2.0, min=0, step=0.5).props("dense")

                                    def accept():
                                        regions.append({"name": rn.value or f"zona{len(regions) + 1}", "size": float(rsz.value), "transition_km": float(rtr.value), "polygon": pts})
                                        sync_regions(); redraw(); save_cfg(case_path(), collect()); dlg.close()
                                        ui.notify(t["zone_added"], type="positive", timeout=8000)
                                    with ui.row():
                                        ui.button(t["save"], icon="add", on_click=accept).props("color=accent")
                                        async def accept_and_regen():
                                            accept(); await generate()
                                        ui.button(t["regenerate"], icon="grid_on", on_click=accept_and_regen).props("outline")
                                        ui.button("✕", on_click=dlg.close).props("flat")
                    dlg.open()
                vmap.on("draw:created", on_view_draw)
                ui.timer(1.0, draw_edits, once=True)

                @ui.refreshable
                def edit_list():
                    from ..mesh.edits import applied_edits, edits_cfg
                    try:
                        done_ = applied_edits(workdir()) or []
                        pending = done_ != edits_cfg({"bathymetry_edits": edits})
                    except Exception:   # noqa: BLE001
                        done_, pending = [], True
                    if not edits and not done_:
                        return
                    with ui.card().classes("q-pa-md w-full q-mt-sm"):
                        ui.label(t["edits"]).classes("text-subtitle1 text-weight-bold")
                        ui.label(t["edits_hint"]).classes("text-caption text-grey-7")
                        for i_, e_ in enumerate(edits):
                            with ui.row().classes("items-center q-gutter-sm"):
                                ui.icon("landscape", color="purple")
                                val_ = f"{e_.get('iterations', 5)} ×" if e_["op"] == "smooth" else f"{float(e_.get('value', 0)):g} m"
                                ui.label(f"{i_ + 1}. {e_.get('name', '')} · {ops.get(e_['op'], e_['op'])} · {val_} · {len(e_['polygon'])} {t['vertices']}")
                                ui.button(icon="close", on_click=lambda _, i_=i_: (edits.pop(i_), save_edits())).props("flat dense round")
                        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                            ui.button(t["edits_apply"], icon="check", on_click=apply_edits_now).props("color=accent" if pending else "outline")
                            if pending:
                                ui.label(t["edits_pending"]).classes("text-caption text-orange-9")
                edit_list()
                async def on_layer(e):
                    _set_legend(); await refresh_overlay()
                layer.on_value_change(on_layer)
            else:
                def _static():
                    r = render_view(d, layer.value, (float(d["x"].min()), float(d["y"].min()), float(d["x"].max()), float(d["y"].max())), 1200, merc=False)
                    static.set_source(r[0] if r else "")
                layer.on_value_change(lambda e: (_set_legend(), _static())); _static()
            _set_legend()

        async def generate():
            c2 = collect(); save_cfg(case_path(), c2)
            if gen.value == "file" and not (mfile.value or "").strip():
                ui.notify(t["file_path"], type="warning"); return
            if gen.value not in ("idealized", "file") and not poly:
                ui.notify(t["draw_hint"], type="warning"); return
            if gen.value not in ("idealized", "file") and poly:
                xs_, ys_ = [float(p_[0]) for p_ in poly], [float(p_[1]) for p_ in poly]
                dx_, dy_ = max(xs_) - min(xs_), max(ys_) - min(ys_)
                if dx_ * dy_ > 16:                      # dominio enorme (>4° × 4°): casi siempre un polígono mal dibujado
                    ui.notify(t["domain_big"].format(dx=dx_, dy=dy_, km=dx_ * 111 * np.cos(np.deg2rad(np.mean(ys_)))), type="warning", timeout=10000)
                if float(res_ns.value or 0) < float(res_min.value or 0):   # refinaria toda la costa del dominio
                    ui.notify(t["ns_lt_min"].format(ns=float(res_ns.value), mn=float(res_min.value)), type="warning", timeout=10000)
                for rg_ in (c2.get("mesh", {}).get("resolution", {}) or {}).get("regions") or []:
                    if float(rg_.get("size", 1e9)) < 25:                 # dt ~ tamano / sqrt(g h): con 10 m, menos de 1 s
                        ui.notify(t["zone_tiny"].format(name=rg_.get("name", "?"), size=float(rg_["size"])), type="warning", timeout=10000)
            log.style("display:block"); log.clear()
            from ..case import Case
            from ..mesh.build import build_mesh
            cp = case_path()                                   # app.storage.user no es accesible desde el hilo de trabajo
            gen_btn.disable(); stop_mesh_btn.set_visibility(True)
            try:
                await run_job_process("schismlab.mesh.build:build_mesh_from_yaml", (str(cp),), log,
                                      on_done=lambda r: (show_result.refresh(), ui.notify(t["done"], type="positive")), key=f"{workdir()}:mesh")
            finally:
                gen_btn.enable(); stop_mesh_btn.set_visibility(False); show_result.refresh()

        with actions:                                   # barra fija abajo: siempre a mano tras cambiar algo
            ui.button(t["save"], icon="save", on_click=lambda: save(collect())).props("outline color=primary")
            gen_btn = ui.button(t["gen_mesh"], icon="grid_on", on_click=generate).props("color=accent unelevated").mark("gen_mesh_btn")
            ui.button(t["save_next"], icon="arrow_forward", on_click=lambda: (save(collect()), ui.navigate.to(next_step("mesh")))).props("color=accent unelevated")
            def stop_mesh():
                j = _JOBS.get(f"{workdir()}:mesh")
                if j is not None and not j.done and hasattr(j, "stop"):
                    j.stop()
            stop_mesh_btn = ui.button(t["stop_run"], icon="stop", on_click=stop_mesh).props("color=negative"); stop_mesh_btn.set_visibility(False)
        # al volver a la página con un mallado en marcha: recuperar su registro y seguirlo hasta que acabe
        prev_m = _JOBS.get(f"{workdir()}:mesh")
        if prev_m is not None and not prev_m.done:
            log.style("display:block"); log.clear(); gen_btn.disable(); stop_mesh_btn.set_visibility(True)
            shown_m = {"n": 0}
            def follow_m():
                for line in prev_m.lines[shown_m["n"]:]:
                    log.push(line)
                shown_m["n"] = len(prev_m.lines)
                if prev_m.done:
                    mtimer.active = False; gen_btn.enable(); stop_mesh_btn.set_visibility(False); show_result.refresh()
                    ui.notify(t["done"] if prev_m.error is None else f"{t['failed']}: {prev_m.error}", type="positive" if prev_m.error is None else "negative")
            mtimer = ui.timer(1.0, follow_m)
            ui.notify(t["mesh_in_progress"], type="info")
            ui.label(t["mesh_actions_hint"]).classes("text-caption text-grey-7")
        with result:
            show_result()


# ----------------------------------------------------------------------------- modelo
@ui.page("/model")
def page_model():
    t = T()
    with layout("model"):
        if need_case():
            return
        c = cfg(); tm = c.setdefault("time", {}); v = c.setdefault("vertical", {"type": "2d"}); ph = c.setdefault("physics", {}); ic = c.setdefault("initial", {})
        ui.label(t["step_model"]).classes("text-h4 text-primary"); build_chip(c)
        from ..build import installed
        builds = installed()
        from ..build import effective_build as _eb
        _bn, _bm, _bb = _eb(c)
        with ui.expansion(t["build_card"], icon="memory", caption=f"pschism_{_bn} · " + ", ".join(_bm) + ("" if _bb else f" · {t['not_compiled']}"), value=False).classes("sl-exp w-full"):
            ui.label(t["build_hint"]).classes("text-caption text-grey-7")
            opts = {"": t["build_auto"]}
            opts.update({n: f"pschism_{n}  ·  " + ", ".join(i["modules"]) for n, i in builds.items()})
            curb = c.get("build") or ""
            if curb and curb not in opts:
                opts[curb] = f"pschism_{curb}  ·  {t['build_none']}"
            def set_build(e):
                c2 = cfg()
                if e.value:
                    c2["build"] = e.value
                    if "wwm" in (builds.get(e.value, {}).get("modules") or []) and not (c2.get("waves") or {}).get("enabled"):
                        c2["waves"] = {**(c2.get("waves") or {}), "enabled": True}
                        ui.notify(t["waves_auto_on"], type="info")
                else:
                    c2.pop("build", None)
                save_cfg(case_path(), c2); ui.navigate.reload()
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                ui.select(opts, value=curb, on_change=set_build).classes("sl-w-xl")
                ui.button(t["install"], icon="build", on_click=lambda: ui.navigate.to("/install")).props("flat dense")
        lang_ = S().get("lang", "es")
        with ui.expansion(t["time"], icon="schedule", value=True).classes("sl-exp w-full") as exp_time:
            with ui.row().classes("row wrap q-col-gutter-sm"):
                start = ui.input(t["start"], value=str(tm.get("start", "2020-01-01"))[:10]).props("type=date").classes("sl-w-md")
                days = ui.number(t["days"], value=float(tm.get("days", 2)), min=0.01, step=0.5).classes("sl-w-sm")
                dt = ui.number(t["dt"], value=float(tm.get("dt", 60)), min=1, step=10).classes("sl-w-sm")
                ramp = ui.number(t["ramp"], value=float(tm.get("ramp_days", 0.5)), min=0, step=0.25).classes("sl-w-sm")
            def time_caption():
                set_caption(exp_time, f"{fmt_num(days.value, lang_, 1)} {t['days_s']} · Δt {fmt_num(dt.value, lang_)} s · {start.value}")
            for w_ in (start, days, dt):
                w_.on_value_change(lambda e: time_caption())
            time_caption()
            dt_hint = ui.label(t["dt_hint_wait"]).classes("text-caption text-grey-7")
            dtr = {}
            def show_dt_hint():
                if not dtr:
                    return
                lo, hi = dtr["lo"], dtr["hi"]; d_ = float(dt.value or 0)
                ok = lo <= d_ <= hi
                dt_hint.set_text(t["dt_hint"].format(lo=f"{lo:.0f}", hi=f"{hi:.0f}", dt=f"{d_:g}", p5=f"{dtr['p5']:.2f}"))
                dt_hint.classes(remove="text-grey-7 text-orange-9", add="text-grey-7" if ok else "text-orange-9")
            async def load_dt_hint():
                from ..mesh import view as mview
                hg = workdir() / "hgrid.gr3"
                if not hg.exists():
                    dt_hint.set_text(t["dt_hint_nomesh"]); return
                try:
                    d_ = await run.io_bound(mview.load, workdir())
                    lo, hi = mview.dt_range(d_)
                    dtr.update(lo=lo, hi=hi, d=d_); dtr["p5"] = mview.cfl_stats(d_, float(dt.value))["cfl_p5"]; show_dt_hint()
                except Exception as ex:   # malla ilegible: no bloquear la página
                    dt_hint.set_text(str(ex))
            def on_dt(e):
                if dtr:
                    from ..mesh import view as mview
                    dtr["p5"] = mview.cfl_stats(dtr["d"], float(e.value or 0))["cfl_p5"]; show_dt_hint()
            dt.on_value_change(on_dt); ui.timer(0.1, load_dt_hint, once=True)
        with ui.expansion(t["vertical"], icon="layers", value=True).classes("sl-exp w-full") as exp_vert:
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                vt = ui.select({"2d": t["v2d"], "sigma": t["vsigma"], "sz": t["vsz"]}, value=safe_select(("2d", "sigma", "sz"), v.get("type", "2d"), "2d", label=t["vertical"]), label=t["vertical"]).classes("sl-w-md")
                nvrt = ui.number(t["nvrt"], value=int(v.get("nvrt", v.get("nsigma", 20))), min=3, step=1).classes("sl-w-sm")
                hc = ui.number("h_c (m)", value=float(v.get("h_c", 10))).classes("sl-w-sm"); tf = ui.number("theta_f", value=float(v.get("theta_f", 4)), min=0.001).classes("sl-w-sm")
                tb = ui.number("theta_b", value=float(v.get("theta_b", 0.5 if v.get("type") == "sz" else 0.0)), min=0, max=1, step=0.1).classes("sl-w-sm")
                zl = ui.input(t["zlevels"], value=",".join(str(z) for z in v.get("zlevels", [-2500, -1500, -1000, -700, -500, -300]))).classes("sl-w-lg")
                vbtn = ui.button(t["show_vgrid"], icon="stacked_line_chart").props("flat dense")
            vdesc = ui.markdown().classes("text-caption text-grey-8")
            def vis():
                nvrt.set_visibility(vt.value != "2d"); hc.set_visibility(vt.value != "2d"); tf.set_visibility(vt.value != "2d"); tb.set_visibility(vt.value != "2d"); zl.set_visibility(vt.value == "sz"); vbtn.set_visibility(vt.value != "2d")
                vdesc.set_content(t["vdesc_" + vt.value])
                set_caption(exp_vert, t["v2d"] if vt.value == "2d" else f"3D {vt.value} · {int(nvrt.value or 0)} {t['levels_s']}")
            vt.on_value_change(lambda e: vis()); nvrt.on_value_change(lambda e: vis()); vis()
            def show_vgrid():
                from ..forcing import VGrid
                from .figures import vgrid_figure
                try:
                    if vt.value == "sz":
                        vg = VGrid.sz(int(nvrt.value), [float(s_) for s_ in zl.value.split(",")], float(hc.value), float(tb.value or 0), float(tf.value))
                    else:
                        vg = VGrid.sigma(int(nvrt.value), float(hc.value), float(tb.value or 0), float(tf.value))
                except (ValueError, IndexError) as ex:
                    ui.notify(str(ex), type="negative"); return
                hmax = 1000.0
                try:
                    from ..io.gr3 import read_gr3
                    hg = workdir() / "hgrid.gr3"
                    if hg.exists():
                        hmax = float(np.nanmax(read_gr3(hg).depth))
                except Exception:   # sin malla todavía: fondo de referencia
                    pass
                with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width:min(760px,95vw)"):
                    ui.label(t["vgrid_dlg"].format(hmax=hmax)).classes("text-caption text-grey-7")
                    from .figures import themed as _themed
                    ui.plotly(_themed(vgrid_figure(vg, hmax, S().get("lang", "es")), bool(S().get("dark")))).classes("w-full")
                dlg.open()
            vbtn.on_click(show_vgrid)
        with ui.expansion(t["model"], icon="tune", value=True).classes("sl-exp w-full") as exp_model:
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                baro = ui.switch(t["baroclinic"], value=bool(ph.get("baroclinic", False)))
                _topts = {0: t["turb_none"], 3: "k-kl (GLS)", 5: "k-ε (GLS)"}
                try:
                    _turb0 = int(ph.get("turbulence", 3))
                except (TypeError, ValueError):
                    _turb0 = 3
                if _turb0 not in _topts:                                              # itur = 1, 2, 4: válidos en SCHISM, se conservan
                    _topts[_turb0] = f"itur = {_turb0}"
                turb = ui.select(_topts, value=_turb0, label=t["turb"]).classes("sl-w-md").mark("turb_select")
                turb_2d = ui.label(t["turb_2d"]).classes("text-caption text-grey-7").mark("turb_2d")
                _cor0 = ph.get("coriolis", "f-plane"); _cor0 = "none" if _cor0 in (False, 0, None, "0", "false") else _cor0
                cor = ui.select(["f-plane", "beta", "none"], value=safe_select(["f-plane", "beta", "none"], _cor0, "f-plane", label=t["coriolis"]), label=t["coriolis"]).classes("sl-w-sm")
                ref = c.get("reference", {})
                lon0 = ui.number("lon0", value=float(ref.get("lon0", 0))).classes("sl-w-sm"); lat0 = ui.number("lat0", value=float(ref.get("lat0", 45))).classes("sl-w-sm")
            # filtro de Shapiro: 0.1 por defecto en dominios idealizados, 0.5 en mallas reales (lo mismo que setup.py)
            _shap_def = 0.1 if (c.get("mesh", {}) or {}).get("generator", default_generator()) == "idealized" else 0.5
            _shap0 = ph.get("shapiro0", (c.get("param") or {}).get("shapiro0", _shap_def))
            with ui.row().classes("row wrap q-col-gutter-sm items-center w-full"):
                shap = ui.number(t["shapiro0"], value=float(_shap0), min=0, max=0.5, step=0.05, format="%g").classes("sl-w-md").mark("shapiro0")
                ui.label(t["shapiro0_hint"]).classes("text-caption text-grey-7 col")
            # viscosidad y difusividad verticales constantes (itur = 0): las de param.nml (sobreescrituras > plantilla)
            from ..io.namelist_catalog import defaults as _nml_def
            _pov = {**(c.get("param") or {}), **((c.get("namelists") or {}).get("param.nml") or {})}
            _numf = lambda v, d: float(str(v).lower().replace("d", "e")) if v is not None else d
            _dfv0 = _numf(_pov.get("dfv0", _nml_def("param.nml").get("dfv0")), 1e-2)
            _dfh0 = _numf(_pov.get("dfh0", _nml_def("param.nml").get("dfh0")), 1e-4)
            with ui.row().classes("row wrap q-col-gutter-sm items-center w-full") as dfrow:
                dfv = ui.number(t["dfv0"], value=_dfv0, min=0, format="%g").classes("sl-w-md").mark("dfv0")
                dfh = ui.number(t["dfh0"], value=_dfh0, min=0, format="%g").classes("sl-w-md").mark("dfh0")
                ui.label(t["dfv0_hint"]).classes("text-caption text-grey-7 col")
            def turb_vis():                                        # Lite: en 2D SCHISMlab pone itur = 0 y el cierre se oculta (Pro lo deja elegir)
                is2d = vt.value == "2d" and not is_pro()
                turb.set_visibility(not is2d); turb_2d.set_visibility(is2d); dfrow.set_visibility(turb.value == 0 and not is2d)
            turb.on_value_change(lambda e: turb_vis()); vt.on_value_change(lambda e: turb_vis()); turb_vis()
            # Igual que Setup.geographic: dominio real o idealizado en lon/lat -> ics=2, ncor=1 (Coriolis completo)
            mc_ = c.get("mesh", {}) or {}
            geo_dom = mc_.get("generator", default_generator()) != "idealized" or ("lon" in mc_ and "lat" in mc_)
            if geo_dom:                                        # Coriolis completo: el selector y lon0/lat0 no se usan (ocultos)
                cor.set_visibility(False); lon0.set_visibility(False); lat0.set_visibility(False)
                ui.label(t["cor_full"]).classes("text-caption text-grey-7")
            else:
                ui.label(t["cor_approx"]).classes("text-caption text-orange-9")
            def model_caption():
                set_caption(exp_model, (t["baroclinic_s"] if baro.value else t["barotropic_s"]) + ("" if (vt.value == "2d" and not is_pro()) else " · " + str(_topts.get(turb.value, turb.value)))
                            + ("" if geo_dom else f" · Coriolis {cor.value}"))
            baro.on_value_change(lambda e: model_caption()); turb.on_value_change(lambda e: model_caption()); cor.on_value_change(lambda e: model_caption())
            vt.on_value_change(lambda e: model_caption()); model_caption()
        with ui.expansion(t["ic"], icon="water", value=True).classes("sl-exp w-full") as exp_ic:
            ui.label(t["ic_hint"]).classes("text-caption text-grey-7")
            _icsrc = ic.get("source") or {}
            src = _icsrc.get("name", "analytic") if isinstance(_icsrc, dict) else str(_icsrc)       # setup admite `source: medsea`
            _sopts = {"analytic": t["ic_analytic"], "medsea_reanalysis": t["ic_cmems"], "medsea": t["ic_cmems_an"], "global": t["ic_cmems_glo"]} \
                if is_pro() else {"analytic": t["ic_analytic"]}                                # Copernicus: SCHISMlab Pro
            src = safe_select(_sopts, src, "analytic", keep_unknown=is_pro())                # cmems, medsea_analysis…: se conservan
            ic_src = ui.select(_sopts, value=src, label=t["ic_source"]).classes("sl-w-xl")
            ic_src.set_visibility(is_pro())
            ic_src.on_value_change(lambda e: set_caption(exp_ic, _sopts.get(e.value, e.value))); set_caption(exp_ic, _sopts.get(src, src))
            from .ic_builder import ic_builder
            def live_vgrid():
                from ..forcing import VGrid
                if vt.value == "sz":
                    return VGrid.sz(int(nvrt.value), [float(s_) for s_ in zl.value.split(",")], float(hc.value), float(tb.value or 0), float(tf.value))
                if vt.value == "sigma":
                    return VGrid.sigma(int(nvrt.value), float(hc.value), float(tb.value or 0), float(tf.value))
                return VGrid.two_d()
            with ui.column().classes("w-full") as ic_box:
                ic_collect, ic_refresh = ic_builder(c, workdir(), t, S().get("lang", "es"), live_vgrid, lambda: bool(baro.value), lambda: vt.value != "2d", dark=bool(S().get("dark")))
            ic_src.on_value_change(lambda e: ic_box.set_visibility(e.value == "analytic")); ic_box.set_visibility(src == "analytic")
            baro.on_value_change(lambda e: ic_refresh()); vt.on_value_change(lambda e: ic_refresh())
        sc = c.get("scenario", {}) or {}; fr = c.get("friction", {}) or {}
        with ui.expansion(t["scenario"], icon="trending_up", value=False).classes("sl-exp w-full") as exp_sc:
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                slr = ui.number(t["slr"], value=float(sc.get("sea_level_rise", 0.0) or 0.0), step=0.1).classes("sl-w-md")
                slr.set_visibility(is_pro())                       # subida del nivel del mar y usos del suelo: SCHISMlab Pro
                _mopts = {"const": t["manning_const"], "worldcover": t["manning_wc"], "corine": t["manning_corine"]} if is_pro() else {"const": t["manning_const"]}
                msrc = ui.select(_mopts, value=safe_select(_mopts, fr.get("landcover") or "const", "const", keep_unknown=is_pro()), label=t["manning_src"]).classes("sl-w-lg")
                man = ui.number(t["manning_sea"] if fr.get("landcover") else "Manning n", value=float(fr.get("manning", 0.025)), step=0.005, format="%.4f").classes("sl-w-sm")
                mfile = ui.input(t["manning_file"], value=fr.get("file", "")).props("dense clearable").classes("sl-w-lg")
                msrc.on_value_change(lambda e: mfile.set_visibility(e.value == "corine")); mfile.set_visibility(msrc.value == "corine")
            def sc_caption():
                set_caption(exp_sc, (f"{t['slr_s']} {fmt_num(slr.value or 0, lang_, 2)} m · Manning {_mopts.get(msrc.value, msrc.value)} " if is_pro() else "Manning n = ")
                            + fmt_num(man.value or 0, lang_, 3))
            for w_ in (slr, msrc, man):
                w_.on_value_change(lambda e: sc_caption())
            sc_caption()
        def collect():
            c2 = cfg()
            c2["scenario"] = {**c2.get("scenario", {}), "sea_level_rise": float(slr.value or 0.0)}
            c2["friction"] = {**c2.get("friction", {}), "manning": float(man.value)}
            if msrc.value == "const":
                c2["friction"].pop("landcover", None); c2["friction"].pop("file", None)
            else:
                c2["friction"]["landcover"] = msrc.value
                if msrc.value == "corine":
                    c2["friction"]["file"] = mfile.value
            c2["time"] = {"start": start.value, "days": float(days.value), "dt": float(dt.value), "ramp_days": float(ramp.value)}
            vv = {"type": vt.value}
            if vt.value == "sigma":
                vv.update(nvrt=int(nvrt.value), h_c=float(hc.value), theta_b=float(tb.value or 0), theta_f=float(tf.value))
            elif vt.value == "sz":
                vv.update(nsigma=int(nvrt.value), zlevels=[float(z) for z in zl.value.split(",")], h_c=float(hc.value), theta_b=float(tb.value or 0), theta_f=float(tf.value))
            c2["vertical"] = vv
            c2["physics"] = {**c2.get("physics", {}), "baroclinic": bool(baro.value), "turbulence": int(turb.value), "coriolis": cor.value}
            # shapiro0 solo se escribe si el caso ya lo tenía o se ha cambiado (los casos guardados siguen el valor por defecto)
            _sv = float(shap.value) if shap.value is not None else float(_shap0)
            if "shapiro0" in ph or abs(_sv - float(_shap0)) > 1e-12:
                c2["physics"]["shapiro0"] = min(max(_sv, 0.0), 0.5)
                if "shapiro0" in (c2.get("param") or {}):            # una sobreescritura directa ganaría: se actualiza
                    c2["param"]["shapiro0"] = c2["physics"]["shapiro0"]
            # dfv0 y dfh0 solo se escriben si se han cambiado o el caso ya los fijaba (donde estuvieran)
            for _k, _w, _v0 in (("dfv0", dfv, _dfv0), ("dfh0", dfh, _dfh0)):
                _v = max(float(_w.value), 0.0) if _w.value is not None else _v0
                _nl = (c2.get("namelists") or {}).get("param.nml") or {}
                if _k in _nl:
                    _nl[_k] = _v
                elif _k in (c2.get("param") or {}) or abs(_v - _v0) > 1e-15:
                    c2.setdefault("param", {})[_k] = _v
            c2["reference"] = {"lon0": float(lon0.value), "lat0": float(lat0.value)}
            c2["initial"] = ic_collect()
            if ic_src.value != "analytic":                       # Copernicus: T, S y eta vienen del reanalisis
                c2["initial"].pop("velocity", None); c2["initial"].pop("recipe", None)
                c2["initial"]["source"] = {"name": ic_src.value}
            return c2
        action_bar(t, collect, "model")


# ----------------------------------------------------------------------------- forzamientos
@ui.page("/forcing")
def page_forcing():
    t = T()
    with layout("forcing"):
        if need_case():
            return
        c = cfg(); fc = c.setdefault("forcing", {}); bc = c.setdefault("boundaries", {}); oc = c.setdefault("output", {})
        ui.label(t["step_forcing"]).classes("text-h4 text-primary"); build_chip(c)
        has_wwm = "wwm" in _case_modules(c)[1]
        has_open = has_open_boundaries(c)
        if not has_open:
            ui.label(t["no_open_boundaries"]).classes("q-pa-sm rounded-borders text-body2 " + ("bg-orange-10" if S().get("dark") else "bg-orange-1 text-orange-10"))
        PRO = is_pro()
        exp_keys = ["atm", "tides", "meteo", "quake", "bc3d", "waves", "rivers"] if PRO else ["atm", "tides"]   # meteotsunami, tsunami, 3D, oleaje y ríos: Pro
        _pg = None
        if PRO:
            from ..edition import pro as _pro
            _pg = _pro("gui.forcing")                          # piezas de Forzamientos de SCHISMlab Pro
        _pro_used = [k for k, used in (("ERA5", bool(fc.get("atmosphere"))), (t["tab_bc3d"], bool(bc.get("source"))), (t["tab_waves"], bool((c.get("waves") or {}).get("enabled"))),
                                        (t["tab_rivers"], bool(fc.get("rivers")))) if used]
        if not PRO and _pro_used:
            pro_notice(t, t["pro_case"].format(what=", ".join(_pro_used)))
        try:
            want_tab = ui.context.client.request.query_params.get("tab") or "atm"
        except Exception:   # noqa: BLE001
            want_tab = "atm"
        if want_tab not in exp_keys:
            want_tab = "atm"
        lang_ = S().get("lang", "es")
        _icons = {"atm": "air", "tides": "waves", "meteo": "speed", "quake": "landslide", "bc3d": "public", "waves": "tsunami", "rivers": "water"}
        exp = {k: ui.expansion(t["tab_" + k], icon=_icons[k], value=(k == want_tab)).classes("sl-exp w-full") for k in exp_keys}
        with exp["atm"]:
            with ui.column().classes("w-full"):
                w = fc.get("wind"); atm = fc.get("atmosphere")
                cur = (atm.get("source", "era5") if atm.get("source") in ("era5", "file") else "era5") if atm else ("stress" if w and w.get("stress") is not None else "expr" if w and any(isinstance(w.get(k), str) for k in ("u", "v")) else "uniform" if w else "none")
                _wopts = {"none": t["w_none"], "uniform": t["w_uniform"], "expr": t["w_expr"], "stress": t["w_stress"], **({"era5": t["w_era5"], **_pg.atmos_options(t)} if PRO else {})}
                if cur not in _wopts:
                    cur = "none"
                _st = (w or {}).get("stress") or {}
                wk = ui.select(_wopts, value=cur).classes("sl-w-lg")
                wk.on_value_change(lambda e: set_caption(exp["atm"], t["no_wind_s"] if e.value == "none" else _wopts.get(e.value, e.value)))
                set_caption(exp["atm"], t["no_wind_s"] if cur == "none" else _wopts.get(cur, cur))
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    u = ui.input(t["u"], value=str((w or {}).get("u", 10))); v = ui.input(t["v"], value=str((w or {}).get("v", 0)))
                    tau_x = ui.input(t["tau_x"], value=str(_st.get("x", 0.1))); tau_y = ui.input(t["tau_y"], value=str(_st.get("y", 0)))
                    wformula = ui.select({1: t["wf_hwang"], -1: t["wf_pp"]}, value=safe_select([1, -1], int((w or {}).get("formula", 1)), 1, label=t["wformula"]), label=t["wformula"]).classes("sl-w-md")
                    _ramp_def = lambda k: 0.0 if k == "stress" else 0.5          # esfuerzo: sin rampa, para comparar con la teoría desde el inicio
                    wramp = ui.number(t["wind_ramp"], value=float((w or {}).get("ramp_days", _ramp_def(cur))), min=0, step=0.25).classes("sl-w-sm")
                    wdt = ui.number(t["wind_dt"], value=float((w or {}).get("dt_hours", 1.0)), min=0.1, step=1).classes("sl-w-sm")
                    heat = ui.switch(t["heat"], value=bool((atm or {}).get("heat", False))); precip = ui.switch(t["precip"], value=bool((atm or {}).get("precipitation", False)))
                def visw():
                    u.set_visibility(wk.value in ("uniform", "expr")); v.set_visibility(wk.value in ("uniform", "expr"))
                    tau_x.set_visibility(wk.value == "stress"); tau_y.set_visibility(wk.value == "stress"); wformula.set_visibility(wk.value in ("uniform", "expr", "stress"))
                    wramp.set_visibility(wk.value in ("uniform", "expr", "stress")); wdt.set_visibility(wk.value in ("uniform", "expr", "stress"))
                    heat.set_visibility(wk.value in ("era5", "file")); precip.set_visibility(wk.value in ("era5", "file"))
                def _wk_ramp(e):                                # otro tipo de viento: su rampa por defecto (la del YAML si es el tipo guardado)
                    wramp.set_value(float((w or {}).get("ramp_days", _ramp_def(cur))) if e.value == cur and w else _ramp_def(e.value))
                wk.on_value_change(_wk_ramp)
                atm_file_collect = _pg.atmos_file_box(t, atm, wk) if PRO else None
                wk.on_value_change(lambda e: visw()); visw()
        with exp["tides"]:
            with ui.column().classes("w-full"):
                ui.label(t["bc"]).classes("text-subtitle1 text-weight-bold")
                e = bc.get("elevation", "none")
                if isinstance(e, dict):
                    cur = "tsunami" if "tsunami" in e else "series" if "series" in e else "tides"
                else:
                    try:
                        cur = "none" if e in ("none", None) else "zero" if float(e) == 0 else "const"
                    except (TypeError, ValueError):                               # p. ej. `th` (fichero propio): sin equivalente
                        ui.notify(t["select_fallback"].format(value=e, label=t["bc_elev"], default=t["bc_none"]), type="warning", timeout=6000); cur = "none"
                _ekopts = {"none": t["bc_none"], "zero": t["bc_zero"], "const": t["bc_const"], "tides": t["bc_tides"], "tsunami": t["bc_tsunami"], "series": t["bc_series"]}
                ek = ui.select(_ekopts, value=cur, label=t["bc_elev"]).classes("sl-w-lg")
                ui.label(t["bc_edges_hint"]).classes("text-caption text-grey-7")
                ts0 = e.get("tsunami", {}) if isinstance(e, dict) else {}
                with ui.row().classes("row wrap q-col-gutter-sm items-center") as tsu_row:
                    ts_shape = ui.select({"solitary": t["ts_solitary"], "n_wave": t["ts_nwave"], "leading_depression": t["ts_depression"]}, value=ts0.get("shape", "solitary"), label=t["ts_shape"]).props("dense").classes("sl-w-md")
                    ts_h = ui.number(t["ts_height"], value=float(ts0.get("height", 1.0)), min=0, step=0.25).props("dense").classes("sl-w-sm")
                    ts_T = ui.number(t["ts_period"], value=float(ts0.get("period_min", 15.0)), min=1, step=1).props("dense").classes("sl-w-sm")
                    ts_t0 = ui.number(t["ts_arrival"], value=float(ts0.get("arrival_h", 0.5)), min=0, step=0.25).props("dense").classes("sl-w-sm")
                    ts_n = ui.number(t["ts_waves"], value=int(ts0.get("waves", 1)), min=1, max=20, step=1).props("dense").classes("sl-w-sm")
                ser0 = e.get("series", [[0, 0.0], [3, 1.0], [6, 0.0]]) if isinstance(e, dict) else [[0, 0.0], [3, 1.0], [6, 0.0]]
                ser = ui.input(t["bc_series_val"], value=json.dumps(ser0)).props("dense").classes("w-full")
                td = e.get("tides", {}) if isinstance(e, dict) else {}
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    const = ui.number("m", value=float(e) if cur == "const" else 0.0)
                    _tsopts = {"idealized": t["t_ideal"], "got4.10c": "GOT4.10c", "fes2022": "FES2022"} if PRO else {"idealized": t["t_ideal"]}   # mareas globales: Pro
                    _tsdef = "got4.10c" if PRO else "idealized"
                    tsrc = ui.select(_tsopts, value=safe_select(tuple(_tsopts), td.get("source", _tsdef), _tsdef, label=t["tide_src"]), label=t["tide_src"]).classes("sl-w-lg")
                    amp = ui.number(t["amp"], value=float(td.get("amplitude", 0.5) or 0.5))
                    _ALL_CONS = ["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1"]
                    cons = ui.select(_ALL_CONS, multiple=True, value=safe_select(_ALL_CONS, td.get("constituents", _ALL_CONS), _ALL_CONS, multiple=True), label=t["cons"]).classes("sl-w-lg")
                    pot = ui.switch(t["potential"], value=bool(bc.get("tidal_potential", True)))
                _bv = bc.get("velocity", "none")
                _bvopts = {"none": t["bc_vel_none"], "flux": t["bc_vel_flux"]}
                if isinstance(_bv, bool) or not isinstance(_bv, (int, float, str)) or (isinstance(_bv, str) and _bv != "none"):
                    _bvopts["keep"] = t["bc_vel_keep"].format(value=_bv); _bv_mode = "keep"      # marea en velocidad, flather...: se conserva
                else:
                    _bv_mode = "none" if _bv == "none" else "flux"
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    bvel = ui.select(_bvopts, value=_bv_mode, label=t["bc_vel"]).classes("sl-w-lg")
                    bflux = ui.number(t["bc_flux"], value=float(_bv) if _bv_mode == "flux" else -1.0e6, step=100000, format="%.0f").classes("sl-w-md")
                bflux.bind_visibility_from(bvel, "value", backward=lambda v_: v_ == "flux")
                ui.label(t["bc_vel_hint"]).classes("text-caption text-grey-7")
                def visb():
                    const.set_visibility(ek.value == "const"); [x.set_visibility(ek.value == "tides") for x in (tsrc, cons, pot)]
                    amp.set_visibility(ek.value == "tides" and tsrc.value == "idealized")
                    tsu_row.set_visibility(ek.value == "tsunami"); ser.set_visibility(ek.value == "series")
                ek.on_value_change(lambda e: visb()); tsrc.on_value_change(lambda e: visb()); visb()
                def tides_caption():
                    lab = _ekopts.get(ek.value, ek.value)
                    if ek.value == "tides":
                        lab = f"{', '.join(cons.value or ['M2'])} {_tsopts.get(tsrc.value, tsrc.value)}" + (f" {fmt_num(amp.value or 0, lang_, 2)} m" if tsrc.value == "idealized" else "")
                    elif ek.value == "const":
                        lab = f"{lab} {fmt_num(const.value or 0, lang_, 2)} m"
                    set_caption(exp["tides"], lab)
                for w_ in (ek, tsrc, amp, cons, const):
                    w_.on_value_change(lambda e: tides_caption())
                tides_caption()
            with ui.column().classes("w-full"):                                  # capa esponja junto a los contornos abiertos
                ui.label(t["sponge_card"]).classes("text-subtitle1 text-weight-bold")
                ui.markdown(t["sponge_expl"]).classes("text-caption text-grey-8")
                sp0 = bc.get("sponge", "auto")
                sp_mode0 = "auto" if sp0 == "auto" else ("off" if not sp0 else "on")
                sp_cfg = sp0 if isinstance(sp0, dict) else {}
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    sp_mode = ui.select({"auto": t["sponge_auto"], "on": t["sponge_on"], "off": t["sponge_off"]}, value=sp_mode0, label=t["sponge_mode"]).classes("sl-w-lg")
                    sp_w = ui.number(t["sponge"], value=float(sp_cfg.get("width_km", 40)), min=1, step=5).classes("sl-w-sm")
                    sp_tau = ui.number(t["sponge_tau"], value=round(1 / max(float(sp_cfg.get("relax_uv", 0.01)), 1e-6) / 60, 2), min=0.1, step=1).classes("sl-w-md")
                    sp_eta = ui.switch(t["sponge_eta"], value=float(sp_cfg.get("relax_elev", 0)) > 0)
                def _sp_vis():
                    for w_ in (sp_w, sp_tau, sp_eta): w_.set_visibility(sp_mode.value == "on")
                sp_mode.on_value_change(lambda e: _sp_vis()); _sp_vis()
        if PRO:                                             # meteotsunami, contornos 3D, oleaje y ríos: SCHISMlab Pro
            with exp["meteo"]:
                pd_collect = _pg.pressure_box(t, fc, set_caption, exp["meteo"], geographic=is_geographic_cfg(c))
            with exp["quake"]:
                bd_collect = _pg.bed_deformation_box(t, fc, set_caption, exp["quake"], geographic=is_geographic_cfg(c),
                                                     mesh_info=lambda: (workdir(), is_geographic_cfg(cfg())))
            with exp["bc3d"]:
                with ui.column().classes("w-full"):
                    pass
                    bsrc = bc.get("source") or {}
                    cur_src = "schismlab" if bsrc.get("name") == "schismlab" else ("cmems" if bsrc else "none")
                    _b3opts = {"none": t["bc_src_none"], "cmems": t["bc_3d"], "schismlab": t["bc_src_nest"]}
                    bc3d = ui.select(_b3opts, value=cur_src, label=t["bc_src"]).classes("sl-w-xl")
                    bc3d.on_value_change(lambda e: set_caption(exp["bc3d"], _b3opts.get(e.value, e.value))); set_caption(exp["bc3d"], _b3opts.get(cur_src, cur_src))
                    if not has_open:                                   # sin contornos: la fuente 3D no se aplica ni se guarda
                        bc3d.set_value("none"); bc3d.set_enabled(False); ui.label(t["no_open_boundaries"]).classes("text-caption text-orange-9")
                    parents = [ci for ci in gallery() if ci.path != case_path() and ci.status().get("run")]
                    bparent = ui.select({str(ci.path): ci.name for ci in parents}, value=bsrc.get("case") if bsrc.get("case") in {str(ci.path) for ci in parents} else (str(parents[0].path) if parents else None), label=t["bc_parent"]).classes("sl-w-lg")
                    bparent.bind_visibility_from(bc3d, "value", backward=lambda v: v == "schismlab")
                    ui.label(t["bc_nest_hint"]).classes("text-caption text-grey-7").bind_visibility_from(bc3d, "value", backward=lambda v: v == "schismlab")
            with exp["waves"]:
                if not has_wwm:
                    ui.label(t["waves_need_wwm"]).classes("text-caption text-grey-7")
                with ui.column().classes("w-full" if has_wwm else "hidden"):
                    wv = c.get("waves") or {}
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        waves_on = ui.switch(t["waves_on"], value=bool(wv.get("enabled", "wwm" in _case_modules(c)[1] and "waves" not in c)))
                        wnstep = ui.number(t["waves_nstep"], value=int(wv.get("nstep", 3)), min=1, step=1).props("dense").classes("sl-w-sm")
                    def waves_caption():
                        if not has_wwm:
                            set_caption(exp["waves"], f"{t['needs_module']} WWM"); return
                        set_caption(exp["waves"], (t["on_s"] + " · " + _wbopts.get(wbt.value, wbt.value)) if waves_on.value else t["off_s"])
                    wb = dict(wv.get("boundary") or {})
                    if not wb and wv.get("boundary_hs"):
                        wb = {"type": "parametric", "hs": wv["boundary_hs"], "tp": wv.get("boundary_tp", 8.0), "dir": wv.get("boundary_dir", 270.0)}
                    with ui.column().classes("w-full").bind_visibility_from(waves_on, "value"):
                        ui.label(t["waves_bc"]).classes("text-subtitle2 q-mt-sm")
                        _wbopts = {"none": t["wbc_none"], "parametric": t["wbc_param"], "series": t["wbc_series"], "copernicus": t["wbc_cmems"]}
                        wbt = ui.select(_wbopts, value=safe_select(("none", "parametric", "series", "copernicus"), wb.get("type", "none"), "none", label=t["waves_bc"]), label=t["waves_bc"]).classes("sl-w-xl")
                        waves_on.on_value_change(lambda e: waves_caption()); wbt.on_value_change(lambda e: waves_caption()); waves_caption()
                        with ui.row().classes("row wrap q-col-gutter-sm items-center").bind_visibility_from(wbt, "value", backward=lambda v: v == "parametric"):
                            whs = ui.number(t["waves_hs"], value=float(wb.get("hs", 1.0)), min=0, step=0.5).props("dense").classes("sl-w-sm")
                            wtp = ui.number("Tp (s)", value=float(wb.get("tp", 8.0)), min=1).props("dense").classes("sl-w-sm")
                            wdir = ui.number(t["waves_dir"], value=float(wb.get("dir", 270.0)), min=0, max=360).props("dense").classes("sl-w-sm")
                            wspr = ui.number(t["waves_spread"], value=float(wb.get("spread", 20.0)), min=2, max=90).props("dense").classes("sl-w-sm")
                        with ui.column().classes("w-full").bind_visibility_from(wbt, "value", backward=lambda v: v == "series"):
                            ui.label(t["wbc_series_hint"]).classes("text-caption text-grey-7")
                            wtab = ui.textarea(value="\n".join(", ".join(str(x) for x in row) for row in (wb.get("table") or [["2020-01-01 00:00", 2.0, 8.0, 45.0], ["2020-01-02 00:00", 3.0, 9.0, 45.0]]))).props("outlined dense rows=4").classes("w-full")
                        with ui.row().classes("row wrap q-col-gutter-sm items-center").bind_visibility_from(wbt, "value", backward=lambda v: v == "copernicus"):
                            wsrc = ui.select({"med_reanalysis": t["wsrc_med_re"], "med_analysis": t["wsrc_med_an"], "global": t["wsrc_global"]},
                                             value=safe_select(("med_reanalysis", "med_analysis", "global"), wb.get("source", "med_reanalysis"), "med_reanalysis", label=t["wbc_cmems_src"]), label=t["wbc_cmems_src"]).props("dense").classes("sl-w-lg")
                            wstep = ui.number(t["wbc_step"], value=float(wb.get("step_hours", 3)), min=1, step=1).props("dense").classes("sl-w-sm")
            with exp["rivers"]:
                with ui.column().classes("w-full"):
                    from ..edition import pro as _pro
                    _pro_forcing_sources = _pro("forcing.sources")
                    CATALOG = _pro_forcing_sources.CATALOG
                    ui.label(t["rivers_hint"]).classes("text-caption text-grey-7")
                    rivers: list[dict] = list(fc.get("rivers") or [])
                    rlist = ui.column().classes("w-full")
                    def render_rivers():
                        rlist.clear(); set_caption(exp["rivers"], t["n_rivers"].format(n=len(rivers)) if rivers else t["none"])
                        with rlist:
                            for i, r in enumerate(rivers):
                                with ui.row().classes("items-center q-gutter-sm"):
                                    ui.label(str(r.get("name", f"río {i + 1}"))).classes("text-weight-bold").style("width:110px")
                                    for key, lab, w in (("lon", "lon", "w-24"), ("lat", "lat", "w-24")):
                                        ui.input(lab, value=str(r.get(key, ""))).props("dense").classes(w).on_value_change(lambda e, r=r, key=key: r.__setitem__(key, _parse_value(e.value)))
                                    _pg.river_flow_widget(t, r, _parse_value)                 # número/expresión, serie CSV o GloFAS
                                    for key, lab, w in (("temperature", "T (°C)", "w-20"), ("salinity", "S (psu)", "w-24")):
                                        ui.input(lab, value=str(r.get(key, ""))).props("dense").classes(w).on_value_change(lambda e, r=r, key=key: r.__setitem__(key, _parse_value(e.value)))
                                    ui.button(icon="delete", on_click=lambda _, i=i: (rivers.pop(i), render_rivers())).props("flat dense round")
                    render_rivers()
                    with ui.row().classes("items-center q-gutter-sm"):
                        rsel = ui.select(list(CATALOG), value="Ebro", label=t["river_catalog"]).props("dense").classes("sl-w-md")
                        ui.button(t["add_station"], icon="add", on_click=lambda: (rivers.append({"name": rsel.value, **CATALOG[rsel.value]}), render_rivers())).props("flat")
                        rname = ui.input(t["name"]).props("dense").classes("sl-w-sm")
                        ui.button(t["add_custom"], icon="add_location", on_click=lambda: (rivers.append({"name": rname.value or "río", "lon": round(float(cfg().get("mesh", {}).get("polygon", [[0, 0]])[0][0]), 2), "lat": round(float(cfg().get("mesh", {}).get("polygon", [[0, 0]])[0][1]), 2), "flow": 10.0, "temperature": 15.0, "salinity": 0.5}), render_rivers())).props("flat")
                rain_collect = _pg.rain_box(t, fc, (c.get("mesh") or {}).get("resolution", {}).get("regions", []) or [])   # lluvia sobre la malla
        def collect():
            c2 = cfg(); f2 = {}
            def num(s):
                try: return float(s)
                except ValueError: return s
            if wk.value in ("uniform", "expr"):
                f2["wind"] = {"u": num(u.value), "v": num(v.value), "ramp_days": float(wramp.value or 0), "formula": int(wformula.value)}
            elif wk.value == "stress":   # esfuerzo en Pa: sin rampa por defecto, para comparar con la teoría desde el inicio
                f2["wind"] = {"stress": {"x": num(tau_x.value), "y": num(tau_y.value)}, "ramp_days": float(wramp.value or 0), "formula": int(wformula.value)}
            if "wind" in f2 and float(wdt.value or 1.0) != 1.0:
                f2["wind"]["dt_hours"] = float(wdt.value)
            elif wk.value == "era5":
                f2["atmosphere"] = {"source": "era5", "heat": bool(heat.value), "precipitation": bool(precip.value)}
            if PRO:
                atm_file_collect(f2, heat, precip); pd_collect(f2); bd_collect(f2); rain_collect(f2, _parse_value)
            if PRO and rivers:
                f2["rivers"] = [dict(r) for r in rivers]
            c2["forcing"] = f2
            b2 = dict(c2.get("boundaries", {}) or {})
            if ek.value == "none": b2["elevation"] = "none"
            elif ek.value == "zero": b2["elevation"] = 0
            elif ek.value == "const": b2["elevation"] = float(const.value)
            elif ek.value == "tsunami":
                b2["elevation"] = {"tsunami": {"shape": ts_shape.value, "height": float(ts_h.value or 0), "period_min": float(ts_T.value or 15),
                                               "arrival_h": float(ts_t0.value or 0), "waves": int(ts_n.value or 1)}}
            elif ek.value == "series":
                try:
                    b2["elevation"] = {"series": [[float(a_), float(b_)] for a_, b_ in json.loads(ser.value or "[]")]}
                except Exception:   # noqa: BLE001
                    ui.notify(t["bc_series_val"], type="warning"); b2["elevation"] = "none"
            else:
                tide = {"constituents": list(cons.value or ["M2"]), "source": tsrc.value}
                if tsrc.value == "idealized": tide["amplitude"] = float(amp.value)
                b2["elevation"] = {"tides": tide}; b2["tidal_potential"] = bool(pot.value)
            if not PRO: pass                                 # Lite: la fuente 3D no se toca
            elif bc3d.value == "cmems": b2["source"] = {"name": (c2.get("initial", {}).get("source") or {}).get("name", "medsea_reanalysis")}
            elif bc3d.value == "schismlab" and bparent.value: b2["source"] = {"name": "schismlab", "case": bparent.value}
            else: b2.pop("source", None)
            if sp_mode.value == "on":
                relax = 1.0 / (max(float(sp_tau.value or 1), 0.1) * 60.0)
                b2["sponge"] = {"width_km": float(sp_w.value or 40), "relax_uv": round(relax, 6), "relax_elev": round(relax, 6) if sp_eta.value else 0.0}
            elif sp_mode.value == "off": b2["sponge"] = None
            else: b2.pop("sponge", None)
            if bvel.value == "none":
                b2.pop("velocity", None)
            elif bvel.value == "flux":
                b2["velocity"] = float(bflux.value or 0)        # caudal constante en m3/s (negativo: entra)
            c2["boundaries"] = b2
            if not PRO:
                pass                                         # Lite: sin oleaje (la sección waves se conserva tal cual)
            elif waves_on.value:
                if wbt.value == "parametric":
                    wbc = {"type": "parametric", "hs": float(whs.value), "tp": float(wtp.value), "dir": float(wdir.value), "spread": float(wspr.value)}
                elif wbt.value == "series":
                    rows = []
                    for line in (wtab.value or "").splitlines():
                        parts = [x.strip() for x in line.replace(";", ",").split(",") if x.strip()]
                        if len(parts) >= 4:
                            rows.append([parts[0], float(parts[1]), float(parts[2]), float(parts[3])])
                    wbc = {"type": "series", "table": rows}
                elif wbt.value == "copernicus":
                    wbc = {"type": "copernicus", "source": wsrc.value, "step_hours": float(wstep.value)}
                else:
                    wbc = {"type": "none"}
                c2["waves"] = {**{k: v for k, v in (c2.get("waves") or {}).items() if k not in ("boundary_hs", "boundary_tp", "boundary_dir")},
                               "enabled": True, "nstep": int(wnstep.value), "boundary": wbc,
                               "variables": (c2.get("waves") or {}).get("variables", ["sigWaveHeight", "peakPeriod", "meanWaveDirection"])}
            else:
                c2["waves"] = {**(c2.get("waves") or {}), "enabled": False}
            return c2
        action_bar(t, collect, "forcing")


# ----------------------------------------------------------------------------- parametros
# ----------------------------------------------------------------------------- parametros de los .nml
def _case_modules(c: dict) -> tuple[str | None, list[str]]:
    """(variante que se usara, modulos efectivos: los de la compilacion mas los que exige el caso)."""
    from ..build import effective_build
    name, mods, _ = effective_build(c)
    return name, mods


def has_open_boundaries(c: dict) -> bool:
    """¿Tiene el caso algún contorno abierto? Idealizado: open_sides; polígono: open_boundaries != none y algún lado no pared."""
    m = c.get("mesh", {}) or {}
    g = m.get("generator", default_generator())
    if g == "idealized":
        return bool(m.get("open_sides"))
    if g == "file":
        return True
    if m.get("open_boundaries", "bbox") == "none":
        return False
    et = m.get("edge_types") or {}
    poly = m.get("polygon") or []
    return not (poly and len(et) >= len(poly) and all(v == "wall" for v in et.values()))


def build_chip(c: dict):
    """Chip con la compilacion efectiva del caso (visible en Modelo, Forzamientos, Parametros y Ejecutar)."""
    from ..build import effective_build
    t = T(); name, mods, built = effective_build(c)
    with ui.row().classes("items-center q-gutter-xs q-mb-sm"):
        ui.icon("memory").classes("text-positive" if built else "text-negative")
        ui.label(f"{t['build']}: pschism_{name}").classes("text-caption text-weight-bold")
        for k in mods:
            mod_chip(k)
        if not built:
            ui.badge(t["not_compiled"], color="negative").props("outline")


# ----------------------------------------------------------------------------- salidas
@ui.page("/outputs")
def page_outputs():
    t = T()
    with layout("outputs"):
        if need_case():
            return
        c = cfg(); wd = workdir(); oc = c.get("output", {}) or {}
        from ..setup import OUTPUT_VARS, OUTPUT_GROUPS, STATION_VARS
        from ..edition import pro as _pro
        WAVE_OUTPUTS = _pro("forcing.waves").WAVE_OUTPUTS if is_pro() else {}   # salidas de WWM: SCHISMlab Pro
        ui.label(t["step_outputs"]).classes("text-h4 text-primary")
        with ui.expansion(t["outputs_what"], icon="help_outline", value=False).classes("sl-exp w-full q-mb-sm"):
            ui.markdown(t["outputs_expl"]).classes("text-caption text-grey-8")
        is3d = (c.get("vertical") or {}).get("type", "2d") != "2d"
        geo = is_geographic_cfg(c)
        boxes: dict[str, ui.checkbox] = {}
        cur = set(oc.get("variables", ["elevation", "depthAverageVel"] + (["horizontalVel"] if is3d else [])))
        # --- variables
        with ui.card().classes("q-pa-md w-full"):
            ui.label(t["outputs"]).classes("text-subtitle1 text-weight-bold")
            nscr = ui.label().classes("text-caption text-grey-7")
            for grp, names in OUTPUT_GROUPS.items():
                ui.label(t["og_" + grp]).classes("text-subtitle2 q-mt-sm")
                if grp == "3d" and not is3d:
                    ui.label(t["og_3d_off"]).classes("text-caption text-orange-9")
                with ui.grid(columns=4).classes("w-full sl-grid"):
                    for v in names:
                        boxes[v] = ui.checkbox(t["ov_" + v], value=v in cur).props("dense"); boxes[v]._help_mode = "tooltip"
                        if grp == "3d" and not is3d:
                            boxes[v].set_enabled(False)
            wboxes: dict[str, ui.checkbox] = {}
            if (c.get("waves") or {}).get("enabled"):
                ui.label(t["og_waves"]).classes("text-subtitle2 q-mt-sm")
                wcur = set((c.get("waves") or {}).get("variables", ["sigWaveHeight", "peakPeriod", "meanWaveDirection"]))
                with ui.grid(columns=4).classes("w-full sl-grid"):
                    for v in WAVE_OUTPUTS:
                        wboxes[v] = ui.checkbox(v, value=v in wcur).props("dense")
            def count():
                n = sum((2 if OUTPUT_VARS[v][2] else 1) for v, b in boxes.items() if b.value and b.enabled) + sum(1 for b in wboxes.values() if b.value)
                nscr.set_text(t["nscribes_hint"].format(n=max(1, n)))
            for b in list(boxes.values()) + list(wboxes.values()):
                b.on_value_change(lambda e: count())
            count()
        # --- frecuencia y ficheros
        with ui.card().classes("q-pa-md w-full"):
            ui.label(t["out_timing"]).classes("text-subtitle1 text-weight-bold")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                out_int = ui.number(t["out_int"], value=float(oc.get("interval_minutes", 60)), min=0.1, step=5).classes("sl-w-md")
                stack_h = ui.number(t["stack_hours"], value=float(oc.get("stack_hours", 24)), min=0.1, step=6).classes("sl-w-md")
                hot_h = ui.number(t["hotstart_hours"], value=float(oc.get("hotstart_hours", 0) or 0), min=0, step=6).classes("sl-w-md")
            size_lbl = ui.label().classes("text-caption text-grey-7")
            def estimate():
                try:
                    from ..io.gr3 import read_gr3
                    hg = wd / "hgrid.gr3"
                    if not hg.exists():
                        size_lbl.set_text(t["size_nomesh"]); return
                    import re as _re
                    nn = int(_re.split(r"\s+", hg.read_text().splitlines()[1].strip())[1])
                    nv = int((c.get("vertical") or {}).get("nvrt", (c.get("vertical") or {}).get("nsigma", 1))) if is3d else 1
                    nt = float((c.get("time") or {}).get("days", 1)) * 1440 / max(float(out_int.value or 60), 0.1)
                    cells = 0
                    for v, b in boxes.items():
                        if b.value and b.enabled:
                            i, three, vec = OUTPUT_VARS[v]; cells += nn * (nv if three else 1) * (2 if vec else 1)
                    size_lbl.set_text(t["size_est"].format(mb=cells * 4 * nt / 1e6, nt=int(nt)))
                except Exception as ex:   # noqa: BLE001
                    size_lbl.set_text(str(ex))
            out_int.on_value_change(lambda e: estimate())
            for b in boxes.values():
                b.on_value_change(lambda e: estimate())
            estimate()
        # --- estaciones
        with ui.card().classes("q-pa-md w-full"):
            ui.label(t["stations"]).classes("text-subtitle1 text-weight-bold")
            ui.label(t["stations_expl"]).classes("text-caption text-grey-7")
            stations = list(c.get("stations", []))
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                sta_int = ui.number(t["sta_int"], value=float(oc.get("station_interval_minutes", 10)), min=0.1, step=1).classes("sl-w-md")
                svcur = set(oc.get("station_variables", ["elev", "T", "S", "u", "v", "w"]))
                with ui.row().classes("items-center q-gutter-x-sm"):
                    sboxes = {k: ui.checkbox(t["sv_" + k], value=k in svcur).props("dense") for k in STATION_VARS}
                for b_ in sboxes.values():
                    b_._help_mode = "tooltip"
            # tabla de estaciones junto al formulario de alta; el mapa (clic = nueva estación) debajo
            _xl, _yl = ("lon", "lat") if geo else ("x", "y")
            scols = [{"name": "name", "label": t["name"], "field": "name", "align": "left"}, {"name": "x", "label": _xl, "field": "x", "align": "right"},
                     {"name": "y", "label": _yl, "field": "y", "align": "right"}, {"name": "rm", "label": "", "field": "rm", "align": "center"}]
            with ui.row().classes("w-full items-start q-col-gutter-md"):
                with ui.column().classes("col-12 col-md-7"):
                    ui.label(t["stations_tbl"]).classes("text-subtitle2")
                    stable = ui.table(columns=scols, rows=[], row_key="i").props("dense flat bordered hide-pagination").classes("w-full")
                    stable.add_slot("body-cell-rm", """<q-td :props="props"><q-btn flat dense round icon="close" size="sm" @click="$parent.$emit('rm', props.row)" /></q-td>""")
                    # nombre editable en la propia tabla (clic en el nombre): se guarda al pulsar Intro o salir de la casilla
                    stable.add_slot("body-cell-name", """<q-td :props="props"><q-input dense borderless :model-value="props.row.name"
                        @update:model-value="v => props.row.name = v" @blur="$parent.$emit('rename', props.row)" @keyup.enter="$parent.$emit('rename', props.row)" /></q-td>""")
                    stable.add_slot("no-data", f"<div class='text-caption text-grey-7 q-pa-sm'>{t['no_stations']}</div>")
                with ui.column().classes("col-12 col-md-5"):
                    ui.label(t["add_station"]).classes("text-subtitle2")
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        sn = ui.input(t["name"], value=f"E{len(stations) + 1}").props("dense").classes("sl-w-sm")
                        slon = ui.number(_xl, value=2.636 if geo else 0.0).props("dense").classes("sl-w-sm"); slat = ui.number(_yl, value=39.556 if geo else 0.0).props("dense").classes("sl-w-sm")
                        def next_name() -> str:
                            used = {str(s_.get("name", "")) for s_ in stations}; k = len(stations) + 1
                            while f"E{k}" in used:
                                k += 1
                            return f"E{k}"
                        def push_station(x_, y_):
                            """Añade la estación con el nombre tecleado en la casilla (o E<n> si está vacía) y prepara el siguiente."""
                            name = (sn.value or "").strip() or next_name()
                            stations.append({"name": name, **({"lon": x_, "lat": y_} if geo else {"x": x_, "y": y_})})
                            sn.set_value(next_name()); station_list(); smap.update_figure(station_map_figure())
                        def add_station():
                            push_station(float(slon.value), float(slat.value))
                        ui.button(t["add_station"], icon="add", on_click=add_station).props("flat")
                    ui.label(t["station_click"]).classes("text-caption text-grey-7")
            def station_list():
                stable.rows = [{"i": i_, "name": str(s_.get("name", "")), "x": s_.get("lon", s_.get("x")), "y": s_.get("lat", s_.get("y"))} for i_, s_ in enumerate(stations)]
                stable.update()
            def rm_station(e):
                i_ = int((e.args or {}).get("i", -1))
                if 0 <= i_ < len(stations):
                    stations.pop(i_); station_list(); smap.update_figure(station_map_figure())
            def rename_station(e):
                a = e.args or {}; i_ = int(a.get("i", -1)); name = str(a.get("name", "")).strip()
                if 0 <= i_ < len(stations) and name and name != stations[i_].get("name"):
                    stations[i_]["name"] = name; station_list(); smap.update_figure(station_map_figure())
            stable.on("rm", rm_station); stable.on("rename", rename_station)
            # mapa del dominio: un clic añade una estación (la malla del caso si existe; si no, el rectángulo idealizado)
            from .ic_builder import preview_mesh
            from .figures import NodeSampler, layout as _layout, _aspect
            import plotly.graph_objects as go
            # la malla, el fondo y la costa se preparan fuera del bucle de eventos: con una malla grande tardan
            # varios segundos y bloqueaban la interfaz («conexión perdida» al entrar en la página)
            ctx = {"mesh": None, "base": [], "ready": False}
            def prepare_map():
                smesh = preview_mesh(c, wd); base = []
                if smesh is not None:
                    smp = NodeSampler(smesh, n=160)
                    base.append(go.Heatmap(x=smp.xi, y=smp.yi, z=smp.grid(smesh.depth), colorscale="deep", zmin=float(min(0.0, np.nanmin(smesh.depth))), colorbar=dict(title=t["depth_h"], thickness=12, tickformat=".3g"),
                                           hovertemplate="%{x:.4f}, %{y:.4f}<br>%{z:.0f} m<extra></extra>"))
                    if geo and (c.get("mesh", {}) or {}).get("generator", default_generator()) != "idealized":
                        from .figures import land_polygons, land_traces, boundary_traces
                        base += land_traces(land_polygons((float(smesh.x.min()), float(smesh.x.max())), (float(smesh.y.min()), float(smesh.y.max())))) + boundary_traces(smesh)
                ctx.update(mesh=smesh, base=base, ready=True)
            def station_map_figure():
                smesh = ctx["mesh"]
                fig = go.Figure(list(ctx["base"]))
                xs = [float(s_.get("lon", s_.get("x", 0))) for s_ in stations]; ys = [float(s_.get("lat", s_.get("y", 0))) for s_ in stations]
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=[str(s_.get("name", "")) for s_ in stations], textposition="top right",
                                         marker=dict(color="#e63946", size=11, line=dict(color="#fff", width=1.5)), hoverinfo="text", showlegend=False))
                fig.update_layout(title=t["station_map"] if ctx["ready"] else t["loading"], xaxis=dict(title="lon" if geo else "x (m)", constrain="domain"),
                                  yaxis=dict(title="lat" if geo else "y (m)", scaleanchor="x", scaleratio=_aspect(smesh.y) if (smesh is not None and geo) else 1), **_layout(bool(S().get("dark"))))
                return fig
            no_mesh_lbl = ui.label(t["ic_no_mesh"]).classes("text-caption text-orange-9"); no_mesh_lbl.set_visibility(False)
            smap = ui.plotly(station_map_figure()).classes("w-full").style("height:420px")
            station_list()
            async def fill_map():
                await run.io_bound(prepare_map)
                no_mesh_lbl.set_visibility(ctx["mesh"] is None)
                smap.update_figure(station_map_figure())
            ui.timer(0.05, fill_map, once=True)
            def on_map_click(e):
                pts = e.args.get("points", [])
                if not pts:
                    return
                x_, y_ = float(pts[0]["x"]), float(pts[0]["y"])
                push_station(round(x_, 4) if geo else round(x_, 1), round(y_, 4) if geo else round(y_, 1))
            from .explorer import CLICK_JS
            smap.on("plotly_click", on_map_click, js_handler=CLICK_JS)
        # --- subdominio
        with ui.card().classes("q-pa-md w-full"):
            ui.label(t["subdomain"]).classes("text-subtitle1 text-weight-bold")
            ui.markdown(t["subdomain_expl"]).classes("text-caption text-grey-8")
            sd = oc.get("subdomain") or {}
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                sd_on = ui.switch(t["subdomain_on"], value=bool(sd.get("lon") and sd.get("lat")))
                sd_lon = ui.input(t["lon_rng"] if geo else "x (min, max)", value=",".join(str(v) for v in sd.get("lon", [])) or "").props("dense").classes("sl-w-md")
                sd_lat = ui.input(t["lat_rng"] if geo else "y (min, max)", value=",".join(str(v) for v in sd.get("lat", [])) or "").props("dense").classes("sl-w-md")
                has_out = (wd / "outputs").exists() and bool(list((wd / "outputs").glob("out2d_*.nc")))
                crop_btn = ui.button(t["crop_now"], icon="content_cut").props("flat"); crop_btn.set_visibility(has_out)
            def sd_vis():
                sd_lon.set_visibility(sd_on.value); sd_lat.set_visibility(sd_on.value); crop_btn.set_visibility(sd_on.value and has_out)
            sd_on.on_value_change(lambda e: sd_vis()); sd_vis()
            async def crop_now():
                try:
                    lo = [float(v) for v in sd_lon.value.split(",")]; la = [float(v) for v in sd_lat.value.split(",")]
                    from ..analysis.output import crop_outputs
                    out = await run.io_bound(lambda: crop_outputs(wd, (lo[0], lo[1]), (la[0], la[1])))
                    _DS_CACHE.pop(str(out), None); ui.notify(f"{t['done']}: {out}", type="positive")
                except Exception as ex:   # noqa: BLE001
                    ui.notify(str(ex), type="negative")
            crop_btn.on_click(crop_now)

        def collect():
            c2 = cfg(); o2 = dict(c2.get("output", {}) or {})
            o2["variables"] = [v for v, b in boxes.items() if b.value and b.enabled] or ["elevation"]
            o2["interval_minutes"] = float(out_int.value or 60); o2["stack_hours"] = float(stack_h.value or 24)
            if float(hot_h.value or 0) > 0: o2["hotstart_hours"] = float(hot_h.value)
            else: o2.pop("hotstart_hours", None)
            o2["station_interval_minutes"] = float(sta_int.value or 10); o2["station_variables"] = [k for k, b in sboxes.items() if b.value]
            if sd_on.value:
                try:
                    o2["subdomain"] = {"lon": [float(v) for v in sd_lon.value.split(",")][:2], "lat": [float(v) for v in sd_lat.value.split(",")][:2]}
                except ValueError:
                    ui.notify(t["subdomain_bad"], type="warning"); o2.pop("subdomain", None)
            else:
                o2.pop("subdomain", None)
            c2["output"] = o2; c2["stations"] = stations
            if wboxes:
                c2["waves"] = {**(c2.get("waves") or {}), "variables": [v for v, b in wboxes.items() if b.value] or ["sigWaveHeight"]}
            return c2
        action_bar(t, collect, "outputs")


ISSUES_URL = "https://github.com/DrAmores/SCHISMlab-Lite/issues/new"


def diagnostic_text(case_dir: Path | None = None) -> tuple[str, str]:
    """(versión y sistema, últimas líneas de los registros) para una incidencia."""
    import platform
    from .. import __version__
    try:
        from ..update import _git
        commit = _git("rev-parse", "--short", "HEAD")
    except Exception:   # noqa: BLE001
        commit = "?"
    pv = Path("/proc/version")
    wsl = "WSL2" if (pv.exists() and "microsoft" in pv.read_text(errors="ignore").lower()) else platform.system()
    ver = f"{__version__} ({commit}) · {platform.system()} {platform.release()} ({wsl}) · Python {platform.python_version()}"
    logs = []
    for f in [HOME / "gui.log"] + ([case_dir / "run.log", case_dir / "outputs" / "fatal.error"] if case_dir else []):
        if f.exists():
            tail = f.read_text(errors="ignore").splitlines()[-25:]
            logs.append(f"--- {f.name}\n" + "\n".join(tail))
    return ver, "\n".join(logs)[-3500:]


def report_problem_dialog(t: dict):
    """Diálogo «Informar de un problema»: diagnóstico para copiar y enlace a una incidencia de GitHub ya rellena."""
    import urllib.parse
    ci = case_info()
    ver, logs = diagnostic_text(ci.workdir if ci else None)
    with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width:720px"):
        ui.label(t["report_problem"]).classes("text-h6")
        ui.markdown(t["report_hint"]).classes("text-body2 text-grey-8")
        # editable: el usuario puede quitar rutas o nombres antes de abrir la incidencia; el enlace usa el texto editado
        txt = ui.textarea(t["report_diag"], value=f"{ver}\n{'caso: ' + ci.name if ci else ''}\n\n{logs}").classes("w-full").props("rows=12 outlined")
        def issue_url() -> str:
            body = str(txt.value or "")
            head, _, rest = body.partition("\n\n")
            q = urllib.parse.urlencode({"template": "problema.yml", "version": head.replace("\n", " · ")[:300], "registro": rest[-2500:]})
            return f"{ISSUES_URL}?{q}"
        with ui.row().classes("q-gutter-sm"):
            ui.button(t["copy"], icon="content_copy", on_click=lambda: (ui.clipboard.write(txt.value), ui.notify(t["copied"]))).props("flat")
            ui.button(t["report_open"], icon="open_in_new", on_click=lambda: ui.navigate.to(issue_url(), new_tab=True)).props("color=accent")
            ui.button(t["report_list"], icon="list", on_click=lambda: ui.navigate.to(ISSUES_URL.rsplit("/", 1)[0], new_tab=True)).props("flat")
            ui.button(t["cancel"], on_click=dlg.close).props("flat")
    dlg.open()


def USER_CASES_DIR() -> Path:
    from .state import USER_CASES
    return USER_CASES


def is_geographic_cfg(c: dict) -> bool:
    from ..initial import is_geographic
    return is_geographic(c)


# ----------------------------------------------------------------------------- actualizar
@ui.page("/update")
def page_update():
    t = T()
    with layout("update"):
        from .. import __version__
        from ..update import check, apply, restart_gui, simulation_running, changelog_since, is_git_repo, REPO as _REPO
        ui.label(t["update"]).classes("text-h4 text-primary")
        ui.markdown(t["update_expl"].format(version=__version__, repo=str(_REPO))).classes("text-body2 text-grey-8")
        if not is_git_repo():
            ui.label(t["update_nogit"]).classes("text-orange-9"); return
        status = ui.markdown().classes("text-body2")
        changes = ui.markdown().classes("text-body2")
        log = log_with_placeholder(t, max_lines=300, classes="w-full h-48")
        with ui.row().classes("q-gutter-sm items-center"):
            chk_btn = ui.button(t["update_check"], icon="refresh").props("outline color=primary")
            upd_btn = ui.button(t["update_now"], icon="system_update").props("color=accent"); upd_btn.set_visibility(False)
            rst_btn = ui.button(t["restart_gui"], icon="restart_alt").props("color=secondary"); rst_btn.set_visibility(False)
        state = {}
        def show(st):
            state.update(st)
            if st.get("error"):
                status.set_content(f"⚠️ {t['update_error']}: `{st['error']}`"); upd_btn.set_visibility(False); return
            if st.get("behind"):
                vr = st.get("version_remote")
                status.set_content(t["update_behind"].format(n=st["behind"], local=st.get("local", ""), remote=st.get("remote", ""), version=(vr or "")))
                cl = changelog_since(vr)
                commits = "\n".join(f"- `{h}` {d} · {m}" for h, d, m in st.get("commits", [])[:30])
                changes.set_content((f"**{t['update_news']}**\n\n{cl}\n\n" if cl else "") + f"**{t['update_commits']}**\n\n{commits}")
                upd_btn.set_visibility(True)
                if st.get("dirty"):
                    status.set_content(status.content + "\n\n⚠️ " + t["update_dirty"]); upd_btn.set_visibility(False)
            else:
                status.set_content(t["update_uptodate"].format(local=st.get("local") or "—")); changes.set_content(""); upd_btn.set_visibility(False)
        async def do_check():
            status.set_content(t["update_checking"]); chk_btn.disable()
            try:
                st = await run.io_bound(lambda: check(force=True)); show(st)
            finally:
                chk_btn.enable()
        async def do_update():
            upd_btn.disable(); chk_btn.disable(); log.clear()
            lines = []
            def lf(msg):
                lines.append(str(msg))
            timer = ui.timer(0.5, lambda: [log.push(l) for l in lines[len(getattr(timer, "_shown", [])):]] and None)
            shown = {"n": 0}
            def poll():
                for l in lines[shown["n"]:]:
                    log.push(l)
                shown["n"] = len(lines)
            timer.callback = poll
            try:
                r = await run.io_bound(lambda: apply(log_fn=lf))
            except Exception as ex:   # noqa: BLE001
                r = dict(ok=False, restart=False, message=str(ex))
            finally:
                timer.active = False; poll(); chk_btn.enable(); upd_btn.enable()
            log.push(r["message"])
            if r["ok"] and r["restart"]:
                ui.notify(t["update_done"], type="positive")
                if simulation_running():
                    log.push(t["update_sim_running"])
                rst_btn.set_visibility(True); upd_btn.set_visibility(False)
            elif not r["ok"]:
                ui.notify(r["message"], type="negative")
        async def do_restart():
            if simulation_running():
                with ui.dialog() as dlg, ui.card():
                    ui.label(t["update_sim_running"])
                    with ui.row():
                        ui.button(t["restart_gui"], color="negative", on_click=lambda: dlg.submit(True)); ui.button(t["cancel"], on_click=lambda: dlg.submit(False))
                if not await dlg:
                    return
            ui.notify(t["restarting"], type="info"); await asyncio.sleep(1.0)
            restart_gui()
        chk_btn.on_click(do_check); upd_btn.on_click(do_update); rst_btn.on_click(do_restart)
        show(check(force=False) if not os.environ.get("SCHISMLAB_NO_UPDATE_CHECK") else {})   # estado conocido (sin red)
        if not os.environ.get("SCHISMLAB_NO_UPDATE_CHECK"):
            ui.timer(0.3, do_check, once=True)


@ui.page("/params")
def page_params():
    t = T(); lang = S().get("lang", "es")
    with layout("params"):
        if need_case():
            return
        from ..build import installed, MODULES, required_namelists
        from ..io.namelist_catalog import catalog, sections, is_auto, NAMELIST_MODULE
        c = cfg(); wd = workdir()
        ui.label(t["step_params"]).classes("text-h4 text-primary"); ui.label(t["params_sub"]).classes("text-grey-7")
        variant, mods = _case_modules(c)
        with ui.row().classes("q-gutter-xs items-center q-mb-sm"):
            ui.label(t["modules"] + ":").classes("text-caption")
            for k in mods:
                mod_chip(k)
            ui.button(t["build_card"], icon="tune", on_click=lambda: ui.navigate.to("/model")).props("flat dense")
        # --- ficheros aplicables
        files = ["param.nml"] + [n for n in required_namelists(mods)]
        overrides_all = dict(c.get("namelists") or {})
        if c.get("param"):
            overrides_all["param.nml"] = {**(c.get("param") or {}), **overrides_all.get("param.nml", {})}
        inputs: dict[str, dict[str, ui.input]] = {}
        builders: dict[str, list] = {}              # fichero -> [(expansion, construir())] de las secciones aún no construidas
        if len(files) == 1:
            ui.label(files[0]).classes("text-subtitle1 text-weight-bold q-mt-sm")
            containers = {files[0]: ui.column().classes("w-full")}
        else:
            with ui.tabs().classes("w-full").props("dense no-caps mobile-arrows") as tabs:
                tab_el = {f: ui.tab(f) for f in files}
            tpanels = ui.tab_panels(tabs, value=tab_el[files[0]]).classes("w-full")
            containers = {}
            for f in files:
                with tpanels:
                    containers[f] = ui.tab_panel(tab_el[f])
        for f in files:
            with containers[f]:
                entries = catalog(f); ov = {str(k): v for k, v in (overrides_all.get(f) or {}).items()}; inputs[f] = {}; builders[f] = []
                with ui.row().classes("row wrap q-col-gutter-sm items-center w-full"):
                    search = ui.input(t["search"]).props("dense clearable").classes("sl-w-md")
                    only_changed = ui.switch(t["only_changed"], value=False).props("dense")
                    show_all = ui.switch(t["show_all"], value=False).props("dense")
                    ui.label(f"{len(entries)} {t['n_params']}").classes("text-caption text-grey-7")
                rows: list[tuple[dict, ui.element]] = []
                def build_section(exp, sec_entries, f=f, ov=ov, rows=rows):
                    with exp:
                        for e in sec_entries:
                            foreign = bool(e.modules) and not any(m in mods for m in e.modules) and f == "param.nml"
                            value = ov.get(e.name, e.default); custom = e.name in ov; auto = is_auto(e, f)
                            with ui.row().classes("items-start w-full no-wrap q-py-xs").style("border-bottom:1px solid " + ("#333" if S().get("dark") else "#eee")) as row:
                                ui.label(e.name).classes("text-weight-bold").style("width:190px;font-family:monospace;font-size:13px;padding-top:8px")
                                inp = ui.input(value=str(value)).props("dense outlined").style("width:170px")
                                inp.default = e.default
                                inputs[f][e.name] = inp
                                with ui.column().classes("q-gutter-none").style("flex:1;padding-top:6px"):
                                    with ui.row().classes("items-center q-gutter-xs"):
                                        badge = ui.badge(t["status_custom"] if custom else (t["status_auto"] if auto else t["status_default"]),
                                                         color="accent" if custom else ("secondary" if auto else "grey-5")).props("outline")
                                        if auto:
                                            with badge:
                                                ui.tooltip(t["auto_hint"])
                                        if foreign:
                                            ui.badge(f"{t['needs_module']} {', '.join(e.modules)}", color="orange").props("outline")
                                        if e.default != "" and custom:
                                            ui.label(f"{t['default_is']}: {e.default}").classes("text-caption text-grey-6")
                                        ui.button(icon="restart_alt", on_click=lambda _, i=inp, b=badge, e=e: (i.set_value(e.default), b.set_text(t["status_default"]))).props("flat dense round size=sm").tooltip(t["reset"])
                                    ui.label(e.help(lang)).classes("text-caption")
                                    lh = e.long_help()
                                    if lh and lh != e.help(lang):
                                        with ui.expansion("ℹ").props("dense header-class=text-caption").classes("text-caption text-grey-7"):
                                            ui.label(lh).classes("text-caption").style("white-space:pre-wrap")
                                inp.on_value_change(lambda ev, b=badge, e=e: b.set_text(t["status_default"] if ev.value == e.default else t["status_custom"]))
                            rows.append(({"name": e.name.lower(), "help": (e.help(lang) + " " + e.long_help()).lower(), "foreign": foreign, "inp": inp, "default": e.default}, row))
                            if foreign:
                                row.set_visibility(False)
                def build_all(f=f):                               # buscar o filtrar: hacen falta todas las secciones
                    for exp, fn in list(builders[f]):
                        fn()
                    builders[f].clear()
                for k_, sec in enumerate(sections(f)):
                    sec_entries = [e for e in entries if e.section == sec]
                    first = any(e.name == "rnday" for e in sec_entries) or (k_ == 0 and f != "param.nml")
                    with ui.expansion(f"&{sec}  ({len(sec_entries)})", icon="folder_open", value=first).classes("w-full q-mb-sm") as exp:
                        pass
                    if first:
                        build_section(exp, sec_entries)
                    else:
                        def _mk(exp=exp, sec_entries=sec_entries, f=f):
                            done_ = {"v": False}
                            def go():
                                if not done_["v"]:
                                    done_["v"] = True; build_section(exp, sec_entries)
                            return go
                        fn = _mk(); builders[f].append((exp, fn))
                        exp.on_value_change(lambda e, fn=fn, exp=exp, f=f: (fn(), builders[f].remove((exp, fn)) if (exp, fn) in builders[f] else None))
                def apply_filter(rows=rows, search=search, only_changed=only_changed, show_all=show_all, build_all=build_all):
                    build_all()
                    q = (search.value or "").lower().strip()
                    for meta, row in rows:
                        vis = (not meta["foreign"] or show_all.value)
                        if q:
                            vis = vis and (q in meta["name"] or q in meta["help"])
                        if only_changed.value:
                            vis = vis and meta["inp"].value != meta["default"]
                        row.set_visibility(vis)
                search.on_value_change(lambda e, fn=apply_filter: fn()); only_changed.on_value_change(lambda e, fn=apply_filter: fn()); show_all.on_value_change(lambda e, fn=apply_filter: fn())
                gen = wd / f
                with ui.expansion(t["preview"], icon="description").classes("w-full q-mt-md"):
                    if gen.exists():
                        ui.code(gen.read_text(errors="ignore"), language="fortran").classes("w-full").style("max-height:500px;overflow:auto")
                    else:
                        ui.label(t["no_preview"]).classes("text-grey-7")
        def collect():
            c2 = cfg(); nl = {}
            for f, d in inputs.items():
                ov = {str(k): v for k, v in (overrides_all.get(f) or {}).items()}   # secciones sin abrir: se conservan
                for name, inp in d.items():
                    v = inp.value
                    if v is None or str(v).strip() == str(inp.default).strip():
                        ov.pop(name, None); continue
                    ov[name] = _parse_value(str(v))
                if ov:
                    nl[f] = ov
            if nl:
                c2["namelists"] = nl
            else:
                c2.pop("namelists", None)
            c2.pop("param", None)        # migrado a namelists.param.nml
            return c2
        action_bar(t, collect, "params")


def log_with_placeholder(t: dict, max_lines: int = 300, classes: str = "w-full h-48") -> ui.log:
    """ui.log oculto hasta la primera línea; mientras tanto, un texto gris («Aquí aparecerá el registro»)."""
    ph = ui.label(t["log_empty"]).classes("text-caption text-grey-6 q-py-sm")
    log = ui.log(max_lines=max_lines).classes(classes); log.set_visibility(False)
    orig_push = log.push
    def push(line, *a, **kw):
        if not log.visible:
            ph.set_visibility(False); log.set_visibility(True)
        return orig_push(line, *a, **kw)
    log.push = push
    return log


def _parse_value(v: str):
    s = v.strip()
    if s.upper() in ("T", "F", ".TRUE.", ".FALSE."):
        return s
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


# ----------------------------------------------------------------------------- ejecutar
@ui.page("/run")
def page_run():
    t = T()
    with layout("run"):
        if need_case():
            return
        c = cfg_run(); wd = run_workdir(); _mem = active_member()
        if _mem:
            ui.label(t["member_select"] + f": {_mem}").classes("text-subtitle2 text-secondary")
        ui.label(t["step_run"]).classes("text-h4 text-primary"); build_chip(c)
        # comprobaciones
        PRO = is_pro()
        if PRO:                                                  # credenciales de datos y clúster: SCHISMlab Pro
            from ..edition import pro as _pro
            era5_ok = _pro("data.era5").have_credentials
            cmems_ok = _pro("data.cmems").have_credentials
            fes_ok = _pro("data.fes").have_credentials
            reachable = _pro("cluster.tramuntana").reachable
        else:
            era5_ok = cmems_ok = fes_ok = reachable = lambda: False
            from ..checks import pro_features
            _used = pro_features(c, S().get("lang", "es"))
            if _used:
                pro_notice(t, t["pro_case"].format(what=", ".join(_used)))
        checks = []
        from ..build import effective_build
        variant, _, built = effective_build(c)
        checks.append((built, f"SCHISM pschism_{variant}: {t['compiled'] if built else t['not_compiled']}"))
        checks.append(((wd / "hgrid.gr3").exists(), f"{t['status_mesh']}: {t['done'] if (wd / 'hgrid.gr3').exists() else t['pending']}"))
        if (c.get("forcing", {}).get("atmosphere") or {}).get("source") == "era5":
            checks.append((era5_ok(), f"ERA5: {t['ok'] if era5_ok() else t['missing']}"))
        if (c.get("initial", {}).get("source") or {}).get("name", "").startswith(("medsea", "global")) or c.get("boundaries", {}).get("source"):
            checks.append((cmems_ok(), f"Copernicus Marine: {t['ok'] if cmems_ok() else t['missing']}"))
        tides = (c.get("boundaries", {}).get("elevation") or {})
        if isinstance(tides, dict) and tides.get("tides", {}).get("source") == "fes2022":
            checks.append((fes_ok(), f"FES2022: {t['ok'] if fes_ok() else t['missing']}"))
        q = json.loads((wd / "mesh_quality.json").read_text()) if (wd / "mesh_quality.json").exists() else {}
        dt = float(c.get("time", {}).get("dt", 60)); days = float(c.get("time", {}).get("days", 1))
        if q and q.get("nodes"):
            from ..estimate import estimate, fmt_range
            el_ = estimate(c, int(q.get("nodes", 0) or 0)); ec_ = estimate(c, int(q.get("nodes", 0) or 0), 128, cluster=True)
            _lg = S().get("lang", "es")
            checks.append((dt <= 10 * q.get("dt_cfl_p5_s", dt), f"dt = {fmt_num(dt, _lg)} s · CFL {fmt_num(q.get('dt_cfl_p5_s', 0), _lg)} s · {t['est']}: {fmt_range(el_, _lg)} ({el_['nprocs']} {t['cores']})"
                           + (f" · {t['cluster']}: {fmt_range(ec_, _lg)}" if PRO else "")))
        with ui.card().classes("q-pa-md w-full"):
            ui.label(t["checks"]).classes("text-subtitle1 text-weight-bold")
            for ok, msg in checks:
                with ui.row().classes("items-center"):
                    ui.icon("check_circle" if ok else "error").classes("text-positive" if ok else "text-negative"); ui.label(msg)
        log = log_with_placeholder(t, max_lines=400, classes="w-full h-64")
        prog = ui.linear_progress(value=0, show_value=False).classes("w-full")
        prog_lbl = ui.label().classes("text-caption text-grey-7")
        jkey = str(wd)
        def show_progress():
            step, total = run_progress(wd); prog.value = step / total
            prog_lbl.set_text(f"{t['progress']}: {100 * step / total:.1f} % ({step}/{total})" if step else "")
        with ui.row().classes("row wrap q-col-gutter-sm items-center"):
            skey = f"{wd}:setup"
            async def setup():
                log.clear(); cp = case_path()
                setup_btn.disable(); stop_setup_btn.set_visibility(True)
                try:                                            # proceso aparte: se puede detener (descargas de ERA5, CMEMS…)
                    await run_job_process("schismlab_pro.runs.project:prepare_from_yaml" if _mem else "schismlab.setup:setup_case_from_yaml",
                                          (str(cp), _mem) if _mem else (str(cp),), log,
                                          on_done=lambda r: ui.notify(t["done"], type="positive"), key=skey)
                finally:
                    setup_btn.enable(); stop_setup_btn.set_visibility(False)
            def stop_setup():
                j = _JOBS.get(skey)
                if j is not None and not j.done and hasattr(j, "stop"):
                    j.stop(); ui.notify(t["stopped"], type="warning")
            setup_btn = ui.button(t["setup"], icon="build_circle", on_click=setup).props("color=primary")
            stop_setup_btn = ui.button(t["stop_run"], icon="stop", on_click=stop_setup).props("color=negative"); stop_setup_btn.set_visibility(False)
            prev_s = _JOBS.get(skey)                            # al volver con una preparacion en marcha: seguirla
            if prev_s is not None and not prev_s.done:
                setup_btn.disable(); stop_setup_btn.set_visibility(True); shown_s = {"n": 0}
                def follow_s():
                    for line in prev_s.lines[shown_s["n"]:]:
                        log.push(line)
                    shown_s["n"] = len(prev_s.lines)
                    if prev_s.done:
                        stimer.active = False; setup_btn.enable(); stop_setup_btn.set_visibility(False)
                        ui.notify(t["done"] if prev_s.error is None else f"{t['failed']}: {prev_s.error}", type="positive" if prev_s.error is None else "negative")
                stimer = ui.timer(1.0, follow_s)
            from ..estimate import default_local_cores
            ncores = ui.number(t["ncores"], value=default_local_cores(), min=1).props("dense").classes("sl-w-sm")
            from ..run import local_pid, stop_local
            async def run_local_():
                log.clear(); from ..run import run_local
                from ..run import post_run
                c_now = cfg_run()                                   # leer la configuración aquí: en el hilo no hay contexto de interfaz
                def _go():
                    rc = run_local(wd, ncores=int(ncores.value))
                    if rc == 0: post_run(wd, c_now)
                    return rc
                run_btn.set_visibility(False); stop_btn.set_visibility(True)
                def done(rc):
                    run_btn.set_visibility(True); stop_btn.set_visibility(False)
                    if rc == 130: ui.notify(t["stopped"], type="warning")
                    else: ui.notify(t["finished"] if rc == 0 else t["failed"], type="positive" if rc == 0 else "negative")
                    if rc == 0: results_btn.set_visibility(True)
                try:
                    await run_job(_go, log, progress=prog, wd=wd, on_done=done, key=jkey)
                finally:
                    run_btn.set_visibility(True); stop_btn.set_visibility(False)
            async def stop_local_():
                ok = await run.io_bound(lambda: stop_local(wd))
                ui.notify(t["stopped"] if ok else t["nothing_running"], type="warning" if ok else "info")
                run_btn.set_visibility(True); stop_btn.set_visibility(False)
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                run_btn = ui.button(t["run_local"], icon="play_arrow", on_click=run_local_).props("color=accent")
                stop_btn = ui.button(t["stop_run"], icon="stop", on_click=stop_local_).props("color=negative")
                has_results = (wd / "outputs").is_dir() and bool(list((wd / "outputs").glob("out2d_*.nc")))
                results_btn = ui.button(t["view_results"], icon="insights", on_click=lambda: ui.navigate.to("/results")).props("color=primary unelevated")
                results_btn.set_visibility(has_results)
            # al volver a esta página con una simulación en marcha: recuperar su registro y seguir mostrando el progreso
            prev = _JOBS.get(jkey)
            running_now = (prev is not None and not prev.done) or local_pid(wd) is not None
            run_btn.set_visibility(not running_now); stop_btn.set_visibility(running_now)
            if running_now:
                shown = {"n": 0}
                def follow():
                    if prev is not None:
                        for line in prev.lines[shown["n"]:]:
                            log.push(line)
                        shown["n"] = len(prev.lines)
                    show_progress()
                    if (prev is not None and prev.done) or (prev is None and local_pid(wd) is None):
                        ftimer.active = False; run_btn.set_visibility(True); stop_btn.set_visibility(False)
                        if (prev is not None and prev.result == 0) or (prev is None and bool(list((wd / "outputs").glob("out2d_*.nc")))):
                            results_btn.set_visibility(True)
                        ui.notify(t["finished"] if (prev is not None and prev.result == 0) else t["stopped"] if (prev is not None and prev.result == 130) else t["done"], type="info")
                if prev is None:
                    ui.label(t["running_other"]).classes("text-caption text-orange-9")
                ftimer = ui.timer(1.0, follow)
        if PRO:                                             # clúster: SCHISMlab Pro
            with ui.card().classes("q-pa-md w-full q-mt-md"):
                ui.label(t["cluster"]).classes("text-subtitle1 text-weight-bold")
                if not reachable():
                    ui.label(t["unreachable"]).classes("text-negative")
                else:
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        user = ui.input(t["user"], value=S().get("cluster_user", "")).props("dense"); cc = ui.number(t["ncores"], value=32, min=1).props("dense").classes("sl-w-sm")
                        part = ui.select(["cpu", "express"], value="cpu", label=t["partition"]).props("dense").classes("sl-w-sm"); wall = ui.input(t["wall"], value="12:00:00").props("dense").classes("sl-w-sm")
                        node = ui.select(["", "ada", "thor", "pampero"], value="", label=t["node"]).props("dense").classes("sl-w-sm")
                        ckey = jkey + ":cluster"
                        async def wait():
                            from ..edition import pro as _pro
                            _pro_cluster = _pro("cluster")
                            Cluster = _pro_cluster.Cluster
                            if not (wd / "jobid").exists():
                                ui.notify(t["nothing_running"], type="info"); return
                            c_now = cfg_run(); u_now = user.value
                            def go():
                                from ..run import post_run
                                cl = Cluster(u_now); cl.connect(); st = cl.wait((wd / "jobid").read_text().strip(), rundir=wd)
                                if st.startswith("COMPLETED"):
                                    cl.fetch(wd); post_run(wd, c_now)
                                return st
                            cancel_btn.set_visibility(True)
                            try:
                                await run_job(go, log, on_done=lambda s_: ui.notify(str(s_), type="positive" if str(s_).startswith("COMPLETED") else "warning"), key=ckey)
                            finally:
                                cancel_btn.set_visibility(False)
                        async def submit():
                            S().update(cluster_user=user.value); Cluster = _pro("cluster").Cluster
                            def go():
                                cl = Cluster(user.value); cl.connect()
                                if not cl.installed(): cl.install(REPO)
                                return cl.submit(wd, ncores=int(cc.value), partition=part.value, walltime=wall.value, node=node.value or None)
                            job = await run_job(go, log, on_done=lambda j: ui.notify(f"{t['job']} {j}", type="positive"))
                            if job.error is None:
                                await wait()                                   # seguimiento automático: estado cada 10 s
                        async def cancel():
                            from ..edition import pro as _pro
                            _pro_cluster = _pro("cluster")
                            Cluster = _pro_cluster.Cluster
                            if not (wd / "jobid").exists():
                                ui.notify(t["nothing_running"], type="info"); return
                            def go():
                                cl = Cluster(user.value); cl.connect(); return cl.cancel((wd / "jobid").read_text().strip())
                            await run_job(go, log, on_done=lambda s_: ui.notify(f"{t['stopped']}: {s_}", type="warning"))
                        smem = ui.input(t["setup_mem"], value="64G").props("dense").classes("sl-w-sm")
                        async def setup_cluster():
                            S().update(cluster_user=user.value); Cluster = _pro("cluster").Cluster
                            cp = case_path(); u_now = user.value
                            def go():
                                cl = Cluster(u_now); cl.connect()
                                job = cl.setup(cp, mem=(smem.value or "64G").strip(), partition=part.value, node=node.value or None, only=_mem)
                                cl.wait(job)
                                r = cl.fetch_setup(workdir())
                                if not r["ok"]:
                                    raise RuntimeError(f"{r['state']}: {r['reason']}")
                                return r["state"]
                            log.clear()
                            await run_job(go, log, on_done=lambda s_: ui.notify(t["setup_fetched"], type="positive"), key=jkey + ":setup_cluster")
                        ui.button(t["setup_cluster"], icon="cloud_sync", on_click=setup_cluster).props("outline").tooltip(t["setup_cluster_hint"])
                        ui.button(t["run_cluster"], icon="cloud_upload", on_click=submit).props("color=secondary")
                        ui.button(t["wait_fetch"], icon="cloud_download", on_click=wait).props("outline")
                        cancel_btn = ui.button(t["stop_cluster"], icon="cancel", on_click=cancel).props("color=negative")
                        cancel_btn.set_visibility((wd / "jobid").exists())
                    prevc = _JOBS.get(ckey)
                    if prevc is not None and not prevc.done:          # seguimiento en marcha al volver a la página
                        shownc = {"n": 0}
                        def followc():
                            for line in prevc.lines[shownc["n"]:]:
                                log.push(line)
                            shownc["n"] = len(prevc.lines)
                            if prevc.done:
                                ctimer.active = False
                        ctimer = ui.timer(1.0, followc)


# ----------------------------------------------------------------------------- analizar
def _outputs_stamp(wd: Path) -> float:
    """Fecha (mtime) del fichero de salida más reciente: cambia con cada simulación nueva o descarga del clúster."""
    out = wd / "outputs" if (wd / "outputs").is_dir() else wd
    files = list(out.glob("out2d_*.nc"))
    return max((f.stat().st_mtime for f in files), default=0.0)


def get_ds(wd: Path):
    key = str(wd); stamp = _outputs_stamp(wd)
    if key not in _DS_CACHE or _DS_CACHE[key][0] != stamp:      # salidas nuevas: reabrir (no mostrar la simulación anterior)
        from ..analysis import open_run
        _DS_CACHE[key] = (stamp, open_run(wd))
    return _DS_CACHE[key][1]


def vgrid_of(c: dict, wd: Path, ds=None):
    """Malla vertical de la simulación de la carpeta `wd` (ver schismlab.analysis.output.run_vgrid)."""
    from ..analysis.output import run_vgrid
    return run_vgrid(wd, ds, cfg=c)


def _results_content(tab_key: str):
    """Contenido de la página de resultados (pestañas)."""
    t = T()
    with layout("results"):
        if need_case():
            return
        c = cfg_run(); wd_case = run_workdir()
        head_row = ui.row().classes("items-center w-full q-col-gutter-sm")
        with head_row:
            ui.label(t["step_results"]).classes("text-h4 text-primary")
        from ..run import list_runs
        runs = list_runs(wd_case)
        if not runs:
            ui.label(t["no_outputs"]).classes("text-h6 text-grey-7")
            if is_pro() and cfg().get("runs"):                # proyecto: el análisis de sus simulaciones no necesita las del base
                from ..edition import pro as _pro
                with ui.card().classes("q-pa-md w-full q-mt-md"):
                    ui.label(t["tab_runs"]).classes("text-subtitle1 text-weight-bold")
                    _pro("gui.runs").runs_tab(None, c, wd_case, t, S().get("lang", "es"), dark=bool(S().get("dark")))
            return
        from ..analysis import nearest_node
        # --- qué simulación ver: la actual (outputs/) o una archivada (outputs_<fecha>/)
        sel_key = f"run_sel:{wd_case}"
        chosen = S().get(sel_key) or str(runs[0]["path"])
        if chosen not in {str(r["path"]) for r in runs}:
            chosen = str(runs[0]["path"])
        labels = {str(r["path"]): (t["run_current"] + " · " if r["current"] else "") + f"{r['when']} ({r['stacks']} {t['files']})" for r in runs}
        with head_row, ui.row().classes("items-center q-gutter-sm wrap col") as rsel_row:
            rsel = ui.select(labels, value=chosen, label=t["run_select"], on_change=lambda e: (S().update(**{sel_key: e.value}), ui.navigate.reload())).classes("sl-w-xl")
            run_dir = Path(chosen)
            is_current = run_dir.name == "outputs"
        # --- gestión de las simulaciones del caso: ver, crear un caso a partir de una, borrar
        async def delete_run(r):
            with ui.dialog() as dlg, ui.card():
                ui.label(t["run_delete_q"].format(name=labels[str(r["path"])]))
                with ui.row():
                    ui.button(t["delete"], color="negative", on_click=lambda: dlg.submit(True))
                    ui.button(t["cancel"], on_click=lambda: dlg.submit(False))
            if await dlg:
                import shutil as _sh
                _sh.rmtree(r["path"], ignore_errors=True); _DS_CACHE.pop(str(r["path"]), None); _DS_CACHE.pop(str(wd_case), None)
                if r["current"]:
                    _sh.rmtree(wd_case / "outputs_recorte", ignore_errors=True)
                S().update(**{sel_key: None}); ui.navigate.reload()
        async def case_from(r):
            from ..run import case_from_run
            with ui.dialog() as dlg, ui.card():
                ui.label(t["run_case_q"])
                nm = ui.input(t["name"], value=f"{wd_case.name}_{r['path'].name.replace('outputs_', '')}").classes("sl-w-lg")
                rf = folder_input(t)
                with ui.row():
                    ui.button(t["create"], on_click=lambda: dlg.submit(nm.value))
                    ui.button(t["cancel"], on_click=lambda: dlg.submit(None))
            name = await dlg
            if name:
                try:
                    p_ = case_from_run(r["path"] if not r["current"] else wd_case, name, USER_CASES_DIR(), workdir_root=chosen_root(rf.value))
                    ui.notify(f"{t['done']}: {p_.name}", type="positive")
                except Exception as ex:   # noqa: BLE001
                    ui.notify(str(ex), type="negative")
        with rsel_row, ui.button(icon="history").props("flat round").tooltip(t["runs_manage"]), ui.menu().classes("q-pa-sm"):
            ui.label(t["runs_manage"]).classes("text-subtitle2")
            ui.label(t["runs_manage_hint"]).classes("text-caption text-grey-7").style("max-width:560px")
            for r in runs:
                info = r["info"]
                with ui.row().classes("items-center q-gutter-sm no-wrap"):
                    ui.icon("play_circle" if r["current"] else "history").classes("text-primary" if r["current"] else "text-grey-7")
                    ui.label(labels[str(r["path"])]).classes("text-body2").style("min-width:260px")
                    desc = []
                    if info.get("machine"): desc.append(info["machine"] + (f" {info.get('host', '')}" if info.get("host") else "") + (f" · job {info['jobid']}" if info.get("jobid") else ""))
                    if info.get("ncores"): desc.append(f"{info['ncores']} {t['cores']}")
                    if info.get("seconds"): desc.append(f"{info['seconds'] / 60:.1f} min")
                    elif info.get("elapsed"): desc.append(str(info["elapsed"]))
                    if info.get("schismlab_commit"): desc.append(f"SCHISMlab {info['schismlab_commit']}")
                    desc.append(f"{r['size'] / 1e6:.0f} MB")
                    desc.append(t["reproducible"] if r["reproducible"] else t["not_reproducible"])
                    ui.label(" · ".join(desc)).classes("text-caption text-grey-7")
                    ui.button(icon="visibility", on_click=lambda r=r: (S().update(**{sel_key: str(r["path"])}), ui.navigate.reload())).props("flat dense round")
                    ui.button(t["run_case"], icon="content_copy", on_click=lambda r=r: case_from(r)).props("flat dense")
                    ui.button(icon="delete", on_click=lambda r=r: delete_run(r)).props("flat dense round color=negative")
        # directorio con la malla/vgrid de esa simulación (las archivadas llevan copia; si falta, el del caso)
        wd = run_dir if (not is_current and (run_dir / "hgrid.gr3").exists()) else wd_case
        crop_dir = (wd_case / "outputs_recorte") if is_current else (run_dir / "recorte")
        has_crop = crop_dir.exists() and bool(list(crop_dir.glob("out2d_*.nc")))
        try:
            if has_crop:
                use_crop = ui.switch(t["use_crop"], value=bool(S().get("use_crop", True)), on_change=lambda e: (S().update(use_crop=bool(e.value)), ui.navigate.reload()))
                ds = get_ds(crop_dir if use_crop.value else (wd_case if is_current else run_dir))
            else:
                ds = get_ds(wd_case if is_current else run_dir)
        except Exception as ex:   # noqa: BLE001  (simulación escribiendo, pila corrupta, sin permisos…)
            ui.label(t["outputs_unreadable"].format(err=ex)).classes("text-orange-9"); return
        import datetime as _dt
        _src = crop_dir if (has_crop and S().get("use_crop", True)) else (wd_case if is_current else run_dir)
        _when = _dt.datetime.fromtimestamp(_outputs_stamp(_src)).strftime("%Y-%m-%d %H:%M")
        _t0, _t1 = (np.datetime_as_string(ds.time.values[i], "m").replace("T", " ") for i in (0, -1))
        with rsel:                                       # sello de la simulación (fecha, ficheros, instantes) al pasar el ratón
            ui.tooltip(t["results_stamp"].format(when=_when, n=len(list((_src / "outputs" if (_src / "outputs").is_dir() else _src).glob("out2d_*.nc"))), t0=_t0, t1=_t1, nt=ds.time.size)).style("max-width:420px;font-size:12px")
        tab_keys = ["maps", "spectrum", "particles", "compare"] + (["validate"] if is_pro() else []) \
            + (["impacts"] if is_pro() and ((c.get("mesh", {}) or {}).get("inundation") or (wd / "impactos").exists()) else []) + ["report"]   # validar e impactos: Pro
        _pro_tabs = []
        if is_pro():                                          # pestañas de SCHISMlab Pro (meteotsunami...)
            from ..edition import pro as _pro
            _pro_tabs = _pro("gui.results").extra_tabs(c, wd, t)
        with ui.tabs().classes("w-full").props("dense no-caps mobile-arrows") as rtabs:
            rtab = {k: ui.tab(t["tab_" + k]) for k in tab_keys}
            for _k, _lab, _ in _pro_tabs:
                rtab[_k] = ui.tab(_lab)
        rpanels = ui.tab_panels(rtabs, value=rtab.get(tab_key, rtab["maps"])).classes("w-full")
        for _k, _lab, _draw in _pro_tabs:
            with rpanels, ui.tab_panel(rtab[_k]):
                _draw(ds, c, wd, t, S().get("lang", "es"), dark=bool(S().get("dark")))
        with rpanels, ui.tab_panel(rtab["maps"]):
            from .explorer import explorer_tab
            lang_ = S().get("lang", "es")
            est = explorer_tab(ds, c, wd, t, lang_, vgrid_of(c, wd, ds), dark=bool(S().get("dark")))
        class _State(dict):                                   # vista del estado del explorador para las demás pestañas
            def __getitem__(self, k):
                if k == "node":
                    return est.points[-1]["node"] if est.points else nearest_node(ds, float(ds.x.mean()), float(ds.y.mean()))
                return getattr(est, k)
        state = _State()
        with rpanels, ui.tab_panel(rtab["spectrum"]):
            from .explorer import spectrum_tab
            spectrum_tab(ds, c, wd, t, lang_, est)
        with rpanels, ui.tab_panel(rtab["report"]):
            async def make_report():
                from ..analysis.report import build_report
                cp, lang = case_path(), S().get("lang", "es")
                p = await run.io_bound(lambda: build_report(cp, lang=lang))
                ui.notify(t["report_done"], type="positive"); ui.download(p)
            ui.button(t["report"], icon="description", on_click=make_report).props("color=primary outline")
        with rpanels, ui.tab_panel(rtab["compare"]):
            from .figures import difference_figure, series_compare_figure, themed
            others = [ci for ci in gallery() if ci.path != case_path() and ci.status().get("run")]
            _copts = {}
            if is_pro() and cfg().get("runs"):                 # proyecto: las demás simulaciones y el caso base
                from ..edition import pro as _pro
                for _n in [m.name for m in _pro("runs.members").expand(cfg())]:
                    _d = workdir() / "runs" / _n
                    if _d != wd_case and (_d / "outputs").is_dir() and any((_d / "outputs").glob("out2d_*.nc")):
                        _copts[f"member:{_n}"] = f"{_n} · {t['tab_runs'].lower()}"
                if wd_case != workdir() and (workdir() / "outputs").is_dir() and any((workdir() / "outputs").glob("out2d_*.nc")):
                    _copts["member:"] = t["base_case"]
            _copts.update({str(ci.path): ci.name for ci in others})
            ui.label(t["compare_hint"]).classes("text-caption text-grey-7")
            if _copts:
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    osel = ui.select(_copts, value=next(iter(_copts)), label=t["case"], with_input=True).classes("sl-w-md")
                    ccol = ui.column().classes("w-full")
                def _odir(v):
                    from ..case import Case
                    if v.startswith("member:"):
                        return workdir() / "runs" / v[7:] if v[7:] else workdir()
                    return Case(Path(v)).workdir
                def _oname(v):
                    return (v[7:] or t["base_case"]) if v.startswith("member:") else Path(v).stem
                async def do_compare():
                    ccol.clear()
                    try:
                        ds2 = await run.io_bound(lambda: get_ds(_odir(osel.value)))
                        disjoint = (float(ds2.x.min()) > float(ds.x.max()) or float(ds2.x.max()) < float(ds.x.min())
                                    or float(ds2.y.min()) > float(ds.y.max()) or float(ds2.y.max()) < float(ds.y.min()))
                        figs = (difference_figure(ds, ds2, state["var"], state["it"], state["layer"], _oname(osel.value)),
                                series_compare_figure(ds, ds2, state["var"], state["node"], state["layer"], active_member() or case_path().stem, _oname(osel.value)))
                    except Exception as ex:   # noqa: BLE001  (variable no guardada en el otro caso, etc.)
                        ui.notify(f"{t['failed']}: {ex}", type="negative"); return
                    with ccol:
                        if disjoint:
                            ui.notify(t["domains_disjoint"], type="warning", timeout=8000)
                            ui.label(t["domains_disjoint"]).classes("text-orange-9 text-body2")
                        ui.plotly(themed(figs[0], bool(S().get("dark")))).classes("w-full").style("height:560px")
                        ui.plotly(themed(figs[1], bool(S().get("dark")))).classes("w-full").style("height:320px")
                ui.button(t["compare"], icon="compare_arrows", on_click=do_compare).props("color=secondary").mark("compare_btn")
            else:
                ui.label(t["no_other_runs"]).classes("text-grey-7")
        with rpanels, ui.tab_panel(rtab["particles"]):
            from .particles_tab import particles_tab
            particles_tab(ds, c, wd, t, S().get("lang", "es"), est, dark=bool(S().get("dark")))
# ----------------------------------------------------------------------------- validar

# ----------------------------------------------------------------------------- impactos de la inundacion
        if "validate" in rtab:
          with rpanels, ui.tab_panel(rtab["validate"]):
            from ..edition import pro as _pro
            _pro_data_observations = _pro("data.observations")
            IOC_STATIONS = _pro_data_observations.IOC_STATIONS
            fetch_ioc = _pro_data_observations.fetch_ioc
            detide_mean = _pro_data_observations.detide_mean
            compare = _pro_data_observations.compare
            from ..analysis import nearest_node
            from .figures import comparison_figure, themed
            import pandas as pd
            _dark = bool(S().get("dark"))
            coords = {"palma": (2.636, 39.556), "ibiza": (1.447, 38.912), "mahon": (4.264, 39.890), "valencia": (-0.33, 39.46), "barcelona": (2.17, 41.35), "tarragona": (1.22, 41.08), "alicante": (-0.48, 38.34), "sagunto": (-0.21, 39.63), "gandia": (-0.15, 38.99)}
            _x0, _x1, _y0, _y1 = float(ds.x.min()), float(ds.x.max()), float(ds.y.min()), float(ds.y.max())
            inside = [k for k in IOC_STATIONS if k in coords and _x0 <= coords[k][0] <= _x1 and _y0 <= coords[k][1] <= _y1]   # mareógrafos dentro del dominio
            gauges = inside or list(IOC_STATIONS)
            g0 = gauges[0]
            if not inside:
                ui.label(t["no_gauge_in_domain"]).classes("text-caption text-orange-9")
            with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                st = ui.select(gauges, value=g0, label=t["gauge"]).classes("sl-w-md")
                lon = ui.number("lon", value=coords.get(g0, (2.636, 39.556))[0]); lat = ui.number("lat", value=coords.get(g0, (2.636, 39.556))[1])
                detide = ui.switch(t["detide"], value=False)
                st.on_value_change(lambda e: (lon.set_value(coords.get(e.value, (lon.value, lat.value))[0]), lat.set_value(coords.get(e.value, (lon.value, lat.value))[1])))
            out = ui.column().classes("w-full")
            async def go():
                out.clear()
                n = nearest_node(ds, float(lon.value), float(lat.value))
                m = pd.Series(ds.elevation.isel(node=n).values, index=pd.DatetimeIndex(ds.time.values))
                def fetch():
                    o = fetch_ioc(st.value, str(m.index[0].date()), str((m.index[-1] + pd.Timedelta(days=1)).date()))
                    o = detide_mean(o) if detide.value else o - o.mean()
                    return o[(o.index >= m.index[0]) & (o.index <= m.index[-1])]
                try:
                    o = await run.io_bound(fetch)
                except Exception as ex:   # noqa: BLE001
                    ui.notify(str(ex), type="negative"); return
                stats = compare(m, o)
                with out:
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        for lab, val in ((t["rmse"], f"{stats['rmse_m'] * 100:.1f} cm"), (t["corr"], f"{stats['corr']:.2f}"), ("σ " + t["obs"], f"{stats['std_obs_m'] * 100:.1f} cm"), ("σ " + t["model_s"], f"{stats['std_model_m'] * 100:.1f} cm")):
                            with ui.card().classes("q-pa-sm").style("min-width:150px"):
                                ui.label(lab).classes("text-caption text-grey-7"); ui.label(val).classes("text-subtitle1 text-weight-bold")
                    ui.plotly(themed(comparison_figure(m.index, m.values, o.index, o.values, st.value), _dark)).classes("w-full").style("height:420px")
            ui.button(t["compare"], icon="compare_arrows", on_click=go).props("color=accent")
            if "temperature" in ds:
                from ..edition import pro as _pro
                _pro_data_validation3d = _pro("data.validation3d")
                fetch_sst = _pro_data_validation3d.fetch_sst
                fetch_argo = _pro_data_validation3d.fetch_argo
                compare_sst = _pro_data_validation3d.compare_sst
                compare_argo = _pro_data_validation3d.compare_argo
                from .figures import sst_compare_figure, argo_figure
                lang = S().get("lang", "es")
                box_lon = (float(ds.x.min()), float(ds.x.max())); box_lat = (float(ds.y.min()), float(ds.y.max()))
                d0 = str(ds.time.values[0])[:10]; d1 = str(ds.time.values[-1])[:10]
                with ui.card().classes("q-pa-md w-full q-mt-lg"):
                    ui.label(t["sst_sat"]).classes("text-subtitle1 text-weight-bold"); ui.label(t["sst_hint"]).classes("text-caption text-grey-7")
                    with ui.row().classes("items-center q-gutter-sm"):
                        sday = ui.input(t["time"], value=d1).props("type=date dense")
                        sprod = ui.select({"med": t["sst_med"], "med_nrt": t["sst_med_nrt"], "global": t["sst_global"]}, value="med").props("dense").classes("sl-w-md")
                    scol = ui.column().classes("w-full")
                    async def do_sst():
                        scol.clear()
                        try:
                            sst = await run.io_bound(lambda: fetch_sst(box_lon, box_lat, d0, d1, product=sprod.value))
                            res = compare_sst(ds, sst, f"{sday.value}T12:00")
                        except Exception as ex:   # noqa: BLE001
                            ui.notify(f"{t['failed']}: {ex}", type="negative"); return
                        with scol:
                            ui.plotly(themed(sst_compare_figure(ds, res, lang), _dark)).classes("w-full").style("height:440px")
                    ui.button(t["compare"], icon="satellite_alt", on_click=do_sst).props("color=accent")
                with ui.card().classes("q-pa-md w-full q-mt-md"):
                    ui.label(t["argo"]).classes("text-subtitle1 text-weight-bold"); ui.label(t["argo_hint"]).classes("text-caption text-grey-7")
                    acol = ui.column().classes("w-full")
                    async def do_argo():
                        acol.clear()
                        try:
                            a = await run.io_bound(lambda: fetch_argo(box_lon, box_lat, d0, d1))
                            profiles = compare_argo(ds, vgrid_of(c, wd, ds), a)
                        except Exception as ex:   # noqa: BLE001
                            ui.notify(f"{t['failed']}: {ex}", type="negative"); return
                        with acol:
                            if not profiles:
                                ui.label(t["no_argo"]).classes("text-grey-7"); return
                            with ui.row().classes("q-gutter-sm"):
                                for p in profiles:
                                    with ui.card().classes("q-pa-sm"):
                                        ui.label(f"{p['platform']} · {str(p['time'])[:16]} · {p['lon']:.2f}E {p['lat']:.2f}N").classes("text-caption")
                                        ui.label(f"RMSE T {p.get('rmse_temp', float('nan')):.2f} °C · S {p.get('rmse_psal', float('nan')):.3f}").classes("text-subtitle2")
                            ui.plotly(themed(argo_figure(profiles, lang), _dark)).classes("w-full").style("height:540px")
                    ui.button(t["compare"], icon="water", on_click=do_argo).props("color=accent")


        if "impacts" in rtab:
          with rpanels, ui.tab_panel(rtab["impacts"]):
            cp = case_path(); lang = S().get("lang", "es")
            ui.label(t["impacts_hint"]).classes("text-body2 text-grey-8")
            ic = c.get("impacts", {}) or {}
            ds_ = ds
            if "sigWaveHeight" in ds_:
                from ..edition import pro as _pro
                _pro_analysis_runup = _pro("analysis.runup")
                swash_exe = _pro_analysis_runup.swash_exe
                xbeach_exe = _pro_analysis_runup.xbeach_exe
                rcf = c.get("runup", {}) or {}
                with ui.card().classes("q-pa-md w-full"):
                    ui.label(t["runup"]).classes("text-subtitle1 text-weight-bold"); ui.label(t["runup_hint"]).classes("text-caption text-grey-7")
                    methods = {"stockdon": "Stockdon (2006)", "swash": "SWASH 1D" + ("" if swash_exe() else " ✗"), "eurotop": "EurOtop (rebase / overtopping)"}
                    if xbeach_exe():
                        methods["xbeach"] = "XBeach-NH 1D"
                    with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                        rmeth = ui.select(methods, value=safe_select(methods, rcf.get("method", "stockdon"), "stockdon", label=t["runup_method"]), label=t["runup_method"]).props("dense").classes("sl-w-md")
                        rsp = ui.number(t["runup_spacing"], value=float(rcf.get("spacing_m", 250)), min=50, step=50).props("dense").classes("sl-w-md")
                        rdur = ui.number(t["runup_dur"], value=float((rcf.get("swash") or {}).get("duration_s", 1200)), min=120, step=60).props("dense").classes("sl-w-md")
                        st_ = rcf.get("structure") or {}
                        rcrest = ui.number(t["crest"], value=float(st_.get("crest_m", 3.0)), step=0.5).props("dense").classes("sl-w-sm")
                        rslope = ui.number(t["slope"], value=float(st_.get("slope", 0.5)), step=0.1).props("dense").classes("sl-w-sm")
                        for w_ in (rcrest, rslope):
                            w_.bind_visibility_from(rmeth, "value", backward=lambda v: v == "eurotop")
                    if not swash_exe():
                        ui.label(t["runup_na"]).classes("text-caption text-orange-8")
                    rlog = ui.log(max_lines=200).classes("w-full h-24")

                    @ui.refreshable
                    def show_runup():
                        rj = wd / "impactos" / "runup.json"
                        if not rj.exists():
                            return
                        rs = json.loads(rj.read_text()); sm = rs.get("summary", {})
                        with ui.row().classes("q-gutter-lg"):
                            for lab, val in ((t["runup_method"], str(sm.get("method"))), (t["runup_r2"], f"{sm.get('r2_median', float('nan')):.2f} / {sm.get('r2_max', float('nan')):.2f} m"),
                                             (t["runup_level"], f"{sm.get('level_max', float('nan')):.2f} m"), (t["runup_n"], f"{sm.get('n_ok')}/{sm.get('n_transects')}")):
                                with ui.card().classes("q-pa-sm").style("min-width:160px"):
                                    ui.label(lab).classes("text-caption text-grey-7"); ui.label(val).classes("text-subtitle1 text-weight-bold")
                        from .figures import runup_figure, themed as _themed
                        ui.plotly(_themed(runup_figure(rs, lang), bool(S().get("dark")))).classes("w-full").style("height:420px")
                    show_runup()

                    async def do_runup():
                        c2 = cfg(); c2["runup"] = {**(c2.get("runup") or {}), "method": rmeth.value, "spacing_m": float(rsp.value),
                                                   "swash": {**((c2.get("runup") or {}).get("swash") or {}), "duration_s": float(rdur.value)}}
                        if rmeth.value == "eurotop":
                            c2["runup"]["structure"] = {"crest_m": float(rcrest.value), "slope": float(rslope.value)}
                        save(c2)
                        from ..edition import pro as _pro
                        _pro_analysis_runup = _pro("analysis.runup")
                        compute_runup = _pro_analysis_runup.compute_runup
                        await run_job(lambda: compute_runup(cp, cfg=c2), rlog, on_done=lambda r: (show_runup.refresh(), ui.notify(t["runup_done"], type="positive")))
                    ui.button(t["runup_run"], icon="waves", on_click=do_runup).props("color=secondary")
            with ui.card().classes("q-pa-md w-full"):
                with ui.row().classes("row wrap q-col-gutter-sm items-center"):
                    res = ui.number(t["impacts_res"], value=float(ic.get("resolution_m", 30)), min=5, step=5).props("dense").classes("sl-w-sm")
                    thr = ui.number(t["impacts_thr"], value=float(ic.get("threshold_m", 0.05)), min=0, step=0.05).props("dense").classes("sl-w-sm")
                    bld = ui.switch(t["impacts_bld"], value=str(ic.get("buildings", "catastro")) == "catastro")
                    pf = ui.number(t["impacts_pf"], value=float(ic.get("price_factor", 1.0)), min=0.1, step=0.1).props("dense").classes("sl-w-md")
                    bf = ui.number(t["impacts_bf"], value=float(ic.get("built_fraction", 0.3)), min=0, max=1, step=0.1).props("dense").classes("sl-w-md")
                log = ui.log(max_lines=200).classes("w-full h-32")
                out = ui.column().classes("w-full")

                @ui.refreshable
                def show():
                    rj = wd / "impactos" / "resumen.json"
                    if not rj.exists():
                        return
                    s = json.loads(rj.read_text())
                    with ui.row().classes("q-gutter-lg q-mb-md"):
                        for lab, val in ((t["flooded_area"], f"{s['flooded_area_ha']:.1f} ha"),
                                         (t["pop_exposed"], f"{s['population_exposed']:.0f}" if s.get("population_exposed") == s.get("population_exposed") and s.get("population_exposed") is not None else "?"),
                                         (t["bld_affected"], f"{s['buildings_affected']} ({s['dwellings_affected']} {t['dwellings']})"),
                                         (t["damage_total"], f"{s['damage_total_eur'] / 1e6:.2f} M€")):
                            with ui.card().classes("q-pa-md").style("min-width:180px"):
                                ui.label(lab).classes("text-caption text-grey-7"); ui.label(val).classes("text-h5 text-primary")
                    png = wd / "impactos" / "mapa_impactos.png"
                    if png.exists():
                        ui.image(str(png)).classes("w-full").style("max-width:900px")
                    for key, title in (("landuse_rows", t["by_landuse"]), ("building_rows", t["by_building"]), ("damage_rows", t["damage_landuse"])):
                        rows = s.get(key) or []
                        if rows:
                            ui.label(title).classes("text-subtitle1 text-weight-bold q-mt-md")
                            fmt = lambda v: (f"{v:,.0f}" if isinstance(v, float) and abs(v) >= 100 else (f"{v:.2f}" if isinstance(v, float) else v))
                            cols = [{"name": k, "label": k, "field": k, "align": "left" if isinstance(rows[0][k], str) else "right"} for k in rows[0]]
                            ui.table(columns=cols, rows=[{k: fmt(v) for k, v in r.items()} for r in rows]).props("dense flat bordered").classes("w-full")
                    csvs = list((wd / "impactos").glob("*.csv"))
                    if csvs:
                        with ui.row():
                            for f in csvs:
                                ui.button(f.name, icon="download", on_click=lambda f=f: ui.download(f)).props("flat dense")
                show()

                async def compute():
                    c2 = cfg(); c2["impacts"] = {**c2.get("impacts", {}), "resolution_m": float(res.value), "threshold_m": float(thr.value),
                                                "buildings": "catastro" if bld.value else "none", "price_factor": float(pf.value), "built_fraction": float(bf.value)}
                    save(c2)
                    from ..edition import pro as _pro
                    _pro_analysis_impacts = _pro("analysis.impacts")
                    compute_impacts = _pro_analysis_impacts.compute_impacts
                    await run_job(lambda: compute_impacts(cp, cfg=c2, lang=lang), log, on_done=lambda r: (show.refresh(), ui.notify(t["impacts_done"], type="positive")))
                ui.button(t["impacts_run"], icon="flood", on_click=compute).props("color=primary")



@ui.page("/results")
def page_results():
    try:
        tab = ui.context.client.request.query_params.get("tab") or "maps"
    except Exception:   # noqa: BLE001
        tab = "maps"
    _results_content(tab)


@ui.page("/analyse")
def page_analyse():
    _results_content("maps")


@ui.page("/runs")
def page_runs():
    t = T()
    with layout("runs"):
        if need_case():
            return
        ui.label(t["step_runs"]).classes("text-h4 text-primary")
        if not is_pro():
            pro_notice(t); return
        from ..edition import pro as _pro
        _pro("gui.runs").runs_page(t, case_path(), dark=bool(S().get("dark")))


@ui.page("/validate")
def page_validate():
    _results_content("validate")


@ui.page("/impacts")
def page_impacts():
    _results_content("impacts")


def main(port: int = 8765, show: bool = True, host: str = "127.0.0.1"):
    """Arranca la interfaz. Por seguridad escucha solo en localhost (`host="0.0.0.0"` para exponerla a la red a propósito)."""
    from .docs_site import mount_docs
    mount_docs(app, REPO / "site")                              # ayuda local (pixi run docs), con el index.html de cada carpeta
    ui.run(title=edition_name(), host=host, port=port, show=show, reload=False, storage_secret="schismlab", favicon=str(BRAND_FAVICON), language="es")


if __name__ in {"__main__", "__mp_main__"}:
    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    _host = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--host=")), "127.0.0.1")
    main(port=int(_args[0]) if _args else 8765, show="--no-browser" not in sys.argv, host=_host)
