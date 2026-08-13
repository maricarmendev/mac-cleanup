"""Los tres tipos de objetivo."""

from pathlib import Path

import pytest

from smartcare.core.safety import DeletionPolicy
from smartcare.core.targets import (
    CommandResult,
    CommandTarget,
    DirectoryTarget,
    Measurement,
    SystemActionTarget,
    TargetState,
)


class RunnerFalso:
    """Registra lo que se le pide y devuelve lo que le digan, sin ejecutar nada."""

    def __init__(self, respuestas: dict[str, CommandResult] | None = None):
        self.llamadas: list[tuple[str, ...]] = []
        self.respuestas = respuestas or {}

    def __call__(self, command) -> CommandResult:
        clave = " ".join(command)
        self.llamadas.append(tuple(command))
        return self.respuestas.get(clave, CommandResult(ok=True, output=""))


@pytest.fixture
def policy(tmp_path: Path) -> DeletionPolicy:
    return DeletionPolicy(allowed_roots=(tmp_path.resolve(),))


# --- DirectoryTarget ----------------------------------------------------------


def test_a_missing_directory_is_not_applicable(tmp_path, policy):
    objetivo = DirectoryTarget("x", "No existe", str(tmp_path / "fantasma"))
    medida = objetivo.measure(policy)

    assert medida.state is TargetState.NOT_APPLICABLE
    assert medida.detail
    assert not medida.counts_towards_total


def test_a_wildcard_path_expands_to_every_match(tmp_path, policy):
    for app in ("com.una.App", "com.otra.App"):
        (tmp_path / "Containers" / app / "Data" / "Library" / "Caches").mkdir(parents=True)
        (tmp_path / "Containers" / app / "Data" / "Library" / "Caches" / "c.bin").write_bytes(
            b"x" * 1024
        )
    (tmp_path / "Containers" / "sin-caches").mkdir()

    objetivo = DirectoryTarget(
        "sandbox", "Contenedores", str(tmp_path / "Containers/*/Data/Library/Caches")
    )
    assert len(objetivo.resolved_paths()) == 2
    assert objetivo.measure(policy).size >= 2048


def test_a_wildcard_that_matches_nothing_is_not_applicable(tmp_path, policy):
    objetivo = DirectoryTarget("x", "Nada", str(tmp_path / "Containers/*/Caches"))
    assert objetivo.measure(policy).state is TargetState.NOT_APPLICABLE


def test_simulating_reports_the_same_bytes_it_would_free(tmp_path, policy):
    caches = tmp_path / "Caches"
    caches.mkdir()
    (caches / "a.bin").write_bytes(b"x" * 8192)
    objetivo = DirectoryTarget("c", "Cachés", str(caches))

    simulado = objetivo.clean(policy, dry_run=True)
    assert (caches / "a.bin").exists(), "la simulación no puede tocar nada"

    real = objetivo.clean(policy, dry_run=False)
    assert simulado.freed == real.freed
    assert not simulado.performed
    assert real.performed


def test_the_age_filter_only_applies_to_targets_that_declare_it(tmp_path):
    caches = tmp_path / "Caches"
    caches.mkdir()
    (caches / "reciente.bin").write_bytes(b"x" * 1024)
    base = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), min_age_days=7)

    con_filtro = DirectoryTarget("c", "Con filtro", str(caches), age_filtered=True)
    sin_filtro = DirectoryTarget("t", "Sin filtro", str(caches), age_filtered=False)

    assert con_filtro.measure(base).size == 0, "un archivo recién creado no llega al umbral"
    assert sin_filtro.measure(base).size > 0


def test_a_staged_target_moves_instead_of_deleting(tmp_path):
    caches = tmp_path / "Caches"
    caches.mkdir()
    (caches / "estado.bin").write_bytes(b"x" * 1024)
    papelera = tmp_path / "Trash"
    papelera.mkdir()

    base = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), trash=papelera)
    objetivo = DirectoryTarget("s", "Con aviso", str(caches), stage_in_trash=True)
    resultado = objetivo.clean(base, dry_run=False)

    assert resultado.freed == 0
    assert resultado.staged > 0
    assert (papelera / "estado.bin").exists()


# --- CommandTarget ------------------------------------------------------------


def test_a_command_that_is_not_installed_is_not_applicable(policy):
    objetivo = CommandTarget("brew", "Homebrew", ("brew", "cleanup"), probe="binario-inexistente")
    medida = objetivo.measure(RunnerFalso())

    assert medida.state is TargetState.NOT_APPLICABLE
    assert medida.detail


