from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_HEADERS = ["SKU价格明细", "价格区间", "SKU数量", "抓取状态"]
TMALL_URL_RE = re.compile(r"https?://[^\s)\]\"'，。；;]+(?:tmall|taobao)[^\s)\]\"'，。；;]*")


@dataclass(frozen=True)
class ProductRow:
    row_number: int
    url: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SheetConfig:
    url_col: str = "G"
    header_row: int = 7
    start_row: int = 8
    max_row: int = 500

    @property
    def url_index(self) -> int:
        return column_to_index(self.url_col)


@dataclass(frozen=True)
class SkuEntry:
    sku_id: str
    spec: str
    price: str
    original_price: str = ""
    stock: int | None = None
    quantity_text: str = ""


@dataclass(frozen=True)
class ProductResult:
    row_number: int
    url: str
    status: str
    title: str = ""
    item_id: str = ""
    entries: tuple[SkuEntry, ...] = ()
    error_code: str = ""
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_json(self) -> dict[str, Any]:
        return {
            "row": self.row_number,
            "url": self.url,
            "status": self.status,
            "title": self.title,
            "item_id": self.item_id,
            "sku_count": len(self.entries),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "skus": [
                {
                    "sku_id": entry.sku_id,
                    "spec": entry.spec,
                    "price": entry.price,
                    "original_price": entry.original_price,
                    "stock": entry.stock,
                    "quantity_text": entry.quantity_text,
                }
                for entry in self.entries
            ],
        }


def column_to_index(column: str) -> int:
    value = 0
    for char in column.strip().upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"invalid column: {column}")
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("link") or item.get("text") or ""))
            else:
                parts.append(normalize_cell(item))
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or value.get("value") or "").strip()
    return str(value).strip()


def extract_url(value: Any) -> str | None:
    text = normalize_cell(value)
    match = TMALL_URL_RE.search(text)
    return match.group(0) if match else None


def extract_product_rows(values: list[list[Any]], config: SheetConfig) -> list[ProductRow]:
    rows: list[ProductRow] = []
    for index, row in enumerate(values, start=1):
        if index < config.start_row:
            continue
        if config.url_index >= len(row):
            continue
        url = extract_url(row[config.url_index])
        if url:
            rows.append(ProductRow(row_number=index, url=url, values=tuple(row)))
    return rows


def build_output_row(result: ProductResult) -> list[str]:
    if not result.ok:
        message = result.error_message or result.error_code or "unknown"
        return ["", "", "0", f"失败：{message}"]

    lines: list[str] = []
    prices: list[float] = []
    for entry in result.entries:
        price = entry.price
        if price:
            try:
                prices.append(float(price.replace("起", "")))
            except ValueError:
                pass
        spec = entry.spec.replace("颜色分类:", "")
        if entry.original_price and entry.original_price != entry.price:
            lines.append(f"{spec}｜¥{entry.price}｜原¥{entry.original_price}｜SKU:{entry.sku_id}")
        else:
            lines.append(f"{spec}｜¥{entry.price}｜SKU:{entry.sku_id}")
    price_range = f"¥{min(prices):g}-¥{max(prices):g}" if prices else ""
    return ["\n".join(lines), price_range, str(len(result.entries)), "已抓取"]


def build_write_block(
    results: list[ProductResult], config: SheetConfig
) -> tuple[str, list[list[str]]]:
    by_row = {result.row_number: result for result in results}
    last_row = max([config.header_row, *by_row.keys()], default=config.header_row)
    values: list[list[str]] = [DEFAULT_HEADERS]
    for row_number in range(config.header_row + 1, last_row + 1):
        result = by_row.get(row_number)
        values.append(build_output_row(result) if result else ["", "", "", ""])
    return f"H{config.header_row}:K{last_row}", values


def merge_copy_data(
    source_values: list[list[Any]],
    results: list[ProductResult],
    config: SheetConfig,
) -> list[list[Any]]:
    by_row = {result.row_number: result for result in results}
    last_row = max(config.header_row, len(source_values), *(by_row.keys() or [config.header_row]))
    merged: list[list[Any]] = []
    for row_number in range(1, last_row + 1):
        source_row = list(source_values[row_number - 1]) if row_number <= len(source_values) else []
        padded = [normalize_cell(value) for value in source_row[:11]]
        while len(padded) < 11:
            padded.append("")
        if row_number == config.header_row:
            padded[7:11] = DEFAULT_HEADERS
        elif row_number in by_row:
            padded[7:11] = build_output_row(by_row[row_number])
        merged.append(padded)
    return merged
