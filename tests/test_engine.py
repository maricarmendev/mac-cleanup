"""Orquestación: selección, solapamientos, progreso, cancelación y simulación."""

import threading
from pathlib import Path

import pytest

from smartcare.core import catalog, engine, safety
from smartcare.core.catalog import Module
from smartcare.core.safety import DeletionPolicy
from smartcare.core.targets import (
    CommandResult,
    CommandTarget,
    DirectoryTarget,
    Risk,
    SystemActionTarget,
    TargetState,
)


@pytest.fixture(autouse=True)
def raices_de_prueba(tmp_path, monkeypatch):
    """El motor debe operar sobre el árbol temporal, no sobre el home real."""
    monkeypatch.setattr(catalog, "allowed_roots", lambda: (tmp_path.resolve(),))
    monkeypatch.setattr(catalog, "excluded_paths", lambda: ())


class RunnerFalso:
    def __init__(self, respuestas=None):
        self.llamadas = []
        self.respuestas = respuestas or {}

    def __call__(self, command):
        clave = " ".join(command)
        self.llamadas.append(clave)
        return self.respuestas.get(clave, CommandResult(ok=True, output=""))


def modulo(key: str, *targets, risk: Risk = Risk.SAFE) -> Module:
    return Module(key=key, flag=f"--{key}", label=key, risk=risk, targets=tuple(targets))


@pytest.fixture
def arbol(tmp_path) -> Path:
    caches = tmp_path / "Caches"
    (caches / "Adobe").mkdir(parents=True)
    (caches / "Adobe" / "media.bin").write_bytes(b"a" * 8192)
    (caches / "otra-cosa.bin").write_bytes(b"o" * 4096)
    return caches


# --- Simulación ---------------------------------------------------------------


def test_simulation_is_the_default():
    assert engine.Options().dry_run is True


def test_analysis_never_writes(arbol, tmp_path):
    antes = set(tmp_path.rglob("*"))
    engine.analyze([modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))])
    assert set(tmp_path.rglob("*")) == antes


def test_simulated_cleaning_never_writes(arbol, tmp_path):
    antes = set(tmp_path.rglob("*"))
    informe = engine.clean([modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))])
    assert set(tmp_path.rglob("*")) == antes
    assert informe.freed > 0, "la simulación sí reporta lo que liberaría"


def test_simulation_reports_what_the_real_run_frees(arbol):
    modulos = [modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))]
    simulado = engine.clean(modulos, engine.Options(dry_run=True))
    real = engine.clean(modulos, engine.Options(dry_run=False, take_snapshot=False))
    assert simulado.freed == real.freed


# --- Solapamientos ------------------------------------------------------------


def test_overlapping_modules_do_not_count_the_same_bytes_twice(arbol, tmp_path):
    ancho = modulo("caches", DirectoryTarget("caches-user", "Cachés", str(arbol)))
    especifico = modulo("design", DirectoryTarget("design-adobe", "Adobe", str(arbol / "Adobe")))

    solo_ancho = engine.analyze([ancho]).total
    ambos = engine.analyze([ancho, especifico]).total

    politica = DeletionPolicy(allowed_roots=(tmp_path.resolve(),))
    real = safety.measure(arbol, politica)

    assert solo_ancho == real
    assert ambos == real, "el total no puede crecer por seleccionar un módulo contenido"


def test_the_wider_target_still_sweeps_everything_when_alone(arbol):
    ancho = modulo("caches", DirectoryTarget("caches-user", "Cachés", str(arbol)))
    engine.clean([ancho], engine.Options(dry_run=False, take_snapshot=False))
    assert list(arbol.rglob("*.bin")) == []


def test_carving_out_does_not_leave_anything_uncleaned(arbol):
    """El recorte reparte el trabajo entre los dos objetivos, no lo pierde."""
    ancho = modulo("caches", DirectoryTarget("caches-user", "Cachés", str(arbol)))
    especifico = modulo("design", DirectoryTarget("design-adobe", "Adobe", str(arbol / "Adobe")))

    engine.clean([ancho, especifico], engine.Options(dry_run=False, take_snapshot=False))

    assert list(arbol.rglob("*.bin")) == []


def test_each_module_keeps_its_own_figure(arbol):
    ancho = modulo("caches", DirectoryTarget("caches-user", "Cachés", str(arbol)))
    especifico = modulo("design", DirectoryTarget("design-adobe", "Adobe", str(arbol / "Adobe")))

    analisis = engine.analyze([ancho, especifico])

    assert analisis.total_for("design") >= 8192
    assert analisis.total_for("caches") > 0
    assert analisis.total_for("caches") + analisis.total_for("design") == analisis.total


# --- Riesgo y confirmaciones --------------------------------------------------


def test_destructive_targets_are_left_out_unless_confirmed(tmp_path):
    papelera = tmp_path / "Trash"
    papelera.mkdir()
    (papelera / "algo.bin").write_bytes(b"x" * 1024)
    destructivo = modulo(
        "trash",
        DirectoryTarget("trash-user", "Papelera", str(papelera), risk=Risk.DESTRUCTIVE),
        risk=Risk.DESTRUCTIVE,
    )

    sin_confirmar = engine.analyze([destructivo])
    assert sin_confirmar.entries == []

    confirmado = engine.analyze([destructivo], engine.Options(confirmed=frozenset({"trash-user"})))
    assert confirmado.total >= 1024


