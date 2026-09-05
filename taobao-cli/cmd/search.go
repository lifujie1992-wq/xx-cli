package cmd

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/spf13/cobra"

	"taobao-cli/browser"
	"taobao-cli/output"
	"taobao-cli/taobao"
)

func init() {
	searchCmd := &cobra.Command{
		Use:           "search",
		Short:         "交互式搜索并导出（依次询问 关键字 / 过滤价格 / 过滤销量 / 翻页数量）",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			keyword, _ := cmd.Flags().GetString("keyword")
			minPrice, priceSet := -1.0, cmd.Flags().Changed("min-price")
			if priceSet {
				minPrice, _ = cmd.Flags().GetFloat64("min-price")
			}
			minSales, salesSet := -1, cmd.Flags().Changed("min-sales")
			if salesSet {
				minSales, _ = cmd.Flags().GetInt("min-sales")
			}
			pages, pagesSet := 0, cmd.Flags().Changed("pages")
			if pagesSet {
				pages, _ = cmd.Flags().GetInt("pages")
			}

			baoyou, baoyouSet := true, cmd.Flags().Changed("baoyou")
			if baoyouSet {
				baoyou, _ = cmd.Flags().GetBool("baoyou")
			}
			ship48, ship48Set := true, cmd.Flags().Changed("ship48")
			if ship48Set {
				ship48, _ = cmd.Flags().GetBool("ship48")
			}

			r := bufio.NewReader(os.Stdin)
			// 1) 关键字
			if strings.TrimSpace(keyword) == "" {
				keyword = prompt(r, "1) 关键字: ", func(s string) bool { return strings.TrimSpace(s) != "" }, "关键字不能为空")
			}
			// 2) 只看包邮？
			if !baoyouSet {
				baoyou = promptYesNo(r, "2) 只看包邮？(Y/n): ", true)
			}
			// 3) 只看48小时内发？
			if !ship48Set {
				ship48 = promptYesNo(r, "3) 只看48小时内发？(Y/n): ", true)
			}
			// 4) 过滤价格（最小金额）
			if !priceSet {
				minPrice = promptFloat(r, "4) 过滤价格（最小金额，单位元）: ")
			}
			// 5) 过滤销量（最小销量）
			if !salesSet {
				minSales = promptInt(r, "5) 过滤销量（最小销量/人付款）: ", 0)
			}
			// 6) 翻页数量
			if !pagesSet {
				pages = promptInt(r, "6) 翻页数量（抓取几页）: ", 1)
			}
			if pages < 1 {
				pages = 1
			}

			keyword = strings.TrimSpace(keyword)
			fmt.Fprintf(os.Stderr, "\n▶ 搜索「%s」· 包邮=%v · 48h=%v · 价格≥%g · 销量≥%d · %d 页 …\n",
				keyword, baoyou, ship48, minPrice, minSales, pages)

			client := browser.NewClient("taobao-cli")
			res, err := taobao.Run(client, keyword, baoyou, ship48, minPrice, minSales, pages, "")
			if err != nil {
				if strings.Contains(err.Error(), "daemon unreachable") {
					output.Error("daemon_unreachable", err.Error()+"  (OpenBridge 未运行？ curl -s http://127.0.0.1:10088/health)")
				} else {
					output.Error("search_failed", err.Error())
				}
				os.Exit(1)
			}
			if ship48 && !res.FilterApplied {
				fmt.Fprintln(os.Stderr, "⚠ 页面级筛选可能未完全生效（页数未降到 100 以下），但每行已按商品卡的包邮/48h角标二次校验，结果仍准确（可能件数偏少）。")
			}
			fmt.Fprintf(os.Stderr, "✔ 去重抓取 %d 件，符合条件 %d 件 → %s\n", res.Scraped, res.Kept, res.CSVPath)
			output.Success(res)
		},
	}
	searchCmd.Flags().String("keyword", "", "搜索关键字（不传则交互询问）")
	searchCmd.Flags().Bool("baoyou", true, "只看包邮（--baoyou=false 关闭；不传则交互询问）")
	searchCmd.Flags().Bool("ship48", true, "只看48小时内发（--ship48=false 关闭；不传则交互询问）")
	searchCmd.Flags().Float64("min-price", 0, "最小金额过滤（不传则交互询问）")
	searchCmd.Flags().Int("min-sales", 0, "最小销量过滤（不传则交互询问）")
	searchCmd.Flags().Int("pages", 0, "翻页数量（不传则交互询问）")
	rootCmd.AddCommand(searchCmd)
}

func promptYesNo(r *bufio.Reader, label string, def bool) bool {
	fmt.Fprint(os.Stderr, label)
	line, _ := r.ReadString('\n')
	line = strings.ToLower(strings.TrimSpace(line))
	if line == "" {
		return def
	}
	return line == "y" || line == "yes" || line == "是"
}

func prompt(r *bufio.Reader, label string, valid func(string) bool, errMsg string) string {
	for {
		fmt.Fprint(os.Stderr, label)
		line, _ := r.ReadString('\n')
		line = strings.TrimSpace(line)
		if valid(line) {
			return line
		}
		fmt.Fprintln(os.Stderr, "  ✗ "+errMsg)
	}
}

func promptFloat(r *bufio.Reader, label string) float64 {
	for {
		s := prompt(r, label, func(s string) bool { return strings.TrimSpace(s) != "" }, "请输入数字")
		v, err := strconv.ParseFloat(s, 64)
		if err == nil && v >= 0 {
			return v
		}
		fmt.Fprintln(os.Stderr, "  ✗ 请输入非负数字")
	}
}

func promptInt(r *bufio.Reader, label string, min int) int {
	for {
		s := prompt(r, label, func(s string) bool { return strings.TrimSpace(s) != "" }, "请输入整数")
		v, err := strconv.Atoi(s)
		if err == nil && v >= min {
			return v
		}
		fmt.Fprintf(os.Stderr, "  ✗ 请输入 ≥%d 的整数\n", min)
	}
}
