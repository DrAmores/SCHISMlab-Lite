"""Explorador de carpetas del servidor (la interfaz va en el navegador y no hay diálogo nativo de carpetas): diálogo
con la ruta actual, accesos rápidos, subcarpetas, subir un nivel, crear carpeta y «Elegir». Devuelve la ruta elegida."""
from __future__ import annotations
import os
from pathlib import Path
from nicegui import ui


def _shortcuts(home_schismlab: Path) -> list[tuple[str, Path]]:
    out = [("~", Path.home()), ("~/.schismlab/cases", home_schismlab / "cases")]
    mnt = Path("/mnt")
    if mnt.is_dir():
        out += [(f"/mnt/{d.name}", d) for d in sorted(mnt.iterdir()) if d.is_dir() and len(d.name) == 1]   # discos de Windows (WSL)
    for d in (Path("/data"), Path("/scratch")):
        if d.is_dir():
            out.append((str(d), d))
    return out


def _subdirs(p: Path) -> list[Path]:
    try:
        return sorted((d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")), key=lambda d: d.name.lower())
    except OSError:
        return []


async def pick_folder(start: str | Path | None, t: dict) -> str | None:
    """Abre el diálogo y espera: ruta elegida (str) o None si se cancela."""
    from .state import HOME
    cur = {"p": Path(str(start or Path.home())).expanduser()}
    if not cur["p"].is_dir():
        cur["p"] = Path.home()
    with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width:520px;max-width:90vw"):
        ui.label(t["sim_folder"]).classes("text-subtitle1 text-weight-bold")
        path_in = ui.input(t["folder_path"], value=str(cur["p"])).props("dense outlined").classes("w-full")
        with ui.row().classes("q-gutter-xs wrap"):
            for lab, p in _shortcuts(HOME):
                ui.button(lab, on_click=lambda e, p=p: go(p)).props("flat dense no-caps size=sm")
        with ui.row().classes("items-center q-gutter-xs"):
            ui.button(icon="arrow_upward", on_click=lambda: go(cur["p"].parent)).props("flat dense round").tooltip(t["folder_up"])
            newname = ui.input(t["new_folder"]).props("dense outlined").classes("col")
            ui.button(icon="create_new_folder", on_click=lambda: mkdir()).props("flat dense round").tooltip(t["new_folder"])
        listing = ui.column().classes("w-full q-gutter-none").style("max-height:40vh;overflow:auto")
        info = ui.label().classes("text-caption text-grey-7")
        with ui.row().classes("justify-end w-full"):
            ui.button(t["cancel"], on_click=lambda: dlg.submit(None)).props("flat")
            ui.button(t["choose_folder"], icon="check", on_click=lambda: dlg.submit(str(cur["p"]))).props("color=accent unelevated")

        def render():
            listing.clear()
            subs = _subdirs(cur["p"])
            with listing:
                if not subs:
                    ui.label(t["no_subfolders"]).classes("text-caption text-grey-7 q-pa-sm")
                for d in subs:
                    with ui.row().classes("items-center cursor-pointer q-px-sm q-py-xs hover-row w-full").on("click", lambda e, d=d: go(d)):
                        ui.icon("folder", color="amber-7"); ui.label(d.name)
            writable = os.access(cur["p"], os.W_OK)
            info.set_text("" if writable else t["folder_not_writable"])
            path_in.set_value(str(cur["p"]))

        def go(p: Path):
            p = Path(p).expanduser()
            if p.is_dir():
                cur["p"] = p.resolve(); render()
            else:
                ui.notify(f"{t['folder_missing']}: {p}", type="warning")

        def mkdir():
            name = (newname.value or "").strip().strip("/")
            if not name or "/" in name or name in (".", ".."):
                return
            try:
                (cur["p"] / name).mkdir(exist_ok=True); newname.set_value(""); go(cur["p"] / name)
            except OSError as ex:
                ui.notify(str(ex), type="negative")

        path_in.on("keydown.enter", lambda e: go(Path(path_in.value or "")))
        render()
    dlg.open()
    return await dlg
