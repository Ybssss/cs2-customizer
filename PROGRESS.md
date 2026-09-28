# PROGRESS — CS2 Customizer

> ## ⚠️ READ THIS FILE FIRST — BEFORE TOUCHING THE SYSTEM
>
> **Owner instruction.** This file is the accumulated state of the project: what is built, what is only
> planned, what was tried and rejected, and which claims in the code and in older documents are already
> known to be wrong. Read it, then verify the specific claim you are about to rely on, in source.
>
> **Latest state (2026-09-28, ninth pass):** Broken Release **v2.3.1 was deleted** (release + remote
> tag, owner-approved) and the dependency hole is closed: `requirements.txt` added,
> `requirements-ci.txt` references it instead of duplicating it, packaging installs it. On top of
> that there is now a check that inspects the **built artifact** — `check_frozen_bundle.py` lists
> the exe's embedded archive with PyInstaller's `archive_viewer` and requires every startup-critical
> module to be present in the exe or in `_internal/`, wired into `build-installer.yml` before the
> installer compile (D26). Owner also chose: no timeout-based "did the exe stay alive" check, because
> an unhandled exception pops a **modal** dialog on Windows and the process then hangs — which would
> pass the very check meant to catch it. Because `VERSION` is still 2.3.1 and no Release exists, the
> next push re-publishes **v2.3.1** with the fixed, bundle-verified build. Earlier in this pass: The pipeline **finally published** — and the exe it
> published does not run. The owner launched it and got `Failed to execute script 'main_widget' … No
> module named 'flask'`. Root cause is structural, not a missing line: `requirements_qt.txt` says in
> its own comments that the core runtime deps live in **`requirements.txt`** — that file was never
> carried into the open-source subset, and the only place those packages were listed was
> `requirements-ci.txt`, which had **copied them a second time**. So CI installed them and packaging
> did not. Fixed by adding `requirements.txt` (flask / pygame / keyboard / pynput / pywin32 /
> pypinyin / numpy / sounddevice / soundfile / PyYAML, every version bound unchanged),
> `requirements-ci.txt` now references it instead of duplicating it, and the packaging job installs
> it (D24). A new test walks the app's **module-level unguarded imports** and requires each to be
> declared — it would have been red before v2.3.1 shipped (D25). **v2.3.1 is still published and
> still broken**; see the open question at the end of section 3. Earlier in this pass: The compiler finally named the blocker, and it was neither
> of the two things suspected: `installer.iss` line 72 asked for
> `compiler:Languages\ChineseSimplified.isl`, and official Inno Setup ships only about a dozen
> languages — **Simplified Chinese is a third-party translation the build machine happened to have**.
> So `build-installer.yml`'s success depended on what was installed on the machine. The MIT translation
> (kira-96, Inno 6.5.0+) is now **bundled at `build_tools/Languages/`** and referenced script-relatively;
> ISCC also now runs with the script's own directory as cwd, which makes the `.iss`'s two different
> relative bases (`..\release\…` vs bare `installer_assets\…`) resolve identically either way
> (D21, D22). **And the test gate is gone from the release path** (D23): the owner is a fork maintainer
> who wants an exe, `test` costs 16 minutes, and that gate never once blocked a real failure — all three
> were bugs in `build-installer.yml` itself. Release is now `preflight -> build -> publish`, ~8 min.
> Earlier in this pass: ISCC now receives correct arguments
> (`[iscc.EXE, installer.iss, /DAppVersion=2.3.1]`, D19) but exits **2 with no output at all** —
> the compiler's own diagnostics were being swallowed by `build_release.run()`, so the log had
> nothing but an exit code. Fixed that first (`run()` gained a `capture` switch, on for the compiler
> only) and, on the evidence available, a second candidate: `installer.iss` was UTF-8 **without a
> BOM** while containing 2811 non-ASCII bytes, and ISCC reads a BOM-less `.iss` as *system ANSI* —
> so the same file compiles on a cp936 dev machine and fails on a cp1252 runner (entry 8). ⚠ **The
> BOM is a hypothesis, not a confirmed root cause.** A second candidate is still open: the `.iss`
> resolves `SetupIconFile` / `WizardImageFile` as `installer_assets\…` while everything else uses
> `..\release\…`, and ISCC is invoked with `cwd=project_root`, so those may not resolve. Both are
> recorded; the runner output will say which. **Still no Release exists.** Earlier in this pass: PyInstaller now succeeds on the runner; the pipeline fails
> one step later, again on a **pre-existing** `build-installer.yml` defect. Run 36406788535 got the gate
> green (`ci / test` and `ci / ui-audit` both passed), built the onedir tree, found Inno Setup already
> installed, and then the hand-rolled `iscc` call died on `You may not specify more than one script
> filename` (entry 7) — `shell: bash` is git-bash, `$(python -c ...)` carries a Windows `
`, and MSYS
> argument conversion mangles `/DAppVersion=<值>`. Fixed by compiling through the project's own hardened
> path, `build_release.py --mode onedir --installer-only`. **Still no Release exists**, and SHA256 /
> upload / `gh release create --target` remain unproven. Earlier in this pass:
> `ci.yml` groups its runs with `${{ github.workflow }}-${{ github.ref }}`, and in a **called** reusable
> workflow `github.workflow` resolves to the **callee's** name (`ci`) — so the release's gate and the
> standalone `ci` run for the same push shared one group and `cancel-in-progress: true` made them kill
> each other. The tell was in plain sight: that push's standalone `ci` run concluded `cancelled`.
> The fix is in **ci.yml**, not the caller — its group now uses `github.workflow_ref` (the *caller's*
> path), which cannot collide. My first attempt (D14, a caller-side `concurrency`) did **not** work and is
> marked superseded: the callee's own group is what governs. Owner decisions since entry 3: the Release
> carries **exactly one asset, the .exe** with the SHA256 in the notes body (D15); and the owner was told
> plainly there is **no Android/APK build** — Windows-only PyQt5, an APK would be a separate port (D16).
> The next push to `main` publishes v2.3.1 for real. Local test runs need the isolated venv in section 5.

---

## 0. Standing rules — how this project runs

These are owner instructions, not findings. They apply to every change.

1. **Read this file first.** Before any change — not after, not only when unsure. Then verify the claim
   you rely on in source; a claim here can be stale, and section 5 lists the ones already known to be.
2. **This file is the single maintained document.** Do not create `CONTEXT.md`, `docs/`, ADR folders or
   any second documentation file. Glossary and decisions live here. (`docs/` predates this file and
   belongs to the upstream project; do not add to it from agent work.)
3. **Always maintain and append to it.** A change — code, schema, workflow, config, docs — is not
   complete until this file reflects it. **Append; never overwrite history.** When a recorded claim is
   overtaken, add a superseding entry and mark the original _superseded_ rather than deleting it.
4. **Commit and push are the owner's decision.** Never commit or push without explicit approval for
   that specific change. Know what a push triggers: pushing a `v*` tag starts the release pipeline,
   which publishes a binary to the Releases page — that is externally visible and irreversible
   (a tag can be deleted, a published download cannot be un-seen).
5. **Repository hygiene already encoded in the repo itself** — do not relax it:
   - third-party actions pinned to a 40-hex commit SHA, never a tag (`tests/test_release_wiring.py`
     enforces this across `.github/workflows/*.yml`);
   - every workflow's `permissions` explicit, `contents: read` unless the job writes;
   - `on:` trigger branches must match the default branch (`main`) or the workflow silently never runs;
   - ruff + `python build_tools/run_tests.py` (per-file subprocess isolation) are the gates.
6. **Frontend.** Not applicable — this is a PyQt5 desktop app. There is no `DESIGN.md`; the UI
   reference is `docs/CS2Customizer_UI打磨蓝图_v1.md` and the three UI rulers in `ci.yml`'s `ui-audit`.
