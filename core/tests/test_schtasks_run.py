r"""tests/test_schtasks_run.py — the shared schtasks.exe invocation.

Mechanism only: this module does not name a task, does not choose elevation,
and does not decide what a non-zero exit code means. Those are PolyShield's
and PolyScour's to keep. What is tested here is the contract both of them
rely on: no console window, a bounded timeout that surfaces as
``TimeoutExpired`` rather than a hang, ``[exe, *args]`` in that order, and
every parameter (``exe``, ``text``, ``stdin``) actually reaching
``subprocess.run`` -- because the two consumers pass different values for
every one of them.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from polybedrock.schtasks_run import run_schtasks

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                 reason="schtasks.exe is Windows-only")


def test_defaults_build_a_bare_schtasks_invocation(monkeypatch):
    """PolyShield relies on PATH and asserts the literal argv it hands to
    subprocess.run -- so the default ``exe`` must stay the bare name."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_schtasks(["/query", "/tn", "Whatever"])

    assert seen["args"] == ["schtasks", "/query", "/tn", "Whatever"]
    assert seen["kwargs"]["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["check"] is False
    assert seen["kwargs"]["stdin"] is None
    assert seen["kwargs"]["text"] is False


def test_exe_text_and_stdin_are_forwarded_verbatim(monkeypatch):
    """PolyScour resolves a full path and reads bytes; PolyShield decodes
    with text=True and redirects stdin. Neither default may leak into the
    other's call."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_schtasks(["/run", "/tn", "X"],
                 exe=r"C:\Windows\System32\schtasks.exe",
                 timeout=5, text=True, stdin=subprocess.DEVNULL)

    assert seen["args"][0] == r"C:\Windows\System32\schtasks.exe"
    assert seen["kwargs"]["timeout"] == 5
    assert seen["kwargs"]["text"] is True
    assert seen["kwargs"]["stdin"] is subprocess.DEVNULL


def test_a_timeout_propagates_rather_than_being_swallowed(monkeypatch):
    """Both consumers decide for themselves what a timeout means to their
    caller -- this module must not turn it into a (False, message) tuple
    itself, or PolyScour's bare ``try/except (OSError, SubprocessError)``
    around it would stop catching anything."""
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        run_schtasks(["/query"], timeout=1)


def test_a_real_invocation_runs_with_no_window(tmp_path):
    """One real call, against a query that is harmless either way. Confirms
    the whole wrapper -- not just the stubbed kwargs -- actually launches
    schtasks.exe and returns a real CompletedProcess."""
    result = run_schtasks(["/query", "/tn", r"\PolyBedrockTestsNonexistentTask"],
                           timeout=15)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode != 0   # the task does not exist
