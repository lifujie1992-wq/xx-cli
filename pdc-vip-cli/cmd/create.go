package cmd

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func init() {
	var file string
	var commit bool
	var confirmTips bool
	var vendorType int

	c := &cobra.Command{
		Use:   "create -f <productVo.json>",
		Short: "提交一份 productVo 创建/保存商品草稿（默认 dry-run，仅做非破坏 SKU 预检）",
		Long: `读取一份完整的 productVo JSON（结构见 你的 productVo.json
与 ARCHAEOLOGY.md），提交到 POST /product/saveProductV2。

默认 dry-run：只跑非破坏的 SKU 预检(/product/saveProduct?editPreCheck)并打印将要
发送的摘要，不写库。确认无误后加 --commit 才真正保存草稿。

注意：sn / colourGSN / barCode 是商家自定义唯一码，新品必须用未被占用的新值，
否则会与已有商品冲突。`,
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			if file == "" {
				fail(fmt.Errorf("必须用 -f 指定 productVo JSON 文件"))
			}
			data, err := os.ReadFile(file)
			if err != nil {
				fail(fmt.Errorf("读取 %s: %w", file, err))
			}
			var vo map[string]any
			if err := json.Unmarshal(data, &vo); err != nil {
				fail(fmt.Errorf("%s 不是合法 JSON 对象: %w", file, err))
			}

			// quick sanity summary
			summarize(vo)

			api := connect()

			// --- non-destructive SKU pre-check ---
			sku, ok := vo["itemSkuAttr"]
			if !ok {
				fail(fmt.Errorf("productVo 缺少 itemSkuAttr（销售属性/SKU）"))
			}
			passed, msg, err := api.SkuPreCheck(sku, vendorType)
			if err != nil {
				fail(fmt.Errorf("SKU 预检请求失败: %w", err))
			}
			if passed {
				fmt.Fprintln(os.Stderr, "✓ SKU 预检通过")
			} else {
				fmt.Fprintf(os.Stderr, "✗ SKU 预检未通过：%s\n", msg)
			}

			if !commit {
				fmt.Fprintln(os.Stderr, "\n— DRY RUN：未写库。确认无误后加 --commit 才真正保存草稿。")
				return
			}
			if !passed {
				fail(fmt.Errorf("SKU 预检未通过，已中止 --commit"))
			}

			// --- real write ---
			fmt.Fprintln(os.Stderr, "▶ 正在保存草稿 (POST saveProductV2)…")
			res, err := api.SaveProduct(data, vendorType, confirmTips)
			if err != nil {
				fail(fmt.Errorf("保存失败: %w", err))
			}
			if res.Result {
				fmt.Fprintln(os.Stderr, "✓ 已保存")
			} else if res.NeedsConfirm() {
				fmt.Fprintln(os.Stderr, "⚠ 后端返回内容警告(checkResultCode 501)，未落库：")
				for _, w := range res.Warnings() {
					fmt.Fprintln(os.Stderr, "   • "+w)
				}
				if !confirmTips {
					fmt.Fprintln(os.Stderr, "\n  处理完上面的问题，或加 --confirm-tips 确认忽略警告后强制保存。")
				}
			} else {
				fmt.Fprintf(os.Stderr, "✗ 保存未成功：%s\n", trunc(res.Raw, 300))
			}
			fmt.Println(res.Raw)
		},
	}
	c.Flags().StringVarP(&file, "file", "f", "", "productVo JSON 文件路径")
	c.Flags().BoolVar(&commit, "commit", false, "真正写库（默认仅 dry-run）")
	c.Flags().BoolVar(&confirmTips, "confirm-tips", false, "确认忽略 501 内容警告强制保存（等同 UI「已知悉，确定修改」）")
	c.Flags().IntVar(&vendorType, "vendor-type", 1, "vendorType（是否买断判定，默认 1）")
	rootCmd.AddCommand(c)
}

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func summarize(vo map[string]any) {
	get := func(k string) string {
		if v, ok := vo[k]; ok {
			return fmt.Sprintf("%v", v)
		}
		return "<空>"
	}
	n := func(k string) int {
		if v, ok := vo[k].([]any); ok {
			return len(v)
		}
		return 0
	}
	fmt.Fprintln(os.Stderr, "── 将提交的商品 ──")
	fmt.Fprintf(os.Stderr, "  标题   : %s\n", get("title"))
	fmt.Fprintf(os.Stderr, "  款号   : %s\n", get("sn"))
	fmt.Fprintf(os.Stderr, "  类目   : %s   品牌: %s\n", get("categoryId"), get("brandId"))
	fmt.Fprintf(os.Stderr, "  vpId   : %s（空=新建）\n", get("vendorProductId"))
	fmt.Fprintf(os.Stderr, "  属性   : specProps %d 项\n", n("specProps"))
	fmt.Fprintf(os.Stderr, "  SKU    : itemSkuAttr %d 色 · 图片 %d/%d\n",
		n("itemSkuAttr"), n("itemImages"), n("squareImages"))
	fmt.Fprintln(os.Stderr, "──────────────────")
}
