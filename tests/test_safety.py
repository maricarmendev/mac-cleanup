"""Los seis invariantes de seguridad de la ruta de borrado.

Todo ocurre sobre directorios temporales: nada aquí toca el disco real.
"""

import errno
import os
import time
from pathlib import Path

import pytest

from smartcare.core import safety
from smartcare.core.safety import Action, DeletionPolicy, SafetyError


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    """Un árbol de caché de mentira con contenido variado."""
    root = tmp_path.resolve() / "Caches"
    (root / "app-uno" / "anidado").mkdir(parents=True)
    (root / "app-uno" / "datos.bin").write_bytes(b"x" * 4096)
    (root / "app-uno" / "anidado" / "mas.bin").write_bytes(b"y" * 2048)
    (root / "app-dos").mkdir()
    (root / "app-dos" / "suelto.bin").write_bytes(b"z" * 1024)
    (root / "suelto-en-la-raiz.bin").write_bytes(b"w" * 512)
    return root


@pytest.fixture
def policy(tmp_path: Path) -> DeletionPolicy:
    return DeletionPolicy(allowed_roots=(tmp_path.resolve(),))


def contenido(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


# --- Invariante 1: en simulación no se escribe ni se borra nada ---------------


def test_planning_does_not_touch_the_disk(cache, policy):
    antes = contenido(cache)
    list(safety.plan(cache, policy))
    safety.measure(cache, policy)
    assert contenido(cache) == antes


def test_measuring_matches_what_deleting_actually_frees(cache, policy):
    estimado = safety.measure(cache, policy)
    informe = safety.execute(safety.plan(cache, policy), policy)
    assert informe.deleted == estimado


# --- Invariante 2: nunca se elimina el directorio padre -----------------------


def test_the_swept_directory_survives(cache, policy):
    safety.execute(safety.plan(cache, policy), policy)
    assert cache.is_dir()
    assert contenido(cache) == set()


# --- Invariante 3: no se siguen enlaces simbólicos ----------------------------


def test_a_symlinked_file_is_unlinked_but_its_target_survives(tmp_path, cache, policy):
    objetivo = tmp_path.resolve() / "fuera.bin"
    objetivo.write_bytes(b"importante")
    (cache / "enlace.bin").symlink_to(objetivo)

    safety.execute(safety.plan(cache, policy), policy)

    assert not (cache / "enlace.bin").exists()
    assert objetivo.read_bytes() == b"importante"


def test_a_symlinked_directory_is_not_followed(tmp_path, cache, policy):
    fuera = tmp_path.resolve() / "carpeta-fuera"
    fuera.mkdir()
    (fuera / "tesoro.bin").write_bytes(b"no me borres")
    (cache / "atajo").symlink_to(fuera, target_is_directory=True)

    plan = list(safety.plan(cache, policy))
    atajo = next(item for item in plan if item.path.name == "atajo")
    assert atajo.is_symlink

    safety.execute(plan, policy)

    assert not (cache / "atajo").exists()
    assert (fuera / "tesoro.bin").read_bytes() == b"no me borres"


# --- Invariante 4: toda ruta debe caer bajo una raíz permitida ----------------


def test_sweeping_outside_the_allowed_roots_is_rejected(tmp_path, cache):
    ajena = DeletionPolicy(allowed_roots=(tmp_path.resolve() / "otra-parte",))
    with pytest.raises(SafetyError):
        safety.plan(cache, ajena)


def test_the_rejection_happens_before_iterating_the_plan(tmp_path, cache):
    """La validación no puede quedar diferida al primer `next()`."""
    ajena = DeletionPolicy(allowed_roots=(tmp_path.resolve() / "otra-parte",))
    with pytest.raises(SafetyError):
        safety.plan(cache, ajena)  # sin list(), sin iterar
    assert (cache / "app-uno" / "datos.bin").exists()


def test_execute_rechecks_every_path_at_the_write_boundary(tmp_path, policy):
    """Un plan construido a mano no puede saltarse la validación."""
    intruso = tmp_path.parent / "victima.bin"
    intruso.write_bytes(b"no")
    falso = safety.PlannedRemoval(intruso, 2, Action.DELETE)

    with pytest.raises(SafetyError):
        safety.execute([falso], policy)
    assert intruso.exists()


# --- Invariante 5: la lista de exclusión nunca se toca ------------------------


def test_an_excluded_path_inside_a_swept_directory_survives(cache, tmp_path):
    recovery = cache / "Adobe InDesign" / "InDesign Recovery"
    recovery.mkdir(parents=True)
    (recovery / "sin-guardar.indd").write_bytes(b"trabajo sin guardar")
    (cache / "Adobe InDesign" / "basura.tmp").write_bytes(b"basura")

    con_exclusion = DeletionPolicy(
        allowed_roots=(tmp_path.resolve(),),
        excluded=(recovery,),
    )
    safety.execute(safety.plan(cache, con_exclusion), con_exclusion)

    assert (recovery / "sin-guardar.indd").read_bytes() == b"trabajo sin guardar"
    assert not (cache / "Adobe InDesign" / "basura.tmp").exists()


def test_excluded_bytes_are_not_counted_as_recoverable(cache, tmp_path):
    recovery = cache / "Adobe InDesign" / "InDesign Recovery"
    recovery.mkdir(parents=True)
    (recovery / "grande.bin").write_bytes(b"g" * 100_000)

    sin_exclusion = DeletionPolicy(allowed_roots=(tmp_path.resolve(),))
    con_exclusion = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), excluded=(recovery,))

    assert safety.measure(cache, con_exclusion) < safety.measure(cache, sin_exclusion)


