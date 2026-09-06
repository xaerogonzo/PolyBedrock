r"""Where an application's files live.

The generic half of a lesson PolyShield paid for in production, kept here so
the next Forge application does not pay for it again.

Two lifetimes, and conflating them is the failure this module exists to remove:

    RESOURCE   ships with the program, read-only, recreatable from the bundle,
               may live in a temporary extraction directory that is DELETED
               when the process exits
    DATA       created or modified by the user or the application, must survive
               a restart, must never live only in a temporary directory

Under a Nuitka onefile build the modules are unpacked into a temp directory that
is removed on exit, so anything resolved from ``__file__`` and then written to is
gone the moment the process ends.

The choice this module forces you to make explicitly
---------------------------------------------------

``configure(data_scope=...)`` has no default, on purpose.

``"user"``    ``%LOCALAPPDATA%\<app>``  -- correct when every component that
              touches the data runs as the logged-in user.

``"machine"`` ``%ProgramData%\<app>``   -- required as soon as a Windows service
              shares the data.

PolyShield shipped ``"user"`` and it was wrong in a way no test could see. Its
service runs as ``NT AUTHORITY\LocalService``, whose profile is
``C:\Windows\ServiceProfiles\LocalService``, so the two components resolved two
different directories:

    GUI           C:\Users\<user>\AppData\Local\PolyShield
    LocalService  C:\Windows\ServiceProfiles\LocalService\AppData\Local\PolyShield

They read the same database and the same settings file -- and two of the files
underneath are cross-process *locks*. A lock file at a path each process resolves
differently does not merely fail to protect: it hands BOTH processes the lock at
once, silently, and what it guards is a SQLite write.

``%ProgramData%`` resolves to one directory for both accounts. It is deliberately
not writable by ordinary users by default, so a machine-scoped application needs
an installer that creates the tree with explicit per-subtree ACLs. That cost is
the reason the scope is a decision rather than a default: an application with no
service should not pay it, and one with a service cannot avoid it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Set by tests. None means "detect". Deliberately not cached, so a test can flip
# modes without reimporting every consumer.
_FROZEN_OVERRIDE: bool | None = None

_app_name: str = ""
_data_dir_env: str = ""
_data_scope: str = ""


def configure(app_name: str, data_dir_env: str, data_scope: str) -> None:
    """Name the application and choose where its durable data lives.

    ``data_scope`` is ``"user"`` or ``"machine"`` -- see the module docstring;
    there is no default because guessing it wrong is silent.
    """
    global _app_name, _data_dir_env, _data_scope
    if data_scope not in ("user", "machine"):
        raise ValueError(
            f"data_scope must be 'user' or 'machine', not {data_scope!r}. "
            "Choose 'machine' if a Windows service shares this data.")
    _app_name, _data_dir_env, _data_scope = app_name, data_dir_env, data_scope


def _require_configured() -> None:
    if not _app_name:
        raise RuntimeError(
            "polybedrock.paths is unconfigured: call configure(app_name, "
            "data_dir_env, data_scope) during application startup.")


def is_frozen() -> bool:
    """True when running from a compiled build rather than a source checkout.

    Covers Nuitka (which injects ``__compiled__`` into every module) and the
    ``sys.frozen`` flag PyInstaller and py2exe set, so the predicate does not
    have to be revisited if the packager changes.
    """
    if _FROZEN_OVERRIDE is not None:
        return _FROZEN_OVERRIDE
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def app_root() -> Path:
    r"""The durable, writable application-data root.

    Emphatically **not** ``Path(sys.executable).parent``: a build installed under
    ``C:\Program Files\<app>`` cannot write beside itself without elevation, so a
    beside-the-exe definition produces a build that works from ``dist\`` and
    fails for every real installation.

    Resolution order:

      1. ``%<DATA_DIR_ENV>%`` if set -- the seam for an installer, a portable
         launcher, or a deployment keeping data on another volume. It must be set
         MACHINE-WIDE to be useful: a service inherits nothing from the
         installing user's environment.
      2. The configured scope's base directory.
      3. A derived fallback when the environment is stripped, which is the shape
         a service account can actually arrive in.
    """
    _require_configured()

    override = os.environ.get(_data_dir_env, "").strip()
    if override:
        return Path(override).expanduser()

    var = "PROGRAMDATA" if _data_scope == "machine" else "LOCALAPPDATA"
    base = os.environ.get(var)
    if base:
        return Path(base) / _app_name

    # Nothing to go on -- a service account with a stripped environment.
    # Derived rather than hard-coded to C:, which is wrong on a machine booting
    # from another volume.
    system_drive = os.environ.get("SystemDrive")
    if system_drive and _data_scope == "machine":
        return Path(system_drive + "\\") / "ProgramData" / _app_name
    if system_drive:
        return Path(system_drive + "\\") / "Users" / "Default" / _app_name
    return Path(sys.executable).resolve().parent


# ── Named data locations ─────────────────────────────────────────────────────
#
# Thin, but they exist so a caller never has to remember which root a given
# directory belongs to -- which is the mistake this module is for.

def config_dir() -> Path:
    """User-editable configuration."""
    return app_root() / "config"


def logs_dir() -> Path:
    return app_root() / "logs"


def state_dir() -> Path:
    r"""Runtime state owned by a privileged component, where one exists.

    Separated from ``config_dir()`` because the two have different writers. In a
    machine-scoped application the installer gives this subtree
    ``<service account>:Modify`` and ``Users:Read``, so nothing an unelevated GUI
    writes may live here.
    """
    return app_root() / "state"
