#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SCHISMlab: compila los modelos de run-up del oleaje que acompañan a SCHISM: SWASH (siempre) y XBeach (si el
# sistema tiene svn y autotools; en Debian/Ubuntu/WSL se instalan con apt si hay sudo). No falla la instalación
# si XBeach no se puede compilar: es opcional (Stockdon y SWASH bastan para la práctica).
# Uso:  pixi run build-wave-models
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SCHISMLAB_HOME:-$HOME/.schismlab}"
if [[ -x "$ROOT/bin/swash.exe" ]]; then
  echo ">> SWASH ya compilado: $ROOT/bin/swash.exe"
else
  bash "$HERE/build_swash.sh" || { echo "AVISO: SWASH no se ha podido compilar (el run-up por SWASH no estará disponible)" >&2; }
fi
if [[ -x "$ROOT/bin/xbeach" || -L "$ROOT/bin/xbeach" ]]; then
  echo ">> XBeach ya compilado: $ROOT/bin/xbeach"
else
  missing=()
  for tool in svn autoconf automake libtoolize; do command -v $tool >/dev/null || missing+=($tool); done
  if (( ${#missing[@]} )) && command -v apt-get >/dev/null && command -v sudo >/dev/null; then
    echo ">> instalando ${missing[*]} para XBeach (se pedirá la contraseña de administrador; Ctrl-C para saltarlo)"
    sudo -n true 2>/dev/null || true
    sudo apt-get install -y -qq subversion autoconf automake libtool >/dev/null 2>&1 || true
    missing=(); for tool in svn autoconf automake libtoolize; do command -v $tool >/dev/null || missing+=($tool); done
  fi
  if (( ${#missing[@]} )); then
    echo "AVISO: XBeach no se compila: faltan ${missing[*]} (apt install subversion autoconf automake libtool; luego pixi run build-xbeach)" >&2
  else
    bash "$HERE/build_xbeach.sh" || { echo "AVISO: XBeach no se ha podido compilar (opcional; SWASH y Stockdon siguen disponibles)" >&2; }
  fi
fi
exit 0
