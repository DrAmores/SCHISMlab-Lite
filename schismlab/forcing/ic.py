"""Condiciones iniciales: elev.ic, temp.ic/salt.ic (gr3, flag_ic=1) y ts.ic (perfil, flag_ic=2)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..io.gr3 import Mesh, write_gr3


def write_elev_ic(path, mesh: Mesh, eta) -> None:
    write_gr3(path, mesh, values=np.broadcast_to(np.asarray(eta, float), (mesh.nnodes,)), boundaries=False,
              comment="elev.ic")


def write_tracer_ic_gr3(path, mesh: Mesh, values) -> None:
    """temp.ic / salt.ic en formato gr3 (variable en horizontal, uniforme en vertical)."""
    write_gr3(path, mesh, values=np.broadcast_to(np.asarray(values, float), (mesh.nnodes,)), boundaries=False,
              comment=Path(path).name)


def write_ts_ic(path, z: np.ndarray, temp: np.ndarray, salt: np.ndarray) -> None:
    """ts.ic: perfil vertical (uniforme en horizontal). z negativa hacia abajo, de abajo a arriba."""
    order = np.argsort(z)
    lines = [f"{len(z)} !niveles"] + [f"{k + 1} {z[i]:.3f} {temp[i]:.4f} {salt[i]:.4f}" for k, i in enumerate(order)]
    Path(path).write_text("\n".join(lines) + "\n")
