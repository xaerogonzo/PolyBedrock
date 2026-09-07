r"""tests/test_startup.py — the identity, and the path extraction behind it.

PolyShield's own suite already covers ``enumerate_startup_items`` and
``_extract_path`` in depth and must keep passing unedited, so this file does
not duplicate it. What it covers is the part that is new here: the
identity-bearing view, and the property that makes it worth having.

**An index is not an identity.** Enumeration order is not guaranteed, entries
appear and vanish between one look and the next, and a caller that intends to
act on an entry later needs to name it again reliably. So the test that matters
is that the identity survives the list being re-enumerated differently.
"""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="winreg is Windows-only")

from polybedrock import startup      # noqa: E402


class _FakeKey:
    def __init__(self, values):
        self.values = list(values.items())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    """Just enough winreg to walk Run keys, with the tree under our control."""
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 1
    KEY_WOW64_64KEY = 2

    def __init__(self):
        self.tree: dict[tuple[str, str], dict] = {}

    def OpenKey(self, hive, path, access=0):
        try:
            return _FakeKey(self.tree[(hive, path)])
        except KeyError:
            raise OSError("no such key")

    def EnumValue(self, key, i):
        try:
            name, value = key.values[i]
        except IndexError:
            raise OSError("no more values")
        return name, value, 1


@pytest.fixture
def registry(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setattr(startup, "winreg", fake)
    monkeypatch.setattr(startup, "_RUN_KEYS", [
        (fake.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
        (fake.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
    ])
    monkeypatch.setattr(startup, "_STARTUP_FOLDERS", [])
    return fake


HKCU_RUN = ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")
HKLM_RUN = ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")


# ── identity ────────────────────────────────────────────────────────────────

def test_an_entry_names_the_registry_value_it_came_from(registry):
    registry.tree[HKCU_RUN] = {"Updater": r"C:\Vendor\updater.exe /background"}

    entry, = startup.iter_run_entries()

    assert entry.hive_name == "HKCU"
    assert entry.key_path == r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    assert entry.value_name == "Updater"
    assert entry.raw_value == r"C:\Vendor\updater.exe /background"
    assert entry.target_path == r"C:\Vendor\updater.exe"


def test_the_identity_survives_reordering(registry):
    """The property the whole record type exists for.

    A caller that stored "the second entry" would act on a different value
    after any change to the key. The identity must not depend on position.
    """
    registry.tree[HKCU_RUN] = {"A": r"C:\a.exe", "B": r"C:\b.exe"}
    first = {e.value_name: e.identity for e in startup.iter_run_entries()}

    registry.tree[HKCU_RUN] = {"B": r"C:\b.exe", "A": r"C:\a.exe", "C": r"C:\c.exe"}
    second = {e.value_name: e.identity for e in startup.iter_run_entries()}

    assert first["A"] == second["A"]
    assert first["B"] == second["B"]


def test_the_identity_reads_as_the_registry_path_it_means(registry):
    """Not a hash. Someone reading a ledger row a year later should be able to
    see which registry value it refers to."""
    registry.tree[HKCU_RUN] = {"Updater": r"C:\a.exe"}
    entry, = startup.iter_run_entries()
    assert entry.identity == (
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run\Updater")


def test_hive_and_scope_distinguish_per_user_from_machine_wide(registry):
    registry.tree[HKCU_RUN] = {"Mine": r"C:\mine.exe"}
    registry.tree[HKLM_RUN] = {"Everyones": r"C:\all.exe"}

    by_name = {e.value_name: e for e in startup.iter_run_entries()}

    assert by_name["Mine"].scope == "user"
    assert by_name["Everyones"].scope == "machine"
    assert by_name["Mine"].identity != by_name["Everyones"].identity


def test_two_values_of_the_same_name_in_different_hives_stay_distinct(registry):
    """HKCU and HKLM can both define "Updater", and they are different things.
    An identity that collided here would let a caller disable the wrong one."""
    registry.tree[HKCU_RUN] = {"Updater": r"C:\user.exe"}
    registry.tree[HKLM_RUN] = {"Updater": r"C:\machine.exe"}

    ids = {e.identity for e in startup.iter_run_entries()}
    assert len(ids) == 2


# ── failures are ordinary ───────────────────────────────────────────────────

def test_a_missing_run_key_is_skipped_not_raised(registry):
    """A machine with no 32-bit view is normal, not exceptional."""
    assert startup.iter_run_entries() == []


def test_a_value_with_no_extractable_path_still_appears(registry):
    """It is still a startup entry, and hiding it would make the list a
    misleading account of what runs at boot."""
    registry.tree[HKCU_RUN] = {"Odd": ""}
    entry, = startup.iter_run_entries()
    assert entry.target_path == ""
    assert entry.target_exists is False


def test_target_exists_reports_the_disk(registry, tmp_path):
    real = tmp_path / "present.exe"
    real.write_bytes(b"MZ")
    registry.tree[HKCU_RUN] = {"Real": str(real), "Ghost": r"C:\nowhere\absent.exe"}

    by_name = {e.value_name: e for e in startup.iter_run_entries()}
    assert by_name["Real"].target_exists is True
    assert by_name["Ghost"].target_exists is False


# ── the shared extractor ────────────────────────────────────────────────────

def test_extract_path_is_exported_under_a_public_name():
    """Consumers outside this module should not have to reach for a private."""
    assert startup.extract_path is startup._extract_path


@pytest.mark.parametrize("value, expected", [
    (r'"C:\Program Files\App\app.exe" --flag', r"C:\Program Files\App\app.exe"),
    (r"C:\Program Files\App\app.EXE --flag", r"C:\Program Files\App\app.EXE"),
    (r"C:\my.exe.tools\app.exe", r"C:\my.exe.tools\app.exe"),
])
def test_extract_path_still_handles_the_cases_it_was_fixed_for(value, expected):
    """Case-insensitivity, and splitting at a token boundary rather than at the
    first substring match. Both were real bugs; each failed silently by
    resolving to a path that simply did not exist."""
    assert startup.extract_path(value) == expected
