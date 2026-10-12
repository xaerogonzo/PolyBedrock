r"""tests/test_settings_bom.py -- a UTF-8 byte-order mark is not corruption.

Found by PolyShield's CI: its install verifier wrote ``ui_settings.json`` with
Windows PowerShell 5.1's ``Set-Content -Encoding UTF8``, which prepends
``EF BB BF``. The reader decoded strict UTF-8, so ``json.loads`` refused the
file, the module set it aside as ``.corrupt`` and carried on with defaults --
logging an error to stderr, which in turn aborted a PowerShell script that ran
under ``$ErrorActionPreference = "Stop"``. A valid settings file had been
reported as damaged and its contents thrown away.

The recovery path for genuinely malformed files is unchanged and is pinned here
too, because a fix that loosened the reader into accepting garbage would be worse
than the bug.
"""
from __future__ import annotations

import json

import pytest

from polybedrock import settings

BOM = b"\xef\xbb\xbf"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A configured settings module pointed at a tmp file, with every module
    global the tests touch restored afterwards."""
    for name in ("_SETTINGS_FILE", "_LOCK_FILE", "_DEFAULTS", "_cache"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    settings.configure(tmp_path / "ui_settings.json", {"theme": "dark", "scale": 1})
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path / "ui_settings.json"


def _corrupt_artifacts(path):
    return list(path.parent.glob(path.name + "*.corrupt"))


def test_a_file_with_a_byte_order_mark_loads_and_is_not_set_aside(cfg):
    cfg.write_bytes(BOM + json.dumps({"theme": "light", "sentinel": "survived"}).encode())

    data = settings.load()

    assert data["theme"] == "light" and data["sentinel"] == "survived"
    assert not _corrupt_artifacts(cfg), "a valid file was reported as damaged"


def test_a_file_without_one_reads_exactly_as_before(cfg):
    cfg.write_bytes(json.dumps({"theme": "light"}).encode())

    assert settings.load()["theme"] == "light"
    assert not _corrupt_artifacts(cfg)


def test_writing_over_a_file_that_had_a_byte_order_mark_drops_it(cfg):
    """The module only ever writes BOM-less JSON, so the first save heals the
    file, and the existing keys survive the read-merge-write."""
    cfg.write_bytes(BOM + json.dumps({"theme": "light"}).encode())

    assert settings.set_value("scale", 2) == settings.SAVE_OK

    raw = cfg.read_bytes()
    assert not raw.startswith(BOM)
    assert json.loads(raw.decode("utf-8")) == {"theme": "light", "scale": 2}
    assert not _corrupt_artifacts(cfg)


@pytest.mark.parametrize("raw", [
    b"{not json",
    BOM + b"{not json",          # a BOM must not make garbage acceptable
    b"[1, 2, 3]",                # valid JSON, wrong shape
    BOM + b"[1, 2, 3]",
])
def test_genuinely_malformed_files_are_still_preserved_and_defaulted(cfg, raw):
    cfg.write_bytes(raw)

    data = settings.load()

    assert data["theme"] == "dark", "defaults must be the fallback"
    kept = _corrupt_artifacts(cfg)
    assert len(kept) == 1 and kept[0].read_bytes() == raw, (
        "the original bytes, BOM included, must be preserved untouched")
