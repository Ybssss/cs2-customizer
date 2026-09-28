# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""发版流水线的接线判据。

**为什么需要它**：`release.yml` 会在**push 到 main** 时自动跑，并由它代表仓库对外发布
一个可下载执行的二进制、顺带打上 tag。这类接线一旦写错，失败方式**全是静默的**：

- `publish` 不 `needs: build` → 用一个空 `dist/` 建 Release，页面显示发布成功，
  附件下载却是 404。**看起来成功比失败更贵**。
- 顶层权限忘了收敛成只读、`publish` 也忘了 `contents: write` → `gh` 报 403，
  而失败点被埋在一大段构建日志末尾。
- 谁把别的作业也提权到 `contents: write`，就等于让要跑 PyInstaller / Inno / choco install
  的构建拿到可写令牌——那正是本仓库反复写在注释里的供应链红线。
- 第三方 action 有人顺手改成 `@v4`（可移动引用）→ 上游重打 tag，我们下一次发版
  静默跑到不同的代码上。
- **少了 preflight 短路**：不抬版本的 push 也会起一台 Windows runner 跑十分钟 PyInstaller，
  一次都不发布。这是浪费，不是正确性事故——所以它排在正确性之后，但同样会被下一个人
  改没。

`ci.yml` 与 `build-installer.yml` 各有一个 `workflow_call` 入口，好让发版复用同一条打包
链路而不是复制一遍——复制那条路的代价是：本地修好了、发版那条还是坏的。

**扫描范围**：涉及 bash 内容的判据都量到**具体作业的 run 脚本**上，而不是整个文件。
这不是洁癖——同一个文件里 `gh release view` 出现两次（一处在 preflight 判断要不要发，
一处在 publish 打完收工看一眼），扫全文时"删掉 preflight 里那一次"照样绿。

分母：三份 workflow 文件一个都不能少（`must_scan`），否则这个目录整体改名/移走时
判据会静默扫不到任何东西。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from _denominator import must_scan

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
CI = WORKFLOWS / "ci.yml"
BUILD = WORKFLOWS / "build-installer.yml"

SHA = re.compile(r"@[0-9a-f]{40}\b")


