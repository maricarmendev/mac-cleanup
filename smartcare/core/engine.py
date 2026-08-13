"""Orquestación: qué se analiza, qué se limpia, en qué orden y con qué política.

El motor no sabe borrar (eso es `safety`) ni qué hay que borrar (eso es
`catalog`). Decide qué objetivos entran, construye su política y reporta
progreso mediante llamadas de retorno, de modo que sirva igual a la interfaz de
terminal y al modo texto plano.
"""

import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace

from smartcare.core import catalog, system
from smartcare.core.catalog import DEFAULT_MIN_AGE_DAYS, Module, Target
from smartcare.core.safety import DeletionPolicy
from smartcare.core.system import DiskUsage
from smartcare.core.targets import (
    CleanOutcome,
    CommandRunner,
    CommandTarget,
    DirectoryTarget,
    Measurement,
    Risk,
    TargetState,
    run_command,
)

_MAX_WORKERS = 8


@dataclass(frozen=True)
class Progress:
    done: int
    total: int
    label: str


ProgressCallback = Callable[[Progress], None] | None


@dataclass(frozen=True)
class Options:
    dry_run: bool = True
    min_age_days: int = DEFAULT_MIN_AGE_DAYS
    take_snapshot: bool = True
    confirmed: frozenset[str] = frozenset()

    def allows(self, target: Target) -> bool:
        """Lo destructivo solo entra si se ha confirmado por su nombre."""
        return target.risk is not Risk.DESTRUCTIVE or target.key in self.confirmed


DEFAULT_OPTIONS = Options()


@dataclass(frozen=True)
class TargetAnalysis:
    module_key: str
    target: Target
    measurement: Measurement


@dataclass
class Analysis:
    entries: list[TargetAnalysis] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total(self) -> int:
        return sum(e.measurement.size for e in self.entries if e.measurement.counts_towards_total)

    def total_for(self, module_key: str) -> int:
        return sum(
            e.measurement.size
            for e in self.entries
            if e.module_key == module_key and e.measurement.counts_towards_total
        )

    def not_applicable(self) -> list[TargetAnalysis]:
        return [e for e in self.entries if e.measurement.state is TargetState.NOT_APPLICABLE]


@dataclass(frozen=True)
class TargetResult:
    module_key: str
    target: Target
    outcome: CleanOutcome


@dataclass
class CleanReport:
    results: list[TargetResult] = field(default_factory=list)
    disk_before: DiskUsage | None = None
    disk_after: DiskUsage | None = None
    snapshot_taken: bool = False
    snapshot_detail: str = ""
    cancelled: bool = False

    @property
    def freed(self) -> int:
        return sum(r.outcome.freed for r in self.results)

    @property
    def staged(self) -> int:
        """Bytes movidos a la papelera: aún no liberan espacio."""
        return sum(r.outcome.staged for r in self.results)

    @property
    def errors(self) -> list[tuple[str, str]]:
        return [(r.target.key, str(detail)) for r in self.results for _, detail in r.outcome.errors]


def analyze(
    modules: Sequence[Module],
    options: Options = DEFAULT_OPTIONS,
    *,
    progress: ProgressCallback = None,
    cancel: threading.Event | None = None,
    runner: CommandRunner = run_command,
) -> Analysis:
    """Mide en paralelo. Nada de esto escribe en disco."""
    jobs = list(_selected_targets(modules, options))
    policies = _policies_for(jobs, options)
    analysis = Analysis()
    if not jobs:
        return analysis

    cancelled = _cancellation(cancel)
    done = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_measure, target, policies.get(target.key), cancelled, runner): (
                module_key,
                target,
            )
            for module_key, target in jobs
        }
        for future in as_completed(futures):
            module_key, target = futures[future]
            analysis.entries.append(TargetAnalysis(module_key, target, future.result()))
            done += 1
            _report(progress, done, len(jobs), target.label)

    analysis.cancelled = cancelled()
    analysis.entries.sort(key=lambda e: (e.module_key, e.target.key))
    return analysis


