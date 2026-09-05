package cmd

import (
	"github.com/spf13/cobra"
)

func init() {
	var vendorType int
	get := &cobra.Command{
		Use:           "get <vendorProductId>",
		Short:         "读取一个完整商品（创建/编辑提交体的样板，~47 字段）",
		Args:          cobra.ExactArgs(1),
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			p, err := api.Product(args[0], vendorType)
			if err != nil {
				fail(err)
			}
			printJSON(p)
		},
	}
	get.Flags().IntVar(&vendorType, "vendor-type", 1, "vendorType（接口必填的“是否买断”判定，默认 1）")
	rootCmd.AddCommand(get)

	var configVendorType int
	cfg := &cobra.Command{
		Use:           "config <categoryId>",
		Short:         "某叶子类目的配置开关（是否需尺码表/是否美妆/大件等）",
		Args:          cobra.ExactArgs(1),
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			id := atoiOrFail(args[0])
			conf, err := api.CategoryConfig(id)
			if err != nil {
				fail(err)
			}
			printJSON(conf)
		},
	}
	cfg.Flags().IntVar(&configVendorType, "vendor-type", 1, "vendorType")
	rootCmd.AddCommand(cfg)
}
