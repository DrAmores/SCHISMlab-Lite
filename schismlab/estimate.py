"""Estimación del tiempo de cálculo de una simulación (rango), calibrada con ejecuciones reales.

Modelo (ajustado el 16/10/2026 con 17 simulaciones de SCHISMlab: 14 en un Ryzen 9 3950X de 16 núcleos y 3 en el
clúster tramuntana/ada):

    trabajo = pasos · nodos · (A + B · (niveles − 1))  +  [oleaje] (pasos / nstep_wwm) · nodos · MSC · MDC · C
    tiempo  = trabajo / núcleos_efectivos + T0

núcleos_efectivos = físicos usados + 0.25 por cada hilo extra (hyperthreading). En el clúster cada núcleo rinde
CLUSTER veces uno de la máquina de referencia. La dispersión de las ejecuciones reales respecto al modelo es de un
factor 1.5 (p10–p90: 0.6–1.6), así que se da un rango y no un número.

Cada ordenador se recalibra solo: `record_run` guarda en ~/.schismlab/perf.jsonl el tiempo real de cada simulación
local de más de un minuto, y `machine_factor` usa la mediana del cociente real/modelo de las últimas ejecuciones.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
import numpy as np

A, B, C, T0 = 2.84e-05, 1.07e-05, 2.21e-06, 26.2
CLUSTER = 1.43
LOW, HIGH = 0.6, 1.6
HOME = Path(os.environ.get("SCHISMLAB_HOME", Path.home() / ".schismlab"))
PERF = HOME / "perf.jsonl"


def physical_cores() -> int:
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return int(n)
    except Exception:   # noqa: BLE001
        pass
    return max(1, (os.cpu_count() or 2) // 2)


def default_local_cores() -> int:
    """Procesos de cálculo por defecto en local: los núcleos físicos menos dos (para el sistema y los scribes)."""
    return max(1, physical_cores() - 2)


def effective_cores(nprocs: int, cluster: bool = False) -> float:
    if cluster:
        return float(nprocs) * CLUSTER
    phys = physical_cores()
    return min(nprocs, phys) + 0.25 * max(0, nprocs - phys)


def work_units(nodes: int, steps: int, nvrt: int = 2, waves: dict | None = None) -> float:
    w = steps * nodes * (A + B * (max(nvrt, 2) - 1))
    if waves:
        w += (steps / max(int(waves.get("nstep", 3)), 1)) * nodes * int(waves.get("msc", 24)) * int(waves.get("mdc", 24)) * C
    return float(w)


def machine_factor(n_last: int = 10) -> tuple[float, int]:
    """(factor real/modelo de este ordenador, número de ejecuciones usadas). 1.0 si aún no hay datos."""
    if not PERF.exists():
        return 1.0, 0
    ratios = []
    for line in PERF.read_text().splitlines()[-n_last:]:
        try:
            r = json.loads(line)
            pred = work_units(r["nodes"], r["steps"], r["nvrt"], r.get("waves")) / effective_cores(r["nprocs"]) + T0
            ratios.append(r["seconds"] / pred)
        except Exception:   # noqa: BLE001
            continue
    return (float(np.median(ratios)), len(ratios)) if ratios else (1.0, 0)


def case_params(cfg: dict) -> dict:
    """Pasos, niveles y oleaje a partir de la configuración del caso (sin leer la malla)."""
    tm = cfg.get("time", {}) or {}
    days = float(tm.get("days", 1)); dt = float(tm.get("dt", 60))
    v = cfg.get("vertical", {}) or {}
    if v.get("type", "2d") == "2d":
        nvrt = 2
    elif v.get("type") == "sz":
        nvrt = int(v.get("nsigma", 20)) + len(v.get("zlevels") or [])
    else:
        nvrt = int(v.get("nvrt", 20))
    wv = cfg.get("waves") or {}
    waves = {"nstep": int(wv.get("nstep", 3)), "msc": int(wv.get("msc", 24)), "mdc": int(wv.get("mdc", 24))} if wv.get("enabled") else None
    return dict(steps=int(round(days * 86400 / dt)), nvrt=nvrt, waves=waves, days=days, dt=dt)


def estimate(cfg: dict, nodes: int, nprocs: int | None = None, cluster: bool = False) -> dict:
    """Rango de tiempo de pared (s) para el caso con `nodes` nodos en `nprocs` procesos (local o clúster)."""
    p = case_params(cfg)
    nprocs = int(nprocs or (128 if cluster else default_local_cores()))
    f, n = (1.0, 0) if cluster else machine_factor()
    t = (work_units(nodes, p["steps"], p["nvrt"], p["waves"]) / effective_cores(nprocs, cluster) + T0) * f
    return dict(seconds=t, low=t * LOW, high=t * HIGH, nprocs=nprocs, calibrated_runs=n, factor=f, **p)


def fmt_duration(s: float, lang: str = "es") -> str:
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    if s < 2 * 86400:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} " + ("días" if lang == "es" else "days")


def fmt_range(e: dict, lang: str = "es") -> str:
    return f"{fmt_duration(e['low'], lang)} – {fmt_duration(e['high'], lang)}"


def record_run(rundir: Path, seconds: float, nprocs: int) -> None:
    """Guarda el tiempo real de una simulación local (>= 60 s) para recalibrar este ordenador."""
    rundir = Path(rundir)
    if seconds < 60:
        return
    try:
        nodes = int((rundir / "hgrid.gr3").open().readlines()[1].split()[1])
        txt = (rundir / "param.nml").read_text()
        g = lambda k, d=None: (float(m.group(1)) if (m := re.search(rf"^\s*{k}\s*=\s*([\d.eE+-]+)", txt, re.M)) else d)
        steps = int(round(g("rnday") * 86400 / g("dt")))
        nvrt = int((rundir / "vgrid.in").read_text().splitlines()[1].split()[0]) if (rundir / "vgrid.in").exists() else 2
        waves = None
        if g("icou_elfe_wwm", 0) and (rundir / "wwminput.nml").exists():
            w = (rundir / "wwminput.nml").read_text()
            gi = lambda k: int(re.search(rf"^\s*{k}\s*=\s*(\d+)", w, re.M | re.I).group(1))
            waves = {"nstep": int(g("nstep_wwm", 3)), "msc": gi("MSC"), "mdc": gi("MDC")}
        PERF.parent.mkdir(parents=True, exist_ok=True)
        with PERF.open("a") as f:
            f.write(json.dumps(dict(when=time.strftime("%Y-%m-%d %H:%M"), case=rundir.name, nodes=nodes, steps=steps, nvrt=nvrt,
                                    waves=waves, nprocs=int(nprocs), seconds=round(seconds, 1))) + "\n")
    except Exception:   # noqa: BLE001  (la calibración nunca debe romper una simulación)
        pass
