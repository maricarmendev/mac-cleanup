#!/usr/bin/env bash
#
# smartcare.sh — Limpieza tipo "Smart Care" para macOS (Apple Silicon)
# Compatible con el bash 3.2 que trae macOS por defecto (sin arreglos asociativos).
# Probado en: MacBook Pro M1 Pro / macOS Tahoe 26.x
#
# USO:
#   ./smartcare.sh                -> modo SIMULACIÓN (no borra nada, solo reporta)
#   ./smartcare.sh --apply        -> ejecuta la limpieza de verdad
#   ./smartcare.sh --apply --yes  -> sin pedir confirmaciones (modo desatendido)
#
# FLAGS DE MÓDULOS (si no pasas ninguno, corren TODOS los seguros):
#   --caches      cachés de usuario y sistema
#   --logs        logs antiguos
#   --trash       vaciar papelera
#   --dev         cachés de desarrollo (Xcode, pnpm, npm, Docker, Homebrew)
#   --memory      liberar RAM inactiva (purge)
#   --snapshots   limpiar snapshots locales de Time Machine
#
# Ej: ./smartcare.sh --apply --dev --caches
#
set -uo pipefail

# ----------------------------------------------------------------------------
# Configuración (variables simples, compatibles con bash 3.2)
# ----------------------------------------------------------------------------
DRY_RUN=true
ASSUME_YES=false
RUN_ALL=true

MOD_CACHES=false
MOD_LOGS=false
MOD_TRASH=false
MOD_DEV=false
MOD_MEMORY=false
MOD_SNAPSHOTS=false

# Colores
B="\033[1m"; DIM="\033[2m"; R="\033[0m"
GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; CYAN="\033[36m"

TOTAL_FREED=0  # bytes liberados (estimado)

# ----------------------------------------------------------------------------
# Parseo de argumentos
# ----------------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --apply)     DRY_RUN=false ;;
    --yes|-y)    ASSUME_YES=true ;;
    --dry-run)   DRY_RUN=true ;;
    --caches)    MOD_CACHES=true;    RUN_ALL=false ;;
    --logs)      MOD_LOGS=true;      RUN_ALL=false ;;
    --trash)     MOD_TRASH=true;     RUN_ALL=false ;;
    --dev)       MOD_DEV=true;       RUN_ALL=false ;;
    --memory)    MOD_MEMORY=true;    RUN_ALL=false ;;
    --snapshots) MOD_SNAPSHOTS=true; RUN_ALL=false ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -n 30
      exit 0 ;;
    *) echo "Argumento desconocido: $arg"; exit 1 ;;
  esac
done

if $RUN_ALL; then
  MOD_CACHES=true; MOD_LOGS=true; MOD_TRASH=true
  MOD_DEV=true; MOD_MEMORY=true; MOD_SNAPSHOTS=true
fi

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
human() {
  # bytes -> humano
  local b="${1:-0}"
  awk -v b="$b" 'BEGIN{
    split("B KB MB GB TB", u, " "); i=1;
    while (b>=1024 && i<5){ b/=1024; i++ }
    printf "%.1f %s", b, u[i]
  }'
}

size_of() {
  # tamaño en bytes de una ruta (0 si no existe)
  local path="$1"
  [ -e "$path" ] || { echo 0; return; }
  du -sk "$path" 2>/dev/null | awk '{print $1*1024}'
}

confirm() {
  $ASSUME_YES && return 0
  $DRY_RUN && return 0
  printf "%b" "${YELLOW}? $1 [s/N]: ${R}"
  read -r ans
  case "$ans" in
    [sSyY]) return 0 ;;
    *) return 1 ;;
  esac
}

