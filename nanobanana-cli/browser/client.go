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
		http:    &http.Client{Timeout: 120 * time.Second},
	}
}

type Status struct {
	Running            bool   `json:"running"`
	ExtensionConnected bool   `json:"extension_connected"`
	ExtensionVersion   string `json:"extension_version"`
	Version            string `json:"version"`
}

func (c *Client) Status() (*Status, error) {
	health, err := c.openBridgeHealth()
	if err != nil {
		return nil, err
	}
	return &Status{
		Running:            health.OK,
		ExtensionConnected: len(health.ConnectedSessions) > 0,
	}, nil
}

func (c *Client) Call(action string, args map[string]any) (json.RawMessage, error) {
	return c.callOpenBridge(action, args)
}

func (c *Client) Navigate(url string, newTab bool) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": newTab})
	return err
}

// Evaluate runs JS and returns the wrapped {type, value} payload.
// Caller typically parses .value into the expected shape.
func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	return c.Call("evaluate", map[string]any{"code": code})
}

// EvaluateValue runs JS and unmarshals the returned expression's value into v.
// The daemon wraps evaluate results as {"type": "...", "value": <json>}.
func (c *Client) EvaluateValue(code string, v any) error {
	raw, err := c.Evaluate(code)
	if err != nil {
		return err
	}
	var wrap struct {
		Type  string          `json:"type"`
		Value json.RawMessage `json:"value"`
	}
	if err := json.Unmarshal(raw, &wrap); err != nil {
		return fmt.Errorf("parse evaluate wrapper: %w", err)
	}
	if len(wrap.Value) == 0 {
		return fmt.Errorf("evaluate returned no value (type=%s)", wrap.Type)
	}
	if err := json.Unmarshal(wrap.Value, v); err != nil {
		return fmt.Errorf("parse evaluate value: %w (raw=%s)", err, string(wrap.Value))
	}
	return nil
}
