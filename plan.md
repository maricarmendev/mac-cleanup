# Migración de SmartCare a aplicación TUI

## Contexto

`smartcare.sh` es un script de mantenimiento para macOS de 364 líneas en bash: mide y borra
cachés, logs, papelera, cachés de desarrollo y diseño, cachés de navegador, libera RAM y adelgaza
snapshots de Time Machine. Funciona, pero su interfaz es texto plano en la terminal: para saber qué
se va a borrar hay que leer un volcado de líneas, la selección de módulos se hace con flags antes de
ver ningún dato, y no hay forma de decidir sobre la marcha.

El objetivo es convertirlo en una **aplicación de terminal interactiva (TUI)**: analizar primero,
enseñar qué ocupa cada cosa, dejar elegir con casillas y limpiar con progreso visible. La prioridad
es que la usen dos personas no técnicas en sus propios Macs: se abre con doble clic desde el Finder
o el Dock y no exige escribir ningún comando.

### Decisiones ya tomadas

| Decisión | Elección |
| --- | --- |
| Stack | Python (lógica) + Textual (interfaz de terminal) |
| Arranque | Lanzador doble-clicable **y** comando `smartcare` con flags |
| Distribución | Binario autocontenido (PyInstaller) instalado en persona; los Macs destino no tienen Python |
| Tests | `pytest` sobre el motor (medir/borrar), no sobre la interfaz |
| Script actual | Se elimina al final, cuando haya paridad demostrada |

### Restricciones del entorno (verificadas)

- Python 3.14.6 (Homebrew) y `uv` 0.12.2 disponibles. Sin Xcode.app, solo Command Line Tools.
- `sudo` pide contraseña: no hay credencial en caché. Dentro de una TUI a pantalla completa el
  prompt de `sudo` corrompe la pantalla alternativa: hay que suspender la interfaz durante la
  autenticación y redibujar al volver.
- Varias rutas del script no existen en esta máquina (Xcode DerivedData, Figma). La interfaz debe
  tratar los objetivos ausentes sin ruido visual.
- Para tocar `~/Library/Caches`, `~/.Trash` y los contenedores de Safari hace falta **Acceso Total
  al Disco** concedido a la app de Terminal (una vez por máquina, paso manual en Ajustes). Sin ese
  permiso no falla, simplemente no borra: hay que detectarlo y explicarlo, no dejar que parezca un
  error.
- Los Macs destino no tienen Python ni Command Line Tools: el binario debe ser autocontenido y la
  instalación se hace en persona (incluye quitar la cuarentena si el archivo llegó por AirDrop o
  descarga).

### Convenciones de código

- Comentarios solo donde expliquen un *porqué* no evidente (una ruta rara de macOS, una decisión de
  seguridad). Nada de comentarios que repitan lo que el código ya dice.
- Textos de interfaz en español; identificadores de código en inglés.
- El motor no importa nada de la capa TUI: debe poder ejecutarse sin Textual.

---

## Arquitectura

- `smartcare/core/units.py` — formateo de bytes a unidades legibles.
- `smartcare/core/system.py` — sondas de solo lectura: versión de macOS, arquitectura, uso de disco,
  estadísticas de memoria. Sustituye a las llamadas a `sw_vers`, `df` y `vm_stat` del script.
- `smartcare/core/targets.py` — tipos de objetivo limpiable: contenido de directorio, comando externo
  (`brew cleanup`, `npm cache clean`…) y acción de sistema (`purge`, `tmutil`). Cada uno sabe medirse
  y limpiarse, y declara si necesita privilegios.
- `smartcare/core/catalog.py` — los 8 módulos y sus objetivos, como datos. Traslada íntegro el
  inventario de rutas del script actual, incluidas sus notas de seguridad, y lo amplía con los
  objetivos nuevos (contenedores sandbox, QuickLook, extras de Xcode, cachés Electron…) y la lista
  de exclusión de datos sincronizados y de recuperación.
- `smartcare/core/safety.py` — la primitiva de borrado y los seis invariantes. Separa el plan (qué
  se quitaría) de la ejecución, de modo que la simulación sea el mismo recorrido sin la mitad que
  escribe, y que haya un único punto del programa que toque el disco.
