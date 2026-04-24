"""Smoke test:验证 rosetta 包可 import 且 __version__ 与 pyproject.toml 同步。

不硬编码具体版本号,避免每次 publish bump 都改测试。
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_rosetta_version() -> None:
    import rosetta

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert rosetta.__version__ == pyproject["project"]["version"]
