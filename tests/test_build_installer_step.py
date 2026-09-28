# SPDX-License-Identifier: GPL-3.0-or-later
"""安装包构建步骤（build_release.build_installer / ISCC 定位）。

背景：2.2.3 发版时因为只在 PATH 和 Program Files 里找 ISCC.exe，误判成"没装
Inno Setup、安装包做不了"，实际它装在 %LOCALAPPDATA%\\Programs 下。这批用例锁住
定位逻辑和三道前置判断，让同样的误判不会再以"沉默失败"的形式出现。

定位逻辑本身住在 `build_tools/inno_setup.py`：打包脚本和安装态冒烟共用一份。
在此之前两边各写了一套，装了 Inno Setup 7 的机器上一边找得到一边找不到——
所以这里除了量行为，还钉了一条"不许再长出第二份实现"的判据。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_build_release():
    # build_tools 不是包，按路径直接加载模块。
    module_path = PROJECT_ROOT / "build_tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_release = _load_build_release()

# build_release 导入时把 build_tools 挂进了 sys.path 并 import 了 inno_setup。
# 这里必须拿到**同一个模块对象**：另起一份副本的话，monkeypatch 打在副本上，
# 下面每一条 find_tool 判据都会变成假绿。
inno_setup = sys.modules["inno_setup"]


# ---------------------------------------------------------------- ISCC 定位


def test_inno_roots_include_localappdata_programs(monkeypatch):
    """用户级安装（仅为我安装）落在 %LOCALAPPDATA%\\Programs —— 就是被漏掉的那个。"""
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")

    roots = inno_setup.inno_setup_roots()

    assert Path(r"C:\Users\someone\AppData\Local\Programs") in roots
    assert Path(r"C:\Program Files") in roots
    assert Path(r"C:\Program Files (x86)") in roots


def test_inno_roots_skip_unset_env(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")

    assert inno_setup.inno_setup_roots() == [Path(r"C:\Program Files (x86)")]


def test_find_iscc_locates_user_level_install(tmp_path, monkeypatch):
    """PATH 上没有、但用户目录里装了 —— 必须能找到（这正是 2.2.3 踩的坑）。"""
    programs = tmp_path / "Local" / "Programs"
    iscc = programs / "Inno Setup 6" / "ISCC.exe"
    iscc.parent.mkdir(parents=True)
    iscc.write_text("stub", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(inno_setup.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") == str(iscc)


def test_find_iscc_prefers_path_when_available(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(inno_setup.shutil, "which", lambda _name: r"D:\onpath\ISCC.exe")

    assert build_release.find_tool("iscc") == r"D:\onpath\ISCC.exe"


def test_find_iscc_prefers_newer_major_version(tmp_path, monkeypatch):
    """目录名带主版本号，用通配匹配 —— 装了 7 也不用改代码。"""
    programs = tmp_path / "Programs"
    for version in ("5", "6", "7"):
        target = programs / f"Inno Setup {version}" / "ISCC.exe"
        target.parent.mkdir(parents=True)
        target.write_text("stub", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(inno_setup.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") == str(programs / "Inno Setup 7" / "ISCC.exe")


def test_find_iscc_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(inno_setup.shutil, "which", lambda _name: None)

    assert build_release.find_tool("iscc") is None


def test_missing_message_names_every_searched_root(monkeypatch):
    """报错文案由共用模块出，逐条列出找过哪儿 —— 只说"找不到"会被读成"没装"。"""
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    message = inno_setup.missing_iscc_message()

    assert r"C:\Users\someone\AppData\Local\Programs" in message
    assert r"C:\Program Files" in message
    assert "PATH" in message


# -------------------------------------------------- 定位逻辑只许有一份实现


def test_smoke_installer_shares_the_one_locator():
    """安装态冒烟必须用同一个定位函数，不许自己再写一套。

    这条守的正是本次合并前的状态：`smoke_installer.py` 把 "Inno Setup 6" 钉死在
    三条候选路径里，装了 7 的机器上打包能跑、冒烟说"没装"，而且不肯讲它找过哪儿。
    """
    if sys.platform != "win32":
        pytest.skip("smoke_installer 依赖 winreg，仅 Windows")
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import smoke_installer
    finally:
        sys.path.pop(0)

    assert smoke_installer.find_iscc is inno_setup.find_iscc
    assert smoke_installer.missing_iscc_message is inno_setup.missing_iscc_message


def test_no_second_hardcoded_iscc_locator():
    """全仓只许有一处拼 `ISCC.exe` 的代码，就是共用模块那处。

    源码级判据，因为退化方式是"有人又在别处贴了一份"——那种重复只有在
    装了新版本的机器上才会暴露，而打包机上永远复现不出来。
    量的是 `ISCC.exe` 这个文件名字面量：拼它 = 在自己找编译器。
    散文里提"Inno Setup 7"不算，那不构成第二份实现。
    """
    offenders = []
    candidates = must_scan(
        sorted(PROJECT_ROOT.glob("build_tools/**/*.py"))
        + sorted(PROJECT_ROOT.glob("scripts/**/*.py")),
        "build_tools/**/*.py + scripts/**/*.py", least=20)
    for path in candidates:
        if path.name == "inno_setup.py":
            continue
        if "ISCC.exe" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert not offenders, (
        "这些文件里又出现了 ISCC.exe 的路径拼装，"
        f"定位逻辑该只在 build_tools/inno_setup.py 一处: {offenders}"
    )


# ------------------------------------------------------------ build_installer


STUB_ISS = "\n".join([
    "; stub",
    "OutputDir=..\\release\\installer",
    "OutputBaseFilename=CS2 Customizer 安装包_{#AppVersion}",
])


@pytest.fixture
def staged(tmp_path):
    """一个刚好能过前置检查的最小项目树。"""
    (tmp_path / "build_tools").mkdir()
    (tmp_path / "build_tools" / "installer.iss").write_text(STUB_ISS, encoding="utf-8")
    (tmp_path / "release" / "CS2 Customizer 9.9.9").mkdir(parents=True)
    return tmp_path


# ------------------------------------------------- 产物名由 installer.iss 说了算


def test_expected_path_follows_iss_declaration(tmp_path):
    """换了品牌/命名风格（开源版是 CS2Customizer-Setup-X）也要跟着走，不能写死。"""
    iss = tmp_path / "installer.iss"
    iss.write_text(
        "OutputDir=..\\release\\installer\nOutputBaseFilename=CS2Customizer-Setup-{#AppVersion}\n",
        encoding="utf-8",
    )

    result = build_release.expected_installer_path(iss, "3.1.4")

    assert result.name == "CS2Customizer-Setup-3.1.4.exe"
    assert result.parent == (tmp_path.parent / "release" / "installer").resolve()


def test_expected_path_rejects_iss_without_output_name(tmp_path):
    iss = tmp_path / "installer.iss"
    iss.write_text("OutputDir=..\\release\\installer\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="OutputBaseFilename"):
        build_release.expected_installer_path(iss, "1.0.0")


def test_real_iss_output_name_is_derivable():
    """仓库里真实的 installer.iss 必须能被解析出产物名（改了排版别把它弄哑）。"""
    iss = PROJECT_ROOT / "build_tools" / "installer.iss"
    result = build_release.expected_installer_path(iss, "9.9.9")

    assert result.name.endswith("9.9.9.exe")
    assert result.parent.name == "installer"


def test_installer_reports_where_it_searched(staged, monkeypatch):
    """找不到编译器时，报错必须**点名找过哪些地方** —— 否则又会被读成"没装"。"""
    monkeypatch.setattr(build_release, "find_tool", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    with pytest.raises(RuntimeError) as exc:
        build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")

    message = str(exc.value)
    assert r"C:\Users\someone\AppData\Local\Programs" in message
    assert "ISCC.exe" in message


def test_installer_rejects_missing_onedir_before_invoking_iscc(staged, monkeypatch):
    """源目录不在就该自己先拦下，而不是把一句路径错误甩给 Inno。"""
    calls = []
    monkeypatch.setattr(build_release, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    with pytest.raises(RuntimeError, match="onedir 产物不存在"):
        build_release.build_installer(staged, "1.0.0", "CS2 Customizer 1.0.0")

    assert calls == [], "前置未通过时不应该调起 ISCC"


def test_installer_passes_version_from_caller(staged, monkeypatch):
    """/DAppVersion 必须来自传入版本号 —— 这是防"打出上一版安装包"的关键一环。"""
    recorded = {}

    # ⚠ 这个替身必须跟着 build_release.run() 的签名走。2026-09-28 给 run() 加了
    # `capture` 关键字（ISCC 的输出必须留下来，见 run() 的 docstring），而这里写死了
    # 三个参数，于是 run 变成 TypeError 而不是编译失败 —— 报在**测试替身**上，
    # 真正的编译器一个字都没跑到。
    def fake_run(cmd, cwd=None, check=True, capture=False):
        recorded["cmd"] = cmd
        recorded["capture"] = capture
        out = staged / "release" / "installer" / "CS2 Customizer 安装包_9.9.9.exe"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 2048)

    monkeypatch.setattr(build_release, "run", fake_run)
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    result = build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")

    assert "/DAppVersion=9.9.9" in recorded["cmd"]
    assert recorded["cmd"][0] == r"C:\fake\ISCC.exe"
    # 编译器是唯一必须留输出的一处：run 36411234329 里 ISCC 退出码 2 而日志一个字没有，
    # 整条链路上"为什么不编译"的信息就这么没了。
    assert recorded["capture"] is True, (
        "调 ISCC 时没有开 capture —— 编译器的诊断信息会被吞掉，"
        "下次失败时又只剩一个退出码（事故 run 36411234329）"
    )
    assert result.name == "CS2 Customizer 安装包_9.9.9.exe"


def test_installer_fails_when_output_missing(staged, monkeypatch):
    """ISCC 退出码 0 但产物不在 —— 不能当成功报出去。"""
    monkeypatch.setattr(build_release, "run", lambda *a, **k: None)
    monkeypatch.setattr(build_release, "find_tool", lambda _name: r"C:\fake\ISCC.exe")

    with pytest.raises(RuntimeError, match="产物不在"):
        build_release.build_installer(staged, "9.9.9", "CS2 Customizer 9.9.9")


# ------------------------------------------------------- run(): 子进程的输出


def test_run_prints_child_output_even_when_it_fails(capsys):
    """子进程的话必须出现在日志里 —— **失败时尤其**。

    **判据记下的是一次真实事故**（2026-09-28，release run 36411234329）：ISCC 返回退出码 2，
    而日志里除了 `returned non-zero exit status 2` **一个字都没有**。编译器自己说了什么被
    整段吞掉，于是"为什么不编译"这件事只能靠猜 —— 而这条判据要防的正是下一次同样的猜。

    ⭐ 这里测的是 `run()` **本身**的行为，不是它的调用点。早先这里只有"调用点传了
    `capture=True`"一条判据：把 `run()` 签名里的 `capture` 删掉，**31 条用例照样全绿**
    （调用点被 monkeypatch 的替身挡着，真函数从没被执行过）。签名与调用点各断一半而
    两边都不响，正是这条判据当初够不着的地方。
    """
    with pytest.raises(subprocess.CalledProcessError) as exc:
        build_release.run(
            [
                sys.executable,
                "-c",
                "import sys; print('child-stdout-line'); "
                "print('child-stderr-line', file=sys.stderr); sys.exit(3)",
            ],
            capture=True,
        )
    assert exc.value.returncode == 3
    printed = capsys.readouterr().out
    assert "child-stdout-line" in printed, "子进程的 stdout 没被打印出来"
    assert "child-stderr-line" in printed, "子进程的 stderr 没被打印出来 —— 编译器的错通常走这里"


def test_run_capture_is_off_by_default_and_reaches_subprocess(monkeypatch):
    """默认**不**抓取，且这个选择真的传到了 subprocess。

    抓取的代价是那段时间日志全程沉默，构建卡住时连"它还活着吗"都看不出来。所以默认关，
    只在编译器那一处显式打开（见 `test_installer_passes_version_from_caller`）。

    ⚠ 这条判据量的不是"输出出现在哪儿"，而是**`run()` 传下去的参数**。先前一版是用
    capsys 去断言"没打印"，结果它量的是 pytest 的捕获管道、不是 `run()` 的行为 ——
    换一套捕获插件就会假红假绿。子进程写的是操作系统层的句柄，从 Python 层断言它
    "没被打印"这件事本身就不成立。
    """
    seen: list[dict] = []

    def fake_sp_run(cmd, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", fake_sp_run)

    build_release.run(["no-such-command"])
    assert seen[-1].get("capture_output") is False, "默认竟然抓取了子进程输出"

    build_release.run(["no-such-command"], capture=True)
    assert seen[-1].get("capture_output") is True, "capture=True 没有传到 subprocess"


def test_run_does_not_raise_when_check_is_off(monkeypatch):
    """`check=False` 时退出码非零也不该抛 —— 否则调用方没法自己判断。"""
    def fake_sp_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, "", "boom")

    monkeypatch.setattr(build_release.subprocess, "run", fake_sp_run)

    result = build_release.run(["no-such-command"], check=False, capture=True)
    assert result.returncode == 2


# ------------------------------------------------------------- installer.iss


def test_installer_iss_is_utf8_with_bom():
    """installer.iss 必须是**带 BOM 的 UTF-8** —— 这是 ISCC 读它的前提。

    **判据记下的是一次真实事故**（2026-09-28，release run 36411234329）：ISCC 退出码 2，
    编译失败。根因之一就是这个：ISCC 对**没有 BOM** 的 .iss 按**系统 ANSI 代码页**解码，
    而这份文件里有 2811 个非 ASCII 字节（`AppPublisher` 里的中文，加上整个 `[Messages]` 段）。
    于是同一份文件在两种机器上判若两物：

    - 开发机（中文 Windows，cp936）：按 GBK 误解码，字符串变花，但**照样编得过**；
    - GitHub 的 windows runner（en-US，cp1252）：解出来的字节大半无意义，
      `0x81/0x8D/0x8F/0x90/0x9D` 在 cp1252 里是未定义字节 —— 编译直接失败。

    ⭐ 这就是"在我机器上是好的"最标准的一种形态：文件本身没改过，环境一换就炸。
    带 BOM 之后 ISCC 走 UTF-8，与代码页无关，两边结果一致。
    """
    raw = (PROJECT_ROOT / "build_tools" / "installer.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), (
        "installer.iss 少了 UTF-8 BOM。没有 BOM 时 ISCC 按系统 ANSI 代码页解码这个文件，"
        "而它含有大量中文（AppPublisher 与整个 [Messages] 段）：中文 Windows 上编得过，"
        "cp1252 的 CI runner 上编不过（事故 run 36411234329）。"
    )
    # 有 BOM 还得真能按 UTF-8 解出来，否则只是加了三字节没意义的标记。
    text = raw.decode("utf-8")
    assert "\ufeff" == text[0], "BOM 应当被解码成 U+FEFF 落在首字符"
    assert "AppPublisher" in text, "解码之后还得认得出这是那份安装脚本"



def test_iss_has_no_stale_version_fallback():
    """installer.iss 不得再有写死的版本兜底常量（会静默打出上一版安装包）。"""
    text = (PROJECT_ROOT / "build_tools" / "installer.iss").read_text(encoding="utf-8")

    assert "#error" in text, "漏传 /DAppVersion 时必须响亮失败"
    assert "#define AppVersion" not in text, "兜底常量会随版本腐烂，只能由外部传入"