def test_warning_targets_do_not_need_confirmation(tmp_path):
    aviso = tmp_path / "Figma"
    aviso.mkdir()
    (aviso / "sesion.bin").write_bytes(b"x" * 512)
    modulos = [modulo("design", DirectoryTarget("figma", "Figma", str(aviso), risk=Risk.WARNING))]
    assert engine.analyze(modulos).entries


# --- Progreso y cancelación ---------------------------------------------------


def test_progress_is_reported_for_every_target(arbol):
    eventos = []
    modulos = [
        modulo(
            "c",
            DirectoryTarget("c1", "Uno", str(arbol)),
            DirectoryTarget("c2", "Dos", str(arbol / "Adobe")),
        )
    ]
    engine.analyze(modulos, progress=eventos.append)

    assert len(eventos) == 2
    assert [e.done for e in eventos] == [1, 2]
    assert all(e.total == 2 for e in eventos)


def test_cancelling_stops_the_cleaning_and_says_so(arbol):
    cancelar = threading.Event()
    cancelar.set()
    modulos = [modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))]

    informe = engine.clean(modulos, engine.Options(dry_run=False), cancel=cancelar)

    assert informe.cancelled
    assert informe.results == []
    assert (arbol / "otra-cosa.bin").exists(), "cancelar no puede dejar el borrado a medias"


def test_a_cancelled_analysis_is_marked_as_such(arbol):
    cancelar = threading.Event()
    cancelar.set()
    modulos = [modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))]
    assert engine.analyze(modulos, cancel=cancelar).cancelled


# --- Errores ------------------------------------------------------------------


def test_a_failing_target_does_not_stop_the_others(arbol):
    runner = RunnerFalso({"brew cleanup": CommandResult(ok=False, output="boom")})
    modulos = [
        modulo(
            "dev",
            CommandTarget("dev-brew", "Homebrew", ("brew", "cleanup")),
            DirectoryTarget("c1", "Cachés", str(arbol)),
        )
    ]

    informe = engine.clean(
        modulos, engine.Options(dry_run=False, take_snapshot=False), runner=runner
    )

    assert informe.errors
    assert list(arbol.rglob("*.bin")) == [], "el objetivo siguiente debe limpiarse igual"


# --- Snapshot previo ----------------------------------------------------------


def test_a_snapshot_is_taken_before_a_real_cleaning(arbol):
    runner = RunnerFalso()
    engine.clean(
        [modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))],
        engine.Options(dry_run=False),
        runner=runner,
    )
    assert "tmutil localsnapshot" in runner.llamadas


def test_no_snapshot_is_taken_when_simulating(arbol):
    runner = RunnerFalso()
    engine.clean([modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))], runner=runner)
    assert "tmutil localsnapshot" not in runner.llamadas


def test_a_failing_snapshot_does_not_block_the_cleaning(arbol):
    runner = RunnerFalso(
        {"tmutil localsnapshot": CommandResult(ok=False, output="no hay Time Machine")}
    )
    informe = engine.clean(
        [modulo("c", DirectoryTarget("c1", "Cachés", str(arbol)))],
        engine.Options(dry_run=False),
        runner=runner,
    )

    assert not informe.snapshot_taken
    assert informe.snapshot_detail
    assert informe.freed > 0


# --- Papelera y bytes que no liberan espacio ----------------------------------


def test_staged_bytes_are_reported_apart_from_freed_bytes(tmp_path):
    origen = tmp_path / "Figma"
    origen.mkdir()
    (origen / "sesion.bin").write_bytes(b"x" * 4096)
    papelera = tmp_path / "Trash"
    papelera.mkdir()

    monkeypatched = DirectoryTarget(
        "figma", "Figma", str(origen), stage_in_trash=True, risk=Risk.WARNING
    )
    informe = engine.clean(
        [modulo("design", monkeypatched)],
        engine.Options(dry_run=False, take_snapshot=False),
    )

    assert informe.staged > 0
    assert informe.freed == 0, "mover a la papelera no libera espacio todavía"


# --- Objetivos no aplicables y privilegios ------------------------------------


def test_missing_targets_are_grouped_as_not_applicable(tmp_path):
    modulos = [modulo("c", DirectoryTarget("fantasma", "No existe", str(tmp_path / "nada")))]
    analisis = engine.analyze(modulos)

    assert len(analisis.not_applicable()) == 1
    assert analisis.total == 0


def test_unmeasurable_targets_do_not_add_zeros_to_the_total(arbol):
    modulos = [
        modulo(
            "m",
            DirectoryTarget("c1", "Cachés", str(arbol)),
            SystemActionTarget("purge", "RAM", ("purge",), effect="libera memoria"),
        )
    ]
    analisis = engine.analyze(modulos, runner=RunnerFalso())

    purge = next(e for e in analisis.entries if e.target.key == "purge")
    assert purge.measurement.state is TargetState.NOT_MEASURABLE
    assert purge.measurement.detail
    assert analisis.total == analisis.total_for("m")


def test_privileged_operations_can_be_listed_before_asking_for_the_password(arbol):
    modulos = [
        modulo(
            "c",
            DirectoryTarget("c1", "Cachés", str(arbol)),
            DirectoryTarget("sistema", "Sistema", "/Library/Caches", requires_privileges=True),
            SystemActionTarget("purge", "RAM", ("purge",), effect="libera memoria"),
        )
    ]
    claves = {t.key for t in engine.privileged_operations(modulos)}
    assert claves == {"sistema", "purge"}
