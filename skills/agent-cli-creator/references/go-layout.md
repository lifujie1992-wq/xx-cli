# Go CLI Layout Reference

Use an independent Go module for each CLI.

## Initialize

```bash
mkdir {platform}-cli && cd {platform}-cli
go mod init {platform}-cli
go get github.com/spf13/cobra
```

## Layout

```text
{platform}-cli/
├── go.mod
├── main.go
├── browser/
│   ├── client.go
│   ├── openbridge.go
│   └── openbridge_test.go
├── output/output.go
├── {platform}/
│   ├── login.go
│   └── {feature}.go
└── cmd/root.go
```

## Browser client

Do not recreate the legacy `{"action","session","args"}` protocol. Copy the current known-good adapter from this repository:

```bash
cp ../google-cli/browser/client.go browser/client.go
cp ../google-cli/browser/openbridge.go browser/openbridge.go
cp ../google-cli/browser/openbridge_test.go browser/openbridge_test.go
```

Then change only package-specific comments or convenience methods. Keep these behaviors:

- default URL `http://127.0.0.1:10088`;
- `OPENBRIDGE_URL` override for auto-shifted ports;
- `/health` for daemon/extension readiness;
- `/command` body `{"toolName":"browser_*","args":{...}}`;
- logical CLI session stored in `args.sessionId`, never top-level `sessionId`;
- existing-tab adoption through `browser_find_tab` + `browser_select_tab`;
- async `browser_evaluate` compatibility polling;
- decoding `{error:{code,message}}` even when OpenBridge returns HTTP 400.

Typical business code remains simple:

```go
client := browser.NewClient("{platform}-cli")
if err := client.Navigate("https://example.com"); err != nil {
    return err
}

var result struct {
    Items []Item `json:"items"`
}
err := client.EvaluateJSON(`(async () => {
  const response = await fetch("/api/items", {credentials: "include"});
  return JSON.stringify(await response.json());
})()`, &result)
```

OpenBridge's `browser_evaluate` tool must be enabled in the Chrome extension popup.

## Output contract

```go
package output

import (
    "encoding/json"
    "fmt"
    "os"
)

func Success(data any) {
    printJSON(map[string]any{"ok": true, "data": data})
}

func Error(code, message string) {
    printJSON(map[string]any{"ok": false, "error": map[string]any{
        "code": code, "message": message,
    }})
}

func printJSON(value any) {
    encoder := json.NewEncoder(os.Stdout)
    encoder.SetEscapeHTML(false)
    encoder.SetIndent("", "  ")
    if err := encoder.Encode(value); err != nil {
        fmt.Fprintf(os.Stderr, "output error: %v\n", err)
    }
}
```

## Verify

```bash
gofmt -w .
go test ./...
go vet ./...
go build -o {platform}-cli .
./{platform}-cli --help
```
