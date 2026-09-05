package cmd

import "github.com/spf13/cobra"

var rootCmd = &cobra.Command{
	Use:   "taobao-cli",
	Short: "淘宝搜索筛选导出 CLI（基于 OpenBridge 驱动你的真实浏览器）",
	Long: `taobao-cli 在你已登录的真实 Chrome 里(经 OpenBridge http://127.0.0.1:10088)
搜索淘宝、应用 包邮 + 48小时内发 筛选、按价格/销量过滤、翻页抓取，并导出 CSV。
标题与链接取自 zzb 插件「复制」按钮的原文。结果以 JSON 输出到 stdout，并写入 CSV 文件。`,
}

func Execute() error {
	return rootCmd.Execute()
}
