import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from openbridge_client import OpenBridgeClient


class Response:
    def __init__(self, value):
        self.value = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.value


class OpenBridgeClientTest(unittest.TestCase):
    def test_navigate_creates_new_session_tab(self):
        seen = []

        def urlopen(request, timeout):
            command = json.loads(request.data)
            seen.append(command)
            if command["toolName"] == "browser_find_tab":
                return Response({"data": {"tabs": []}})
            return Response({"data": {"tabId": 3}})

        client = OpenBridgeClient("sphxd", "http://bridge")
        with patch("urllib.request.urlopen", side_effect=urlopen):
            result = client.call(
                "navigate",
                {"url": "https://example.com", "newTab": False, "group_title": "测试"},
            )

        self.assertEqual(result["tabId"], 3)
        self.assertTrue(seen[1]["args"]["newTab"])
        self.assertEqual(seen[1]["args"]["groupTitle"], "测试")
        self.assertEqual(seen[1]["args"]["sessionId"], "sphxd")
        self.assertNotIn("sessionId", seen[1])

    def test_async_evaluate_polls(self):
        states = iter(
            [
                {"state": "pending"},
                {"state": "fulfilled", "type": "string", "value": "done"},
            ]
        )

        def urlopen(request, timeout):
            command = json.loads(request.data)
            if command["toolName"] == "browser_find_tab":
                return Response({"data": {"tabs": [{"tabId": 8}]}})
            if command["toolName"] == "browser_select_tab":
                return Response({"data": {"tabId": 8}})
            return Response({"data": {"result": next(states), "type": "object"}})

        client = OpenBridgeClient("sphxd", "http://bridge")
        with patch("urllib.request.urlopen", side_effect=urlopen), patch("time.sleep"):
            result = client.call("evaluate", {"code": "Promise.resolve('done')"})
        self.assertEqual(result, {"type": "string", "value": "done"})

    def test_http_error_uses_structured_message(self):
        body = io.BytesIO(
            json.dumps({"error": {"code": "TOOL_DISABLED", "message": "enable it"}}).encode()
        )
        error = urllib.error.HTTPError("http://bridge", 400, "bad", {}, body)
        client = OpenBridgeClient("sphxd", "http://bridge")
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "TOOL_DISABLED: enable it"):
                client.call("navigate", {"url": "https://example.com", "newTab": True})


if __name__ == "__main__":
    unittest.main()