def test_the_excluded_path_is_reported_as_preserved(cache, tmp_path):
    recovery = cache / "app-uno" / "InDesign Recovery"
    recovery.mkdir(parents=True)
    politica = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), excluded=(recovery,))

    informe = safety.execute(safety.plan(cache, politica), politica)

    assert recovery in informe.preserved


# --- Invariante 6: en staging no se borra, se mueve ---------------------------


def test_staging_moves_to_the_trash_instead_of_deleting(cache, tmp_path):
    papelera = tmp_path.resolve() / "Trash"
    papelera.mkdir()
    politica = DeletionPolicy(
        allowed_roots=(tmp_path.resolve(),), stage_in_trash=True, trash=papelera
    )

    informe = safety.execute(safety.plan(cache, politica), politica)

    assert informe.deleted == 0
    assert informe.staged > 0
    assert contenido(cache) == set()
    assert (papelera / "app-uno" / "datos.bin").exists()


def test_staging_renames_instead_of_colliding(cache, tmp_path):
    papelera = tmp_path.resolve() / "Trash"
    papelera.mkdir()
    (papelera / "app-dos").mkdir()
    (papelera / "app-dos" / "ya-estaba.bin").write_bytes(b"anterior")

    politica = DeletionPolicy(
        allowed_roots=(tmp_path.resolve(),), stage_in_trash=True, trash=papelera
    )
    safety.execute(safety.plan(cache, politica), politica)

    assert (papelera / "app-dos" / "ya-estaba.bin").exists()
    assert (papelera / "app-dos 2" / "suelto.bin").exists()


def test_staging_across_volumes_skips_instead_of_deleting(cache, tmp_path, monkeypatch):
    """Si el movimiento falla, se omite. Nunca se degrada a borrado."""
    papelera = tmp_path.resolve() / "Trash"
    papelera.mkdir()
    politica = DeletionPolicy(
        allowed_roots=(tmp_path.resolve(),), stage_in_trash=True, trash=papelera
    )

    def otro_volumen(*args, **kwargs):
        raise OSError(errno.EXDEV, "Cross-device link")

    monkeypatch.setattr(os, "rename", otro_volumen)
    informe = safety.execute(safety.plan(cache, politica), politica)

    assert informe.deleted == 0
    assert informe.staged == 0
    assert len(informe.skipped) > 0
    assert (cache / "app-uno" / "datos.bin").exists()


def test_staging_without_a_trash_directory_skips(cache, tmp_path):
    politica = DeletionPolicy(
        allowed_roots=(tmp_path.resolve(),),
        stage_in_trash=True,
        trash=tmp_path.resolve() / "no-existe",
    )
    informe = safety.execute(safety.plan(cache, politica), politica)

    assert informe.staged == 0
    assert len(informe.skipped) > 0
    assert (cache / "app-uno" / "datos.bin").exists()


