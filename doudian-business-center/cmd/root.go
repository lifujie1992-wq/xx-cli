package cmd

import "github.com/spf13/cobra"

var rootCmd = &cobra.Command{
	Use:   "doudian-biz",
	Short: "抖店商机中心 CLI（基于 OpenBridge + 飞书 CLI）",
	Long: `doudian-biz 使用真实 Chrome 登录态访问抖店商机中心接口，支持连续翻页抓取关键词、
按搜索次数过滤、剔除明显品牌词、导出 JSON/TSV/CSV，并可通过 feishu-cli 写入飞书多维表格。

默认抓取「全网热卖、热度高、成交增速快」三个推荐理由标签，搜索次数 > 10000，数量 100。`,
}

func Execute() error { return rootCmd.Execute() }
