"""Scene registration.

A *scene* puts a view into a specific state and photographs it. The registry is
a class rather than module globals so two applications in one process cannot
collide -- and, more usefully, so a test can build a throwaway registry without
disturbing the real one.

Each application owns one instance and re-exports its `scene` decorator, which
keeps the call site reading exactly as it did before this was shared::

    @scene("dashboard", golden=False)
    def dashboard(session): ...
"""
from __future__ import annotations

from collections.abc import Callable


class SceneRegistry:
    """The scenes one application knows how to photograph."""

    def __init__(self) -> None:
        self._scenes: dict[str, Callable] = {}
        self._golden: set[str] = set()

    def scene(self, name: str, golden: bool = True):
        """Register a scene.

        ``golden=False`` marks a scene whose content depends on live data --
        feed ages tick over, row counts change after an update. Those shots are
        documentary: useful to look at, useless as a regression baseline,
        because they drift for reasons that have nothing to do with the code.
        A baseline that depends on the wall clock is worse than no baseline, so
        ``--check`` skips them.

        This was learned the hard way on PolyShield: the first golden set
        included live scenes, and an hour later three of them "drifted" purely
        because *just now* had become *11h ago*.

        Making a live scene comparable means pinning its inputs -- freeze the
        clock, fix the counts -- not widening ``--tolerance``.
        """
        def register(fn: Callable) -> Callable:
            self._scenes[name] = fn
            if golden:
                self._golden.add(name)
            return fn
        return register

    def all_scenes(self) -> dict[str, Callable]:
        return dict(self._scenes)

    def golden_scenes(self) -> set[str]:
        """Names whose shots are stable enough to compare against goldens."""
        return set(self._golden)
