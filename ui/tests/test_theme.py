"""The one thing that had to change when theme.py became shared."""
from __future__ import annotations

import pytest

ctk = pytest.importorskip("customtkinter")

from polybedrock.ui import theme


def test_the_app_name_is_formatted_into_the_classic_preset():
    """PolyShield shipped the label 'Classic PolyShield'; PolyScour must not
    inherit it. Everything else was already generic."""
    theme.configure("Demo")
    labels = dict(theme.preset_names())
    assert labels["classic"] == "Classic Demo"
    assert labels["forest"] == "Deep Forest"


def test_an_unconfigured_theme_does_not_leave_a_dangling_word():
    """Rendered before configure() runs, the label should read 'Classic', not
    'Classic ' with a trailing space sitting in a dropdown."""
    theme.configure("")
    assert dict(theme.preset_names())["classic"] == "Classic"


def test_every_preset_has_a_label():
    theme.configure("Demo")
    assert set(dict(theme.preset_names())) == set(
        k for k, _ in theme.preset_names())
    for key, label in theme.preset_names():
        assert label.strip(), f"preset {key} has an empty label"
