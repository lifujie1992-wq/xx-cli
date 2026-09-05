from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .lark_cli import LarkCli
from .output import CliError


@dataclass(frozen=True)
class FeishuTarget:
    original_url: str
    spreadsheet_token: str
    source_type: str
    wiki_token: str | None = None


_WIKI_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")
_SHEET_RE = re.compile(r"/sheets/([A-Za-z0-9]+)")


def parse_feishu_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if not parsed.netloc.endswith("feishu.cn"):
        raise CliError("invalid_feishu_url", "URL is not a feishu.cn link", {"url": url})
    wiki_match = _WIKI_RE.search(parsed.path)
    if wiki_match:
        return "wiki", wiki_match.group(1)
    sheet_match = _SHEET_RE.search(parsed.path)
    if sheet_match:
        return "sheet", sheet_match.group(1)
    raise CliError(
        "invalid_feishu_url", "Only Feishu wiki and sheet URLs are supported", {"url": url}
    )


def resolve_target(url: str, lark: LarkCli) -> FeishuTarget:
    source_type, token = parse_feishu_url(url)
    if source_type == "sheet":
        return FeishuTarget(original_url=url, spreadsheet_token=token, source_type="sheet")

    node_response = lark.resolve_wiki_node(token)
    node = (node_response.get("data") or {}).get("node") or {}
    obj_type = node.get("obj_type")
    obj_token = node.get("obj_token")
    if obj_type != "sheet" or not isinstance(obj_token, str) or not obj_token:
        raise CliError(
            "wiki_node_not_sheet",
            "The Feishu wiki URL does not point to a spreadsheet",
            {"obj_type": obj_type, "node": node},
        )
    return FeishuTarget(
        original_url=url,
        spreadsheet_token=obj_token,
        source_type="wiki",
        wiki_token=token,
    )
