#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SCHISMlab: instalador para Linux, WSL2 (Ubuntu) y macOS.
#   1. instala pixi si falta        2. crea el entorno (compiladores, MPI, NetCDF, Python)
#   3. compila SCHISM               4. ejecuta el caso de prueba
# Uso: bash install/install.sh [hydro|wwm]
# ---------------------------------------------------------------------------
set -euo pipefail
VARIANT="${1:-hydro}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.pixi/bin:$PATH"

echo "== SCHISMlab: instalacion en $(uname -s) $(uname -m)"

# 0. Herramientas minimas del sistema (git, curl) ---------------------------------
if ! command -v git >/dev/null || ! command -v curl >/dev/null; then
  if command -v apt-get >/dev/null; then
    echo ">> instalando git y curl (se pedira la contrasena de administrador)"
    sudo apt-get update -qq && sudo apt-get install -y -qq git curl subversion autoconf automake libtool
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    echo ">> instalando las Command Line Tools de Xcode (acepta el dialogo)"; xcode-select --install || true
  fi
fi

# 1. pixi ----------------------------------------------------------------------
if ! command -v pixi >/dev/null; then
  echo ">> instalando pixi en ~/.pixi"
  curl -fsSL https://pixi.sh/install.sh | bash
fi
# Los entornos van fuera del repositorio (evita problemas con Dropbox/OneDrive/NTFS)
pixi config set --global detached-environments true >/dev/null

# 2. entorno -------------------------------------------------------------------
cd "$HERE"
echo ">> creando el entorno (puede tardar unos minutos la primera vez)"
pixi install

# 3. SCHISM --------------------------------------------------------------------
# Primero se intenta el ejecutable precompilado de las releases de GitHub (coincide con este pixi.lock);
# incluye su propia prueba. Si no hay o no funciona, se compila (10-20 min).
if pixi run python -m schismlab.prebuilt "$VARIANT"; then
  echo ">> SCHISM ($VARIANT) descargado y probado"
  pixi run fix-rpath >/dev/null 2>&1 || true
else
  echo ">> compilando SCHISM ($VARIANT)"
  pixi run build-schism "$VARIANT"
  # 4. prueba --------------------------------------------------------------------
  echo ">> caso de prueba"
  pixi run test-run "$VARIANT"
fi
# 5. modelos de run-up del oleaje (SWASH siempre; XBeach si se puede) -----------------
# (solo con SCHISMlab Pro: SCHISMlab Lite no tiene run-up ni mallas con costa real)
if pixi run python -c "from schismlab.edition import is_pro; raise SystemExit(0 if is_pro() else 1)" 2>/dev/null; then
  echo ">> modelos de oleaje para el run-up (SWASH, XBeach)"
  pixi run build-wave-models
  # 6. linea de costa de OpenStreetMap (polígonos de tierra globales, ~930 MB; evita Overpass y el servidor de GSHHG) ---
  echo ">> línea de costa OSM global (una sola vez; 'pixi run schismlab data coast --update' para actualizarla)"
  pixi run schismlab data coast || echo "AVISO: no se ha podido descargar la costa OSM (sin red); se usará GSHHG hasta que ejecutes 'pixi run schismlab data coast'"
fi
# 7. documentacion local (boton Ayuda de la interfaz) ----------------------------------
pixi run docs >/dev/null 2>&1 || echo "AVISO: no se ha podido generar la documentacion local (pixi run docs)"
# 8. pixi en el PATH de las terminales nuevas ----------------------------------------
RC="$HOME/.bashrc"; [[ "$(uname -s)" == "Darwin" && -f "$HOME/.zshrc" ]] && RC="$HOME/.zshrc"
if ! grep -q '.pixi/bin' "$RC" 2>/dev/null; then
  echo 'export PATH="$HOME/.pixi/bin:$PATH"' >> "$RC"
fi
echo "== SCHISMlab instalado correctamente. Ejecutables en ~/.schismlab/bin"
echo "   Interfaz:  pixi run schismlab gui     (http://localhost:8765)"
echo "   Si la terminal no encuentra 'pixi', abre una terminal nueva o ejecuta:  source $RC"
