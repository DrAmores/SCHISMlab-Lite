"""bctides.in: condiciones de contorno abiertas (constantes, mareas) y potencial de marea."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..io.gr3 import Mesh

# nombre: (especie, amplitud del potencial [m], frecuencia angular [rad/s])
TIDAL_CONSTITUENTS = {
    "M2": (2, 0.242334, 1.405189e-4), "S2": (2, 0.112841, 1.454441e-4), "N2": (2, 0.046398, 1.378797e-4),
    "K2": (2, 0.030704, 1.458423e-4), "K1": (1, 0.141565, 7.292117e-5), "O1": (1, 0.100514, 6.759775e-5),
    "P1": (1, 0.046843, 7.252295e-5), "Q1": (1, 0.019256, 6.495457e-5),
}


def write_bctides(path, mesh: Mesh, boundaries: list[dict], constituents: list[str] | None = None,
                  tidal_potential: bool = False, tip_dp: float = 40.0, comment: str = "SCHISMlab",
                  nodal: dict | None = None) -> None:
    """Escribe bctides.in.

    boundaries : lista (una entrada por contorno abierto, en el orden de hgrid) de dicts con
        elev : 'none' | number (constante) | {'tides': {'M2': (amp, fase_deg) | (amp_array, fase_array)}}
        vel  : 'none' | number (caudal constante, <0 entra) | {'tides': {...}}  (u,v amp/fase) | 'flather' (radiación)
        temp, salt : 'none' | number (valor para entrada, relajacion 1) | 'ic'
    constituents : constituyentes para las fronteras tipo 3 (nodal factor 1, argumento 0 por defecto)
    nodal : {NOMBRE: dict(omega, ff, face)} frecuencia, factor nodal y argumento de equilibrio reales (de schismlab.data.tides)
    """
    nodal = nodal or {}
    def freq(c): return nodal.get(c, {}).get("omega", TIDAL_CONSTITUENTS[c][2])
    def ff(c): return nodal.get(c, {}).get("ff", 1.0)
    def face(c): return nodal.get(c, {}).get("face", 0.0)
    constituents = constituents or []
    L = [comment]
    if tidal_potential and constituents:
        L.append(f"{len(constituents)} {tip_dp:g} !ntip, tip_dp")
        for c in constituents:
            sp, amp, w = TIDAL_CONSTITUENTS[c]
            L += [c, f"{sp} {amp:.6f} {freq(c):.6e} {ff(c):.5f} {face(c):.3f}"]
    else:
        L.append(f"0 {tip_dp:g} !ntip, tip_dp")
    L.append(f"{len(constituents)} !nbfr")
    for c in constituents:
        L += [c, f"{freq(c):.6e} {ff(c):.5f} {face(c):.3f}"]
    L.append(f"{len(mesh.open_boundaries)} !nope")
    for b, nodes in zip(boundaries, mesh.open_boundaries):
        n = len(nodes)
        e, v, t, s = b.get("elev", "none"), b.get("vel", "none"), b.get("temp", "none"), b.get("salt", "none")
        # elev: 'none' | numero | 'th1' (1: elev.th, serie uniforme) | {'tides': ...} (3) | 'th' (4: elev2D.th.nc) | {'tides': ..., 'th': True} (5)
        iet = 0 if e == "none" else 4 if e == "th" else 1 if e == "th1" else (5 if isinstance(e, dict) and e.get("th") else 3) if isinstance(e, dict) else 2
        ifl = 0 if v == "none" else -4 if v == "th" else -1 if v == "flather" else 3 if isinstance(v, dict) else 2
        itt = 0 if t == "none" else 4 if t == "th" else 3 if t == "ic" else 2
        ist = 0 if s == "none" else 4 if s == "th" else 3 if s == "ic" else 2
        L.append(f"{n} {iet} {ifl} {itt} {ist}")
        if iet == 2:
            L.append(f"{float(e):g}")
        elif iet in (3, 5):
            for c in constituents:
                amp, pha = e["tides"].get(c, (0.0, 0.0))
                amp, pha = np.broadcast_to(np.asarray(amp, float), n), np.broadcast_to(np.asarray(pha, float), n)
                L.append(c); L += [f"{a:.5f} {p:.3f}" for a, p in zip(amp, pha)]
        if ifl == 2:
            L.append(f"{float(v):g}")
        elif ifl == -1:                                  # radiación de Flather (iettype 0): nivel y velocidad normal medios
            nv = int(b.get("nvrt", 2))
            L.append("eta_mean"); L += ["0.0"] * n
            L.append("vn_mean"); L += [" ".join(["0.0"] * nv)] * n
        elif ifl == -4:
            L.append(f"{b.get('rel_in', 0.5):g} {b.get('rel_out', 0.5):g} !relajacion a uv3D.th.nc (entrada, salida)")
        elif ifl == 3:
            for c in constituents:
                ua, up, va, vp = [np.broadcast_to(np.asarray(x, float), n) for x in v["tides"].get(c, (0, 0, 0, 0))]
                L.append(c); L += [f"{a:.5f} {p:.3f} {b_:.5f} {q:.3f}" for a, p, b_, q in zip(ua, up, va, vp)]
        for flag, val in ((itt, t), (ist, s)):
            if flag == 2:
                L += [f"{float(val):g}", "1."]
            elif flag in (3, 4):
                L.append("1.")
    Path(path).write_text("\n".join(L) + "\n")
