package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"

	"pdc-cli/browser"
	"pdc-cli/pdc"
)

// atoiOrFail parses a positive integer arg (e.g. categoryId) or exits.
func atoiOrFail(s string) int {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		fail(fmt.Errorf("%q 不是合法整数 ID", s))
	}
	return n
}

// session is the OpenBridge session name this CLI uses.
const session = "pdc-cli"

// connect returns a ready API handle (tab parked on pdc-portal.vip.com) or
// exits with a friendly message.
func connect() *pdc.API {
	client := browser.NewClient(session)
	if err := pdc.EnsureReady(client); err != nil {
		fail(err)
	}
	return pdc.New(client)
}

// printJSON writes v as indented JSON to stdout.
func printJSON(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		fail(err)
	}
}

// fail prints an actionable error to stderr and exits 1.
func fail(err error) {
	msg := err.Error()
	switch {
	case strings.Contains(msg, "daemon unreachable"):
		fmt.Fprintln(os.Stderr, "✗ OpenBridge 未运行。启动后重试：curl -s http://127.0.0.1:10088/health")
	case strings.Contains(msg, "never reached"):
		fmt.Fprintln(os.Stderr, "✗ "+msg)
		fmt.Fprintln(os.Stderr, "  请在 Chrome 里先登录 https://vis.vip.com 供应商平台。")
	default:
		fmt.Fprintln(os.Stderr, "✗ "+msg)
	}
	os.Exit(1)
}
