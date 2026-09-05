# doudian-biz

抖店商机中心 CLI。通过 `OpenBridge` 复用真实 Chrome 登录态，在页面上下文里调用抖店接口，连续翻页抓取商机关键词，过滤搜索次数和明显品牌词，导出本地文件，并可通过 `feishu-cli` 写入飞书多维表格。

默认行为等同于本次手工流程：

- 推荐理由标签：`全网热卖`、`热度高`、`成交增速快`
- 搜索次数：`> 10000`
- 数量：`100`
- 剔除明显品牌词

## 前置条件

```bash
curl -s http://127.0.0.1:10088/health
feishu-cli --help
```

Chrome 里需要已登录抖店，并且能打开：

```text
https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter
```

默认会复用 `OpenBridge` 会话 `doudian-business-center` 里已经打开的商机中心标签页，避免把请求发到未登录的 Chrome 资料窗口。若需要让 CLI 自动打开页面，可显式加：

```bash
./doudian-biz keywords --require-existing-tab=false
```

## 构建

```bash
cd ~/xx-cli/doudian-business-center
go build -o doudian-biz .
```

## 抓取并导出

```bash
./doudian-biz keywords
```

输出文件会写到 `output/`：

- `doudian_keywords_*.json`
- `doudian_keywords_*.tsv`
- `doudian_keywords_*.csv`

## 页面搜索框搜索

把关键词填入商机中心页面搜索框，并用页面接口返回搜索结果：

```bash
doudian-biz search "夏季透气户外布鞋"
```

默认返回 20 条，不限制推荐理由标签，不过滤品牌词，不过滤搜索次数。常用参数：

```bash
doudian-biz search "夏季透气户外布鞋" --limit 5
doudian-biz search "夏季透气户外布鞋" --tags "全网热卖,热度高,成交增速快"
doudian-biz search "夏季透气户外布鞋" --min-search 10000 --exclude-brands
```

## 添加晓风云商品库

从当前飞书表读取关键词，查抖店商机中心的完全匹配结果，搜索次数大于 1w 后打开晓风截流页，勾选 `抖音面单`、`一件代发`、`包邮`，在前三个货源里选价格最低的添加到晓风云商品库，并回写 `晓风云库状态`：

```bash
doudian-biz xf-cloud
```

只处理单个关键词：

```bash
doudian-biz xf-cloud --keyword "夏季透气户外布鞋"
```

重跑临时失败项：

```bash
doudian-biz xf-cloud --retry-find-tab-failures
doudian-biz xf-cloud --retry-xf-empty
```

默认飞书表为当前这张商机关键词表，晓风云库批处理日志写入 `output/xf-cloud-batch-state.jsonl`。

## 抓取并写入飞书

默认写入当前使用的飞书多维表格 app token：

```bash
./doudian-biz keywords --feishu --feishu-table "抖店商机关键词100"
```

写入已有数据表：

```bash
./doudian-biz keywords --feishu --feishu-table-id tblxxxx
```

默认飞书列为 5 列：`关键词`、`搜索次数`、`搜索次数区间`、`类目路径`、`标签`。

写入完整字段：

```bash
./doudian-biz keywords --feishu --feishu-columns full
```

## 常用参数

```bash
./doudian-biz keywords \
  --tags "全网热卖,热度高,成交增速快" \
  --min-search 10000 \
  --limit 100 \
  --exclude-brands \
  --feishu
```

查看全部参数：

```bash
./doudian-biz keywords --help
```

## 说明

CLI 不手写 `a_bogus` / `msToken`，而是在浏览器页面内 `fetch` 抖店接口：

```text
POST /api/commop/business_chance_center/clue/common/real_time_list
```

接口和字段考古见 `ARCHAEOLOGY.md`。
