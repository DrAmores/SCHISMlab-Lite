"""Ayuda local: se genera con MkDocs como `pixi run docs`, se sirve como en la interfaz (/docs) y se siguen todos los
enlaces internos. Antes, todo lo que no fuera la portada daba 404 (las páginas son carpetas: /docs/instalacion/)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("mkdocs")
from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from schismlab.gui.docs_site import docs_files, mount_docs  # noqa: E402

LINK = re.compile(r'(?:href|src)="([^"]+)"')


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not (ROOT / "mkdocs.yml").exists() or shutil.which("mkdocs") is None:
        pytest.skip("sin mkdocs.yml o sin mkdocs")
    out = tmp_path_factory.mktemp("site")
    r = subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict", "-q", "-d", str(out)], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    return out


def test_todos_los_enlaces_de_la_ayuda_funcionan(site):
    client = TestClient(Starlette(routes=[Mount("/docs", app=docs_files(site))]))
    pending, seen, broken, pages = ["/docs/index.html", "/docs/"], set(), [], 0
    while pending:
        url = pending.pop()
        if url in seen:
            continue
        seen.add(url)
        r = client.get(url)
        if r.status_code != 200:
            broken.append(f"{url} -> {r.status_code}")
            continue
        if "text/html" not in r.headers.get("content-type", ""):
            continue
        pages += 1
        for href in LINK.findall(r.text):
            u = urlsplit(urljoin("http://testserver" + url, href))
            if u.netloc == "testserver" and u.path.startswith("/docs"):
                pending.append(u.path)
    assert not broken, "enlaces rotos en la ayuda:\n" + "\n".join(sorted(broken))
    assert pages > 3 and "/docs/instalacion/" in seen


def test_mathjax_local_sin_internet(site):
    client = TestClient(Starlette(routes=[Mount("/docs", app=docs_files(site))]))
    html = client.get("/docs/index.html").text
    assert "javascripts/mathjax/tex-mml-chtml.js" in html and "cdnjs.cloudflare.com/ajax/libs/mathjax" not in html
    for f in ("tex-mml-chtml.js", "output/chtml/fonts/woff-v2/MathJax_Main-Regular.woff", "input/tex/extensions/color.js"):
        assert client.get(f"/docs/javascripts/mathjax/{f}").status_code == 200, f


def test_mount_docs_solo_si_esta_generada(tmp_path, site):
    app = Starlette()
    assert not mount_docs(app, tmp_path / "no_existe")
    assert mount_docs(app, site) and TestClient(app).get("/docs/instalacion/").status_code == 200


def test_formulas_de_bloque_separadas_del_texto():
    """Un $$…$$ pegado al párrafo se dibuja en línea y deja los «$» a la vista."""
    malas = []
    for f in sorted((ROOT / "docs").rglob("*.md")):
        L = f.read_text(encoding="utf-8").split("\n")
        for i, l in enumerate(L):
            s = l.strip()
            if s.startswith("$$") and s.endswith("$$") and len(s) > 4:
                if (i > 0 and L[i - 1].strip()) or (i + 1 < len(L) and L[i + 1].strip()):
                    malas.append(f"{f.relative_to(ROOT)}:{i + 1}")
    assert not malas, "fórmulas $$ sin línea en blanco alrededor:\n" + "\n".join(malas)
