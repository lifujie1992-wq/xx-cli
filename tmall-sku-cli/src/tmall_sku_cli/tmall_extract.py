from __future__ import annotations

import time
from typing import Any

from .output import CliError, progress
from .sheet_model import ProductResult, SkuEntry
from .webbridge import WebBridgeClient

EXTRACT_JS = r"""
(() => {
  const res = window.__ICE_APP_CONTEXT__?.loaderData?.home?.data?.res;
  const bodyText = document.body?.innerText || "";
  if (location.href.includes("login.taobao.com") || bodyText.includes("密码登录短信登录")) {
    return JSON.stringify({ok:false, code:"tmall_login_required", message:"淘宝/天猫需要登录", url:location.href, title:document.title});
  }
  if (bodyText.includes("验证") && (bodyText.includes("滑块") || bodyText.includes("验证码") || bodyText.includes("安全"))) {
    return JSON.stringify({ok:false, code:"tmall_captcha_required", message:"页面需要安全验证", url:location.href, title:document.title});
  }
  if (!res?.skuBase || !res?.skuCore) {
    return JSON.stringify({ok:false, code:"tmall_sku_context_missing", message:"SKU context missing", url:location.href, title:document.title, text:bodyText.slice(0,500)});
  }

  const props = res.skuBase.props || [];
  const skus = res.skuBase.skus || [];
  const sku2info = res.skuCore.sku2info || {};
  const propNames = {};
  const valueNames = {};

  for (const prop of props) {
    propNames[String(prop.pid)] = prop.name || "";
    for (const value of (prop.values || [])) {
      valueNames[String(prop.pid) + ":" + String(value.vid)] = value.name || "";
    }
  }

  const entries = skus.map((sku) => {
    const propPath = String(sku.propPath || "");
    const info = sku2info[String(sku.skuId)] || sku2info[propPath] || {};
    const spec = propPath.split(";").filter(Boolean).map((key) => {
      const pid = key.split(":")[0];
      const prop = propNames[pid] || "";
      const value = valueNames[key] || key;
      return prop ? `${prop}:${value}` : value;
    }).join(" / ");
    return {
      sku_id: String(sku.skuId || ""),
      prop_path: propPath,
      spec,
      price: info.subPrice?.priceText || info.price?.priceText || "",
      original_price: info.price?.priceText || "",
      stock: info.quantity ?? null,
      quantity_text: info.quantityText || ""
    };
  });

  return JSON.stringify({
    ok: true,
    url: location.href,
    title: res.item?.title || document.title,
    item_id: res.item?.itemId || "",
    sku_count: entries.length,
    entries
  });
})()
"""


def extract_product(
    client: WebBridgeClient,
    row_number: int,
    url: str,
    new_tab: bool = False,
    poll_seconds: int = 24,
) -> ProductResult:
    progress(f"[{row_number}] opening {url}")
    try:
        client.navigate(url, new_tab=new_tab)
    except CliError as exc:
        return ProductResult(
            row_number=row_number,
            url=url,
            status="error",
            error_code=exc.code,
            error_message=exc.message,
        )

    deadline = time.monotonic() + poll_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            payload = client.evaluate_json(EXTRACT_JS)
        except CliError as exc:
            last_payload = {"ok": False, "code": exc.code, "message": exc.message}
            time.sleep(1)
            continue
        last_payload = payload
        if payload.get("ok"):
            result = _payload_to_result(row_number, url, payload)
            progress(f"[{row_number}] extracted {len(result.entries)} SKUs")
            return result
        code = str(payload.get("code") or "")
        if code in {"tmall_login_required", "tmall_captcha_required"}:
            break
        time.sleep(1)

    payload = last_payload or {
        "code": "tmall_extract_timeout",
        "message": "Timed out waiting for SKU data",
    }
    return ProductResult(
        row_number=row_number,
        url=url,
        status="error",
        title=str(payload.get("title") or ""),
        error_code=str(payload.get("code") or "tmall_extract_failed"),
        error_message=str(
            payload.get("message") or payload.get("text") or "Failed to extract SKU data"
        ),
    )


def _payload_to_result(row_number: int, source_url: str, payload: dict[str, Any]) -> ProductResult:
    entries = tuple(_entry_from_payload(entry) for entry in payload.get("entries", []))
    return ProductResult(
        row_number=row_number,
        url=source_url,
        status="ok",
        title=str(payload.get("title") or ""),
        item_id=str(payload.get("item_id") or ""),
        entries=entries,
    )


def _entry_from_payload(entry: dict[str, Any]) -> SkuEntry:
    stock = entry.get("stock")
    return SkuEntry(
        sku_id=str(entry.get("sku_id") or ""),
        spec=str(entry.get("spec") or ""),
        price=str(entry.get("price") or ""),
        original_price=str(entry.get("original_price") or ""),
        stock=stock if isinstance(stock, int) else None,
        quantity_text=str(entry.get("quantity_text") or ""),
    )