def test_an_unmeasurable_command_says_so_instead_of_reporting_zero(policy):
    objetivo = CommandTarget("docker", "Docker", ("docker", "system", "prune"))
    medida = objetivo.measure(RunnerFalso())

    assert medida.state is TargetState.NOT_MEASURABLE
    assert medida.detail, "debe explicar por qué no hay cifra"
    assert not medida.counts_towards_total


def test_a_command_can_report_the_size_of_its_own_cache(tmp_path, policy):
    cache = tmp_path / "npm-cache"
    cache.mkdir()
    (cache / "paquete.tgz").write_bytes(b"x" * 4096)

    runner = RunnerFalso({"npm config get cache": CommandResult(ok=True, output=str(cache))})
    objetivo = CommandTarget(
        "npm",
        "npm",
        ("npm", "cache", "clean", "--force"),
        size_from=("npm", "config", "get", "cache"),
    )
    medida = objetivo.measure(runner)

    assert medida.size >= 4096
    assert medida.state is TargetState.NOT_MEASURABLE
    assert not medida.counts_towards_total, "no puede sumarse al total: es una estimación"


def test_a_command_cache_outside_the_allowed_roots_can_still_be_measured(tmp_path):
    """Medir no es borrar: `npm config get cache` apunta donde cada máquina quiera.

    Las raíces permitidas protegen la ruta de borrado; aplicarlas aquí rompía el
    análisis en cuanto npm tenía su caché en `~/.npm`.
    """
    cache = tmp_path / "fuera-de-toda-raiz"
    cache.mkdir()
    (cache / "paquete.tgz").write_bytes(b"x" * 4096)

    runner = RunnerFalso({"npm config get cache": CommandResult(ok=True, output=str(cache))})
    objetivo = CommandTarget(
        "npm", "npm", ("npm", "cache", "clean"), size_from=("npm", "config", "get", "cache")
    )

    assert objetivo.measure(runner).size >= 4096


def test_the_readiness_check_gates_availability():
    """Docker puede estar instalado y con el demonio parado."""
    runner = RunnerFalso({"docker info": CommandResult(ok=False, output="cannot connect")})
    objetivo = CommandTarget(
        "docker", "Docker", ("docker", "system", "prune"), readiness=("docker", "info")
    )
    assert not objetivo.is_available(runner)


def test_simulating_a_command_never_runs_it():
    runner = RunnerFalso()
    objetivo = CommandTarget("brew", "Homebrew", ("brew", "cleanup", "--prune=all"))

    resultado = objetivo.clean(dry_run=True, runner=runner)

    assert ("brew", "cleanup", "--prune=all") not in runner.llamadas
    assert not resultado.performed
    assert "brew cleanup --prune=all" in resultado.detail


def test_a_failing_command_is_recorded_as_an_error():
    runner = RunnerFalso({"brew cleanup": CommandResult(ok=False, output="boom")})
    objetivo = CommandTarget("brew", "Homebrew", ("brew", "cleanup"))

    resultado = objetivo.clean(dry_run=False, runner=runner)

    assert resultado.errors
    assert "boom" in resultado.detail


# --- SystemActionTarget -------------------------------------------------------


def test_a_system_action_declares_its_effect_instead_of_a_size():
    objetivo = SystemActionTarget(
        "purge", "Liberar RAM inactiva", ("purge",), effect="libera memoria, no espacio en disco"
    )
    medida = objetivo.measure()

    assert medida.state is TargetState.NOT_MEASURABLE
    assert medida.size == 0
    assert "memoria" in medida.detail
    assert not medida.counts_towards_total


def test_a_system_action_requires_privileges_by_default():
    objetivo = SystemActionTarget("purge", "Liberar RAM", ("purge",), effect="libera memoria")
    assert objetivo.requires_privileges


def test_simulating_a_system_action_never_runs_it():
    runner = RunnerFalso()
    objetivo = SystemActionTarget(
        "snap", "Snapshots", ("tmutil", "thinlocalsnapshots", "/"), effect="espacio purgable"
    )

    objetivo.clean(dry_run=True, runner=runner)

    assert runner.llamadas == []


def test_measurements_without_a_size_never_count_towards_the_total():
    for estado in (TargetState.NOT_APPLICABLE, TargetState.NOT_MEASURABLE):
        assert not Measurement(estado, size=999).counts_towards_total
    assert Measurement(TargetState.READY, size=999).counts_towards_total
