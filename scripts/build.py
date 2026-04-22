"""PyInstaller 打包驱动。

用法
----
默认打两个 exe:
    uv run --group build python scripts/build.py

只打其一:
    uv run --group build python scripts/build.py --target server
    uv run --group build python scripts/build.py --target cli

产物
----
    dist/rosetta-server.exe
    dist/rosetta.exe

中间产物落在 `build/work/<spec-name>/`(.gitignore 已覆盖),不污染 spec 源目录。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD_DIR = _REPO_ROOT / "build"
_DIST_DIR = _REPO_ROOT / "dist"
_WORK_DIR = _BUILD_DIR / "work"

_TARGETS: dict[str, tuple[str, str]] = {
    # key → (spec 文件名, 最终 exe 名 · 用于打印和产物校验)
    "server": ("rosetta-server.spec", "rosetta-server.exe"),
    "cli": ("rosetta.spec", "rosetta.exe"),
}


def _run_pyinstaller(spec_name: str) -> None:
    spec_path = _BUILD_DIR / spec_name
    if not spec_path.exists():
        raise RuntimeError(f"spec 不存在:{spec_path}")

    # --distpath / --workpath 必须是绝对路径,否则 PyInstaller 以当前工作目录为根
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(_DIST_DIR),
        "--workpath",
        str(_WORK_DIR),
        str(spec_path),
    ]
    print(f"\n[build] $ {' '.join(cmd)}\n", flush=True)
    result = subprocess.run(cmd, cwd=_BUILD_DIR, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller 失败:{spec_name} exit={result.returncode}")


def _report(exe_name: str) -> None:
    exe_path = _DIST_DIR / exe_name
    if not exe_path.exists():
        print(f"[build] FAIL 产物未生成:{exe_path}", file=sys.stderr)
        return
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"[build] OK   {exe_path}  ({size_mb:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="PyInstaller 打包驱动")
    parser.add_argument(
        "--target",
        choices=["server", "cli", "all"],
        default="all",
        help="打哪个;默认全打",
    )
    args = parser.parse_args()

    targets: list[str] = ["server", "cli"] if args.target == "all" else [args.target]

    # 只清要重打的 exe,不动另一个 target(`--target cli` 不应波及 server.exe)
    for t in targets:
        stale = _DIST_DIR / _TARGETS[t][1]
        if stale.exists():
            stale.unlink()

    for t in targets:
        spec_name, _exe_name = _TARGETS[t]
        _run_pyinstaller(spec_name)

    print("\n[build] 产物:")
    for t in targets:
        _report(_TARGETS[t][1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
