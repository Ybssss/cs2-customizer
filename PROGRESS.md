# PROGRESS — CS2 Customizer

> ## ⚠️ READ THIS FILE FIRST — BEFORE TOUCHING THE SYSTEM
>
> **Owner instruction.** This file is the accumulated state of the project: what is built, what is only
> planned, what was tried and rejected, and which claims in the code and in older documents are already
> known to be wrong. Read it, then verify the specific claim you are about to rely on, in source.
>
> **Latest state (2026-09-28, fourth pass):** The concurrency fix (D17) is **confirmed on a runner** —
> run 36403249454 got past the gate and reached packaging. It then failed one step later, on a
> **pre-existing** defect in `build-installer.yml`: `build_release.py` runs
> `tests/test_no_bundled_assets.py` as a pre-build gate (line 951) but the packaging workflow never
> installed pytest, so it died on `No module named pytest` (entry 6). Fixed by installing pytest in
> that job and guarded by a test. **Still no Release exists.** The first two failures were self-inflicted
> and are recorded as superseded; this third one was already broken in the upstream workflow, so it would
> have hit any release attempt. Earlier in this pass:
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
| Real release run | `gh run view 36401751401`, `36402772836` | **failed twice**, identically: preflight ok, `ci` job never created, build/publish skipped, no Release. D14 did not fix it | 2026-09-28 |
| Real release run, after D17 | run 36403249454 (head 27b53ff) | gate **started** (`ci / test`, `ci / ui-audit`) with the standalone ci unaffected — D17 confirmed. Then packaging failed: `No module named pytest` | 2026-09-28 |
| Packaging job | same run, job 108870195018 | failed at step 6 `No module named pytest`; steps 7-10 skipped. D18 not yet re-run | 2026-09-28 |

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
