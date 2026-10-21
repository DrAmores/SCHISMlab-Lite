#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SCHISMlab: compila XBeach (Deltares, GPL) para el run-up no hidrostático en perfiles 1D (opcional).
# Uso:  pixi run build-xbeach   -> ~/.schismlab/bin/xbeach
# Necesita svn y autotools del sistema (apt install subversion autoconf automake libtool) y el netCDF/MPI de pixi.
# Fuente: https://svn.oss.deltares.nl/repos/xbeach/trunk (anónimo).
# ---------------------------------------------------------------------------
set -euo pipefail
ROOT="${SCHISMLAB_HOME:-$HOME/.schismlab}"
SRC="$ROOT/src/xbeach"
BIN="$ROOT/bin"
if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: ejecuta este script con 'pixi run build-xbeach'." >&2; exit 1
fi
for tool in svn autoconf automake libtoolize; do
  command -v $tool >/dev/null || { echo "ERROR: falta $tool (apt install subversion autoconf automake libtool)" >&2; exit 1; }
done
mkdir -p "$ROOT/src" "$BIN"
if [[ ! -d "$SRC" ]]; then
  echo ">> Descargando XBeach (svn, trunk) ..."
  svn checkout -q --non-interactive --trust-server-cert https://svn.oss.deltares.nl/repos/xbeach/trunk "$SRC"
fi
cd "$SRC"
python -c "import mako" 2>/dev/null || { echo "ERROR: falta mako (pixi add mako)" >&2; exit 1; }
echo ">> Configurando XBeach con netCDF y MPI de pixi ..."
export FC=mpif90 F77=mpif90 CC=mpicc FCFLAGS="-O2 -ffree-line-length-none -fallow-argument-mismatch -fallow-invalid-boz" FFLAGS="-O2 -fallow-argument-mismatch"
export PKG_CONFIG_PATH="$CONDA_PREFIX/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export NETCDF_FORTRAN_CFLAGS="$(nf-config --fflags)" NETCDF_FORTRAN_LIBS="$(nf-config --flibs)"
make distclean >/dev/null 2>&1 || true
./autogen.sh >/dev/null 2>&1
./configure --prefix="$ROOT/xbeach" --with-netcdf --with-mpi 2>&1 | tail -3
make 2>&1 | tail -3        # en serie: los .inc generados con mako fallan con -j
make install >/dev/null
ln -sf "$ROOT/xbeach/bin/xbeach" "$BIN/xbeach"
echo ">> OK: $BIN/xbeach (MPI: se ejecuta con mpirun -np 2)"
