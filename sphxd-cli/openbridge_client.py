"""Small dependency-free OpenBridge compatibility client for the sphxd scripts."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

DEFAULT_OPENBRIDGE_URL = "http://127.0.0.1:10088"


class OpenBridgeClient:
    def __init__(self, session: str, daemon_url: str | None = None, timeout: int = 120):
        self.session = session
        self.daemon_url = (
            daemon_url or os.environ.get("OPENBRIDGE_URL") or DEFAULT_OPENBRIDGE_URL
        ).rstrip("/")
        self.timeout = timeout

    def call(
        self,
        action: str,
        args: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        timeout = timeout or self.timeout
        mapped = dict(args or {})
        if "group_title" in mapped:
            mapped["groupTitle"] = mapped.pop("group_title")
        if self.session:
            mapped["sessionId"] = self.session

        if action == "evaluate":
            if self.session and not self._select_session_tab(timeout):
                raise RuntimeError(
                    f"TAB_NOT_FOUND: no OpenBridge tab is assigned to session {self.session!r}"
                )
            expression = mapped.pop("code", None)
            if not isinstance(expression, str):
                raise RuntimeError("OpenBridge evaluate requires a string code argument")
            return self._evaluate(expression, mapped, timeout)

        if action == "find_tab":
            mapped.pop("sessionId", None)
            if "url" in mapped:
                mapped["urlContains"] = mapped.pop("url")
            mapped.pop("active", None)
            mapped["activate"] = False
            data = self._command("browser_find_tab", mapped, timeout)
            tabs = data.get("tabs", []) if isinstance(data, dict) else []
            if not tabs:
                raise RuntimeError("TAB_NOT_FOUND: OpenBridge found no matching Chrome tab")
            select_args: dict[str, Any] = {"tabId": tabs[0]["tabId"]}
            if self.session:
                select_args["sessionId"] = self.session
            self._command("browser_select_tab", select_args, timeout)
            return self._object(data, "browser_find_tab")

        if action == "navigate":
            if self.session and not bool(mapped.get("newTab")):
                if not self._select_session_tab(timeout):
                    mapped["newTab"] = True
        elif self.session and not self._select_session_tab(timeout):
            raise RuntimeError(
                f"TAB_NOT_FOUND: no OpenBridge tab is assigned to session {self.session!r}"
            )

        tool_name = action if action.startswith("browser_") else f"browser_{action}"
        return self._object(self._command(tool_name, mapped, timeout), tool_name)

    def health(self, timeout: int | None = None) -> dict[str, Any]:
        timeout = timeout or self.timeout
        request = urllib.request.Request(f"{self.daemon_url}/health")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"OpenBridge health check failed at {self.daemon_url}: {exc}") from exc
        return self._object(result, "health")

    def _select_session_tab(self, timeout: int) -> bool:
        data = self._command(
            "browser_find_tab",
            {"sessionId": self.session, "activate": False},
            timeout,
        )
        tabs = data.get("tabs", []) if isinstance(data, dict) else []
        if not tabs:
            return False
        self._command(
            "browser_select_tab",
            {"tabId": tabs[0]["tabId"], "sessionId": self.session},
            timeout,
        )
        return True

    def _evaluate(
        self,
        expression: str,
        args: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
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
        state = self._run_evaluate(evaluate_args, timeout)
        deadline = time.monotonic() + timeout

        while state.get("state") == "pending":
            if time.monotonic() >= deadline:
                raise RuntimeError("OpenBridge timed out waiting for asynchronous JavaScript")
            time.sleep(0.05)
            poll_args = dict(args)
            poll_args["expression"] = f"""(() => {{
  const __key = {json.dumps(key)};
  const __value = globalThis[__key];
  if (!__value) return {{state: "rejected", message: "async evaluation state was lost"}};
  if (__value.state !== "pending") delete globalThis[__key];
  return __value;
}})()"""
            state = self._run_evaluate(poll_args, timeout)

        if state.get("state") == "rejected":
            raise RuntimeError(
                f"OpenBridge JavaScript evaluation failed: {state.get('message', 'unknown error')}"
            )
        if state.get("state") != "fulfilled":
            raise RuntimeError(f"OpenBridge returned unknown evaluate state: {state!r}")
        return {"type": state.get("type"), "value": state.get("value")}

    def _run_evaluate(self, args: dict[str, Any], timeout: int) -> dict[str, Any]:
        data = self._command("browser_evaluate", args, timeout)
        if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
            raise RuntimeError(f"Unexpected OpenBridge browser_evaluate response: {data!r}")
        return data["result"]

    def _command(self, tool_name: str, args: dict[str, Any], timeout: int) -> Any:
        body = json.dumps(
            {"toolName": tool_name, "args": args},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.daemon_url}/command",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(self._format_error(tool_name, raw, exc.code)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenBridge daemon unreachable at {self.daemon_url}: {exc}") from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenBridge returned non-JSON: {raw[:1000]}") from exc
        if not isinstance(envelope, dict):
            raise RuntimeError(f"OpenBridge response is not an object: {envelope!r}")
        if envelope.get("error"):
            raise RuntimeError(self._format_error(tool_name, raw, None))
        return envelope.get("data")

    @staticmethod
    def _format_error(tool_name: str, raw: str, status: int | None) -> str:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return f"OpenBridge {tool_name} failed with HTTP {status}: {raw[:1000]}"
        error = envelope.get("error") if isinstance(envelope, dict) else None
        if isinstance(error, dict):
            code = error.get("code") or "OPENBRIDGE_ERROR"
            message = error.get("message") or f"{tool_name} failed"
            return f"{code}: {message}"
        return f"OpenBridge {tool_name} failed with HTTP {status}: {envelope!r}"

    @staticmethod
    def _object(value: Any, tool_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuntimeError(f"OpenBridge {tool_name} response is not an object: {value!r}")
        return value