# Borra el CONTENIDO de un directorio (no el directorio en sí).
# En dry-run solo reporta el tamaño.
clean_dir_contents() {
  local dir="$1"; local label="$2"; local use_sudo="${3:-false}"
  [ -d "$dir" ] || return 0

  local sz; sz=$(size_of "$dir")
  [ "$sz" -eq 0 ] && return 0

  printf "  %b•%b %s %b(%s)%b -> %s\n" "$CYAN" "$R" "$label" "$DIM" "$dir" "$R" "$(human "$sz")"

  if $DRY_RUN; then
    TOTAL_FREED=$((TOTAL_FREED + sz))
    return 0
  fi

  # find + delete es más seguro que rm -rf "$dir"/*
  # nunca borramos el directorio padre, solo su contenido.
  if [ "$use_sudo" = true ]; then
    sudo find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null
  else
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null
  fi
  TOTAL_FREED=$((TOTAL_FREED + sz))
}

header() { printf "\n%b%s%b\n" "$B" "$1" "$R"; }

# ----------------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------------
printf "%b🧹 SmartCare casero — limpieza para macOS%b\n" "$B" "$R"
if $DRY_RUN; then
  printf "%bModo SIMULACIÓN: no se borrará nada. Usa --apply para ejecutar.%b\n" "$YELLOW" "$R"
else
  printf "%bModo APLICAR: se borrarán archivos.%b\n" "$RED" "$R"
fi
printf "%bmacOS: %s | %s%b\n" "$DIM" "$(sw_vers -productVersion)" "$(uname -m)" "$R"

# Espacio en disco antes
printf "%bDisco antes:%b\n" "$DIM" "$R"
df -h / | awk 'NR==1 || /\/$/ {print "  "$0}'

# ----------------------------------------------------------------------------
# MÓDULO: Cachés
# ----------------------------------------------------------------------------
if $MOD_CACHES; then
  header "📦 Cachés"
  clean_dir_contents "$HOME/Library/Caches" "Cachés de usuario"
  if confirm "Limpiar cachés de sistema (/Library/Caches, requiere sudo)?"; then
    clean_dir_contents "/Library/Caches" "Cachés de sistema" true
  fi
fi

# ----------------------------------------------------------------------------
# MÓDULO: Logs
# ----------------------------------------------------------------------------
if $MOD_LOGS; then
  header "📝 Logs"
  clean_dir_contents "$HOME/Library/Logs" "Logs de usuario"
  if confirm "Limpiar logs de diagnóstico de sistema (requiere sudo)?"; then
    clean_dir_contents "/Library/Logs/DiagnosticReports" "Reportes de diagnóstico" true
  fi
fi

# ----------------------------------------------------------------------------
# MÓDULO: Papelera
# ----------------------------------------------------------------------------
if $MOD_TRASH; then
  header "🗑  Papelera"
  clean_dir_contents "$HOME/.Trash" "Papelera"
fi

