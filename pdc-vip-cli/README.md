# pdc-vip-cli

唯品会供应商平台 **PDC 创建商品** 的只读 CLI。在你已登录的真实 Chrome 里（经 [OpenBridge](https://github.com/60ke/openBridge) 守护进程 `http://127.0.0.1:10088`）以 `fetch` 复用登录 cookie 读取分类与商品数据，不走 API token。

接口与「创建商品」完整提交体的逆向记录见 [`ARCHAEOLOGY.md`](./ARCHAEOLOGY.md)。

## 前置

1. 跑着 OpenBridge，且 Chrome 里已登录 <https://vis.vip.com>（供应商平台）。
2. Go 1.25+。

## 构建

```bash
go build -o pdc-cli .
```

## 命令

```bash
pdc-cli login-status              # 确认登录态 + 当前商家(user/vendorCode)
pdc-cli categories                # 商品分类树 JSON（默认剔除停用项）
pdc-cli categories --tree         # 缩进树形 + categoryId
pdc-cli categories --all          # 含停用(status=1)类目
pdc-cli config <categoryId>       # 叶子类目配置开关(是否需尺码表/美妆/大件…)
pdc-cli get <vendorProductId>     # 读一个完整商品(~47 字段，创建提交体样板)
pdc-cli create -f <productVo.json>          # 提交商品草稿（默认 dry-run）
pdc-cli create -f <productVo.json> --commit # 真正写库
pdc-cli upload-image <本地图>...            # 本地图传唯品图床，返回 URL（无需第三方图床）
```

### create（写入）

`create` 提交一份完整的 `productVo` JSON（字段结构见 `DATA-PACKAGE-FORMAT.md`，可先用 `pdc-cli get <vpId>` 读一个已有商品当模板）：

- **默认 dry-run**：打印将提交的商品摘要 + 跑非破坏的 SKU 预检（`/product/saveProduct?editPreCheck`），**不写库**。
- 加 `--commit` 才真正 `POST /product/saveProductV2`（form-urlencoded）保存草稿。
- 若后端返回 **501 内容警告**（旧→新属性迁移、违规词等），首次保存不落库并列出警告；处理掉、或加 `--confirm-tips`（等同 UI「已知悉，确定修改」）确认忽略后强制保存。

```bash
# 1. 拿一个已有商品当模板
pdc-cli get 1900000000000000001 > tpl.json
# 2. 改 productVo：清空 vendorProductId、换新 sn / colourGSN / barCode、
#    把 descProps 转成 specProps（{attributeId,attributeName,dataType,multiValue,values}）、
#    清空每个 SKU 的 vendorSkuId/sizeDetailId（服务端分配）
# 3. dry-run 验证
pdc-cli create -f tpl.json
# 4. 确认后写库
pdc-cli create -f tpl.json --commit
```

> ⚠️ `sn`/`colourGSN`/`barCode` 是商家唯一码，新品必须用未占用的新值；`vendorProductId` 非空会**更新**该商品而非新建。

示例：

```bash
$ pdc-cli categories --tree | head
311      女装
  312      女上装
    314      女式T恤
    ...

$ pdc-cli get 1900000000000000001 | jq '{title, categoryId, sn, attrs: (.descProps|length)}'
{ "title": "设计感…上衣", "categoryId": 314, "sn": "DEMOSN001", "attrs": 19 }
```

## 设计

- `browser/client.go` —— OpenBridge 守护进程的薄客户端（与 taobao-cli 同款）。
- `pdc/api.go` —— 所有调用都封装成页面内 `fetch`，自动把标签页停在 `pdc-portal.vip.com` 同源下以继承登录态。
- 输出统一 JSON 到 stdout，人类可读提示走 stderr。

## 已知边界 / 下一步

- **属性可选项全集**（面料/版型… 的所有可选 optionId）来自第二后端 `mp-product.vip.com/api/vc/productCategory/getCategoryAttribute`，其 body 形状尚未试通（见 ARCHAEOLOGY 末尾），故暂未做 `attrs` 命令。当前可用 `get <vpId>` 从已有商品的 `descProps` 反查已选项。
- `create --commit --confirm-tips` 的真实写库路径**已端到端实测通过**（对一件 status=11 草稿原样重存，返回 `result:true` + SKU 映射）。尚未验证的是**全新商品**（清空 vendorProductId + 全新 sn/barCode）的首次创建。
- 还缺一个把 `get` 输出自动转成 create-ready `productVo`（清 ID + descProps→specProps）的 `template` 命令，目前这步要手工改。
