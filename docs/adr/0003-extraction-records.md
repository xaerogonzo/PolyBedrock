# 0003 — Extraction records

**Status:** Living document

Every module admitted to PolyBedrock records its answers to the five-question
extraction gate here. Without this the gate quietly becomes "it seemed useful."

A module moves when a **second consumer actually exists**. Extraction is cheap
now that the alias technique is proven; a speculative shared API is not.

---

## Moved in Stage 1

### `polybedrock.ps_run`

- **Why generic:** running a PowerShell command and capturing its output is not
  a security-product concern.
- **Current consumers:** PolyShield (11 call sites via `win_security._run_ps`),
  PolyScour (`win_security`, and later condition checks).
- **Duplication reduced:** yes — PolyScour would otherwise reimplement the
  no-window / timeout / encoding handling.
- **API is capability-oriented:** `run_ps(command, timeout)`.
- **Keeping it in the app would be worse:** PolyScour cannot import PolyShield.

### `polybedrock.win_security` (922 LOC — the largest single win)

- **Why generic:** Windows security posture, device security, firewall, ASR,
  accounts and system health are properties of the machine, not of an AV product.
- **Current consumers:** PolyShield (Windows Security view), PolyScour
  (`get_system_health()` for pending-reboot, driver-error and uptime findings).
- **Duplication reduced:** substantially — this is the module PolyScour would
  have spent the most effort recreating badly.
- **API is capability-oriented:** `get_system_health()`, `get_device_security()`,
  `get_security_score()` return plain dicts.
- **Keeping it in the app would be worse:** PolyScour's dashboard would either
  shell out to PowerShell itself or require PolyShield to be installed.

### `polybedrock.settings`

- **Why generic:** atomic write, cross-process file lock, corrupt-file
  preservation. A design that took a real corrupted-settings incident to get right.
- **Current consumers:** PolyShield, PolyScour.
- **Duplication reduced:** yes.
- **API is capability-oriented:** `configure(config_path, defaults)` takes the
  path and the defaults rather than a `paths` module — PolyShield's defaults name
  VirusTotal keys and Guardian AI profiles, which mean nothing to any other
  consumer, so the application owns them.
- **Keeping it in the app would be worse:** PolyScour would reimplement the
  locking, and would get it wrong in the ways this one already learned.

### `polybedrock.ui.theme`

- **Why generic:** five palettes and live font propagation; nothing in it is
  security-specific.
- **Current consumers:** PolyShield (a dozen views), PolyScour.
- **Duplication reduced:** yes, and it makes the suite *look* like a suite.
- **API is capability-oriented:** `configure(app_name)` supplies the one
  product-specific string (the `classic` preset label).
- **Keeping it in the app would be worse:** the two products would diverge
  palette by palette.

### `polybedrock.paths` (generic half only)

See `0002-polyshield-keeps-its-paths-module.md`. Consumer: PolyScour only.

### `polybedrock.ui.uishot`

- **Why generic:** photographing a GUI without putting it on screen. Nothing in
  the hidden-desktop binding, the `PrintWindow` capture, the scene registry or
  the golden-diff CLI is specific to a security product.
- **Current consumers:** PolyShield (6 scenes, 10 golden images), PolyScour
  (6 scenes, 8 golden images).
- **Duplication reduced:** substantially. The alternative was a second copy of
  the `CreateDesktop` binding, the DIB capture, and ~130 lines of golden-diff
  CLI -- along with a second chance to rediscover why off-screen coordinates
  produce confidently wrong screenshots.
- **API is capability-oriented:** `desktop` and `capture` take an `hwnd` and know
  no toolkit. `TkSession` takes `entry_module` and `on_root`, so the application
  says what its startup does instead of the harness hard-coding it. `cli.run()`
  takes a registry and a session factory.
- **Keeping it in the app would be worse:** PolyScour cannot import PolyShield,
  and the measurements behind the design are not the kind of thing anyone would
  redo -- they would just ship the off-screen version and get bad shots.

**Verified pixel-exact.** After the extraction, PolyShield's `--check` reported
*all 10 comparable shot(s) match golden*. A capture harness is one of the few
things that can prove its own refactor was behaviour-preserving by photograph.

Placed in `polybedrock-ui` rather than `-core` even though `desktop` and
`capture` import no toolkit: every consumer today is a Tk GUI application, and
splitting a six-module package across two distributions to serve a hypothetical
Qt caller would be exactly the speculative API this gate exists to prevent. If
OpenChem Studio ever wants `compare`/`write_diff`, split then -- `capture.py`
has no UI imports, so the move is mechanical.

### `polybedrock.capabilities` (new)

- **Why generic:** the mechanism that stops `if is_admin:` / `if is_frozen:` /
  `if windows_build >= N:` breeding across two codebases.
- **Current consumers:** PolyScour.
- **Note:** populated with only the capabilities something consumes today
  (`POWERSHELL`, `SYSTEM_SECURITY`). The enum grows when a feature arrives, not
  in anticipation of one.

---

## Moved in Stage 2

### `polybedrock.proc_control` (2026-09-07)

The row below said this moves "when PolyScour 0.2 needs `suspend_pid`/`resume_pid`".
Game Mode is that consumer, so it moved — and **only the two functions named
there did.**

- **Why generic:** freezing a process without killing it is a property of
  Windows, not of a security product. `NtSuspendProcess`/`NtResumeProcess` are
  the same pair Process Explorer's "Suspend" uses.
