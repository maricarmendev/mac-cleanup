"""Los tipos de objetivo limpiable.

Cada uno sabe medirse y limpiarse, y declara si necesita privilegios. La
diferencia que justifica que sean tipos distintos es la medición: un directorio
se mide sumando bytes, un comando externo no se puede medir hasta ejecutarlo, y
una acción de sistema puede no liberar disco en absoluto.
"""

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from smartcare.core.safety import (
    Action,
    DeletionPolicy,
    RemovalReport,
    directory_size,
    execute,
    measure,
    plan,
)

_COMMAND_TIMEOUT = 900


class TargetState(Enum):
    READY = "ready"
    NOT_APPLICABLE = "not_applicable"
    NOT_MEASURABLE = "not_measurable"


class Risk(Enum):
    """Impulsa el UX: qué se preselecciona y qué exige confirmación explícita."""

    SAFE = "seguro"
    WARNING = "con aviso"
    DESTRUCTIVE = "destructivo"


@dataclass(frozen=True)
class Measurement:
    state: TargetState
    size: int = 0
    detail: str = ""

    @property
    def counts_towards_total(self) -> bool:
        return self.state is TargetState.READY


@dataclass
class CleanOutcome:
    freed: int = 0
    staged: int = 0
    performed: bool = False
    detail: str = ""
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    output: str = ""


CommandRunner = Callable[[Sequence[str]], CommandResult]
Cancellation = Callable[[], bool] | None


def run_command(command: Sequence[str]) -> CommandResult:
    try:
        result = subprocess.run(
            list(command), capture_output=True, text=True, timeout=_COMMAND_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        return CommandResult(ok=False, output=str(error))
    salida = (result.stdout + result.stderr).strip()
    return CommandResult(ok=result.returncode == 0, output=salida)


@dataclass(frozen=True)
class DirectoryTarget:
    """El contenido de un directorio. Nunca el directorio en sí."""

    key: str
    label: str
    path: str
    requires_privileges: bool = False
    stage_in_trash: bool = False
    age_filtered: bool = False
    risk: Risk = Risk.SAFE
    note: str = ""

    def resolved_paths(self) -> list[Path]:
        """Expande `~` y comodines.

        Rutas como `~/Library/Containers/*/Data/Library/Caches` designan un
        objetivo por aplicación instalada, así que un objetivo del catálogo
        puede corresponder a decenas de directorios reales o a ninguno.
        """
        expanded = Path(self.path).expanduser()
        if "*" not in self.path and "?" not in self.path:
            return [expanded] if expanded.is_dir() else []
        anchor = Path(expanded.anchor)
        pattern = str(expanded.relative_to(anchor))
        return sorted(match for match in anchor.glob(pattern) if match.is_dir())

    def measure(self, policy: DeletionPolicy, cancelled: Cancellation = None) -> Measurement:
        directories = self.resolved_paths()
        if not directories:
            return Measurement(TargetState.NOT_APPLICABLE, detail="no existe en esta máquina")
        effective = self.policy_from(policy)
        total = 0
        for directory in directories:
            # Un solo objetivo puede expandirse a cientos de directorios, así que
            # la cancelación se atiende aquí dentro y no solo entre objetivos.
            if cancelled is not None and cancelled():
                break
            total += measure(directory, effective)
        return Measurement(TargetState.READY, size=total)

    def clean(
        self, policy: DeletionPolicy, *, dry_run: bool, cancelled: Cancellation = None
    ) -> CleanOutcome:
        directories = self.resolved_paths()
        if not directories:
            return CleanOutcome(detail="no existe en esta máquina")

        effective = self.policy_from(policy)
        outcome = CleanOutcome(performed=not dry_run)
        for directory in directories:
            if cancelled is not None and cancelled():
                break
            removals = plan(directory, effective)
            if dry_run:
                outcome.freed += sum(
                    item.size for item in removals if item.action is not Action.PRESERVE
                )
                continue
            self._absorb(execute(removals, effective), outcome)
        return outcome

    def policy_from(self, base: DeletionPolicy) -> DeletionPolicy:
        return replace(
            base,
            min_age_days=base.min_age_days if self.age_filtered else None,
            stage_in_trash=self.stage_in_trash,
        )

    @staticmethod
    def _absorb(report: RemovalReport, outcome: CleanOutcome) -> None:
        outcome.freed += report.deleted
        outcome.staged += report.staged
        outcome.skipped.extend(report.skipped)
        outcome.errors.extend(report.errors)


@dataclass(frozen=True)
class CommandTarget:
    """Un comando externo que limpia lo suyo: `brew cleanup`, `npm cache clean`…"""

    key: str
    label: str
    command: tuple[str, ...]
    probe: str = ""
    readiness: tuple[str, ...] = ()
    size_from: tuple[str, ...] = ()
    requires_privileges: bool = False
    risk: Risk = Risk.SAFE
    note: str = ""

    def is_available(self, runner: CommandRunner = run_command) -> bool:
        if self.probe and shutil.which(self.probe) is None:
            return False
        if self.readiness:
            return runner(self.readiness).ok
        return True

    def measure(self, runner: CommandRunner = run_command) -> Measurement:
        if not self.is_available(runner):
            return Measurement(TargetState.NOT_APPLICABLE, detail="no está instalado")
        cache = self.cache_path(runner)
        if cache is None:
            return Measurement(TargetState.NOT_MEASURABLE, detail="se sabrá al ejecutar el comando")
        return Measurement(
            TargetState.NOT_MEASURABLE,
            size=directory_size(cache),
            detail=f"tamaño de {cache}; lo que libere el comando puede diferir",
        )

    def cache_path(self, runner: CommandRunner = run_command) -> Path | None:
        """Ubicación de la caché, si el propio comando sabe decirla.

        Se pregunta en vez de codificarla: `npm config get cache` y
        `brew --cache` respetan la configuración de cada máquina.
        """
        if not self.size_from:
            return None
        result = runner(self.size_from)
        if not result.ok or not result.output:
            return None
        cache = Path(result.output.splitlines()[0].strip()).expanduser()
        return cache if cache.is_dir() else None

    def clean(self, *, dry_run: bool, runner: CommandRunner = run_command) -> CleanOutcome:
        if not self.is_available(runner):
            return CleanOutcome(detail="no está instalado")
        if dry_run:
            return CleanOutcome(detail=f"ejecutaría: {' '.join(self.command)}")
        result = runner(self.command)
        if not result.ok:
            return CleanOutcome(
                performed=True,
                detail=f"falló: {result.output}",
                errors=[(Path(self.command[0]), result.output)],
            )
        return CleanOutcome(performed=True, detail=result.output)


@dataclass(frozen=True)
class SystemActionTarget:
    """Una acción del sistema cuyo efecto no es liberar bytes medibles."""

    key: str
    label: str
    command: tuple[str, ...]
    effect: str
    requires_privileges: bool = True
    risk: Risk = Risk.SAFE
    note: str = ""

    def measure(self) -> Measurement:
        return Measurement(TargetState.NOT_MEASURABLE, detail=self.effect)

    def clean(self, *, dry_run: bool, runner: CommandRunner = run_command) -> CleanOutcome:
        if dry_run:
            return CleanOutcome(detail=f"ejecutaría: {' '.join(self.command)}")
        result = runner(self.command)
        if not result.ok:
            return CleanOutcome(
                performed=True,
                detail=f"falló: {result.output}",
                errors=[(Path(self.command[0]), result.output)],
            )
        return CleanOutcome(performed=True, detail=self.effect)
