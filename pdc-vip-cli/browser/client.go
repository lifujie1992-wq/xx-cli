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

// Navigate loads url in the active tab. Pass newTab=true to open a fresh tab
// (use on the first navigation); newTab=false reloads the current tab (use for
// filter-reset retries so tabs don't pile up).
func (c *Client) Navigate(url string, newTab bool) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": newTab})
	return err
}

// Evaluate runs `code` as a top-level JS expression in the active tab.
func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	return c.Call("evaluate", map[string]any{"code": code})
}

// EvaluateString runs `code` (which must return a JS string) and returns it.
func (c *Client) EvaluateString(code string) (string, error) {
	raw, err := c.Evaluate(code)
	if err != nil {
		return "", err
	}
	var env struct {
		Type  string `json:"type"`
		Value string `json:"value"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return "", fmt.Errorf("decode evaluate envelope: %w", err)
	}
	return env.Value, nil
}

// EvaluateJSON runs `code` (which must end with JSON.stringify(...)) and decodes
// the stringified JSON it returns into v.
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
