#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SCHISMlab: compila SCHISM dentro del entorno pixi (Linux, WSL2 y mac).
# Uso:  pixi run build-schism            (variante hydro, por defecto)
#       pixi run build-schism wwm        (hidrodinamica + oleaje WWM)
#       SCHISM_MODULES="USE_WWM USE_SED PREC_EVAP" pixi run build-schism wwm+sed   (cualquier combinacion)
#       SCHISM_VERSION=v5.13.0 pixi run build-schism
# Resultado: ~/.schismlab/bin/pschism_<variante>  (ejecutable)
# ---------------------------------------------------------------------------
set -euo pipefail

VARIANT="${1:-hydro}"
SCHISM_VERSION="${SCHISM_VERSION:-v5.13.0}"
ROOT="${SCHISMLAB_HOME:-$HOME/.schismlab}"
SRC="$ROOT/src/schism-$SCHISM_VERSION"
BUILD="$ROOT/build/$SCHISM_VERSION-$VARIANT"
BIN="$ROOT/bin"
NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu)"

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: ejecuta este script con 'pixi run build-schism' para tener el toolchain." >&2
  exit 1
fi

echo ">> SCHISM $SCHISM_VERSION, variante '$VARIANT', $NPROC procesos de compilacion"

# 1. Fuentes --------------------------------------------------------------
mkdir -p "$ROOT/src" "$BIN"
if [[ ! -d "$SRC" ]]; then
  echo ">> Descargando fuentes de SCHISM $SCHISM_VERSION ..."
  git clone -q --depth 1 --branch "$SCHISM_VERSION" https://github.com/schism-dev/schism.git "$SRC"
fi

# Parche: con C=Clang (mac) SCHISM pasa "--preprocess" a gfortran, que lo interpreta como -E (solo
# preprocesar) y no genera los modulos. gfortran necesita "-cpp" (bug de SCHISM 5.13, cmake/SCHISMCompile.cmake).
sed -i.bak 's/C_PREPROCESS_FLAG "--preprocess"/C_PREPROCESS_FLAG "-cpp"/g' "$SRC/cmake/SCHISMCompile.cmake" 2>/dev/null || true
# ... y ese flag solo debe aplicarse a Fortran (SCHISM lo aplica a todos los lenguajes y clang rechaza -cpp)
sed -i.bak 's/^add_compile_options(\${C_PREPROCESS_FLAG})/add_compile_options($<$<COMPILE_LANGUAGE:Fortran>:${C_PREPROCESS_FLAG}>)/' "$SRC/src/CMakeLists.txt" 2>/dev/null || true

# 2. Opciones por variante ---------------------------------------------------
# hydro y wwm son los nombres clasicos; cualquier otra variante toma sus modulos de SCHISM_MODULES
# (opciones de CMake separadas por espacios, p.ej. "USE_WWM USE_SED PREC_EVAP"; ver schismlab/build.py).
MODULE_FLAGS=()
case "$VARIANT" in
  hydro) MODULE_FLAGS+=(-DPREC_EVAP=ON) ;;
  wwm)   MODULE_FLAGS+=(-DUSE_WWM=ON -DPREC_EVAP=ON) ;;
  *) if [[ -z "${SCHISM_MODULES:-}" ]]; then
       echo "Variante '$VARIANT': define SCHISM_MODULES (p.ej. 'USE_WWM USE_SED PREC_EVAP')" >&2; exit 1
     fi
     for m in $SCHISM_MODULES; do MODULE_FLAGS+=("-D$m=ON"); done ;;
esac
echo ">> modulos: ${MODULE_FLAGS[*]:-ninguno}"

# 3. Configurar y compilar -------------------------------------------------------
FFLAGS="-O2 -ffree-line-length-none -fallow-argument-mismatch -finit-local-zero"
# un directorio de compilacion de otro entorno pixi (p. ej. tras cambiar pixi.lock) guarda en CMakeCache rutas a
# compiladores que ya no existen y CMake reconfigura sin modulos ("No rule to make target pschism"): se empieza de cero
if [[ -f "$BUILD/CMakeCache.txt" && "$(cat "$BUILD/.conda_prefix" 2>/dev/null)" != "$CONDA_PREFIX" ]]; then
  echo ">> directorio de compilacion de otro entorno: se borra $BUILD"
  rm -rf "$BUILD"
fi
mkdir -p "$BUILD"
echo "$CONDA_PREFIX" > "$BUILD/.conda_prefix"
cd "$BUILD"   # el CMake de ParMETIS crea un enlace "metis" en el directorio actual
cmake -S "$SRC/src" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_Fortran_COMPILER=mpifort \
  -DCMAKE_C_COMPILER=mpicc \
  -DCMAKE_CXX_COMPILER=mpicxx \
  -DCMAKE_Fortran_FLAGS_RELEASE="$FFLAGS" \
  -DNetCDF_FORTRAN_DIR="$CONDA_PREFIX" \
  -DNetCDF_C_DIR="$CONDA_PREFIX" \
  -DOLDIO=OFF -DTVD_LIM=VL -DBLD_STANDALONE=ON \
  ${MODULE_FLAGS[@]+"${MODULE_FLAGS[@]}"} > "$BUILD/cmake.log" 2>&1 || { tail -40 "$BUILD/cmake.log"; exit 1; }

make -C "$BUILD" -j"$NPROC" pschism > "$BUILD/make.log" 2>&1 || {
  echo ">> ERROR de compilacion; lineas relevantes de $BUILD/make.log:"
  grep -v -E "Building (C|Fortran|CXX) object|Wunused-command-line|Linking|Built target|^\[ *[0-9]+%\] *$" "$BUILD/make.log" | head -200
  echo ">> modulos encontrados:"; find "$BUILD" -iname "*.mod" | head -20
  echo ">> flags Fortran de Core:"; cat "$BUILD/Core/CMakeFiles/core.dir/flags.make" 2>/dev/null
  echo ">> regla de schism_glbl:"; grep -A4 "schism_glbl.F90.o:" "$BUILD/Core/CMakeFiles/core.dir/build.make" 2>/dev/null | head -8
  exit 1; }

# 4. Instalar el ejecutable con nombre estable -------------------------------------
EXE="$(ls -t "$BUILD"/bin/pschism_* | head -1)"   # el mas reciente (pueden coexistir varios nombres)
cp "$EXE" "$BIN/pschism_$VARIANT.new" && mv -f "$BIN/pschism_$VARIANT.new" "$BIN/pschism_$VARIANT"   # mv: no falla si el binario esta en uso
echo ">> OK: $BIN/pschism_$VARIANT  (copiado de $(basename "$EXE"))"
