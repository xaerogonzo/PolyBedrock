r"""What runs when Windows starts, read without changing any of it.

Two audiences, one set of mechanisms. PolyShield asks "what starts up, so I can
scan those files"; PolyScour asks "what starts up, so a person can decide what
to turn off". They want different shapes of the same walk over the same
registry keys and folders, so both shapes live here rather than each product
learning the mechanisms separately.

**This module reads. It never writes.** Nothing here disables, enables, or
deletes a startup entry. Changing what runs on someone's machine is a decision
with an owner, and the owner is the application -- where it can be gated by
that application's policy, recorded in its ledger, and undone. A substrate that
could disable autoruns would put that power somewhere no product is accountable
for it.

Two views of the same data
--------------------------

``enumerate_startup_items()`` returns dicts with a human-readable ``source``
string. It is the older shape and PolyShield depends on it exactly as written.

``iter_run_entries()`` returns :class:`RunEntry`, which carries the **machine**
identity -- hive, key path, value name -- because a caller that intends to act
on an entry later needs to name it again reliably. A display string like
``"Registry: HKCU\...\Run"`` cannot be turned back into a key, and an index
into a list is not an identity at all: enumeration order is not guaranteed
stable, so "the third one" may be a different entry by the time anyone clicks.

``_extract_path`` is the hard-won part
--------------------------------------

Pulling a path out of a registry value looks trivial and is not; the docstring
below records three ways an earlier version got it wrong, each of which failed
silently. It is exported as ``extract_path`` for callers outside this module,
with the private name kept because existing tests reach for it.
"""
import os
import winreg
from dataclasses import dataclass
from pathlib import Path

_RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
     "HKCU"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
     "HKLM"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
     "HKLM (32-bit)"),
]

_STARTUP_FOLDERS = [
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"),
    os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Startup"),
]


