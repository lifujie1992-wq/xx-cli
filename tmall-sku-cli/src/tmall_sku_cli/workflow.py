from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .feishu_url import FeishuTarget, resolve_target
from .lark_cli import LarkCli, LarkCommandError
from .output import CliError, progress
from .sheet_model import (
    ProductResult,
    SheetConfig,
    build_write_block,
    extract_product_rows,
    merge_copy_data,
)
from .tmall_extract import extract_product
from .webbridge import WebBridgeClient


@dataclass(frozen=True)
class SheetContext:
    target: FeishuTarget
    title: str
    sheet_id: str
    values: list[list[Any]]


def status(lark: LarkCli, webbridge: WebBridgeClient) -> dict[str, Any]:
    lark_status = lark.check_available()
    webbridge_status = webbridge.require_ready()
    return {
        "openbridge": webbridge_status,
        "lark_cli": lark_status,
        "defaults": {
            "url_column": "G",
            "header_row": 7,
            "data_start_row": 8,
            "output_columns": "H:K",
            "session": webbridge.session,
        },
    }


def run_extract(
    url: str,
    config: SheetConfig,
    lark: LarkCli,
    webbridge: WebBridgeClient,
) -> dict[str, Any]:
    webbridge.require_ready()
    context = load_sheet_context(url, config, lark)
    products = extract_product_rows(context.values, config)
    if not products:
        return {
            "spreadsheet_token": context.target.spreadsheet_token,
            "sheet_id": context.sheet_id,
            "title": context.title,
            "source": _source_summary(config, len(context.values), []),
            "products": [],
            "errors": [],
        }

    results: list[ProductResult] = []
    for index, product in enumerate(products):
        results.append(
            extract_product(
                webbridge,
                product.row_number,
                product.url,
                new_tab=index == 0,
            )
        )
    return {
        "spreadsheet_token": context.target.spreadsheet_token,
        "sheet_id": context.sheet_id,
        "title": context.title,
        "source": _source_summary(config, len(context.values), [p.row_number for p in products]),
        "products": [result.to_json() for result in results],
        "errors": [result.to_json() for result in results if not result.ok],
    }


def run_write(
    url: str,
    config: SheetConfig,
    lark: LarkCli,
    webbridge: WebBridgeClient,
    force_copy: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    webbridge.require_ready()
    context = load_sheet_context(url, config, lark)
    products = extract_product_rows(context.values, config)
    results = [
        extract_product(webbridge, product.row_number, product.url, new_tab=index == 0)
        for index, product in enumerate(products)
    ]
    range_suffix, write_values = build_write_block(results, config)
    full_range = f"{context.sheet_id}!{range_suffix}"
    base = {
        "spreadsheet_token": context.target.spreadsheet_token,
        "sheet_id": context.sheet_id,
        "title": context.title,
        "source": _source_summary(config, len(context.values), [p.row_number for p in products]),
        "products_processed": len(results),
        "errors": [result.to_json() for result in results if not result.ok],
    }
    if dry_run:
        return {
            **base,
            "write_mode": "dry_run",
            "planned_range": full_range,
            "planned_values": write_values,
        }

    if not force_copy:
        try:
            write_response = lark.write_range(
                context.target.spreadsheet_token,
                full_range,
                write_values,
            )
            return {**base, "write_mode": "original", "write_response": write_response}
        except LarkCommandError as exc:
            if not exc.is_forbidden:
                raise CliError(
                    "sheet_write_failed",
                    "Failed to write original sheet",
                    {"stdout": exc.stdout, "stderr": exc.stderr, "returncode": exc.returncode},
                ) from exc
            progress("Original sheet is read-only; creating a copy")
            forbidden_details = {
                "stdout": exc.stdout,
                "stderr": exc.stderr,
                "returncode": exc.returncode,
            }
    else:
        forbidden_details = {"forced": True}

    copy_data = merge_copy_data(context.values, results, config)
    copy_title = f"{context.title}-SKU价格副本-{datetime.now().strftime('%Y%m%d-%H%M')}"
    copy_response = lark.create_sheet(copy_title, copy_data)
    return {
        **base,
        "write_mode": "created_copy",
        "original_write_error": forbidden_details,
        "copy": _copy_summary(copy_response),
        "create_response": copy_response,
    }


def load_sheet_context(url: str, config: SheetConfig, lark: LarkCli) -> SheetContext:
    target = resolve_target(url, lark)
    info = lark.sheet_info(target.spreadsheet_token)
    spreadsheet = ((info.get("data") or {}).get("spreadsheet") or {}).get("spreadsheet") or {}
    title = str(spreadsheet.get("title") or "Tmall SKU Result")
    sheets = ((info.get("data") or {}).get("sheets") or {}).get("sheets") or []
    if not sheets:
        raise CliError("sheet_id_not_found", "No sheets found in spreadsheet", info)
    sheet_id = str(sheets[0].get("sheet_id") or "")
    if not sheet_id:
        raise CliError("sheet_id_not_found", "First sheet has no sheet_id", sheets[0])
    range_name = f"{sheet_id}!A1:K{config.max_row}"
    read_response = lark.read_range(target.spreadsheet_token, range_name)
    values = (((read_response.get("data") or {}).get("valueRange") or {}).get("values")) or []
    if not isinstance(values, list):
        raise CliError(
            "sheet_values_invalid", "lark-cli returned invalid sheet values", read_response
        )
    return SheetContext(target=target, title=title, sheet_id=sheet_id, values=values)


def _source_summary(
    config: SheetConfig, rows_scanned: int, product_rows: list[int]
) -> dict[str, Any]:
    return {
        "url_column": config.url_col,
        "header_row": config.header_row,
        "data_start_row": config.start_row,
        "output_columns": "H:K",
        "rows_scanned": rows_scanned,
        "product_rows": product_rows,
    }


def _copy_summary(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") or {}
    return {
        "spreadsheet_token": data.get("spreadsheet_token"),
        "title": data.get("title"),
        "url": data.get("url"),
    }
