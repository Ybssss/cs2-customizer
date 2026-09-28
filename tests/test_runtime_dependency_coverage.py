# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""打包装的那份依赖，必须覆盖程序**真正 import** 的每一个第三方包。

**判据记下的是一次已经发出去的事故。** 2026-09-28，本仓库第一个成功发布的 Release
（v2.3.1）双击即崩：

    Failed to execute script 'main_widget' due to unhandled exception:
    No module named 'flask'

根因不是"忘了写一行 flask"，而是**三份依赖表各说各话**：

    requirements_qt.txt   只有 Qt 专用包，并且**逐字写着**
                          「核心运行依赖在 requirements.txt 里（不是 Qt 专用）
                            … pygame（音频系统）… **flask（GSI 服务器）** …」
    requirements.txt      ← **开源裁剪时没带进来**，README 指的那个文件根本不存在
    requirements-ci.txt   把上面那些包**又抄了一遍**，于是 CI 装得到、打包装不到

`gsi_server.py:7` 是顶层 `from flask import Flask, request, jsonify`，而 GSI 接收端由
主窗口启动 —— 缺 flask 不是"某个功能不可用"，是**程序根本起不来**。CI 全绿是因为它装的是
那份抄了一遍的表。

⭐ 这条判据防的不是"某一行依赖忘了写"，而是**"依赖清单和代码各有一份真相"**：
清单不完整时，测试全绿、构建成功、产物照样发出去，只有用户双击时才炸。
所以这里量的是**代码里 import 的东西**与**打包装的东西**这两个集合的差，而不是某一行文本。

分母：必须真的扫到应用代码和依赖表（`must_scan`），否则两边都空，差集恒为空、判据恒绿。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

ROOT = Path(__file__).resolve().parent.parent

#: 应用代码目录。build_tools/ 与 tests/ 不算——它们是构建期与测试期用的依赖。
APP_DIRS = ("core", "pages", "widgets", "dialogs")

#: import 名 → 发行包名。凡是"两者对不上"的都在这儿，一处写清，不散落在各处。
#: ⚠ 这张表是**有意的例外清单**：pip 的发行名与 import 名不同名，靠自动匹配会漏。
#: 每加一个别名都该问一句"能不能反过来让 import 名和发行名一致"。
IMPORT_TO_DIST = {
    "yaml": "PyYAML",          # import yaml, 装 PyYAML
    "PIL": "pillow",           # import PIL, 装 pillow
    "win32api": "pywin32",     # Windows 专用后端
    "win32com": "pywin32",
    "winreg": "pywin32",
    "win32con": "pywin32",
    "win32event": "pywin32",
    "pywintypes": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32file": "pywin32",
    "win32service": "pywin32",
    "winerror": "pywin32",
    "win32ts": "pywin32",
    "ntsecuritycon": "pywin32",
    "win32security": "pywin32",
    "pythoncom": "pywin32",
    "websocket": "websocket-client",
    "PySide6": "PySide6",     # 同名,列出来是为了让"这张表覆盖了全部非同名情况"可核对
}

#: 仓库内部模块/包名：它们由源码提供，不该出现在任何依赖表里。
INTERNAL = {
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
}


def _dists_in(path: Path, seen: set[str] | None = None) -> set[str]:
    """一份 requirements 文件里出现的发行包名（小写去分隔符），跟随 `-r` 递归。"""
    seen = seen if seen is not None else set()
    if path.name in seen:
        return set()
    seen.add(path.name)
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            target = line.split(None, 1)[1].strip()
            names |= _dists_in(path.parent / target, seen)
            continue
        name = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def _guards_imports(tree: ast.AST) -> set[int]:
    """哪些 import 节点处在"缺了就降级"的 try 里。

    ⭐ 这是本判据最要紧的一处区分，判错哪边都会造成真实损害：
    - **没被守卫的** import = 硬依赖。缺了它程序起不来（`gsi_server.py:7` 的 flask 就是），
      必须写进依赖表。
    - **被守卫的** import = 有意的可选依赖。仓库里有一批：`mutagen`（取不到时长���信息，
      music_player.py 走 try/except）、`mouse`（core/hotkeys/registry.py）、
      `scipy`（voice_output_manager.py 的重采样，退化成线性插值）、`shiboken6`
      （PySide6 自带，缺了只降级预热）、`pyi_splash`（only in a onefile bundle）、
      `account_help`（开源裁剪时删掉了账号模块，这里显式 `except ImportError: pass`）。

    把可选依赖塞进依赖表是**改变产品行为**：装上去就等于默认启用一条作者特意留了降级
    路径的代码分支。反过来把硬依赖漏掉，就是 v2.3.1 那个装不起来的 exe。
    """
    guarded: set[int] = set()

    def walk(node: ast.AST, inside_guard: bool) -> None:
        for child in ast.iter_child_nodes(node):
            flag = inside_guard
            if isinstance(child, ast.Try) and _catches_import_error(child):
                flag = True
            if inside_guard and isinstance(child, (ast.Import, ast.ImportFrom)):
                guarded.add(id(child))
            walk(child, flag)

    walk(tree, False)
    return guarded


