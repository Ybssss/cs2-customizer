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
    must_scan(list(jobs), "release.yml 的作业", least=4)

    preflight = jobs.get("preflight")
    assert preflight, (
        "release.yml 没有 preflight 作业 —— 不抬版本的 push 也会起一台 Windows runner "
        "跑十分钟 PyInstaller，一次都不发布。"
    )
    outputs = preflight.get("outputs") or {}
    assert "should_release" in outputs, "preflight 没有 should_release 输出，下游无从短路"
    assert "version" in outputs, "preflight 没有 version 输出，发布说明和 tag 就没有版本号来源"

    # 三个花钱的作业每一个都要挂在同一个条件上。漏挂一个的后果不同：
    # ci 漏挂 = 测试门禁形同虚设；build/publish 漏挂 = 短路失效，packaging 白跑。
    for name in ("ci", "build", "publish"):
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
    assert "concurrency" not in (_load(RELEASE)["jobs"]["ci"]), (
        "release.yml 的 ci 调用作业又加回了 concurrency。"
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


def test_publish_gates_on_ci_and_build():
    """`publish` 必须等打包，且经由 build 传递地等到 ci。"""
    jobs = _load(RELEASE)["jobs"]
    must_scan(list(jobs), "release.yml 的作业", least=4)

    assert "ci" in jobs, "release.yml 里没有 ci 作业：发版就不受测试门禁保护了"
    assert "build" in jobs, "release.yml 里没有 build 作业：附件从哪来？"

    assert "ci" in _needs(jobs["build"]), (
        "build 必须在 ci 之后跑 —— 门禁红了就不该再花机时打包。"
    )
    assert "build" in _needs(jobs["publish"]), (
        "publish 没有 needs: build —— 它会在 dist/ 还是空的时候就建 Release，"
        "留下一个看起来发布成功、下载却 404 的 Release。"
    )

    # ci 必须是 publish 的**传递**依赖。只写 `needs: build` 一层是对的（不重复声明），
    # 所以这里量的是可达性：谁把 build 的 needs 改成空，测试门禁就在发版链路上消失了，
    # 而 workflow 文件本身仍然合法、不报任何错。
    reachable = _reachable(jobs, "publish")
    assert "ci" in reachable, (
        f"publish 的传递依赖是 {sorted(reachable)}，里面没有 ci —— "
        "测试门禁已经不在发版链路上了。"
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
