"""Los ocho módulos y sus objetivos, como datos.

Cada ruta de este archivo es una decisión con consecuencias. Están aquí, en una
lista legible de una sentada, en vez de repartidas por el código, para que se
puedan auditar y para que los tests las recorran todas.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from smartcare.core.targets import (
    CommandTarget,
    DirectoryTarget,
    Risk,
    SystemActionTarget,
)

Target = DirectoryTarget | CommandTarget | SystemActionTarget

DEFAULT_MIN_AGE_DAYS = 7


@dataclass(frozen=True)
class Module:
    key: str
    flag: str
    label: str
    risk: Risk
    targets: tuple[Target, ...]
    note: str = ""

    @property
    def preselected(self) -> bool:
        return self.risk is Risk.SAFE


# --- Raíces permitidas (invariante 4) ----------------------------------------
# Deliberadamente amplias: no son una lista de lo que se limpia, sino un muro
# contra un error de programación que apuntase a `/`, a Documentos o al home.


def allowed_roots() -> tuple[Path, ...]:
    home = Path.home()
    return (
        home / "Library",
        home / ".Trash",
        home / ".cache",
        home / ".gradle",
        home / ".cargo",
        home / ".npm",
        home / ".bun" / "install" / "cache",
        home / ".expo",
        home / ".agent-browser",
        # Solo la caché: el resto de ~/.nvm son las versiones de Node instaladas.
        home / ".nvm" / ".cache",
        Path("/Library/Caches"),
        Path("/Library/Logs"),
    )


# --- Lista de exclusión (invariante 5) ---------------------------------------

_SYNCED_DATA = (
    "~/Library/Caches/com.apple.bird",
    "~/Library/Caches/CloudKit",
    "~/Library/Caches/com.apple.CloudDocs",
    "~/Library/Application Support/CloudDocs",
    "~/Library/Application Support/FileProvider",
    "~/Library/Application Support/Adobe/CoreSync",
    "~/Library/Application Support/Adobe/CCLibraries",
    "~/Library/Caches/Adobe/CoreSync",
)

_RECOVERY_DATA = (
    # Vive DENTRO de la caché de InDesign, bajo una carpeta de versión que
    # cambia con cada actualización: de ahí el comodín.
    "~/Library/Caches/Adobe InDesign/**/InDesign Recovery",
    "~/Library/Application Support/Adobe/InDesign/**/Recovery",
)

EXCLUSION_PATTERNS = _SYNCED_DATA + _RECOVERY_DATA


def excluded_paths() -> tuple[Path, ...]:
    """Expande los patrones de exclusión a rutas concretas."""
    found: list[Path] = []
    for pattern in EXCLUSION_PATTERNS:
        expanded = Path(pattern).expanduser()
        if "*" not in pattern:
            found.append(expanded)
            continue
        anchor = Path(expanded.anchor)
        found.extend(sorted(anchor.glob(str(expanded.relative_to(anchor)))))
    return tuple(found)


# --- Exclusiones deliberadas --------------------------------------------------
# No son objetivos y no se limpian. Están aquí, y no simplemente ausentes, para
# que se vea que la decisión fue tomada y no olvidada.


@dataclass(frozen=True)
class DeliberateExclusion:
    label: str
    where: str
    reason: str


DELIBERATE_EXCLUSIONS = (
    DeliberateExclusion(
        "Previsualizaciones de Lightroom",
        "~/Pictures/*.lrdata",
        "ocupan mucho, pero regenerarlas cuesta horas de proceso",
    ),
    DeliberateExclusion(
        "Media de WhatsApp",
        "~/Library/Group Containers/*.net.whatsapp.WhatsApp",
        "no siempre se puede volver a descargar",
    ),
    DeliberateExclusion(
        "Datos sincronizados",
        "contenedores de iCloud, Adobe CoreSync y CC Libraries",
        "borrarlos dispara re-sincronizaciones masivas",
    ),
    DeliberateExclusion(
        "Datos de recuperación",
        "InDesign Recovery, dentro de la propia caché de InDesign",
        "contienen trabajo sin guardar",
    ),
    DeliberateExclusion(
        "Máquina virtual de Claude",
        "~/Library/Application Support/Claude/vm_bundles",
        "la app la usa mientras corre y la vuelve a descargar entera",
    ),
    DeliberateExclusion(
        "Historial de Claude Code",
        "~/.claude/projects",
        "son las conversaciones guardadas, no caché",
    ),
    DeliberateExclusion(
        "Emuladores e imágenes de Android",
        "~/.android/avd y ~/Library/Android/sdk",
        "borrarlos elimina los emuladores configurados y el SDK instalado",
    ),
    DeliberateExclusion(
        "Simuladores de iOS",
        "~/Library/Developer/CoreSimulator/Devices",
        "guardan las apps y el estado de cada simulador; los no disponibles ya se borran",
    ),
    DeliberateExclusion(
        "Datos de sitios en Chrome",
        "IndexedDB, File System y Local Storage de cada perfil",
        "son datos que guardan las páginas, no caché",
    ),
)


# --- Cachés de aplicaciones Electron ------------------------------------------
# Solo estas tres subcarpetas, enumeradas por nombre. El resto del perfil
# (Local Storage, IndexedDB, sesión) contiene estado y documentos sin
# sincronizar, y queda fuera del objetivo a propósito.

# Carpeta en Application Support → nombre visible. La carpeta no siempre se
# llama como la app: VS Code usa `Code` y Obsidian, `obsidian`.
ELECTRON_APPS = {
    "Miro": "Miro",
    "Notion": "Notion",
    "Zeplin": "Zeplin",
    "Framer": "Framer",
    "Slack": "Slack",
    "Discord": "Discord",
    "Postman": "Postman",
    "Claude": "Claude",
    "Code": "VS Code",
    "Grain": "Grain",
    "Linear": "Linear",
    "Fathom": "Fathom",
    "obsidian": "Obsidian",
    "ResponsivelyApp": "Responsively",
}
ELECTRON_CACHE_DIRS = ("Cache", "Code Cache", "GPUCache")


def _slug(text: str) -> str:
    return text.replace(" ", "-").lower()


def _electron_targets() -> tuple[DirectoryTarget, ...]:
    return tuple(
        DirectoryTarget(
            key=f"electron-{_slug(label)}-{_slug(sub)}",
            label=f"{label} ({sub})",
            path=f"~/Library/Application Support/{folder}/{sub}",
        )
        for folder, label in ELECTRON_APPS.items()
        for sub in ELECTRON_CACHE_DIRS
    )


# --- Módulos ------------------------------------------------------------------

CACHES = Module(
    key="caches",
    flag="--caches",
    label="Cachés",
    risk=Risk.SAFE,
    targets=(
        DirectoryTarget("caches-user", "Cachés de usuario", "~/Library/Caches", age_filtered=True),
        DirectoryTarget(
            "caches-system",
            "Cachés de sistema",
            "/Library/Caches",
            requires_privileges=True,
            age_filtered=True,
        ),
        DirectoryTarget(
            "caches-containers",
            "Cachés de apps en sandbox",
            "~/Library/Containers/*/Data/Library/Caches",
            age_filtered=True,
            note="requiere Acceso Total al Disco",
        ),
        DirectoryTarget(
            "caches-group-containers",
            "Cachés de contenedores compartidos",
            "~/Library/Group Containers/*/Library/Caches",
            age_filtered=True,
            note="requiere Acceso Total al Disco",
        ),
        DirectoryTarget(
            "caches-crashreporter",
            "Informes de fallos",
            "~/Library/Application Support/CrashReporter",
        ),
        DirectoryTarget(
            "caches-saved-state",
            "Estado de ventanas guardado",
            "~/Library/Saved Application State",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="las apps olvidarán qué ventanas tenían abiertas",
        ),
        DirectoryTarget(
            "caches-telegram-media",
            "Media de Telegram",
            "~/Library/Group Containers/*.ru.keepcoder.Telegram/*/postbox/media",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="se vuelve a descargar al abrir las conversaciones",
        ),
        *_electron_targets(),
        DirectoryTarget(
            "caches-zoom-webview",
            "Zoom (caché web)",
            "~/Library/Application Support/zoom.us/data/UnifyWebView_Cache",
        ),
        CommandTarget("caches-quicklook", "Miniaturas de QuickLook", ("qlmanage", "-r", "cache")),
        CommandTarget(
            "caches-fonts",
            "Cachés de fuentes",
            ("atsutil", "databases", "-remove"),
            requires_privileges=True,
            note="las fuentes se reindexan en el siguiente arranque",
        ),
    ),
)

LOGS = Module(
    key="logs",
    flag="--logs",
    label="Logs",
    risk=Risk.SAFE,
    targets=(
        DirectoryTarget("logs-user", "Logs de usuario", "~/Library/Logs", age_filtered=True),
        DirectoryTarget(
            "logs-diagnostic",
            "Reportes de diagnóstico",
            "/Library/Logs/DiagnosticReports",
            requires_privileges=True,
            age_filtered=True,
        ),
    ),
)

TRASH = Module(
    key="trash",
    flag="--trash",
    label="Papelera",
    risk=Risk.DESTRUCTIVE,
    note="vaciarla es permanente: lo que hay dentro no se puede recuperar",
    targets=(DirectoryTarget("trash-user", "Papelera", "~/.Trash", risk=Risk.DESTRUCTIVE),),
)

DEV = Module(
    key="dev",
    flag="--dev",
    label="Cachés de desarrollo",
    risk=Risk.SAFE,
    targets=(
        DirectoryTarget(
            "dev-xcode-derived", "Xcode DerivedData", "~/Library/Developer/Xcode/DerivedData"
        ),
        DirectoryTarget(
            "dev-xcode-archives",
            "Xcode Archives",
            "~/Library/Developer/Xcode/Archives",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="contienen los dSYM de versiones ya publicadas",
        ),
        DirectoryTarget(
            "dev-xcode-ios-devicesupport",
            "iOS DeviceSupport",
            "~/Library/Developer/Xcode/iOS DeviceSupport",
        ),
        DirectoryTarget(
            "dev-xcode-watchos-devicesupport",
            "watchOS DeviceSupport",
            "~/Library/Developer/Xcode/watchOS DeviceSupport",
        ),
        DirectoryTarget(
            "dev-xcode-device-logs",
            "Logs de dispositivos iOS",
            "~/Library/Developer/Xcode/iOS Device Logs",
        ),
        DirectoryTarget(
            "dev-coresimulator", "CoreSimulator Caches", "~/Library/Developer/CoreSimulator/Caches"
        ),
        DirectoryTarget("dev-cocoapods", "CocoaPods", "~/Library/Caches/CocoaPods"),
        DirectoryTarget("dev-gradle", "Gradle", "~/.gradle/caches"),
        DirectoryTarget("dev-yarn", "Yarn", "~/Library/Caches/Yarn"),
        # `npm cache clean` no toca _npx: los paquetes que bajó `npx` se
        # acumulan aquí sin límite y se vuelven a descargar al usarse.
        DirectoryTarget("dev-npx", "npx (paquetes descargados)", "~/.npm/_npx"),
        DirectoryTarget("dev-bun", "Bun", "~/.bun/install/cache"),
        DirectoryTarget("dev-nvm", "nvm (descargas de Node)", "~/.nvm/.cache"),
        DirectoryTarget(
            "dev-expo-simulator",
            "Expo (apps de simulador)",
            "~/.expo/ios-simulator-app-cache",
        ),
        DirectoryTarget(
            "dev-agent-browser",
            "agent-browser (temporales)",
            "~/.agent-browser/tmp",
            age_filtered=True,
            note="solo lo que lleva días sin usarse; una sesión abierta escribe aquí",
        ),
        DirectoryTarget(
            "dev-vscode-cached-data",
            "VS Code (código compilado)",
            "~/Library/Application Support/Code/CachedData",
        ),
        DirectoryTarget(
            "dev-vscode-vsix",
            "VS Code (instaladores de extensiones)",
            "~/Library/Application Support/Code/CachedExtensionVSIXs",
        ),
        DirectoryTarget("dev-cache-dir", "~/.cache (varios)", "~/.cache"),
        DirectoryTarget(
            "dev-ios-updates",
            "Actualizaciones de iOS antiguas",
            "~/Library/iTunes/iPhone Software Updates",
        ),
        CommandTarget(
            "dev-simctl",
            "Simuladores no disponibles",
            ("xcrun", "simctl", "delete", "unavailable"),
            probe="xcrun",
        ),
        CommandTarget(
            "dev-brew",
            "Homebrew",
            ("brew", "cleanup", "--prune=all"),
            probe="brew",
            size_from=("brew", "--cache"),
        ),
        CommandTarget(
            "dev-npm",
            "npm",
            ("npm", "cache", "clean", "--force"),
            probe="npm",
            size_from=("npm", "config", "get", "cache"),
            size_subpath="_cacache",
        ),
        CommandTarget(
            "dev-pnpm",
            "pnpm",
            ("pnpm", "store", "prune"),
            probe="pnpm",
            size_from=("pnpm", "store", "path"),
        ),
        CommandTarget("dev-uv", "uv", ("uv", "cache", "clean"), probe="uv"),
        # El subcomando `cache` no viene con cargo: lo instala cargo-cache aparte,
        # así que es ese binario el que hay que detectar.
        CommandTarget("dev-cargo", "cargo", ("cargo", "cache", "-a"), probe="cargo-cache"),
        CommandTarget(
            "dev-docker",
            "Docker",
            ("docker", "system", "prune", "-a", "--volumes", "-f"),
            probe="docker",
            readiness=("docker", "info"),
            risk=Risk.DESTRUCTIVE,
            note="borra imágenes y volúmenes que no estén en uso",
        ),
    ),
)

DESIGN = Module(
    key="design",
    flag="--design",
    label="Cachés de diseño y vídeo",
    risk=Risk.SAFE,
    note="Adobe regenerará su Media Cache al reabrir los proyectos",
    targets=(
        DirectoryTarget(
            "design-adobe-media-cache-files",
            "Adobe Media Cache Files",
            "~/Library/Application Support/Adobe/Common/Media Cache Files",
        ),
        DirectoryTarget(
            "design-adobe-media-cache",
            "Adobe Media Cache",
            "~/Library/Application Support/Adobe/Common/Media Cache",
        ),
        DirectoryTarget(
            "design-adobe-peak-files",
            "Adobe Peak Files",
            "~/Library/Application Support/Adobe/Common/Peak Files",
        ),
        DirectoryTarget("design-adobe-caches", "Adobe (caché general)", "~/Library/Caches/Adobe"),
        DirectoryTarget(
            "design-camera-raw-2", "Adobe Camera Raw (v2)", "~/Library/Caches/Adobe Camera Raw 2"
        ),
        DirectoryTarget(
            "design-camera-raw", "Adobe Camera Raw", "~/Library/Caches/Adobe Camera Raw"
        ),
        DirectoryTarget(
            "design-photoshop", "Photoshop (caché)", "~/Library/Caches/com.adobe.Photoshop"
        ),
        DirectoryTarget(
            "design-illustrator",
            "Illustrator (caché)",
            "~/Library/Caches/Adobe Illustrator",
            note="no se toca su carpeta Settings, que guarda archivos de recuperación",
        ),
        DirectoryTarget(
            "design-figma-desktop",
            "Figma Desktop (caché)",
            "~/Library/Application Support/Figma/Desktop",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="cierra tu sesión de Figma; los diseños están en la nube",
        ),
        DirectoryTarget(
            "design-figma-profile",
            "Figma DesktopProfile",
            "~/Library/Application Support/Figma/DesktopProfile",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="cierra tu sesión de Figma; los diseños están en la nube",
        ),
        DirectoryTarget(
            "design-sketch", "Sketch (caché)", "~/Library/Caches/com.bohemiancoding.sketch3"
        ),
        DirectoryTarget(
            "design-capcut",
            "CapCut (caché)",
            "~/Library/Caches/com.lemon.lvoverseas",
            note="los proyectos viven en ~/Movies/CapCut y no se tocan",
        ),
        DirectoryTarget(
            "design-capcut-alt",
            "CapCut (caché alternativa)",
            "~/Library/Caches/42f94da3.com.lemon.lvoverseas",
        ),
    ),
)

BROWSERS = Module(
    key="browsers",
    flag="--browsers",
    label="Navegadores",
    risk=Risk.SAFE,
    note="historial, contraseñas, marcadores y cookies no se tocan",
    targets=(
        DirectoryTarget("browsers-safari", "Safari (caché)", "~/Library/Caches/com.apple.Safari"),
        DirectoryTarget(
            "browsers-safari-container",
            "Safari (caché del contenedor)",
            "~/Library/Containers/com.apple.Safari/Data/Library/Caches",
            note="requiere Acceso Total al Disco",
        ),
        DirectoryTarget("browsers-chrome", "Chrome (caché)", "~/Library/Caches/Google/Chrome"),
        # El comodín recorre todos los perfiles (Default, Profile 1…). Junto a
        # CacheStorage viven IndexedDB y File System, que son datos de los
        # sitios y quedan fuera.
        DirectoryTarget(
            "browsers-chrome-service-workers",
            "Chrome (caché de Service Workers)",
            "~/Library/Application Support/Google/Chrome/*/Service Worker/CacheStorage",
            note="cierra Chrome antes de limpiar",
        ),
        DirectoryTarget(
            "browsers-chrome-gpu",
            "Chrome (caché de GPU)",
            "~/Library/Application Support/Google/Chrome/*/GPUCache",
        ),
        DirectoryTarget(
            "browsers-chrome-components",
            "Chrome (componentes descargados)",
            "~/Library/Application Support/Google/Chrome/component_crx_cache",
        ),
        DirectoryTarget(
            "browsers-google-updater",
            "Google Updater (descargas)",
            "~/Library/Application Support/Google/GoogleUpdater/crx_cache",
        ),
        DirectoryTarget(
            "browsers-chrome-ai-model",
            "Chrome (modelo de IA local)",
            "~/Library/Application Support/Google/Chrome/OptGuideOnDeviceModel",
            stage_in_trash=True,
            risk=Risk.WARNING,
            note="Chrome lo vuelve a descargar (~4 GB) si las funciones de IA siguen activas",
        ),
        DirectoryTarget(
            "browsers-opera", "Opera (caché)", "~/Library/Caches/com.operasoftware.Opera"
        ),
        DirectoryTarget(
            "browsers-opera-gx", "Opera GX (caché)", "~/Library/Caches/com.operasoftware.OperaGX"
        ),
        DirectoryTarget(
            "browsers-opera-dev",
            "Opera Developer (caché)",
            "~/Library/Caches/com.operasoftware.OperaDeveloper",
        ),
    ),
)

MEMORY = Module(
    key="memory",
    flag="--memory",
    label="Memoria",
    risk=Risk.SAFE,
    targets=(
        SystemActionTarget(
            "memory-purge",
            "Liberar RAM inactiva",
            ("purge",),
            effect="libera memoria inactiva; no libera espacio en disco",
        ),
    ),
)

SNAPSHOTS = Module(
    key="snapshots",
    flag="--snapshots",
    label="Snapshots locales",
    risk=Risk.WARNING,
    note="elimina los puntos de restauración locales de Time Machine",
    targets=(
        SystemActionTarget(
            "snapshots-thin",
            "Adelgazar snapshots locales",
            ("tmutil", "thinlocalsnapshots", "/", "999999999999", "4"),
            effect="recupera el espacio marcado como purgable",
            risk=Risk.WARNING,
        ),
    ),
)

MODULES: tuple[Module, ...] = (CACHES, LOGS, TRASH, DEV, DESIGN, BROWSERS, MEMORY, SNAPSHOTS)


def module_by_key(key: str) -> Module | None:
    return next((module for module in MODULES if module.key == key), None)


def directory_targets(modules: Iterable[Module]) -> list[DirectoryTarget]:
    return [
        target
        for module in modules
        for target in module.targets
        if isinstance(target, DirectoryTarget)
    ]


def carve_outs(selected: Sequence[DirectoryTarget]) -> dict[str, tuple[Path, ...]]:
    """Rutas que cada objetivo debe respetar porque otro seleccionado las cubre.

    Sin esto, el módulo de cachés y el de diseño contarían dos veces las mismas
    carpetas de Adobe, que viven bajo `~/Library/Caches`. El cálculo depende de
    la selección: si el módulo específico no está elegido, el objetivo ancho se
    lleva esas carpetas como siempre.
    """
    resolved = {target.key: target.resolved_paths() for target in selected}
    result: dict[str, tuple[Path, ...]] = {}
    for target in selected:
        inside: list[Path] = []
        for other in selected:
            if other.key == target.key:
                continue
            inside.extend(
                path
                for path in resolved[other.key]
                if any(path != mine and path.is_relative_to(mine) for mine in resolved[target.key])
            )
        result[target.key] = tuple(sorted(set(inside)))
    return result
