# taobao-cli

在你**真实已登录的 Chrome** 里搜索淘宝，应用 `包邮 + 48小时内发` 筛选，按价格/销量过滤，翻页抓取，导出 CSV。

底层经 [OpenBridge](https://github.com/60ke/openBridge) 驱动浏览器。商品**标题与链接取自 zzb 插件「复制」按钮的原文**（不做标题抓取）；价格/销量从商品卡读取，仅用于过滤。

## 前置依赖

1. **OpenBridge** 已运行、浏览器扩展已连接：
   ```bash
   curl -s http://127.0.0.1:10088/health   # ok:true，且 connectedSessions 非空
   ```
2. Chrome 里**已登录淘宝**，并安装了 **zzb 插件**（结果页注入「复制 / 筛选导出」工具栏）。

## 构建 & 安装

```bash
cd ~/xx-cli/taobao-cli
go build -o taobao-cli .
ln -sf "$PWD/taobao-cli" ~/.local/bin/taobao-cli   # 让命令全局可用
```

## 使用

直接运行 `search`，依次回答 6 项即可：

```bash
taobao-cli search
# 1) 关键字: 有机核桃仁
# 2) 只看包邮？(Y/n): y
# 3) 只看48小时内发？(Y/n): y
# 4) 过滤价格（最小金额，单位元）: 5
# 5) 过滤销量（最小销量/人付款）: 10
# 6) 翻页数量（抓取几页）: 5
```

也可用 flag 跳过交互（适合脚本）：

```bash
taobao-cli search --keyword "有机核桃仁" --baoyou --ship48 --min-price 5 --min-sales 10 --pages 5
# 关掉某个物流筛选：--baoyou=false 或 --ship48=false
```

| flag | 含义 | 默认 |
|---|---|---|
| `--keyword` | 搜索关键字 | 交互询问 |
| `--baoyou` | 只看包邮（`=false` 关闭） | 是 |
| `--ship48` | 只看48小时内发（`=false` 关闭） | 是 |
| `--min-price` | 最小金额过滤 | 交互询问 |
| `--min-sales` | 最小销量过滤 | 交互询问 |
| `--pages` | 翻页数量 | 交互询问 |

> 包邮 / 48小时内发都可开可关。除了页面级筛选，每行还会按商品卡自带的包邮/48h角标**二次校验**，所以即使页面筛选偶发失效，结果也准确。

## 输出

- **stdout**：JSON 信封 `{"ok":true,"data":{...}}`，含 `items`、`kept`、`csv_path`、`filter_baoyou_48h_applied` 等。
- **CSV 文件**：写到 `~/`，文件名形如 `有机核桃仁_包邮48h_价格5_销量10_5页.csv`（UTF-8 BOM，Excel/WPS 直接打开）。列：`页码 / 标题(插件复制原文) / 价格 / 销量 / 宝贝ID / 链接`。
- **stderr**：进度提示与告警（如筛选未生效）。

失败时输出 `{"ok":false,"error":{...}}` 并以非零码退出。

## 工作原理（简述）

1. 打开 `s.taobao.com/search?q=<关键字>`。
2. 点 `包邮` chip + 全部筛选面板里的 `48小时内发`；用**总页数从 100 降下来**校验是否生效，不生效则**整页重载重试**（避免重复点击把已选 chip 又 toggle 关掉）。
3. 每页：滚动加载 → hook 住剪贴板写入 → 全选 → 点插件「复制」→ 读取 `window.__cap` 拿到插件复制原文 → 按宝贝ID匹配卡片的价格/销量做过滤 → 点「下一页」。
4. 跨页去重，写 CSV。

选择器全部用**稳定身份**（精确文本 / class / aria-label），不依赖坐标。元素定位细节见 [ARCHAEOLOGY.md](./ARCHAEOLOGY.md)。
