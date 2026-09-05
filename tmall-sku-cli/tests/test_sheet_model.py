import pytest

from tmall_sku_cli.sheet_model import (
    DEFAULT_HEADERS,
    ProductResult,
    SheetConfig,
    SkuEntry,
    build_output_row,
    build_write_block,
    extract_product_rows,
    merge_copy_data,
)


@pytest.mark.unit
def test_extract_product_rows_from_column_g() -> None:
    values = [
        [""],
        [""],
        [""],
        [""],
        [""],
        [""],
        ["", "", "", "", "", "", "link"],
        ["", "", "", "", "慕安娜", "蜂巢帘", "https://detail.tmall.com/item.htm?id=1"],
        ["", "", "", "", "", "", ""],
        ["", "", "", "", "", "铝百叶", [{"link": "https://detail.tmall.com/item.htm?id=2"}]],
    ]
    rows = extract_product_rows(values, SheetConfig())
    assert [row.row_number for row in rows] == [8, 10]
    assert rows[1].url.endswith("id=2")


@pytest.mark.unit
def test_build_output_row_ok() -> None:
    result = ProductResult(
        row_number=8,
        url="https://detail.tmall.com/item.htm?id=1",
        status="ok",
        entries=(
            SkuEntry("sku1", "颜色分类:白色", "90.99", "129.99"),
            SkuEntry("sku2", "颜色分类:黑色", "108.99", "149.99"),
        ),
    )
    row = build_output_row(result)
    assert "白色｜¥90.99｜原¥129.99｜SKU:sku1" in row[0]
    assert row[1] == "¥90.99-¥108.99"
    assert row[2] == "2"
    assert row[3] == "已抓取"


@pytest.mark.unit
def test_build_write_block_keeps_sparse_rows() -> None:
    result = ProductResult(
        row_number=10,
        url="https://detail.tmall.com/item.htm?id=1",
        status="error",
        error_message="blocked",
    )
    range_name, values = build_write_block([result], SheetConfig())
    assert range_name == "H7:K10"
    assert values[0] == DEFAULT_HEADERS
    assert values[1] == ["", "", "", ""]
    assert values[3] == ["", "", "0", "失败：blocked"]


@pytest.mark.unit
def test_merge_copy_data_adds_headers_and_result() -> None:
    source = [[""] * 7 for _ in range(8)]
    result = ProductResult(
        row_number=8,
        url="https://detail.tmall.com/item.htm?id=1",
        status="ok",
        entries=(SkuEntry("sku1", "颜色分类:白色", "90.99"),),
    )
    merged = merge_copy_data(source, [result], SheetConfig())
    assert merged[6][7:11] == DEFAULT_HEADERS
    assert merged[7][9] == "1"
