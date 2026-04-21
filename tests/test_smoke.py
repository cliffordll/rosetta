"""Smoke test:验证 rosetta 包可 import 并暴露 __version__。"""

from __future__ import annotations


def test_rosetta_version() -> None:
    import rosetta

    assert rosetta.__version__ == "0.1.0"
