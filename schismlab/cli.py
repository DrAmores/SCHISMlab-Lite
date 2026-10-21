"""Linea de ordenes de SCHISMlab:  schismlab mesh caso.yaml"""
from __future__ import annotations
import logging
from pathlib import Path
import typer
from rich.logging import RichHandler
from rich import print as rprint

app = typer.Typer(help="SCHISMlab: simular con SCHISM de cero (SCHISMlab Lite o Pro).", no_args_is_help=True)


def _setup(verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s",
                        handlers=[RichHandler(show_path=False, show_time=False)])
    for noisy in ("ocsmesh", "rasterio", "fiona", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def mesh(case: Path = typer.Argument(..., help="fichero YAML del caso"),
         outdir: Path = typer.Option(None, help="directorio de salida (por defecto <carpeta del yaml>/<nombre>)"),
         verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Genera hgrid.gr3 (y hgrid.ll), mesh.png y mesh_quality.json."""
    _setup(verbose)
    from .case import Case
    from .mesh.build import build_mesh
    c = Case(case)
    m = build_mesh(c, outdir)
    rprint(f"[green]OK[/] malla de '{c.name}': {m.nnodes} nodos, {m.nelements} elementos -> {outdir or c.workdir}")


@app.command()
def setup(case: Path = typer.Argument(..., help="fichero YAML del caso"),
          outdir: Path = typer.Option(None, help="directorio de ejecucion (por defecto <carpeta del yaml>/<nombre>)"),
          verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Prepara el directorio de ejecucion completo: malla, vgrid, CI, forzamientos, bctides y param.nml."""
    _setup(verbose)
    from .case import Case
    from .setup import setup_case
    d = setup_case(Case(case), outdir)
    rprint(f"[green]OK[/] caso preparado en {d}. Ejecuta:  schismlab run {case}")


@app.command()
def run(case: Path = typer.Argument(..., help="fichero YAML del caso (o directorio de ejecucion)"),
        cores: int = typer.Option(None, help="procesos de calculo (por defecto: todos menos los scribes)"),
        variant: str = typer.Option("hydro", help="ejecutable: hydro | wwm"),
        verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Ejecuta SCHISM en local con mpirun sobre un caso ya preparado con 'setup'."""
    _setup(verbose)
    from .case import Case
    from .run import run_local
    d = case if case.is_dir() else Case(case).workdir
    rc = run_local(d, variant=variant, ncores=cores)
    if rc == 0:
        _post_run(d, case)
    raise typer.Exit(rc)


def _post_run(d: Path, case: Path):
    """Tareas tras la simulacion (recorte al subdominio): con el YAML del caso o, si se dio un directorio, su caso.yaml."""
    from .case import Case
    from .run import post_run
    try:
        yml = case if case.is_file() else (d / "caso.yaml" if (d / "caso.yaml").exists() else None)
        if yml is not None:
            post_run(d, Case(yml).cfg)
    except Exception as ex:   # noqa: BLE001
        logging.getLogger(__name__).warning("post_run: %s", ex)


@app.command()
def gui(port: int = typer.Option(8765, help="puerto local"), no_browser: bool = typer.Option(False, "--no-browser"),
        host: str = typer.Option("127.0.0.1", help="direccion en la que escucha; --host 0.0.0.0 expone la interfaz a la red local")):
    """Abre la interfaz grafica paso a paso en el navegador (--host 0.0.0.0 la expone a la red local)."""
    from .gui.app import main
    show = not no_browser
    if show and _is_wsl():                                   # en WSL no hay navegador de Linux: abrir el de Windows
        import subprocess, threading, time
        def _open():
            time.sleep(2.5)
            for cmd in (["wslview", f"http://localhost:{port}"], ["cmd.exe", "/c", "start", f"http://localhost:{port}"]):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=15); return
                except (OSError, subprocess.SubprocessError):
                    continue
        threading.Thread(target=_open, daemon=True).start(); show = False
    main(port=port, show=show, host=host)


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


@app.command()
def report(case: Path = typer.Argument(..., help="fichero YAML del caso"), lang: str = typer.Option("es", help="es | en"),
           out: Path = typer.Option(None, help="fichero HTML de salida")):
    """Informe HTML autocontenido de la simulacion (configuracion, malla, parametros, figuras)."""
    _setup(False)
    from .analysis.report import build_report
    rprint(f"[green]informe:[/] {build_report(case, out, lang=lang)}")


from .edition import is_pro as _is_pro   # noqa: E402
if _is_pro():                            # órdenes de SCHISMlab Pro (credenciales, clúster, impactos, run-up, vídeo, datos)
    from .edition import pro as _pro
    _pro("cli").register(app)
