"""Esfuerzo del viento <-> viento a 10 m, con las mismas fórmulas que SCHISM (schism_step.F90).

SCHISM calcula el esfuerzo cinemático tau/rho_w = Cd * (rho_a/rho_w) * |W| * W, con rho_a/rho_w = 0.001293 fijo en el
código, y la salida `windStress` es ese valor (m²/s²): el esfuerzo en Pa es windStress * 1000.

Fórmulas (param.nml, iwind_form):
    -1  Pond & Pichard: Cd = 1e-3 (0.61 + 0.063 |W|), acotado entre Cd(6 m/s) y Cd(50 m/s) (límites fijos en el código).
     1  Hwang (2018):   Cd = 1e-4 (-0.016 |W|² + 0.967 |W| + 8.058) hasta 35 m/s; 2.23e-3 * 35/|W| por encima.
Las dos son monótonas en |W|, así que el esfuerzo se invierte de forma exacta (tabla fina + interpolación).
Las fórmulas 0 (del intercambio de calor) y -2/-3 (oleaje) no dependen solo del viento y no se pueden invertir.
"""
from __future__ import annotations
import numpy as np

RHO_AIR_OVER_WATER = 0.001293     # constante de SCHISM (rho_a / rho_w)
RHO_WATER = 1000.0                # rho_w implícita en esa constante (rho_a = 1.293 kg/m³)
INVERTIBLE = (-1, 1)
_WMAX = 200.0


def drag_coefficient(wmag, formula: int = 1) -> np.ndarray:
    """Cd(|W|) de SCHISM para iwind_form = -1 (Pond & Pichard) o 1 (Hwang 2018)."""
    w = np.asarray(wmag, float)
    if formula == -1:
        cd = 1e-3 * (0.61 + 0.063 * w)
        return np.clip(cd, 1e-3 * (0.61 + 0.063 * 6.0), 1e-3 * (0.61 + 0.063 * 50.0))
    if formula == 1:
        cd = np.where(w <= 35.0, 1e-4 * (-0.016 * w * w + 0.967 * w + 8.058), 2.23e-3 * 35.0 / np.maximum(w, 1e-12))
        return np.maximum(cd, 4e-4)
    raise ValueError(f"fórmula de arrastre {formula} no invertible (solo -1 Pond & Pichard o 1 Hwang)")


def kinematic_stress(wmag, formula: int = 1) -> np.ndarray:
    """|tau|/rho_w (m²/s²) en función del módulo del viento, tal como lo calcula SCHISM."""
    w = np.asarray(wmag, float)
    return drag_coefficient(w, formula) * RHO_AIR_OVER_WATER * w * w


def stress_from_wind(u, v, formula: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """(tau_x, tau_y) en Pa a partir del viento a 10 m (m/s)."""
    u, v = np.asarray(u, float), np.asarray(v, float)
    w = np.hypot(u, v)
    k = kinematic_stress(w, formula) * RHO_WATER
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(w > 0, k / np.where(w > 0, w, 1.0), 0.0)
    return f * u, f * v


def wind_from_stress(tau_x, tau_y, formula: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Viento a 10 m (u, v) que hace que SCHISM aplique exactamente el esfuerzo (tau_x, tau_y) en Pa."""
    tx, ty = np.asarray(tau_x, float), np.asarray(tau_y, float)
    tmag = np.hypot(tx, ty)
    wtab = np.linspace(0.0, _WMAX, 400001)                  # paso 0.5 mm/s: error de interpolación < 1e-6 m/s
    ktab = kinematic_stress(wtab, formula) * RHO_WATER       # Pa, monótona creciente
    if np.any(tmag > ktab[-1]):
        raise ValueError(f"esfuerzo del viento demasiado grande (máximo {ktab[-1]:.1f} Pa con esta fórmula)")
    wmag = np.interp(tmag, ktab, wtab)
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(tmag > 0, wmag / np.where(tmag > 0, tmag, 1.0), 0.0)
    return f * tx, f * ty
