"""Ayuda local: la documentación generada con MkDocs (carpeta site/) servida en /docs.

MkDocs enlaza las páginas como carpetas (/docs/instalacion/), así que el servidor tiene que devolver el index.html de
cada carpeta; los ficheros estáticos de NiceGUI no lo hacen y daban 404 en todo lo que no fuera la portada.
"""
from __future__ import annotations
from pathlib import Path

from starlette.staticfiles import StaticFiles


def docs_files(site: Path) -> StaticFiles:
    """Aplicación ASGI que sirve `site` con el index.html de cada carpeta (html=True)."""
    return StaticFiles(directory=str(site), html=True)


def mount_docs(app, site: Path, path: str = "/docs") -> bool:
    """Monta la ayuda en `path` si está generada; devuelve si se ha montado."""
    if not (Path(site) / "index.html").exists():
        return False
    app.mount(path, docs_files(Path(site)), name="docs")
    return True
