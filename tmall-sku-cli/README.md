# tmall-sku-cli

从飞书表格读取天猫商品链接，使用 OpenBridge 接管真实浏览器访问商品页，提取 SKU 和价格，并写回飞书表格。原表只读时会自动创建可编辑副本。

## Requirements

- `lark-cli` 已登录并可访问目标飞书文档
- OpenBridge daemon 已运行，浏览器扩展已连接
- 浏览器里已登录淘宝/天猫

检查环境：

```bash
tmall-sku-cli status
```

## Usage

只抓取并输出 JSON，不写表：

```bash
tmall-sku-cli extract --url "https://example.feishu.cn/wiki/REPLACE_WITH_WIKI_TOKEN"
```

抓取并写回。原表可编辑时写原表，只读时创建副本：

```bash
tmall-sku-cli run --url "https://example.feishu.cn/wiki/REPLACE_WITH_WIKI_TOKEN"
```

## Defaults

- 商品链接列：`G`
- 表头行：`7`
- 数据起始行：`8`
- 输出列：`H:K`
  - `SKU价格明细`
  - `价格区间`
  - `SKU数量`
  - `抓取状态`

可通过参数覆盖：

```bash
tmall-sku-cli run --url "..." --url-col G --header-row 7 --start-row 8 --max-row 500
```

## Install

```bash
cd ~/xx-cli/tmall-sku-cli
python3 -m pip install -e .
```
