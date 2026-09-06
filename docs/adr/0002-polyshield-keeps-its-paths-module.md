# 0002 — PolyShield keeps its own `paths.py`; PolyBedrock ships the generic half

**Status:** Accepted · **Date:** 2026-09-05

## Context

`ui/core/paths.py` is the most valuable module in PolyShield. It encodes the
RESOURCE-vs-DATA lifetime split and the `%LOCALAPPDATA%` → `%ProgramData%`
correction, which fixed a real production fault: the GUI and the
`LocalService`-hosted Windows service resolved *different* data directories, so
two cross-process lock files were handed to both processes at once while they
wrote the same SQLite.

The Phase 0a plan called for splitting it into a generic `polybedrock.paths` plus
PolyShield-specific accessors, with PolyShield's test suite passing **unedited**
as proof the extraction was behaviour-preserving.

## What we found

It cannot be split behaviour-preservingly.

1. **Cross-function patching.** `test_paths.py` (lines 469, 519) does
   `monkeypatch.setattr(paths, "resource_root", …)` and then asserts that
   `install_root()` and `script_launch_argv()` observe the patch. If the generic
   functions move to `polybedrock`, the patch lands on the shim while the code
   continues to read `polybedrock.paths`' own globals. Silently.

2. **The alias technique does not rescue it.** Replacing the module object in
   `sys.modules` works for `ps_run` and `win_security` because those are *pure*
   moves. `paths.py` must keep PolyShield-specific accessors (`k2_exe`,
   `venv_python`, `script_launch_argv`, `service_registration`,
   `intelligence_dir`, …) in the **same namespace** as the generic ones —
   `test_paths.py:311` resolves `app_root()` and `intelligence_dir()` through one
   module object in a subprocess.

3. **Much of it is not generic anyway.** `runtime_python`, `venv_python`,
   `venv_pip`, `script_launch_argv` and `install_root` encode PolyShield's
   staged-runtime distribution layout (`runtime\`, `service\`) and its `kicomav_env`
   virtualenv. PolyScour has none of that and may never.

The "no test edits permitted" rule did exactly its job: it detected that this
particular extraction is not behaviour-preserving. Forcing it and editing the
tests would have meant trusting review instead of the suite.

## Decision

- `polybedrock.paths` ships **only the generic core** — `configure`, `is_frozen`,
  `app_root`, `config_dir`, `logs_dir`, `state_dir` — consumed by PolyScour.
- **PolyShield's `paths.py` is not touched.** No shim, no alias.
- The overlap is deliberate duplication, recorded here.
- `data_scope` (`"user"` | `"machine"`) has **no default**, so the choice that
  caused PolyShield's fault must be made explicitly by every consumer. The
  reasoning travels with the module as documentation even where the code does not.

## Stage 2

PolyShield migrates onto `polybedrock.paths` when the shared module has a second
real consumer and its API has been validated against one — at which point
renegotiating the monkeypatch contract with deliberate test edits is legitimate,
because the tests will be changing to describe a new design rather than to
accommodate a regression.
