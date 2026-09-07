r"""tests/test_proc_control.py — the freeze actually freezes.

The easy tests here are the worthless ones. Asserting that a bogus PID returns
``False`` passes just as happily against a pair of functions that do nothing at
all, and "returns False on failure" is not the capability anyone wants. So the
load-bearing test spawns a real child that counts, freezes it, and checks the
counter **stops** — then resumes and checks it moves again.

That shape gives the negative control for free: a ``suspend_pid`` that silently
did nothing would leave the counter climbing and fail, rather than reporting
success over a process that never paused.

**The child reports its own PID and the test suspends that**, rather than
trusting ``Popen.pid``. Writing it the obvious way produced a test that failed
against working code: the interpreter used here re-execs, so ``Popen.pid`` was
a launcher whose child did the counting. Suspending the launcher genuinely
suspended it — and the counter kept climbing. That is not a quirk of the test
harness, it is the hazard consumers face when they aim this at a program the
user launched, and it is why targeting is the caller's decision.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time

import pytest

from polybedrock.proc_control import resume_pid, suspend_pid


pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="NtSuspendProcess is Windows-only")

# Writes "<own pid> <n>" to argv[1], incrementing as fast as it can be sampled.
_COUNTER = textwrap.dedent("""
    import os, sys, time
    path, n = sys.argv[1], 0
    while True:
        n += 1
        with open(path, "w") as fh:
            fh.write(f"{os.getpid()} {n}")
        time.sleep(0.005)
""")


def _read(path) -> tuple[int, int]:
    """(pid, count), tolerating the torn read of a file rewritten under us."""
    for _ in range(200):
        try:
            parts = path.read_text().split()
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        except (OSError, ValueError):
            pass
        time.sleep(0.01)
    raise AssertionError(f"never read a value from {path}")


def _count(path) -> int:
    return _read(path)[1]


def _stays_put(path, target: int, seconds: float = 0.4) -> bool:
    time.sleep(seconds)
    return _count(path) == target


def _moves(path, from_: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _count(path) > from_:
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def counter(tmp_path):
    """A live child incrementing a file, yielded as (worker_pid, path).

    The PID is the one the child reports, not ``Popen.pid`` — see the module
    docstring for why that distinction is the whole point of this fixture.
    """
    out = tmp_path / "n.txt"
    proc = subprocess.Popen([sys.executable, "-c", _COUNTER, str(out)])
    try:
        worker_pid, _ = _read(out)
        yield worker_pid, out
    finally:
        # Resume before killing: a suspended process cannot act on its own
        # termination, and leaving one frozen would outlive the test run.
        resume_pid(worker_pid)
        proc.kill()
        proc.wait(timeout=10)


def test_a_suspended_process_stops_making_progress(counter):
    """The capability itself. Everything else here guards this."""
    pid, out = counter

    assert suspend_pid(pid) is True
    time.sleep(0.2)                     # let any in-flight write land
    frozen = _count(out)
    assert _stays_put(out, frozen), "the process kept running while suspended"


def test_a_resumed_process_carries_on(counter):
    pid, out = counter

    assert suspend_pid(pid) is True
    time.sleep(0.2)
    frozen = _count(out)

    assert resume_pid(pid) is True
    assert _moves(out, frozen), "the process did not resume"


def test_resume_is_safe_on_a_process_that_was_never_suspended(counter):
    """Cleanup paths resume unconditionally rather than tracking who froze it,
    so this has to be a no-op that reports success."""
    pid, out = counter
    assert resume_pid(pid) is True
    assert _moves(out, 0), "resuming a running process disturbed it"


def test_suspension_nests_and_one_resume_is_not_enough(counter):
    """Two suspends need two resumes. A caller that gets this wrong leaves a
    frozen process behind, which presents to the user as a hung application —
    worth pinning as documented behaviour rather than discovered behaviour."""
    pid, out = counter

    assert suspend_pid(pid) is True
    assert suspend_pid(pid) is True
    time.sleep(0.2)
    frozen = _count(out)

    assert resume_pid(pid) is True          # one of two
    assert _stays_put(out, frozen), "one resume undid two suspends"

    assert resume_pid(pid) is True          # the second releases it
    assert _moves(out, frozen), "the second resume did not release the process"


# ── failure is a return value, never an exception ──────────────────────────

def test_a_pid_that_cannot_be_opened_is_false_not_an_exception():
    # PID 0 is the System Idle Process: it cannot be opened for suspend/resume,
    # and unlike a made-up number it can never be recycled onto something real
    # while the test runs.
    assert suspend_pid(0) is False
    assert resume_pid(0) is False


def test_a_protected_process_is_false_rather_than_a_crash():
    """PID 4 is the System process. Refusing it is the correct outcome; doing
    so by raising would make every caller wrap this in a try."""
    assert suspend_pid(4) is False
