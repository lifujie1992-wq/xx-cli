package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func init() {
	var bizType string
	var vendorType int
	c := &cobra.Command{
		Use:           "upload-image <本地图片路径>...",
		Short:         "把本地图片上传到唯品图床，返回可用 URL（无需第三方图床）",
		Args:          cobra.MinimumNArgs(1),
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			urls := make([]string, 0, len(args))
			for _, p := range args {
				u, err := api.UploadImage(p, bizType, vendorType)
				if err != nil {
					fmt.Fprintf(os.Stderr, "✗ %s : %v\n", p, err)
					continue
				}
				fmt.Fprintf(os.Stderr, "✓ %s\n", p)
				urls = append(urls, u)
			}
			printJSON(urls)
		},
	}
	c.Flags().StringVar(&bizType, "biz-type", "skuSuitDetailImage", "bizType（图片用途）")
	c.Flags().IntVar(&vendorType, "vendor-type", 1, "vendorType")
	rootCmd.AddCommand(c)
}
