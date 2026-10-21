#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SCHISMlab: compila SWASH (TU Delft, GPL) para el run-up y rebase del oleaje en perfiles 1D.
# Uso:  pixi run build-swash            -> ~/.schismlab/bin/swash.exe (serie, suficiente para perfiles 1D)
# Solo necesita un compilador Fortran 90 (el de pixi). Fuente: https://swash.sourceforge.io (GitLab TU Delft).
# ---------------------------------------------------------------------------
set -euo pipefail
SWASH_VERSION="${SWASH_VERSION:-12.01}"
ROOT="${SCHISMLAB_HOME:-$HOME/.schismlab}"
SRC="$ROOT/src/swash-$SWASH_VERSION"
BIN="$ROOT/bin"
if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: ejecuta este script con 'pixi run build-swash' para tener el compilador." >&2; exit 1
fi
mkdir -p "$ROOT/src" "$BIN"
if [[ ! -d "$SRC" ]]; then
  echo ">> Descargando SWASH $SWASH_VERSION ..."
  curl -fsSL "https://swash.sourceforge.io/download/zip/swash-$SWASH_VERSION.tar.gz" -o "$ROOT/src/swash.tar.gz"
  mkdir -p "$SRC"; tar -xzf "$ROOT/src/swash.tar.gz" -C "$SRC" --strip-components=1; rm -f "$ROOT/src/swash.tar.gz"
fi
cd "$SRC"
echo ">> Compilando SWASH (serie) con $(gfortran --version | head -1)"
# macro de plataforma: el Makefile de SWASH genera macros.inc con 'make config'
export FC=gfortran F90=gfortran
make config >/dev/null 2>&1 || true
if [[ ! -f macros.inc ]]; then
  echo "ERROR: 'make config' no genero macros.inc; revisa INSTALL.README en $SRC" >&2; exit 1
fi
sed -i.bak 's/^F90_SER *=.*/F90_SER = gfortran/' macros.inc   # -i.bak: vale en GNU y BSD (mac)
make ser 2>&1 | tail -3
cp -f swash.exe "$BIN/swash.exe"
echo ">> OK: $BIN/swash.exe"
