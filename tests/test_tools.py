"""Tests for the standalone command line helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
import sys

import pytest

_PATH = Path(__file__).parents[1] / "tools" / "fastweb_power_control.py"
_SPEC = importlib.util.spec_from_file_location("fastweb_tool", _PATH)
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_save_cookie_is_private_from_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without a later chmod, the file must already be private when it is written.
    monkeypatch.setattr(tool.os, "chmod", lambda *args, **kwargs: None)
    target = tmp_path / "session.cookie"
    stale = tmp_path / "session.cookie.tmp"
    stale.write_text("old")
    stale.chmod(0o644)

    tool.save_cookie(str(target), "FWB_RM=abc")

    assert target.read_text() == "FWB_RM=abc\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not stale.exists()


def test_read_cookie_rejects_multiline_values(tmp_path: Path) -> None:
    path = tmp_path / "cookie"
    path.write_text("Cookie: FWB_RM=abc\nX: y")
    with pytest.raises(tool.FastwebError):
        tool.read_cookie(str(path))
    path.write_text("Cookie: FWB_RM=abc")
    assert tool.read_cookie(str(path)) == "FWB_RM=abc"
