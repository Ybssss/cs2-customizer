#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""核对**冻好的 exe** 里到底有没有那些启动必需的第三方模块。

**为什么需要它**：事故 v2.3.1 —— 第一个真正发布出去的 Release，双击即

    Failed to execute script 'main_widget' … No module named 'flask'

依赖表是对的、CI 是绿的、构建是绿的，**唯独产物里没有 flask**。原因在
`requirements_qt.txt` 指向的那个 `requirements.txt` 从没被带进仓库（entry 10）。
`tests/test_runtime_dependency_coverage.py` 量的是"声明"，本脚本量的是"产物"——
**只查一头，另一头照样能漏**。

## 怎么查

PyInstaller 的归档可以用它自带的 `archive_viewer` 列出来：

    python -m PyInstaller.utils.cliutils.archive_viewer -r -b <exe>

`-r -b` 是"递归 + 只列文件名 + 列完就退出"，输出里能看到 `yaml`、`flask` 这类顶层模块名
（子模块写成 `yaml\\_yaml.cp311-win_amd64.pyd` 这种形式）。

⚠ **onedir 的东西分两处放**：纯 Python 的模块在 exe 内的 PYZ 里，而 C 扩展（`.pyd`）
与数据文件落在同级的 `_internal\\` 目录。所以本脚本读**两个**来源，缺一个就会误报。
（这个细节是先在一次一次性构建上实测出来的，不是照文档猜的。）

⚠ 直接启动 exe 来判断行不行：**行不通**。未捕获异常在 Windows 上会弹一个原生模态框，
进程会**挂着**等用户点，于是"没崩"和"弹了崩溃框"在超时判据下长得一模一样——
恰好在最该抓住的那类缺陷上给出假绿。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_scan import third_party_imports  # noqa: E402  (路径原因)

_PYI_TOP = re.compile(r"^[^.\s\\]+")


def top_level_names(listing: str) -> set[str]:
    """把 archive_viewer 的输出折成顶层模块名集合。"""
    names: set[str] = set()
    for raw in listing.splitlines():
        line = raw.strip()
        if not line or line.startswith(("Options", "Contents of")):
            continue
        # 子模块是 `pkg\mod.pyd` / `pkg\__init__.py` / `mod.py`；顶层目录名是 `pkg`
        head = line.replace("/", "\\").split("\\")[0]
        m = _PYI_TOP.match(head)
        if m:
            names.add(m.group(0).lower())
    return names


def internal_top_level(internal_dir: Path) -> set[str]:
    """`_internal/` 里 C 扩展的顶层模块名（`win32api.pyd` -> `win32api`）。"""
    if not internal_dir.is_dir():
        return set()
    out: set[str] = set()
    for path in internal_dir.rglob("*.pyd"):
        parts = path.relative_to(internal_dir).parts
        out.add(parts[0].lower())
    return out


def archive_listing(exe: Path, python: str = sys.executable) -> str:
    """跑 archive_viewer 并取回输出。"""
    result = subprocess.run(
        [python, "-m", "PyInstaller.utils.cliutils.archive_viewer", "-r", "-b", str(exe)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"archive_viewer 读不了 {exe}（退出码 {result.returncode}）:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def missing_modules(exe: Path, required: set[str], python: str = sys.executable) -> set[str]:
    """exe 的两个存放位置里都找不到的模块名。"""
    available = top_level_names(archive_listing(exe, python)) | internal_top_level(
        exe.parent / "_internal"
    )
    return {name for name in required if name.lower() not in available}


def find_exe(root: Path | None = None) -> Path:
    """在 `release/<应用名>/` 下找出构建出的可执行文件。

    ⚠ 找**多于**一个就报错，而不是挑最新的那个：构建目录里躺着上一版的产物时，
    "挑一个"会随机地核到旧包，然后给出一个关于错误产物的结论。宁可直接失败。
    """
    root = root or (Path(__file__).resolve().parent.parent)
    found = sorted(root.glob("release/*/CS2 Customizer.exe"))
    if not found:
        raise RuntimeError(
            f"{root / 'release'} 下没有 `*/CS2 Customizer.exe`。"
            "先跑 `python build_tools/build_release.py --mode onedir …`。"
        )
    if len(found) > 1:
        raise RuntimeError(
            "找到多于一个候选可执行文件:\n  "
            + "\n  ".join(str(f) for f in found)
            + "\n请把上一版的 release/ 目录清掉再构建 —— 否则核到的可能是旧包。"
        )
    return found[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="?", type=Path,
                        help="构建出的 onedir 里的可执行文件（省略则自动在 release/ 下找）")
    parser.add_argument("--python", default=sys.executable, help="装有 PyInstaller 的解释器")
    args = parser.parse_args(argv)

    try:
        exe = args.exe or find_exe()
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    if not exe.is_file():
        print(f"[FAIL] 找不到可执行文件: {exe}", file=sys.stderr)
        return 1
    print(f"[INFO] 核对产物: {exe}")

    required = third_party_imports()
    print(f"[INFO] 启动必需的第三方模块 ({len(required)}): {', '.join(sorted(required))}")

    missing = missing_modules(args.exe, required, args.python)
    if missing:
        print("", file=sys.stderr)
        print(
            f"[FAIL] 这些模块在产物里找不到：{', '.join(sorted(missing))}\n"
            f"       查的是 {args.exe} 的 PYZ 归档，以及同级的 _internal\\ 目录。\n"
            "       ⇒ 装依赖的那一步漏了包（看 .github/workflows/build-installer.yml 的 pip install），\n"
            "         或者 PyInstaller 没把它冻进去（需要 hidden-import）。\n"
            "       这个产物**装到用户机器上也是起不来的**——事故 v2.3.1 就是这么发出去的。",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] 产物里 {len(required)} 个启动必需的模块都在。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