7. **Development** uses the **`/implement`** skill. If it is not installed, record that here and proceed
   under the remaining rules.
8. **Keep the project modular — for expandability.** See section 0.1.
9. **Report outcomes faithfully.** Say _verified_ only for what was executed, and name how
   ("8 passed", "3 workflow files parsed with PyYAML"). Otherwise write _not verified_ and what would
   verify it. A green run proves only what the tests exercise.
10. **Never paste secret-shaped strings into this file.** Describe them.
11. **Write "section N", never the section-sign glyph.**
12. **This repository is a fork of `gufan0000/cs2-customizer` and merges upstream regularly.**
    No `upstream` remote is configured yet; add it with
    `git remote add upstream https://github.com/gufan0000/cs2-customizer.git`.
    **Fork-only files** (upstream never touches them, so they never conflict):
    `.github/workflows/release.yml`, `tests/test_release_wiring.py`, `PROGRESS.md`.
    **Fork-only edits inside shared files** (these are the merge-conflict surface, in
    expected order of pain): `README.md` and `README.en.md` (heavily divergent, the release
    section and the top block are ours) > `CHANGELOG.md` (version sections) >
    `.github/workflows/ci.yml` and `build-installer.yml` (one added `workflow_call:` line each —
    take the upstream side plus that line, never drop it).
    Upstream publishes no binaries by policy, so upstream Releases never enter the picture: the
    `preflight` check only ever asks about *this* repository's own Releases.

### 1. Modularization

- **Domain modules** — `core/<domain>/` owns its logic (audio, gsi, hud, presets, hotkeys, net,
  backup...). Root-level `gsi_handler_*.py` are the GSI event handlers, one file per event family.
- **UI** — `pages/*_page.py` one page per sidebar entry (26), `widgets/` for cross-page components,
  `dialogs/` for wizards and prompts. Pages must not import each other's internals; shared UI pieces
  are promoted to `widgets/` or `ui_design_system.py`.
- **Build and release tooling** — `build_tools/` owns packaging, Inno Setup, the test driver. The
  workflows are the callers; they must not re-implement build steps inline.
- **Shared code lives in shared places.** Do not copy a helper into a second module; promote it.
- **Workflows are modules too.** `release.yml` calls `ci.yml` and `build-installer.yml` through
  `uses:` instead of copying their steps — a copied pipeline rots independently, and only the copy
  gets fixed. Enforced by `tests/test_release_wiring.py::test_upstream_workflows_expose_a_reusable_entrypoint`.
- **Practical test before adding code:** if the change needs another module's internals, or duplicates
  logic that exists elsewhere, stop — the feature belongs in that module, or the shared piece is promoted first.

---

## 1. Decisions

Settled decisions, numbered. Reversing or clarifying one means **appending a new row**, never rewriting.
Mark items the owner delegated to the agent as _(delegated)_.