- `smartcare/core/privileges.py` — gestión de `sudo`: validación única por ejecución y refresco
  mientras duren las operaciones privilegiadas.
- `smartcare/core/permissions.py` — detección de Acceso Total al Disco.
- `smartcare/core/engine.py` — orquestación: análisis en paralelo, limpieza, progreso, cancelación,
  modo simulación.
- `smartcare/tui/app.py` — aplicación Textual: pantallas, eventos y presentación.
- `smartcare/cli.py` — punto de entrada. Sin argumentos abre la TUI; con flags corre en modo texto
  plano.
- `scripts/build_binary.py` — genera el binario autocontenido y el lanzador doble-clicable. (No se
  llama `packaging/` porque ese nombre eclipsaría a la librería `packaging` de PyPI, de la que
  dependen pytest y PyInstaller, en todo lo que se ejecute desde la raíz del repositorio.)
- `tests/` — pytest sobre el motor.

### Clasificación de riesgo (impulsa el UX)

Cada módulo se etiqueta como **seguro** (cachés regenerables), **con aviso** (Figma cierra sesión,
Safari requiere permisos) o **destructivo** (papelera permanente, `docker system prune`). Por defecto
solo se preseleccionan los seguros; los destructivos exigen confirmación explícita.

Tres mecanismos permiten limpiar más superficie sin aumentar el riesgo:

- **Staging en papelera**: los objetivos *con aviso* no se borran, se mueven a `~/.Trash` (mismo
  volumen, movimiento instantáneo). Siguen siendo recuperables hasta que la usuaria vacíe la
  papelera.
- **Filtro de antigüedad**: en cachés y logs solo se eliminan archivos con más de N días (7 por
  defecto). Las cachés "calientes" en uso se conservan; el volumen acumulado, que es donde está el
  espacio, se va.
- **Snapshot APFS previo**: antes de aplicar, `tmutil localsnapshot` crea un punto de restauración
  de coste casi nulo. Si el módulo de snapshots está seleccionado, el adelgazamiento posterior lo
  eliminará: es la elección explícita de la usuaria y se le indica.

### Invariantes de seguridad (verificados por tests)

1. En modo simulación no se escribe ni se borra nada.
2. Nunca se elimina el directorio padre, solo su contenido.
3. No se siguen enlaces simbólicos al borrar.
4. Toda ruta a borrar debe caer bajo una raíz permitida; cualquier otra se rechaza.
5. Las rutas de la lista de exclusión nunca se tocan, aunque caigan bajo una raíz permitida. La
   lista cubre dos categorías: **datos sincronizados**, cuyo borrado dispara re-sincronizaciones
   masivas (contenedores de iCloud: `com.apple.bird`, `com.apple.CloudDocs`, FileProvider; Adobe
   `CoreSync` y CC Libraries), y **datos de recuperación**, cuyo borrado pierde trabajo sin guardar
   (`InDesign Recovery`, que vive *dentro* de `~/Library/Caches/Adobe InDesign`). La exclusión debe
   respetarse también al barrer un directorio padre: si una entrada contiene una ruta excluida en su
   interior, el motor desciende y la conserva en vez de borrar la entrada completa.
6. En modo staging no se borra nada: solo se mueve a la papelera, dentro del mismo volumen.

---

## Fase 1 — Andamiaje del proyecto

**Explicación.** Dejar el repositorio listo para albergar un paquete Python sin tocar todavía el
script actual, que sigue siendo la referencia de comportamiento hasta la última fase.

**Tareas**

- [x] Crear el proyecto `uv` con `pyproject.toml`: dependencia `textual`, extra de desarrollo con
      `pytest`, `ruff` y `pyinstaller`, y el ejecutable `smartcare`.
- [x] Crear el árbol de paquetes `smartcare/core/`, `smartcare/tui/`, `tests/`, `scripts/`.
- [x] Ampliar el `.gitignore` con `dist/`, `build/` y `*.spec` de PyInstaller.
- [x] Configurar `ruff` en `pyproject.toml` con reglas de estilo y longitud de línea.
- [x] Comprobar que `uv sync` resuelve e instala en un entorno limpio.

