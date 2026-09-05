package cmd

import (
	"os"

	"github.com/spf13/cobra"

	"aldspdd-cli/aldspdd"
	"aldspdd-cli/browser"
	"aldspdd-cli/output"
)

const session = "aldspdd"

var rootCmd = &cobra.Command{
	Use:   "aldspdd-cli",
	Short: "阿奇索·拼多多自动发货 商品页自动化 CLI（接管已登录的 Chrome 标签页）",
	Long:  "通过 OpenBridge 接管你已打开并登录的 aldspdd.agiso.com 商品页，无需 API key，复用真实登录态。",
}

func Execute() error {
	return rootCmd.Execute()
}

func init() {
	rootCmd.AddCommand(loginStatusCmd())
	rootCmd.AddCommand(checkSupplyCmd())
	rootCmd.AddCommand(checkNoCmd())
	rootCmd.AddCommand(buildMapCmd())
	rootCmd.AddCommand(goodsCmd())
}

func loginStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "login-status",
		Short: "检查登录态（TOKEN 是否有效、商品列表能否访问）",
		Run: func(cmd *cobra.Command, args []string) {
			c := browser.NewClient(session)
			st, err := aldspdd.CheckLogin(c)
			if err != nil {
				output.Error("login_check_error", err.Error())
				os.Exit(1)
			}
			if !st.LoggedIn {
				output.Error("not_logged_in", st.Note)
				os.Exit(1)
			}
			output.Success(st)
		},
	}
}

func checkSupplyCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "check-supply",
		Short: "扫描在售商品，找出绑定的货源编号已失效（搜不到）的商品",
		Long:  "对每个在售商品的每个 SKU，取其绑定的货源编号，调用 Agiso 货源搜索接口校验；\n搜不到该编号即视为失效（货源被下架/删除），需要你处理。",
		Run: func(cmd *cobra.Command, args []string) {
			limit, _ := cmd.Flags().GetInt("limit")
			all, _ := cmd.Flags().GetBool("all")
			scope, _ := cmd.Flags().GetString("scope")
			c := browser.NewClient(session)
			res, err := aldspdd.CheckSupply(c, scope, limit, all)
			if err != nil {
				output.Error("check_supply_error", err.Error())
				os.Exit(1)
			}
			output.Success(res)
		},
	}
	cmd.Flags().Int("limit", 0, "只扫描前 N 个商品（0 = 全部）")
	cmd.Flags().Bool("all", false, "输出每个货源编号的全部结果（成功/失败/跳过），不只是失效的")
	cmd.Flags().String("scope", "onsale", "扫描范围：onsale=出售中 / offsale=已下架 / configured=已设置发货")
	return cmd
}

func checkNoCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "check-no <货源编号>",
		Short: "查单个货源编号是否还在（搜不到=货源已失效）",
		Long:  "调用 Agiso 货源搜索接口查一个货源编号。默认遍历全部货源账号；\n任一账号下精确命中即视为「货源在」，全部搜不到即「失效」。",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			acc, _ := cmd.Flags().GetInt("acc")
			locate, _ := cmd.Flags().GetBool("locate")
			refresh, _ := cmd.Flags().GetBool("refresh")
			scope, _ := cmd.Flags().GetString("scope")
			c := browser.NewClient(session)
			res, err := aldspdd.CheckNo(c, args[0], acc)
			if err != nil {
				output.Error("check_no_error", err.Error())
				os.Exit(1)
			}
			if locate {
				if err := res.Locate(c, scope, refresh); err != nil {
					output.Error("locate_error", err.Error())
					os.Exit(1)
				}
			}
			output.Success(res)
		},
	}
	cmd.Flags().Int("acc", 0, "只查指定货源账号 idNo（0 = 遍历全部账号）")
	cmd.Flags().Bool("locate", false, "反查该编号被你方哪些商品/SkuId 使用（用本地映射缓存）")
	cmd.Flags().Bool("refresh", false, "配合 --locate：强制重建映射缓存")
	cmd.Flags().String("scope", "onsale", "建映射的范围：onsale=出售中 / offsale=已下架 / configured=已设置")
	return cmd
}

func buildMapCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "build-map",
		Short: "扫描商品建立「货源编号 → 你方商品/SkuId」反查映射并缓存（供 check-no --locate 用）",
		Run: func(cmd *cobra.Command, args []string) {
			scope, _ := cmd.Flags().GetString("scope")
			c := browser.NewClient(session)
			um, err := aldspdd.BuildUsageMap(c, scope)
			if err != nil {
				output.Error("build_map_error", err.Error())
				os.Exit(1)
			}
			output.Success(map[string]any{"builtAt": um.BuiltAt, "scope": um.Scope, "goods": um.Goods, "codes": len(um.Map)})
		},
	}
	cmd.Flags().String("scope", "onsale", "范围：onsale=出售中 / offsale=已下架 / configured=已设置")
	return cmd
}

func goodsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "goods",
		Short: "列出商品（默认出售中；--scope 切换 onsale/offsale/configured）",
		Run: func(cmd *cobra.Command, args []string) {
			scope, _ := cmd.Flags().GetString("scope")
			c := browser.NewClient(session)
			if err := c.FindTab("aldspdd.agiso.com", true); err != nil {
				_ = c.Navigate(aldspdd.GoodsURL)
			}
			list, err := aldspdd.LoadGoods(c, scope)
			if err != nil {
				output.Error("goods_error", err.Error())
				os.Exit(1)
			}
			output.Success(map[string]any{"scope": scope, "count": len(list), "items": list})
		},
	}
	cmd.Flags().String("scope", "onsale", "商品范围：onsale=出售中 / offsale=已下架 / configured=已设置发货")
	return cmd
}
