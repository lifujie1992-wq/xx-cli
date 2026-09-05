from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from tmall_sku_cli.output import CliError
from tmall_sku_cli.webbridge import WebBridgeClient


class Response:
    def __init__(self, payload: object):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def payload(request) -> dict:
    return json.loads(request.data.decode())


def test_status_uses_openbridge_health():
    client = WebBridgeClient(daemon_url="http://127.0.0.1:10088")
    with patch("urllib.request.urlopen", return_value=Response({"ok": True, "connectedSessions": ["x"]})) as urlopen:
        assert client.require_ready()["ok"] is True
    assert urlopen.call_args.args[0].full_url == "http://127.0.0.1:10088/health"


def test_navigate_creates_session_tab_when_none_exists():
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(payload(request))
        tool = requests[-1]["toolName"]
        if tool == "browser_find_tab":
            return Response({"data": {"tabs": [], "count": 0}})
        assert tool == "browser_navigate"
        return Response({"data": {"tabId": 7}})

    client = WebBridgeClient(session="tmall", daemon_url="http://bridge")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert client.navigate("https://detail.tmall.com/item.htm", new_tab=False)["tabId"] == 7

    assert requests[0] == {
        "toolName": "browser_find_tab",
        "args": {"sessionId": "tmall", "activate": False},
    }
    assert requests[1]["args"]["newTab"] is True
    assert requests[1]["args"]["sessionId"] == "tmall"
    assert "sessionId" not in {key for key in requests[1] if key != "args"}


def test_async_evaluate_is_polled_and_normalized():
    requests = []
    evaluate_results = iter(
        [
            {"state": "pending", "key": "probe"},
            {"state": "fulfilled", "type": "string", "value": '{"ok":true}'},
        ]
    )

    def fake_urlopen(request, timeout):
        command = payload(request)
        requests.append(command)
        if command["toolName"] == "browser_find_tab":
            return Response({"data": {"tabs": [{"tabId": 9}], "count": 1}})
        if command["toolName"] == "browser_select_tab":
            return Response({"data": {"tabId": 9}})
        assert command["toolName"] == "browser_evaluate"
        return Response({"data": {"result": next(evaluate_results), "type": "object"}})

    client = WebBridgeClient(session="tmall", daemon_url="http://bridge")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep"):
        assert client.evaluate_json("Promise.resolve(JSON.stringify({ok:true}))") == {"ok": True}

    evaluate_calls = [item for item in requests if item["toolName"] == "browser_evaluate"]
    assert len(evaluate_calls) == 2
    assert all(item["args"]["sessionId"] == "tmall" for item in evaluate_calls)


def test_http_error_decodes_openbridge_error():
    body = io.BytesIO(json.dumps({"error": {"code": "TOOL_DISABLED", "message": "Enable browser_evaluate"}}).encode())
    error = urllib.error.HTTPError("http://bridge/command", 400, "Bad Request", {}, body)
    client = WebBridgeClient(daemon_url="http://bridge")

    with patch("urllib.request.urlopen", side_effect=error), pytest.raises(CliError) as raised:
        client.call("navigate", {"url": "https://example.com", "newTab": True})

    assert raised.value.code == "TOOL_DISABLED"
    assert raised.value.message == "Enable browser_evaluate"
