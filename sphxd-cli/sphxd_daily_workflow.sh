#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage:
  ./sphxd_daily_workflow.sh status
      查看今天已经有效复制多少个、飞书剩余未复制样本、最近批次。

  ./sphxd_daily_workflow.sh run
      只跑一批：切到飞书页面可视化复制最多 50 个未复制链接 ->
      切到智能店长链接复制页粘贴并抓取商品 ->
      设置类目 -> 清标题 -> 清描述图。不会点击「开始搬家」。

  ./sphxd_daily_workflow.sh run --confirm-move
      完整日流程：按「抓取成功 N 个」累计有效复制数，最多 150 个/天。
      每批清洗后点击「下一步：开始搬家」，然后继续下一批。
      飞书未复制链接为空时，自动执行：
      ~/x-cli/ali1688-cli/phone_case_workflow.sh next 1 8

Common options:
  --daily-limit N       默认 150
  --batch-size N        默认 50
  --no-visual-copy      不切飞书页面演示复制，直接后台填入智能店长
  --refill-pages N      默认 1
  --refill-delay SEC    默认 8

Files:
  Engine: ./sphxd_daily_workflow.py
  Daily state: ./data/sphxd_daily_state.json
  Current batch: ./data/feishu_current_batch.json
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status)
    python3 ./sphxd_daily_workflow.py status
    ;;
  run)
    python3 ./sphxd_daily_workflow.py run "$@"
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