**Ejecución.** Sin lógica de negocio todavía. Al terminar, `uv run python -c "import smartcare"`
debe funcionar.

**Code review.** Que `pyproject.toml` fije versiones mínimas coherentes, que el `.gitignore` no
excluya nada que deba versionarse y que la estructura no deje paquetes sin `__init__.py`.

**Commit:** `chore: scaffold Python package for the SmartCare TUI app`

---

## Fase 2 — Núcleo: modelo de objetivos y motor de limpieza

**Explicación.** El corazón del trabajo y la parte peligrosa: lo que mide tamaños y lo que borra
archivos. Se construye entero sin interfaz, para poder probarlo aislado. El motor expone progreso
mediante llamadas de retorno, de modo que luego sirva igual a la TUI y al modo texto plano.

**Tareas**

- [x] `units.py`: conversión de bytes a texto legible, equivalente a la función `human` del script.
- [x] `system.py`: versión de macOS, arquitectura, espacio libre en disco y estadísticas de memoria.
      La lectura de memoria debe deducir el tamaño de página en vez de asumirlo, como ya hace el
      script actual.
- [x] `targets.py`: los tres tipos de objetivo, cada uno con medición, limpieza y declaración de
      privilegios. Un objetivo ausente se marca como no aplicable en vez de fallar; un objetivo sin
      tamaño medible (comandos externos, snapshots, memoria) lo declara en vez de reportar cero.
- [x] `catalog.py`: trasladar los 8 módulos con todas sus rutas y notas, más la etiqueta de riesgo.
      Resolver los solapamientos entre módulos (las rutas de Yarn, Adobe, Sketch, CapCut y
      navegadores viven bajo `~/Library/Caches`, que ya cubre el módulo de cachés) para que la suma
      de módulos seleccionados no cuente nada dos veces.
- [x] `catalog.py`: añadir los objetivos nuevos, asignados a los módulos existentes para no cambiar
      los flags:
      - *Cachés*: contenedores sandbox (`~/Library/Containers/*/Data/Library/Caches` y
        `~/Library/Group Containers/*/Library/Caches` — el gran hueco del script actual, requiere
        Acceso Total al Disco), QuickLook (`qlmanage -r cache`), cachés de fuentes
        (`atsutil databases -remove`, sudo), `~/Library/Application Support/CrashReporter`, y con
        aviso: `~/Library/Saved Application State` (las apps olvidan sus ventanas abiertas).
      - *Cachés de apps Electron* (Miro, Notion, Zeplin, Framer…): **solo** las subcarpetas
        `Cache`, `Code Cache` y `GPUCache` bajo `~/Library/Application Support/<App>/`, enumeradas
        por nombre exacto. El resto del perfil (`Local Storage`, `IndexedDB`, sesión, datos) queda
        fuera del objetivo: contiene estado de la app y documentos sin sincronizar.
      - *Desarrollo*: extras de Xcode (`iOS Device Logs`, `watchOS DeviceSupport`,
        `xcrun simctl delete unavailable`), CocoaPods, Gradle, `uv cache clean`, cargo, y
        actualizaciones de iOS antiguas (`~/Library/iTunes/iPhone Software Updates`).
      - *Con aviso*: cachés de media de Telegram/Slack en Group Containers (se re-descargan).
- [x] Lista de exclusión en el catálogo (datos sincronizados: contenedores de iCloud, Adobe
      CoreSync y CC Libraries; datos de recuperación: `InDesign Recovery`), aplicada por el motor
      como invariante (nº 5), no como convención — incluido el descenso para conservar rutas
      excluidas dentro de un directorio que se barre.
- [x] Exclusiones documentadas (deliberadas, no objetivos): previsualizaciones de Lightroom
      (`*.lrdata`, junto al catálogo en Imágenes) — ocupan mucho pero regenerarlas cuesta horas;
      media de WhatsApp — no siempre re-descargable.
- [x] `engine.py`: análisis concurrente con progreso y cancelación; limpieza secuencial con progreso,
      registro por objetivo y recuento de errores; modo simulación como opción por defecto.
