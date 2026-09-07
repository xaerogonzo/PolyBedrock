@D:\Claude Co worker\Token Save Manager Source\templates\project-baseline.md

# PolyBedrock — Claude Project Instructions

## What this is

The Windows substrate **PolyShield** and **PolyScour** both consume and neither
owns. It is infrastructure: its own tests passing is *not* sufficient evidence
that a change is safe.

```
                    PolyBedrock
              ┌─────────────────┐
       polybedrock-core    polybedrock-ui
       Windows platform    CustomTkinter
              └────────┬────────┘
              ┌────────┴────────┐
         PolyShield         PolyScour
         security           maintenance
```

**Stack:** Python 3.11+, Windows-only. **No entry point** — this is a library.

## The rules that make it a substrate rather than a junk drawer

> **`polybedrock-core` has no UI dependency.** Not customtkinter, not tkinter,
> not `polybedrock.ui`. Enforced by `core/tests/test_package_boundary.py`.

> **Neither distribution may ship `src/polybedrock/__init__.py`.** `polybedrock`
> is a PEP 420 namespace package that both contribute to; an `__init__.py`
> shadows the other's contribution, and the breakage only appears once both are
> installed. Also guarded by test.

> **A module moves here when a *second consumer actually exists*,** not when one
> is imagined. Extraction is cheap now that the technique is proven; a
> speculative shared API is not.

> **Packages version independently.** A trivial `polybedrock-ui` change must
> never force a new semantic release of the Windows substrate.

## The extraction gate

Nothing enters without clearing all five, and recording the answers in
`docs/adr/0003-extraction-records.md`:

1. Does the concept make sense with no PolyShield in the picture?
2. Would a third, unrelated Windows application plausibly consume it?
3. Does the API describe the *capability*, not one app's implementation of it?
4. Does extracting it actually reduce duplication?
5. Does extraction avoid coupling the two products?

## Structure

```
core/src/polybedrock/
├── paths.py         RESOURCE vs DATA lifetimes; data_scope has NO default
├── settings.py      Atomic write + cross-process lock; takes path AND defaults
├── ps_run.py        Safe PowerShell invocation
├── win_security.py  Security posture, device security, system health (922 ln)
├── proc_control.py  Suspend/resume by PID. Targeting is NOT its job
├── startup.py       Registry Run keys + Startup folders. READS ONLY —
│                    disabling an entry belongs to the application
└── capabilities.py  Observational probes — no side effects, ever
ui/src/polybedrock/ui/
├── theme.py         5 palettes, live font propagation
└── uishot/          Headless GUI capture + golden diffing
    ├── desktop.py   Hidden Win32 desktop (toolkit-agnostic, takes an hwnd)
    ├── capture.py   PrintWindow -> PIL, compare, write_diff (toolkit-agnostic)
    ├── registry.py  SceneRegistry — a class, so two apps cannot collide
    ├── session.py   TkSession; entry_module + on_root are the app's hooks
    └── cli.py       Argument parsing, capture loop, golden comparison
```

## Testing a change here

```powershell
python -m pytest core/tests ui/tests
```

**That is not enough.** Because this is infrastructure, a change is not green
until its consumers are:

```powershell
cd "..\KicomAI_Project"; .\kicomav_env\Scripts\python.exe -m pytest        # 887, unedited
cd "..\KicomAI_Project"; .\kicomav_env\Scripts\python.exe tools\uishot\__main__.py --check
cd "..\PolyScour";       .\venv\Scripts\python.exe -m pytest               # 126
```

PolyShield's suite must pass **with no test edits**. A test that needs changing
means the change was not behaviour-preserving — that rule is what caught the
`paths.py` extraction as unsafe (see `docs/adr/0002`), and it should catch the
next one too.

The uishot `--check` is the strongest signal available: it proves a refactor was
behaviour-preserving *by photograph*.

## Documentation discipline

| What changed | Update |
|---|---|
| A module admitted or refused | **docs/adr/0003-extraction-records.md** |
| The package split, versioning, or CI contract | **docs/adr/0001** |
| A decision with a real alternative | a new **docs/adr/** entry |
| Anything a consumer calls | **README.md** module table |
| What to check at a phase boundary, or a consumer pin moving | **docs/ECOSYSTEM_HEALTH.md** |

## Project-specific notes

- **`paths.configure(data_scope=...)` has no default on purpose.** PolyShield's
  GUI and its `LocalService` service once resolved *different* `%LOCALAPPDATA%`
  directories, so two cross-process lock files were handed to both processes at
  once, silently, over a SQLite write. Guessing this wrong is invisible; making
  it a required argument is not.
- **Capability probes must be side-effect free and cheap.** No file creation, no
  registry writes, no process launches, no elevation. `POWERSHELL` is answered
  by looking for the executable, never by running it.
- **`win_security.get_system_health()` returns facts, not verdicts.** Its
  `driver_errors` count comes from `Get-PnpDevice | Where Status -ne 'OK'`,
  which counts every device not currently present — dozens on a normal machine.
  Consumers must not headline it. PolyScour learned this one live.
