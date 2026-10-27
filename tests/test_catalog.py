"""El catálogo: los 8 módulos, sus rutas y la resolución de solapamientos."""

from pathlib import Path

import pytest

from smartcare.core import catalog
from smartcare.core.catalog import MODULES, Module
from smartcare.core.targets import CommandTarget, DirectoryTarget, Risk, SystemActionTarget

TODOS_LOS_OBJETIVOS = [target for module in MODULES for target in module.targets]
OBJETIVOS_DE_DIRECTORIO = [t for t in TODOS_LOS_OBJETIVOS if isinstance(t, DirectoryTarget)]


# --- Estructura ---------------------------------------------------------------


def test_the_eight_modules_are_present():
    assert [module.key for module in MODULES] == [
        "caches",
        "logs",
        "trash",
        "dev",
        "design",
        "browsers",
        "memory",
        "snapshots",
    ]


def test_every_module_has_a_flag():
    for module in MODULES:
        assert module.flag == f"--{module.key}"


def test_every_key_is_unique():
    claves = [target.key for target in TODOS_LOS_OBJETIVOS]
    assert len(claves) == len(set(claves))


def test_no_two_directory_targets_share_a_path():
    """Dos objetivos con la misma ruta contarían sus bytes dos veces."""
    rutas = [target.path for target in OBJETIVOS_DE_DIRECTORIO]
    assert len(rutas) == len(set(rutas))


# --- Invariante 4 en los datos ------------------------------------------------


def test_every_catalogued_path_falls_under_an_allowed_root():
    """Un objetivo fuera de las raíces sería rechazado en tiempo de ejecución."""
    raices = catalog.allowed_roots()
    for target in OBJETIVOS_DE_DIRECTORIO:
        ruta = Path(target.path).expanduser()
        assert any(ruta == raiz or ruta.is_relative_to(raiz) for raiz in raices), (
            f"{target.key} apunta fuera de las raíces permitidas: {target.path}"
        )


def test_no_catalogued_path_escapes_the_home_or_the_system_libraries():
    prohibidos = ("~/Documents", "~/Desktop", "~/Movies", "~/Pictures", "~/Downloads")
    for target in OBJETIVOS_DE_DIRECTORIO:
        assert not any(target.path.startswith(p) for p in prohibidos)


# --- Riesgo -------------------------------------------------------------------


def test_only_safe_modules_are_preselected():
    preseleccionados = {module.key for module in MODULES if module.preselected}
    assert "trash" not in preseleccionados
    assert "snapshots" not in preseleccionados
    assert "caches" in preseleccionados


def test_the_trash_is_destructive():
    papelera = catalog.module_by_key("trash")
    assert papelera.risk is Risk.DESTRUCTIVE
    assert papelera.note


def test_every_warning_directory_target_is_staged_not_deleted():
    """Los objetivos 'con aviso' se mueven a la papelera, no se borran."""
    for target in OBJETIVOS_DE_DIRECTORIO:
        if target.risk is Risk.WARNING:
            assert target.stage_in_trash, f"{target.key} avisa pero borra sin red"


def test_the_trash_is_never_staged_into_itself():
    papelera = next(t for t in OBJETIVOS_DE_DIRECTORIO if t.key == "trash-user")
    assert not papelera.stage_in_trash


def test_destructive_targets_carry_an_explanation():
    for target in TODOS_LOS_OBJETIVOS:
        if target.risk is Risk.DESTRUCTIVE:
            assert target.note or target.key == "trash-user"


def test_docker_is_destructive_without_making_the_whole_module_unsafe():
    dev = catalog.module_by_key("dev")
    docker = next(t for t in dev.targets if t.key == "dev-docker")
    assert docker.risk is Risk.DESTRUCTIVE
    assert dev.risk is Risk.SAFE


# --- Filtro de antigüedad y privilegios ---------------------------------------


def test_caches_and_logs_are_age_filtered():
    for clave in ("caches-user", "caches-system", "logs-user", "logs-diagnostic"):
        target = next(t for t in OBJETIVOS_DE_DIRECTORIO if t.key == clave)
        assert target.age_filtered


def test_the_trash_is_not_age_filtered():
    """Vaciar la papelera es vaciarla entera, no solo lo viejo."""
    papelera = next(t for t in OBJETIVOS_DE_DIRECTORIO if t.key == "trash-user")
    assert not papelera.age_filtered


def test_system_wide_paths_declare_that_they_need_privileges():
    for target in OBJETIVOS_DE_DIRECTORIO:
        if target.path.startswith("/Library"):
            assert target.requires_privileges, f"{target.key} toca /Library sin declarar sudo"


# --- Cachés de Electron -------------------------------------------------------


def test_electron_targets_only_touch_the_three_cache_folders():
    permitidas = set(catalog.ELECTRON_CACHE_DIRS)
    electron = [t for t in OBJETIVOS_DE_DIRECTORIO if t.key.startswith("electron-")]
    assert electron
    for target in electron:
        assert Path(target.path).name in permitidas, f"{target.path} no es una carpeta de caché"


def test_electron_targets_never_reach_app_state_or_documents():
    prohibidas = ("Local Storage", "IndexedDB", "Session Storage", "databases", "Partitions")
    for target in OBJETIVOS_DE_DIRECTORIO:
        if target.key.startswith("electron-"):
            assert not any(nombre in target.path for nombre in prohibidas)


