package cmd

import (
	"os"
	"strings"

	"github.com/spf13/cobra"

	"woda-aftersale-cli/browser"
	"woda-aftersale-cli/output"
	"woda-aftersale-cli/woda"
)

const sessionName = "woda-aftersale-cli"

func init() {
	openCmd := &cobra.Command{
		Use:           "open",
		Short:         "Open the Woda Douyin aftersale page",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			client := browser.NewClient(sessionName)
			if err := client.Navigate(woda.TargetURL); err != nil {
				output.Error("open_failed", err.Error())
				os.Exit(1)
			}
			output.Success(map[string]any{"url": woda.TargetURL})
		},
	}

	listCmd := &cobra.Command{
		Use:           "refund-only",
		Aliases:       []string{"only-refund", "list"},
		Short:         "List visible 仅退款 aftersale orders",
		Long:          "Opens https://douyins.woda.com/#/AfterSaleTrades and extracts visible 仅退款 orders from the logged-in browser page. It is read-only and will not click 同意/拒绝 actions.",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			limit, _ := cmd.Flags().GetInt("limit")
			noNavigate, _ := cmd.Flags().GetBool("no-navigate")
			exportFormat, _ := cmd.Flags().GetString("export")
			outPath, _ := cmd.Flags().GetString("out")
			client := browser.NewClient(sessionName)
			result, err := woda.ListRefundOnly(client, limit, noNavigate)
			if err != nil {
				msg := err.Error()
				switch {
				case strings.Contains(msg, "daemon unreachable"):
					output.Error("daemon_unreachable", explainDaemonUnreachable(msg))
				case strings.Contains(msg, "unexpected page url"):
					output.Error("unexpected_page", msg)
				default:
					output.Error("refund_only_failed", msg)
				}
				os.Exit(1)
			}
			if exportFormat != "" {
				path, err := exportRefundOnly(result, exportFormat, outPath)
				if err != nil {
					output.Error("export_failed", err.Error())
					os.Exit(1)
				}
				output.Success(map[string]any{
					"export_path": path,
					"format":      strings.ToLower(exportFormat),
					"count":       len(result.Orders),
					"summary":     result,
				})
				return
			}
			output.Success(result)
		},
	}
	listCmd.Flags().IntP("limit", "n", 50, "maximum visible refund-only orders to return")
	listCmd.Flags().Bool("no-navigate", false, "read the current active tab without navigating first")
	listCmd.Flags().String("export", "", "export orders to csv, json, or md")
	listCmd.Flags().String("out", "", "export output path; defaults to ~/Downloads/woda_refund_only_<timestamp>.<ext>")

	rootCmd.AddCommand(openCmd)
	rootCmd.AddCommand(listCmd)
}

func explainDaemonUnreachable(msg string) string {
	if strings.Contains(msg, "operation not permitted") {
		return msg + "; local network access is blocked in the current sandbox. Run this CLI from a normal terminal, or allow this binary to run outside the sandbox so it can POST to OpenBridge at http://127.0.0.1:10088/command."
	}
	return msg + "; check `curl -s http://127.0.0.1:10088/health` and make sure it reports ok:true with a non-empty connectedSessions array."
}
