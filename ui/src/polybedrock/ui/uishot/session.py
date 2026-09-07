"""
TkSession — build a CustomTkinter view on a hidden desktop and photograph it.

Usage::

    with TkSession(out_dir=Path("artifacts/ui"),
                   project_root=ROOT,
                   entry_module="polyscour.app",
                   on_root=my_theme_setup) as s:
        view = s.mount(DashboardView, app=fake_app)
        s.shot("dashboard")
        view.set_some_state(...)
        s.shot("dashboard_after")

Nothing appears on any screen, nothing takes focus, and the mouse is never
touched. Widgets are driven through Tk (``invoke()``, direct handler calls), not
by synthesising input — which is both faster and immune to whatever else the
machine is doing.

The two application-shaped hooks
--------------------------------

``entry_module`` and ``on_root`` exist because of a bug that cost real time on
PolyShield, and they are the whole reason this class could be shared.

``ui/app.py`` calls ``ctk.set_appearance_mode("dark")`` at **module** level.
Importing only the view modules leaves CustomTkinter in its default *light*
appearance, and every label that does not set an explicit ``text_color`` renders
dark-on-dark — nearly invisible, but a perfectly valid-looking screenshot. The
first Settings capture looked like a genuine contrast bug in the application. It
was the harness.

So the session **imports the real entry point** rather than guessing at what it
configures, and hands the root back to the application for anything else its
startup does (theme initialisation, loading a Tcl package, and so on).

The general lesson, worth keeping in the shared code: a capture harness that
does not reproduce global initialisation will hand you a picture that is wrong
in ways no assertion catches.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .capture import PW_RENDERFULLCONTENT, capture_window
from .desktop import DesktopUnavailable, hidden_desktop


@dataclass
class Shot:
    name: str
    path: Path
    size: tuple[int, int]
    scene: str = ""


class TkSession:
    """A Tk root living on a hidden desktop, plus a shot recorder."""

    def __init__(self, out_dir: Path | str = Path("artifacts/ui"),
                 size: tuple[int, int] = (1200, 760),
                 settle_cycles: int = 20,
                 project_root: Path | None = None,
                 entry_module: str | None = None,
                 on_root: Callable[[object], None] | None = None):
        self.out_dir = Path(out_dir)
        self.size = size
        self.settle_cycles = settle_cycles
        self.shots: list[Shot] = []
        self._desktop_cm = None
        self._root = None
        self._mounted = []
        self._warned_clamp = False
        self._entry_module = entry_module
        self._on_root = on_root
        # Set by the CLI before each scene; initialised here so a session used
        # directly (as the docstring above shows) still works.
        self.current_scene = ""
        self._project_root = project_root or Path.cwd()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __enter__(self) -> "TkSession":
        # Order matters: bind the desktop before anything creates a window.
        # SetThreadDesktop fails once the calling thread owns one.
        self._desktop_cm = hidden_desktop()
        self._desktop_cm.__enter__()

        for path in (self._project_root, self._project_root / "src"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))

        import customtkinter as ctk

        # Reproduce the real entry point's GLOBAL setup before building
        # anything -- see the module docstring for what happens otherwise.
        if self._entry_module:
            importlib.import_module(self._entry_module)

        self._ctk = ctk
        self._root = ctk.CTk()
        self._root.geometry(f"{self.size[0]}x{self.size[1]}+0+0")

        # Anything else the application's startup does: theme initialisation,
        # loading a Tcl package a view needs at build time, and so on.
        if self._on_root is not None:
            self._on_root(self._root)

        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc):
        if self._root is not None:
            self._cancel_pending()
            try:
                self._root.destroy()
            except Exception:
                pass
            self._root = None
        if self._desktop_cm is not None:
            self._desktop_cm.__exit__(*exc)
            self._desktop_cm = None
        return False

    def _cancel_pending(self) -> None:
        """Drop queued `after` callbacks before teardown.

        CustomTkinter schedules DPI and redraw callbacks; if they fire after
        destroy, Tcl prints 'invalid command name ...update' noise that looks
        like a failure but is not.
        """
        try:
            for job in self._root.tk.call("after", "info"):
                try:
                    self._root.after_cancel(job)
                except Exception:
                    pass
        except Exception:
            pass

    # ── Building ──────────────────────────────────────────────────────────────

    @property
    def root(self):
        if self._root is None:
            raise RuntimeError("TkSession must be used as a context manager")
        return self._root

    def mount(self, view_cls, **kwargs):
        """Instantiate a view, fill the window with it, and return it."""
        for existing in self._mounted:
            try:
                existing.pack_forget()
            except Exception:
                pass
        view = view_cls(self.root, **kwargs)
        view.pack(fill="both", expand=True)
        self._mounted.append(view)
        self.settle()
        return view

    def settle(self, cycles: int | None = None) -> None:
        """Let Tk finish layout and painting before a capture."""
        self.root.update_idletasks()
        for _ in range(cycles if cycles is not None else self.settle_cycles):
            self.root.update()

    # ── Capturing ─────────────────────────────────────────────────────────────

    def _stable_capture(self, attempts: int = 4):
        """Capture the same frame twice and only accept it once it stops moving.

        ``settle()`` drains Tk's event queue, which is necessary and not
        sufficient: ``PrintWindow`` asks the window to paint itself, and under
        load Windows can hand back a frame where labels are half-drawn. The
        failure is silent and looks exactly like a UI change -- observed as
        goldens "drifting" with text truncated to its first character, a
        different scene each run.

        Two identical consecutive frames is the cheapest honest evidence that
        painting has finished. On the last attempt the frame is returned
        anyway: a capture that never settles is still more useful to look at
        than an exception, and a genuinely animating UI would otherwise never
        photograph at all.
        """
        previous = None
        for attempt in range(attempts):
            self.settle()
            image = capture_window(self.root.winfo_id(), PW_RENDERFULLCONTENT)
            if previous is not None and image.tobytes() == previous:
                return image
            previous = image.tobytes()
        return image

    def shot(self, name: str) -> Shot:
        image = self._stable_capture()

        # A hidden desktop inherits the session's screen metrics, so a window
        # larger than the desktop is silently clamped — the shot then shows a
        # cropped layout rather than the one that was asked for. Measured on a
        # GitHub windows-latest runner: 1200x760 requested, 1028x749 delivered.
        # Say so once, because it is also why golden images do not travel.
        if image.size != self.size and not self._warned_clamp:
            self._warned_clamp = True
            print(f"uishot: window clamped to {image.size[0]}x{image.size[1]} "
                  f"(requested {self.size[0]}x{self.size[1]}) — the desktop is "
                  f"smaller than the window; shots will not match goldens "
                  f"recorded elsewhere", file=sys.stderr)

        path = self.out_dir / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        shot = Shot(name=name, path=path, size=image.size,
                    scene=self.current_scene)
        self.shots.append(shot)
        return shot


def is_supported() -> tuple[bool, str]:
    """Whether hidden-desktop capture can run here."""
    if sys.platform != "win32":
        return False, "hidden-desktop capture is Windows-only"
    try:
        with hidden_desktop("UIShotProbe"):
            pass
    except DesktopUnavailable as exc:
        return False, str(exc)
    return True, ""