def test_chrome_targets_never_reach_site_data():
    prohibidas = ("IndexedDB", "File System", "Local Storage", "Session Storage", "Cookies")
    for target in OBJETIVOS_DE_DIRECTORIO:
        if "Google" in target.path:
            assert not any(nombre in target.path for nombre in prohibidas), target.path


def test_installed_node_versions_are_outside_the_allowed_roots():
    """De ~/.nvm solo se permite la caché; las versiones instaladas son herramientas."""
    instaladas = Path("~/.nvm/versions/node").expanduser()
    assert not any(instaladas.is_relative_to(raiz) for raiz in catalog.allowed_roots())


def test_npm_is_measured_by_what_its_command_actually_cleans():
    dev = catalog.module_by_key("dev")
    npm = next(t for t in dev.targets if t.key == "dev-npm")
    npx = next(t for t in dev.targets if t.key == "dev-npx")
    assert npm.size_subpath == "_cacache"
    assert npx.path.endswith("/_npx")


def test_there_is_one_electron_target_per_app_and_folder():
    electron = [t for t in OBJETIVOS_DE_DIRECTORIO if t.key.startswith("electron-")]
    assert len(electron) == len(catalog.ELECTRON_APPS) * len(catalog.ELECTRON_CACHE_DIRS)


# --- Lista de exclusión -------------------------------------------------------


def test_the_exclusion_list_covers_both_categories():
    patrones = " ".join(catalog.EXCLUSION_PATTERNS)
    assert "CloudDocs" in patrones or "bird" in patrones
    assert "CoreSync" in patrones
    assert "InDesign Recovery" in patrones


def test_exclusion_patterns_expand_to_paths(monkeypatch, tmp_path):
    recovery = tmp_path / "Library/Caches/Adobe InDesign/Version 20.0/es_ES/InDesign Recovery"
    recovery.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    expandidas = catalog.excluded_paths()

    assert recovery in expandidas
    assert tmp_path / "Library/Caches/com.apple.bird" in expandidas


# --- Solapamientos ------------------------------------------------------------


def test_the_catalogue_really_does_overlap():
    """Documenta el solapamiento que carve_outs existe para resolver."""
    ancho = next(t for t in OBJETIVOS_DE_DIRECTORIO if t.key == "caches-user")
    adobe = next(t for t in OBJETIVOS_DE_DIRECTORIO if t.key == "design-adobe-caches")
    assert adobe.path.startswith(ancho.path + "/")


def test_a_contained_target_is_carved_out_of_the_wider_one(tmp_path):
    caches = tmp_path / "Caches"
    (caches / "Adobe").mkdir(parents=True)
    (caches / "otra-cosa").mkdir()

    ancho = DirectoryTarget("ancho", "Cachés", str(caches))
    especifico = DirectoryTarget("adobe", "Adobe", str(caches / "Adobe"))

    recortes = catalog.carve_outs([ancho, especifico])

    assert recortes["ancho"] == (caches / "Adobe",)
    assert recortes["adobe"] == ()


def test_nothing_is_carved_out_when_the_specific_target_is_not_selected(tmp_path):
    caches = tmp_path / "Caches"
    (caches / "Adobe").mkdir(parents=True)
    ancho = DirectoryTarget("ancho", "Cachés", str(caches))

    recortes = catalog.carve_outs([ancho])

    assert recortes["ancho"] == ()


def test_targets_that_do_not_overlap_carve_nothing(tmp_path):
    (tmp_path / "uno").mkdir()
    (tmp_path / "dos").mkdir()
    uno = DirectoryTarget("uno", "Uno", str(tmp_path / "uno"))
    dos = DirectoryTarget("dos", "Dos", str(tmp_path / "dos"))

    recortes = catalog.carve_outs([uno, dos])

    assert recortes == {"uno": (), "dos": ()}


# --- Objetivos no medibles ----------------------------------------------------


def test_memory_and_snapshots_are_system_actions():
    for clave in ("memory", "snapshots"):
        module = catalog.module_by_key(clave)
        assert all(isinstance(t, SystemActionTarget) for t in module.targets)


def test_every_system_action_explains_its_effect():
    for target in TODOS_LOS_OBJETIVOS:
        if isinstance(target, SystemActionTarget):
            assert target.effect


def test_every_command_target_declares_how_to_detect_it():
    sin_deteccion = [
        target.key
        for target in TODOS_LOS_OBJETIVOS
        if isinstance(target, CommandTarget) and not target.probe and not target.readiness
    ]
    assert sin_deteccion == ["caches-quicklook", "caches-fonts"], (
        "solo las herramientas que trae macOS de serie pueden darse por presentes"
    )


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.key)
def test_every_module_has_targets(module: Module):
    assert module.targets


# --- Exclusiones deliberadas --------------------------------------------------


def test_deliberate_exclusions_are_documented_with_a_reason():
    assert catalog.DELIBERATE_EXCLUSIONS
    for exclusion in catalog.DELIBERATE_EXCLUSIONS:
        assert exclusion.label and exclusion.where and exclusion.reason


def test_nothing_deliberately_excluded_is_also_a_target():
    """Una exclusión documentada que además fuese objetivo sería una contradicción."""
    rutas = {target.path for target in OBJETIVOS_DE_DIRECTORIO}
    for exclusion in catalog.DELIBERATE_EXCLUSIONS:
        assert exclusion.where not in rutas


def test_lightroom_and_whatsapp_are_on_the_record():
    etiquetas = " ".join(e.label for e in catalog.DELIBERATE_EXCLUSIONS)
    assert "Lightroom" in etiquetas
    assert "WhatsApp" in etiquetas