# --- Filtro de antigüedad -----------------------------------------------------


def envejecer(path: Path, dias: float, ahora: float) -> None:
    momento = ahora - dias * 86400
    os.utime(path, (momento, momento))


def test_only_files_older_than_the_threshold_are_planned(cache, tmp_path):
    ahora = time.time()
    envejecer(cache / "app-uno" / "datos.bin", 30, ahora)
    envejecer(cache / "app-uno" / "anidado" / "mas.bin", 1, ahora)

    politica = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), min_age_days=7)
    planificado = {item.path for item in safety.plan(cache, politica, now=ahora)}

    assert cache / "app-uno" / "datos.bin" in planificado
    assert cache / "app-uno" / "anidado" / "mas.bin" not in planificado


def test_the_age_threshold_boundary(cache, tmp_path):
    ahora = time.time()
    justo = cache / "app-dos" / "suelto.bin"
    envejecer(justo, 7, ahora)

    politica = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), min_age_days=7)
    planificado = {item.path for item in safety.plan(cache, politica, now=ahora)}
    assert justo not in planificado, "exactamente 7 días no es 'más de 7 días'"

    envejecer(justo, 7.001, ahora)
    planificado = {item.path for item in safety.plan(cache, politica, now=ahora)}
    assert justo in planificado


def test_the_age_filter_descends_instead_of_removing_whole_directories(cache, tmp_path):
    """Sin filtro se borra el árbol entero; con filtro hay que mirar archivo a archivo."""
    ahora = time.time()
    for archivo in cache.rglob("*.bin"):
        envejecer(archivo, 30, ahora)
    reciente = cache / "app-uno" / "anidado" / "caliente.bin"
    reciente.write_bytes(b"en uso")

    politica = DeletionPolicy(allowed_roots=(tmp_path.resolve(),), min_age_days=7)
    safety.execute(safety.plan(cache, politica, now=ahora), politica)

    assert reciente.exists()
    assert not (cache / "app-uno" / "datos.bin").exists()


# --- Rutas ausentes, sin permisos y tamaños -----------------------------------


def test_a_missing_directory_plans_nothing(tmp_path, policy):
    assert list(safety.plan(tmp_path.resolve() / "no-existe", policy)) == []
    assert safety.measure(tmp_path.resolve() / "no-existe", policy) == 0


def test_a_file_where_a_directory_was_expected_plans_nothing(tmp_path, policy):
    archivo = tmp_path.resolve() / "soy-un-archivo"
    archivo.write_bytes(b"hola")
    assert list(safety.plan(archivo, policy)) == []


def test_an_unreadable_directory_does_not_crash_the_plan(cache, policy):
    cerrado = cache / "app-uno"
    cerrado.chmod(0o000)
    try:
        planificado = list(safety.plan(cache, policy))
    finally:
        cerrado.chmod(0o755)
    assert any(item.path.name == "app-dos" for item in planificado)


def test_size_accounts_for_the_whole_tree(cache, policy):
    total = safety.measure(cache, policy)
    assert total >= 4096 + 2048 + 1024 + 512


def test_permission_errors_are_recorded_without_aborting_the_rest(cache, policy, monkeypatch):
    original = safety._remove
    fallado = []

    def a_veces_falla(path: Path) -> None:
        if path.name == "app-uno":
            fallado.append(path)
            raise PermissionError(errno.EACCES, "Operation not permitted")
        original(path)

    monkeypatch.setattr(safety, "_remove", a_veces_falla)
    informe = safety.execute(safety.plan(cache, policy), policy)

    assert len(informe.errors) == 1
    assert fallado
    assert not (cache / "app-dos").exists(), "el resto debe limpiarse igualmente"


def test_allowed_roots_are_compared_resolved(tmp_path, cache):
    """Una raíz detrás de un enlace simbólico sigue siendo la misma raíz."""
    enlace = tmp_path / "atajo-a-la-raiz"
    enlace.symlink_to(tmp_path.resolve(), target_is_directory=True)
    politica = DeletionPolicy(allowed_roots=(enlace,))

    planificado = list(safety.plan(cache, politica))

    assert planificado, "la raíz enlazada debe aceptarse, no rechazarse"
