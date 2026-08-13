"""Sondas de solo lectura sobre el sistema: nada de lo que hay aquí escribe."""

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_PAGE_SIZE_PATTERN = re.compile(r"page size of (\d+) bytes")
_PAGE_COUNT_PATTERN = re.compile(r"^(.*?):\s+(\d+)\.?\s*$")


@dataclass(frozen=True)
class DiskUsage:
    total: int
    used: int
    free: int

    @property
    def used_ratio(self) -> float:
        return self.used / self.total if self.total else 0.0


@dataclass(frozen=True)
class MemoryStats:
    page_size: int
    free: int
    active: int
    inactive: int
    wired: int
    compressed: int


def macos_version() -> str:
    """Versión de macOS según el propio sistema.

    Se consulta `sw_vers` en vez de `platform.mac_ver()` porque este último
    puede reportar 10.16 cuando el binario se construye con un SDK antiguo,
    y el binario de distribución se genera con PyInstaller.
    """
    version = _capture(["sw_vers", "-productVersion"])
    return version or platform.mac_ver()[0] or "desconocida"


def architecture() -> str:
    return platform.machine()


def disk_usage(path: Path | str = "/") -> DiskUsage:
    total, used, free = shutil.disk_usage(path)
    return DiskUsage(total=total, used=used, free=free)


def memory_stats() -> MemoryStats | None:
    output = _capture(["vm_stat"])
    return parse_vm_stat(output) if output else None


def parse_vm_stat(output: str) -> MemoryStats:
    """Traduce la salida de `vm_stat`, que cuenta páginas, no bytes.

    El tamaño de página varía con la arquitectura (16 KB en Apple Silicon,
    4 KB en Intel), así que se lee de la cabecera y solo se recurre al valor
    del sistema si esa cabecera no aparece.
    """
    match = _PAGE_SIZE_PATTERN.search(output)
    page_size = int(match.group(1)) if match else os.sysconf("SC_PAGE_SIZE")

    pages: dict[str, int] = {}
    for line in output.splitlines():
        entry = _PAGE_COUNT_PATTERN.match(line)
        if entry:
            pages[entry.group(1).strip().lower()] = int(entry.group(2))

    def as_bytes(key: str) -> int:
        return pages.get(key, 0) * page_size

    return MemoryStats(
        page_size=page_size,
        free=as_bytes("pages free"),
        active=as_bytes("pages active"),
        inactive=as_bytes("pages inactive"),
        wired=as_bytes("pages wired down"),
        compressed=as_bytes("pages occupied by compressor"),
    )


def _capture(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
