"""The generic half of the path contract.

PolyShield keeps its own paths.py for now (see docs/adr/0002); these tests cover
what polybedrock.paths itself promises, and in particular the decision it refuses
to make for you.
"""
from __future__ import annotations

import sys

import pytest

from polybedrock import paths


@pytest.fixture(autouse=True)
def _reset():
    """configure() is process-global; leaving it set would leak between tests."""
    paths._app_name = paths._data_dir_env = paths._data_scope = ""
    paths._FROZEN_OVERRIDE = None
    yield
    paths._app_name = paths._data_dir_env = paths._data_scope = ""
    paths._FROZEN_OVERRIDE = None


def test_an_unconfigured_module_says_so_rather_than_guessing():
    with pytest.raises(RuntimeError, match="unconfigured"):
        paths.app_root()


def test_the_scope_must_be_chosen_explicitly():
    """There is no default, because guessing it wrong is silent -- the GUI and a
    service resolve different directories and the lock files stop protecting."""
    with pytest.raises(ValueError, match="user.*machine"):
        paths.configure("Demo", "DEMO_DATA_DIR", "whatever")


def test_user_scope_resolves_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DEMO_DATA_DIR", raising=False)
    paths.configure("Demo", "DEMO_DATA_DIR", "user")
    assert paths.app_root() == tmp_path / "Demo"


def test_machine_scope_resolves_under_programdata(monkeypatch, tmp_path):
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.delenv("DEMO_DATA_DIR", raising=False)
    paths.configure("Demo", "DEMO_DATA_DIR", "machine")
    assert paths.app_root() == tmp_path / "Demo"


def test_the_two_scopes_do_not_resolve_to_the_same_place(monkeypatch, tmp_path):
    """The whole reason the parameter exists."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "machine"))
    monkeypatch.delenv("DEMO_DATA_DIR", raising=False)

    paths.configure("Demo", "DEMO_DATA_DIR", "user")
    user = paths.app_root()
    paths.configure("Demo", "DEMO_DATA_DIR", "machine")
    assert paths.app_root() != user


@pytest.mark.parametrize("scope", ["user", "machine"])
def test_the_environment_override_outranks_the_scope(monkeypatch, tmp_path, scope):
    """The seam an installer or a portable launcher uses."""
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path / "elsewhere"))
    paths.configure("Demo", "DEMO_DATA_DIR", scope)
    assert paths.app_root() == tmp_path / "elsewhere"


def test_a_blank_override_is_ignored(monkeypatch, tmp_path):
    """An empty or whitespace variable is an unset one, not a request to write
    to the current directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("DEMO_DATA_DIR", "   ")
    paths.configure("Demo", "DEMO_DATA_DIR", "user")
    assert paths.app_root() == tmp_path / "Demo"


def test_named_directories_all_sit_under_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path))
    paths.configure("Demo", "DEMO_DATA_DIR", "user")
    root = paths.app_root()
    for d in (paths.config_dir(), paths.logs_dir(), paths.state_dir()):
        assert d.parent == root


def test_a_source_checkout_is_not_frozen():
    assert paths.is_frozen() is False


def test_sys_frozen_is_honoured(monkeypatch):
    """PyInstaller and py2exe set this; the predicate should not need revisiting
    if the packager ever changes."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.is_frozen() is True
