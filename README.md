# mac-cleanup

Script de mantenimiento para macOS (Apple Silicon e Intel) que automatiza tareas de limpieza nativas del sistema: cachés, logs, papelera, cachés de desarrollo y diseño, navegadores, liberación de RAM y snapshots locales de Time Machine.

Es una alternativa casera y transparente a las herramientas comerciales de limpieza: hace solo lo que puedes ver en el código, sin instalar nada y usando únicamente comandos estándar de macOS.

---

## ⚠️ Advertencia

**Este script borra archivos y usa `sudo`. Úsalo bajo tu propio riesgo.**

- Corre **siempre primero el modo simulación** (sin `--apply`) para ver qué se borraría y cuánto espacio liberarías, sin tocar nada.
- Lee el código antes de ejecutarlo. No corras scripts de internet a ciegas.
- Cierra las aplicaciones que vayas a limpiar (navegadores, Figma, Illustrator, etc.) antes de usar `--apply`.
- El vaciado de la papelera es **permanente**.

El autor no se hace responsable de pérdida de datos. Ver [LICENSE](./LICENSE).

---

## Requisitos

- macOS (probado en macOS Tahoe 26.x / Apple Silicon M1 Pro; funciona también en Intel).
- Bash (el que trae macOS por defecto; no requiere instalar nada).

## Instalación

```bash
git clone https://github.com/<tu-usuario>/mac-cleanup.git
cd mac-cleanup
chmod +x smartcare.sh
```

## Uso

```bash
./smartcare.sh                # SIMULACIÓN: reporta qué borraría, no toca nada
./smartcare.sh --apply        # ejecuta la limpieza (pide confirmación en lo delicado)
./smartcare.sh --apply --yes  # ejecuta sin pedir confirmaciones (desatendido)
```

### Limpiar solo módulos específicos

Si pasas uno o más flags de módulo, solo se ejecutan esos:

```bash
./smartcare.sh --apply --dev --design   # solo cachés de desarrollo y diseño
./smartcare.sh --browsers               # simular solo navegadores
```

## Módulos

| Flag          | Qué limpia                                                                                                 |
| ------------- | ---------------------------------------------------------------------------------------------------------- |
| `--caches`    | Cachés de usuario y de sistema (regenerables).                                                             |
| `--logs`      | Logs de usuario y reportes de diagnóstico del sistema.                                                     |
| `--trash`     | Vacía la papelera (**permanente**).                                                                        |
| `--dev`       | Xcode (DerivedData, Archives, DeviceSupport), CoreSimulator, y prune de pnpm, npm, Homebrew, Docker, Yarn. |
| `--design`    | Cachés de Adobe (Media Cache, Camera Raw, Photoshop, Illustrator), Figma, Sketch, CapCut.                  |
| `--browsers`  | Cachés de Safari, Opera (+ GX/Developer) y Chrome.                                                         |
| `--memory`    | Libera RAM inactiva con `purge` y muestra el uso en MB.                                                    |
| `--snapshots` | Adelgaza los snapshots locales de Time Machine (recupera el espacio "purgable").                           |

Sin flags de módulo, se ejecutan todos.

## Notas de seguridad por módulo

- **Navegadores:** nunca se tocan historial, contraseñas ni marcadores; solo caché. Limpiar la caché puede cerrarte la sesión en algunos sitios web abiertos (recuperable).
- **Safari:** requiere dar _Acceso total al disco_ a la Terminal (Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco). Sin ese permiso, Safari simplemente no se limpia (no falla).
- **Figma:** limpiar su caché **cierra tu sesión** de Figma (tus diseños están en la nube; no se pierden). Por eso pide confirmación.
- **Illustrator / apps de Adobe:** ciérralas antes de limpiar. Con la app abierta y un documento sin guardar, la limpieza de caché podría afectar archivos de recuperación.
- **Cachés en general:** son archivos regenerables. Las apps los reconstruyen solas; el primer arranque tras la limpieza puede ser un poco más lento.

## Cómo funciona

El script no hace magia: combina comandos nativos de macOS (`du`, `find`, `purge`, `tmutil`, `pnpm store prune`, `brew cleanup`, etc.) para replicar las tareas de mantenimiento más útiles, de forma transparente y auditable.

## Licencia

MIT. Ver [LICENSE](./LICENSE).
