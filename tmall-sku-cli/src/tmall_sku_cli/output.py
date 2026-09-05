from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CliError(Exception):
    code: str
    message: str
    details: Any | None = None


def success(data: Any) -> int:
    _write_json({"ok": True, "data": data})
    return 0


def failure(code: str, message: str, details: Any | None = None) -> int:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    _write_json({"ok": False, "error": error})
    return 1


def progress(message: str) -> None:
    print(message, file=sys.stderr)


def _write_json(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
