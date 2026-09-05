from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from .output import CliError


@dataclass(frozen=True)
class LarkCommandError(Exception):
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def is_forbidden(self) -> bool:
        text = f"{self.stdout}\n{self.stderr}"
        return "91403" in text or "Forbidden" in text or "forbidden" in text


@dataclass(frozen=True)
class LarkCli:
    binary: str = "lark-cli"
    timeout_seconds: int = 120

    def check_available(self) -> dict[str, Any]:
        path = shutil.which(self.binary)
        if not path:
            raise CliError("lark_cli_not_found", "lark-cli was not found on PATH")
        result = subprocess.run(
            [self.binary, "--help"],
            text=True,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        return {"path": path, "available": result.returncode == 0}

    def resolve_wiki_node(self, token: str) -> dict[str, Any]:
        return self.run_json(
            [
                "api",
                "GET",
                "/open-apis/wiki/v2/spaces/get_node",
                "--params",
                json.dumps({"token": token}, ensure_ascii=False),
            ]
        )

    def sheet_info(self, spreadsheet_token: str) -> dict[str, Any]:
        return self.run_json(["sheets", "+info", "--spreadsheet-token", spreadsheet_token])

    def read_range(self, spreadsheet_token: str, range_name: str) -> dict[str, Any]:
        return self.run_json(
            [
                "sheets",
                "+read",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                range_name,
                "--value-render-option",
                "FormattedValue",
            ]
        )

    def write_range(
        self,
        spreadsheet_token: str,
        range_name: str,
        values: list[list[Any]],
    ) -> dict[str, Any]:
        return self.run_json(
            [
                "sheets",
                "+write",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                range_name,
                "--values",
                json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            ]
        )

    def create_sheet(self, title: str, data: list[list[Any]]) -> dict[str, Any]:
        return self.run_json(
            [
                "sheets",
                "+create",
                "--title",
                title,
                "--data",
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            ]
        )

    def run_json(self, args: list[str]) -> dict[str, Any]:
        result = subprocess.run(
            [self.binary, *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        if result.returncode != 0:
            raise LarkCommandError(
                tuple([self.binary, *args]), result.returncode, result.stdout, result.stderr
            )
        payload = _extract_json(result.stdout)
        if not isinstance(payload, dict):
            raise CliError(
                "lark_cli_invalid_json", "lark-cli returned non-object JSON", result.stdout
            )
        if payload.get("ok") is False:
            raise LarkCommandError(
                tuple([self.binary, *args]),
                1,
                result.stdout,
                result.stderr,
            )
        return payload


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise CliError("lark_cli_empty_output", "lark-cli returned empty output")
    start = min([idx for idx in (stripped.find("{"), stripped.find("[")) if idx >= 0], default=-1)
    if start < 0:
        raise CliError("lark_cli_invalid_json", "lark-cli output did not contain JSON", text)
    try:
        return json.loads(stripped[start:])
    except json.JSONDecodeError as exc:
        raise CliError(
            "lark_cli_invalid_json",
            "Failed to decode lark-cli JSON output",
            {"stdout": text, "error": str(exc)},
        ) from exc
