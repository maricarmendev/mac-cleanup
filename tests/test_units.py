"""Formateo de tamaños."""

import pytest

from smartcare.core.units import format_bytes


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0.0 B"),
        (1, "1.0 B"),
        (1023, "1023.0 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (1024**4, "1.0 TB"),
    ],
)
def test_formats_each_unit(size, expected):
    assert format_bytes(size) == expected


def test_caps_at_terabytes():
    """No hay unidad por encima de TB: un petabyte se expresa en miles de TB."""
    assert format_bytes(1024**5) == "1024.0 TB"


def test_rounds_to_one_decimal():
    assert format_bytes(1024 * 1024 * 1.25) == "1.2 MB"
    assert format_bytes(1024 * 1024 * 1.28) == "1.3 MB"


def test_accepts_negative_deltas():
    """El disco puede reportarse como diferencia antes/después."""
    assert format_bytes(-2048) == "-2.0 KB"
