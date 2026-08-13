"""Borrado seguro: el único punto del programa que escribe en disco.

La operación se parte en dos mitades deliberadamente:

- `plan()` recorre el árbol y decide qué se quitaría. No escribe nada.
- `execute()` recibe ese plan y lo lleva a cabo.

La simulación es exactamente el mismo recorrido sin la segunda mitad, así que
no puede divergir de lo que hace la limpieza real ni reportar cifras distintas.
"""

import os
import shutil
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_SECONDS_PER_DAY = 86400


class Action(Enum):
    DELETE = "delete"
    STAGE = "stage"
    PRESERVE = "preserve"


class SafetyError(Exception):
    """Una ruta no cumple los invariantes y se rechaza sin tocarla."""


@dataclass(frozen=True)
class DeletionPolicy:
    allowed_roots: tuple[Path, ...]
    excluded: tuple[Path, ...] = ()
    min_age_days: int | None = None
    stage_in_trash: bool = False
    trash: Path | None = None

    def trash_dir(self) -> Path:
        return self.trash if self.trash is not None else Path.home() / ".Trash"


@dataclass(frozen=True)
class PlannedRemoval:
    path: Path
    size: int
    action: Action
    is_symlink: bool = False


@dataclass
class RemovalReport:
    deleted: int = 0
    staged: int = 0
    preserved: list[Path] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def plan(
    directory: Path, policy: DeletionPolicy, *, now: float | None = None
) -> Iterator[PlannedRemoval]:
    """Enumera lo que se quitaría del contenido de `directory`.

    La validación de la raíz es inmediata, no diferida al primer `next()`: una
    ruta fuera de las raíces permitidas debe fallar al pedir el plan, no a mitad
    de recorrerlo.
    """
    root = _validated_root(directory, policy)
    if root is None:
        return iter(())
    cutoff = None
    if policy.min_age_days is not None:
        cutoff = (time.time() if now is None else now) - policy.min_age_days * _SECONDS_PER_DAY
    return _plan_entries(root, policy, cutoff)


def measure(directory: Path, policy: DeletionPolicy, *, now: float | None = None) -> int:
    return sum(
        item.size for item in plan(directory, policy, now=now) if item.action is not Action.PRESERVE
    )


def directory_size(path: Path) -> int:
    """Tamaño de un directorio que no vamos a borrar nosotros.

    No pasa por las raíces permitidas a propósito: esa comprobación protege la
    ruta de borrado, y esto es una lectura. Sirve para enseñar el tamaño de
    cachés que limpia su propia herramienta (`npm cache clean`, `brew cleanup`),
    que viven donde cada máquina las tenga configuradas.
    """
    expanded = path.expanduser()
    return _tree_size(expanded) if expanded.is_dir() else 0


def execute(removals: Iterable[PlannedRemoval], policy: DeletionPolicy) -> RemovalReport:
    report = RemovalReport()
    roots = _resolved_roots(policy)
    for item in removals:
        if item.action is Action.PRESERVE:
            report.preserved.append(item.path)
            continue
        # Segunda comprobación en el borde de escritura: el plan pudo construirse
        # en otro sitio, y esta es la última línea antes de tocar el disco.
        if not _under_allowed_root(item.path, roots):
            raise SafetyError(f"ruta fuera de las raíces permitidas: {item.path}")
        try:
            if item.action is Action.STAGE:
                _stage(item, policy, report)
            else:
                _remove(item.path)
                report.deleted += item.size
        except OSError as error:
            report.errors.append((item.path, str(error)))
    return report


def _validated_root(directory: Path, policy: DeletionPolicy) -> Path | None:
    absolute = directory.expanduser().resolve()
    if not _under_allowed_root(absolute, _resolved_roots(policy)):
        raise SafetyError(f"ruta fuera de las raíces permitidas: {directory}")
    if not absolute.is_dir():
        return None
    return absolute


def _resolved_roots(policy: DeletionPolicy) -> tuple[Path, ...]:
    """Las raíces se comparan resueltas, como la ruta a barrer.

    De lo contrario un home detrás de un enlace simbólico haría fallar la
    comparación y rechazaría rutas legítimas. Se calcula una vez por operación,
    no una vez por archivo.
    """
    return tuple(root.expanduser().resolve() for root in policy.allowed_roots)


def _under_allowed_root(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _plan_entries(
    directory: Path, policy: DeletionPolicy, cutoff: float | None
) -> Iterator[PlannedRemoval]:
    action = Action.STAGE if policy.stage_in_trash else Action.DELETE
    for entry in _scandir(directory):
        path = Path(entry.path)

        if _is_excluded(path, policy.excluded):
            yield PlannedRemoval(path, 0, Action.PRESERVE)
            continue

        try:
            is_symlink = entry.is_symlink()
            is_directory = entry.is_dir(follow_symlinks=False)
            stats = entry.stat(follow_symlinks=False)
        except OSError:
            continue

        if is_directory:
            # Descender cuesta más que borrar el árbol entero de una vez, así que
            # solo se hace cuando hay algo dentro que preservar o fechas que mirar.
            if cutoff is not None or _contains_excluded(path, policy.excluded):
                yield from _plan_entries(path, policy, cutoff)
            else:
                yield PlannedRemoval(path, _tree_size(path), action)
            continue

        if cutoff is not None and stats.st_mtime >= cutoff:
            continue
        yield PlannedRemoval(path, _disk_size(stats), action, is_symlink)


def _is_excluded(path: Path, excluded: Iterable[Path]) -> bool:
    return any(path == item or path.is_relative_to(item) for item in excluded)


def _contains_excluded(path: Path, excluded: Iterable[Path]) -> bool:
    return any(item.is_relative_to(path) for item in excluded)


def _scandir(directory: Path) -> Iterator[os.DirEntry]:
    try:
        with os.scandir(directory) as entries:
            yield from list(entries)
    except OSError:
        return


def _tree_size(path: Path) -> int:
    total = 0
    for entry in _scandir(path):
        try:
            stats = entry.stat(follow_symlinks=False)
            total += _disk_size(stats)
            if entry.is_dir(follow_symlinks=False):
                total += _tree_size(Path(entry.path))
        except OSError:
            continue
    return total


def _disk_size(stats: os.stat_result) -> int:
    """Bytes ocupados en disco, no tamaño aparente.

    Son los bloques reservados los que se recuperan al borrar, y por tanto lo
    que se verá reflejado en el espacio libre.
    """
    return stats.st_blocks * 512


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return
    shutil.rmtree(path)


def _stage(item: PlannedRemoval, policy: DeletionPolicy, report: RemovalReport) -> None:
    trash = policy.trash_dir()
    if not trash.is_dir():
        report.skipped.append((item.path, "no hay papelera donde mover"))
        return
    destination = _non_colliding(trash / item.path.name)
    try:
        # rename, no shutil.move: entre volúmenes falla con EXDEV en vez de
        # copiar y borrar. En modo staging nada puede acabar borrándose.
        item.path.rename(destination)
    except OSError as error:
        report.skipped.append((item.path, f"no se pudo mover a la papelera: {error}"))
        return
    report.staged += item.size


def _non_colliding(destination: Path) -> Path:
    if not destination.exists():
        return destination
    for index in range(2, 1000):
        candidate = destination.with_name(f"{destination.name} {index}")
        if not candidate.exists():
            return candidate
    raise OSError(f"demasiadas colisiones de nombre en la papelera para {destination.name}")