# ----------------------------------------------------------------------------
# MÓDULO: Cachés de desarrollo
# ----------------------------------------------------------------------------
if $MOD_DEV; then
  header "💻 Cachés de desarrollo"

  # Xcode (suele ser ENORME)
  clean_dir_contents "$HOME/Library/Developer/Xcode/DerivedData" "Xcode DerivedData"
  clean_dir_contents "$HOME/Library/Developer/Xcode/Archives" "Xcode Archives"
  clean_dir_contents "$HOME/Library/Developer/Xcode/iOS DeviceSupport" "iOS DeviceSupport"
  clean_dir_contents "$HOME/Library/Developer/CoreSimulator/Caches" "CoreSimulator Caches"

  # pnpm
  if command -v pnpm >/dev/null 2>&1; then
    pnpm_path=$(pnpm store path 2>/dev/null)
    [ -n "$pnpm_path" ] && printf "  %b•%b pnpm store %b(%s)%b -> %s\n" "$CYAN" "$R" "$DIM" "$pnpm_path" "$R" "$(human "$(size_of "$pnpm_path")")"
    if ! $DRY_RUN && confirm "Ejecutar 'pnpm store prune'?"; then
      pnpm store prune
    fi
  fi

  # npm
  if command -v npm >/dev/null 2>&1; then
    npm_cache=$(npm config get cache 2>/dev/null)
    [ -d "$npm_cache" ] && printf "  %b•%b npm cache %b(%s)%b -> %s\n" "$CYAN" "$R" "$DIM" "$npm_cache" "$R" "$(human "$(size_of "$npm_cache")")"
    if ! $DRY_RUN && confirm "Ejecutar 'npm cache clean --force'?"; then
      npm cache clean --force 2>/dev/null
    fi
  fi

  # Homebrew
  if command -v brew >/dev/null 2>&1; then
    printf "  %b•%b Homebrew -> cache en %s\n" "$CYAN" "$R" "$(brew --cache 2>/dev/null)"
    if ! $DRY_RUN && confirm "Ejecutar 'brew cleanup --prune=all'?"; then
      brew cleanup --prune=all
    fi
  fi

  # Docker (cuidado: borra imágenes/volúmenes no usados)
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    printf "  %b•%b Docker -> %s\n" "$CYAN" "$R" "$(docker system df --format '{{.Type}}: {{.Size}}' 2>/dev/null | tr '\n' ' ')"
    if ! $DRY_RUN && confirm "Ejecutar 'docker system prune -a --volumes'? (borra imágenes y volúmenes NO usados)"; then
      docker system prune -a --volumes -f
    fi
  fi

  # Yarn / otros gestores comunes
  clean_dir_contents "$HOME/Library/Caches/Yarn" "Yarn cache"
  clean_dir_contents "$HOME/.cache" "~/.cache (varios)"
fi

# ----------------------------------------------------------------------------
# MÓDULO: Memoria RAM
# ----------------------------------------------------------------------------
if $MOD_MEMORY; then
  header "🧠 Memoria"
  printf "  %bMemoria (vm_stat):%b\n" "$DIM" "$R"
  vm_stat | awk '/free|inactive|wired|active/ {print "    "$0}'
  if confirm "Liberar RAM inactiva con 'sudo purge'?"; then
    $DRY_RUN || sudo purge
    printf "  %b✓ purge ejecutado%b\n" "$GREEN" "$R"
  fi
fi

# ----------------------------------------------------------------------------
# MÓDULO: Snapshots locales de Time Machine (espacio "purgable")
# ----------------------------------------------------------------------------
if $MOD_SNAPSHOTS; then
  header "📸 Snapshots locales (Time Machine)"
  snaps=$(tmutil listlocalsnapshots / 2>/dev/null | grep -c "com.apple")
  printf "  %b•%b Snapshots locales encontrados: %s\n" "$CYAN" "$R" "${snaps:-0}"
  if [ "${snaps:-0}" -gt 0 ] && confirm "Eliminar snapshots locales? (recupera el espacio 'purgable')"; then
    if ! $DRY_RUN; then
      sudo tmutil thinlocalsnapshots / 999999999999 4
    fi
    printf "  %b✓ snapshots adelgazados%b\n" "$GREEN" "$R"
  fi
fi

# ----------------------------------------------------------------------------
# Resumen
# ----------------------------------------------------------------------------
printf "\n%b─────────────────────────────────────%b\n" "$B" "$R"
if $DRY_RUN; then
  printf "%bSIMULACIÓN. Espacio recuperable estimado: %b%s%b\n" "$YELLOW" "$B" "$(human "$TOTAL_FREED")" "$R"
  printf "%b(No incluye prune de pnpm/npm/brew/docker, que se ejecutan en --apply)%b\n" "$DIM" "$R"
  printf "Para ejecutar de verdad: %b%s --apply%b\n" "$B" "$0" "$R"
else
  printf "%bLimpieza terminada. Liberado aprox.: %b%s%b\n" "$GREEN" "$B" "$(human "$TOTAL_FREED")" "$R"
  printf "%bDisco después:%b\n" "$DIM" "$R"
  df -h / | awk '/\/$/ {print "  "$0}'
fi