def enumerate_startup_items() -> list[dict]:
    """
    Return all startup entries from registry run keys and startup folders.
    Each entry: {name, raw_value, resolved_path, source, exists}
    """
    items = []

    # Registry run keys
    for hive, key_path, hive_label in _RUN_KEYS:
        try:
            with winreg.OpenKey(hive, key_path,
                                access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        resolved = _extract_path(str(value))
                        items.append({
                            "name": name,
                            "raw_value": str(value),
                            "resolved_path": resolved,
                            "source": f"Registry: {hive_label}\\...\\Run",
                            "exists": Path(resolved).exists() if resolved else False,
                        })
                        i += 1
                    except OSError:
                        break
        except OSError:
            pass

    # Startup folders
    for folder in _STARTUP_FOLDERS:
        if not os.path.isdir(folder):
            continue
        short_folder = folder.split("\\Programs\\")[1] if "\\Programs\\" in folder else folder
        for fname in os.listdir(folder):
            full = os.path.join(folder, fname)
            items.append({
                "name": fname,
                "raw_value": full,
                "resolved_path": full,
                "source": f"Startup folder ({short_folder})",
                "exists": os.path.exists(full),
            })

    return items


def get_scannable_paths(items: list[dict]) -> list[str]:
    """Extract unique, existing file paths from startup items for scanning."""
    seen = set()
    paths = []
    for item in items:
        p = item.get("resolved_path", "")
        if p and p not in seen and Path(p).is_file():
            seen.add(p)
            paths.append(p)
    return paths


# Extensions a Run key can launch directly through ShellExecute.  Used only to
# find where the executable ends and its arguments begin.
_EXE_SUFFIXES = (".exe", ".com", ".bat", ".cmd", ".scr", ".pif")


def _extract_path(value: str) -> str:
    r"""
    Pull a file path out of a registry value string.
    Values can be bare paths, quoted paths, or paths with arguments.

    Every mistake here has the same consequence, and it is a quiet one: the
    resolved path fails Path.exists(), the entry is dropped by
    get_scannable_paths(), and a startup executable is simply never scanned.
    Autoruns are where persistence lives, so a miss is not cosmetic.

    Three ways the previous form produced a wrong path:

      * `v.split(".exe", 1)` was case-sensitive.  Registry values preserve the
        case the installer wrote, and `.EXE` is common, so
        `C:\Program Files\App\app.EXE --flag` fell through to the
        first-token fallback and resolved to `C:\Program`.
      * It split on the first *substring* match rather than at a token
        boundary, so `C:\my.exe.tools\app.exe` resolved to `C:\my.exe`.
      * Environment variables were never expanded, so a perfectly ordinary
        `%ProgramFiles%\App\app.exe` never resolved to anything at all.
    """
    # Expand first: a quoted value can contain variables too.  expandvars
    # leaves an unknown %VAR% untouched, which resolves to "does not exist" --
    # the same outcome as before, so nothing regresses on a name we cannot map.
    v = os.path.expandvars(value.strip())
    if not v:
        return ""

    if v.startswith('"'):
        end = v.find('"', 1)
        return v[1:end] if end > 1 else v[1:]

    # Find the earliest executable extension that actually ENDS a token, so a
    # directory named "my.exe.tools" cannot be mistaken for the target.
    low = v.lower()
    cut = -1
    for suffix in _EXE_SUFFIXES:
        start = 0
        while True:
            idx = low.find(suffix, start)
            if idx == -1:
                break
            end = idx + len(suffix)
            if end == len(v) or v[end].isspace():
                if cut == -1 or end < cut:
                    cut = end
                break
            start = idx + 1          # a substring match; keep looking
    if cut != -1:
        return v[:cut].strip()

    # No recognisable extension — first whitespace-delimited token, as before.
    parts = v.split()
    return parts[0] if parts else ""


# ── The identity-bearing view ────────────────────────────────────────────────

@dataclass(frozen=True)
class RunEntry:
    """One registry Run value, named the way it can be found again.

    ``hive_name``/``key_path``/``value_name`` together are the identity. They
    are what a caller writes down if it intends to act on this entry later,
    and they survive the list being re-enumerated in a different order --
    which it will be, because enumeration order is not guaranteed and entries
    appear and vanish between one look and the next.
    """
    hive_name: str          # "HKCU" | "HKLM" | "HKLM_WOW6432"
    key_path: str
    value_name: str
    raw_value: str
    target_path: str        # "" when no path could be extracted
    scope: str              # "user" | "machine"

    @property
    def identity(self) -> str:
        r"""A stable string key: ``HKCU\SOFTWARE\...\Run\ValueName``.

        Deliberately not a hash. A caller storing this in a ledger should be
        able to read the row a year later and know exactly which registry
        value it means.
        """
        return f"{self.hive_name}\\{self.key_path}\\{self.value_name}"

    @property
    def target_exists(self) -> bool:
        return bool(self.target_path) and Path(self.target_path).exists()


#: hive constant -> (label, scope). Built at call time rather than import time
#: so a test that swaps the ``winreg`` module still sees matching constants --
#: the same reason ``_RUN_KEYS`` is a module global rather than a frozen tuple.
def _hive_table():
    return {
        winreg.HKEY_CURRENT_USER: ("HKCU", "user"),
        winreg.HKEY_LOCAL_MACHINE: ("HKLM", "machine"),
    }


def iter_run_entries() -> list:
    """Every registry Run value, with the identity needed to act on it later.

    Startup **folders** are deliberately absent: a shortcut in a folder is a
    file, not a registry value, and folding both into one record type would
    produce a shape where half the fields are meaningless for half the rows.
    A caller that wants those has ``enumerate_startup_items()``.

    Never raises. A key that cannot be opened is skipped, because a machine
    missing the 32-bit view is normal rather than exceptional.
    """
    table = _hive_table()
    out = []
    for hive, key_path, hive_label in _RUN_KEYS:
        label, scope = table.get(hive, (hive_label, "machine"))
        if "WOW6432" in key_path:
            label = f"{label}_WOW6432"
        try:
            with winreg.OpenKey(hive, key_path,
                                access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out.append(RunEntry(
                        hive_name=label,
                        key_path=key_path,
                        value_name=name,
                        raw_value=str(value),
                        target_path=_extract_path(str(value)),
                        scope=scope,
                    ))
                    i += 1
        except OSError:
            continue
    return out


#: Public name for the path extractor. The private one stays because existing
#: tests reach for it, and renaming it would be a change to PolyShield's suite
#: rather than to its behaviour.
extract_path = _extract_path
