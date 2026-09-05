import json

import pytest

from tmall_sku_cli.output import failure, success


@pytest.mark.unit
def test_success_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    assert success({"x": 1}) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "data": {"x": 1}}


@pytest.mark.unit
def test_failure_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    assert failure("bad", "Bad thing") == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "ok": False,
        "error": {"code": "bad", "message": "Bad thing"},
    }
