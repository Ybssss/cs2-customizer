# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""打包装的那份依赖，必须同时覆盖**声明**和**产物**。

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

⭐ 所以这里有**四条**判据，而不是一条：依赖关系有两头，只查一头，另一头照样能漏。
- `requirements.txt` / `requirements_qt.txt` 覆盖了代码的 import（**声明**）
- 打包作业真的装了那份（**中间那一步**，v2.3.1 恰好漏在这里）
- `check_frozen_bundle.py` 在打包后核对产物（**产物**，CI 里跑不到）
- 运行时依赖只留一份清单，不许在 CI 那份里再抄一遍（**为什么会腐烂**）

分母：必须真的扫到应用代码和依赖表（`must_scan`），否则两边都空、差集恒为空、判据恒绿。
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    """按路径加载 build_tools 下的模块（那边不是包，本仓既有做法）。"""
    path = ROOT / "build_tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = _load("import_scan")
bundle = _load("check_frozen_bundle")


def test_third_party_imports_match_declared_dependencies():
    """每个启动必需的 import 都必须能在**打包装的那份依赖**里找到。

    这条判据在本仓库已经晚了：它本该在 v2.3.1 发出去之前就红着。
    """
    needed = scan.third_party_dists()
    installed = scan.dists_in(ROOT / "requirements.txt") | scan.dists_in(ROOT / "requirements_qt.txt")
    must_scan(needed, "应用启动必需的第三方发行包", least=8)
    must_scan(installed, "requirements.txt + requirements_qt.txt 提供的发行包", least=8)

    missing = {d for d in needed if d.lower().replace("_", "-") not in installed}
    assert not missing, (
        f"程序启动时 import 了这些包，而 requirements.txt / requirements_qt.txt 里没有："
        f"{sorted(missing)}。\n"
        "只装 requirements_qt.txt 装不出一个能跑起来的程序——requirements_qt.txt 自己"
        "就写着「核心运行依赖在 requirements.txt 里」。缺 flask 的那次，产物照样打包成功、"
        "照样发成 Release，测试全绿，只有用户双击时才炸（v2.3.1）。\n"
        "⇒ 把这些包写进 requirements.txt，并在那里留一句它是干什么用的。"
    )


def _install_run() -> str:
    """打包作业里那条 `pip install` 的**完整**命令（YAML 折行已合并）。

    ⚠ 必须走 YAML 而不是逐行找：那条命令后来被折成
    `run: >-` 加三行，`pip install --retries 10 --timeout 120` 与
    `-r requirements.txt` **分属不同的行**。逐行断言"包含 requirements.txt 的那一行"
    会在折行那一刻无声地变成查别的东西——和之前那几次"扫到了错的东西"同形。
    """
    import yaml

    data = yaml.safe_load((ROOT / ".github" / "workflows" / "build-installer.yml").read_text(encoding="utf-8"))
    steps = (data.get("jobs") or {}).get("build", {}).get("steps") or []
    runs = [str(s.get("run", "")) for s in steps if "pip install" in str(s.get("run", ""))]
    must_scan(runs, "build-installer.yml 里带 pip install 的步骤", least=1)
    return " ".join(runs)


def test_requirements_files_are_readable_by_pip_on_any_locale():
    """依赖表必须是 **ASCII**：pip 用**机器的区域代码页**解码它，而不是 UTF-8。

    **判据记下的是一次本地复现**：`requirements.txt` 最初带中文注释，在本机
    （pip 23.2.1 + GBK）直接 `UnicodeDecodeError: 'gbk' codec can't decode byte 0x80`，
    pip **连解析都没开始**。也就是说：一个以中文 Windows 为主力用户的项目，
    自己新增的依赖表在主力用户的机器上装不了。
    ⭐ 三份依赖表现在都判。`requirements_qt.txt` 是**两份 README 安装说明的第一行**，
    在本项目主力的机器上（中文 Windows，GBK）它自己就 pip 装不了——实测本机
    pip 23.2.1 读它就 UnicodeDecodeError，**解析根本没开始**。
    它的内容一字未改，只把注释换成 ASCII：包与版本约束逐条照抄。
    runner 上读得动是因为 cp1252 能解码任意字节——**能读不代表别人也读得动**。
    """
    for name in ("requirements.txt", "requirements-ci.txt", "requirements_qt.txt"):
        raw = (ROOT / name).read_bytes()
        offenders = [i for i, b in enumerate(raw) if b > 127]
        assert not offenders, (
            f"{name} 里有 {len(offenders)} 个非 ASCII 字节（第一个在偏移 {offenders[0]}）。"
            "pip 用机器的区域代码页解码依赖表：在 GBK 机器上，UTF-8 的中文可能解不出来，"
            "pip 会直接 UnicodeDecodeError，连解析都不开始。"
            "⇒ 依赖表的注释写 ASCII，叙述留在 PROGRESS.md。"
        )
        raw.decode("ascii")          # 能解，就一定不会被区域代码页难住


