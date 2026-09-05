import pytest

from tmall_sku_cli.sheet_model import ProductResult, SkuEntry, build_output_row
from tmall_sku_cli.tmall_extract import _payload_to_result


@pytest.mark.unit
def test_payload_to_result() -> None:
    payload = {
        "ok": True,
        "title": "商品",
        "item_id": "123",
        "entries": [
            {
                "sku_id": "sku1",
                "spec": "颜色分类:白色 / 尺寸:平方米",
                "price": "90.99",
                "original_price": "129.99",
                "stock": 200,
                "quantity_text": "有货",
            }
        ],
    }
    result = _payload_to_result(8, "https://detail.tmall.com/item.htm?id=123", payload)
    assert result.ok
    assert result.title == "商品"
    assert result.entries[0].stock == 200


@pytest.mark.unit
def test_error_output_row() -> None:
    result = ProductResult(
        row_number=8,
        url="https://detail.tmall.com/item.htm?id=123",
        status="error",
        error_message="需要登录",
    )
    assert build_output_row(result) == ["", "", "0", "失败：需要登录"]


@pytest.mark.unit
def test_missing_original_price() -> None:
    result = ProductResult(
        row_number=8,
        url="https://detail.tmall.com/item.htm?id=123",
        status="ok",
        entries=(SkuEntry("sku1", "颜色分类:白色", "90.99"),),
    )
    row = build_output_row(result)
    assert row[0] == "白色｜¥90.99｜SKU:sku1"
