r"""What this machine can actually do, asked once and answered descriptively.

The mechanism exists to stop ``if is_admin:`` / ``if is_frozen:`` /
``if windows_build >= N:`` from breeding across every feature in two
applications. A caller asks whether a capability is available and gets a reason
it can show the user, rather than discovering the answer through an exception.

Two invariants, both enforced by test:

**Probes are strictly observational.** A probe must never create a file, change
registry state, launch a process, elevate, modify a service, or start a repair.
It inspects and reports. This is why ``POWERSHELL`` is answered by looking for
the executable rather than by running it -- running it would be a process launch,
and a capability layer that has side effects cannot be called speculatively,
which is the only reason to have one.

**Only capabilities something consumes today appear here.** A registry of eight
serving three call sites is exactly the speculative API this package is meant to
avoid. The enum grows when a feature arrives, not in anticipation of one.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from enum import Enum


class Capability(Enum):
    #: Running a PowerShell command via polybedrock.ps_run.
    POWERSHELL = "powershell"
    #: Reading Windows security posture via polybedrock.win_security.
    SYSTEM_SECURITY = "system_security"


@dataclass(frozen=True)
class CapabilityState:
    """The answer, in a shape a UI can render without further interpretation."""
    capability: Capability
    available: bool
    #: True when the capability works but returns a reduced answer unelevated.
    #: Distinct from `available`: a caller may still want the partial result.
    requires_elevation: bool
    #: Human-readable, always populated -- including when available is True, so
    #: a tooltip has something to say either way.
    reason: str

    def __bool__(self) -> bool:
        return self.available


def _powershell() -> CapabilityState:
    if os.name != "nt":
        return CapabilityState(
            Capability.POWERSHELL, False, False,
            "Not Windows; PowerShell is not available.")
    exe = shutil.which("powershell.exe")
    if not exe:
        return CapabilityState(
            Capability.POWERSHELL, False, False,
            "powershell.exe was not found on PATH.")
    return CapabilityState(
        Capability.POWERSHELL, True, False, f"Available at {exe}.")


def _system_security() -> CapabilityState:
    ps = _powershell()
    if not ps.available:
        return CapabilityState(
            Capability.SYSTEM_SECURITY, False, False,
            f"Requires PowerShell. {ps.reason}")
    try:
        import winreg  # noqa: F401  -- presence check only, nothing is opened
    except ImportError:
        return CapabilityState(
            Capability.SYSTEM_SECURITY, False, False,
            "The winreg module is unavailable.")
    # Several probes (Secure Boot, TPM ownership, account policy) return a
    # reduced answer without elevation rather than failing, so this reports
    # available-but-partial rather than unavailable.
    return CapabilityState(
        Capability.SYSTEM_SECURITY, True, True,
        "Available; some device and account details need administrator rights.")


_PROBES = {
    Capability.POWERSHELL: _powershell,
    Capability.SYSTEM_SECURITY: _system_security,
}


def probe(capability: Capability) -> CapabilityState:
    """Report on one capability. Cheap, repeatable, and free of side effects."""
    try:
        return _PROBES[capability]()
    except KeyError:
        raise ValueError(f"no probe registered for {capability!r}") from None


def probe_all() -> dict[Capability, CapabilityState]:
    """Every registered capability, for a diagnostics view."""
    return {cap: probe(cap) for cap in Capability}