def test_packaging_install_retries_the_index():
    """打包那一步的 pip 必须带重试与超时。

    ⭐ 实测 run 36423164375：一次索引读超时（`/simple/click/`）被 pip 报成
    `ResolutionImpossible` + "no matching distributions available for your environment"，
    日志里那串 `flask 3.0.0…3.1.3 depends on click>=8.1.3` 看着像版本冲突，
    **极易把人引去改版本号**——而改版本号什么也修不了。
    """
    run = _install_run()
    assert "--retries" in run, (
        f"打包那一步的 pip 没有重试：{run.strip()!r}。一次索引抖动就会让发版红，"
        "而 pip 会把它报成依赖冲突（run 36423164375）。"
    )


def test_build_job_installs_the_runtime_dependency_set():
    """打包作业必须装**运行时**依赖，不只是 Qt 那一半。

    上一条量的是"代码要的有没有被声明"，这一条量的是"声明了有没有被装"。
    两边都成立，产物里才可能有那个包——事故 v2.3.1 正是两边各自都对、而**中间那一步**
    只装了 requirements_qt.txt。
    """
    run = _install_run()
    assert "requirements.txt" in run, (
        f"打包作业的 pip install 是 {run.strip()!r}，没有装 requirements.txt。"
        "那份表才是运行时依赖（flask / pygame / 热键 / 音频 / pywin32），"
        "只装 requirements_qt.txt 冻出来的 exe 起不来（事故 v2.3.1）。"
    )


def test_build_job_verifies_the_bundle_before_packaging():
    """打包作业必须在编安装包**之前**真跑一次产物核对。

    ⭐ 依赖与产物是两头：上一条量"装了什么"，这一条量"冻进去什么"——PyInstaller 漏收一个
    hidden import 时，前一条照样全绿。

    ⚠⚠ 这一格改过两次写法，两次都是**判据空转**：
    1. 第一次拿 `iscc` 当"编译那一步"的锚点，而 D19 已把那个手搓调用换成
       `build_release.py --installer-only`——锚点消失，位置比较退化成"小于文件末尾"，恒真。
    2. 第二次全文搜 `check_frozen_bundle.py` 的位置，而**注释里也有这个字符串**，
       于是"把命令改成 `echo later  # check_frozen_bundle.py`"照样绿。
    ⇒ 所以这里解析 YAML，按**步骤顺序**找，并且要求那一步的 `run` **就是**这条调用
    （前缀匹配，不接受尾部注释里挂着名字）。
    """
    import yaml

    data = yaml.safe_load((ROOT / ".github" / "workflows" / "build-installer.yml").read_text(encoding="utf-8"))
    steps = (data.get("jobs") or {}).get("build", {}).get("steps") or []
    must_scan(steps, "build-installer.yml 的 build 作业步骤", least=5)

    def index_of(predicate) -> int:
        for idx, step in enumerate(steps):
            if predicate(str(step.get("run", "")).strip()):
                return idx
        return -1

    check_at = index_of(lambda run: run.startswith("python build_tools/check_frozen_bundle.py"))
    assert check_at != -1, (
        "build-installer.yml 里没有一步**真的执行** `python build_tools/check_frozen_bundle.py`。"
        "依赖装对了不等于冻进去了——事故 v2.3.1 就是产物里没有 flask。"
    )

    anchor = "build_release.py --mode onedir --installer-only"
    assert any(anchor in str(s.get("run", "")) for s in steps), (
        f"找不到编译安装包那一步（锚点 {anchor!r}）。本条要量的是顺序，锚点没了就量不了。"
    )
    compile_at = index_of(lambda run: anchor in run)
    assert check_at < compile_at, (
        f"产物核对在第 {check_at + 1} 步、编译安装包在第 {compile_at + 1} 步——顺序反了。"
        "坏产物应当在核对那一步就停，不必先把安装包编出来再失败。"
    )


def test_bundle_check_detects_a_missing_module():
    """核对脚本本身：产物里少一个模块就必须报出来。

    ⭐ 这条是给**判据本身**做判据。事故那次的教训是"检查全绿"和"检查根本没看对地方"
    在报告上长得一模一样，所以这里喂一份**已知缺包**的合成清单，确认它会红。
    """
    required = {"flask", "pygame", "yaml"}
    present = """Options in 'app.exe' (PKG/CArchive):
 pyi-contents-directory _internal
Contents of 'app.exe' (PKG/CArchive):
 struct
 yaml
 yaml\\_yaml.cp311-win_amd64.pyd
 pygame
"""
    names = bundle.top_level_names(present)
    must_scan(names, "合成清单里解析出的顶层名", least=2)
    assert "yaml" in names and "pygame" in names
    assert "flask" not in names, "解析把 flask 读出来了，而清单里没有它"
    missing = {name for name in required if name not in names}
    assert missing == {"flask"}, f"应当只报 flask 缺失，实际报了 {sorted(missing)}"


