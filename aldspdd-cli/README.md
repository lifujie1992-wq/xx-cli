# aldspdd-cli

接管已登录的 `aldspdd.agiso.com`（阿奇索·拼多多自动发货）商品页，通过 [OpenBridge](https://github.com/60ke/openBridge) 复用真实 Chrome 登录态，不走 API key。

**核心用途**：批量体检每个在售商品绑定的「货源编号」是否还搜得到。手工流程是「在售列表 → 编辑 → 修改 → 关联商品对话框 → 点搜索」，搜不到就说明该编号对应的货源被删/下架了，拍下会发不出货。本 CLI 自动扫全店。

## 用法

```bash
go build -o aldspdd-cli .

# 1. 确认接管到已登录的标签页
./aldspdd-cli login-status

# 2. 列出在售商品
./aldspdd-cli goods

# 3. 全店体检失效货源（进度走 stderr，JSON 走 stdout）
./aldspdd-cli check-supply > scan.json
./aldspdd-cli check-supply --limit 5   # 只扫前 5 个，快速验证
```

## 输出

```json
{
  "ok": true,
  "data": {
    "totalGoods": 37, "scannedGoods": 37, "checkedNo": 271,
    "deadCount": 104, "deadGoods": 23,
    "dead": [
      { "goodsId": "963894978530", "goodsName": "...", "price": "21.19",
        "deadEntries": [
          { "sku": "【早餐-两件套】...", "skuId": "1913880615213",
            "acc": 59665, "no": "36551", "spType": 6,
            "status": "dead_empty", "found": 0 }
        ] }
    ]
  }
}
```

- `no`：失效的货源编号（关联商品对话框里预填、搜不到的那个）
- `status`：`dead_empty`（搜索为空）/ `dead_mismatch`（搜到别的、无此编号）
- 只校验 `spType==6`（自有货源）的条目，卡密/全店统一发货记 `skip`

## 依赖

- OpenBridge 守护进程在跑（`curl -s http://127.0.0.1:10088/health`）
- 用户已在 Chrome 登录 aldspdd.agiso.com 并打开商品页

## 底层接口

| 用途 | 接口 |
|---|---|
| 商品列表 | `GET /api/UnAldsInfo/LoadAldsGoodsList?pageSize=50&page=N` |
| SKU 列表 | `GET /api/AldsInfo/GetAldsSkuList/{goodsId}` |
| SKU 货源详情 | `GET /api/AldsInfo/GetSkuAldsInfo/{goodsId}/{skuId}` → `supplierAccountId` / `supplierProductNo` / `spType` |
| 整体货源详情 | `GET /api/AldsInfo/GetGoodsAldsInfo/{goodsId}` |
| 货源搜索（判活） | `POST /api/AcprSerivces/GetSupplierProductList` body `{idNo, keyword, pageIndex, pageSize}` |

全部带 `Authorization: Bearer <localStorage.TOKEN>` + `credentials:include`，由浏览器内 `evaluate` 执行。

> 注意：OpenBridge 的 `evaluate` 共享全局作用域，页面侧 JS 不能用顶层 `const`/`return`，必须包在 async IIFE 内（见 `aldspdd/api.go` 的 `wrapJS`）。
