"""Punto de entrada de SmartCare.

Sin argumentos abrirá la TUI; con flags correrá en modo texto plano (fase 4).
"""

import sys


def main() -> int:
    print("SmartCare aún no está implementado. En construcción.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
