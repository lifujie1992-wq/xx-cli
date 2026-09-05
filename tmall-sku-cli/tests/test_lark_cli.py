import json
import subprocess

import pytest

from tmall_sku_cli.lark_cli import LarkCli, LarkCommandError, _extract_json


@pytest.mark.unit
def test_extract_json_skips_warning_prefix() -> None:
    payload = _extract_json('warning\n{"ok": true, "data": {"x": 1}}')
    assert payload == {"ok": True, "data": {"x": 1}}


@pytest.mark.unit
def test_forbidden_detection() -> None:
    error = LarkCommandError(("lark-cli",), 1, '{"code":91403}', "Forbidden")
    assert error.is_forbidden


@pytest.mark.unit
def test_run_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps({"ok": True, "data": {"a": 1}}), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert LarkCli().run_json(["x"]) == {"ok": True, "data": {"a": 1}}


@pytest.mark.unit
def test_run_json_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args[0], 1, stdout="bad", stderr="Forbidden")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(LarkCommandError):
        LarkCli().run_json(["x"])


@pytest.mark.unit
def test_run_json_ok_false_raises_lark_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout=json.dumps({"ok": False, "error": {"code": 91403, "message": "Forbidden"}}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(LarkCommandError) as exc:
        LarkCli().run_json(["x"])
    assert exc.value.is_forbidden
