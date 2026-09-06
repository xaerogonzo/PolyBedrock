"""
PolyShield — user settings persistence.

Two processes write this file: the UI, and the Windows Service (via the
SET_CONFIG IPC command and via watcher.start()/stop()).  That is the whole
reason this module is more than json.dump().

Concurrency contract
--------------------
`set_value()` is the persistence primitive.  One call performs, under an
OS-owned cross-process lock:

    re-read the file  ->  merge the one changed key  ->  atomic replace

Re-reading inside the lock is what makes concurrent writers preserve each
other's keys.  Atomic replacement alone does NOT: it protects the *file* from
a torn write, not the read-merge-replace *transaction*.  Without the lock,
this interleaving silently loses a=2:

    A: read {a:1,b:1}                B: read {a:1,b:1}
    A: write {a:2,b:1}               B: write {a:1,b:2}

The lock is a byte-range lock (msvcrt.locking) held on a *sidecar* file,
`ui_settings.json.lock`.  Two properties matter and neither is incidental:

  * It is owned by the OS handle, so a crashed process releases it
    automatically.  A PID-in-a-lockfile convention would leave settings
    permanently "locked" after one crash.
  * It is on a sidecar rather than on ui_settings.json itself, because
    Windows refuses os.replace() over a file that has an open handle —
    locking the target would break the atomic replace it exists to protect.

`intel_updater._acquire_file_lock()` is deliberately NOT reused: it is built
for hour-scale operations and reclaims on age, which is the wrong semantics
for a millisecond write.

Return values (never exceptions — see below)
--------------------------------------------
    SAVE_OK        durable merge completed under the lock
    SAVE_DEGRADED  lock timed out; a single best-effort write was made.  This
                   write is explicitly OUTSIDE the lost-update guarantee.
    SAVE_FAILED    nothing was persisted; _cache is left unchanged

Cost
----
set_value() is not free: a lock acquisition, a read, a merge, and an atomic
replace with an fsync is roughly 3 ms. That is fine for a button or a switch
and wrong for a continuous input -- do not call it from a slider `command=`
handler on every tick. display_view's sliders coalesce through
_schedule_persist() and flush on release; anything similar should do the same.
The fsync is deliberate: os.replace() keeps a reader from ever seeing a torn
file, but without the flush a crash can leave the new name pointing at
unwritten blocks, which is the corruption this module exists to prevent.

set_value() returns a status rather than raising.  All 73 call sites are bare
calls inside Tk event handlers — including slider `command=` callbacks that
fire on every drag tick — so an exception would propagate into Tk's dispatcher
per tick.  Callers that ignore the return value behave exactly as before;
callers that care can check it.  Every non-OK outcome is logged.
"""
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

try:                                    # Windows-only; the product is too.
    import msvcrt
except ImportError:                     # pragma: no cover - non-Windows
    msvcrt = None

log = logging.getLogger(__name__)

#: Both are None until configure() runs. They stay module-level globals that
#: every function reads at call time rather than captures, because PolyShield's
#: conftest patches _SETTINGS_FILE to redirect a whole test session at a tmp_path
#: -- a capture would make that patch invisible.
_SETTINGS_FILE: Path | None = None
_LOCK_FILE:     Path | None = None


def configure(config_path, defaults: dict | None = None) -> None:
    """Bind the settings file. Call once, before any load()/save().

    Takes the path and the defaults rather than a paths module: which directory
    a settings file belongs in, and what a missing key means, are both the
    consuming application's decisions. Inverting them this way is what lets this
    module be shared without knowing whose settings it is holding -- PolyShield's
    defaults name VirusTotal keys and Guardian AI profiles, which have no meaning
    to any other consumer.
    """
    global _SETTINGS_FILE, _LOCK_FILE, _DEFAULTS
    _SETTINGS_FILE = Path(config_path)
    _LOCK_FILE     = _SETTINGS_FILE.with_name(_SETTINGS_FILE.name + ".lock")
    _DEFAULTS      = dict(defaults or {})


def _require_configured() -> Path:
    if _SETTINGS_FILE is None:
        raise RuntimeError(
            "polybedrock.settings is unconfigured: call configure(config_path) "
            "before reading or writing settings.")
    return _SETTINGS_FILE

SAVE_OK       = "ok"
SAVE_DEGRADED = "degraded"
SAVE_FAILED   = "failed"

# Bounded so a settings write can never block a UI toggle indefinitely.
_LOCK_TIMEOUT_S = 2.0
_LOCK_RETRY_S   = 0.02

# Serialises writers inside THIS process; the file lock handles the other one.
_write_lock = threading.Lock()

#: Set by configure(). Empty rather than absent so the merge expressions below
#: read the same whether or not an application supplied defaults.
_DEFAULTS: dict = {}

_cache: dict | None = None


# ── Cross-process lock ────────────────────────────────────────────────────────

