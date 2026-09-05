package browser

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

const DefaultDaemonURL = "http://127.0.0.1:10088"

type Client struct {
	baseURL string
	session string
	http    *http.Client
}

func NewClient(session string) *Client {
	return &Client{
		baseURL: openBridgeURL(),
		session: session,
		http:    &http.Client{Timeout: 90 * time.Second},
	}
}

func (c *Client) Call(action string, args map[string]any) (json.RawMessage, error) {
	return c.callOpenBridge(action, args)
}

func (c *Client) Navigate(url string) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": true})
	return err
}

// Evaluate runs `code` as a top-level JS expression in the active tab.
// The daemon wraps the result as {"type": "...", "value": ...}. For structured
// data, prefer EvaluateJSON, which unwraps the envelope for you.
func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	return c.Call("evaluate", map[string]any{"code": code})
}

// EvaluateJSON runs `code` and decodes the stringified JSON it returns into v.
// `code` must end with a `JSON.stringify(...)` expression; the daemon reports
// that as {"type":"string","value":"<stringified JSON>"}.
func (c *Client) EvaluateJSON(code string, v any) error {
	raw, err := c.Evaluate(code)
	if err != nil {
		return err
	}
	var env struct {
		Type  string `json:"type"`
		Value string `json:"value"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return fmt.Errorf("decode evaluate envelope: %w", err)
	}
	if env.Type != "string" {
		return fmt.Errorf("expected evaluate type=string, got %q — did the code end with JSON.stringify(...)?", env.Type)
	}
	if err := json.Unmarshal([]byte(env.Value), v); err != nil {
		return fmt.Errorf("decode evaluate value: %w", err)
	}
	return nil
}
