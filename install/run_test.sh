#!/usr/bin/env bash
# Prueba de instalacion: genera el caso smoke_basin, lo ejecuta con 4 procesos y comprueba la salida.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${SCHISMLAB_HOME:-$HOME/.schismlab}"
EXE="$ROOT/bin/pschism_${1:-hydro}"
RUN="$ROOT/runs/smoke_basin"
NP="${NP:-4}"           # procesos de calculo
NSCRIBES="${NSCRIBES:-2}" # scribes de salida: SCHISM exige al menos tantos como variables de salida activas

[[ -x "$EXE" ]] || { echo "No existe $EXE: ejecuta antes 'pixi run build-schism'"; exit 1; }
# Un binario precompilado sin rpath ajustado busca NetCDF/MPI en el entorno pixi: se le indica donde estan
if [[ -n "${CONDA_PREFIX:-}" ]]; then
  export LD_LIBRARY_PATH="$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export DYLD_FALLBACK_LIBRARY_PATH="$CONDA_PREFIX/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
fi
rm -rf "$RUN"; mkdir -p "$RUN"
python "$HERE/cases/tests/smoke_basin/make_case.py" "$RUN"
cd "$RUN"
echo ">> ejecutando SCHISM con $NP procesos + $NSCRIBES scribes ..."
start=$(date +%s)
mpirun --oversubscribe -np $((NP + NSCRIBES)) "$EXE" $NSCRIBES > run.log 2>&1 || { tail -30 run.log; cat outputs/fatal.error 2>/dev/null; exit 1; }
echo ">> tiempo: $(( $(date +%s) - start )) s"
ls outputs/out2d_1.nc > /dev/null && echo ">> OK: outputs/out2d_1.nc generado en $RUN"
python -c "
import xarray as xr; ds = xr.open_dataset('outputs/out2d_1.nc')
e = ds['elevation']; print(f'>> elevacion: {e.shape}, max final {float(abs(e[-1]).max()):.3f} m (inicial 0.5 m)')"
