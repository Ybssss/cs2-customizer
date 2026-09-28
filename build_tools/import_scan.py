#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""应用代码 import 了哪些**第三方包** —— 全仓唯一的一份实现。

**为什么单独成一个模块**：`tests/test_runtime_dependency_coverage.py` 要在提交前就发现
"代码 import 了而依赖表没写"，而 `build_tools/check_frozen_bundle.py` 要在打包后确认那些包
**真的冻进了 exe**。两边问的是同一个问题（这个程序启动时离不开哪些第三方模块），
各写一份就等于两份会各自腐烂的真相——**只测声明、或者只测产物，都会漏掉另一半**。

## 这里量的是"启动必需"，不是"代码里出现过"

三层过滤，每一层都对应一种**真实存在**的依赖形态：

1. **模块层**。本项目侧栏 26 页是懒加载的，所以函数体里的 import 属于"用到那个功能
   才缺"（`weapon_row_widget._apply_theme_styles()` 里的 `shiboken6`、
   `magnifier_page` 里的 `mouse`）。把它们算成硬依赖，等于替作者做决定：装上去就默认
   启用了一条他特意留了降级路径的分支。
2. **未被守卫**。`try: import X / except ImportError:` 声明的是"缺了也继续跑"。仓库里
   有一批这样的可选依赖：`mutagen`（取不到时长音频信息）、`scipy`（重采样退化成线性
   插值）、`shiboken6`、`pyi_splash`（仅 onefile）、`account_help`（开源裁剪删掉了账号模块）。
3. **不是标准库、也不是仓库自己的模块**。

事故 `v2.3.1` 死在第 1、2 层都没拦住的地方：`gsi_server.py:7` 的
`from flask import Flask, request, jsonify` 在**文件顶层、未被守卫**，而 GSI 接收端由主
窗口启动——缺它程序起不来。`requirements_qt.txt` 只装了 Qt 那一半，exe 里根本没有 flask。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 应用代码目录。`build_tools/` / `tests/` / `scripts/` 不算——它们是构建期与开发期用的。
APP_DIRS = ("core", "pages", "widgets", "dialogs")

#: 仓库内部模块/包名：由源码提供，不该出现在任何依赖表里，也不该出现在 exe 里。
INTERNAL = frozenset({
    "config", "utils", "resource_manager", "theme_manager", "service_urls",
    "gsi_server", "gui_widget", "main_widget", "page_theme_helper",
    "background_loader", "crosshair_animation", "crosshair_overlay",
    "kill_icon_overlay", "kill_icon_player", "flash_process", "flash_process_manager",
    "music_player", "music_control_bar", "voice_output_manager", "utility_display",
    "utility_usage_tracker", "source_backup_manager", "screen_effect_overlay",
    "ui_animations", "ui_design_system", "ui_effects", "ui_focus_underline",
    "ui_help_panel", "ui_motion", "ui_osd", "ui_ripple_effect", "ui_shimmer",
    "ui_slider_bubble", "ui_style_applier", "ui_toast", "ui_toggle_switch",
    "ui_transitions", "gsi_handler_flash", "gsi_handler_fun", "gsi_handler_hud_color",
    "gsi_handler_kills", "gsi_handler_music", "gsi_handler_sounds",
    "gsi_handler_special", "gsi_handler_stats", "gsi_handler_utility",
})

#: import 名 → 发行包名。凡"两者不同名"的都在这儿，一处写清。
#: ⚠ 这是**有意的例外清单**。pip 的发行名与 import 名不同名，自动匹配必然漏。
#: 每加一个别名都该问一句：能不能反过来让 import 名与发行名一致？
IMPORT_TO_DIST = {
    "yaml": "PyYAML",
    "PIL": "pillow",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "winreg": "pywin32",
    "win32con": "pywin32",
    "win32event": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32file": "pywin32",
    "win32service": "pywin32",
    "winerror": "pywin32",
    "win32ts": "pywin32",
    "ntsecuritycon": "pywin32",
    "win32security": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "websocket": "websocket-client",
    "PySide6": "PySide6",
}

#: 接住 ImportError 的异常名（含裸 except —— 它一样是"缺了就降级"）。
_IMPORT_GUARDS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def app_files(root: Path | None = None) -> list[Path]:
    """应用代码的全部 .py 文件。"""
    root = root or PROJECT_ROOT
    files = [p for p in root.glob("*.py")
             if p.name != "setup.py" and not p.name.startswith("test_")]
    for d in APP_DIRS:
        files.extend((root / d).rglob("*.py"))
    return files


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        exc = handler.type
        if exc is None:
            return True                                  # 裸 except
        names: list[str] = []
        if isinstance(exc, ast.Name):
            names = [exc.id]
        elif isinstance(exc, ast.Tuple):
            names = [e.id for e in exc.elts if isinstance(e, ast.Name)]
        if _IMPORT_GUARDS & set(names):
            return True
    return False


def _guarded_import_nodes(tree: ast.AST) -> set[int]:
    guarded: set[int] = set()

    def walk(node: ast.AST, inside_guard: bool) -> None:
        for child in ast.iter_child_nodes(node):
            flag = inside_guard or (isinstance(child, ast.Try) and _catches_import_error(child))
            if inside_guard and isinstance(child, (ast.Import, ast.ImportFrom)):
                guarded.add(id(child))
            walk(child, flag)

    walk(tree, False)
    return guarded


def _module_level_nodes(tree: ast.AST) -> list[ast.AST]:
    """不在函数体里的节点（类体算模块层——那些 import 一样在导入时执行）。"""
    out: list[ast.AST] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue                              # 懒加载：不收
            out.append(child)
            walk(child)

    walk(tree)
    return out


def module_level_imports(root: Path | None = None) -> set[str]:
    """应用代码里所有**模块层、未被守卫**的 import 模块名。"""
    found: set[str] = set()
    for path in app_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:                            # pragma: no cover - 只在源码坏掉时
            continue
        guarded = _guarded_import_nodes(tree)
        for node in _module_level_nodes(tree):
            if id(node) in guarded:
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def third_party_imports(root: Path | None = None) -> set[str]:
    """启动必需的第三方**模块名**（import 名，用于核对 exe 里有没有）。"""
    root = root or PROJECT_ROOT
    stdlib = set(sys.stdlib_module_names)
    out: set[str] = set()
    for name in module_level_imports(root):
        if name in stdlib or name in INTERNAL:
            continue
        if (root / f"{name}.py").is_file() or (root / name / "__init__.py").is_file():
            continue                                  # 仓库自己的模块
        out.add(name)
    return out


def third_party_dists(root: Path | None = None) -> set[str]:
    """启动必需的第三方**发行包名**（用于核对 requirements 表）。"""
    return {IMPORT_TO_DIST.get(name, name) for name in third_party_imports(root)}


def dists_in(requirements: Path) -> set[str]:
    """一份 requirements 文件里出现的发行包名（小写、去分隔符），跟随 `-r` 递归。"""
    seen: set[str] = set()

    def walk(path: Path) -> set[str]:
        if path.name in seen or not path.is_file():
            return set()
        seen.add(path.name)
        names: set[str] = set()
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith(("-r ", "--requirement ")):
                names |= walk(path.parent / line.split(None, 1)[1].strip())
                continue
            name = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
            if name:
                names.add(name.lower().replace("_", "-"))
        return names

    return walk(requirements)
