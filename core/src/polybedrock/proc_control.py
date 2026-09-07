r"""Suspend and resume a running process, and deliberately nothing else.

Windows can freeze a process without killing it — every thread stops, the
process keeps its memory, its handles and its place in the world, and it
continues exactly where it left off when resumed. `NtSuspendProcess` and
`NtResumeProcess` are the undocumented-but-stable ntdll pair that Process
Explorer's "Suspend" uses; there is no documented Win32 equivalent for a whole
process, which is why this reaches through ``ctypes`` rather than ``win32api``.

**The scope is the name.** This module suspends and resumes. It does not
enumerate, kill, reprioritise, or decide *which* processes are safe to touch —
and that last one is the important omission. Suspending
``csrss.exe`` or ``winlogon.exe`` wedges the session; suspending an antivirus
mid-write can leave a file locked for as long as the freeze lasts. Choosing a
target is a policy decision belonging to the application, where it can be
reviewed against that application's own safety rules. A substrate that both
froze processes *and* picked them would put that decision somewhere no product
owns it.

**Failure is a return value, never an exception.** Every failure mode here is
ordinary rather than exceptional: the process exited between enumerating it and
opening it, it is protected, or the caller lacks the right. A raising API would
make each of those a special case at every call site, so both functions answer
``False`` and let the caller carry on. That also makes them inert on
non-Windows, where ``ctypes.windll`` does not exist — the ``AttributeError`` is
caught with everything else and the answer is ``False``.

**A PID is not always the process doing the work.** Launchers, shims and
re-execing interpreters spawn a child and sit there; suspending the one you
started succeeds, reports success, and freezes something that was not doing
anything. This module's own tests hit it -- the venv interpreter they spawn
re-execs, so an obvious-looking test failed against working code -- and a
consumer aiming this at a program a user launched will hit it too. Resolving
a launcher to its worker is targeting, which is to say policy, which is to
say the application's job.

Consumers: PolyShield (its cross-engine scan pause, which layers a
``threading.Event`` watcher over these two), PolyScour (Game Mode).
"""
from __future__ import annotations

import ctypes

#: PROCESS_SUSPEND_RESUME. The narrowest right that does the job -- not
#: PROCESS_ALL_ACCESS, which would ask for far more than suspending needs and
#: fail against processes this can legitimately pause.
_PROCESS_SUSPEND_RESUME = 0x0800


def suspend_pid(pid: int) -> bool:
    """Suspend a process by PID via ``NtSuspendProcess``. True on success.

    Suspension nests: two calls need two resumes. A caller that suspends the
    same process twice and resumes it once leaves it frozen, which looks
    exactly like a hung application to the person using the machine.
    """
    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            _PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.ntdll.NtSuspendProcess(handle) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def resume_pid(pid: int) -> bool:
    """Resume a process by PID via ``NtResumeProcess``. True on success.

    Safe to call on a process that is not suspended -- it is a no-op that
    reports success, so a cleanup path can resume unconditionally rather than
    tracking whether it was the one that froze it.
    """
    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            _PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.ntdll.NtResumeProcess(handle) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False
