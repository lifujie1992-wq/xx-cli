package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func init() {
	rootCmd.AddCommand(&cobra.Command{
		Use:           "login-status",
		Short:         "确认登录态并打印当前商家账号",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			u, err := api.CurrentUser()
			if err != nil || !u.LoggedIn() {
				fmt.Fprintln(os.Stderr, "✗ 未登录或会话失效：", err)
				os.Exit(1)
			}
			fmt.Fprintf(os.Stderr, "✓ 已登录：%s (vendorCode=%s)\n", u.User, u.VendorCode)
			printJSON(u)
		},
	})
}