| #      | Decision | Outcome |
| ------ | -------- | ------- |
| **D1** | Release is published by a **new third workflow** `release.yml`, not by editing `build-installer.yml`. _Owner asked for a release action; splitting the workflows was the agent's call (delegated)._ | Keeps packaging read-only; write scope stays on one job. |
| **D2** | Job graph is `ci -> build -> publish`; `publish` needs `build` only, and the test asserts `ci` is a **transitive** dependency. | No duplicate `needs`, gate still provably in the chain. |
| **D3** | `contents: write` only on `publish`; workflow top level stays `contents: read`; checkout uses `persist-credentials: false`. | A build step that runs PyInstaller / Inno / `choco install` never holds a writable token. |
| **D4** | Release notes are extracted from the `## [X.Y.Z]` section of `CHANGELOG.md`; a missing section is a **hard failure** (`sys.exit`), never a placeholder body. | No empty-looking Release; the changelog stays the single source. |
| **D5** | `actions/download-artifact` pinned to `v4.3.0` (`d3f86a1...`), same generation as the repo's `upload-artifact` v4.6.2, even though v8 exists. | Artifact format is versioned by major; cross-major retrieval is a risk with no benefit here. |
| **D6** | Publication trigger is a `v*` tag push only. No manual-dispatch release path. | A Release and the code it was built from stay the same commit; `workflow_dispatch` on `build-installer.yml` still exists for gate-only runs. |
| **D7** | The changelog-extraction step pins `PYTHONIOENCODING=utf-8`. | GitHub's Windows runners are `en-US` (cp1252); without it the Chinese release notes are mojibake or `UnicodeEncodeError` while the run still goes green. |
| **D8** | The two READMEs' "this repository publishes no Release binaries" claims were rewritten rather than left as upstream text. | Documentation drift is a defect: the fork now ships binaries, and the old text would misdirect users and contradict the pipeline. |
| **D9** | **Supersedes D6.** Release triggers on `push` to `main` (a `v*` tag push is still accepted as a catch-up entry). The tag is created by the pipeline, not by a human. | Owner instruction: automate it so an update from origin updates the Release with a tag. Manual tagging was a step the owner did not want. |
| **D10** | **The release trigger is the version, not the commit.** A `preflight` job compares `config.VERSION` against existing Releases and short-circuits the rest of the graph. | A per-commit Release is a different product (a prerelease track) and was not asked for. This way an ordinary push starts zero Windows runners. |
| **D11** | `gh release create` uses `--target "$GITHUB_SHA"`, and **no** `--verify-tag`. A remote tag that exists without a Release is a **hard failure**, not a publish. | The tag must be created *by* this run at the pushed commit. `--verify-tag` here would be a chicken-and-egg deadlock; the stale-tag case would otherwise attach a Release to an unknown commit. |
| **D12** | Release notes and the tag name take their version from `needs.preflight.outputs.version`, never from `GITHUB_REF_NAME`. | At publish time the tag does not exist yet, so there is no ref name to derive a version from. |
| **D14** | The `ci` gate job carries its own `concurrency`: group `release-gate-${{ github.ref }}`, `cancel-in-progress: false`, and **no `github.workflow` in the group**. | Fixes the self-cancelling gate of entry 4. The invariant is "the gate's group must not depend on `github.workflow`", because in a reusable call that value is not ours to control. |
| **D17** | **Supersedes D14.** The real fix is in **`ci.yml`**: its `concurrency.group` now uses `${{ github.workflow_ref }}-${{ github.ref }}` (the *caller's* workflow path) instead of `${{ github.workflow }}-${{ github.ref }}`. The caller-side `concurrency` from D14 is **removed** — two mechanisms overlap, and D14 demonstrably did not work. | D14 was tried and disproved by run 36402772836, which failed identically with D14 in place. Invariant, now guarded by a test: a workflow that gets reused must not key its concurrency group on `github.workflow`. |
| **D26** | The packaging job runs `build_tools/check_frozen_bundle.py` **before** compiling the installer: it lists the built exe's embedded archive via PyInstaller's `archive_viewer -r -b` and requires every module from the shared import scan to be present, in the exe **or** in the sibling `_internal/`. | A dependency relationship has two ends and the CI suite can only see one. Deciding **against** a "did the exe stay alive for 20 seconds" smoke test: an unhandled exception on Windows opens a modal crash dialog, the process then hangs waiting for a click, so "did not exit" is exactly what a crash looks like — the check would pass the defect it was built for. The archive listing was validated against a real one-file build before being relied on. |
| **D24** | The core runtime dependencies live in a new **`requirements.txt`**, which `requirements_qt.txt` already referred to; `requirements-ci.txt` references it instead of listing those packages a second time; the packaging job installs it. | The first published Release (v2.3.1) could not start: `No module named 'flask'`. The dependency was not missing from the *code*, it was missing from the *packaging input* — and CI stayed green precisely because the list had been copied in two places. |
| **D25** | A test walks the app's **module-level, unguarded** imports and requires every one to be declared in `requirements_qt.txt` + `requirements.txt`, and requires the packaging job to install that set. | The gap that shipped a broken binary. Deliberately scoped to module-level unguarded imports: a function-body import is lazy (this app lazy-loads pages), and a `try/except`-guarded import is an intentional optional dependency — declaring those would change product behaviour by enabling fallback paths the author left disabled. Recorded limitation: guarding a hard import turns this test green while only converting a crash into a silent degradation. |
| **D21** | The Simplified Chinese Inno translation is **bundled** at `build_tools/Languages/ChineseSimplified.isl` (MIT, kira-96) and `installer.iss` references it script-relatively instead of via `compiler:`. | `compiler:` resolves against the **compiler's own** Languages folder, which official Inno Setup does not populate with Simplified Chinese, so the build depended on what the machine happened to have (run 36414070599, line 72). Owner's decision: bundle it. |
| **D22** | ISCC is invoked with the **script's own directory** as `cwd`, not the repo root. | `installer.iss` mixes two relative bases — `..\release\…` for `OutputDir` / `[Files] Source`, bare `installer_assets\…` and `Languages\…` for the icons, wizard art and translation. Fixing cwd makes both interpretations agree, instead of guessing which one Inno uses. |
| **D23** | **Supersedes D13.** The release path has **no test gate**: `preflight -> build -> publish`. `ci.yml` still runs on every push, it just no longer blocks publishing. | Owner: a fork of the repo, wants an exe, not the upstream developer. `test` is 16 min on the runner and **never once blocked a real failure** — the three that stopped releases were all in `build-installer.yml` (D18, D19, D21). Stated cost: a commit with a red matrix can still ship a binary. Recorded so re-adding the gate is a decision, not a silent "fix". |
| **D20** | `installer.iss` carries a UTF-8 BOM, and `build_release.run()` gained a `capture` switch used **only** for the ISCC call. | ISCC reads a BOM-less `.iss` as system ANSI, so a file full of Chinese compiles on a cp936 machine and fails on a cp1252 runner. The capture switch exists because that failure produced a log with an exit code and nothing else (entry 8). PyInstaller deliberately keeps streaming: capturing a 15-minute build means a silent log. |
| **D19** | The installer is compiled by `python build_tools/build_release.py --mode onedir --installer-only`, never by a hand-written `iscc` invocation in shell. | Run 36406788535: git-bash + `\r` from `$(python -c ...)` + MSYS argument conversion on `/DAppVersion=…` made ISCC read the define as a second script filename, and the error pointed nowhere near the cause. The project already owns a hardened path (version read from `config.VERSION`, `find_tool("iscc")` with a "searched these paths" error, `subprocess` with a list so no shell is involved). |
| **D18** | The packaging job installs `pytest` alongside the build requirements, rather than adding it to `requirements-build.txt` or switching to `requirements-ci.txt`. | `build_release.py:951` runs a test as a pre-build gate, so the test runner is a **build** dependency. `requirements-build.txt` has an exact-content test (`PyInstaller>=6.21,<7` only) and `requirements-ci.txt` drags in flask / pygame / sounddevice / numpy / pywin32 — neither is the right place. |
| **D15** | The Release carries **exactly one asset**, the installer `.exe`. The SHA256 moves into the release notes body. | Owner's decision (they asked for "only exe apk", then learned there is no APK). The checksum still ships, and a downloader of only the exe still sees it. |
| **D16** | This project has **no Android build and no APK is planned**. | It is a Windows-only PyQt5 app: Windows Magnification API, GSI, cfg writes, pywin32 autostart. An APK is a separate port with its own toolchain, not a build flag. Owner informed 2026-09-28. |
| **D13** | The `ci` job runs again inside `release.yml` on the pushes that actually publish, duplicating the standalone `ci.yml` run for the same push. | Accepted deliberately: the "wait for another workflow" patterns (`workflow_run`) need re-run, staleness and cross-workflow state handling, which is far more machinery than the saved runner minutes. Duplication only happens on version-bump commits. |

---

## 2. Glossary

| Term | Meaning in this project |
| ---- | ----------------------- |
| `config.VERSION` | The single source of truth for the version (`config.py`). `version_info.txt`, the tag, and the Inno compile all derive from it. |
| onedir | PyInstaller output mode: an exe plus an `_internal/` directory. Chosen over `onefile` (much faster cold start). |
| GSI | Valve's Game State Integration — the only supported way this tool reads game state, plus reading/writing CS2 `cfg` files. |
| `build-installer.yml` | Packaging gate. Builds onedir + Inno installer, uploads a 90-day artifact. Does **not** publish. |
| `release.yml` | Publication pipeline. Runs `ci.yml`, calls `build-installer.yml`, then creates the Release. |
| `publish` job | The only job with `contents: write`. Downloads the artifact, writes release notes, runs `gh release create`. |
| Reusable workflow | A workflow invoked with `uses: ./.github/workflows/<file>`; it runs only its jobs, never its own `on:` triggers. Resolved at the caller's ref, so a tag release uses the workflow file from the tagged commit. |
| "The gate is green but idle" | A check that passes because it scanned nothing. Guarded here by `tests/_denominator.py::must_scan`. |

---

## 3. Progress & Work Plan

Status labels: ✅ complete · 🟡 partial · 🔴 blocked / defect · ⏳ planned. Newest entries at the end.

### ✅ Entry 1: Release pipeline (2026-09-28)

**What / why.** Owner instruction: make an action that publishes a GitHub Release with the `.exe`;
the repository had no Release at all, so there was no download path for the open-source build.

**Changed.**
- `.github/workflows/release.yml` (new) — `on: push tags v*`; jobs `ci` -> `build` -> `publish`;
  top-level `permissions: contents: read`, `contents: write` on `publish` only; `concurrency`
  `release-${{ github.ref }}` with `cancel-in-progress: false`; `gh release create --verify-tag
  --target $GITHUB_SHA` with `dist/*.exe` and `dist/*.sha256`.
- `.github/workflows/ci.yml` — added `workflow_call:`.
- `.github/workflows/build-installer.yml` — added `workflow_call:`; header comment corrected
  (it still does not publish, but it is now also called by `release.yml`).
- `tests/test_release_wiring.py` (new) — 8 cases: parse-all (denominator guard), `v*` trigger,
  job graph and transitive `ci` gate, write-permission scope, both reusable entry points, SHA
  pinning across all workflow files, `--verify-tag` + attachment check, changelog-sourced notes.
- `README.md` / `README.en.md` — the "no Release binaries" block rewritten; new
  "发一个 Release" / "Publishing a Release" subsection describing the chain, the tag/version
  consistency gate, the unsigned-exe caveat, and the one-Release-per-tag rule.

**Decision(s).** D1, D2, D3, D4, D5, D6, D7, D8.

**Verified.** `tests/test_release_wiring.py` 8 passed. Mutation check: removing `needs: ci` from
`build` turns the file red (1 failed) and restoring turns it green again. `ci.yml`,
`build-installer.yml`, `release.yml` all parse with PyYAML. Changelog extraction proven locally for
`2.3.1` (section found, notes emitted) and for a nonexistent `9.9.9` (exit code 1). Ruff clean on
the new test. Adjacent suites re-run green: `test_version_consistency.py` 9, `test_no_legacy_brand.py`
7, `test_the_index_gate_is_wired_into_ci.py` 3, `test_audit_coverage_r11.py` 9 (+1 skip),
`test_ci_gates_read_the_verdict_line.py` 9, and
`test_lazy_imports_r8a.py::test_ci_workflow_uses_only_job_level_contexts` 1. All four new/modified
files are LF-only per `.gitattributes`.

**Not done / open.** Not committed, not pushed. **Not verified on a runner:** no workflow has ever
executed — PyInstaller, Inno, `gh release create`, the bash heredoc under `shell: bash` on
`windows-latest`, and the artifact round trip are all untested in a real Actions run. First real
proof is a tag push. `tests/test_startup_splash.py` and `tests/test_brand_assets.py` could not be
collected locally (no `PIL` in the isolated venv) — unrelated to this change, but that leaves
`test_packaging_guide_uses_pinned_build_requirements` unrun; its three assertions were checked by
string inspection of `README.md` instead.

**Supersedes.** The claim in `README.md` / `README.en.md` that this repository publishes no Release
binaries (now false, see section 4). `PROGRESS.md` did not exist before this entry — there is no
earlier log to reconcile.

### ⏳ Entry 2: First real release (planned)

**What / why.** Nothing ships until a tag is pushed. `CHANGELOG.md` still marks `## [2.3.1]` as
"开发中" and `config.VERSION` is `2.3.1`, so the tag would have to be `v2.3.1`.

**Not done / open.** Owner decisions: (a) whether to close the "开发中" marker first; (b) whether to
commit and push the workflow, and (c) whether to push the `v2.3.1` tag. Also undecided and
**deliberately not changed**: `build_tools/installer.iss` still carries upstream identity
(`AppPublisher` 孤帆, `AppURL` https://github.com/gufan0000/cs2-customizer) — a fork release will
show upstream's name and URL in the installer's Add/Remove Programs entry. That is attribution the
upstream licence context may want, so it is the owner's call.

### ✅ Entry 3: Auto-release on push (2026-09-28)

**What / why.** Owner instruction, verbatim intent: automate the push so that an update from origin
updates the Release with a tag. Entry 1's manual-tag design was therefore overtaken the same day it
was written — the owner does not want a tagging step.

**Changed.**
- `.github/workflows/release.yml` — rewritten. `on: push {branches: [main], tags: ["v*"]}`;
  new `preflight` job on `ubuntu-latest` reads `config.VERSION`, asks GitHub whether `v<version>`
  already has a Release, and sets `should_release` / `version`; `ci`, `build` and `publish` are all
  gated on `should_release == 'true'`. `publish` now runs `gh release create "v$VERSION" --target
  "$GITHUB_SHA"` (no `--verify-tag`), and the notes/tag version comes from
  `needs.preflight.outputs.version`. The stale-tag case (remote `v<version>` with no Release) exits 1
  via `git ls-remote`.
- `README.md` / `README.en.md` — the "发布一个 Release" section and the top block rewritten from
  "push a tag" to "bump `VERSION`, push `main`", with the four-stage chain and the three deliberate
  design rules spelled out.
- `tests/test_release_wiring.py` — grew to 9 cases: added `test_preflight_short_circuits_unreleased_pushes`
  (both skip and release branches, plus the `gh release view` and `git ls-remote` guards), rewrote the
  tag test for `--target`/no-`--verify-tag`, and scoped all bash-scanning assertions to a **specific
  job's `run` scripts** (`_run_text`) instead of the whole file.

**Decision(s).** D9, D10, D11, D12, D13. Supersedes D6.

**Verified.** `tests/test_release_wiring.py` 9 passed; ruff clean. Five mutations of `release.yml`
each turned it red and restoring turned it green: dropping `build`'s `if:`, dropping `ci`'s `if:`,
changing `--target "$GITHUB_SHA"` to `--target main`, making preflight always release, and removing
preflight's `gh release view` check. Re-ran after each restore. Adjacent suites: 37 passed, 1 skipped
(`test_version_consistency`, `test_no_legacy_brand`, `test_the_index_gate_is_wired_into_ci`,
`test_audit_coverage_r11`, `test_ci_gates_read_the_verdict_line`,
`test_lazy_imports_r8a::test_ci_workflow_uses_only_job_level_contexts`).

**Not done / open.** **Not verified on a runner** — no Actions run has ever happened. Untested in
practice: the preflight bash (`python3` regex, `gh release view`, `git ls-remote` against a real
remote), `gh release create --target` creating the tag, and the `needs.<job>.outputs` wiring through
a reusable-workflow call. **Consequence the owner must know before pushing:** the first push to `main`
publishes **v2.3.1** automatically, because `VERSION` is already `2.3.1` and no Release exists. The
owner deferred the changelog-heading and installer-identity questions to the automation decision, so
`CHANGELOG.md` still says `## [2.3.1] - 开发中` (the marker is not part of the extracted notes) and
`build_tools/installer.iss` still names the upstream publisher and upstream repo URL.

**Supersedes.** Entry 1's manual-tag trigger and its `build-installer.yml`-header claim; D6.

### ✅ Entry 4: First run failed — the CI gate cancelled itself (2026-09-28)

**What / why.** The first real execution of the pipeline, triggered by the push of entry 3. It
failed, and **no Release was created** — the failure is harmless to the outside world and worth
reading precisely, because the symptom pointed at nothing that was actually broken.

**Observed (run 36401751401, head 040f485).** `preflight` succeeded and logged
"v2.3.1 还没发过"; `build` and `publish` were `skipped`; **the `ci` job produced no job record at
all**; run conclusion `failure`. `actionlint` 1.7.12 reported **zero problems** for all three
workflow files, so this was not a schema error — the job was destroyed at scheduling time.

**Root cause.** `ci.yml` carries
`concurrency: {group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true}`. In a
**called** reusable workflow, `github.workflow` is not a value this repository controls — it can
resolve to the callee (`ci`). When it does, the release's gate job and the **standalone** `ci.yml`
run for the same push land in the **same concurrency group**, and `cancel-in-progress: true` makes
them cancel each other. Both runs started 09:09:57; preflight finished 7 seconds later, inside the
window.

**Changed.** `.github/workflows/release.yml` — the `ci` gate job now declares
`concurrency: {group: release-gate-${{ github.ref }}, cancel-in-progress: false}`; the reason is
written into the file so the next person does not "clean it up". `tests/test_release_wiring.py`
grew to 11 cases: `test_release_gate_does_not_cancel_itself` (the group must not mention
`github.workflow`, and must not cancel) and `test_release_contains_only_the_installer` (D15).
`README.md` / `README.en.md` — the asset list is now one exe with the checksum in the notes.

**Decision(s).** D14, D15, D16.

**Verified.** 11 passed; ruff clean; `actionlint` clean on all three workflows. Five new mutations
each turned the file red and restoring turned it green: delete the gate's `concurrency`, put
`github.workflow` back in the group, set `cancel-in-progress: true`, re-add the `.sha256` as an
asset, and stop writing the checksum into the notes. **Not verified:** that the fix actually lets
the gate start — only a real run proves that, and the next push is that proof.

**Not done / open.** The pipeline is unproven end to end: `ci` gate start, PyInstaller, Inno, the
artifact round trip, and `gh release create --target` have still never run. The next push to `main`
publishes v2.3.1 for real (owner's explicit approval, 2026-09-28).

**Supersedes.** Nothing; this is the first execution record. Corrects the entry 1/3 claim that the
graph was ready — it was correct on paper and wrong at runtime, which is why "verified on a runner"
was and stays a separate line in every entry.

### ✅ Entry 5: The first fix was wrong; the group lives in the callee (2026-09-28)

**What / why.** Entry 4 claimed a caller-side `concurrency` had fixed the self-cancelling gate. It had
not. Run **36402772836** — pushed with D14 in place — failed **identically**: preflight success, the
`ci` gate job with no job record, `build` / `publish` skipped, run `failure`, no error message. A fix
that survives zero re-runs is not a fix, so entry 4's claim is now marked wrong rather than quietly
edited.

**What the second run actually told us.** The standalone `ci` run for the *first* push had concluded
`cancelled`. Nothing had cancelled it except another run of the same file: the release's gate. So the
group collision was real — but the group that collides is the one **inside `ci.yml`**, and in a called
workflow `github.workflow` resolves to the **callee** (`ci`), which is why a caller-side override on
the calling job changed nothing.

**Changed.** `.github/workflows/ci.yml` — `concurrency.group` is now
`${{ github.workflow_ref }}-${{ github.ref }}`, with the incident written next to it.
`github.workflow_ref` is the *caller's* workflow file path: `.../ci.yml` for a push, `.../release.yml`
when called from the release pipeline, so the two runs can never share a group. Standalone
cancellation behaviour is unchanged (same run, same group). `.github/workflows/release.yml` — the D14
concurrency block removed, replaced by a comment pointing at `ci.yml`, so nobody re-adds a second
mechanism. `tests/test_release_wiring.py` — the guard rewritten to
`test_reused_workflow_concurrency_group_is_caller_specific`, asserting the invariant where it actually
lives (the callee), plus that the caller carries no group of its own.

**Decision(s).** D17 (supersedes D14).

**Verified.** 11 passed; ruff clean; `actionlint` clean on all three workflows. Five mutations turned
the file red, restoring turned it green: revert the group to `github.workflow`, drop
`cancel-in-progress`, delete `concurrency` entirely, re-add the caller-side group, and drop the
`workflow_ref`. ⚠ One of those five mutation runs first reported a false pass — the replacement had hit
the word `cancel-in-progress: true` **inside the new explanatory comment** instead of the setting.
The mutation was wrong, not the test; re-run with the setting line as the anchor, it goes red.

**Verified on a runner (2026-09-28, run 36403249454, head 27b53ff).** The gate starts. The run is
`in_progress` instead of dead in 5 seconds, and it carries `ci / test` and `ci / ui-audit` — the
nested `ci / <job>` names are the reusable workflow's own jobs, and the standalone `ci` run for the
same commit is running alongside it without either being cancelled. That is the whole claim of D17
confirmed against GitHub, not against a schema linter.

⏳ **Still unverified downstream of the gate** (as of this writing): PyInstaller, Inno Setup, the
artifact round trip, `gh release create --target`, and whether v2.3.1 actually appears. This entry
is being written while that run is still in flight; check the run's conclusion before trusting the
rest of section 3.

**Not done / open.** Everything downstream of the gate is still unproven: PyInstaller, Inno, the
artifact round trip, `gh release create --target`. The next push to `main` publishes v2.3.1 for real
(owner approved 2026-09-28).

**Supersedes.** Entry 4's "Changed"/"Decision(s)" for the concurrency fix, and D14.

### 🟡 Entry 6: The packaging job never installed pytest (2026-09-28)

**What / why.** Run 36403249454 cleared the gate (D17 confirmed) and then failed in the packaging job
at step 6, "构建 onedir 产物", on one decisive line:

    C:\hostedtoolcache\windows\Python\3.13.15\x64\python.exe: No module named pytest
    [CMD] ...\python.exe -m pytest -q tests/test_no_bundled_assets.py

`build_tools/build_release.py:951` runs `tests/test_no_bundled_assets.py` as a **pre-build gate**
(`if not args.skip_tests`), and the packaging workflow installed only `requirements_qt.txt` +
`requirements-build.txt` (PyInstaller). pytest lives in `requirements-ci.txt`. So the packaging
workflow has never been able to finish on a clean runner — this is **pre-existing in
`build-installer.yml`**, not something the release work introduced, and it would have blocked any
release attempt from this repository.

**Changed.** `.github/workflows/build-installer.yml` — the install step now adds `pytest`, with the
reason and the reason-not-to-use-`requirements-ci.txt` written next to it.
`tests/test_release_wiring.py` gained
`test_packaging_workflow_installs_the_test_runner_the_build_script_calls` (12 cases now): it reads
`build_release.py`, requires the pre-build gate to still exist, then requires the packaging job's
`pip install` line to name pytest — and pins that pytest is **not** in `requirements_qt.txt` /
`requirements-build.txt`, so the assertion cannot be satisfied by accident later.

**Decision(s).** D18.

**Verified.** 12 passed; ruff clean; `actionlint` clean. Three mutations turn the file red and
restoring turns it green: drop pytest from the install line, delete the whole install line, and remove
the pre-build gate from `build_release.py`. A fourth mutation (adding pytest to
`requirements_qt.txt`) was skipped — `pytest` is not currently in that file, so the anchor was absent.
**Not verified:** that the packaging job now completes. PyInstaller, Inno Setup, the artifact round
trip and `gh release create --target` are all still unproven.

**Not done / open.** If the next run gets past PyInstaller, the next unproven thing is Inno Setup
(`choco install innosetup` on the runner) and then the publish job. Keep reading section 5 before
believing any of it.

**Supersedes.** Nothing; first record of this defect. Corrects the implicit assumption in entries 1,
3, 4 and 5 that the packaging job worked — it was never actually executed to completion.

### 🟡 Entry 7: The hand-rolled `iscc` call mangled its own arguments (2026-09-28)

**What / why.** Run 36406788535 (head 81eb8bb) is the first run to get the gate green
(`ci / test` and `ci / ui-audit` both success) and to build the onedir tree. It then failed at the
installer compile step:

    You may not specify more than one script filename.
    Inno Setup 6 Command-Line Compiler

Nothing about that message points at the real cause, which is two layers of escaping stacked:

- the step used `shell: bash`, i.e. git-bash, on a Windows runner;
- the version came from `ver=$(python -c "…")`, whose output keeps the Windows `\r`
  (`$( )` strips the trailing newline, not the carriage return), so `/DAppVersion=$ver`
  carried a stray `\r`;
- and `/DAppVersion=<值>` is an argument that starts with a slash, which MSYS argument conversion
  rewrites before the Windows binary ever sees it.

ISCC consequently read the define as a second script filename. The step had been fine on a developer's
machine and wrong on the runner — the classic shape of a shell-quoting bug.

**Changed.** `.github/workflows/build-installer.yml` — the compile step is now
`python build_tools/build_release.py --mode onedir --installer-only`, with the failure written next to
it. That path already did all three things right: version read straight from `config.VERSION` and
passed as `/DAppVersion` (the `.iss` has no fallback constant, so a missing define is a hard `#error`),
`find_tool("iscc")` locating the compiler and naming every path it searched when it fails, and
`subprocess.run` with a **list**, so no shell quoting or argument conversion is involved at all.
`--mode onedir` is required alongside `--installer-only` because the installer's `[Files]` section only
accepts the onedir layout.

`tests/test_release_wiring.py` gained `test_installer_is_compiled_by_the_build_script_not_by_hand`
(13 cases now): no step may contain a raw `iscc` call, the `--installer-only` step must exist, the
`--mode onedir` flag must be **on that same command**, and `build_release.py` must still pass the
version via `/DAppVersion`.

**Decision(s).** D19.

**Verified.** 13 passed; ruff clean; `actionlint` clean. Four mutations turn it file red and restoring
turns it green: revert to a hand-rolled `iscc`, drop `--installer-only`, drop `--mode onedir`, and stop
passing `/DAppVersion` from the script.
⚠ **One of those four first reported a false pass.** Dropping `--mode onedir` stayed green because
`--mode onedir` also appears in the *build onedir* step, and the assertion concatenated every step's
script before searching. That is the same shape as an earlier miss in this file (a `gh release view`
string that also appeared in a different job). Both are now fixed by matching **per step**
(`_run_scripts`) rather than over the whole job. ⭐ **一个字符串出现过，不等于那件事发生在你以为它
出现的地方。**
**Not verified:** that the installer compiles. The next runner proof is the one that matters.

**Not done / open.** SHA256, artifact upload and `gh release create --target` are still unproven —
nothing has ever reached the publish job.

**Supersedes.** Nothing; first record of this defect.

### 🟡 Entry 8: ISCC exits 2 and the log says nothing (2026-09-28)

**What / why.** Run 36411234329 (head 2c467f4) passed the gate, built the onedir tree, and reached
the installer compile with **correct arguments this time** — `[INFO] ISCC detected:
C:\ProgramData\Chocolatey\bin\iscc.EXE` then
`[CMD] …\iscc.EXE …\build_tools\installer.iss /DAppVersion=2.3.1`. ISCC then returned exit status
2, and between the `[CMD]` line and the traceback there was **not one word** from the compiler.

**Two defects, in priority order.**

1. **The build swallowed the compiler's diagnostics.** `build_release.run()` inherited the parent's
   stdout, so in principle output should have been visible; whatever the reason it was not (a
   Chocolatey shim is an indirection that can only lose information). Either way, on the one command
   whose entire purpose is to tell you why it failed, that is unacceptable. `run()` now takes
   `capture` and the ISCC call sets it, printing both streams **before** raising. PyInstaller
   deliberately keeps `capture=False`: capturing a 15-minute build leaves a silent log, and a silent
   log cannot tell you the build is still alive.

2. **`installer.iss` was UTF-8 without a BOM** and contains 2811 non-ASCII bytes — `AppPublisher`'s
   Chinese name and the entire `[Messages]` section. ISCC decodes a BOM-less `.iss` with the
   **system ANSI code page**, so one file yields two different results: a cp936 dev machine
   mis-decodes it into mojibake and still compiles; a cp1252 GitHub runner hits bytes that are
   undefined in that code page and the compile fails. This is the textbook "works on my machine",
   and the file has never been byte-different — only the machine is.

**Changed.** `build_tools/build_release.py` — `run()` gained `capture: bool = False`; the ISCC call
passes `capture=True`. `build_tools/installer.iss` — UTF-8 BOM added.
`tests/test_build_installer_step.py` (18 → 21 cases) — `test_installer_iss_is_utf8_with_bom`;
`test_run_prints_child_output_even_when_it_fails`; `test_run_capture_is_off_by_default_and_reaches_subprocess`;
`test_run_does_not_raise_when_check_is_off`; and `test_installer_passes_version_from_caller` extended
to assert the ISCC call really captures. Its `run` double had a hardcoded three-parameter signature
and had to be widened — a `TypeError` raised inside a test double reports at the double, while the
compiler never runs at all.

**Decision(s).** D20.

**Verified.** 21 passed in `test_build_installer_step.py`, 13 in `test_release_wiring.py`, ruff clean
on both changed source files. Three mutations turn the suite red: remove the BOM, drop `capture=True`
from the ISCC call, remove `capture` from `run()`'s signature.
⚠ Two of my own judgements were wrong on the way here and are worth keeping: (a) removing `capture`
from the signature left **31 cases green** — nothing executed the real `run()`, every caller-side test
monkeypatched it; the behavioural tests above are what close that. (b) A first attempt asserted
"output was not captured" via `capsys`, which measures pytest's capture plumbing, not `run()`; a
child process writes to an OS handle, so that assertion is not well-founded at the Python level. It
was replaced with a test of the arguments actually passed to `subprocess.run`.
**Not verified:** that either of the two fixes makes the compile succeed.

**Not done / open — the second candidate, still unexamined.** The `.iss` mixes two bases:
`OutputDir` / `[Files] Source` use `..\release\…` (script-relative, which is what Inno documents)
while `SetupIconFile` / `WizardImageFile` use `installer_assets\…` (no `..`). ISCC is invoked with
`cwd=project_root`, so if Inno resolves those three relative to the *current directory* rather than
the script directory, they are not found and the compile fails with a "file not found" that the
capture switch will now actually print. Guessing a fix here would repeat the mistake of D14, so it
was left alone until the log says so.

**Supersedes.** Nothing; first record of this failure. Adds to the pattern in entries 6 and 7:
**three pre-existing defects in `build-installer.yml` in a row, none of which had ever been
executed on a runner.**

### 🟡 Entry 9: The build depended on what the build machine had installed (2026-09-28)

**What / why.** The `capture` switch from entry 8 finally produced the compiler's own message, and it
was neither candidate I had written down:

    Error on line 72 in installer.iss: Couldn't open include file
    "c:\program files (x86)\inno setup 6\Languages\ChineseSimplified.isl":
    The system cannot find the file specified.

Line 72 read `MessagesFile: "compiler:Languages\ChineseSimplified.isl"`. The `compiler:` prefix means
"look in the **compiler's own** Languages folder". Official Inno Setup ships about a dozen languages;
**Simplified Chinese is a third-party translation**. The upstream author's Chinese Windows had it
installed; the GitHub runner does not. So the packaging workflow's outcome depended on the build
machine's installed software — the textbook CI-only failure, and the reason local and CI could never
be made to agree by tweaking flags.

**Changed.**
- `build_tools/Languages/ChineseSimplified.isl` — new, bundled: the MIT translation from
  `kira-96/Inno-Setup-Chinese-Simplified-Translation` (Inno 6.5.0+), stored as UTF-8 **with BOM** for
  the same reason as the `.iss` itself.
- `build_tools/installer.iss` — `MessagesFile: "Languages\ChineseSimplified.isl"` (script-relative),
  with the reason written beside it.
- `build_tools/build_release.py` — ISCC now runs with `cwd=iss_path.parent` (the script's directory).
  That also closes the second open candidate from entry 8: the `.iss` uses `..\release\…` for
  `OutputDir` and `[Files] Source` but bare `installer_assets\…` for the three icon and wizard images.
  Fixing cwd makes both interpretations resolve the same way, so there is nothing left to guess about.
- `THIRD-PARTY-NOTICES.md` — a section for the bundled file: source, maintainer (Zhenghan Yang / Kira),
  MIT, and why it is bundled.
- `.github/workflows/release.yml` — **the test gate is removed** (D23). `ci.yml` still runs on every
  push; it no longer blocks this fork's releases.
- `tests/test_build_installer_step.py` 21 → 24 cases, `tests/test_release_wiring.py` still 13 with
  `test_publish_gates_on_ci_and_build` rewritten into
  `test_release_path_deliberately_has_no_test_gate`.

**Decision(s).** D21, D22, D23 (which supersedes D13).

**Verified.** 24 + 13 passed; ruff clean on both test files and `build_release.py`; `actionlint` clean.
Nine mutations turn the suite red: delete the bundled `.isl`, strip its BOM, revert the `.iss` to
`compiler:`, revert ISCC's cwd, drop the maintainer credit, drop the source repo, relabel the licence,
and quietly re-add the `ci` gate to `release.yml`.
⚠ **Four of my mutations were faulty, not the tests**, and all four were the same mistake: I replaced
the **first** occurrence of a string, and the first occurrence was somewhere else — a dependency
table's `MIT`, a comment quoting the old `compiler:Languages`, a `run` signature, the `cancel` in a
comment. Re-anchored on the unique string and each went red. Related: the notices check originally
scanned the whole file, where `MIT` appears a dozen times, so relabelling that section's licence
stayed green until the check was scoped to its own section — the **fourth** time in this project that a
scan matched the wrong occurrence of a string (workflow comment, a name in two jobs, an `.iss`
comment quoting the old path, now a licence that appears elsewhere in the document).
**Not verified:** that the installer now compiles. Everything from here on — the compile, SHA256, the
artifact round trip, `gh release create --target` — is still unproven.

**Not done / open.** A red test matrix can now ship a binary. Recorded in D23 and enforced by a test
that asks whoever re-adds the gate to write down why.

**Supersedes.** D13. Entry 8's second open candidate (the mixed relative bases) is now closed by
construction, not by a fix.

### 🔴 Entry 10: The first published Release could not start (2026-09-28)

**What / why.** Run 36415053429 succeeded — the pipeline's first green end-to-end, and it created
Release **v2.3.1** with the installer attached. The owner launched the exe and got:

    Failed to execute script 'main_widget' due to unhandled exception:
    No module named 'flask'

**Root cause — one promise, no file behind it.** `requirements_qt.txt` carries this comment:

    注意事项：核心运行依赖在 requirements.txt 里（不是 Qt 专用）
    - customtkinter（改版需要） - pygame（音频系统） - **flask（GSI 服务器）** - 等等…

**`requirements.txt` does not exist in this repository** — the open-sourcing did not carry it. The
only place those packages were listed was `requirements-ci.txt`, which had **copied them a second
time** to make CI work. So: CI installed flask, packaging installed `requirements_qt.txt` only, and
`gsi_server.py:7`'s top-level `from flask import Flask, request, jsonify` — the GSI receiver the
main window starts — was simply absent from the frozen app. The developer's machine had flask
installed globally, so nothing had ever shown it.

**Changed.**
- `requirements.txt` — **new**: flask, pygame, sounddevice, soundfile, numpy, keyboard, pynput,
  pywin32, pypinyin, PyYAML. Every version bound identical to what `requirements-ci.txt` had
  (verified programmatically, spec by spec). Its header states the two failures this file prevents.
- `requirements-ci.txt` — now `-r requirements_qt.txt` + `-r requirements.txt` + `pytest>=8.0`.
  The duplicated list is gone, so the next dependency change cannot rot in one place only.
- `.github/workflows/build-installer.yml` — installs the runtime set.
- `README.md` / `README.en.md` — the documented local-run and build commands now install
  `requirements.txt`; without this, a clean machine following the README hits the same crash.
- `tests/test_runtime_dependency_coverage.py` — **new**, 4 cases (D25).
- `THIRD-PARTY-NOTICES.md` — the two lines that named the source of version bounds now include
  `requirements.txt`.

**Decision(s).** D24, D25.

**Verified.** 4 passed. Four mutations go red, and one correctly goes green:
delete `flask` from the requirements (the accident itself), drop `-r requirements.txt` from the
packaging job, copy `flask` back into `requirements-ci.txt`, delete `requirements.txt` — all red;
and wrapping `gsi_server.py`'s flask import in `try/except ImportError` goes **green**, because a
guarded import is by definition optional. That is the check reporting the code's intent faithfully,
and it is written down as a limitation in the test: it converts a crash into a silent degradation,
so taking that route has to be a documented decision.
**Not verified:** that a rebuilt exe actually starts. That needs one more build.

**Not done / open — the owner's call, and it is a public artifact.** Release **v2.3.1** is
published, tagged, and broken. Three ways out, none of which I will take unasked:
1. bump `config.VERSION` to 2.3.2 (+ a `## [2.3.2]` CHANGELOG section) and let the pipeline publish a
   working build; v2.3.1 stays as the broken first attempt;
2. additionally delete the v2.3.1 Release and its remote tag, so nobody downloads a broken exe —
   irreversible for anyone who already did;
3. leave it and just fix forward.

**Supersedes.** Nothing. Corrects D18's reasoning, which used "requirements-ci.txt drags in flask /
pygame / sounddevice / numpy / pywin32" as an argument *against* using it — that drag was not
incidental noise, it was the symptom: the packaging job was installing a set that cannot run the
app, and I read the extra packages as a reason to avoid them rather than as evidence of the hole.

### ✅ Entry 11: Delete the broken v2.3.1, and check the artifact instead of the list (2026-09-28)

**What / why.** Two owner decisions on the back of entry 10. (1) Delete the broken Release.
(2) Add a check that actually looks at the built exe. Both are now done; the first one changed
public state.

**Deleted (irreversible).** `gh release delete v2.3.1 --cleanup-tag`: the Release and the remote tag
are gone; the Releases page is empty again. Anyone who had already downloaded the installer still has
it. The pipeline did exactly what it was built to do — the artifact was simply wrong, and no amount of
workflow work would have caught that, which is the point of this entry.

**The artifact check.** `build_tools/import_scan.py` (new) is the single implementation of "which
third-party modules does this app need to start": module-level, unguarded, non-stdlib, non-internal.
`build_tools/check_frozen_bundle.py` (new) lists the built exe's embedded archive with PyInstaller's
own `archive_viewer -r -b` and requires each of those modules to be present — in the exe's PYZ **or**
in the sibling `_internal/`, because onedir keeps C extensions outside the exe. It runs in
`build-installer.yml` right after the onedir build, before Inno Setup, so a bad product stops there.

**Why not a "launch the exe" smoke test — the reason is worth keeping.** An unhandled exception in a
frozen Windows app opens a **modal** crash dialog (the one in the owner's screenshot) and the process
then *hangs* waiting for a click. A timeout-based check ("the exe is still alive after 20 seconds")
therefore returns **green for exactly the crash it was written to catch**. Waiting for the process to
*exit* would be worse: a clean launch also doesn't exit. Getting a real smoke test means adding a
headless self-check entry point to the app, which is app work, not build work — recorded as the
honest limit of this approach rather than faked with a timeout.

**Changed.** `build_tools/import_scan.py`, `build_tools/check_frozen_bundle.py` (both new);
`.github/workflows/build-installer.yml` (the check step); `tests/test_runtime_dependency_coverage.py`
4 → 8 cases, now importing the shared scanner instead of carrying its own copy.

**Decision(s).** D26, plus D24/D25 from entry 10.

**Verified.** 8 passed; ruff clean. Six mutations go red: delete `flask` from the requirements,
drop `-r requirements.txt` from the packaging job, remove the bundle-check step, move the bundle check
after the installer compile, copy `flask` back into `requirements-ci.txt`, delete `requirements.txt`.
Two mutations correctly stay green: wrapping the flask import in `try/except` (a guarded import is by
definition optional — this converts a crash into a silent degradation, so it is a product decision, not
a fix), and the archive-listing parser reading a synthetic listing.
⚠ **One of my own mutations was faulty twice over, and the first version of the ordering assertion was
a判据 that could never fail.** It compared positions of `check_frozen_bundle.py` and `iscc` in the raw
file; D19 had already removed the `iscc` invocation, so the comparison degenerated to "position <
end of file" — always true. The second attempt searched the raw text again, and the workflow's
comments mention the script by name, so replacing the command with `echo later  # check_frozen_bundle.py`
stayed green. It now parses the YAML, finds the step by **step order**, and requires that step's `run`
to *be* the invocation (prefix match). ⚠⭐ **A judge that cannot fail is worse than no judge**, because
it makes people believe something is being checked. This is the third family of that bug in this
project after `_denominator.py` was written for the first one.
**Not verified:** that a real build passes the bundle check. The archive listing format was validated
against a real one-file build; the onedir layout, the `_internal/` half, and the whole check on a real
product build are unproven until the next run.

**Not done / open.** `PROGRESS.md` is now past 700 lines and needs compaction.

**Supersedes.** Nothing.

---

## 4. Known drift and superseded claims

Claims in code comments, older documents or earlier entries that are known to be wrong. Anything
remembered from a superseded source is unverified until re-checked.

| Source | Claim | Reality | Disposition |
| ------ | ----- | ------- | ----------- |
| `README.md` line 34 (pre-2026-09-28) | "**本仓库不发布 Release 安装包。**" | The fork now publishes a Release built from this source. | Rewritten in place; old wording superseded by entry 1. |
| `README.en.md` line 37 (pre-2026-09-28) | "**This repository publishes no Release binaries.**" | Same, English side. | Rewritten in place. |
| `README.md` / `README.en.md` build section | "**不进 Release**" about `build-installer.yml` | Still true of that workflow alone; it is no longer true of the tag path as a whole. | Kept, re-scoped to "when run on its own". |
| `build-installer.yml` header | "**它不发布 Release。**" / "本仓库不做二进制分发渠道" | The first half is still true of this file; the second is no longer true of the repository. | Header rewritten to state both halves. |
| Entries 1 and 3 (2026-09-28) | "The job graph is ready; first proof is a tag push." | The first run cancelled its own CI gate (entry 4). Paper-correct, runtime-wrong. | Superseded by D14 and entry 4. |
| D18 (2026-09-28) | "requirements-ci.txt drags in flask / pygame / sounddevice / numpy / pywin32 — neither is the right place." | That drag was the symptom, not noise: the packaging job was installing a set that **cannot run the app**, and I read it as a reason to avoid the file rather than as evidence of the missing `requirements.txt`. | Corrected by D24 and entry 10. |
| Entries 1, 3, 4, 5 (2026-09-28) | Implicit: the packaging workflow's steps work as written. | Twice false in a row: the pytest gap (entry 6) and the hand-rolled `iscc` call (entry 7). Both pre-existing in `build-installer.yml`; neither had ever been executed on a runner. | Corrected by D18/D19. Treat "it works on my machine" as unproven for every step in this file. |
| Entries 1, 3, 4, 5 (2026-09-28) | Implicit: the packaging job installs what the build script needs. | `build-installer.yml` never installed pytest, so `build_release.py`'s pre-build gate could not run. Packaging has never completed on a clean runner. | Corrected by D18 and entry 6. |
| Entry 4 / D14 (2026-09-28) | "The caller-side `concurrency` on the `ci` gate job stops it cancelling itself." | Wrong. Run 36402772836 failed identically with D14 in place. The group that collides is inside the callee. | Superseded by D17 and entry 5. The failure it was written to fix was real; the fix was not. |
| Decision D6 (2026-09-28, entry 1) | "Publication trigger is a `v*` tag push only. No manual-dispatch release path." | The pipeline now runs on `push` to `main` and creates the tag itself. | Superseded by D9; kept in the table as history, do not act on it. |

---

### Environment traps (not repo claims, but they will waste an hour)

| Assumption | Reality | What to do |
| ---------- | ------- | ---------- |
| "the tests are red" after `python build_tools/run_tests.py` | No Python on this machine has `pytest` (3.14 default, 3.11, uv 3.12). It fails with `No module named pytest` before running anything. | Use the isolated venv in section 5. |
| CJK shown as mojibake in PowerShell means the file is corrupted | Console encoding only; file bytes verified through Python reads were correct. | Read files through Python, not `Get-Content`. |
| Every test file can be collected anywhere | The isolated venv has no `PIL` / `PyQt5`, so splash and brand test files fail at collection. | Expected; not a regression from any change here. |

## 5. Verification baseline

| Check | Command | Last result | Date |
| ----- | ------- | ----------- | ---- |
| Release wiring tests | `python -m pytest tests/test_release_wiring.py -q` | 11 passed (isolated venv); 10 mutations of release.yml each turn it red | 2026-09-28 |
| Workflow schema | `actionlint.exe .github/workflows/*.yml` (v1.7.12) | 0 problems, all three files | 2026-09-28 |
| Adjacent workflow/brand suites | `python -m pytest tests/test_version_consistency.py tests/test_no_legacy_brand.py tests/test_the_index_gate_is_wired_into_ci.py tests/test_audit_coverage_r11.py tests/test_ci_gates_read_the_verdict_line.py -q` (one file per process) | 37 passed, 1 skipped | 2026-09-28 |
| Lint (new file) | `python -m ruff check tests/test_release_wiring.py` | All checks passed | 2026-09-28 |
| Workflow YAML parses | PyYAML `safe_load` over `.github/workflows/*.yml` | 3/3 parsed, jobs as expected | 2026-09-28 |
| Changelog extraction | Local run of the embedded python for `2.3.1` and `9.9.9` | found / exit 1 | 2026-09-28 |
| Mutation checks on `release.yml` | drop `build`/`ci` `if:` · `--target` -> `main` · always-release · drop `gh release view` | each red; restore green | 2026-09-28 |
| Full test matrix | `python build_tools/run_tests.py` | **not run** — needs pytest on the project interpreter | — |
| **Published Release** | launch the v2.3.1 exe | **`No module named 'flask'` — the artifact did not run.** Release + tag deleted (owner-approved); fix D24/D25/D26 in, not yet re-run | 2026-09-28 |
| Real release run | run 36415053429 | **success** — Release v2.3.1 created with the installer attached | 2026-09-28 |
| Earlier release runs | `gh run view 36401751401`, `36402772836` | **failed twice**, identically: preflight ok, `ci` job never created, build/publish skipped, no Release. D14 did not fix it | 2026-09-28 |
| Real release run, after D17 | run 36403249454 (head 27b53ff) | gate **started** (`ci / test`, `ci / ui-audit`) with the standalone ci unaffected — D17 confirmed. Then packaging failed: `No module named pytest` | 2026-09-28 |
| Packaging job | run 36403249454 job 108870195018 | failed at step 6 `No module named pytest`; steps 7-10 skipped. D18 fixed | 2026-09-28 |
| Gate on a runner | run 36406788535 | `ci / test` and `ci / ui-audit` both success (16 min and 2.9 min) | 2026-09-28 |
| Packaging job | run 36406788535 job 108881363747 | PyInstaller succeeded; Inno preinstalled (6.7.1); step 8 failed: `You may not specify more than one script filename`. D19 fixed | 2026-09-28 |
| Packaging job | run 36411234329 job 108896844855 | PyInstaller succeeded; ISCC received correct args; **exit status 2, no compiler output at all** | 2026-09-28 |
| Compiler diagnostics | probe run 36414070599 (standalone `build-installer`, no gate) | `capture` switch worked; compiler said: `Couldn't open include file "...\Languages\ChineseSimplified.isl"`. D21/D22 not yet re-run | 2026-09-28 |

Isolated venv used for the runs above (created by the agent, outside the repo):
`C:\Users\YB\AppData\Local\Temp\opencode\cs2venv` (Python 3.11 + `pytest`, `PyYAML`, `ruff`).

---

## Appendix A — Lessons carried over from earlier projects

**Workflows / release**

- A pipeline that publishes must fail loudly on missing inputs. An empty artifact list produces a
  Release that *looks* published and 404s on download — strictly worse than a red run.
- Job graph changes fail silently. `needs:` removals leave a valid file that no longer enforces the
  gate. Assert the invariant you care about (`ci` is a transitive dependency of `publish`), not the
  line you happened to write.
- Give a job only the permission it uses. A build job that installs packages from the network should
  never hold a write token.
- Pin third-party actions to commit SHAs, and keep retrieval-side and upload-side actions on the same
  major — artifact formats are versioned together.
- On Windows runners, pin `PYTHONIOENCODING` for any step that writes non-ASCII to a file. The
  default console encoding is cp1252 and the failure is mojibake, not an error.

**Testing**

- A judge with an empty denominator is indistinguishable from a passing one. `must_scan` before
  every negative assertion, and re-run a mutated version of the input to prove the judge bites.
- Fix the parser, not the fixture: PyYAML follows YAML 1.1, so `on:` arrives as the boolean `True`.

**Process**

- "Feature-complete" is not "done": security, deployment, records and cutover belong in the definition
  of done, not at the tail.
- Record unverified inferences as inferences, and check them before building on them.
