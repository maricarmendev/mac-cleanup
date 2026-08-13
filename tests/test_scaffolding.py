"""Comprueba que el andamiaje de la fase 1 está en pie."""

import subprocess
import sys
import textwrap

import smartcare
from smartcare import cli


def test_package_is_importable():
    assert smartcare.__version__


def test_entry_point_exists():
    assert callable(cli.main)


def test_engine_runs_without_textual():
    """Invariante del plan: `core` no importa nada de la capa TUI.

    Se ejecuta en un proceso aparte con `textual` bloqueado en el `meta_path`,
    porque el propio pytest ya lo tiene importado en el proceso principal.
    """
    code = textwrap.dedent("""
        import importlib, pkgutil, sys

        class BloqueoDeTextual:
            def find_spec(self, name, path=None, target=None):
                if name == "textual" or name.startswith(("textual.", "smartcare.tui")):
                    raise AssertionError(f"el motor importó {name}")
                return None

        sys.meta_path.insert(0, BloqueoDeTextual())

        import smartcare.core
        for modulo in pkgutil.walk_packages(smartcare.core.__path__, "smartcare.core."):
            importlib.import_module(modulo.name)
    """)
    resultado = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert resultado.returncode == 0, resultado.stderr