- [x] `engine.py`: staging en papelera para los objetivos con aviso — mover a `~/.Trash` con nombre
      no colisionante en lugar de borrar; si la ruta está en otro volumen o el movimiento falla, se
      degrada a "omitido", nunca a borrado directo.
- [x] `engine.py`: filtro de antigüedad (mtime > N días, 7 por defecto) aplicable por objetivo;
      activo en cachés y logs, sin efecto en papelera y comandos externos.
- [x] `engine.py`: snapshot APFS previo (`tmutil localsnapshot`) al comenzar una limpieza real; su
      fallo se reporta pero no bloquea (puede no haber Time Machine configurado).
- [x] Implementar los seis invariantes de seguridad en el borrado (en `safety.py`).
- [x] Tests: cobertura de los seis invariantes, del cálculo de tamaños, del filtro de antigüedad
      (límites de fecha), del staging (colisiones de nombre, otro volumen) y del comportamiento con
      rutas inexistentes, sin permisos y con enlaces simbólicos. Para la exclusión: un árbol
      simulado con `InDesign Recovery` dentro de la caché debe sobrevivir al barrido del padre.
      Para Electron: nada fuera de `Cache`, `Code Cache` y `GPUCache` se toca.

**Ejecución.** Desarrollo guiado por los tests, sobre directorios temporales. Nada toca el disco real
del usuario en esta fase.

**Code review.** Foco en la ruta de borrado: revisar la validación de raíces permitidas, el manejo de
enlaces simbólicos y que la simulación no tenga ningún camino que escriba. Verificar que los
cancelados dejan el sistema en estado coherente y que los errores por permisos se registran sin
abortar el resto.

**Commit:** `feat: add cleanup engine with target catalog and safety invariants`

---

## Fase 3 — Privilegios y permisos del sistema

**Explicación.** En una TUI, `sudo` funciona de forma nativa, pero con dos matices: no se puede
pedir la contraseña una vez por comando (hay que validar una sola vez y refrescar), y el prompt de
`sudo` no puede pintarse encima de la pantalla alternativa de Textual sin corromperla. El segundo
problema es Acceso Total al Disco: sin él la app no puede tocar buena parte de lo que promete
limpiar, y el fallo es silencioso.

**Tareas**

- [ ] `privileges.py`: validación única de `sudo` al comenzar una limpieza que incluya operaciones
      privilegiadas, con refresco periódico mientras duren.
- [ ] Exponer la lista literal de operaciones que se ejecutarán como administrador, para poder
      mostrarla antes de pedir la contraseña.
- [ ] Contrato de suspensión: el motor avisa a la interfaz antes de pedir la contraseña, para que la
      TUI se suspenda durante el prompt y se redibuje al volver.
- [ ] Distinguir cancelación por parte del usuario (Ctrl-C en el prompt) de fallo real, y no tratar
      la primera como error.
- [ ] `permissions.py`: detectar si el proceso tiene Acceso Total al Disco mediante un sondeo de
      lectura sobre una ruta protegida conocida.
- [ ] Ofrecer la apertura directa del panel de Ajustes correspondiente.
- [ ] Tests del ensamblado de la orden privilegiada y del escapado de rutas con espacios y comillas.

**Ejecución.** La prueba manual de la elevación se hace sobre un objetivo inocuo antes de conectarla
a los módulos reales.

**Code review.** Es la fase de mayor riesgo de seguridad. Revisar en detalle el escapado de cualquier
ruta que acabe en una orden elevada, confirmar que no se construyen órdenes con datos no saneados y
que ninguna contraseña pasa por el proceso ni queda en registros. Comprobar que la detección de
permisos no da falsos positivos.

**Commit:** `feat: add privileged execution and Full Disk Access detection`

---

## Fase 4 — Modo texto plano y paridad con el script

**Explicación.** Antes de construir la TUI, se cierra el círculo funcional: una entrada por línea de
órdenes con los mismos flags que el script actual. Sirve como red de seguridad (permite comparar
resultados con el `.sh` original) y cubre el uso en scripts que la decisión de arranque exige
mantener.

