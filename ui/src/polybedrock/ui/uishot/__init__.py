"""uishot — photograph a GUI without it ever being on screen.

No visible window, no focus stealing, no mouse control. Captures land as PNGs
and can be diffed against recorded goldens to catch visual regressions.

Two decisions carry the design, both measured rather than assumed:

1. **A hidden Win32 desktop, not off-screen coordinates.** Tk will not paint a
   window positioned outside the virtual screen; a window parked at
   (-3200, -3200) captures its text but none of its frame backgrounds — 95.58%
   of pixels wrong, including the page colour. Through a hidden desktop the
   image is byte-identical to the on-screen render (0 of 912,000 px differed).
2. **Reproduce the entry point's global setup.** See `session.TkSession`.

`desktop` and `capture` are toolkit-agnostic — they take an `hwnd`. Only
`session` knows about Tk. A Qt application needs neither: `QWidget.grab()`
renders to a pixmap with no window at all, and `QT_QPA_PLATFORM=offscreen` gives
true headless rendering; the reusable parts there are `compare` / `write_diff`
and the scene/golden/CLI structure.
"""
from .capture import CaptureError, capture_window, compare, write_diff
from .desktop import DesktopUnavailable, hidden_desktop
from .registry import SceneRegistry
from .session import Shot, TkSession, is_supported

__all__ = ["capture_window", "compare", "write_diff", "CaptureError",
           "hidden_desktop", "DesktopUnavailable", "SceneRegistry",
           "TkSession", "Shot", "is_supported"]
