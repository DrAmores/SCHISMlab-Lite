"""Malla vertical de SCHISM: 2D, SZ (sigma + z) y calculo de las cotas z de cada nivel."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np


@dataclass
class VGrid:
    """Malla vertical SZ. Con nvrt=2 y h_s enorme es el caso 2D.

    nvrt    : numero total de niveles
    kz      : numero de niveles z (>=1); el ultimo nivel z esta en -h_s
    h_s     : profundidad de transicion S -> Z
    h_c, theta_b, theta_f : parametros de la transformacion sigma (Song & Haidvogel)
    zlevels : cotas de los niveles z (negativas, crecientes), longitud kz, la ultima = -h_s
    """
    nvrt: int = 2
    kz: int = 1
    h_s: float = 1e6
    h_c: float = 40.0
    theta_b: float = 1.0
    theta_f: float = 1e-4
    zlevels: list = field(default_factory=lambda: [-1e6])

    @classmethod
    def two_d(cls):
        return cls()

    @classmethod
    def sigma(cls, nvrt: int = 20, h_c: float = 10.0, theta_b: float = 0.0, theta_f: float = 4.0, h_s: float = 1e6):
        """Malla sigma pura (un solo nivel z en -h_s muy profundo)."""
        return cls(nvrt=nvrt, kz=1, h_s=h_s, h_c=h_c, theta_b=theta_b, theta_f=theta_f, zlevels=[-h_s])

    @classmethod
    def sz(cls, nsigma: int, zlevels: list, h_c: float = 10.0, theta_b: float = 0.0, theta_f: float = 4.0):
        """Sigma en los nsigma niveles superiores (hasta -h_s) y niveles z fijos por debajo."""
        z = sorted(float(v) for v in zlevels)
        return cls(nvrt=nsigma + len(z) - 1, kz=len(z), h_s=-z[-1], h_c=h_c, theta_b=theta_b,
                   theta_f=theta_f, zlevels=z)

    @property
    def sigma_levels(self) -> np.ndarray:
        n = self.nvrt - self.kz + 1
        return np.linspace(-1.0, 0.0, n)

    def write(self, path: str | Path) -> None:
        lines = ["2 !ivcor (2: SZ)", f"{self.nvrt} {self.kz} {self.h_s:g} !nvrt, kz, h_s", "Z levels"]
        lines += [f"{k + 1} {z:g}" for k, z in enumerate(self.zlevels)]
        lines += ["S levels", f"{self.h_c:g} {self.theta_b:g} {self.theta_f:g} !h_c, theta_b, theta_f"]
        lines += [f"{self.kz + k} {s:.6f}" for k, s in enumerate(self.sigma_levels)]
        Path(path).write_text("\n".join(lines) + "\n")

    def zcor(self, depth: np.ndarray, eta: np.ndarray | None = None) -> np.ndarray:
        """Cotas z (nnodes, nvrt) de cada nivel; nivel 0 = fondo, nivel nvrt-1 = superficie.

        Replica la transformacion de SCHISM (Song & Haidvogel): niveles por debajo del fondo se
        rellenan con la cota del fondo (SCHISM los ignora, kbp).
        """
        h = np.asarray(depth, float); eta = np.zeros_like(h) if eta is None else np.asarray(eta, float)
        sig = self.sigma_levels
        tf, tb, hc = self.theta_f, self.theta_b, self.h_c
        if tf > 1e-3:
            cs = (1 - tb) * np.sinh(tf * sig) / np.sinh(tf) + tb * (np.tanh(tf * (sig + 0.5)) - np.tanh(tf / 2)) / (2 * np.tanh(tf / 2))
        else:
            cs = sig
        hmod = np.minimum(h, self.h_s)
        z = np.empty((h.size, self.nvrt))
        # parte sigma (niveles kz-1 .. nvrt-1)
        for k, (s, c) in enumerate(zip(sig, cs)):
            zs = np.where(hmod <= hc, (eta + hmod) * s + eta, eta * (1 + s) + hc * s + (hmod - hc) * c)
            z[:, self.kz - 1 + k] = zs
        # parte z (niveles 0 .. kz-2)
        for k in range(self.kz - 1):
            z[:, k] = np.maximum(self.zlevels[k], -h)
        return z


def write_vgrid(path, vg: VGrid) -> None:
    vg.write(path)