**Tareas**

- [ ] `cli.py`: soporte de `--apply`, `--dry-run`, `--yes` y los ocho flags de módulo, con la misma
      semántica que hoy (sin flags de módulo, se ejecutan todos).
- [ ] Salida de texto con colores, agrupada por módulo y con resumen final, comparable a la actual.
- [ ] Confirmaciones interactivas para lo destructivo, omitidas con `--yes`.
- [ ] Sin argumentos, abrir la TUI; añadir un flag explícito para forzar el modo texto plano.
- [ ] Código de salida distinto de cero si hubo errores, para que sea usable en automatizaciones.

**Ejecución.** Ejecutar en simulación el `.sh` original y la nueva orden sobre la misma máquina y
comparar módulo a módulo los tamaños reportados.

**Code review.** Verificar la paridad de flags frente al bloque de parseo del script actual, que las
diferencias de tamaño respecto al original estén justificadas, y que la capa de terminal no duplique
lógica que ya vive en el motor.

**Commit:** `feat: add plain-text mode with parity to the shell script`

---

## Fase 5 — Interfaz TUI

**Explicación.** La fase que justifica la migración. El recorrido es: al abrir, la app analiza sola
y enseña qué ocupa cada módulo; la usuaria marca lo que quiere; ve cuánto va a liberar antes de
decidir; limpia con progreso real y termina con un resumen. La simulación es el modo por defecto.
El análisis y la limpieza corren en workers de Textual, fuera del bucle de la interfaz, para que la
pantalla nunca se congele.

**Tareas**

- [ ] Estructura de la pantalla: cabecera con datos del sistema y uso de disco, lista de módulos,
      pie con total seleccionado y acción principal.
- [ ] Análisis automático al abrir, con progreso y opción de cancelar.
- [ ] Lista de módulos con casilla, nombre, tamaño y distintivo de riesgo; desplegable para ver los
      objetivos concretos y sus rutas, conservando la transparencia del script actual. Los objetivos
      sin tamaño medible muestran su condición en lugar de un cero.
- [ ] Preselección solo de los módulos seguros.
- [ ] Selector de modo simulación / aplicar, con la diferencia siempre visible y sin ambigüedad.
- [ ] Confirmaciones modales para lo destructivo, indicando qué es irreversible.
- [ ] Pantalla de limpieza con progreso, elemento en curso y registro en vivo; suspensión y
      redibujado limpios cuando `sudo` pide contraseña.
- [ ] Resumen final con espacio liberado, disco antes y después, y detalle de errores si los hubo.
      Distinguir lo borrado de lo movido a la papelera: lo segundo no libera espacio hasta vaciarla,
      y el total debe reflejarlo sin ambigüedad.
- [ ] Estados vacíos y de error: objetivos no aplicables agrupados y ocultos por defecto, aviso
      accionable cuando falte Acceso Total al Disco, aviso de cierre de sesión en Figma.
- [ ] Manejo del cierre (Ctrl-C o cerrar la ventana de Terminal) durante una operación en curso sin
      dejar procesos huérfanos.
- [ ] Usable con el tamaño por defecto de Terminal (80×24) y con redimensionado en caliente; tema
      claro y oscuro según el terminal, con contraste suficiente.
- [ ] Navegación completa por teclado (con atajos visibles en pantalla) y soporte de ratón.

**Ejecución.** Iterar con la app abierta en modo simulación, que no toca nada, hasta que el recorrido
completo se sienta bien.

**Code review.** Comprobar que la interfaz no reimplementa reglas de negocio del motor, que todo
estado largo tiene indicador de progreso, que el modo aplicar nunca puede confundirse con la
simulación, y que la pantalla sobrevive a redimensionados y al ciclo suspender/redibujar de `sudo`.

**Commit:** `feat: build the SmartCare TUI`

---

## Fase 6 — Binario autocontenido y lanzador de doble clic

**Explicación.** La mitad de la decisión de arranque que falta: que dos personas sin Python ni
conocimientos técnicos lo abran con un clic. El binario incluye el intérprete y todas las
dependencias; el lanzador abre Terminal y lo ejecuta.