def _catches_import_error(node: ast.Try) -> bool:
    """这个 try 是否接住了 ImportError（裸 except 也算——它一样是"缺了就降级"）。"""
    for handler in node.handlers:
        exc = handler.type
        names: list[str] = []
        if exc is None:
            return True                                  # 裸 except
        if isinstance(exc, ast.Name):
            names = [exc.id]
        elif isinstance(exc, ast.Tuple):
            names = [e.id for e in exc.elts if isinstance(e, ast.Name)]
        if {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"} & set(names):
            return True
    return False


def _imported_modules() -> set[str]:
    """应用代码里所有**模块层、未被守卫**的 import 模块名。

    ⭐ 为什么只算模块层：函数体里的 import 是**懒加载**。本项目页面本来就是懒加载的
    （README：「侧栏 26 项，一页一文件，懒加载」），所以函数体里的 import 意味着
    "用到那个功能时才会缺"——`weapon_row_widget._apply_theme_styles()` 里的
    `shiboken6`、`magnifier_page` 里的 `mouse` 都属于这一类，它们是**特性级**依赖。

    而 v2.3.1 那个事故是**模块层**的硬依赖：`gsi_server.py:7` 的
    `from flask import Flask, request, jsonify` 在文件顶层，而 GSI 接收端由主窗口
    启动 —— 缺它程序**根本起不来**。

    判据要量的是"启动必需"，所以只算模块层。把懒加载的包也塞进依赖表是**改变产品
    行为**：装上去就等于默认启用一条作者特意留了降级路径的分支。
    """
    files = [p for p in ROOT.glob("*.py")
             if p.name not in ("setup.py",) and not p.name.startswith("test_")]
    for d in APP_DIRS:
        files.extend((ROOT / d).rglob("*.py"))
    must_scan(files, "应用代码（根目录 + core/pages/widgets/dialogs）", least=50)

    found: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:                     # pragma: no cover - 只在源码坏掉时发生
            continue
        guarded = _guards_imports(tree)
        for node in _module_level_nodes(tree):
            if id(node) in guarded:
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:   # 0 = 绝对导入；level>0 是包内相对导入
                    found.add(node.module.split(".")[0])
    must_scan(found, "应用代码里模块层且未被守卫的 import 模块名", least=10)
    return found


def _module_level_nodes(tree: ast.AST) -> list[ast.AST]:
    """不在任何函数 / 类方法体里的节点（类体本身算模块层——那些 import 一样在导入时执行）。"""
    out: list[ast.AST] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue                      # 懒加载：不收
            if isinstance(child, ast.ClassDef):
                out.append(child)
                walk(child)
                continue
            out.append(child)
            walk(child)

    walk(tree)
    return out


def _third_party(modules: set[str]) -> set[str]:
    """把 import 名过滤成"第三方发行包名"的集合。"""
    stdlib = set(sys.stdlib_module_names)
    dists: set[str] = set()
    for name in modules:
        if name in stdlib or name in INTERNAL:
            continue
        if (ROOT / f"{name}.py").is_file() or (ROOT / name / "__init__.py").is_file():
            continue                                   # 仓库自己的模块
        dists.add(IMPORT_TO_DIST.get(name, name))
    must_scan(dists, "应用依赖的第三方发行包", least=8)
    return dists


def test_third_party_imports_match_declared_dependencies():
    """每个第三方 import 都必须能在**打包装的那份依赖**里找到。

    这条判据在本仓库已经晚了：它本该在 v2.3.1 发出去之前就红着。

    ⚠ **它有一条真实的漏法，方向和直觉相反**：把硬依赖的 import 包进
    `try/except ImportError`，这条判据就绿了——因为"被守卫的 import"按定义就是可选依赖。
    这不是漏洞，是判据在如实反映代码的**声明**：代码说了"缺了也继续跑"，依赖表就该信它。
    但要清楚那意味着什么——那是一条**降级路径**，不是修复：GSI 接收端会静默失效，
    而 v2.3.1 的症状（起不来）会换成另一个更难查的症状。所以真要走这条路，
    请在 PROGRESS.md 里写明"flask 变成可选"是有意为之，并说明缺它时程序如何表现。
    """
    needed = _third_party(_imported_modules())
    installed = _dists_in(ROOT / "requirements.txt") | _dists_in(ROOT / "requirements_qt.txt")
    must_scan(installed, "requirements.txt + requirements_qt.txt 提供的发行包", least=8)

    missing = {d for d in needed if d.lower().replace("_", "-") not in installed}
    assert not missing, (
        f"程序 import 了这些包，而 requirements.txt / requirements_qt.txt 里没有："
        f"{sorted(missing)}。\n"
        "只装 requirements_qt.txt 装不出一个能跑起来的程序——requirements_qt.txt 自己"
        "就写着「核心运行依赖在 requirements.txt 里」。缺 flask 的那次，产物照样打包成功、"
        "照样发成 Release，测试全绿，只有用户双击时才炸（v2.3.1）。\n"
        f"⇒ 把这些包写进 requirements.txt，并在那里留一句它是干什么用的。"
    )


def test_build_job_installs_the_runtime_dependency_set():
    """打包作业必须装**运行时**依赖，不只是 Qt 那一半。

    上一条量的是"代码要的有没有被声明"，这一条量的是"声明了有没有被装"。
    两边都成立，产物里才可能有那个包——事故 v2.3.1 正是两边各自都对、而**中间那一步**
    只装了 requirements_qt.txt。
    """
    run = "\n".join(
        line for line in
        (ROOT / ".github" / "workflows" / "build-installer.yml").read_text(encoding="utf-8").splitlines()
        if "pip install" in line and not line.lstrip().startswith("#")
    )
    must_scan([run], "build-installer.yml 里的 pip install 行", least=1)
    assert "requirements.txt" in run, (
        f"打包作业的 pip install 是 {run.strip()!r}，没有装 requirements.txt。"
        "那份表才是运行时依赖（flask / pygame / 热键 / 音频 / pywin32），"
        "只装 requirements_qt.txt 冻出来的 exe 起不来（事故 v2.3.1）。"
    )


def test_runtime_dependencies_are_declared_in_exactly_one_place():
    """运行时依赖只留一份清单，不许在 requirements-ci.txt 里再抄一遍。

    ⭐ 事故的形状不是"少了一行"，而是**同一份依赖写了两遍**：`requirements-ci.txt`
    抄了一份运行时包，CI 装得到、打包装不到，于是 CI 恒绿而产物恒缺。抄第二份的那一刻，
    两边就开始各烂各的。
    """
    ci_text = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in ci_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    for dup in ("flask", "pygame", "keyboard", "pynput", "pywin32", "sounddevice", "numpy"):
        assert not re.search(rf"^{re.escape(dup)}\b", code, re.M | re.I), (
            f"requirements-ci.txt 里又有 {dup} 了。运行时依赖只该在 requirements.txt 里"
            "存在一份——抄第二份的代价是 CI 装得到、打包装不到（事故 v2.3.1）。"
        )
    assert "-r requirements.txt" in code, (
        "requirements-ci.txt 没有引用 requirements.txt，于是运行时依赖在 CI 侧无人安装"
    )


def test_the_file_requirements_qt_points_at_exists():
    """`requirements_qt.txt` 自己承诺的那个文件必须真的存在。

    requirements_qt.txt 里那句「核心运行依赖在 requirements.txt 里」是一句**承诺**。
    开源裁剪时那个文件没带进来，承诺就悬空了——而所有读代码的人（包括我）都会以为
    装完 requirements_qt.txt 就能跑。
    """
    qt = (ROOT / "requirements_qt.txt").read_text(encoding="utf-8")
    if "requirements.txt" not in qt:
        pytest.skip("requirements_qt.txt 不再提 requirements.txt，这条判据的依据没了")
    assert (ROOT / "requirements.txt").is_file(), (
        "requirements_qt.txt 说「核心运行依赖在 requirements.txt 里」，而那个文件不存在。"
        "于是只装 requirements_qt.txt 装不出能跑的程序（事故 v2.3.1 缺 flask）。"
    )


if __name__ == "__main__":  # pragma: no cover
    print(sorted(_third_party(_imported_modules())))
