#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage:
  ./sphxd_feishu_grab.sh status
      查看飞书未复制链接样本和最近批次，不操作页面。

  ./sphxd_feishu_grab.sh grab [limit]
      从飞书取 limit 条「是否复制过=false」链接，切到飞书页面可视化复制，
      再切到智能店长链接复制页粘贴，
      点击「开始批量抓取商品」，完成后回写飞书为 true。
      默认 limit=50。

  ./sphxd_feishu_grab.sh category
      在当前抓取成功后的商品列表页，批量设置小店分类为
      手机通讯>手机配件>手机壳/保护套，并应用所有。

  ./sphxd_feishu_grab.sh titles
      逐个检查当前批次商品标题，删除：
      工厂、代发、批发、跨境、外贸。

  ./sphxd_feishu_grab.sh descimg
      逐个检查当前批次商品描述图，OCR 命中工厂、1688、厂家、
      代发、批发、跨境、外贸等词的图片会删除。

Files:
  Engine: ./sphxd_feishu_grab.py
  Current batch: ./data/feishu_current_batch.json
  Batch ledger: ./data/feishu_sphxd_batches.json
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status)
    python3 ./sphxd_feishu_grab.py status
    ;;
  grab)
    limit="${1:-50}"
    python3 ./sphxd_feishu_grab.py grab --limit "$limit"
    ;;
  category)
    python3 ./sphxd_feishu_grab.py category
    ;;
  titles)
    python3 ./sphxd_feishu_grab.py titles
    ;;
  descimg)
    python3 ./sphxd_feishu_grab.py descimg
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
