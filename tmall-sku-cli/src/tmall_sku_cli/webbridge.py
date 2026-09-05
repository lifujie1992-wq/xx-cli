from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .output import CliError

DEFAULT_DAEMON_URL = "http://127.0.0.1:10088"
OPENBRIDGE_URL_ENV = "OPENBRIDGE_URL"


@dataclass(frozen=True)
class WebBridgeClient:
    session: str = "tmall-sku-cli"
    daemon_url: str | None = None
    timeout_seconds: int = 90

    @property
    def base_url(self) -> str:
        configured = self.daemon_url or os.environ.get(OPENBRIDGE_URL_ENV) or DEFAULT_DAEMON_URL
        return configured.rstrip("/")

    def status(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/health")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise CliError(
                "webbridge_unreachable",
                f"OpenBridge daemon is unreachable at {self.base_url}",
                str(exc),
            ) from exc
        status = self._decode_json(raw, "OpenBridge health endpoint returned non-JSON")
        if not isinstance(status, dict):
            raise CliError("webbridge_status_invalid", "OpenBridge health response is not an object", status)
        return status

    def require_ready(self) -> dict[str, Any]:
        status = self.status()
        if not status.get("ok"):
            raise CliError(
                "webbridge_not_running",
                "OpenBridge daemon is not ready. Start it with: openbridge start",
                status,
            )
        if not status.get("connectedSessions"):
            raise CliError(
                "webbridge_extension_disconnected",
                "OpenBridge is running, but its Chrome extension is not connected or authorized.",
                status,
            )
        return status

    def call(self, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        mapped = dict(args or {})
        if "group_title" in mapped:
            mapped["groupTitle"] = mapped.pop("group_title")
        if self.session:
            mapped["sessionId"] = self.session

        if action == "evaluate":
            if self.session and not self._select_session_tab():
                raise CliError(
                    "TAB_NOT_FOUND",
                    f"No OpenBridge tab is assigned to session {self.session!r}",
                )
            code = mapped.pop("code", None)
            if not isinstance(code, str):
                raise CliError(
                    "webbridge_evaluate_code",
                    "OpenBridge evaluate requires a string code argument",
                )
            return self._evaluate(code, mapped)

        if action == "find_tab":
            mapped.pop("sessionId", None)
            if "url" in mapped:
                mapped["urlContains"] = mapped.pop("url")
            mapped.pop("active", None)
            mapped["activate"] = False
            data = self._command("browser_find_tab", mapped)
            tabs = data.get("tabs", []) if isinstance(data, dict) else []
            if not tabs:
                raise CliError("TAB_NOT_FOUND", "OpenBridge found no matching Chrome tab", data)
            select_args: dict[str, Any] = {"tabId": tabs[0]["tabId"]}
            if self.session:
                select_args["sessionId"] = self.session
            self._command("browser_select_tab", select_args)
            return self._require_object(data, "browser_find_tab")

        if action == "navigate":
            if self.session and not bool(mapped.get("newTab")) and not self._select_session_tab():
                mapped["newTab"] = True
        elif self.session and not self._select_session_tab():
            raise CliError(
                "TAB_NOT_FOUND",
                f"No OpenBridge tab is assigned to session {self.session!r}",
            )

        tool_name = action if action.startswith("browser_") else f"browser_{action}"
        return self._require_object(self._command(tool_name, mapped), tool_name)

    def navigate(self, url: str, new_tab: bool = False) -> dict[str, Any]:
        return self.call(
            "navigate",
            {"url": url, "newTab": new_tab, "groupTitle": "tmall-sku-cli"},
        )

    def evaluate_string(self, code: str) -> str:
        data = self.call("evaluate", {"code": code})
        if data.get("type") != "string":
            raise CliError(
                "webbridge_evaluate_type",
                f"Expected evaluate type=string, got {data.get('type')!r}",
                data,
            )
        value = data.get("value")
        if not isinstance(value, str):
            raise CliError("webbridge_evaluate_value", "Evaluate value is not a string", data)
        return value

    def evaluate_json(self, code: str) -> dict[str, Any]:
        value = self.evaluate_string(code)
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CliError(
                "webbridge_evaluate_json",
                "Evaluate returned a string that is not JSON",
                {"value": value[:1000], "error": str(exc)},
            ) from exc
        if not isinstance(decoded, dict):
            raise CliError(
                "webbridge_evaluate_json_type",
                "Evaluate JSON result is not an object",
                decoded,
            )
        return decoded

    def _select_session_tab(self) -> bool:
        data = self._command(
            "browser_find_tab",
            {"sessionId": self.session, "activate": False},
        )
        tabs = data.get("tabs", []) if isinstance(data, dict) else []
        if not tabs:
            return False
        self._command(
            "browser_select_tab",
            {"tabId": tabs[0]["tabId"], "sessionId": self.session},
        )
        return True

    def _evaluate(self, expression: str, args: dict[str, Any]) -> dict[str, Any]:
        key = f"__xcli_openbridge_{uuid.uuid4().hex}"
        wrapped = f"""(() => {{
  const __key = {json.dumps(key)};
  const __pack = value => ({{state: "fulfilled", type: value === null ? "object" : typeof value, value: value === undefined ? null : value}});
  try {{
    const __value = (0, eval)({json.dumps(expression)});
    if (__value && typeof __value.then === "function") {{
      globalThis[__key] = {{state: "pending", key: __key}};
      Promise.resolve(__value).then(
        value => {{ globalThis[__key] = __pack(value); }},
        error => {{ globalThis[__key] = {{state: "rejected", message: String(error && (error.stack || error.message) || error)}}; }}
      );
      return globalThis[__key];
    }}
    return __pack(__value);
  }} catch (error) {{
    return {{state: "rejected", message: String(error && (error.stack || error.message) || error)}};
  }}
}})()"""
        evaluate_args = dict(args)
        evaluate_args["expression"] = wrapped
        state = self._run_evaluate(evaluate_args)
        deadline = time.monotonic() + self.timeout_seconds

        while state.get("state") == "pending":
            if time.monotonic() >= deadline:
                raise CliError(
                    "webbridge_evaluate_timeout",
                    "OpenBridge timed out waiting for asynchronous JavaScript",
                )
            time.sleep(0.05)
            poll_args = dict(args)
            poll_args["expression"] = f"""(() => {{
  const __key = {json.dumps(key)};
  const __value = globalThis[__key];
  if (!__value) return {{state: "rejected", message: "async evaluation state was lost"}};
  if (__value.state !== "pending") delete globalThis[__key];
  return __value;
}})()"""
            state = self._run_evaluate(poll_args)

        if state.get("state") == "rejected":
            raise CliError(
                "webbridge_evaluate_failed",
                f"OpenBridge JavaScript evaluation failed: {state.get('message', 'unknown error')}",
                state,
            )
        if state.get("state") != "fulfilled":
            raise CliError("webbridge_evaluate_state", "OpenBridge returned an unknown evaluate state", state)
        return {"type": state.get("type"), "value": state.get("value")}

    def _run_evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        data = self._command("browser_evaluate", args)
        if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
            raise CliError(
                "webbridge_evaluate_response",
                "OpenBridge browser_evaluate returned an unexpected response",
                data,
            )
        return data["result"]

    def _command(self, tool_name: str, args: dict[str, Any]) -> Any:
        payload = json.dumps(
            {"toolName": tool_name, "args": args},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            self._raise_command_error(tool_name, raw, exc.code)
            raise AssertionError("unreachable")
        except urllib.error.URLError as exc:
            raise CliError(
                "webbridge_unreachable",
                f"OpenBridge daemon is unreachable at {self.base_url}",
                str(exc),
            ) from exc

        envelope = self._decode_json(raw, "OpenBridge returned a non-JSON response")
        if not isinstance(envelope, dict):
            raise CliError("webbridge_response_invalid", "OpenBridge response is not an object", envelope)
        if envelope.get("error"):
            self._raise_command_error(tool_name, raw, None)
        return envelope.get("data")

    def _raise_command_error(self, tool_name: str, raw: str, status: int | None) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            raise CliError(
                "webbridge_response_invalid",
                f"OpenBridge returned HTTP {status} with a non-JSON response",
                raw,
            )
        error = envelope.get("error") if isinstance(envelope, dict) else None
        if isinstance(error, dict):
            raise CliError(
                str(error.get("code") or "webbridge_command_failed"),
                str(error.get("message") or f"OpenBridge tool failed: {tool_name}"),
                envelope,
            )
        raise CliError(
            "webbridge_command_failed",
            f"OpenBridge tool failed: {tool_name}",
            {"status": status, "response": envelope},
        )

    @staticmethod
    def _decode_json(raw: str, message: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError(
                "webbridge_response_invalid",
                message,
                {"response": raw, "error": str(exc)},
            ) from exc

    @staticmethod
    def _require_object(value: Any, tool_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CliError(
                "webbridge_data_invalid",
                f"OpenBridge {tool_name} response data is not an object",
                value,
            )
        return value
