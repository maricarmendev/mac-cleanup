"""Formateo de tamaños a unidades legibles."""

_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(size: float) -> str:
    """Convierte bytes a texto legible en base 1024, con un decimal."""
    value = float(size)
    index = 0
    while abs(value) >= 1024 and index < len(_UNITS) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {_UNITS[index]}"