def clean(
    modules: Sequence[Module],
    options: Options = DEFAULT_OPTIONS,
    *,
    progress: ProgressCallback = None,
    cancel: threading.Event | None = None,
    runner: CommandRunner = run_command,
) -> CleanReport:
    """Limpia en secuencia. Un fallo en un objetivo no detiene los demás."""
    jobs = list(_selected_targets(modules, options))
    policies = _policies_for(jobs, options)
    report = CleanReport(disk_before=system.disk_usage("/"))
    cancelled = _cancellation(cancel)

    if not options.dry_run:
        _take_snapshot(report, options, runner)

    for index, (module_key, target) in enumerate(jobs, start=1):
        if cancelled():
            report.cancelled = True
            break
        outcome = _clean_one(target, policies.get(target.key), options, cancelled, runner)
        report.results.append(TargetResult(module_key, target, outcome))
        _report(progress, index, len(jobs), target.label)

    if not options.dry_run:
        report.disk_after = system.disk_usage("/")
    return report


def privileged_operations(
    modules: Sequence[Module], options: Options = DEFAULT_OPTIONS
) -> list[Target]:
    """Lo que se ejecutará como administrador, para poder enseñarlo antes de pedir la clave."""
    return [
        target for _, target in _selected_targets(modules, options) if target.requires_privileges
    ]


def _selected_targets(modules: Iterable[Module], options: Options) -> Iterable[tuple[str, Target]]:
    for module in modules:
        for target in module.targets:
            if options.allows(target):
                yield module.key, target


def _policies_for(
    jobs: Sequence[tuple[str, Target]], options: Options
) -> dict[str, DeletionPolicy]:
    """Una política por objetivo de directorio, con sus recortes por solapamiento."""
    directories = [target for _, target in jobs if isinstance(target, DirectoryTarget)]
    recortes = catalog.carve_outs(directories)
    base = DeletionPolicy(
        allowed_roots=catalog.allowed_roots(),
        excluded=catalog.excluded_paths(),
        min_age_days=options.min_age_days,
    )
    return {
        target.key: replace(base, excluded=base.excluded + recortes.get(target.key, ()))
        for target in directories
    }


def _measure(
    target: Target,
    policy: DeletionPolicy | None,
    cancelled: Callable[[], bool],
    runner: CommandRunner,
) -> Measurement:
    if isinstance(target, DirectoryTarget):
        return target.measure(policy, cancelled)
    if isinstance(target, CommandTarget):
        return target.measure(runner)
    return target.measure()


def _clean_one(
    target: Target,
    policy: DeletionPolicy | None,
    options: Options,
    cancelled: Callable[[], bool],
    runner: CommandRunner,
) -> CleanOutcome:
    if isinstance(target, DirectoryTarget):
        return target.clean(policy, dry_run=options.dry_run, cancelled=cancelled)
    return target.clean(dry_run=options.dry_run, runner=runner)


def _take_snapshot(report: CleanReport, options: Options, runner: CommandRunner) -> None:
    """Punto de restauración APFS antes de tocar nada.

    Su coste es casi nulo y su fallo no puede impedir la limpieza: puede
    perfectamente no haber Time Machine configurada en esta máquina.
    """
    if not options.take_snapshot:
        return
    result = runner(("tmutil", "localsnapshot"))
    report.snapshot_taken = result.ok
    report.snapshot_detail = result.output


def _cancellation(cancel: threading.Event | None) -> Callable[[], bool]:
    if cancel is None:
        return lambda: False
    return cancel.is_set


def _report(progress: ProgressCallback, done: int, total: int, label: str) -> None:
    if progress is not None:
        progress(Progress(done=done, total=total, label=label))


__all__ = [
    "Analysis",
    "CleanReport",
    "Options",
    "Progress",
    "TargetAnalysis",
    "TargetResult",
    "analyze",
    "clean",
    "privileged_operations",
]
