"""Sondas de solo lectura."""

import textwrap

from smartcare.core import system

APPLE_SILICON = textwrap.dedent("""\
    Mach Virtual Memory Statistics: (page size of 16384 bytes)
    Pages free:                                     3817.
    Pages active:                                 194175.
    Pages inactive:                               192524.
    Pages speculative:                               432.
    Pages throttled:                                   0.
    Pages wired down:                             126458.
    Pages purgeable:                                   4.
    "Translation faults":                       88904044.
    Pages copy-on-write:                         2733288.
    Pages occupied by compressor:                  65536.
""")

INTEL = APPLE_SILICON.replace("page size of 16384 bytes", "page size of 4096 bytes")


def test_reads_the_page_size_from_the_header():
    assert system.parse_vm_stat(APPLE_SILICON).page_size == 16384
    assert system.parse_vm_stat(INTEL).page_size == 4096


def test_converts_pages_to_bytes():
    stats = system.parse_vm_stat(APPLE_SILICON)
    assert stats.free == 3817 * 16384
    assert stats.active == 194175 * 16384
    assert stats.inactive == 192524 * 16384
    assert stats.wired == 126458 * 16384
    assert stats.compressed == 65536 * 16384


def test_the_same_report_scales_with_the_page_size():
    """El mismo recuento de páginas son cifras distintas según la arquitectura."""
    assert system.parse_vm_stat(APPLE_SILICON).free == system.parse_vm_stat(INTEL).free * 4


def test_falls_back_to_the_system_page_size_when_the_header_is_missing():
    sin_cabecera = "\n".join(APPLE_SILICON.splitlines()[1:])
    stats = system.parse_vm_stat(sin_cabecera)
    assert stats.page_size > 0
    assert stats.free == 3817 * stats.page_size


def test_missing_counters_are_zero_instead_of_crashing():
    """vm_stat no siempre reporta todos los contadores."""
    sin_compresor = "\n".join(
        linea for linea in APPLE_SILICON.splitlines() if "compressor" not in linea
    )
    assert system.parse_vm_stat(sin_compresor).compressed == 0


def test_the_header_is_not_read_as_a_counter():
    """La cabecera acaba en dos puntos como los contadores, pero no lo es."""
    solo_cabecera = APPLE_SILICON.splitlines()[0]
    stats = system.parse_vm_stat(solo_cabecera)
    assert stats.free == 0
    assert stats.page_size == 16384


def test_probes_the_real_machine():
    assert system.macos_version() != "desconocida"
    assert system.architecture()

    disco = system.disk_usage("/")
    assert disco.total > 0
    assert disco.free <= disco.total
    assert 0.0 <= disco.used_ratio <= 1.0

    memoria = system.memory_stats()
    assert memoria is not None
    assert memoria.free >= 0
