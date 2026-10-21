"""Caso de prueba de instalacion: seiche en una cuenca rectangular cerrada (2D barotropico).

Cuenca de 100 km x 50 km, 50 m de fondo, elevacion inicial gaussiana. 6 horas de simulacion.
Uso: python make_case.py <directorio_de_salida>
"""
import sys
from pathlib import Path
import numpy as np
from schismlab.io import write_gr3, write_vgrid_2d, write_prop, write_param
from schismlab.mesh import rectangular_basin

out = Path(sys.argv[1] if len(sys.argv) > 1 else "run"); out.mkdir(parents=True, exist_ok=True)
(out / "outputs").mkdir(exist_ok=True)

mesh = rectangular_basin(Lx=100e3, Ly=50e3, dx=2e3, depth=50.0, name="smoke_basin: seiche 100x50 km")
write_gr3(out / "hgrid.gr3", mesh)
write_gr3(out / "manning.gr3", mesh, values=0.025, boundaries=False)
eta0 = 0.5 * np.exp(-((mesh.x - 30e3) ** 2 + (mesh.y - 25e3) ** 2) / (2 * 10e3 ** 2))
write_gr3(out / "elev.ic", mesh, values=eta0, boundaries=False)
write_vgrid_2d(out / "vgrid.in")
write_prop(out / "tvd.prop", mesh, 1)
(out / "bctides.in").write_text("smoke_basin\n0 40.\n0\n0\n")
write_param(out / "param.nml", {
    "ibc": 1, "ibtp": 0, "rnday": 0.25, "dt": 60.0, "nspool": 10, "ihfskip": 360,
    "ics": 1, "ncor": 0, "coricoef": 1.0e-4, "nchi": -1, "hmin_man": 1.0,
    "ic_elev": 1, "nws": 0, "itur": 0, "ihot": 0, "dramp": 0.0,
    "iof_hydro(1)": 1, "iof_hydro(16)": 1, "iof_hydro(26)": 0,
})
print(f"caso generado en {out}: {mesh.nnodes} nodos, {mesh.nelements} elementos")
