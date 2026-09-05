# woda-aftersale-cli

我打抖音售后 CLI，基于 OpenBridge 操作真实 Chrome 登录态。

目标页面：
https://douyins.woda.com/#/AfterSaleTrades

## 功能

- `open`：打开我打抖音售后页
- `refund-only` / `only-refund` / `list`：读取页面里当前可见的“仅退款”售后订单

注意：当前 CLI 只读订单，不会点击“同意仅退款 / 拒绝仅退款”等高风险操作。

## 前置条件

1. Chrome 已安装并连接 OpenBridge 插件
2. 本机 daemon 正常：

```bash
curl -s http://127.0.0.1:10088/health
```

需要看到：

```json
{"ok":true,"connectedSessions":["<extension-session-id>"],"enabledTools":["browser_evaluate"]}
```

3. Chrome 里已登录 `douyins.woda.com`

## 构建

```bash
cd ~/xx-cli/woda-aftersale-cli
go mod tidy
go build -o ./woda-aftersale-cli .
```

## 使用

打开售后页：

```bash
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli open
```

查看“仅退款”订单：

```bash
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only
```

导出“仅退款”订单：

```bash
# 默认导出到 ~/Downloads/woda_refund_only_<timestamp>.csv
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --export csv

# 指定导出路径
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --export csv --out ~/Downloads/refund_only.csv

# 也支持 json / md
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --export json
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --export md
```

限制数量：

```bash
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --limit 10
```

不重新跳转页面，直接读取当前活动 tab：

```bash
~/xx-cli/woda-aftersale-cli/woda-aftersale-cli refund-only --no-navigate
```

## 输出格式

成功：

```json
{
  "ok": true,
  "data": {
    "page_title": "我打-抖音-批量打印发货-全新版",
    "url": "https://douyins.woda.com/#/AfterSaleTrades",
    "expected_tab_count": 2,
    "visible_refund_count": 2,
    "orders": [
      {
        "shop": "示例店铺",
        "aftersale_id": "100000000000000001",
        "order_id": "6000000000000000000",
        "amount": "114.76",
        "aftersale_type": "仅退款",
        "aftersale_status": "买家已申请售后",
        "reason": "其他",
        "shipping_logistics": "极兔速递 JT0000000000000",
        "available_actions": ["同意仅退款", "拒绝仅退款", "日志"]
      }
    ]
  }
}
```

失败会输出：

```json
{"ok": false, "error": {"code": "...", "message": "..."}}
```

## 项目结构

```text
woda-aftersale-cli/
├── main.go
├── browser/client.go
├── cmd/root.go
├── cmd/refund_only.go
├── output/output.go
├── woda/refund_only.go
├── go.mod
└── README.md
```