**Tareas**

- [ ] `scripts/build_binary.py`: generar con PyInstaller un binario único que arranque la TUI.
- [ ] Lanzador `SmartCare.command` doble-clicable que ejecuta el binario, sin depender de rutas de
      la máquina de desarrollo.
- [ ] Envoltorio `.app` mínimo con icono propio para el Dock, que abra el lanzador en Terminal.
- [ ] Guion de instalación en persona: copiar a la máquina destino, quitar la cuarentena, conceder
      Acceso Total al Disco a Terminal, y recorrer el flujo en simulación.
- [ ] Probar el binario en una cuenta de usuario limpia, sin el entorno de desarrollo.
- [ ] Verificar que el arranque falla con un mensaje comprensible si algo falta.

**Ejecución.** Construir, instalar como si fuera la máquina de una usuaria final y recorrer el flujo
completo en simulación.

**Code review.** Verificar que el binario y el lanzador no dependen de rutas absolutas de la máquina
de desarrollo, que el `.command` no hace nada más que lanzar, y que el guion de instalación es
completo y reproducible.

**Commit:** `feat: package SmartCare as a self-contained double-clickable binary`

---

## Fase 7 — Retirada del script y documentación

**Explicación.** Cerrar la migración: el `.sh` desaparece solo ahora, cuando su comportamiento está
cubierto y verificado, y el README pasa a describir la aplicación.

**Tareas**

- [ ] Verificación final de paridad módulo a módulo contra el script antes de borrarlo.
- [ ] Eliminar `smartcare.sh`.
- [ ] Reescribir `README.md`: qué es, instalación (incluido el guion de instalación en persona), las
      dos formas de arranque, los módulos, y las advertencias de seguridad que ya tiene hoy, que
      siguen siendo válidas.
- [ ] Documentar los requisitos de permisos de macOS, incluida la nota de Safari que ya existe.
- [ ] Documentar las exclusiones deliberadas (previsualizaciones de Lightroom, media de WhatsApp,
      datos de recuperación y sincronizados) para que no parezcan olvidos.
- [ ] Añadir capturas de la TUI.
- [ ] Revisar que `LICENSE` y la advertencia de responsabilidad se mantienen.

**Ejecución.** El borrado del script es el último paso, después de la verificación.

**Code review.** Leer el README como quien no conoce el proyecto: comprobar que no quedan referencias
a `smartcare.sh` ni instrucciones obsoletas, y que las advertencias de seguridad no se han diluido.

**Commit:** `refactor: replace the shell script with the SmartCare app`

---

## Verificación

**Automática.** `uv run pytest` cubre el motor: los cuatro invariantes de seguridad, el cálculo de
tamaños y el manejo de rutas ausentes, sin permisos o con enlaces simbólicos.

**Paridad con el script.** Antes de borrarlo, ejecutar el `.sh` original y la nueva herramienta en
simulación sobre la misma máquina y comparar los tamaños módulo a módulo. Cualquier diferencia debe
tener explicación (la deduplicación de rutas solapadas y los objetivos nuevos que el script no
cubría —contenedores sandbox, QuickLook, extras de Xcode…— son diferencias esperadas y
documentadas).

**Manual, en simulación.** Recorrido completo con la TUI abierta: que el análisis muestre progreso y
se pueda cancelar; que los tamaños coincidan con los del modo texto; que los módulos ausentes no
ensucien la lista; que lo destructivo pida confirmación; que el resumen cuadre.

**Manual, aplicando de verdad.** Empezar por un módulo seguro y pequeño, comprobando el espacio libre
en disco antes y después. Solo después probar un módulo con privilegios, verificando que la
contraseña se pide una sola vez y que la pantalla se redibuja bien tras el prompt. La papelera se
prueba la última, con contenido de usar y tirar.

**Permisos.** Probar sin Acceso Total al Disco y confirmar que avisa de forma accionable en lugar de
fallar en silencio; concederlo a Terminal y confirmar que entonces sí limpia.

**Distribución.** Probar el binario y el lanzador en una cuenta limpia sin entorno de desarrollo,
siguiendo el guion de instalación paso a paso.