def _load(path: Path) -> dict:
    """读一份 workflow。

    ⚠ `on:` 在 YAML 1.1 里被解析成布尔 True（PyYAML 就是 YAML 1.1），所以键要两个名字
    都试。只写 `data["on"]` 的话，这一条会挂在 `KeyError: True` 上——而报错信息与真正
    要防的东西毫无关系，排错的人得先绕一圈才知道是 YAML 方言问题。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} 解析出来不是映射"
    return data


def _on(data: dict) -> dict:
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict), f"触发器不是映射：{triggers!r}"
    return triggers


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def _run_scripts(job: dict) -> list[str]:
    """一个作业里每一步的 `run:` 正文（各自去注释）。

    ⚠ 需要**逐步**分开看时用它，而不是拼成一大段再 `in` 断言：`build-installer.yml` 里
    `--mode onedir` 在"构建 onedir 产物"那一步也出现过，所以拼起来查
    "`--installer-only` 那一步是否也带 `--mode onedir`"永远绿——**匹配到的是另一处**。
    这和 `gh release view` 那次是同一个形状的错误。
    """
    out: list[str] = []
    for step in job.get("steps") or []:
        lines = [
            line for line in str(step.get("run", "")).splitlines()
            if not line.lstrip().startswith("#")
        ]
        if lines:
            out.append("\n".join(lines))
    return out


def _run_text(job: dict) -> str:
    """一个作业里所有 `run:` 脚本拼起来的正文，**去掉整行注释**。

    ⚠ 去注释是因为 workflow 里那段注释为了说明为什么**不**用 `--verify-tag`、
      为什么**不**从 `GITHUB_REF_NAME` 反推版本，逐字写出了这两个字符串。朴素的
      `in text` 会在**正确**的 workflow 上报红，而真写进命令行的版本反而可能被注释掩盖。
      ⭐⭐ **一个字符串出现过，不等于那件事发生过**（本仓
      `test_the_index_gate_is_wired_into_ci.py` 记过一次同形的：判据命中了自己写的解释）。
    """
    steps = job.get("steps") or []
    lines: list[str] = []
    for step in steps:
        for line in str(step.get("run", "")).splitlines():
            if not line.lstrip().startswith("#"):
                lines.append(line)
    return "\n".join(lines)


def _reachable(jobs: dict, start: str) -> set[str]:
    """从某个作业出发能到达的全部作业（传递依赖）。"""
    seen: set[str] = set()
    queue = list(_needs(jobs.get(start, {})))
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(_needs(jobs.get(name, {})))
    return seen


def test_every_workflow_file_parses():
    """分母守卫：目录里确实有 workflow，而且每一份都解析得开。"""
    files = must_scan(sorted(WORKFLOWS.glob("*.yml")), ".github/workflows/*.yml")
    for path in files:
        _load(path)


def test_release_runs_on_main_push_and_on_version_tags():
    """push 到 main 就起；手工推 `v*` tag 也起（补发那一版的入口）。"""
    triggers = _on(_load(RELEASE))
    push = triggers.get("push", {})
    assert push.get("branches") == ["main"], (
        f"release.yml 监听 {push.get('branches')!r}，应为 ['main']。"
        "发版流水线必须跟着仓库的默认分支走——写错分支名的话文件依然合法，"
        "只是永远不被触发，而看起来有发版比没有发版更糟。"
    )
    assert push.get("tags") == ["v*"], "手工推 v* tag 也应该能起这条流水线（补发入口）"


def test_preflight_short_circuits_unreleased_pushes():
    """不抬版本的 push 必须被 preflight 短路，且短路信号要真的接到了下游。"""
    jobs = _load(RELEASE)["jobs"]
    must_scan(list(jobs), "release.yml 的作业", least=3)

    preflight = jobs.get("preflight")
    assert preflight, (
        "release.yml 没有 preflight 作业 —— 不抬版本的 push 也会起一台 Windows runner "
        "跑十分钟 PyInstaller，一次都不发布。"
    )
    outputs = preflight.get("outputs") or {}
    assert "should_release" in outputs, "preflight 没有 should_release 输出，下游无从短路"
    assert "version" in outputs, "preflight 没有 version 输出，发布说明和 tag 就没有版本号来源"

    # 每个花钱的作业都要挂在同一个条件上。漏挂的后果是短路失效，packaging 白跑。
    for name in ("build", "publish"):
        cond = str(jobs[name].get("if", ""))
        assert "should_release" in cond, (
            f"作业 {name} 没有挂在 preflight 的 should_release 上（if={cond!r}）"
        )

    # 上面的 if 只是一根**线**；线接到哪里才是开关本身。短路逻辑住在 bash 里，
    # YAML 判据看不见它，所以这里逐条点出来（范围限定在 preflight 自己的脚本里——
    # 扫全文会被 publish 里那次同名调用糊弄过去）：
    #  - 查已有 Release 是短路的前提，少了它就无从判断；
    #  - 两条取值分支都要在。少了 false 那条就是「永远发版」，而那**不会有任何测试
    #    变红**，只会让每个普通 push 都去跑十分钟 PyInstaller；
    #  - 远端已有同名 tag 却没 Release 时必须响亮失败。
    run = _run_text(preflight)
    assert "gh release view" in run, "preflight 没有查这个版本是不是已经发过了"
    assert "should_release=false" in run, "preflight 没有不发版的那条分支"
    assert "should_release=true" in run, "preflight 没有发版的那条分支"
    assert "git ls-remote" in run, (
        "preflight 没有守「远端已有同名 tag 但没有 Release」这个中间态 —— "
        "放着不管，gh 会把新 Release 挂到一个指向未知提交的旧 tag 上。"
    )


def test_reused_workflow_concurrency_group_is_caller_specific():
    """会被复用的 workflow,它的 concurrency group 不能只由 `github.workflow` 决定。

    **这是判据记下的两次真实失败**，不是假想。第一次：run 36401751401；加了调用作业级
    `concurrency` 之后：run 36402772836。两次现象一样——preflight 成功，门禁那个作业
    **连作业记录都不产生**，build / publish 变成 skipped，整条 run 记 failure，没有任何
    错误信息。actionlint 对三份 workflow 都报合法，所以不是语法问题。

    成因：`ci.yml` 原本写
    `group: ${{ github.workflow }}-${{ github.ref }}` + `cancel-in-progress: true`。在
    **被调用**的 workflow 里 `github.workflow` 解析成的是**被调用方**的名字（`ci`），
    于是同一次 push 上独立跑的那条 ci 与发版门禁落进同一个 group，互相取消。佐证：
    那次 push 的独立 ci run 的 conclusion 正是 `cancelled`。

    ⚠ 修复第一次也踩空了：给**调用作业**加 `concurrency` 没用——起作用的是被调用文件
    自己的 group。两条 run 都是 ci.yml 跑的，只有"调用方是谁"能把它们分开，而
    `github.workflow_ref` 正是这个信息（本文件 vs release.yml）。

    所以不变式落在**被调用文件**上：它的 group 必须认得出调用方。
    """
    conc = _load(CI).get("concurrency") or {}
    group = str(conc.get("group", ""))
    assert group, "ci.yml 没有 concurrency：连续 push 会把 Windows runner 堆起来"
    assert "github.workflow_ref" in group, (
        f"ci.yml 的 concurrency group 是 {group!r}，没有用 github.workflow_ref。"
        "被调用时 github.workflow 是被调用方的名字，两条 run 会落进同一个 group 互相取消"
        "（事故 run 36401751401 / 36402772836）。"
    )
    # 精确的不变量：不能用**裸的** github.workflow。workflow_ref 里也含 "workflow"，
    # 所以判据要卡住的是 "${{ github.workflow }}" 这种不带 _ref 的引用。
    assert "github.workflow }}" not in group and "github.workflow }}-" not in group, (
        f"ci.yml 的 concurrency group 里出现了裸的 github.workflow（{group!r}）——"
        "被调用时它解析成被调用方的名字。"
    )
    # 同一条流水线里仍然要能互相取消，否则连续 push 会把 runner 堆起来。
    assert conc.get("cancel-in-progress") is True, (
        "ci.yml 应当保留 cancel-in-progress: true —— 同一条流水线的旧 run 仍需要被取消"
    )

    # 调用方不再自带第二套并发机制：两套机制叠着，下次出问题没人说得清是谁在起作用。
    # （release.yml 现在调用的是 build-installer.yml，那条链路没有 concurrency；
    #  这里盯着 ci.yml 是因为它仍然带 workflow_call 入口——判据防的是"将来又被谁
    #  复用一次"，而不是某一次具体的调用。）
    reusable_jobs = [
        name for name, job in _load(RELEASE)["jobs"].items() if job.get("uses")
    ]
    for name in reusable_jobs:
        assert "concurrency" not in _load(RELEASE)["jobs"][name], (
            f"release.yml 的 {name} 调用作业又加回了 concurrency。"
            "曾经试过用它来划开 group，没用（那两次事故），留着只会让人以为它在起作用。"
        )


def test_release_contains_only_the_installer():
    """Release 里只挂一个 exe；校验和进说明正文，不做第二个附件。"""
    run = _run_text(_load(RELEASE)["jobs"]["publish"])
    create = run.split("gh release create", 1)[1].split('echo "----"', 1)[0]
    assert "dist/*.exe" in create, "发版命令没有把安装包 exe 作为附件传进去"
    assert ".sha256" not in create, (
        "发版命令还挂着 .sha256 附件。校验和应该写进说明正文（只下 exe 的人也会看到），"
        "而不是在下载页上多出一个没人点的文件。"
    )
    assert "cat dist/*.sha256" in run, "校验和没有被写进发布说明"


def test_packaging_workflow_installs_the_test_runner_the_build_script_calls():
    """打包脚本在打包前会跑 pytest，所以打包流水线必须把它装上。

    **这也是一次真实失败**（release run 36403249454，作业 build 第 6 步）。`build_release.py`
    把"无内置素材"那条判据当**打包前的门禁**跑（`build_tools/build_release.py:951`，
    `run([args.python, "-m", "pytest", "-q", "tests/test_no_bundled_assets.py"])`，只有
    `--skip-tests` 才跳过），而 pytest 住在 `requirements-ci.txt` 里，不在
    `requirements_qt.txt` / `requirements-build.txt` 里 —— 于是打包必然挂在
    `No module named pytest` 上。

    ⭐ 这条判据防的正是"两个依赖表各自成立、合起来少一个"这种形状：两份 requirements
    都能装上、构建脚本自己也能跑，只有**打包这个动作**才暴露。而且它失败的位置离原因很远
    （报错在 `subprocess.CalledProcessError` 里，真正的信息在上一行的 stderr）。
    """
    build_script = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    assert '"-m", "pytest"' in build_script, (
        "build_release.py 里那条打包前门禁不见了 —— 如果它改成不跑测试了，"
        "本条判据的依据就不在了，请连带改这条测试，别留着一条永远绿的。"
    )

    run = _run_text(_load(BUILD)["jobs"]["build"])
    install_lines = [line for line in run.splitlines() if "pip install" in line]
    must_scan(install_lines, "build-installer.yml 里的 pip install 行", least=1)
    assert any("pytest" in line for line in install_lines), (
        f"打包流水线装依赖时没有 pytest：{install_lines}。"
        "而 build_release.py 默认会在打包前跑 tests/test_no_bundled_assets.py，"
        "没有它就是 `No module named pytest`（实测 run 36403249454）。"
    )

    # 顺带钉住"它是直接装的"：万一哪天有人把 pytest 加进 requirements-build.txt，
    # 这两行会先提醒他"依据变了"，而不是让上面那条断言悄悄变成由间接满足。
    for req in ("requirements_qt.txt", "requirements-build.txt"):
        text = (ROOT / req).read_text(encoding="utf-8")
        assert not re.search(r"^pytest", text, re.M), (
            f"{req} 里现在已经有 pytest 了。打包流水线的 pip install 行还写着 pytest 的话，"
            "要么删掉多余的字样，要么改这条判据的说明 —— 别让它两处都留着。"
        )


def test_installer_is_compiled_by_the_build_script_not_by_hand():
    """安装包必须由 `build_release.py --installer-only` 编译，不许在 shell 里手搓 iscc。

    **这也是一次真实失败**（release run 36406788535，作业 build 第 8 步）：

        You may not specify more than one script filename.
        Inno Setup 6 Command-Line Compiler

    看着像脚本名写错了，其实是两层转义叠在一起：`shell: bash` 是 git-bash，
    `$(python -c ...)` 的输出带着 Windows 的 `\r`，而 `/DAppVersion=<值>` 这种以斜杠
    开头的参数还会被 MSYS 的参数转换搅一遍。ISCC 于是把第二个参数当成了第二个脚本名。
    **报错完全指不到真正的原因**——而这正是"在 shell 里手搓编译器调用"的固有代价。

    判据钉的是**归属**，不是具体写法：谁负责调编译器、怎么传版本号。仓库里已经有 hardened
    的那条路（`build_release.py` 的 `build_installer()`：版本号从 `config.VERSION` 直读、
    `find_tool("iscc")` 定位并给出"找过哪些路径"的报错、`subprocess` 用列表传参不经过
    任何 shell）。判据同时要求那条路仍然把版本号经 `/DAppVersion` 传出去——如果哪天
    改成在 iss 里写死版本号（正是 `test_installer_iss_declares_no_version_of_its_own`
    正在防的事），本条要跟着改。
    """
    scripts = _run_scripts(_load(BUILD)["jobs"]["build"])
    for script in scripts:
        assert not re.search(r"^\s*iscc\s", script, re.M), (
            "打包流水线里又出现了手写的 iscc 调用。"
            "走 `python build_tools/build_release.py --mode onedir --installer-only`——"
            "在 shell 里手搓编译器调用已经被 git-bash 的参数转换坑过一次"
            "（run 36406788535，报错还完全指不到原因）。"
        )

    installer_steps = [s for s in scripts if "--installer-only" in s]
    must_scan(installer_steps, "build-installer.yml 里带 --installer-only 的那一步", least=1)
    for step in installer_steps:
        # 逐步查，不是拼起来查：`--mode onedir` 在"构建 onedir 产物"那一步也有，
        # 拼起来断言会匹配到那一处，于是这步缺了参数也照样绿。
        assert "--mode onedir" in step, (
            "--installer-only 必须和 --mode onedir 写在**同一条命令**里："
            "安装包的 [Files] 段只吃 onedir 形态，缺了会在 build_release.py 里当场报错"
        )

    script = (ROOT / "build_tools" / "build_release.py").read_text(encoding="utf-8")
    assert 'f"/DAppVersion={version}"' in script, (
        "build_release.py 不再经 /DAppVersion 把版本号传给 ISCC 了。"
        "installer.iss 已经去掉自带兜底常量（漏传会 #error），"
        "这条路径要是也断了，构建就会在装的时候才炸。"
    )


def test_release_path_deliberately_has_no_test_gate():
    """发版链路上**没有**测试门禁 —— 这是 2026-09-28 的明确决定，不是漏了。

    这条判据把**决定**钉住，而不是钉住"缺少某个东西"。要恢复门禁的人会在这里看到一段
    写明的账，然后**有意识地**改，而不是以为自己在修一个遗漏。

    **为什么撤掉（主人原话大意：他只是 fork 了这个仓库、想编出一个 exe，不是这个项目的
    开发者）：**

    - `ci.yml` 的 `test` 作业在 runner 上要 **16 分钟**（124 个测试文件逐个起子进程），
      `ui-audit` 3 分钟；两条本来就是并行作业，所以 3 分钟那部分**不在关键路径上**，
      撤掉它一秒都不省。
    - 更要紧的是：**这道门一次都没有拦住过任何东西。** 拦住发版的三次失败全在
      `build-installer.yml` 自身——缺 pytest（D18）、手搓 iscc 参数被搅坏（D19）、
      缺中文语言文件（D21）。砍掉测试，那三次一次也避免不了。
    - 门禁没有白丢：`ci.yml` 仍然在每次 push 上**独立跑**，那是上游自己的标准，
      信息还在 Actions 页面上；只是不再挡住这个 fork 发版。

    **代价，写明白**：一个测试矩阵红的提交**也可能**被发成二进制。要恢复这道门，把
    `build` 的 `needs` 换回 `[preflight, ci]` 并把 `ci` 作业加回来，同时在
    `PROGRESS.md` 的 Decisions 里追加一行说明为什么改主意——**不要静悄悄地改**。
    """
    jobs = _load(RELEASE)["jobs"]
    must_scan(list(jobs), "release.yml 的作业", least=3)

    assert "ci" not in jobs, (
        "release.yml 又加回了 ci 门禁。如果这是有意的(例如想恢复'测试不绿就不发版'),"
        "请在 PROGRESS.md 的 Decisions 里追加一行说明为什么,并把本条判据改成新的形状;"
        "不要让它以'修复遗漏'的名义悄悄回来。"
    )
    for name, job in jobs.items():
        assert not str(job.get("uses", "")).endswith("ci.yml"), (
            f"作业 {name} 又调起了 ci.yml —— 同上,这是门禁,不是打包。"
        )
    # publish 仍然必须等 build:dist/ 是空的就去建 Release,会留下一个
    # 看起来发布成功、下载却 404 的 Release。这条与门禁撤不撤无关。
    assert "build" in _needs(jobs["publish"]), (
        "publish 没有 needs: build —— 它会在 dist/ 还是空的时候就建 Release。"
    )
    assert "preflight" in _needs(jobs["build"]), (
        "build 必须挂在 preflight 的短路上,否则不抬版本的 push 也会起 Windows runner。"
    )


def test_only_publish_job_may_write():
    """写权限只给 publish 一个作业，顶层收敛为只读。"""
    data = _load(RELEASE)
    assert data.get("permissions") == {"contents": "read"}, (
        f"release.yml 顶层权限是 {data.get('permissions')!r}，应为 contents: read —— "
        "顶层提权等于把写权限发给 ci / build / preflight 作业。"
    )
    for name, job in data["jobs"].items():
        perms = job.get("permissions")
        if name == "publish":
            assert perms == {"contents": "write"}, (
                f"publish 作业权限是 {perms!r}，应为 contents: write（建 Release 要它）"
            )
        else:
            # 复用型作业（uses:）不写 permissions 是对的：它继承调用方。
            assert perms is None or perms == {"contents": "read"}, (
                f"作业 {name} 的权限是 {perms!r} —— 只有 publish 该拿到写权限"
            )


def test_upstream_workflows_expose_a_reusable_entrypoint():
    """ci 与 build-installer 都得能被 `uses:` 调用。

    这两条是发版复用同一条打包链路的地基。少了任何一条，要么发版跑不了，
    要么有人复制一份流水线进去——而复制的那份会独立腐烂。
    """
    for path, label in ((CI, "ci.yml"), (BUILD, "build-installer.yml")):
        triggers = _on(_load(path))
        assert "workflow_call" in triggers, (
            f"{label} 少了 workflow_call 入口，release.yml 调不动它。"
            "别改成复制一份流水线 —— 那份副本会独立腐烂。"
        )


def test_third_party_actions_are_pinned_to_a_commit_sha():
    """每一条第三方 `uses:` 都得带 40 位 commit SHA。

    分母是整个 workflows 目录：这条判据防的是有人在某个文件里顺手改成 tag。
    @v4 是**可移动引用**——上游重打一次 tag，我们下一次发版就静默跑到不同的代码上，
    而且这类漂移永远不会让任何一条测试变红。
    """
    files = must_scan(sorted(WORKFLOWS.glob("*.yml")), ".github/workflows/*.yml", least=3)
    unpinned: list[str] = []
    checked = 0
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if not match:
                continue
            ref = match.group(1)
            # `./.github/workflows/x.yml` 是本仓库内的可复用工作流，版本由 tag / 分支本身
            # 钉死，它不是第三方 action，SHA 规则不适用（也钉不了）。
            if ref.startswith("."):
                continue
            checked += 1
            if not SHA.search(ref):
                unpinned.append(f"{path.name}: {ref}")
    assert checked, "一条第三方 uses: 都没扫到 —— 扫描路径失效了"
    assert not unpinned, "第三方 action 没有按 commit SHA 固定：\n  " + "\n  ".join(unpinned)


def test_release_tags_the_commit_that_was_built():
    """Release 和它附带的二进制必须指向**同一次 push 的那个提交**。

    tag 由 gh 在 `--target $GITHUB_SHA` 上建出来；命令行里**不**出现 `--verify-tag`
    （此刻 tag 正是要建的东西，先验后建是死循环）；附件取件失败要在建 Release 之前
    当场停——否则会拿空附件建出一个看起来发布成功的 Release，下载才是 404。
    """
    jobs = _load(RELEASE)["jobs"]
    run = _run_text(jobs["publish"])
    assert "gh release create" in run, "publish 里没有 gh release create —— 那它不发布任何东西"
    assert '--target "$GITHUB_SHA"' in run, (
        "gh release create 少了 --target $GITHUB_SHA：tag 会建在默认分支的头上，"
        "而不是这次 push 的提交上——期间有别的 push 时，二进制和 tag 就对不上了。"
    )
    assert "--verify-tag" not in run, (
        "自动打 tag 的流程里不该出现 --verify-tag：此刻 tag 正是要建的东西，先验后建是死循环。"
    )
    assert "ls dist/*.exe" in run, (
        "publish 必须在建 Release 之前确认 dist 里有 exe —— "
        "空附件建出来的 Release 看起来是发布成功的，下载才是 404。"
    )
    assert "dist/*.exe" in run and "dist/*.sha256" in run, (
        "发布的附件应当是安装包 exe 加它的 .sha256"
    )


def test_release_notes_come_from_the_changelog_and_fail_loudly():
    """发布说明取自 CHANGELOG.md 本版本那一节，抽不到就失败。

    版本号只能来自 preflight 的输出：tag 在这一刻还不存在，所以任何从
    `GITHUB_REF_NAME` 反推版本的写法都属于旧设计残留。
    """
    jobs = _load(RELEASE)["jobs"]
    publish = jobs["publish"]
    run = _run_text(publish)
    assert "CHANGELOG.md" in run, "发布说明没有取自 CHANGELOG.md"
    # 判据防的是抽不到就写一句占位文案：那会让人以为这一版没有改动。
    assert "sys.exit" in run, (
        "抽不到 CHANGELOG 对应小节时必须 sys.exit 失败，"
        "不能退回一句占位文案 —— 那看起来像这一版没改东西。"
    )
    assert "GITHUB_REF_NAME" not in run, (
        "发布说明/版本号还在从 GITHUB_REF_NAME 反推。自动打 tag 的流程里此刻还没有 "
        "ref 名可推 —— 版本号只能来自 preflight.outputs.version。"
    )
    env = publish.get("env") or {}
    assert str(env.get("VERSION", "")).strip() == "${{ needs.preflight.outputs.version }}", (
        f"publish 的 VERSION 是 {env.get('VERSION')!r}，应当接 preflight 算出来的版本号"
    )