- **Current consumers:** PolyShield (its cross-engine scan pause) today;
  PolyScour's Game Mode is the second, landing immediately after this and
  before the pin that gates PolyScour is bumped to a revision using it. Stated
  that way rather than as a fait accompli: gate #4 asks whether a second
  consumer *actually exists*, and until that PR merges the honest answer is
  "it is being written", not "yes".
- **Duplication reduced:** yes — PolyScour would otherwise carry a second copy
  of the same ctypes handle dance, including the `finally: CloseHandle` that is
  easy to omit and impossible to notice omitting.
- **API is capability-oriented:** `suspend_pid(pid)` / `resume_pid(pid)`,
  answering `bool`. Failure is a return value rather than an exception, because
  every failure mode is ordinary: the process exited, it is protected, or the
  caller lacks the right.
- **Keeping it in the app would be worse:** PolyScour cannot import PolyShield.

**`watch_pause_event` deliberately stayed behind.** It is generic in *shape* —
it takes a `subprocess.Popen` and a `threading.Event` — but it encodes
PolyShield's scan-pause convention, its only caller is `clamav_engine`, and
PolyScour's Game Mode does not want it: Game Mode suspends *other people's*
processes, it does not sync its own subprocess to an event. Moving it would
have failed gate #4 (extracting it reduces no duplication) while looking like
progress. The gate exists to refuse exactly that.

So PolyShield's `ui.core.proc_pause` is **not** an aliased module like
`ps_run`; it re-exports the two names and keeps its own function. That
distinction is load-bearing rather than stylistic: `test_scan_control.py` does
`monkeypatch.setattr(proc_pause, "suspend_pid", fake)` and expects
`watch_pause_event`'s inner loop to call the fake. A `from ... import` binding
puts the name in that module's globals, which is what the loop resolves at call
time, so the patch lands. Aliasing would also have worked — but only by taking
`watch_pause_event` along with it.

**Verified behaviour-preserving.** PolyShield's suite passes **887, unedited**.

**What the extraction's own tests found.** PolyBedrock's tests for this spawn a
real child, freeze it, and assert the counter *stops* — a bogus-PID test would
pass against functions that do nothing. Written the obvious way that test failed
against working code: the interpreter it spawns re-execs, so `Popen.pid` was a
launcher and the counter kept climbing while the launcher sat frozen. The
functions were right; the aim was wrong. It is recorded in the module docstring
because a consumer pointing this at a program a user launched hits the same
thing, and resolving a launcher to its worker is targeting — which is policy,
which belongs to the application.

**Nuitka.** `polybedrock.proc_control` is named in both PolyShield build targets.
The editable finder resolves at import time, so a module Nuitka cannot see
statically compiles fine and then fails to start — the failure class
`--include-package=ui.core` already exists to prevent.

---

## Deliberately **not** moved

| Module | Gate failure | Moves when |
|---|---|---|
| `paths` (PolyShield's full module) | Not behaviour-preserving; also encodes PolyShield's staged-runtime layout | Stage 2 — see ADR 0002 |
| `proc_pause.watch_pause_event` | Generic in shape, but encodes PolyShield's scan-pause convention and has **one caller** (gate #4) | If a second consumer wants a Popen synced to an Event — Game Mode does not |
| `startup_scanner` | Same — zero second consumers today | PolyScour 0.2 — Startup Manager |
| `scheduler` | Depends on `paths.script_launch_argv`; encodes PolyShield's staged-runtime packaging (gate #3) | If PolyScour ever schedules, and only with argv passed in rather than imported |
| `shell_ext` | Depends on `paths.app_launch_argv`; same problem | Same |
| `quarantine` | AV-specific semantics (threat name, restore-to-original). PolyScour's staged-deletion vault is a different concept wearing similar clothes | Possibly never; PolyScour's `vault` lives in PolyScour until a second consumer appears |
| `ignore_list` | Pulls `service_client` and `pattern_stats` — PolyShield's service and false-positive tracking (gate #1, #5) | Not foreseen |
| `intel_updater` | Pulls `yara_engine` and `tools.update_intelligence` (gate #1, #5) | Not foreseen; PolyScour copies the *pattern* for rule updates, not the code |

---

## Packaging verification (2026-09-05)

The one real risk in this extraction: `polybedrock-core` and `polybedrock-ui` are
installed with `pip install -e`, which resolves through an `__editable__` finder
at **import** time. Nuitka has to see through that at **compile** time, or
PolyShield compiles cleanly and then cannot start — the exact failure class
`--include-package=ui.core` already exists to prevent.

**Verified.** A standalone Nuitka build of a probe importing
`polybedrock.{ps_run, settings, win_security}` and `polybedrock.ui.theme`, using the
same `--include-module=` flags now in `build.ps1`, resolved all of them: the
compiled binary executed the core import successfully and reached
`probe.dist\polybedrock\ui\theme.py:28` inside the bundled tree.

It stopped there on `customtkinter`, which had been deliberately excluded via
`--nofollow-import-to` — confirming the note in `build.ps1`'s **service** target
that `polybedrock.ui.theme` must *not* be listed there, or it drags the UI toolkit
back past the nofollow.

**Not verified:** a full `build.bat` run. `dist\` was held open by a Windows
Sandbox (the build script detects this and refuses rather than building over it,
which is correct). The end-to-end shipped GUI therefore remains unbuilt since
the extraction.

**Trap for whoever tries next:** Nuitka standalone binaries do not run from a
deeply nested temp path that Windows 8.3-shortens — a trivial `print()` build
fails with *"Failed to import encodings module"* from
`...\D-1BAD~1\AFE928~1\SCRATC~1\`. Build probes somewhere with a short path.
