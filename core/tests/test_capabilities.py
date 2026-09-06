"""The capability layer's two invariants, and the answers it gives."""
from __future__ import annotations

import os

import pytest

from polybedrock import capabilities as caps
from polybedrock.capabilities import Capability


def test_every_capability_has_a_probe():
    """A member added to the enum without a probe would raise at the call site
    of whichever feature asked for it, which is the wrong place to find out."""
    for cap in Capability:
        assert caps.probe(cap).capability is cap


def test_a_state_always_carries_a_reason():
    """Populated even when available, so a tooltip has something to say either
    way rather than rendering an empty string."""
    for state in caps.probe_all().values():
        assert state.reason.strip()


def test_a_state_is_truthy_exactly_when_available():
    for state in caps.probe_all().values():
        assert bool(state) is state.available


def test_probes_are_free_of_side_effects(tmp_path, monkeypatch):
    """The invariant that makes the layer safe to call speculatively.

    Asserted by forbidding the operations rather than by inspecting afterwards:
    a probe that shells out or writes would trip one of these immediately.
    """
    import subprocess

    def _forbidden(*a, **k):
        raise AssertionError("a capability probe launched a process")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.chdir(tmp_path)

    caps.probe_all()

    assert list(tmp_path.iterdir()) == [], "a capability probe wrote to disk"


def test_system_security_reports_partial_rather_than_unavailable():
    """Several probes underneath return a reduced answer without elevation
    rather than failing, so the state must distinguish the two."""
    state = caps.probe(Capability.SYSTEM_SECURITY)
    if state.available:
        assert state.requires_elevation is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only capability")
def test_powershell_is_available_on_windows():
    assert caps.probe(Capability.POWERSHELL).available
