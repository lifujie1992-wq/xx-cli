package cmd

import "github.com/spf13/cobra"

var rootCmd = &cobra.Command{
	Use:   "woda-aftersale-cli",
	Short: "Woda Douyin aftersale CLI backed by the OpenBridge browser daemon",
	Long: `woda-aftersale-cli drives the logged-in Woda Douyin aftersale page inside
Chrome via OpenBridge (http://127.0.0.1:10088). All commands emit JSON on
stdout: {"ok":true,"data":...} on success, {"ok":false,"error":{...}} on failure.
Every command exits non-zero on failure.`,
}

func Execute() error {
	return rootCmd.Execute()
}