def test_bundle_parser_sees_nested_pywin32_entries():
    """`win32\win32api.pyd` 要算作 **win32api** 在，而不是只有目录名 win32。

    ⭐ 第一次版本只取路径第一段，于是 pywin32 的扩展（它们只以
    `win32\win32api.pyd` 这种形式出现）被判成缺失——**一个完全正确的产物会被判红**。
    这和之前几次同形：判据量错了东西，看起来却像判据在工作。目录名与文件名主干
    都要记。
    """
    listing = (
        "Options in 'app.exe' (PKG/CArchive):\n"
        " pyi-contents-directory _internal\n"
        "Contents of 'app.exe' (PKG/CArchive):\n"
        " struct\n"
        " win32\\win32api.pyd\n"
        " win32\\win32gui.pyd\n"
        " win32\\win32process.pyd\n"
        " pywintypes\n"
        " pywin32_system32\\pywintypes311.dll\n"
    )
    names = bundle.top_level_names(listing)
    must_scan(names, "合成清单里解析出的名字", least=4)
    for expected in ("win32", "win32api", "win32gui", "win32process", "pywintypes"):
        assert expected in names, f"{expected} 没被解析出来，实际 {sorted(names)}"
    # 目录名与文件名主干都要在：只给其中之一，就会在另一种布局上误判
    assert "win32" in names and "win32api" in names


def test_build_puts_the_pywin32_extension_dir_on_the_analysis_path():
    """构建必须把 pywin32 的扩展目录加进 spec 的 `pathex`。

    ⭐ pywin32 把 `.pyd` 装在 `site-packages/win32/` 下，靠一个 `.pth` 把那个目录加进
    `sys.path`；**PyInstaller 的 Analysis 不执行 `.pth`**，所以它的搜索路径里没有那个
    目录 —— 于是源码里明写着 `import win32gui`，产物里也**没有**（2026-09-28 实测：
    run 36424381580 第 7 步报缺 win32api / win32gui / win32process；把该目录加进
    pathex 之后，四个模块连同 `pyi_rth_pywintypes` 一起进包）。

    所以判据盯的是"有没有把这个目录交给 PyInstaller"，而不是"有没有写死某个路径"
    ——写死路径在换机器 / 换 pip 版本时就会失效。
    """
    text = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    assert "pywin32_module_dir" in text, "build_release.py 里没有定位 pywin32 扩展目录的函数"
    assert "pywin32_pathex" in text and "pathex=[{str(stage_dir)!r}{pywin32_pathex}]" in text, (
        "spec 的 pathex 没有把 pywin32 的目录加进去 —— 产物会缺 win32api / win32gui / "
        "win32process（PyInstaller 不执行 .pth）。"
    )
    for mod in ("pywintypes", "win32api", "win32gui", "win32process"):
        assert f'"{mod}"' in text, f"hidden imports 里少了 {mod}"


def test_bundle_check_reads_both_storage_locations(tmp_path):
    """onedir 的纯 Python 在 exe 的 PYZ 里，C 扩展在 `_internal/` —— 两处都要看。

    只看其中一处，就会对另一种包给出假红；而在 v2.3.1 那种"缺包"的事故里，
    假红至少是吵的，**假绿是致命的**。
    """
    internal = tmp_path / "_internal"
    (internal / "win32api").mkdir(parents=True)
    (internal / "win32api" / "win32api.pyd").write_bytes(b"x")
    (internal / "soundfile").mkdir(parents=True)
    (internal / "soundfile" / "soundfile.pyd").write_bytes(b"x")
    found = bundle.internal_top_level(internal)
    must_scan(found, "_internal 里的顶层名", least=2)
    assert found == {"win32api", "soundfile"}, found


def test_bundle_check_refuses_to_pick_between_several_builds(tmp_path):
    """`release/` 下有多个候选时必须失败，而不是挑一个。

    挑一个就意味着可能核到**上一版的产物**，然后给出一个关于错误包名的结论——
    而报告里看不出核的是哪个。
    """
    for name in ("CS2 Customizer 2.3.0", "CS2 Customizer 2.3.1"):
        d = tmp_path / "release" / name
        d.mkdir(parents=True)
        (d / "CS2 Customizer.exe").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="多于一个"):
        bundle.find_exe(tmp_path)


