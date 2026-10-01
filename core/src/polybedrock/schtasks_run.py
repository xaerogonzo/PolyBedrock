"""Shared schtasks.exe runner.

PolyShield (``ui/core/scheduler.py``) and PolyScour (``scheduling/task.py``)
each carried a near-identical wrapper around invoking ``schtasks.exe``
without a console window: ``creationflags=CREATE_NO_WINDOW``, a bounded
timeout, and ``check=False`` so a non-zero exit code comes back as data
rather than an exception. That invocation is the part that was actually
identical between the two. Everything above it -- task naming, elevation,
ownership by path, how a failure is reported to the user -- differs between
the two products on purpose, and stays where it is; see PolyBedrock's
``docs/adr/0003-extraction-records.md`` for why only this much moved.

``exe``, ``text`` and ``stdin`` are left as plain parameters rather than
given one shared default, because the two existing callers already differ
there and neither is "more correct":

* PolyShield passes a bare ``"schtasks"`` (relies on PATH, and its test suite
  asserts the literal argv it hands to ``subprocess.run``), decodes with
  ``text=True``, and redirects ``stdin=DEVNULL`` -- schtasks can fail with
  WinError 6 when launched with no console and an inherited invalid stdin
  handle.
* PolyScour resolves the executable explicitly under ``%SystemRoot%``
  (measured corruption in piped ``schtasks /query /xml`` output made it
  cautious about relying on PATH for anything), reads raw bytes to decode
  with the OEM codepage itself, and lets stdin inherit.

This module exists to stop duplicating the mechanism underneath those two
policies, not to pick a winner between them.
"""
from __future__ import annotations

import subprocess


def run_schtasks(args: list[str], *, exe: str = "schtasks",
                  timeout: float = 30, text: bool = False,
                  stdin: int | None = None) -> subprocess.CompletedProcess:
    """Run ``[exe, *args]`` with no console window. Never raises itself --
    ``subprocess.TimeoutExpired`` and ``OSError`` propagate, because both
    existing callers already handle a timeout and a launch failure as
    distinct cases rather than folding them into one generic failure."""
    return subprocess.run(
        [exe, *args],
        capture_output=True, text=text, shell=False, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdin=stdin, check=False)
