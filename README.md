# PolyBedrock

The Windows substrate shared by the Forge applications — [PolyShield](https://github.com/xaerogonzo/Polyshield-Antivirus)
(security) and PolyScour (maintenance).

Two packages, one repository:

| Package | Import | Contains |
|---|---|---|
| `polybedrock-core` | `polybedrock.*` | Windows platform code. **No UI dependency.** |
| `polybedrock-ui` | `polybedrock.ui.*` | CustomTkinter theming and shared widget behaviour. |

`polybedrock` is a [PEP 420](https://peps.python.org/pep-0420/) namespace package,
so both distributions contribute to it. **Neither may ship `src/polybedrock/__init__.py`** —
adding one shadows the other package's contribution, and the breakage only
appears once both are installed. `core/tests/test_package_boundary.py` guards it.

The dependency is one-way: `polybedrock-ui` may import `polybedrock`, never the
reverse. That boundary is what keeps this from degrading into a mixture of
Win32, SQLite, PowerShell, colours and widgets — it is also enforced by test.

## Developer setup

```bash
pip install -e "D:/Random Projects/PolyBedrock/core" -e "D:/Random Projects/PolyBedrock/ui"
```

Both packages are versioned **independently**. A trivial `polybedrock-ui` change
must never force a new semantic release of the Windows substrate. Consumers
declare the versions they use.

## Running the tests

```bash
python -m pytest core/tests ui/tests
```

PolyBedrock is infrastructure, so its own suite passing is not sufficient. A change
here is not green until its **consumers** pass too — see
`.github/workflows/tests.yml` and `docs/adr/0001`.

Both consumers run in that workflow, each **pinned to a commit** rather than to
`master`. Two moving branches proving each other can go green for a pair of
mutually-dependent changes that would not work against any released version of
either — and a red run would not say whether the substrate broke the consumer or
the consumer was already broken. The pins are bumped deliberately, as the act of
declaring support for a newer consumer revision.

## What is here, and what deliberately is not

| Module | Consumers | Notes |
|---|---|---|
| `polybedrock.ps_run` | PolyShield, PolyScour | Safe PowerShell invocation |
| `polybedrock.win_security` | PolyShield, PolyScour | Security posture, device security, system health |
| `polybedrock.settings` | PolyShield, PolyScour | Atomic writes, cross-process file lock |
| `polybedrock.paths` | PolyScour | Generic half only — see `docs/adr/0002` |
| `polybedrock.proc_control` | PolyShield, PolyScour | Suspend / resume a process by PID |
| `polybedrock.startup` | PolyShield, PolyScour | What runs at boot. **Reads only** |
| `polybedrock.capabilities` | PolyScour | Observational probes |
| `polybedrock.ui.theme` | PolyShield, PolyScour | 5 palettes, live font propagation |
| `polybedrock.ui.uishot` | PolyShield, PolyScour | Headless GUI capture + golden-image diffing |

Modules that stayed in PolyShield, and why, are recorded in
`docs/adr/0003-extraction-records.md`. The short version: a module moves when a
**second consumer actually exists**, not when one is imagined. Extraction is
cheap now that the technique is proven; a speculative shared API is not.

## The extraction gate

Nothing enters `polybedrock-core` without clearing all five, and recording the
answers in `docs/adr/0003`:

1. Does the concept make sense with no PolyShield in the picture?
2. Would a third, unrelated Windows application plausibly consume it?
3. Does the API describe the *capability*, not one app's implementation of it?
4. Does extracting it actually reduce duplication?
5. Does extraction avoid coupling the two products?

## Licence

MIT, matching PolyShield.
