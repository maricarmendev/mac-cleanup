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
#   --design      cachés de diseño/video (Adobe, Figma, Sketch, CapCut)
#   --browsers    cachés de navegador (Safari, Opera, Chrome)
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
MOD_DESIGN=false
MOD_BROWSERS=false
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
    --design)    MOD_DESIGN=true;    RUN_ALL=false ;;
    --browsers)  MOD_BROWSERS=true;  RUN_ALL=false ;;
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
  MOD_DEV=true; MOD_DESIGN=true; MOD_BROWSERS=true; MOD_MEMORY=true; MOD_SNAPSHOTS=true
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
  # Si du falla (p.ej. permisos), awk END garantiza que siempre salga un número.
  du -sk "$path" 2>/dev/null | awk 'END{print ($1=="" ? 0 : $1*1024)}'
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
  [ "${sz:-0}" -eq 0 ] && return 0

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
# MÓDULO: Cachés de diseño y video
# ----------------------------------------------------------------------------
# IMPORTANTE: aquí SOLO se tocan cachés regenerables, nunca proyectos ni datos.
# Adobe regenera su Media Cache solo (la primera apertura de un proyecto será
# un poco más lenta). Para Figma/CapCut solo se limpia caché, no borradores.
if $MOD_DESIGN; then
  header "🎨 Cachés de diseño y video"

  # --- Adobe (Premiere, After Effects, Photoshop, etc.) ---
  # Media Cache: el gran acumulador en edición de video. Seguro de borrar.
  clean_dir_contents "$HOME/Library/Application Support/Adobe/Common/Media Cache Files" "Adobe Media Cache Files"
  clean_dir_contents "$HOME/Library/Application Support/Adobe/Common/Media Cache" "Adobe Media Cache"
  clean_dir_contents "$HOME/Library/Application Support/Adobe/Common/Peak Files" "Adobe Peak Files"
  clean_dir_contents "$HOME/Library/Caches/Adobe" "Adobe (caché general)"
  clean_dir_contents "$HOME/Library/Caches/Adobe Camera Raw 2" "Adobe Camera Raw (v2)"
  clean_dir_contents "$HOME/Library/Caches/Adobe Camera Raw" "Adobe Camera Raw (legacy)"
  clean_dir_contents "$HOME/Library/Caches/com.adobe.Photoshop" "Photoshop (caché)"
  # Illustrator: la caché vive en ~/Library/Caches/Adobe Illustrator (regenerable).
  # NO se toca la carpeta de Settings, que puede contener archivos de recuperación.
  clean_dir_contents "$HOME/Library/Caches/Adobe Illustrator" "Illustrator (caché)"

  # --- Figma ---
  # Ruta real verificada (soporte oficial de Figma): la caché del app de
  # escritorio vive en Application Support, no en Caches. OJO: limpiarla
  # CIERRA TU SESIÓN de Figma (los diseños están en la nube, no se pierden).
  figma_dir="$HOME/Library/Application Support/Figma"
  if [ -d "$figma_dir" ]; then
    printf "  %b•%b Figma %b(%s)%b -> %s\n" "$CYAN" "$R" "$DIM" "$figma_dir" "$R" "$(human "$(size_of "$figma_dir")")"
    printf "  %b  (limpiar esto cerrará tu sesión de Figma; tendrás que volver a entrar)%b\n" "$DIM" "$R"
    if confirm "Limpiar caché de Figma? (cierra sesión)"; then
      clean_dir_contents "$figma_dir/Desktop" "Figma Desktop (caché)"
      clean_dir_contents "$figma_dir/DesktopProfile" "Figma DesktopProfile"
    fi
  fi

  # --- Sketch ---
  clean_dir_contents "$HOME/Library/Caches/com.bohemiancoding.sketch3" "Sketch (caché)"

  # --- CapCut (versión internacional: com.lemon.lvoverseas) ---
  # OJO: los proyectos viven en ~/Movies/CapCut, NO se tocan aquí.
  clean_dir_contents "$HOME/Library/Caches/com.lemon.lvoverseas" "CapCut (caché)"
  clean_dir_contents "$HOME/Library/Caches/42f94da3.com.lemon.lvoverseas" "CapCut (caché alt.)"

  printf "  %bNota: Adobe regenerará su Media Cache al reabrir proyectos.%b\n" "$DIM" "$R"