def test_main_passes_the_discovered_exe_not_the_parsed_argument(tmp_path, monkeypatch, capsys):
    """不传参调用时，传给 archive_viewer 的必须是**找到的那个** exe，而不是 None。

    ⭐ 这是判据记下的第三次"指向了错的东西"：2026-09-28 的 run 36422318501 第 7 步，
    脚本明明找到了产物、还把它打印了出来，却把 `args.exe`（不传参时就是 `None`）交给了
    archive_viewer，于是 `Archive None does not exist!`。那次重构改了三个用到 exe 的地方，
    **只改了两个**——而当时所有判据都在量别的：解析器、`find_exe` 的"多于一个"分支、
    cp1252 打印。**没有一条走 main() 的发现路径。**

    所以这里盯的不是某一行文本，而是"main 不传参时**真正传下去的对象**是哪个"。
    """
    exe = tmp_path / "CS2 Customizer 9.9.9" / "CS2 Customizer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")

    seen: dict[str, object] = {}

    monkeypatch.setattr(bundle, "find_exe", lambda root=None: exe)
    monkeypatch.setattr(bundle, "third_party_imports", lambda: {"flask"})
    monkeypatch.setattr(
        bundle, "archive_listing",
        lambda path, python=None: seen.setdefault("exe", path) and "" or "flask\n")
    monkeypatch.setattr(bundle, "internal_top_level", lambda d: set())

    code = bundle.main([])
    capsys.readouterr()

    assert seen.get("exe") == exe, (
        f"传给 archive_viewer 的是 {seen.get('exe')!r}，应当是找到的产物 {exe}。"
        "把 args.exe 传给归档读取，就是 run 36422318501 里那个 `Archive None does not exist!`。"
    )
    assert code == 0, f"模块齐了应当返回 0，实际 {code}"


def test_main_fails_when_a_module_is_absent_from_the_bundle(tmp_path, monkeypatch, capsys):
    """反向：产物里真的少一个模块时，main 必须红，且把缺的那个点名。"""
    exe = tmp_path / "CS2 Customizer 9.9.9" / "CS2 Customizer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")

    monkeypatch.setattr(bundle, "find_exe", lambda root=None: exe)
    monkeypatch.setattr(bundle, "third_party_imports", lambda: {"flask", "pygame"})
    monkeypatch.setattr(bundle, "archive_listing", lambda path, python=None: "pygame\n")
    monkeypatch.setattr(bundle, "internal_top_level", lambda d: set())

    code = bundle.main([])
    out = capsys.readouterr()

    assert code == 1, f"缺包时必须返回 1，实际 {code}"
    assert "flask" in out.err, f"报错要点名缺的是 flask，实际 stderr:\n{out.err[:300]}"


def test_bundle_check_can_print_on_a_cp1252_console(tmp_path):
    """核对脚本在 cp1252 控制台上必须能**打印**,而不是死在打印上。

    **判据记下的是一次真实运行**（run 36418436440，第 7 步）：脚本在打第一行中文日志时
    就 `UnicodeEncodeError` 退出了，一次比较都没做——而报告上只是一个退出码 1，
    和"检查通过"在报告上**一模一样**。

    ⭐ 这是本项目里第二次栽在同一个坑（第一次是 release.yml 的发布说明，见 D7），
    而第一次已经把原因写在注释里了。写新脚本时没去看同类脚本怎么处理——**它不会提醒你**。

    ⚠⚠ 这条判据第一版量错了流：它只让脚本走**失败分支**，而那条分支写的是 stderr。
    实测在 Windows 上 `PYTHONIOENCODING=cp1252` 会让 **stdout** 炸掉，而 stderr 仍是
    UTF-8——所以第一版在删掉修复之后**照样全绿**。现在这条盯的是 runner 上真正炸掉的那条
    路径：脚本成功分支的第一行 `[INFO] 核对产物: …`，走 stdout。
    """
    import os

    dummy = tmp_path / "CS2 Customizer.exe"
    dummy.write_bytes(b"not really an archive")
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    result = subprocess.run(
        [sys.executable, str(ROOT / "build_tools" / "check_frozen_bundle.py"), str(dummy)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, check=False,
    )
    output = result.stdout + result.stderr
    assert "UnicodeEncodeError" not in output, (
        "核对脚本在 cp1252 控制台上死于打印自己的中文日志——"
        f"它因此一次比较都没做，却只留下一个退出码 {result.returncode}，"
        "和检查通过在报告上无法区分。stdout 是真正炸掉的那条流，别只测 stderr。"
    )
    assert "核对产物" in result.stdout, (
        f"脚本连第一行中文 INFO 都没打出来，stdout:\n{result.stdout[:400]}"
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
    print(sorted(scan.third_party_dists()))
    r = subprocess.run([sys.executable, str(ROOT / "build_tools" / "check_frozen_bundle.py")])
    raise SystemExit(r.returncode)