class _FileLock:
    """OS-owned byte-range lock on the sidecar file.

    Used as a context manager; `acquired` says whether the lock was actually
    taken or the bounded wait expired.  A timeout is not an error — the caller
    degrades to a best-effort write and reports SAVE_DEGRADED.
    """

    def __init__(self, timeout: float = _LOCK_TIMEOUT_S):
        self._timeout = timeout
        self._fd: int | None = None
        self.acquired = False

    def __enter__(self) -> "_FileLock":
        if msvcrt is None:                       # pragma: no cover
            self.acquired = True                 # in-process lock is all we have
            return self
        try:
            _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            log.warning("settings: cannot open lock file (%s); "
                        "proceeding without cross-process exclusion", exc)
            return self

        deadline = time.monotonic() + self._timeout
        while True:
            try:
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                self.acquired = True
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    log.warning(
                        "settings: lock busy for %.1fs; falling back to a "
                        "best-effort write (outside the lost-update guarantee)",
                        self._timeout)
                    return self
                time.sleep(_LOCK_RETRY_S)

    def __exit__(self, *exc_info) -> None:
        if self._fd is None:
            return
        try:
            if self.acquired and msvcrt is not None:
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass                                 # handle close releases it anyway
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


# ── Corruption handling ───────────────────────────────────────────────────────

def _preserve_corrupt(raw: bytes) -> None:
    """Copy unparseable settings aside for diagnosis.

    Deliberately a COPY, never a move: if this fails, the user's original file
    is still the original file.  It is their last remaining copy and outranks
    successful recovery bookkeeping — nothing here may delete or truncate it.
    """
    target = _SETTINGS_FILE.with_name(_SETTINGS_FILE.name + ".corrupt")
    if target.exists():
        # Never clobber a previous diagnostic artifact.
        stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = _SETTINGS_FILE.with_name(f"{_SETTINGS_FILE.name}.{stamp}.corrupt")
    try:
        target.write_bytes(raw)
        log.error("settings: %s was unreadable; preserved as %s and "
                  "falling back to defaults", _SETTINGS_FILE.name, target.name)
    except OSError as exc:
        log.error("settings: %s was unreadable and could not be preserved "
                  "(%s); the original is left untouched",
                  _SETTINGS_FILE.name, exc)


def _read_disk() -> dict:
    """Return the on-disk settings as a dict.

    Absent file -> {} with no .corrupt artifact.  Malformed file -> preserved
    aside, then {} so _DEFAULTS becomes the merge base.  This is the read half
    of set_value()'s locked transaction as well as load()'s, so both paths get
    identical recovery behaviour.
    """
    try:
        raw = _SETTINGS_FILE.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        log.error("settings: cannot read %s (%s); using defaults",
                  _SETTINGS_FILE, exc)
        return {}

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _preserve_corrupt(raw)
        return {}

    if not isinstance(data, dict):
        _preserve_corrupt(raw)
        return {}
    return data


# ── Atomic write ──────────────────────────────────────────────────────────────

def _atomic_write(data: dict) -> bool:
    """Write `data` via a unique temp file + os.replace.  True if it landed.

    The temp name must be unique: a fixed ui_settings.json.tmp is a file two
    processes collide on.  On any failure the original file is left intact and
    the temp file is removed.
    """
    fd = tmp = None
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_SETTINGS_FILE.parent),
                                   prefix=".ui_settings-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None                            # fdopen owns it now
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(_SETTINGS_FILE))
        return True
    except Exception as exc:
        log.error("settings: durable write failed (%s); %s is unchanged",
                  exc, _SETTINGS_FILE.name)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def load() -> dict:
    """(Re)read settings from disk into the process cache."""
    _require_configured()
    global _cache
    _cache = {**_DEFAULTS, **_read_disk()}
    return _cache


def get(key: str):
    if _cache is None:
        load()
    return _cache.get(key, _DEFAULTS.get(key))


def set_value(key: str, value) -> str:
    """Persist one key.  Returns SAVE_OK / SAVE_DEGRADED / SAVE_FAILED.

    The whole read-merge-write runs inside both locks so a concurrent writer
    in either this process or the service cannot lose the other's key.  On
    failure `_cache` is deliberately left alone: it must never report a value
    as persisted when the durable write did not land.
    """
    global _cache
    if _cache is None:
        load()

    with _write_lock:
        with _FileLock() as lock:
            merged = _read_disk()
            merged[key] = value
            written = _atomic_write(merged)

        if not written:
            return SAVE_FAILED

        _cache = {**_DEFAULTS, **merged}
        return SAVE_OK if lock.acquired else SAVE_DEGRADED


def save(updated: dict) -> str:
    """Deprecated whole-file write.  Prefer set_value().

    Kept as cheap insurance against a late-bound caller; the v1.13 audit found
    none.  Unlike set_value() this does NOT merge — it replaces the file
    wholesale, reintroducing exactly the lost-update problem set_value() exists
    to avoid.
    """
    _require_configured()
    global _cache
    with _write_lock:
        with _FileLock() as lock:
            written = _atomic_write(updated)
        if not written:
            return SAVE_FAILED
        _cache = {**_DEFAULTS, **updated}
        return SAVE_OK if lock.acquired else SAVE_DEGRADED