fi

# ----------------------------------------------------------------------------
# MÓDULO: Navegadores (Safari, Opera)
# ----------------------------------------------------------------------------
# Solo se limpia CACHÉ (archivos temporales regenerables). NUNCA se tocan
# historial, marcadores, contraseñas ni cookies (esos viven en otras carpetas).
if $MOD_BROWSERS; then
  header "🌐 Navegadores"

  # --- Safari ---
  # En macOS moderno Safari está protegido por SIP/TCC: para que la terminal
  # pueda borrar su caché necesitas dar "Acceso total al disco" a la Terminal
  # (Ajustes del Sistema > Privacidad y seguridad > Acceso total al disco).
  # Si no, estas líneas simplemente no borran nada (no rompen nada).
  clean_dir_contents "$HOME/Library/Caches/com.apple.Safari" "Safari (caché)"
  clean_dir_contents "$HOME/Library/Containers/com.apple.Safari/Data/Library/Caches" "Safari (caché contenedor)"
  if [ -d "$HOME/Library/Caches/com.apple.Safari" ] || [ -d "$HOME/Library/Containers/com.apple.Safari" ]; then
    printf "  %b  (si Safari no se limpió, da 'Acceso total al disco' a la Terminal)%b\n" "$DIM" "$R"
  fi

  # --- Opera --- (caché regenerable; datos/perfil están en Application Support)
  clean_dir_contents "$HOME/Library/Caches/com.operasoftware.Opera" "Opera (caché)"
  # Variantes comunes por si usa Opera GX o Developer:
  clean_dir_contents "$HOME/Library/Caches/com.operasoftware.OperaGX" "Opera GX (caché)"
  clean_dir_contents "$HOME/Library/Caches/com.operasoftware.OperaDeveloper" "Opera Developer (caché)"

  # --- Google Chrome --- (caché regenerable; el perfil, marcadores, contraseñas
  # y sesiones viven en ~/Library/Application Support/Google/Chrome y NO se tocan)
  # En macOS, Chrome guarda TODA su caché (incluyendo Default/Cache,
  # Default/Code Cache y Default/GPUCache) bajo ~/Library/Caches/Google/Chrome.
  # Por eso una sola línea padre basta; las rutas en Application Support/.../Default
  # son de Windows y en Mac no existen.
  clean_dir_contents "$HOME/Library/Caches/Google/Chrome" "Chrome (caché)"

  printf "  %bNota: historial, contraseñas y marcadores NO se tocan.%b\n" "$DIM" "$R"
fi

# ----------------------------------------------------------------------------
# MÓDULO: Memoria RAM
# ----------------------------------------------------------------------------
if $MOD_MEMORY; then
  header "🧠 Memoria"
  printf "  %bMemoria (MB):%b\n" "$DIM" "$R"
  # vm_stat reporta en PÁGINAS. El tamaño de página varía (Apple Silicon = 16 KB,
  # Intel = 4 KB), así que lo leemos de la cabecera y convertimos a MB.
  vm_stat | awk '
    NR==1 { for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+$/) ps=$i; if (ps=="") ps=16384; next }
    function mb(v){ gsub(/\./,"",v); return v*ps/1048576 }
    /Pages free/             { printf "    Libre:       %9.1f MB\n", mb($NF) }
    /Pages active/           { printf "    Activa:      %9.1f MB\n", mb($NF) }
    /Pages inactive/         { printf "    Inactiva:    %9.1f MB\n", mb($NF) }
    /Pages wired down/       { printf "    Reservada:   %9.1f MB\n", mb($NF) }
    /occupied by compressor/ { printf "    Comprimida:  %9.1f MB\n", mb($NF) }
  '
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